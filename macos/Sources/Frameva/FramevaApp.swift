import SwiftUI
import AppKit
import FramevaCore

@main
struct FramevaApp: App {
    @NSApplicationDelegateAdaptor(FramevaAppDelegate.self) private var delegate
    @StateObject private var store = StudioStore()
    var body: some Scene {
        WindowGroup("Frameva") {
            StudioView(store: store)
                .frame(minWidth: 1120, minHeight: 720)
                .task {
                    delegate.store = store
                    if !store.isConnected { await store.start() }
                }
        }
        .defaultSize(width: 1440, height: 940)
        .windowStyle(.hiddenTitleBar)
        .commands {
            CommandGroup(replacing: .newItem) {
                Button("New Production") { store.showCreateProject = true }.keyboardShortcut("n")
                Button("Import Media…") { store.perform("Importing media…") { try await store.importMedia() } }.keyboardShortcut("i")
                    .disabled(store.selectedProjectID == nil || store.isBusy)
            }
            CommandGroup(replacing: .saveItem) {
                Button("Save Scene") { store.perform("Saving scene…") { try await store.saveShot() } }.keyboardShortcut("s")
                    .disabled(store.selectedShotID == nil || store.isBusy)
            }
            CommandMenu("Production") {
                Button("Record App Window…") { Task { await store.startCapture() } }.keyboardShortcut("r", modifiers: [.command, .shift])
                    .disabled(store.selectedProjectID == nil || store.capture.phase.isBusy)
                Button("Render Selected Scene") { store.perform("Queueing scene…") { try await store.renderSelected() } }.disabled(store.selectedShotID == nil)
                Button("Render All Scenes") { store.perform("Queueing timeline…") { try await store.renderAll() } }.disabled(store.shots.isEmpty)
            }
        }
        Settings { NativeSettingsView(store: store).frame(width: 650, height: 480) }
    }
}

@MainActor
final class FramevaAppDelegate: NSObject, NSApplicationDelegate {
    weak var store: StudioStore?
    private var terminating = false
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }
    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        if terminating { return .terminateLater }
        guard let store else { return .terminateNow }
        if store.capture.phase.isBusy || store.isBusy || !store.activeJobs.isEmpty || store.draftIsDirty {
            let alert = NSAlert(); alert.messageText = "Quit this production session?"
            alert.informativeText = "Active window capture will be finalized before closing. Unsaved scene edits will be lost. Renders owned by this app will stop; finished media remains saved."
            alert.addButton(withTitle: "Keep Frameva open"); alert.addButton(withTitle: "Quit and finish capture")
            guard alert.runModal() == .alertSecondButtonReturn else { return .terminateCancel }
        }
        terminating = true
        Task { await store.shutdown(); sender.reply(toApplicationShouldTerminate: true) }
        return .terminateLater
    }
}
