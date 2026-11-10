import Foundation
import FramevaCore

/// Worker requests are authenticated and never need an HTTP redirect. Refusing
/// redirects also prevents a local endpoint from forwarding a bearer request.
final class RejectRedirects: NSObject, URLSessionTaskDelegate, @unchecked Sendable {
    func urlSession(_ session: URLSession, task: URLSessionTask,
                    willPerformHTTPRedirection response: HTTPURLResponse,
                    newRequest request: URLRequest,
                    completionHandler: @escaping (URLRequest?) -> Void) {
        completionHandler(nil)
    }
}

final class APIClient: @unchecked Sendable {
    let baseURL: URL
    private let token: String
    private let session: URLSession
    private let decoder: JSONDecoder
    private let encoder: JSONEncoder
    init(baseURL: URL, token: String) {
        self.baseURL = baseURL; self.token = token
        let configuration = URLSessionConfiguration.ephemeral
        configuration.timeoutIntervalForRequest = 30
        configuration.timeoutIntervalForResource = 600
        configuration.httpShouldSetCookies = false
        session = URLSession(configuration: configuration, delegate: RejectRedirects(), delegateQueue: nil)
        decoder = JSONDecoder(); decoder.keyDecodingStrategy = .convertFromSnakeCase
        encoder = JSONEncoder(); encoder.keyEncodingStrategy = .convertToSnakeCase
    }
    deinit { session.invalidateAndCancel() }
    private func request(_ path: String, method: String) throws -> URLRequest {
        guard path.hasPrefix("/api/"), let url = URL(string: path, relativeTo: baseURL)?.absoluteURL,
              url.scheme == "http", url.host == "127.0.0.1",
              url.host == baseURL.host, url.port == baseURL.port,
              url.user == nil, url.password == nil, url.fragment == nil else { throw StudioError("Invalid worker API path.") }
        var request = URLRequest(url: url)
        request.httpMethod = method
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        return request
    }
    private func validate(_ response: URLResponse, data: Data) throws {
        guard let http = response as? HTTPURLResponse else { throw StudioError("The worker returned an invalid response.") }
        guard (200..<300).contains(http.statusCode) else {
            let value = try? JSONDecoder().decode(JSONValue.self, from: data)
            let detail = value?["detail"]?.string ?? value?["detail"]?.prettyPrinted() ?? "Worker request failed (HTTP \(http.statusCode))."
            throw StudioError(String(detail.prefix(2000)))
        }
    }
    func get<T: Decodable>(_ path: String, as type: T.Type = T.self) async throws -> T {
        let (data, response) = try await session.data(for: request(path, method: "GET"))
        try validate(response, data: data)
        return try decoder.decode(type, from: data)
    }
    func send<T: Decodable, Body: Encodable>(_ path: String, method: String = "POST", body: Body, as type: T.Type = T.self) async throws -> T {
        var req = try request(path, method: method)
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.httpBody = try encoder.encode(body)
        let (data, response) = try await session.data(for: req)
        try validate(response, data: data)
        return try decoder.decode(type, from: data)
    }
    func action(_ path: String, method: String = "POST") async throws -> JSONValue {
        let (data, response) = try await session.data(for: request(path, method: method))
        try validate(response, data: data)
        return try decoder.decode(JSONValue.self, from: data)
    }
    func upload(_ fileURL: URL, projectID: String, source: Bool = false) async throws -> Data {
        try Task.checkCancellation()
        guard (1...64).contains(projectID.utf8.count), projectID.utf8.allSatisfy({
            (48...57).contains($0) || (65...90).contains($0) || (97...122).contains($0) || $0 == 45 || $0 == 95
        }) else {
            throw StudioError("Invalid production identifier.")
        }
        let values = try fileURL.resourceValues(forKeys: [.fileSizeKey, .isRegularFileKey])
        let maximum = source ? 64 * 1024 * 1024 : 256 * 1024 * 1024
        guard values.isRegularFile == true, let size = values.fileSize, size <= maximum else {
            throw StudioError(source ? "Choose a source ZIP no larger than 64 MiB." : "Media must be a regular file no larger than 256 MiB. Your original recording has been kept.")
        }
        let boundary = "Frameva-\(UUID().uuidString)"
        let payloadURL = FileManager.default.temporaryDirectory.appendingPathComponent("frameva-upload-\(UUID().uuidString)")
        guard FileManager.default.createFile(atPath: payloadURL.path, contents: nil, attributes: [.posixPermissions: 0o600]) else {
            throw StudioError("Cannot prepare the private upload file. Check available disk space.")
        }
        defer { try? FileManager.default.removeItem(at: payloadURL) }
        let output = try FileHandle(forWritingTo: payloadURL)
        defer { try? output.close() }
        func write(_ text: String) throws { try output.write(contentsOf: Data(text.utf8)) }
        if !source { try write("--\(boundary)\r\nContent-Disposition: form-data; name=\"project_id\"\r\n\r\n\(projectID)\r\n") }
        let safeName = fileURL.lastPathComponent.replacingOccurrences(of: "\\", with: "_").replacingOccurrences(of: "\"", with: "_").replacingOccurrences(of: "\r", with: "_").replacingOccurrences(of: "\n", with: "_")
        let mime: String
        switch fileURL.pathExtension.lowercased() {
        case "zip": mime = "application/zip"
        case "mp4", "m4v": mime = "video/mp4"
        case "mov": mime = "video/quicktime"
        case "webm": mime = "video/webm"
        case "png": mime = "image/png"
        case "jpg", "jpeg": mime = "image/jpeg"
        case "wav": mime = "audio/wav"
        case "mp3": mime = "audio/mpeg"
        case "m4a": mime = "audio/mp4"
        default: mime = "application/octet-stream"
        }
        try write("--\(boundary)\r\nContent-Disposition: form-data; name=\"file\"; filename=\"\(safeName)\"\r\nContent-Type: \(mime)\r\n\r\n")
        let input = try FileHandle(forReadingFrom: fileURL)
        defer { try? input.close() }
        var copied = 0
        while true {
            try Task.checkCancellation()
            guard let chunk = try input.read(upToCount: 1024 * 1024), !chunk.isEmpty else { break }
            guard chunk.count <= maximum - copied else {
                throw StudioError("This file grew beyond the upload limit while it was being copied. Your original file has been kept.")
            }
            copied += chunk.count
            try output.write(contentsOf: chunk)
        }
        guard copied == size else {
            throw StudioError("This file changed while the upload was being prepared. Wait for it to finish saving, then retry.")
        }
        try write("\r\n--\(boundary)--\r\n"); try output.synchronize(); try output.close()
        try Task.checkCancellation()
        let path = source ? "/api/projects/\(projectID)/source" : "/api/assets"
        var req = try request(path, method: "POST")
        req.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")
        let (data, response) = try await session.upload(for: req, fromFile: payloadURL)
        try validate(response, data: data)
        return data
    }
    func uploadAsset(_ url: URL, projectID: String) async throws -> Asset {
        try decoder.decode(Asset.self, from: await upload(url, projectID: projectID))
    }
    func uploadSource(_ url: URL, projectID: String) async throws -> JSONValue {
        try decoder.decode(JSONValue.self, from: await upload(url, projectID: projectID, source: true))
    }
    func downloadAsset(_ asset: Asset, to destination: URL) async throws {
        guard destination.isFileURL else { throw StudioError("Choose a local file destination.") }
        try Task.checkCancellation()
        let (temporary, response) = try await session.download(for: request("/api/assets/\(asset.id)/file", method: "GET"))
        defer { try? FileManager.default.removeItem(at: temporary) }
        // Only read a bounded error body. Successful videos can be substantially
        // larger than an upload, and should not be loaded into application memory.
        if let http = response as? HTTPURLResponse, (200..<300).contains(http.statusCode) {
            try validate(response, data: Data())
        } else {
            let handle = try FileHandle(forReadingFrom: temporary)
            defer { try? handle.close() }
            let errorBody = try handle.read(upToCount: 64 * 1024) ?? Data()
            try validate(response, data: errorBody)
        }
        let attributes = try FileManager.default.attributesOfItem(atPath: temporary.path)
        guard let size = attributes[.size] as? NSNumber, size.int64Value == asset.size else {
            throw StudioError("The downloaded media is incomplete. The existing destination has been kept.")
        }
        try Task.checkCancellation()
        // Copy to the destination volume first. Never delete an existing export
        // before the complete replacement is available beside it.
        let manager = FileManager.default
        let staging = destination.deletingLastPathComponent().appendingPathComponent(".frameva-download-\(UUID().uuidString)")
        defer { try? manager.removeItem(at: staging) }
        try manager.copyItem(at: temporary, to: staging)
        try manager.setAttributes([.posixPermissions: 0o600], ofItemAtPath: staging.path)
        try Task.checkCancellation()
        if manager.fileExists(atPath: destination.path) {
            _ = try manager.replaceItemAt(destination, withItemAt: staging,
                                          backupItemName: nil, options: .usingNewMetadataOnly)
        } else {
            try manager.moveItem(at: staging, to: destination)
        }
    }
}
