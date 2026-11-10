import SwiftUI
import AppKit
import AVKit
import FramevaCore

private let nativeAccent = Color(red: 0.68, green: 0.91, blue: 0.38)

struct NativeRecordView: View {
    @ObservedObject var store: StudioStore
    @ObservedObject var capture: CaptureController
    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 24) {
                SectionHeading(eyebrow: "CAPTURE THE WORKING PRODUCT", title: "Real interactions. Real footage.", detail: "Use the macOS system picker to choose a window or display. Frameva records video, pointer movement, and optional click highlights—not a slideshow of screenshots.")
                GroupBox {
                    HStack(alignment: .top, spacing: 30) {
                        VStack(alignment: .leading, spacing: 16) {
                            Label(capture.phase.label, systemImage: capture.phase == .recording ? "record.circle.fill" : "macwindow").font(.title2.weight(.medium)).foregroundStyle(capture.phase == .recording ? Color.red : Color.primary)
                            Text(capture.message).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
                            if let began = capture.startedAt { Text(began, style: .timer).font(.system(size: 34, weight: .light, design: .monospaced)).foregroundStyle(nativeAccent) }
                            HStack {
                                if capture.phase.canStop {
                                    Button { Task { do { try await capture.stop() } catch { store.errorMessage = error.localizedDescription } } } label: { Label("Stop & finalize", systemImage: "stop.fill") }.buttonStyle(.borderedProminent).tint(.red)
                                } else {
                                    Button { Task { await store.startCapture() } } label: { Label("Choose window & record", systemImage: "record.circle") }.buttonStyle(.borderedProminent).foregroundStyle(.black).disabled(capture.phase.isBusy || store.isBusy)
                                }
                                if capture.phase == .stopping || capture.phase == .finalizing || capture.phase == .starting { ProgressView().controlSize(.small) }
                            }.controlSize(.large)
                        }.frame(maxWidth: .infinity, alignment: .leading)
                        VStack(alignment: .leading, spacing: 14) {
                            Text("CAPTURE OPTIONS").font(.caption2.weight(.semibold)).tracking(1.5).foregroundStyle(.secondary)
                            Toggle("Show click highlights", isOn: $capture.showClicks)
                            Toggle("Capture system audio", isOn: $capture.systemAudio)
                            Toggle("Capture microphone", isOn: $capture.microphone)
                            Text("Microphone permission is requested only when enabled. The system sharing picker controls the selected content.").font(.caption).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
                        }.frame(width: 260).disabled(capture.phase.isBusy)
                    }.padding(20)
                }
                if capture.retainedRecording != nil {
                    GroupBox {
                        HStack {
                            VStack(alignment: .leading, spacing: 5) { Text("Your original take is kept locally.").font(.headline); Text("If upload fails or exceeds 256 MiB, reveal the file and import a shorter take. An unfinished file is never treated as a successful recording.").font(.caption).foregroundStyle(.secondary) }
                            Spacer(); Button("Reveal file") { capture.revealRecording() }
                            if capture.phase == .finished { Button("Retry import") { store.perform("Importing finalized recording…") { try await store.retryCaptureImport() } }.disabled(store.isBusy) }
                        }.padding(12)
                    }
                }
                HStack(alignment: .top, spacing: 26) {
                    InstructionCard(number: "01", title: "Prepare demo data", detail: "Open your app, choose a clean example, and keep private windows outside the selected share.")
                    InstructionCard(number: "02", title: "Demonstrate one workflow", detail: "Use the interface at a deliberate pace. Cursor, clicks, and changing UI become real video frames.")
                    InstructionCard(number: "03", title: "Shape the scene", detail: "After macOS finishes the MP4, Frameva imports it and creates a recording scene for trim, focus, and titles.")
                }
                Divider()
                HStack { VStack(alignment: .leading, spacing: 8) { Text("Want repeatable app demos?").font(.headline); Text("Use Live flows to record explicit browser actions against a running app. Source code informs the plan; recorded steps provide runtime evidence.").foregroundStyle(.secondary) }; Spacer(); Button("Open Live flows") { store.selectedPage = .flows } }
            }.padding(30)
        }
    }
}

struct SourceView: View {
    @ObservedObject var store: StudioStore
    @State private var aspect = "landscape"
    @State private var replace = false
    var features: [JSONValue] { store.source?["features"]?.array ?? [] }
    var candidates: [JSONValue] { store.coverage?["source_candidates"]?.array ?? [] }
    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 24) {
                HStack(alignment: .top) {
                    SectionHeading(eyebrow: "EVIDENCE BEFORE THE SCRIPT", title: "Find the story in your code.", detail: "Source candidates are not proof of a working feature. Record an explicitly mapped app flow to show what actually ran.")
                    Spacer(); Button { store.perform("Inspecting source ZIP…") { try await store.sourceImport() } } label: { Label("Import source ZIP", systemImage: "doc.zipper") }.disabled(store.isBusy)
                }
                if let source = store.source {
                    GroupBox {
                        VStack(alignment: .leading, spacing: 12) {
                            Text(source["product_name"]?.string ?? source["name"]?.string ?? "Source inspected").font(.title2)
                            Text(source["summary"]?.string ?? source["description"]?.string ?? "Review the candidate features below.").foregroundStyle(.secondary)
                            Text("\(Int(source["stats"]?["files_scanned"]?.number ?? 0)) files inspected · \(features.count) feature candidates").font(.caption).foregroundStyle(.secondary)
                            HStack { Picker("Format", selection: $aspect) { Text("Landscape").tag("landscape"); Text("Portrait").tag("portrait"); Text("Square").tag("square") }.frame(width: 240)
                                Toggle("Replace existing scenes", isOn: $replace).disabled(store.shots.isEmpty)
                                Spacer(); Button("Draft storyboard") { store.perform("Drafting source-based scenes…") { try await store.draftLaunch(aspect: aspect, replaceExisting: replace) } }.buttonStyle(.borderedProminent).foregroundStyle(.black).disabled(store.isBusy) }
                            Text("The built-in draft uses conservative templates. Your coding agent can refine the narrative using the same source evidence.").font(.caption2).foregroundStyle(.secondary)
                        }.padding(12).frame(maxWidth: .infinity, alignment: .leading)
                    }
                    if let coverage = store.coverage {
                        GroupBox("Runtime coverage") {
                            HStack {
                                VStack(alignment: .leading, spacing: 6) { Text("\(coverage["totals"]?["recorded_percent"]?.number ?? 0, specifier: "%.0f")% explicitly mapped to completed recordings").font(.headline); Text("A successful flow verifies only its recorded steps. It does not verify every feature, edge case, or product claim.").font(.caption).foregroundStyle(.secondary) }
                                Spacer(); Button("Record a flow") { store.selectedPage = .flows }
                            }.padding(10)
                        }
                    }
                    if let changed = store.coverage?["flows_with_unrecorded_changes"]?.array, !changed.isEmpty {
                        GroupBox("Flows needing a new take") {
                            VStack(alignment: .leading, spacing: 8) {
                                ForEach(Array(changed.enumerated()), id: \.offset) { _, flow in
                                    Text("\(flow["name"]?.string ?? "Flow"): \(flow["reason"]?.string ?? "Record the current plan.")").font(.caption).foregroundStyle(.orange)
                                }
                            }.padding(10).frame(maxWidth: .infinity, alignment: .leading)
                        }
                    }
                    ForEach(Array(features.enumerated()), id: \.offset) { _, feature in
                        let mapped = candidates.first { $0["title"]?.string == feature["title"]?.string }
                        GroupBox {
                            VStack(alignment: .leading, spacing: 10) {
                                HStack { Text(feature["title"]?.string ?? "Feature candidate").font(.headline); Spacer(); Text(mapped?["status"]?.string == "recorded" ? "RECORDED FLOW" : "SOURCE CANDIDATE").font(.caption2.weight(.semibold)).foregroundStyle(mapped?["status"]?.string == "recorded" ? nativeAccent : Color.orange) }
                                Text(feature["description"]?.string ?? "Review this candidate before using it in the launch copy.").foregroundStyle(.secondary)
                                ForEach(Array((feature["evidence"]?.array ?? []).prefix(4).enumerated()), id: \.offset) { _, evidence in
                                    VStack(alignment: .leading, spacing: 5) {
                                        Text("\(evidence["path"]?.string ?? "source"):\(Int(evidence["line"]?.number ?? 0))").font(.caption.monospaced()).foregroundStyle(nativeAccent)
                                        if let excerpt = evidence["excerpt"]?.string { Text(excerpt).font(.caption2.monospaced()).foregroundStyle(.secondary).textSelection(.enabled) }
                                    }
                                }
                            }.padding(12).frame(maxWidth: .infinity, alignment: .leading)
                        }
                    }
                    ForEach(Array((source["warnings"]?.array ?? []).enumerated()), id: \.offset) { _, warning in Text(warning.string ?? "").font(.caption).foregroundStyle(.orange) }
                } else {
                    ContentUnavailableView("Bring the repository into the story", systemImage: "curlybraces", description: Text("Import a ZIP without dependencies or build output, or ask Codex / Claude Code to inspect the local repository through Frameva MCP."))
                        .frame(maxWidth: .infinity, minHeight: 290)
                }
            }.padding(30)
        }
    }
}

struct FlowEditorView: View {
    @ObservedObject var store: StudioStore
    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            HStack(alignment: .top) {
                SectionHeading(eyebrow: "SCRIPT THE DEMO, RECORD THE INTERACTION", title: "A repeatable product take.", detail: "Start your app separately. This explicit JSON plan drives its real browser UI and records moving video; no source code is installed or executed by Frameva.")
                Spacer()
                Button("New flow") { store.selectedFlowID = nil; store.flowJSON = StudioStore.defaultFlow }.disabled(store.isBusy)
            }
            HStack(alignment: .top, spacing: 18) {
                VStack(alignment: .leading, spacing: 10) {
                    Text("SAVED FLOWS").font(.caption2.weight(.semibold)).tracking(1.3).foregroundStyle(.secondary)
                    ForEach(Array(store.flows.enumerated()), id: \.offset) { _, flow in
                        Button { store.selectFlow(flow) } label: { VStack(alignment: .leading, spacing: 5) { Text(flow["name"]?.string ?? "Flow").font(.callout); Text(flow["base_url"]?.string ?? "").font(.caption2).foregroundStyle(.secondary).lineLimit(2) }.frame(maxWidth: .infinity, alignment: .leading).padding(10).background(store.selectedFlowID == flow["id"]?.string ? nativeAccent.opacity(0.12) : Color.primary.opacity(0.04), in: RoundedRectangle(cornerRadius: 8)) }.buttonStyle(.plain).disabled(store.isBusy)
                    }
                    if store.flows.isEmpty { Text("No saved flows yet. Edit the example for your app, then save.").font(.caption).foregroundStyle(.secondary) }
                    Spacer()
                    Button(store.browserInstalling ? "Installing Chromium…" : "Install flow browser…") { store.installBrowser() }.disabled(store.browserInstalling)
                    Text("Explicitly downloads Playwright Chromium. Native window recording needs no browser installation.").font(.caption2).foregroundStyle(.secondary)
                }.frame(width: 210)
                VStack(alignment: .leading, spacing: 10) {
                    TextEditor(text: $store.flowJSON).disabled(store.isBusy).font(.system(.body, design: .monospaced)).scrollContentBackground(.hidden).padding(10).background(Color.primary.opacity(0.035), in: RoundedRectangle(cornerRadius: 10)).overlay(RoundedRectangle(cornerRadius: 10).stroke(Color.primary.opacity(0.12))).frame(minHeight: 350)
                    Text("Actions: goto, click, fill, press, scroll, wait, assert_text. Navigation stays on base_url’s origin. Map exact source candidate titles with feature_titles. Put sensitive fills in FRAMEVA_FLOW_SECRET_* environment variables, not literal JSON.").font(.caption).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
                }
            }
            HStack {
                if store.selectedFlowID != nil { Button("Delete flow", role: .destructive) { store.perform("Deleting flow…") { try await store.deleteFlow() } } }
                Spacer(); Button("Save plan") { store.perform("Saving flow…") { try await store.saveFlow(record: false) } }
                Button { store.perform("Queueing live app recording…") { try await store.saveFlow(record: true) } } label: { Label("Save & record workflow", systemImage: "record.circle") }.buttonStyle(.borderedProminent).foregroundStyle(.black)
            }.disabled(store.isBusy)
        }.padding(30)
    }
}

struct MediaView: View {
    @ObservedObject var store: StudioStore
    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 22) {
                HStack { SectionHeading(eyebrow: "YOUR PRODUCTION ASSETS", title: "Keep the real material.", detail: "Recordings, screenshots, rendered scenes, and music stay with this project."); Spacer(); Button("Import media…") { store.perform("Importing media…") { try await store.importMedia() } } }
                if store.previewAssetID != nil { NativePreviewView(store: store).frame(maxHeight: 340) }
                if store.assets.isEmpty { ContentUnavailableView("No media yet", systemImage: "photo.on.rectangle", description: Text("Record an app window, run a live flow, or import an existing recording.")) }
                ForEach(store.assets) { asset in
                    HStack(spacing: 15) {
                        Image(systemName: asset.kind == "video" ? "video.fill" : asset.kind == "audio" ? "waveform" : "photo").font(.title2).foregroundStyle(nativeAccent).frame(width: 38)
                        VStack(alignment: .leading, spacing: 5) { Text(asset.name).font(.headline).lineLimit(1); Text("\(asset.kind.capitalized) · \(ByteCountFormatter.string(fromByteCount: asset.size, countStyle: .file))\(asset.duration.map { String(format: " · %.1fs", $0) } ?? "")").font(.caption).foregroundStyle(.secondary)
                            if asset.captureReport != nil { Text("Completed browser flow · capture report attached").font(.caption2).foregroundStyle(nativeAccent) }
                        }
                        Spacer()
                        Button("Preview") { Task { await store.preview(asset, force: true) } }
                        if asset.kind == "video" { Button("Add to timeline") { store.perform("Adding real recording scene…") { try await store.addRecordingScene(asset); store.selectedPage = .timeline } } }
                        Button { store.perform("Saving media…") { try await store.saveAsset(asset) } } label: { Image(systemName: "square.and.arrow.up") }.help("Save a copy")
                        Button(role: .destructive) { store.perform("Deleting media…") { try await store.removeAsset(asset) } } label: { Image(systemName: "trash") }.help("Delete unreferenced media")
                    }.padding(15).background(Color.primary.opacity(0.035), in: RoundedRectangle(cornerRadius: 10))
                }
            }.padding(30)
        }
    }
}

struct JobsView: View {
    @ObservedObject var store: StudioStore
    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                SectionHeading(eyebrow: "ON THE RENDER FLOOR", title: "From a take to the final cut.", detail: "Recording, composition, and export jobs are durable. Failed steps stay visible; partial recordings are not published as success.")
                if store.jobs.isEmpty { ContentUnavailableView("Ready when you are", systemImage: "film", description: Text("Record a flow or render a timeline scene to see its progress here.")) }
                ForEach(store.jobs) { job in
                    VStack(alignment: .leading, spacing: 12) {
                        HStack(alignment: .top) {
                            Image(systemName: job.status == "succeeded" ? "checkmark.circle.fill" : job.status == "failed" ? "exclamationmark.circle" : "arrow.triangle.2.circlepath").foregroundStyle(job.status == "failed" ? Color.orange : nativeAccent).font(.title2)
                            VStack(alignment: .leading, spacing: 5) {
                                Text(job.type == "export" ? "Film export" : job.type == "record" ? job.params["flow"]?["name"]?.string ?? "Live app flow" : job.params["shot"]?["name"]?.string ?? "Scene render").font(.headline)
                                Text("\(job.status.capitalized) · \(job.type)").font(.caption).foregroundStyle(.secondary)
                            }
                            Spacer()
                            if job.isActive { Button("Cancel") { store.perform("Cancelling…") { try await store.modifyJob(job, action: "cancel") } } }
                            if job.status == "failed" || job.status == "cancelled" { Button("Retry saved inputs") { store.perform("Retrying saved job…") { try await store.modifyJob(job, action: "retry") } } }
                            if let asset = store.assets.first(where: { $0.id == job.assetId }) {
                                Button("Preview") { store.selectedPage = .media; Task { await store.preview(asset, force: true) } }
                                Button("Save…") { store.perform("Saving finished media…") { try await store.saveAsset(asset) } }.buttonStyle(.borderedProminent).foregroundStyle(.black)
                            }
                        }
                        if job.isActive { ProgressView(value: min(100, max(0, job.progress)), total: 100).tint(nativeAccent) }
                        if let error = job.error { Text(error).font(.caption).foregroundStyle(.orange).textSelection(.enabled) }
                    }.padding(18).background(Color.primary.opacity(0.035), in: RoundedRectangle(cornerRadius: 11))
                }
            }.padding(30)
        }
    }
}

struct AgentSetupView: View {
    @ObservedObject var store: StudioStore
    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 23) {
                SectionHeading(eyebrow: "YOUR CODING AGENT, NOW YOUR DIRECTOR", title: "Agent setup", detail: "Use Frameva’s local MCP tools from Codex or Claude Code. The bundled worker provides the bridge; no separate Python installation is needed in a packaged app.")
                GroupBox("Claude Code / MCP JSON") {
                    VStack(alignment: .leading, spacing: 14) {
                        Text(store.worker.mcpConfiguration()).font(.system(.caption, design: .monospaced)).textSelection(.enabled).frame(maxWidth: .infinity, alignment: .leading)
                        Button("Copy configuration") { NSPasteboard.general.clearContents(); NSPasteboard.general.setString(store.worker.mcpConfiguration(), forType: .string) }
                    }.padding(14)
                }
                GroupBox("Codex configuration") {
                    VStack(alignment: .leading, spacing: 10) {
                        Text("Run the bundled helper’s mcp-config command to print exact Codex TOML and registration commands. Merge entries into your existing settings; keep Frameva open while the agent works.").foregroundStyle(.secondary)
                        Text("\"\(store.worker.executable?.path ?? store.worker.helperExecutable.path)\" mcp-config").font(.system(.caption, design: .monospaced)).textSelection(.enabled)
                    }.padding(14)
                }
                Text("Read this app’s source code. Identify three real benefits with file evidence. Write a live flow for the running demo URL, record and verify its steps, then build a 20-second launch film from the actual recording in Frameva. Do not claim unrecorded features are verified.")
                    .font(.title3).lineSpacing(5).padding(24).background(nativeAccent.opacity(0.09), in: RoundedRectangle(cornerRadius: 12))
                Label("The local token is read from the same private data directory. It is never embedded in this configuration or in media URLs.", systemImage: "lock.shield").font(.caption).foregroundStyle(.secondary)
            }.padding(30)
        }
    }
}

struct NativeSettingsView: View {
    @ObservedObject var store: StudioStore
    @AppStorage("workerExecutablePath") private var workerPath = ""
    var body: some View {
        Form {
            Section("Local worker") {
                WorkerStatusView(worker: store.worker)
                LabeledContent("Data directory", value: store.worker.dataDirectory.path).textSelection(.enabled)
                LabeledContent("Worker endpoint", value: store.worker.baseURL.absoluteString)
                TextField("Development executable override", text: $workerPath, prompt: Text("Leave empty to use the bundled worker"))
                Text("For development, choose an absolute frameva executable or the Python binary from your installed virtual environment. FRAMEVA_WORKER_EXECUTABLE takes precedence when set.").font(.caption).foregroundStyle(.secondary)
                HStack {
                    Button("Choose executable…") { let panel = NSOpenPanel(); panel.canChooseDirectories = false; if panel.runModal() == .OK { workerPath = panel.url?.path ?? "" } }
                    Button("Reconnect") { Task { await store.worker.stopOwnedWorker(); store.isConnected = false; await store.start() } }.disabled(store.isBusy || store.capture.phase.isBusy)
                }
            }
            Section("Browser flow recording") {
                Text("Native ScreenCaptureKit recording works without Chromium. Automated browser flows require an explicit Playwright Chromium installation.").font(.caption).foregroundStyle(.secondary)
                Button(store.browserInstalling ? "Installing…" : "Install Chromium for live flows") { store.installBrowser() }.disabled(store.browserInstalling)
            }
            Section("Build status") { Text("Frameva 0.2 native source alpha. Native compilation, signing, permission prompts, and recording must be verified on a real macOS 15+ machine. An unsigned development build is not a notarized distribution.").font(.caption).foregroundStyle(.secondary) }
        }.formStyle(.grouped).padding()
    }
}

struct ProjectSheet: View {
    @ObservedObject var store: StudioStore
    let editing: Bool
    @Environment(\.dismiss) private var dismiss
    @State private var name = ""
    @State private var description = ""
    var body: some View {
        VStack(alignment: .leading, spacing: 20) {
            Text(editing ? "Production settings" : "Give your launch a name.").font(.title2.weight(.semibold))
            TextField("Product or project name", text: $name).textFieldStyle(.roundedBorder)
            TextField("Production brief", text: $description, axis: .vertical).lineLimit(3...6).textFieldStyle(.roundedBorder)
            HStack {
                if editing { Button("Delete project", role: .destructive) { store.perform("Deleting project…") { try await store.deleteProject(); dismiss() } } }
                Spacer(); Button("Cancel") { dismiss() }.keyboardShortcut(.cancelAction)
                Button(editing ? "Save settings" : "Create production") { store.perform("Saving production…") { if editing { try await store.renameProject(name: name, description: description) } else { try await store.createProject(name: name, description: description) }; dismiss() } }.buttonStyle(.borderedProminent).foregroundStyle(.black).keyboardShortcut(.defaultAction).disabled(name.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || store.isBusy)
            }
        }.padding(28).frame(width: 520)
            .onAppear { if editing { name = store.project?.name ?? ""; description = store.project?.description ?? "" } }
    }
}
struct ExportSheet: View {
    @ObservedObject var store: StudioStore
    @Environment(\.dismiss) private var dismiss
    @State private var format = "1280x720"
    @State private var fps = 30
    @State private var audio = ""
    @State private var transition = "crossfade"
    @State private var transitionDuration = 0.35
    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            Text("Ready for the launch?").font(.title2.weight(.semibold))
            Text("Export the latest fresh render of each timeline scene. Original clip audio is preserved; an optional soundtrack is mixed by the rendering worker.").foregroundStyle(.secondary)
            Form {
                Picker("Output", selection: $format) { Text("Landscape · 1280 × 720").tag("1280x720"); Text("Landscape · 1920 × 1080").tag("1920x1080"); Text("Portrait · 1080 × 1920").tag("1080x1920"); Text("Square · 1080 × 1080").tag("1080x1080") }
                Picker("Frame rate", selection: $fps) { Text("24 fps").tag(24); Text("25 fps").tag(25); Text("30 fps").tag(30) }
                Picker("Soundtrack", selection: $audio) { Text("Original audio only").tag(""); ForEach(store.audioAssets) { Text($0.name).tag($0.id) } }
                Picker("Transitions", selection: $transition) { Text("Crossfade").tag("crossfade"); Text("Cut").tag("cut") }
                if transition == "crossfade" { HStack { Text("Crossfade duration"); Slider(value: $transitionDuration, in: 0.05...0.8); Text("\(transitionDuration, specifier: "%.2f")s").monospacedDigit() } }
            }
            Text("A crossfade must fit within half of the shortest scene. Render changed scenes again before exporting. Save the finished MP4 from the render queue.").font(.caption).foregroundStyle(.secondary)
            HStack { Button("Cancel") { dismiss() }.keyboardShortcut(.cancelAction); Spacer(); Button("Export film") { store.perform("Queueing final film…") { let dimensions = format.split(separator: "x").compactMap { Int($0) }; try await store.exportFilm(width: dimensions[0], height: dimensions[1], fps: fps, soundtrack: audio.isEmpty ? nil : audio, transition: transition, seconds: transitionDuration); dismiss() } }.buttonStyle(.borderedProminent).foregroundStyle(.black).disabled(store.isBusy) }
        }.padding(28).frame(width: 600)
    }
}
private struct SectionHeading: View {
    let eyebrow: String; let title: String; let detail: String
    var body: some View { VStack(alignment: .leading, spacing: 12) { Text(eyebrow).font(.caption2.weight(.semibold)).tracking(1.5).foregroundStyle(nativeAccent); Text(title).font(.system(size: 29, weight: .medium)).tracking(-0.8); Text(detail).foregroundStyle(.secondary).lineSpacing(3).fixedSize(horizontal: false, vertical: true) }.frame(maxWidth: 760, alignment: .leading) }
}
private struct InstructionCard: View {
    let number: String; let title: String; let detail: String
    var body: some View { VStack(alignment: .leading, spacing: 11) { Text(number).font(.caption.monospaced()).foregroundStyle(nativeAccent); Text(title).font(.headline); Text(detail).font(.callout).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true) }.frame(maxWidth: .infinity, alignment: .leading) }
}
