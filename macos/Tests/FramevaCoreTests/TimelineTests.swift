import XCTest
@testable import FramevaCore

final class TimelineTests: XCTestCase {
    func testRecordingTrimUsesTemporalCoverage() throws {
        var scene = ShotDraft(); scene.provider = "recording"; scene.videoAssetId = "video-1"
        scene.trimStart = 2; scene.duration = 5; scene.playbackRate = 2
        XCTAssertThrowsError(try scene.validate(recordingDuration: 11))
        XCTAssertNoThrow(try scene.validate(recordingDuration: 12))
    }
    func testRecordingRequiresRealMedia() {
        var scene = ShotDraft(); scene.provider = "recording"
        XCTAssertThrowsError(try scene.validate(recordingDuration: 10))
    }
    func testNonfiniteAndOutOfRangeMotionRejected() {
        var scene = ShotDraft(); scene.zoom = .infinity
        XCTAssertThrowsError(try scene.validate())
        scene.zoom = 1; scene.focusX = -0.1
        XCTAssertThrowsError(try scene.validate())
        scene.focusX = 0.5; scene.playbackRate = 0
        XCTAssertThrowsError(try scene.validate())
    }
    func testOldShotDecodesWithRecordingDefaults() throws {
        let decoder = JSONDecoder(); decoder.keyDecodingStrategy = .convertFromSnakeCase
        let scene = try decoder.decode(ShotDraft.self, from: Data(#"{"name":"Existing","width":1280,"height":720,"fps":24,"duration":3}"#.utf8))
        XCTAssertEqual(scene.trimStart, 0); XCTAssertEqual(scene.playbackRate, 1)
        XCTAssertEqual(scene.focusX, 0.5); XCTAssertEqual(scene.zoom, 1)
        XCTAssertNil(scene.videoAssetId)
    }
    func testClearedReferencesEncodeNull() throws {
        let encoder = JSONEncoder(); encoder.keyEncodingStrategy = .convertToSnakeCase
        let payload = try XCTUnwrap(JSONSerialization.jsonObject(with: encoder.encode(ShotDraft())) as? [String: Any])
        XCTAssertTrue(payload["video_asset_id"] is NSNull)
        XCTAssertTrue(payload["reference_asset_id"] is NSNull)
        XCTAssertTrue(payload["workflow_id"] is NSNull)
    }
    func testRecordingAndStartingPermitStopAction() {
        XCTAssertTrue(CapturePhase.recording.canStop)
        XCTAssertTrue(CapturePhase.starting.canStop)
        XCTAssertFalse(CapturePhase.finalizing.canStop)
        XCTAssertTrue(CapturePhase.finalizing.isBusy)
        XCTAssertFalse(CapturePhase.finished.isBusy)
    }
    func testSequenceWinsOverSameTimestamp() throws {
        let decoder = JSONDecoder(); decoder.keyDecodingStrategy = .convertFromSnakeCase
        let payload = #"[{"id":"older","project_id":"p","shot_id":"s","type":"generate","status":"succeeded","progress":100,"created_at":"2026-11-10T00:00:00Z","sequence":5,"params":{}},{"id":"newer","project_id":"p","shot_id":"s","type":"generate","status":"succeeded","progress":100,"created_at":"2026-11-10T00:00:00Z","sequence":6,"params":{}}]"#
        let jobs = try decoder.decode([Job].self, from: Data(payload.utf8))
        XCTAssertEqual(jobs.sorted(by: Job.newestFirst).first?.id, "newer")
    }
    func testSourceJSONIsDataNotExecutable() throws {
        let source = try JSONDecoder().decode(JSONValue.self, from: Data(#"{"features":[{"title":"<script>alert(1)</script>","evidence":[{"path":"README.md","line":7}]}]}"#.utf8))
        XCTAssertEqual(source["features"]?.array?.first?["title"]?.string, "<script>alert(1)</script>")
        XCTAssertEqual(source["features"]?.array?.first?["evidence"]?.array?.first?["line"]?.number, 7)
    }
}
