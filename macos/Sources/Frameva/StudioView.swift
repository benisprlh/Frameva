import SwiftUI
import AppKit
import AVKit
import FramevaCore

private let accent = Color(red: 0.68, green: 0.91, blue: 0.38)

struct StudioView: View {
    @ObservedObject var store: StudioStore
    @State private var showExport = false
    @State private var showProjectSettings = false
    var body: some View {
        NavigationSplitView {
            VStack(alignment: .leading, spacing: 0) {
                HStack(spacing: 10) {
                    Image(systemName: "f.square.fill").font(.system(size: 30)).foregroundStyle(accent)
                    Text("frameva.").font(.system(size: 25, weight: .semibold, design: .rounded))
                }.padding(.horizontal, 20).padding(.top, 29).padding(.bottom, 22)
                Button { store.showCreateProject = true } label: { Label("New production", systemImage: "plus").frame(maxWidth: .infinity) }
                    .buttonStyle(.bordered).padding(.horizontal, 16).disabled(!store.isConnected)
                List {
                    Section("PRODUCTIONS") {
                        ForEach(store.projects) { project in
                            Button { Task { await store.selectProject(project.id) } } label: {
                                HStack { Image(systemName: "film.stack"); Text(project.name).lineLimit(1); Spacer() }
                                    .padding(.vertical, 5).contentShape(Rectangle())
                            }.buttonStyle(.plain)
                                .listRowBackground(store.selectedProjectID == project.id ? accent.opacity(0.15) : Color.clear)
                        }
                    }
                    Section("STUDIO") {
                        ForEach(StudioPage.allCases) { page in
                            Button { store.selectedPage = page } label: {
                                HStack { Image(systemName: page.symbol).frame(width: 21); Text(page.rawValue); Spacer()
                                    if page == .jobs, !store.activeJobs.isEmpty { Text("\(store.activeJobs.count)").font(.caption).padding(.horizontal, 6).background(accent.opacity(0.2), in: Capsule()) }
                                }.padding(.vertical, 5).contentShape(Rectangle())
                            }.buttonStyle(.plain).listRowBackground(store.selectedPage == page ? Color.primary.opacity(0.07) : Color.clear)
                        }
                    }
                }.listStyle(.sidebar)
                WorkerStatusView(worker: store.worker).padding(16)
                HStack { Text("NATIVE MAC STUDIO").font(.system(size: 9, weight: .medium)).foregroundStyle(.tertiary); Spacer(); SettingsLink { Image(systemName: "gearshape") } }.padding(.horizontal, 19).padding(.bottom, 17)
            }
            .navigationSplitViewColumnWidth(min: 215, ideal: 235, max: 280)
        } detail: {
            VStack(spacing: 0) {
                header
                Divider()
                if !store.isConnected { connectionView }
                else if store.selectedPage == .agents { AgentSetupView(store: store) }
                else if store.project == nil { welcome }
                else {
                    switch store.selectedPage {
                    case .timeline: TimelineView(store: store)
                    case .record: NativeRecordView(store: store, capture: store.capture)
                    case .source: SourceView(store: store)
                    case .flows: FlowEditorView(store: store)
                    case .media: MediaView(store: store)
                    case .jobs: JobsView(store: store)
                    case .agents: EmptyView()
                    }
                }
                if store.isBusy { HStack(spacing: 10) { ProgressView().controlSize(.small); Text(store.activity).font(.caption); Spacer() }.padding(12).background(.bar) }
            }
            .background(Color(nsColor: .windowBackgroundColor))
        }
        .tint(accent)
        .sheet(isPresented: $store.showCreateProject) { ProjectSheet(store: store, editing: false) }
        .sheet(isPresented: $showProjectSettings) { ProjectSheet(store: store, editing: true) }
        .sheet(isPresented: $showExport) { ExportSheet(store: store) }
        .alert("Frameva", isPresented: Binding(get: { store.errorMessage != nil }, set: { if !$0 { store.errorMessage = nil } })) {
            Button("OK", role: .cancel) { store.errorMessage = nil }
        } message: { Text(store.errorMessage ?? "") }
    }
    private var header: some View {
        HStack(spacing: 16) {
            VStack(alignment: .leading, spacing: 4) {
                Text(store.project?.name ?? "Your next launch starts here").font(.title3.weight(.semibold))
                Text(store.selectedPage.rawValue).font(.caption).foregroundStyle(.secondary)
            }
            Spacer()
            if store.project != nil {
                Button { showProjectSettings = true } label: { Image(systemName: "slider.horizontal.3") }.help("Production settings")
                Button { store.perform("Importing media…") { try await store.importMedia() } } label: { Label("Import", systemImage: "square.and.arrow.down") }.disabled(store.isBusy)
                Button { showExport = true } label: { Label("Export film", systemImage: "square.and.arrow.up") }
                    .buttonStyle(.borderedProminent).foregroundStyle(Color.black).disabled(store.shots.isEmpty || store.isBusy)
            }
        }.padding(.horizontal, 26).padding(.vertical, 21)
    }
    private var welcome: some View {
        VStack(alignment: .leading, spacing: 25) {
            Text("FROM REAL PRODUCT TO RELEASE FILM").font(.caption.weight(.semibold)).tracking(2).foregroundStyle(accent)
            Text("You built something.\nNow make it seen.").font(.system(size: 48, weight: .medium)).tracking(-2)
            Text("Read the source. Record the working app. Shape the real interaction into a launch film—with native capture, an editable timeline, and your coding agent.")
                .font(.title3).foregroundStyle(.secondary).lineSpacing(5).frame(maxWidth: 650, alignment: .leading)
            HStack { Button("Create a production") { store.showCreateProject = true }.buttonStyle(.borderedProminent).controlSize(.large).foregroundStyle(.black)
                Button("Connect Codex / Claude") { store.selectedPage = .agents }.controlSize(.large) }
            HStack(alignment: .top, spacing: 35) {
                WelcomeStep(number: "01", title: "Understand the source", detail: "Inspect candidate features with file evidence.")
                WelcomeStep(number: "02", title: "Capture what works", detail: "Record a live window or an explicit browser flow.")
                WelcomeStep(number: "03", title: "Direct the release", detail: "Trim, focus, render, and export a real video.")
            }.padding(.top, 25)
            Spacer()
        }.padding(45).frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
    }
    private var connectionView: some View {
        VStack(spacing: 20) {
            Image(systemName: "externaldrive.connected.to.line.below").font(.system(size: 44)).foregroundStyle(accent)
            Text("Connect your local worker").font(.title2)
            Text("Frameva uses its bundled Python worker for durable projects, media rendering, and agent tools. No browser wrapper is involved.").foregroundStyle(.secondary).multilineTextAlignment(.center).frame(maxWidth: 500)
            WorkerStatusView(worker: store.worker)
            HStack { Button("Retry connection") { Task { await store.start() } }.buttonStyle(.borderedProminent).foregroundStyle(.black); SettingsLink { Text("Worker settings") } }
        }.frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}

private struct WelcomeStep: View {
    let number: String; let title: String; let detail: String
    var body: some View { VStack(alignment: .leading, spacing: 10) { Text(number).font(.caption.monospaced()).foregroundStyle(accent); Text(title).font(.headline); Text(detail).font(.callout).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true) }.frame(maxWidth: .infinity, alignment: .leading) }
}
struct WorkerStatusView: View {
    @ObservedObject var worker: WorkerController
    var body: some View { HStack(alignment: .top, spacing: 7) { Circle().fill(worker.isReady ? accent : Color.orange).frame(width: 6, height: 6).padding(.top, 4); Text(worker.status).font(.caption2).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true) } }
}

struct TimelineView: View {
    @ObservedObject var store: StudioStore
    var body: some View {
        HSplitView {
            VStack(alignment: .leading, spacing: 0) {
                HStack {
                    VStack(alignment: .leading, spacing: 6) { Text("DIRECTOR’S VIEW").font(.caption2.weight(.semibold)).tracking(1.6).foregroundStyle(.secondary); Text("\(store.shots.count) scenes · \(store.timelineDuration, specifier: "%.1f") seconds").font(.caption).foregroundStyle(.secondary) }
                    Spacer()
                    Button { store.perform("Adding title scene…") { try await store.addTitleScene() } } label: { Label("Title scene", systemImage: "plus") }
                    Button { store.selectedPage = .record } label: { Label("Record app", systemImage: "record.circle") }
                }.padding(22)
                NativePreviewView(store: store).padding(.horizontal, 22)
                HStack { Text(store.previewLabel).font(.caption).foregroundStyle(.secondary); Spacer()
                    if let asset = store.assets.first(where: { $0.id == store.previewAssetID }) { Button("Save media…") { store.perform("Saving media…") { try await store.saveAsset(asset) } }.font(.caption) }
                }.padding(.horizontal, 22).padding(.top, 9)
                Divider().padding(.vertical, 20)
                HStack { Text("Shot sequence").font(.headline); Spacer(); Button("Render all") { store.perform("Queueing timeline…") { try await store.renderAll() } }.disabled(store.shots.isEmpty || store.isBusy) }.padding(.horizontal, 22)
                ScrollView(.horizontal) {
                    HStack(spacing: 10) {
                        ForEach(store.shots) { shot in
                            Button { store.selectShot(shot) } label: {
                                VStack(alignment: .leading, spacing: 10) {
                                    HStack { Image(systemName: shot.draft.provider == "recording" ? "video.fill" : "textformat").foregroundStyle(accent); Spacer(); Text("\(shot.draft.duration, specifier: "%.1f")s").foregroundStyle(.secondary) }.font(.caption)
                                    Text(shot.draft.headline.isEmpty ? shot.draft.name : shot.draft.headline).font(.callout.weight(.medium)).lineLimit(2).frame(height: 38, alignment: .topLeading)
                                    HStack { Text(shot.draft.name).font(.caption2).foregroundStyle(.secondary).lineLimit(1); Spacer(); Circle().fill(store.freshOutput(for: shot) == nil ? Color.secondary : accent).frame(width: 5, height: 5) }
                                }.padding(14).frame(width: 166, alignment: .leading)
                                    .background(store.selectedShotID == shot.id ? accent.opacity(0.12) : Color.primary.opacity(0.035), in: RoundedRectangle(cornerRadius: 10))
                                    .overlay(RoundedRectangle(cornerRadius: 10).stroke(store.selectedShotID == shot.id ? accent.opacity(0.7) : Color.primary.opacity(0.1), lineWidth: 1))
                            }.buttonStyle(.plain)
                        }
                    }.padding(22)
                }
                if store.selectedShotID != nil {
                    HStack {
                        Button { store.perform("Reordering…") { try await store.moveShot(-1) } } label: { Label("Earlier", systemImage: "arrow.left") }
                        Button { store.perform("Reordering…") { try await store.moveShot(1) } } label: { Label("Later", systemImage: "arrow.right") }
                        Spacer(); Button("Delete scene", role: .destructive) { store.perform("Deleting scene…") { try await store.deleteShot() } }
                    }.controlSize(.small).padding(.horizontal, 22)
                }
                Spacer(minLength: 14)
                Label("Real recording pixels stay temporal. Source analysis alone does not prove a working feature.", systemImage: "checkmark.shield").font(.caption2).foregroundStyle(.secondary).padding(22)
            }.frame(minWidth: 500, maxWidth: .infinity)
            SceneInspector(store: store).frame(minWidth: 300, idealWidth: 330, maxWidth: 380)
        }
    }
}
struct NativePreviewView: View {
    @ObservedObject var store: StudioStore
    var body: some View {
        ZStack {
            RoundedRectangle(cornerRadius: 13).fill(Color.black.opacity(0.85))
            if let player = store.previewPlayer { VideoPlayer(player: player).clipShape(RoundedRectangle(cornerRadius: 13)) }
            else if let image = store.previewImage { Image(nsImage: image).resizable().scaledToFit().padding(12) }
            else {
                VStack(alignment: .leading, spacing: 18) {
                    Text(store.project?.name.uppercased() ?? "FRAMEVA").font(.caption2.weight(.semibold)).tracking(3).foregroundStyle(accent)
                    Text(store.draft.headline.isEmpty ? "Your next big thing." : store.draft.headline).font(.system(size: 38, weight: .medium)).tracking(-1.4).foregroundStyle(.white)
                    Text(store.draft.caption.isEmpty ? "Record your app to show the actual product in action." : store.draft.caption).font(.callout).foregroundStyle(.white.opacity(0.6))
                    Text("LAYOUT REFERENCE · RENDER TO SEE THE FINAL VIDEO").font(.system(size: 9, weight: .medium)).tracking(1).foregroundStyle(.white.opacity(0.3)).padding(.top, 15)
                }.frame(maxWidth: .infinity, alignment: .leading).padding(35)
            }
        }.aspectRatio(16/9, contentMode: .fit).frame(minHeight: 240, maxHeight: 520)
    }
}
struct SceneInspector: View {
    @ObservedObject var store: StudioStore
    private func field<Value>(_ path: WritableKeyPath<ShotDraft, Value>) -> Binding<Value> {
        Binding(get: { store.draft[keyPath: path] }, set: { store.editDraft(path, value: $0) })
    }
    private func optionalField(_ path: WritableKeyPath<ShotDraft, String?>) -> Binding<String> {
        Binding(get: { store.draft[keyPath: path] ?? "" }, set: { store.editDraft(path, value: $0.isEmpty ? nil : $0) })
    }
    var body: some View {
        VStack(spacing: 0) {
            HStack { Text("Scene settings").font(.headline); Spacer(); Text(store.draftIsDirty ? "Unsaved" : "Saved").font(.caption2).foregroundStyle(store.draftIsDirty ? Color.orange : Color.secondary) }.padding(20)
            Divider()
            if store.selectedShotID == nil { ContentUnavailableView("No scene selected", systemImage: "film", description: Text("Record an app or add a title scene to begin.")) }
            else {
                Form {
                    Section("Story") {
                        TextField("Scene name", text: field(\.name))
                        TextField("Headline", text: field(\.headline), axis: .vertical).lineLimit(1...3)
                        TextField("Supporting line", text: field(\.caption), axis: .vertical).lineLimit(2...4)
                        TextField("Brand color", text: field(\.brandColor))
                        Picker("Scene type", selection: field(\.provider)) {
                            Text("Real recording").tag("recording"); Text("Product motion").tag("preview")
                            if store.draft.provider == "comfyui" { Text("ComfyUI (configure via agent)").tag("comfyui") }
                        }
                        Picker("Layout", selection: field(\.layout)) { Text("App showcase").tag("showcase"); Text("Title").tag("title"); Text("Detail").tag("detail") }
                    }
                    if store.draft.provider == "recording" {
                        Section("Recorded footage") {
                            Picker("Video", selection: optionalField(\.videoAssetId)) { Text("Choose recording").tag(""); ForEach(store.videoAssets) { Text($0.name).tag($0.id) } }
                            NumberRow(title: "Trim start · s", value: field(\.trimStart))
                            NumberRow(title: "Output duration · s", value: field(\.duration))
                            NumberRow(title: "Playback rate", value: field(\.playbackRate))
                            Text("Footage consumed: \(store.draft.duration * store.draft.playbackRate, specifier: "%.2f") seconds after the trim point. Overruns are rejected, never frozen.").font(.caption2).foregroundStyle(.secondary)
                            Toggle("Keep original audio", isOn: field(\.keepAudio))
                        }
                        Section("Focus & framing") {
                            Slider(value: field(\.focusX), in: 0...1) { Text("Horizontal focus") }; Text("Horizontal focus \(store.draft.focusX, specifier: "%.2f")").font(.caption2).foregroundStyle(.secondary)
                            Slider(value: field(\.focusY), in: 0...1) { Text("Vertical focus") }; Text("Vertical focus \(store.draft.focusY, specifier: "%.2f")").font(.caption2).foregroundStyle(.secondary)
                            Slider(value: field(\.zoom), in: 1...2.5) { Text("Zoom") }; Text("Zoom \(store.draft.zoom, specifier: "%.2f")×").font(.caption2).foregroundStyle(.secondary)
                        }
                    } else if store.draft.provider == "preview" {
                        Section("Screenshot") { Picker("Reference", selection: optionalField(\.referenceAssetId)) { Text("Typography only").tag(""); ForEach(store.imageAssets) { Text($0.name).tag($0.id) } }; NumberRow(title: "Duration · s", value: field(\.duration)) }
                    }
                    Section("Output") {
                        Picker("Movement", selection: field(\.camera)) { Text("Static").tag("static"); Text("Push in").tag("dolly_in"); Text("Pull back").tag("dolly_out"); Text("Pan left").tag("pan_left"); Text("Pan right").tag("pan_right"); Text("Gentle drift").tag("orbit") }
                        Picker("Style", selection: field(\.style)) { Text("Cinematic").tag("cinematic"); Text("Natural").tag("natural"); Text("Noir").tag("noir"); Text("Dream").tag("dream") }
                        HStack { Text("Width"); Spacer(); TextField("Width", value: field(\.width), format: .number).frame(width: 82).multilineTextAlignment(.trailing) }
                        HStack { Text("Height"); Spacer(); TextField("Height", value: field(\.height), format: .number).frame(width: 82).multilineTextAlignment(.trailing) }
                        Picker("Frame rate", selection: field(\.fps)) { ForEach([8, 12, 16, 24, 25, 30], id: \.self) { Text("\($0) fps").tag($0) } }
                    }
                }.formStyle(.grouped).scrollContentBackground(.hidden).disabled(store.isBusy)
                Divider()
                VStack(spacing: 10) {
                    Button { store.perform("Saving and queueing scene…") { try await store.renderSelected() } } label: { Label("Render scene", systemImage: "play.rectangle.fill").frame(maxWidth: .infinity) }.buttonStyle(.borderedProminent).foregroundStyle(.black)
                    Button("Save changes") { store.perform("Saving scene…") { try await store.saveShot() } }.keyboardShortcut("s")
                }.padding(18).disabled(store.isBusy)
            }
        }.background(Color.primary.opacity(0.025))
    }
}
private struct NumberRow: View {
    let title: String
    @Binding var value: Double
    var body: some View { HStack { Text(title); Spacer(); TextField(title, value: $value, format: .number.precision(.fractionLength(0...3))).frame(width: 80).multilineTextAlignment(.trailing) } }
}
