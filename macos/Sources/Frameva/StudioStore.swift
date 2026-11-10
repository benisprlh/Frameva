import Foundation
import SwiftUI
import AppKit
import AVKit
import UniformTypeIdentifiers
import FramevaCore

@MainActor
final class StudioStore: ObservableObject {
    let worker = WorkerController()
    let capture = CaptureController()
    @Published var projects: [Project] = []
    @Published var selectedProjectID: String?
    @Published var shots: [Shot] = []
    @Published var assets: [Asset] = []
    @Published var jobs: [Job] = []
    @Published var source: JSONValue?
    @Published var coverage: JSONValue?
    @Published var flows: [JSONValue] = []
    @Published var selectedShotID: String?
    @Published var draft = ShotDraft()
    @Published var draftIsDirty = false
    @Published var selectedPage = StudioPage.timeline
    @Published var isBusy = false
    @Published var activity = ""
    @Published var errorMessage: String?
    @Published var isConnected = false
    @Published var previewPlayer: AVPlayer?
    @Published var previewImage: NSImage?
    @Published var previewLabel = "Select a scene or recording"
    @Published var previewAssetID: String?
    @Published var showCreateProject = false
    @Published var flowJSON = StudioStore.defaultFlow
    @Published var selectedFlowID: String?
    @Published var browserInstalling = false
    private var captureImportPending = false
    private var captureProjectID: String?
    private var previewRequest = UUID()
    private var snapshotRequest = UUID()
    private var pollingTask: Task<Void, Never>?
    private var lastMetadataRefresh = Date.distantPast
    private var cache: [String: URL] = [:]

    var project: Project? { projects.first { $0.id == selectedProjectID } }
    var selectedShot: Shot? { shots.first { $0.id == selectedShotID } }
    var videoAssets: [Asset] { assets.filter { $0.kind == "video" } }
    var imageAssets: [Asset] { assets.filter { $0.kind == "image" } }
    var audioAssets: [Asset] { assets.filter { $0.kind == "audio" } }
    var timelineDuration: Double { shots.reduce(0) { $0 + $1.draft.duration } }
    var activeJobs: [Job] { jobs.filter(\.isActive) }
    var api: APIClient { get throws { guard let client = worker.client else { throw StudioError("The local worker is not connected.") }; return client } }

    init() {
        capture.onFinished = { [weak self] url in
            guard let self, let projectID = self.captureProjectID else { return }
            self.captureImportPending = true
            Task { @MainActor in
                while self.isBusy { try? await Task.sleep(nanoseconds: 100_000_000) }
                self.isBusy = true; self.activity = "Importing finalized recording…"
                defer { self.isBusy = false; self.captureImportPending = false; self.activity = "" }
                do {
                    let asset = try await self.api.uploadAsset(url, projectID: projectID)
                    self.capture.markImported(url)
                    if self.selectedProjectID == projectID {
                        await self.refresh()
                        try await self.addRecordingScene(asset)
                        self.selectedPage = .timeline
                    }
                } catch { self.errorMessage = error.localizedDescription }
            }
        }
        capture.onError = { [weak self] error in self?.errorMessage = error }
    }
    func start() async {
        do {
            try await worker.start(); isConnected = true
            projects = try await api.get("/api/projects")
            let remembered = UserDefaults.standard.string(forKey: "lastNativeProject")
            if let selected = projects.first(where: { $0.id == remembered }) ?? projects.first { await selectProject(selected.id) }
            startPolling()
        } catch { errorMessage = error.localizedDescription; isConnected = false }
    }
    func perform(_ label: String, operation: @escaping @MainActor () async throws -> Void) {
        guard !isBusy else { return }
        isBusy = true; activity = label
        Task {
            defer { isBusy = false; activity = "" }
            do { try await operation() } catch { errorMessage = error.localizedDescription }
        }
    }
    func confirmDiscard() -> Bool {
        guard draftIsDirty else { return true }
        let alert = NSAlert(); alert.messageText = "Discard unsaved scene changes?"
        alert.informativeText = "Save the current scene before switching, or discard the local edits."
        alert.addButton(withTitle: "Keep editing"); alert.addButton(withTitle: "Discard changes")
        return alert.runModal() == .alertSecondButtonReturn
    }
    func selectProject(_ id: String) async {
        guard !isBusy else { return }
        guard id != selectedProjectID || shots.isEmpty else { return }
        guard confirmDiscard() else { return }
        previewRequest = UUID()
        selectedProjectID = id; selectedShotID = nil; draftIsDirty = false
        shots = []; assets = []; jobs = []; source = nil; coverage = nil; flows = []; selectedFlowID = nil
        previewPlayer?.pause(); previewPlayer = nil; previewImage = nil; previewAssetID = nil
        UserDefaults.standard.set(id, forKey: "lastNativeProject")
        await refresh(forceSelection: true)
    }
    func refresh(forceSelection: Bool = false) async {
        guard isConnected, let id = selectedProjectID else { return }
        let requestID = UUID(); snapshotRequest = requestID
        do {
            let client = try api
            async let fetchedShots: [Shot] = client.get("/api/projects/\(id)/shots")
            async let fetchedAssets: [Asset] = client.get("/api/assets?project_id=\(id)")
            async let fetchedJobs: [Job] = client.get("/api/jobs?project_id=\(id)")
            async let fetchedFlows: [JSONValue] = client.get("/api/projects/\(id)/flows")
            let values = try await (fetchedShots, fetchedAssets, fetchedJobs, fetchedFlows)
            let fetchedSource = try? await client.get("/api/projects/\(id)/source", as: JSONValue.self)
            let fetchedCoverage = try? await client.get("/api/projects/\(id)/coverage", as: JSONValue.self)
            guard selectedProjectID == id, snapshotRequest == requestID else { return }
            shots = values.0.sorted { $0.position < $1.position }; assets = values.1; jobs = values.2.sorted(by: Job.newestFirst); flows = values.3
            source = fetchedSource; coverage = fetchedCoverage
            if !draftIsDirty {
                if selectedShotID == nil || !shots.contains(where: { $0.id == selectedShotID }) { selectedShotID = shots.first?.id }
                if let shot = selectedShot { draft = shot.draft; await refreshPreview(for: shot) }
            }
        } catch { if forceSelection { errorMessage = error.localizedDescription } }
    }
    private func startPolling() {
        pollingTask?.cancel()
        pollingTask = Task { [weak self] in
            while !Task.isCancelled {
                do { try await Task.sleep(nanoseconds: 2_000_000_000) } catch { return }
                guard let self, !self.isBusy, self.isConnected else { continue }
                if Date().timeIntervalSince(self.lastMetadataRefresh) > 6 {
                    self.lastMetadataRefresh = Date()
                    if let projects: [Project] = try? await self.api.get("/api/projects") { self.projects = projects }
                }
                await self.refresh()
            }
        }
    }
    func createProject(name: String, description: String) async throws {
        guard confirmDiscard() else { return }
        let p: Project = try await api.send("/api/projects", body: ["name": name, "description": description])
        projects.insert(p, at: 0); showCreateProject = false
        selectedProjectID = p.id; selectedShotID = nil; draftIsDirty = false; previewRequest = UUID(); previewPlayer?.pause(); previewPlayer = nil; previewImage = nil; previewAssetID = nil
        shots = []; assets = []; jobs = []; source = nil; coverage = nil; flows = []; selectedFlowID = nil; draft = ShotDraft()
        UserDefaults.standard.set(p.id, forKey: "lastNativeProject"); await refresh(forceSelection: true)
    }
    func renameProject(name: String, description: String) async throws {
        guard let id = selectedProjectID else { return }
        let updated: Project = try await api.send("/api/projects/\(id)", method: "PATCH", body: ["name": name, "description": description])
        projects = projects.map { $0.id == id ? updated : $0 }
    }
    func deleteProject() async throws {
        guard let project else { return }
        let alert = NSAlert(); alert.messageText = "Delete \(project.name)?"
        alert.informativeText = "Its storyboard, media, and render history will be deleted. This cannot be undone."
        alert.addButton(withTitle: "Cancel"); alert.addButton(withTitle: "Delete project")
        guard alert.runModal() == .alertSecondButtonReturn else { return }
        _ = try await api.action("/api/projects/\(project.id)", method: "DELETE")
        previewRequest = UUID(); projects.removeAll { $0.id == project.id }; selectedProjectID = nil; selectedShotID = nil
        shots = []; assets = []; jobs = []; source = nil; coverage = nil; flows = []; selectedFlowID = nil; draftIsDirty = false; previewPlayer?.pause(); previewPlayer = nil; previewImage = nil; previewAssetID = nil; draft = ShotDraft()
        if let next = projects.first { selectedProjectID = next.id; await refresh(forceSelection: true) }
    }
    func selectShot(_ shot: Shot) {
        guard !isBusy, shot.id != selectedShotID else { return }
        guard confirmDiscard() else { return }
        previewRequest = UUID(); selectedShotID = shot.id; draft = shot.draft; draftIsDirty = false
        Task { await refreshPreview(for: shot, force: true) }
    }
    func editDraft<Value>(_ keyPath: WritableKeyPath<ShotDraft, Value>, value: Value) {
        draft[keyPath: keyPath] = value; draftIsDirty = true
    }
    func saveShot() async throws {
        guard let id = selectedShotID else { return }
        let recording = assets.first { $0.id == draft.videoAssetId }
        try draft.validate(recordingDuration: recording?.videoDuration ?? recording?.duration)
        let updated: Shot = try await api.send("/api/shots/\(id)", method: "PATCH", body: draft)
        shots = shots.map { $0.id == id ? updated : $0 }; draft = updated.draft; draftIsDirty = false
        await refreshPreview(for: updated, force: true)
    }
    func addTitleScene() async throws {
        guard let id = selectedProjectID else { return }
        if draftIsDirty { try await saveShot() }
        var value = ShotDraft(); value.name = "Title \(shots.count + 1)"; value.headline = "Introducing \(project?.name ?? "your product")"; value.layout = "title"
        let shot: Shot = try await api.send("/api/projects/\(id)/shots", body: value)
        shots.append(shot); selectedShotID = shot.id; draft = shot.draft; draftIsDirty = false
        await refreshPreview(for: shot, force: true)
    }
    func addRecordingScene(_ asset: Asset) async throws {
        guard let id = selectedProjectID, asset.kind == "video" else { return }
        if draftIsDirty { try await saveShot() }
        var value = ShotDraft(); value.provider = "recording"; value.videoAssetId = asset.id
        value.name = "Demo \(shots.count + 1)"; value.headline = String(asset.name.replacingOccurrences(of: ".mp4", with: "").prefix(120))
        value.duration = min(120, max(1, (asset.videoDuration ?? asset.duration ?? 6) - 0.05)); value.camera = "static"
        let shot: Shot = try await api.send("/api/projects/\(id)/shots", body: value)
        shots.append(shot); selectedShotID = shot.id; draft = shot.draft; draftIsDirty = false
        await refreshPreview(for: shot, force: true)
    }
    func deleteShot() async throws {
        guard let id = selectedShotID else { return }
        _ = try await api.action("/api/shots/\(id)", method: "DELETE")
        draftIsDirty = false; selectedShotID = nil; await refresh(forceSelection: true)
    }
    func moveShot(_ offset: Int) async throws {
        guard let index = shots.firstIndex(where: { $0.id == selectedShotID }), shots.indices.contains(index + offset), let projectID = selectedProjectID else { return }
        var ids = shots.map(\.id); ids.swapAt(index, index + offset)
        _ = try await api.send("/api/projects/\(projectID)/shots/order", method: "PUT", body: ["shot_ids": ids], as: JSONValue.self)
        await refresh()
    }
    func renderSelected() async throws {
        try await saveShot()
        guard let id = selectedShotID else { return }
        _ = try await api.send("/api/jobs", body: ["shot_id": id], as: Job.self)
        await refresh()
    }
    func renderAll() async throws {
        if draftIsDirty { try await saveShot() }
        guard let id = selectedProjectID else { return }
        _ = try await api.action("/api/projects/\(id)/generate"); selectedPage = .jobs; await refresh()
    }
    func modifyJob(_ job: Job, action: String) async throws {
        _ = try await api.action("/api/jobs/\(job.id)/\(action)"); await refresh()
    }
    func sourceImport() async throws {
        guard let projectID = selectedProjectID else { return }
        let panel = NSOpenPanel(); panel.allowedContentTypes = [.zip]; panel.allowsMultipleSelection = false; panel.canChooseDirectories = false
        panel.message = "Choose a source ZIP. Frameva reads evidence; it does not execute this code."
        guard panel.runModal() == .OK, let url = panel.url else { return }
        source = try await api.uploadSource(url, projectID: projectID)
        selectedPage = .source; await refresh()
    }
    func draftLaunch(aspect: String, replaceExisting: Bool) async throws {
        guard let id = selectedProjectID else { return }
        if draftIsDirty { try await saveShot() }
        _ = try await api.send("/api/projects/\(id)/launch-plan", body: ["aspect": JSONValue.string(aspect), "replace_existing": .bool(replaceExisting)], as: JSONValue.self)
        selectedPage = .timeline; await refresh(forceSelection: true)
    }
    func importMedia() async throws {
        guard let projectID = selectedProjectID else { return }
        let panel = NSOpenPanel(); panel.allowsMultipleSelection = true; panel.canChooseDirectories = false
        panel.allowedContentTypes = [.movie, .image, .audio]
        panel.message = "Import real app recordings, screenshots, or music you have permission to use."
        guard panel.runModal() == .OK else { return }
        for url in panel.urls { _ = try await api.uploadAsset(url, projectID: projectID) }
        await refresh(); selectedPage = .media
    }
    func startCapture() async {
        guard !isBusy, !capture.phase.isBusy, !captureImportPending else { return }
        guard let id = selectedProjectID else { errorMessage = "Create or select a project before recording."; return }
        captureProjectID = id; await capture.chooseWindow()
    }
    func retryCaptureImport() async throws {
        guard let url = capture.retainedRecording, capture.phase == .finished, let id = captureProjectID else { return }
        let asset = try await api.uploadAsset(url, projectID: id); capture.markImported(url)
        await refresh(); if id == selectedProjectID { try await addRecordingScene(asset) }
    }
    func freshOutput(for shot: Shot) -> Asset? {
        guard let job = jobs.filter({ $0.type == "generate" && $0.shotId == shot.id && $0.status == "succeeded" }).sorted(by: Job.newestFirst).first,
              let snapshot = job.params["shot"], let data = try? JSONEncoder().encode(snapshot) else { return nil }
        let decoder = JSONDecoder(); decoder.keyDecodingStrategy = .convertFromSnakeCase
        guard let rendered = try? decoder.decode(ShotDraft.self, from: data), rendered == shot.draft else { return nil }
        return assets.first { $0.id == job.assetId }
    }
    func refreshPreview(for shot: Shot, force: Bool = false) async {
        if let output = freshOutput(for: shot) { await preview(output, label: "Rendered scene", force: force) }
        else if let recording = assets.first(where: { $0.id == shot.draft.videoAssetId }) { await preview(recording, label: "Original recording · render to apply edits", force: force) }
        else if let image = assets.first(where: { $0.id == shot.draft.referenceAssetId }) { await preview(image, label: "Source screenshot · render to animate", force: force) }
        else { previewRequest = UUID(); previewPlayer?.pause(); previewPlayer = nil; previewImage = nil; previewAssetID = nil; previewLabel = "Scene not rendered yet" }
    }
    func preview(_ asset: Asset, label: String = "Original media", force: Bool = false) async {
        guard force || previewAssetID != asset.id else { return }
        let request = UUID(); previewRequest = request; let projectID = selectedProjectID
        do {
            let local: URL
            if let existing = cache[asset.id], FileManager.default.fileExists(atPath: existing.path) { local = existing }
            else {
                let directory = worker.dataDirectory.appendingPathComponent("native-cache", isDirectory: true)
                try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700])
                let ext = asset.kind == "video" ? "mp4" : asset.kind == "image" ? "png" : "audio"
                local = directory.appendingPathComponent("\(UUID().uuidString).\(ext)")
                try await api.downloadAsset(asset, to: local); cache[asset.id] = local
            }
            guard previewRequest == request, selectedProjectID == projectID else { return }
            previewPlayer?.pause(); previewImage = nil; previewPlayer = nil
            if asset.kind == "image" { previewImage = NSImage(contentsOf: local) }
            else { previewPlayer = AVPlayer(url: local) }
            previewAssetID = asset.id; previewLabel = label
        } catch { errorMessage = error.localizedDescription }
    }
    func saveAsset(_ asset: Asset) async throws {
        let panel = NSSavePanel(); panel.nameFieldStringValue = asset.name; panel.canCreateDirectories = true
        panel.message = "Save the actual generated or recorded media to your Mac."
        guard panel.runModal() == .OK, let url = panel.url else { return }
        try await api.downloadAsset(asset, to: url)
    }
    func removeAsset(_ asset: Asset) async throws {
        _ = try await api.action("/api/assets/\(asset.id)", method: "DELETE")
        if previewAssetID == asset.id { previewPlayer?.pause(); previewPlayer = nil; previewImage = nil; previewAssetID = nil }
        await refresh()
    }
    func exportFilm(width: Int, height: Int, fps: Int, soundtrack: String?, transition: String, seconds: Double) async throws {
        if draftIsDirty { try await saveShot() }
        guard let id = selectedProjectID else { return }
        let body: [String: JSONValue] = ["width": .number(Double(width)), "height": .number(Double(height)), "fps": .number(Double(fps)),
            "audio_asset_id": soundtrack.map(JSONValue.string) ?? .null, "transition": .string(transition), "transition_duration": .number(seconds)]
        _ = try await api.send("/api/projects/\(id)/export", body: body, as: Job.self)
        selectedPage = .jobs; await refresh()
    }
    func saveFlow(record: Bool) async throws {
        guard let id = selectedProjectID else { return }
        guard let data = flowJSON.data(using: .utf8), data.count <= 1024 * 1024 else { throw StudioError("The flow must be a JSON object smaller than 1 MiB.") }
        let value = try JSONDecoder().decode(JSONValue.self, from: data)
        guard value.object != nil else { throw StudioError("A flow plan must be a JSON object.") }
        let path = selectedFlowID.map { "/api/flows/\($0)" } ?? "/api/projects/\(id)/flows"
        let saved: JSONValue = try await api.send(path, method: selectedFlowID == nil ? "POST" : "PUT", body: value)
        selectedFlowID = saved["id"]?.string
        if record, let flowID = selectedFlowID { _ = try await api.action("/api/flows/\(flowID)/record"); selectedPage = .jobs }
        await refresh()
    }
    func selectFlow(_ flow: JSONValue) {
        guard !isBusy else { return }
        selectedFlowID = flow["id"]?.string
        let allowed = Set(["name", "base_url", "width", "height", "fps", "max_duration", "steps", "feature_titles"])
        flowJSON = JSONValue.object((flow.object ?? [:]).filter { allowed.contains($0.key) }).prettyPrinted()
    }
    func deleteFlow() async throws {
        guard let id = selectedFlowID else { return }
        _ = try await api.action("/api/flows/\(id)", method: "DELETE")
        selectedFlowID = nil; flowJSON = Self.defaultFlow; await refresh()
    }
    func installBrowser() {
        guard !browserInstalling else { return }; browserInstalling = true
        Task {
            defer { browserInstalling = false }
            do { try await worker.installBrowser(); activity = "Chromium installed for browser-flow recording." }
            catch { errorMessage = error.localizedDescription }
        }
    }
    func shutdown() async {
        pollingTask?.cancel(); previewPlayer?.pause()
        if capture.phase == .recording || capture.phase == .starting { try? await capture.stop() }
        // Delegate completion is the only successful recording completion signal.
        let deadline = Date().addingTimeInterval(50)
        while (capture.phase == .finalizing || capture.phase == .stopping || isBusy || captureImportPending), Date() < deadline { try? await Task.sleep(nanoseconds: 100_000_000) }
        capture.teardownPicker()
        await worker.stopOwnedWorker()
    }
    static let defaultFlow = """
    {
      "name": "Demonstrate a real feature",
      "base_url": "http://127.0.0.1:3000",
      "width": 1440,
      "height": 900,
      "fps": 30,
      "max_duration": 60,
      "feature_titles": [],
      "steps": [
        {"action": "goto", "url": "/", "label": "Open the running product"},
        {"action": "wait", "seconds": 2.0, "label": "Establish the interface"},
        {"action": "assert_text", "text": "Replace with real visible text", "label": "Verify the expected screen"},
        {"action": "wait", "seconds": 3.0, "label": "Hold for the audience"}
      ]
    }
    """
}

enum StudioPage: String, CaseIterable, Identifiable {
    case timeline = "Timeline", record = "Record app", source = "Source & coverage", flows = "Live flows", media = "Media library", jobs = "Render queue", agents = "Codex / Claude"
    var id: String { rawValue }
    var symbol: String {
        switch self {
        case .timeline: return "film.stack"
        case .record: return "record.circle"
        case .source: return "curlybraces"
        case .flows: return "point.topleft.down.to.point.bottomright.curvepath"
        case .media: return "photo.on.rectangle"
        case .jobs: return "arrow.triangle.2.circlepath"
        case .agents: return "terminal"
        }
    }
}
