import Foundation

public enum JSONValue: Codable, Equatable, Sendable {
    case string(String), number(Double), bool(Bool), object([String: JSONValue]), array([JSONValue]), null
    public init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()
        if container.decodeNil() { self = .null }
        else if let value = try? container.decode(Bool.self) { self = .bool(value) }
        else if let value = try? container.decode(Double.self) { self = .number(value) }
        else if let value = try? container.decode(String.self) { self = .string(value) }
        else if let value = try? container.decode([String: JSONValue].self) { self = .object(value) }
        else { self = .array(try container.decode([JSONValue].self)) }
    }
    public func encode(to encoder: Encoder) throws {
        var c = encoder.singleValueContainer()
        switch self {
        case .string(let v): try c.encode(v)
        case .number(let v): try c.encode(v)
        case .bool(let v): try c.encode(v)
        case .object(let v): try c.encode(v)
        case .array(let v): try c.encode(v)
        case .null: try c.encodeNil()
        }
    }
    public var string: String? { if case .string(let value) = self { return value }; return nil }
    public var number: Double? { if case .number(let value) = self { return value }; return nil }
    public var object: [String: JSONValue]? { if case .object(let value) = self { return value }; return nil }
    public var array: [JSONValue]? { if case .array(let value) = self { return value }; return nil }
    public subscript(_ key: String) -> JSONValue? { object?[key] }
    public func prettyPrinted() -> String {
        let encoder = JSONEncoder(); encoder.outputFormatting = [.prettyPrinted, .sortedKeys, .withoutEscapingSlashes]
        return (try? String(data: encoder.encode(self), encoding: .utf8)) ?? "{}"
    }
}

public struct Project: Codable, Identifiable, Hashable, Sendable {
    public var id: String
    public var name: String
    public var description: String
    public var createdAt: String
    public var updatedAt: String
}
public struct Asset: Decodable, Identifiable, Hashable, Sendable {
    public var id: String
    public var projectId: String
    public var name: String
    public var kind: String
    public var mimeType: String
    public var size: Int64
    public var duration: Double?
    public var videoDuration: Double?
    public var width: Int?
    public var height: Int?
    public var jobId: String?
    public var createdAt: String
    public var captureReport: JSONValue?
    public static func == (lhs: Asset, rhs: Asset) -> Bool { lhs.id == rhs.id }
    public func hash(into hasher: inout Hasher) { hasher.combine(id) }
}
public struct Job: Decodable, Identifiable, Sendable {
    public var id: String
    public var projectId: String
    public var shotId: String?
    public var type: String
    public var status: String
    public var progress: Double
    public var error: String?
    public var assetId: String?
    public var createdAt: String
    public var sequence: Int64?
    public var params: JSONValue
    public var isActive: Bool { status == "queued" || status == "running" }
    public static func newestFirst(_ a: Job, _ b: Job) -> Bool {
        if let lhs = a.sequence, let rhs = b.sequence { return lhs > rhs }
        return a.createdAt > b.createdAt
    }
}
public struct Shot: Decodable, Identifiable, Sendable {
    public var id: String
    public var projectId: String
    public var position: Int
    public var draft: ShotDraft
    private enum CodingKeys: String, CodingKey { case id, projectId, position }
    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        projectId = try c.decode(String.self, forKey: .projectId)
        position = try c.decode(Int.self, forKey: .position)
        draft = try ShotDraft(from: decoder)
    }
}

public struct ShotDraft: Codable, Equatable, Sendable {
    public var name = "New scene"
    public var prompt = ""
    public var negativePrompt = ""
    public var provider = "preview"
    public var workflowId: String? = nil
    public var referenceAssetId: String? = nil
    public var videoAssetId: String? = nil
    public var camera = "dolly_in"
    public var style = "cinematic"
    public var width = 1280
    public var height = 720
    public var duration = 4.0
    public var fps = 30
    public var seed: UInt64 = 42
    public var headline = ""
    public var caption = ""
    public var brandColor = "#b8ff65"
    public var layout = "showcase"
    public var trimStart = 0.0
    public var playbackRate = 1.0
    public var focusX = 0.5
    public var focusY = 0.5
    public var zoom = 1.0
    public var keepAudio = true
    public init() {}
    private enum CodingKeys: String, CodingKey {
        case name, prompt, negativePrompt, provider, workflowId, referenceAssetId, videoAssetId
        case camera, style, width, height, duration, fps, seed, headline, caption, brandColor, layout
        case trimStart, playbackRate, focusX, focusY, zoom, keepAudio
    }
    public init(from decoder: Decoder) throws {
        self.init()
        let c = try decoder.container(keyedBy: CodingKeys.self)
        name = try c.decodeIfPresent(String.self, forKey: .name) ?? name
        prompt = try c.decodeIfPresent(String.self, forKey: .prompt) ?? prompt
        negativePrompt = try c.decodeIfPresent(String.self, forKey: .negativePrompt) ?? negativePrompt
        provider = try c.decodeIfPresent(String.self, forKey: .provider) ?? provider
        workflowId = try c.decodeIfPresent(String.self, forKey: .workflowId)
        referenceAssetId = try c.decodeIfPresent(String.self, forKey: .referenceAssetId)
        videoAssetId = try c.decodeIfPresent(String.self, forKey: .videoAssetId)
        camera = try c.decodeIfPresent(String.self, forKey: .camera) ?? camera
        style = try c.decodeIfPresent(String.self, forKey: .style) ?? style
        width = try c.decodeIfPresent(Int.self, forKey: .width) ?? width
        height = try c.decodeIfPresent(Int.self, forKey: .height) ?? height
        duration = try c.decodeIfPresent(Double.self, forKey: .duration) ?? duration
        fps = try c.decodeIfPresent(Int.self, forKey: .fps) ?? fps
        seed = try c.decodeIfPresent(UInt64.self, forKey: .seed) ?? seed
        headline = try c.decodeIfPresent(String.self, forKey: .headline) ?? headline
        caption = try c.decodeIfPresent(String.self, forKey: .caption) ?? caption
        brandColor = try c.decodeIfPresent(String.self, forKey: .brandColor) ?? brandColor
        layout = try c.decodeIfPresent(String.self, forKey: .layout) ?? layout
        trimStart = try c.decodeIfPresent(Double.self, forKey: .trimStart) ?? trimStart
        playbackRate = try c.decodeIfPresent(Double.self, forKey: .playbackRate) ?? playbackRate
        focusX = try c.decodeIfPresent(Double.self, forKey: .focusX) ?? focusX
        focusY = try c.decodeIfPresent(Double.self, forKey: .focusY) ?? focusY
        zoom = try c.decodeIfPresent(Double.self, forKey: .zoom) ?? zoom
        keepAudio = try c.decodeIfPresent(Bool.self, forKey: .keepAudio) ?? keepAudio
    }
    public func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(name, forKey: .name)
        try c.encode(prompt, forKey: .prompt)
        try c.encode(negativePrompt, forKey: .negativePrompt)
        try c.encode(provider, forKey: .provider)
        try c.encode(workflowId, forKey: .workflowId)
        try c.encode(referenceAssetId, forKey: .referenceAssetId)
        try c.encode(videoAssetId, forKey: .videoAssetId)
        try c.encode(camera, forKey: .camera)
        try c.encode(style, forKey: .style)
        try c.encode(width, forKey: .width)
        try c.encode(height, forKey: .height)
        try c.encode(duration, forKey: .duration)
        try c.encode(fps, forKey: .fps)
        try c.encode(seed, forKey: .seed)
        try c.encode(headline, forKey: .headline)
        try c.encode(caption, forKey: .caption)
        try c.encode(brandColor, forKey: .brandColor)
        try c.encode(layout, forKey: .layout)
        try c.encode(trimStart, forKey: .trimStart)
        try c.encode(playbackRate, forKey: .playbackRate)
        try c.encode(focusX, forKey: .focusX)
        try c.encode(focusY, forKey: .focusY)
        try c.encode(zoom, forKey: .zoom)
        try c.encode(keepAudio, forKey: .keepAudio)
    }
    public func validate(recordingDuration: Double? = nil) throws {
        guard !name.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { throw StudioError("Give the scene a name.") }
        guard name.count <= 120, headline.count <= 120, caption.count <= 300 else { throw StudioError("Use at most 120 characters for the name/headline and 300 for the caption.") }
        guard width >= 64, height >= 64, width <= 2560, height <= 2560, width.isMultiple(of: 2), height.isMultiple(of: 2) else { throw StudioError("Video dimensions must be even, between 64 and 2560 pixels.") }
        guard duration.isFinite, (1...120).contains(duration), (8...30).contains(fps) else { throw StudioError("Use 1–120 seconds and 8–30 frames per second.") }
        guard playbackRate.isFinite, (0.25...4).contains(playbackRate), trimStart.isFinite, trimStart >= 0,
              focusX.isFinite, focusY.isFinite, (0...1).contains(focusX), (0...1).contains(focusY),
              zoom.isFinite, (1...2.5).contains(zoom) else { throw StudioError("Review the trim, speed, focus, and zoom values.") }
        guard brandColor.range(of: "^#[0-9a-fA-F]{6}$", options: .regularExpression) != nil else { throw StudioError("Use a six-digit brand color, such as #b8ff65.") }
        if provider == "recording" {
            guard videoAssetId != nil else { throw StudioError("Choose a recorded or imported video.") }
            if let available = recordingDuration, trimStart + duration * playbackRate > available + 0.04 {
                throw StudioError("This scene needs more footage than the recording contains. Reduce the duration, trim, or speed.")
            }
        }
    }
}

public struct StudioError: LocalizedError, Sendable {
    public let message: String
    public init(_ message: String) { self.message = message }
    public var errorDescription: String? { message }
}
public enum CapturePhase: Equatable, Sendable {
    case idle, choosing, starting, recording, stopping, finalizing, finished, failed
    public var isBusy: Bool { [.choosing, .starting, .recording, .stopping, .finalizing].contains(self) }
    public var canStop: Bool { self == .recording || self == .starting }
    public var label: String {
        switch self {
        case .idle: return "Ready to record"
        case .choosing: return "Choose an app window"
        case .starting: return "Starting capture…"
        case .recording: return "Recording"
        case .stopping: return "Stopping capture…"
        case .finalizing: return "Finalizing the movie…"
        case .finished: return "Recording finished"
        case .failed: return "Capture needs attention"
        }
    }
}
