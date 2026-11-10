import Foundation
import Combine
import AppKit
import AVFoundation
import ScreenCaptureKit
import CoreMedia
import CoreVideo
import FramevaCore

@MainActor
final class CaptureController: NSObject, ObservableObject {
    @Published private(set) var phase: CapturePhase = .idle
    @Published private(set) var message = "Record a real app window with the macOS sharing picker."
    @Published private(set) var startedAt: Date?
    @Published private(set) var retainedRecording: URL?
    @Published var systemAudio = true
    @Published var microphone = false
    @Published var showClicks = true
    var onFinished: ((URL) -> Void)?
    var onError: ((String) -> Void)?
    private var stream: SCStream?
    private var recordingOutput: SCRecordingOutput?
    private var outputURL: URL?
    private var finishWaiter: CheckedContinuation<Void, Error>?
    private var completionDelivered = false
    private var timeoutTask: Task<Void, Never>?
    private var observedPicker = false
    private var captureID = UUID()
    private let recordingDirectory = URL(fileURLWithPath: ProcessInfo.processInfo.environment["FRAMEVA_DATA_DIR"] ?? NSHomeDirectory() + "/.frameva", isDirectory: true).appendingPathComponent("native-recordings", isDirectory: true)

    func chooseWindow() async {
        guard !phase.isBusy else { return }
        captureID = UUID(); let attempt = captureID
        completionDelivered = false; outputURL = nil; phase = .choosing
        if microphone {
            let status = AVCaptureDevice.authorizationStatus(for: .audio)
            var allowed = status == .authorized
            if status == .notDetermined { allowed = await AVCaptureDevice.requestAccess(for: .audio) }
            guard captureID == attempt else { return }
            guard allowed else { fail(StudioError("Microphone access was not granted. Enable it in System Settings or record without microphone audio.")); return }
        }
        guard captureID == attempt else { return }
        message = "Choose the app window or display you want to demonstrate."
        let picker = SCContentSharingPicker.shared
        var config = SCContentSharingPickerConfiguration()
        config.allowedPickerModes = [.singleWindow, .singleDisplay]
        config.allowsChangingSelectedContent = false
        picker.defaultConfiguration = config
        if !observedPicker { picker.add(self); observedPicker = true }
        picker.isActive = true
        picker.present()
    }
    private func start(filter: SCContentFilter) async {
        guard phase == .choosing else { return }
        phase = .starting; message = "Preparing the selected content…"
        let startupID = captureID
        timeoutTask?.cancel()
        timeoutTask = Task { [weak self] in
            do { try await Task.sleep(nanoseconds: 30_000_000_000) } catch { return }
            guard let self, self.captureID == startupID, self.phase == .starting else { return }
            self.fail(StudioError("macOS did not start recording in time. Choose the window again; no partial file was imported."))
        }
        let attempt = captureID
        let directory = recordingDirectory.appendingPathComponent("Take-\(UUID().uuidString)", isDirectory: true)
        do {
            try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700])
            let destination = directory.appendingPathComponent("App-recording.mp4")
            outputURL = destination
            let configuration = SCStreamConfiguration()
            let scale = CGFloat(filter.pointPixelScale)
            let naturalWidth = max(64, Double(filter.contentRect.width * scale))
            let naturalHeight = max(64, Double(filter.contentRect.height * scale))
            let ratio = min(1, 2560 / max(naturalWidth, naturalHeight))
            configuration.width = max(64, Int(naturalWidth * ratio) / 2 * 2)
            configuration.height = max(64, Int(naturalHeight * ratio) / 2 * 2)
            configuration.minimumFrameInterval = CMTime(value: 1, timescale: 30)
            configuration.queueDepth = 6
            configuration.pixelFormat = kCVPixelFormatType_32BGRA
            configuration.showsCursor = true
            configuration.showMouseClicks = showClicks
            configuration.capturesAudio = systemAudio
            configuration.sampleRate = 48_000
            configuration.channelCount = 2
            configuration.excludesCurrentProcessAudio = true
            configuration.captureMicrophone = microphone
            configuration.includeChildWindows = true
            let recordingConfig = SCRecordingOutputConfiguration()
            recordingConfig.outputURL = destination
            recordingConfig.outputFileType = .mp4
            recordingConfig.videoCodecType = .h264
            let output = SCRecordingOutput(configuration: recordingConfig, delegate: self)
            let capture = SCStream(filter: filter, configuration: configuration, delegate: self)
            try capture.addRecordingOutput(output)
            self.recordingOutput = output; self.stream = capture
            try await capture.startCapture()
            guard captureID == attempt, self.stream === capture, !completionDelivered else {
                try? await capture.stopCapture(); return
            }
            // The recording-start delegate owns the visible recording state.
        } catch { if captureID == attempt { fail(error) } }
    }
    func stop() async throws {
        guard phase == .recording || phase == .starting, let stream else { return }
        phase = .stopping; message = "Closing the recording. Please keep Frameva open."
        try await withCheckedThrowingContinuation { (continuation: CheckedContinuation<Void, Error>) in
            finishWaiter = continuation
            armFinalizationTimeout()
            Task {
                do {
                    try await stream.stopCapture()
                    guard self.stream === stream else { return }
                    if !completionDelivered { phase = .finalizing; message = "Waiting for macOS to finalize the MP4…" }
                } catch { if self.stream === stream { fail(error) } }
            }
        }
    }
    private func armFinalizationTimeout() {
        timeoutTask?.cancel()
        let attempt = captureID
        timeoutTask = Task { [weak self] in
            do { try await Task.sleep(nanoseconds: 45_000_000_000) } catch { return }
            guard let self, self.captureID == attempt, !self.completionDelivered else { return }
            self.fail(StudioError("macOS did not confirm that the recording finished. No partial recording was uploaded. Check the recording folder before retrying."))
        }
    }
    private func finish() {
        guard !completionDelivered, let url = outputURL else { return }
        completionDelivered = true; timeoutTask?.cancel(); timeoutTask = nil
        retainedRecording = url; phase = .finished; startedAt = nil
        message = "Recording finalized. Importing the actual video…"
        stream = nil; recordingOutput = nil; SCContentSharingPicker.shared.isActive = false
        let waiter = finishWaiter; finishWaiter = nil; waiter?.resume()
        onFinished?(url)
    }
    private func fail(_ error: Error) {
        guard !completionDelivered else { return }
        completionDelivered = true; timeoutTask?.cancel(); timeoutTask = nil
        phase = .failed; message = error.localizedDescription; startedAt = nil
        if let outputURL { retainedRecording = outputURL } // Never upload unfinished bytes as success.
        let waiter = finishWaiter; finishWaiter = nil; waiter?.resume(throwing: error)
        SCContentSharingPicker.shared.isActive = false
        if let current = stream { Task { try? await current.stopCapture() } }
        stream = nil; recordingOutput = nil
        onError?(message)
    }
    func markImported(_ url: URL) {
        guard retainedRecording == url else { return }
        message = "Recording imported. Add it to the timeline and shape the launch."
        // The original is intentionally retained until the user explicitly removes it.
    }
    func teardownPicker() {
        SCContentSharingPicker.shared.isActive = false
        if observedPicker { SCContentSharingPicker.shared.remove(self); observedPicker = false }
        if phase == .choosing { captureID = UUID(); phase = .idle }
    }
    func revealRecording() { if let url = retainedRecording { NSWorkspace.shared.activateFileViewerSelecting([url]) } }
}

extension CaptureController: SCContentSharingPickerObserver {
    nonisolated func contentSharingPicker(_ picker: SCContentSharingPicker, didUpdateWith filter: SCContentFilter, for stream: SCStream?) {
        Task { @MainActor [weak self] in await self?.start(filter: filter) }
    }
    nonisolated func contentSharingPicker(_ picker: SCContentSharingPicker, didCancelFor stream: SCStream?) {
        Task { @MainActor [weak self] in
            guard let self, self.phase == .choosing else { return }
            self.phase = .idle; self.message = "No content selected. Nothing was recorded."
            SCContentSharingPicker.shared.isActive = false
        }
    }
    nonisolated func contentSharingPickerStartDidFailWithError(_ error: any Error) {
        Task { @MainActor [weak self] in self?.fail(error) }
    }
}
extension CaptureController: SCRecordingOutputDelegate {
    nonisolated func recordingOutputDidStartRecording(_ recordingOutput: SCRecordingOutput) {
        Task { @MainActor [weak self] in
            guard let self, self.recordingOutput === recordingOutput, self.phase == .starting, !self.completionDelivered else { return }
            self.timeoutTask?.cancel(); self.timeoutTask = nil
            self.phase = .recording; self.startedAt = Date(); self.message = "Recording the selected app. Demonstrate the real workflow, then stop."
        }
    }
    nonisolated func recordingOutputDidFinishRecording(_ recordingOutput: SCRecordingOutput) {
        Task { @MainActor [weak self] in
            guard let self, self.recordingOutput === recordingOutput else { return }; self.finish()
        }
    }
    nonisolated func recordingOutput(_ recordingOutput: SCRecordingOutput, didFailWithError error: any Error) {
        Task { @MainActor [weak self] in
            guard let self, self.recordingOutput === recordingOutput else { return }; self.fail(error)
        }
    }
}
extension CaptureController: SCStreamDelegate {
    nonisolated func stream(_ stream: SCStream, didStopWithError error: any Error) {
        Task { @MainActor [weak self] in
            guard let self, self.stream === stream, !self.completionDelivered else { return }
            // macOS may stop a share from the system UI. The recording-output callback,
            // not this callback or stopCapture(), decides whether the movie is complete.
            self.phase = .finalizing; self.message = "Sharing ended. Waiting for recording finalization…"
            self.armFinalizationTimeout()
        }
    }
}
