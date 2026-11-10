import Foundation
import Combine
import Darwin
import Security
import AppKit
import FramevaCore

@MainActor
final class WorkerController: ObservableObject {
    @Published private(set) var status = "Starting local worker…"
    @Published private(set) var isReady = false
    @Published private(set) var ownsProcess = false
    private(set) var client: APIClient?
    private(set) var executable: URL?
    private(set) var dataDirectory: URL
    private(set) var port: Int
    private var process: Process?
    private var logHandle: FileHandle?
    private var token = ""
    private var connecting = false
    private var installer: Process?
    private var portConfigurationError: String?

    init() {
        let env = ProcessInfo.processInfo.environment
        dataDirectory = URL(fileURLWithPath: env["FRAMEVA_DATA_DIR"] ?? NSHomeDirectory() + "/.frameva", isDirectory: true).standardizedFileURL
        let suppliedPort = Int(env["FRAMEVA_NATIVE_PORT"] ?? "8741")
        port = suppliedPort.flatMap { (1024...65535).contains($0) ? $0 : nil } ?? 8741
        if env["FRAMEVA_NATIVE_PORT"] != nil && (suppliedPort == nil || !(1024...65535).contains(suppliedPort!)) { portConfigurationError = "FRAMEVA_NATIVE_PORT must be between 1024 and 65535." }
    }
    var baseURL: URL { URL(string: "http://127.0.0.1:\(port)")! }
    var helperExecutable: URL {
        Bundle.main.bundleURL.appendingPathComponent("Contents/Helpers/FramevaWorker.app/Contents/MacOS/frameva-worker")
    }
    private func prepareToken() throws {
        if let portConfigurationError { throw StudioError(portConfigurationError) }
        guard (1024...65535).contains(port) else { throw StudioError("FRAMEVA_NATIVE_PORT must be between 1024 and 65535.") }
        try FileManager.default.createDirectory(at: dataDirectory, withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700])
        let tokenFile = dataDirectory.appendingPathComponent("token")
        if !FileManager.default.fileExists(atPath: tokenFile.path) {
            var bytes = [UInt8](repeating: 0, count: 48)
            guard SecRandomCopyBytes(kSecRandomDefault, bytes.count, &bytes) == errSecSuccess else { throw StudioError("Cannot create a secure local access token.") }
            let candidate = Data(bytes).base64EncodedString().replacingOccurrences(of: "+", with: "-").replacingOccurrences(of: "/", with: "_")
            let fd = open(tokenFile.path, O_WRONLY | O_CREAT | O_EXCL, S_IRUSR | S_IWUSR)
            if fd >= 0 {
                let handle = FileHandle(fileDescriptor: fd, closeOnDealloc: true)
                try handle.write(contentsOf: Data((candidate + "\n").utf8)); try handle.close()
            } else if errno != EEXIST { throw StudioError("Cannot create the private token file.") }
        }
        token = try String(contentsOf: tokenFile, encoding: .utf8).trimmingCharacters(in: .whitespacesAndNewlines)
        guard (32...512).contains(token.utf8.count), token.utf8.allSatisfy({ $0 >= 33 && $0 <= 126 }) else { throw StudioError("Your ~/.frameva/token file is invalid. Check it before starting the studio.") }
    }
    private func resolveExecutable() throws -> URL {
        let configured = ProcessInfo.processInfo.environment["FRAMEVA_WORKER_EXECUTABLE"] ?? UserDefaults.standard.string(forKey: "workerExecutablePath") ?? ""
        let url = configured.isEmpty ? helperExecutable : URL(fileURLWithPath: configured)
        guard FileManager.default.isExecutableFile(atPath: url.path) else {
            throw StudioError("The bundled worker was not found. Use the packaged Frameva.app, or set an absolute worker executable in Settings for development.")
        }
        return url
    }
    private func commandArguments(_ command: [String], executable: URL) -> [String] {
        executable.lastPathComponent.lowercased().hasPrefix("python") ? ["-I", "-m", "frameva"] + command : command
    }
    private func probe() async throws -> Bool {
        var request = URLRequest(url: baseURL.appendingPathComponent("api/config"), timeoutInterval: 1.5)
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        do {
            let session = URLSession(configuration: .ephemeral, delegate: RejectRedirects(), delegateQueue: nil)
            defer { session.invalidateAndCancel() }
            let (data, response) = try await session.data(for: request)
            guard let http = response as? HTTPURLResponse else { return false }
            if http.statusCode == 401 {
                throw StudioError("A worker is already running on port \(port), but it uses a different token. Stop that worker or use its shared data directory. Frameva will not launch a second worker against the database.")
            }
            guard http.statusCode == 200 else { throw StudioError("Port \(port) is occupied by an incompatible service (HTTP \(http.statusCode)). Stop it or set FRAMEVA_NATIVE_PORT before launching.") }
            guard let payload = try JSONSerialization.jsonObject(with: data) as? [String: Any],
                  let version = payload["version"] as? String,
                  let providers = payload["providers"] as? [[String: Any]],
                  providers.contains(where: { $0["id"] as? String == "preview" }) else {
                throw StudioError("Port \(port) does not identify itself as a compatible Frameva worker.")
            }
            let parts = version.split(separator: ".").compactMap { Int($0) }
            guard parts.count >= 2, parts[0] > 0 || parts[1] >= 2 else {
                throw StudioError("Frameva worker \(version) is already running. Stop it and upgrade to version 0.2 or newer before using the native recording studio.")
            }
            return true
        } catch let error as URLError {
            if [.cannotConnectToHost, .networkConnectionLost, .timedOut].contains(error.code) { return false }
            throw error
        }
    }
    func start() async throws {
        guard !connecting else { return }; connecting = true
        defer { connecting = false }
        isReady = false; status = "Connecting to the local worker…"
        try prepareToken()
        let api = APIClient(baseURL: baseURL, token: token)
        if try await probe() {
            client = api; isReady = true; ownsProcess = process?.isRunning == true && ownsProcess
            executable = try? resolveExecutable()
            status = "Connected to your existing worker"
            return
        }
        let command = try resolveExecutable(); executable = command
        let child = Process(); child.executableURL = command
        child.arguments = commandArguments(["serve", "--no-open", "--port", String(port)], executable: command)
        var environment = ProcessInfo.processInfo.environment
        environment["FRAMEVA_DATA_DIR"] = dataDirectory.path
        environment.removeValue(forKey: "FRAMEVA_TOKEN")
        environment["PYTHONUNBUFFERED"] = "1"
        child.environment = environment
        let logURL = dataDirectory.appendingPathComponent("native-worker.log")
        if !FileManager.default.fileExists(atPath: logURL.path) { FileManager.default.createFile(atPath: logURL.path, contents: nil, attributes: [.posixPermissions: 0o600]) }
        let handle = try FileHandle(forWritingTo: logURL); try handle.seekToEnd()
        child.standardOutput = handle; child.standardError = handle; child.standardInput = FileHandle.nullDevice
        child.terminationHandler = { [weak self] process in
            Task { @MainActor in
                guard let self, self.process === process else { return }
                self.isReady = false
                if self.ownsProcess { self.status = "Worker stopped (exit \(process.terminationStatus)). See ~/.frameva/native-worker.log." }
            }
        }
        try child.run(); process = child; logHandle = handle; ownsProcess = true
        do {
        for _ in 0..<80 {
            if !child.isRunning { throw StudioError("The worker exited before it was ready. Check \(logURL.path).") }
            if try await probe() {
                client = api; isReady = true; status = "Local worker ready"
                return
            }
            try await Task.sleep(nanoseconds: 250_000_000)
        }
        throw StudioError("The worker did not start in time. Check \(logURL.path).")
        } catch { await Task { @MainActor in await self.stopOwnedWorker() }.value; throw error }
    }
    func stopOwnedWorker() async {
        if let installer, installer.isRunning {
            installer.terminate()
            for _ in 0..<50 { if !installer.isRunning { break }; try? await Task.sleep(nanoseconds: 100_000_000) }
            if installer.isRunning { kill(installer.processIdentifier, SIGKILL) }
        }
        self.installer = nil
        guard ownsProcess, let child = process else { return }
        ownsProcess = false; isReady = false
        if child.isRunning { child.terminate() }
        status = "Waiting for render cleanup before stopping…"
        for _ in 0..<500 {
            if !child.isRunning { break }
            try? await Task.sleep(nanoseconds: 100_000_000)
        }
        if child.isRunning { kill(child.processIdentifier, SIGKILL) }
        try? logHandle?.close(); logHandle = nil; process = nil
    }
    func installBrowser() async throws {
        let command = try resolveExecutable()
        let child = Process(); child.executableURL = command
        child.arguments = commandArguments(["install-browser"], executable: command)
        var env = ProcessInfo.processInfo.environment; env["FRAMEVA_DATA_DIR"] = dataDirectory.path; env.removeValue(forKey: "FRAMEVA_TOKEN")
        child.environment = env; child.standardInput = FileHandle.nullDevice
        let logURL = dataDirectory.appendingPathComponent("browser-install.log")
        FileManager.default.createFile(atPath: logURL.path, contents: nil, attributes: [.posixPermissions: 0o600])
        let handle = try FileHandle(forWritingTo: logURL); defer { try? handle.close() }
        child.standardOutput = handle; child.standardError = handle
        try child.run(); installer = child
        defer { if child.isRunning { child.terminate() }; if installer === child { installer = nil } }
        let deadline = Date().addingTimeInterval(600)
        while child.isRunning {
            if Task.isCancelled || Date() > deadline { child.terminate(); throw StudioError("Browser installation stopped. See \(logURL.path).") }
            try await Task.sleep(nanoseconds: 300_000_000)
        }
        guard child.terminationStatus == 0 else { throw StudioError("Browser installation failed. See \(logURL.path).") }
    }
    func mcpConfiguration() -> String {
        guard let executable = executable ?? (try? resolveExecutable()) else { return "The bundled worker is missing. Build the native app bundle first." }
        let config: [String: Any] = ["mcpServers": ["frameva": ["type": "stdio", "command": executable.path,
            "args": commandArguments(["mcp"], executable: executable),
            "env": ["FRAMEVA_DATA_DIR": dataDirectory.path, "FRAMEVA_URL": baseURL.absoluteString]]]]
        guard let bytes = try? JSONSerialization.data(withJSONObject: config, options: [.prettyPrinted, .sortedKeys, .withoutEscapingSlashes]), let text = String(data: bytes, encoding: .utf8) else { return "Unable to format configuration." }
        return text
    }
}
