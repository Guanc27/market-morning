import Foundation

final class BackendManager {
    static let shared = BackendManager()

    private let healthURL = URL(string: "http://127.0.0.1:8742/health")!
    private var process: Process?
    private var ownsProcess = false
    private var healthTimer: Timer?

    var isOnline = false
    var onStatusChange: ((Bool) -> Void)?

    private init() {}

    func start() {
        Task {
            if await pingHealth() {
                setOnline(true)
                startHealthPolling()
                return
            }
            guard let backendDir = Self.locateBackendDirectory() else {
                NSLog("Market Morning: backend directory not found")
                setOnline(false)
                return
            }
            guard spawnBackend(at: backendDir) else {
                setOnline(false)
                return
            }
            for attempt in 1...40 {
                try? await Task.sleep(nanoseconds: 500_000_000)
                if await pingHealth() {
                    setOnline(true)
                    startHealthPolling()
                    return
                }
                if attempt % 4 == 0 {
                    NSLog("Market Morning: waiting for backend (%d/40)", attempt)
                }
            }
            setOnline(false)
        }
    }

    func stop() {
        healthTimer?.invalidate()
        healthTimer = nil
        guard ownsProcess, let process, process.isRunning else { return }
        process.terminate()
        self.process = nil
        ownsProcess = false
    }

    private func spawnBackend(at backendDir: URL) -> Bool {
        let uvicorn = backendDir.appendingPathComponent(".venv/bin/uvicorn")
        guard FileManager.default.isExecutableFile(atPath: uvicorn.path) else {
            NSLog("Market Morning: uvicorn missing at %@", uvicorn.path)
            return false
        }

        let proc = Process()
        proc.executableURL = uvicorn
        proc.arguments = ["app.main:app", "--host", "127.0.0.1", "--port", "8742"]
        proc.currentDirectoryURL = backendDir
        var env = ProcessInfo.processInfo.environment
        env["PYTHONUNBUFFERED"] = "1"
        proc.environment = env

        do {
            try proc.run()
            process = proc
            ownsProcess = true
            return true
        } catch {
            NSLog("Market Morning: failed to start backend: %@", error.localizedDescription)
            return false
        }
    }

    private func startHealthPolling() {
        healthTimer?.invalidate()
        healthTimer = Timer.scheduledTimer(withTimeInterval: 20, repeats: true) { [weak self] _ in
            Task { [weak self] in
                guard let self else { return }
                let ok = await self.pingHealth()
                self.setOnline(ok)
            }
        }
    }

    private func pingHealth() async -> Bool {
        var request = URLRequest(url: healthURL)
        request.timeoutInterval = 2
        do {
            let (_, response) = try await URLSession.shared.data(for: request)
            guard let http = response as? HTTPURLResponse else { return false }
            return (200..<300).contains(http.statusCode)
        } catch {
            return false
        }
    }

    private func setOnline(_ online: Bool) {
        guard online != isOnline else { return }
        isOnline = online
        DispatchQueue.main.async { [weak self] in
            guard let self else { return }
            self.onStatusChange?(online)
        }
    }

    static func locateBackendDirectory() -> URL? {
        if let env = ProcessInfo.processInfo.environment["MM_BACKEND_DIR"] {
            let url = URL(fileURLWithPath: env, isDirectory: true)
            if isBackendRoot(url) { return url }
        }

        let bundle = Bundle.main.bundleURL
        let candidates = [
            bundle.deletingLastPathComponent().appendingPathComponent("backend"),
            bundle.deletingLastPathComponent().deletingLastPathComponent().appendingPathComponent("backend"),
        ]
        for url in candidates {
            if isBackendRoot(url) { return url }
        }
        return nil
    }

    private static func isBackendRoot(_ url: URL) -> Bool {
        FileManager.default.fileExists(atPath: url.appendingPathComponent("app/main.py").path)
    }
}
