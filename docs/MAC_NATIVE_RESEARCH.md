# Native macOS capture research

Research checked 10 November 2026 against Apple and PyInstaller documentation.
This is an engineering decision record, not a claim that a macOS build or device
test has run. The research environment is Linux and has no macOS SDK or Mac GUI.

## Product direction

Frameva's Mac application should have a SwiftUI/AppKit interface, native open
and save panels, keyboard commands, a recording indicator and native video
playback. The existing Python engine can remain an implementation detail for
source inspection, project persistence, MCP, rendering and optional AI b-roll.
Opening a local website inside a web view would not implement this direction.

Use `NavigationSplitView` for projects and the selected project workspace, and
AVKit `VideoPlayer` with `AVPlayer` for preview. These are supported native
building blocks, not a requirement to rewrite the renderer in Swift. Sources:
[Apple's macOS SwiftUI tutorial](https://developer.apple.com/tutorials/swiftui/creating-a-macos-app)
and [AVKit VideoPlayer](https://developer.apple.com/documentation/avkit/videoplayer).

The source-to-launch pipeline needs three separate kinds of evidence: source
references that suggest a feature, an executable or manually performed workflow
that demonstrates the feature, and a real video recording of that workflow.
Only the second and third establish what was actually demonstrated. A source
scan cannot establish complete functional coverage, supply credentials, or
guarantee that all features work. Frameva should expose these gaps in its flow
checklist and permit one feature to have multiple takes.

## Platform baseline

**Recommend macOS 15 or later, with Xcode 16 or later as the minimum SDK/toolchain.**
Apple's current Mac capture sample uses that baseline. `SCRecordingOutput`,
`SCStreamConfiguration.captureMicrophone`, `microphoneCaptureDeviceID`, and
`showMouseClicks` have macOS 15.0 availability in the official documentation's
Markdown metadata. `SCContentSharingPicker` dates to macOS 14; ordinary
ScreenCaptureKit streams date to macOS 12.3. A lower deployment target would
need a separate recording pipeline, such as explicit sample buffers and an
AVAssetWriter, plus availability branches.

Sources:
[Mac capture sample](https://developer.apple.com/documentation/screencapturekit/capturing-screen-content-in-macos),
[SCRecordingOutput](https://developer.apple.com/documentation/screencapturekit/screcordingoutput),
[microphone](https://developer.apple.com/documentation/screencapturekit/scstreamconfiguration/capturemicrophone),
[microphone device](https://developer.apple.com/documentation/screencapturekit/scstreamconfiguration/microphonecapturedeviceid),
[mouse clicks](https://developer.apple.com/documentation/screencapturekit/scstreamconfiguration/showmouseclicks).

## Capture APIs and lifecycle

| Need | Verified Swift API | Implementation consequence |
| --- | --- | --- |
| User chooses content | `SCContentSharingPicker.shared` | Reuse Apple's singleton, not an independently initialized picker. |
| Observe selection | `picker.add(observer)` | Retain the observer and remove it on teardown. |
| Show the picker | `picker.isActive = true`; `picker.present()` | Present from an explicit user action. |
| Window-only filter | `SCContentFilter(desktopIndependentWindow: window)` | Captures the selected `SCWindow`; other app windows are not automatically included. |
| Enumerate if needed | `try await SCShareableContent.excludingDesktopWindows(true, onScreenWindowsOnly: true)` | Broad enumeration is separate from the preferred picker path. |
| Create stream | `SCStream(filter: filter, configuration: config, delegate: streamDelegate)` | Retain stream and delegate for the capture session. |
| Create writer | `SCRecordingOutput(configuration: recordingConfig, delegate: recordingDelegate)` | The delegate is passed at initialization; there is no public assignable `output.delegate` property. |
| Attach writer | `try stream.addRecordingOutput(output)` | Add before starting when the entire stream should be recorded. |
| Start | `try await stream.startCapture()` | Failure must reset the session and show an actionable error. |
| Stop stream | `try await stream.stopCapture()` | Initiates ending capture; file readiness is a separate callback. |
| Stop only recording | `try stream.removeRecordingOutput(output)` | Allows the stream to continue while the recording finishes. |

Sources:
[picker](https://developer.apple.com/documentation/screencapturekit/sccontentsharingpicker),
[window filter](https://developer.apple.com/documentation/screencapturekit/sccontentfilter/init(desktopindependentwindow:)),
[enumeration](https://developer.apple.com/documentation/screencapturekit/scshareablecontent/getexcludingdesktopwindows(_:onscreenwindowsonly:completionhandler:)),
[stream initializer](https://developer.apple.com/documentation/screencapturekit/scstream/init(filter:configuration:delegate:)),
[recording initializer](https://developer.apple.com/documentation/screencapturekit/screcordingoutput/init(configuration:delegate:)),
[add writer](https://developer.apple.com/documentation/screencapturekit/scstream/addrecordingoutput(_:)),
[start](https://developer.apple.com/documentation/screencapturekit/scstream/startcapture(completionhandler:)),
[stop](https://developer.apple.com/documentation/screencapturekit/scstream/stopcapture(completionhandler:)).

The required observer entry points to implement are:

```swift
func contentSharingPicker(_ picker: SCContentSharingPicker,
                          didUpdateWith filter: SCContentFilter,
                          for stream: SCStream?)
func contentSharingPicker(_ picker: SCContentSharingPicker,
                          didCancelFor stream: SCStream?)
func contentSharingPickerStartDidFailWithError(_ error: any Error)
```

The recording delegate methods are:

```swift
func recordingOutputDidStartRecording(_ recordingOutput: SCRecordingOutput)
func recordingOutputDidFinishRecording(_ recordingOutput: SCRecordingOutput)
func recordingOutput(_ recordingOutput: SCRecordingOutput,
                     didFailWithError error: any Error)
```

Sources:
[picker observer](https://developer.apple.com/documentation/screencapturekit/sccontentsharingpickerobserver)
and [recording delegate](https://developer.apple.com/documentation/screencapturekit/screcordingoutputdelegate).

**Do not upload, preview, or render the recorded file merely because
`stopCapture()` returned.** Apple identifies the successful recording-finished
callback as the point at which the file is ready. Keep the writer and destination
alive until that callback, and propagate recording failure separately from stream
failure. Use an explicit `idle → selecting → starting → recording → finalizing →
ready/failed` state model. The system can also stop a recording; this must leave
the application usable and preserve a successfully finalized take.

Sources:
[WWDC24 capture recording walkthrough](https://developer.apple.com/videos/play/wwdc2024/10088/)
and [macOS 15 release notes](https://developer.apple.com/documentation/macos-release-notes/macos-15-release-notes).

An original configuration sketch follows. It assumes an already authorized
filter and retained delegates; it is not a complete state machine or a
Mac-compiled sample.

```swift
import AVFoundation
import CoreMedia
import CoreVideo
import ScreenCaptureKit

@available(macOS 15.0, *)
func makeRecording(filter: SCContentFilter,
                   destination: URL,
                   streamDelegate: any SCStreamDelegate,
                   recordingDelegate: any SCRecordingOutputDelegate,
                   microphone: Bool) throws -> (SCStream, SCRecordingOutput) {
    let config = SCStreamConfiguration()
    config.width = 1920
    config.height = 1080
    config.minimumFrameInterval = CMTime(value: 1, timescale: 30)
    config.queueDepth = 5
    config.pixelFormat = kCVPixelFormatType_32BGRA
    config.showsCursor = true
    config.showMouseClicks = true
    config.includeChildWindows = true
    config.capturesAudio = true
    config.excludesCurrentProcessAudio = true
    config.captureMicrophone = microphone
    config.sampleRate = 48_000
    config.channelCount = 2

    let file = SCRecordingOutputConfiguration()
    file.outputURL = destination
    file.outputFileType = .mp4
    file.videoCodecType = .h264
    let output = SCRecordingOutput(configuration: file,
                                   delegate: recordingDelegate)
    let stream = SCStream(filter: filter, configuration: config,
                          delegate: streamDelegate)
    try stream.addRecordingOutput(output)
    return (stream, output)
}
```

Production code should preserve the selected window's aspect ratio, round video
dimensions to even values, and cap output dimensions. The fixed 16:9 sketch is
not suitable for every source window. `filter.contentRect` is expressed in screen
points; `filter.pointPixelScale` supplies its pixel scale. Retain source media at
useful resolution before fitting it into a final landscape or portrait layout.

Use `availableOutputFileTypes` and `availableVideoCodecTypes` to validate output
choices. Start with SDR H.264/MP4 for predictable playback and renderer input;
HDR streaming capability alone does not prove a tested end-to-end HDR export.
Keep queue depth modest: Apple's sample uses 5 and says not to exceed 8.

Sources:
[stream settings](https://developer.apple.com/documentation/screencapturekit/scstreamconfiguration),
[recording settings](https://developer.apple.com/documentation/screencapturekit/screcordingoutputconfiguration),
[filter geometry](https://developer.apple.com/documentation/screencapturekit/sccontentfilter),
[child windows](https://developer.apple.com/documentation/screencapturekit/scstreamconfiguration/includechildwindows).

Native delegate callbacks should marshal UI mutations to `MainActor`. Do not
assume their queue is the UI queue. Under Swift 6 concurrency checking, inspect
the SDK protocol isolation and use nonisolated forwarding callbacks where
necessary. A continuation waiting for file finalization must resolve exactly
once on success or failure, including an external stop or cancellation.

## Consent and recording scope

Apple recommends its content-sharing picker. The macOS picker grants capture of
the chosen content for that session without the app separately acquiring broad
screen-recording permission. Avoid requiring `CGPreflightScreenCaptureAccess()`
to return true before presenting this picker: it would block the session-based
authorization path. A custom window-enumeration workflow instead needs to handle
screen-recording permission and denial explicitly.

Sources:
[Apple privacy session, screen picker segment](https://developer.apple.com/videos/play/wwdc2023/10053/)
and [ScreenCaptureKit overview](https://developer.apple.com/documentation/screencapturekit).

Microphone permission is separate. Include `NSMicrophoneUsageDescription`, check
`AVCaptureDevice.authorizationStatus(for: .audio)`, and request
`await AVCaptureDevice.requestAccess(for: .audio)` when the person enables voice
recording. A denied microphone must not silently produce a claimed narration.
Hardened-runtime microphone capture uses the
`com.apple.security.device.audio-input` entitlement. Do not request camera access
for a feature that does not use a camera.

Sources:
[media authorization](https://developer.apple.com/documentation/bundleresources/requesting-authorization-for-media-capture-on-macos),
[requestAccess](https://developer.apple.com/documentation/avfoundation/avcapturedevice/requestaccess(for:completionhandler:)),
[audio input entitlement](https://developer.apple.com/documentation/bundleresources/entitlements/com.apple.security.device.audio-input).

For a broad-screen permission path, the documented check/request functions are
`CGPreflightScreenCaptureAccess()` and `CGRequestScreenCaptureAccess()`. Do not
infer authorization from window titles or try to change the TCC database.
Apple's current framework overview also names `NSScreenCaptureUsageDescription`;
include a clear purpose string and verify behavior on the supported OS versions.
`NSAudioCaptureUsageDescription` documents Core Audio system-audio capture;
it is not a substitute for ScreenCaptureKit's session authorization.

Sources:
[Apple DTS permission clarification](https://developer.apple.com/forums/thread/839069?answerId=898801022)
and [system-audio usage description](https://developer.apple.com/documentation/bundleresources/information-property-list/nsaudiocaptureusagedescription).

Recording selected content does not automate its controls. For web products,
Playwright can replay an approved flow and record actual browser frames. For
native products, the first usable path is a guided manual take; later native
automation needs its own Accessibility permission and app-specific validation.
Cursor visibility and click decoration are not structured interaction telemetry.
Precise cinematic zoom needs recorded event timestamps and focus regions, or
user-edited keyframes. Do not claim that the SCRecordingOutput API supplies a
complete semantic action timeline.

## Python worker and release packaging

Keep the Swift process responsible for native UI and ScreenCaptureKit. Launch the
bundled Python worker with `Process`, an absolute executable URL, and an argument
array. Use the existing loopback-only authenticated API. Keep secrets out of
arguments, URLs and logs; load the private token from Frameva's configured data
directory. Readiness needs an authenticated health check with a timeout, not a
fixed sleep. Stop only a worker owned by this application instance. A worker
failure should produce a recoverable error, not an invisible native window.

Use a PyInstaller one-folder worker bundle on the target OS. Build arm64 and
x86_64 releases separately unless the complete interpreter/dependency graph
supports universal2. PyInstaller validates architecture compatibility; merging
two already-frozen executables with `lipo` is not supported. Package dynamic
imports, static resources, workflow JSON and the FFmpeg binary explicitly and
smoke-test their lookup from outside the checkout. The user-facing executable
remains the Swift application.

Sources:
[PyInstaller architecture and signing notes](https://pyinstaller.org/en/stable/feature-notes.html),
[PyInstaller usage](https://pyinstaller.org/en/stable/usage.html).

Apple reserves `Contents/MacOS` or `Contents/Helpers` for helper executables,
`Contents/Frameworks` for frameworks/dylibs, and `Contents/Resources` for data.
A nested worker `.app` under Helpers, built with PyInstaller's bundle support,
is preferable to dumping a mixed code/data tree into Resources. If preserving a
nonstandard Python layout, move code into proper locations and use internal
symlinks as Apple documents. Never write caches, downloaded models, tokens,
SQLite or generated media into the signed application bundle.

Sources:
[bundle placement](https://developer.apple.com/documentation/bundleresources/placing-content-in-a-bundle)
and [nonstandard code structures](https://developer.apple.com/documentation/xcode/embedding-nonstandard-code-structures-in-a-bundle).

Sign nested code from the inside out, with the intended entitlements per
executable, then sign the outer app. Apple advises against `codesign --deep` for
signing; it is suitable for verification. A distribution build needs Developer
ID signing, hardened runtime, notarization and stapling. Use Xcode's `notarytool`
and `stapler` tooling. Ad-hoc signing is useful for local development but is not
a notarized release and can invalidate retained privacy grants between builds.

Sources:
[distribution signing](https://developer.apple.com/documentation/xcode/creating-distribution-signed-code-for-the-mac),
[notarization](https://developer.apple.com/documentation/security/customizing-the-notarization-workflow),
[Apple DTS on ad-hoc identity and capture grants](https://developer.apple.com/forums/thread/819406).

## Required Mac verification before a release claim

- Build and launch the app on supported arm64 and x86_64 macOS hosts; validate
  the bundled worker and FFmpeg from a clean user account without Python.
- Exercise picker selection, cancellation, microphone allow/deny, system stop,
  target-window closure, app quit during recording, and a failed file write.
- Record actual typing, navigation, animation and scrolling; inspect audio and
  cursor visibility, preserved aspect ratio, duration, and final file playback.
- Import the finalized take, trim it, render a launch shot, export multiple
  shots, and replay the resulting MP4 in AVKit and QuickTime.
- Verify code signatures, notarization ticket and Gatekeeper behavior of the
  downloaded package. A CI workflow file alone is not evidence of a passing run.
- Maintain a feature-to-flow checklist. A video that demonstrates several flows
  is not proof that every function in an arbitrary source repository was covered.

These are outstanding native platform checks until actual Mac evidence is
recorded in `VERIFICATION.md`; Linux engine tests cannot substitute for them.
