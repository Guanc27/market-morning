import AppKit
import WebKit

final class PanelWindowController: NSWindowController, NSWindowDelegate, WKScriptMessageHandler {
    private static let frameKey = "mm.panel.frame"
    private static let alwaysOnTopKey = "mm.panel.alwaysOnTop"
    /// Name of the JS→native bridge: `window.webkit.messageHandlers.ping.postMessage(...)`
    private static let pingHandlerName = "ping"

    private let webView: WKWebView
    private var webViewTopConstraint: NSLayoutConstraint?
    private weak var webContainer: NSView?
    /// Token returned by `requestUserAttention`, used to cancel the bounce once focused.
    private var attentionRequestID: Int?

    var isVisible: Bool {
        guard let window else { return false }
        return window.isVisible && !window.isMiniaturized
    }

    init() {
        let defaults = UserDefaults.standard
        let alwaysOnTop = defaults.bool(forKey: Self.alwaysOnTopKey)

        let rect = Self.initialFrame(defaults: defaults)

        webView = WKWebView(frame: .zero, configuration: WKWebViewConfiguration())

        let style: NSWindow.StyleMask = [.titled, .closable, .miniaturizable, .resizable, .fullSizeContentView]
        let window = NSWindow(
            contentRect: rect,
            styleMask: style,
            backing: .buffered,
            defer: false
        )
        window.title = "Market Morning"
        window.titlebarAppearsTransparent = true
        window.titleVisibility = .hidden
        window.isMovableByWindowBackground = true
        window.backgroundColor = Self.creamBackground
        window.level = alwaysOnTop ? .floating : .normal
        window.collectionBehavior = [.moveToActiveSpace, .fullScreenAuxiliary, .participatesInCycle]
        window.isReleasedWhenClosed = false
        window.setFrameAutosaveName("MarketMorningPanel")

        super.init(window: window)
        window.delegate = self
        setupWebView()
        setupBridge()
        loadUI()
        ensureOnScreen()
    }

    @available(*, unavailable)
    required init?(coder: NSCoder) {
        fatalError("init(coder:) has not been implemented")
    }

    private static func initialFrame(defaults: UserDefaults) -> NSRect {
        let fallback = NSRect(x: 0, y: 0, width: 420, height: 820)
        guard let saved = defaults.string(forKey: frameKey) else { return fallback }
        let restored = NSRectFromString(saved)
        guard restored.width > 200, restored.height > 300 else { return fallback }
        return restored
    }

    private static let creamBackground = NSColor(
        srgbRed: 246 / 255,
        green: 244 / 255,
        blue: 239 / 255,
        alpha: 1
    )

    private func setupWebView() {
        guard let window else { return }

        let container = NSView(frame: window.contentView?.bounds ?? .zero)
        container.autoresizingMask = [.width, .height]
        container.wantsLayer = true
        container.layer?.backgroundColor = Self.creamBackground.cgColor

        webView.translatesAutoresizingMaskIntoConstraints = false
        container.addSubview(webView)
        window.contentView = container
        webContainer = container

        let top = webView.topAnchor.constraint(equalTo: container.topAnchor)
        webViewTopConstraint = top

        NSLayoutConstraint.activate([
            webView.leadingAnchor.constraint(equalTo: container.leadingAnchor),
            webView.trailingAnchor.constraint(equalTo: container.trailingAnchor),
            webView.bottomAnchor.constraint(equalTo: container.bottomAnchor),
            top,
        ])

        updateWebViewTopInset()
    }

    /// Registers the JS→native message bridge so the web UI can request a Dock bounce.
    private func setupBridge() {
        let controller = webView.configuration.userContentController
        controller.removeScriptMessageHandler(forName: Self.pingHandlerName)
        controller.add(self, name: Self.pingHandlerName)
    }

    // MARK: - WKScriptMessageHandler

    func userContentController(
        _ userContentController: WKUserContentController,
        didReceive message: WKScriptMessage
    ) {
        guard message.name == Self.pingHandlerName else { return }
        // Payload: { type: "generation-done", kind: "brief" | "picks" | "explore" | "portfolio" }
        let type = (message.body as? [String: Any])?["type"] as? String
        if type == "generation-done" {
            bounceDock()
        }
    }

    /// Bounces the Dock icon to get the user's attention — but only when the app is
    /// not frontmost, so we never nag while they're already watching the panel.
    private func bounceDock() {
        guard !NSApp.isActive else { return }
        // `.informationalRequest` bounces the Dock icon once (a subtle "ping").
        // Use `.criticalRequest` instead to bounce continuously until the app is focused.
        attentionRequestID = NSApp.requestUserAttention(.informationalRequest)
    }

    /// Clears any pending attention request so the Dock stops bouncing once focused.
    func cancelAttention() {
        if let id = attentionRequestID {
            NSApp.cancelUserAttentionRequest(id)
            attentionRequestID = nil
        }
    }

    private func titlebarInset(for window: NSWindow) -> CGFloat {
        let layoutHeight = window.contentLayoutRect.height
        let inset = window.frame.height - layoutHeight
        return max(inset, 28)
    }

    private func updateWebViewTopInset() {
        guard let window, let top = webViewTopConstraint else { return }
        let safe = webContainer?.safeAreaInsets.top ?? 0
        top.constant = max(titlebarInset(for: window), safe)
    }

    private func loadUI() {
        guard let webDir = Bundle.main.resourceURL?.appendingPathComponent("web", isDirectory: true),
              FileManager.default.fileExists(atPath: webDir.path)
        else {
            let html = """
            <html><body style="font:14px -apple-system;padding:24px">
            <h2>UI bundle missing</h2>
            <p>Rebuild with <code>./scripts/build-mac-app.sh</code></p>
            </body></html>
            """
            webView.loadHTMLString(html, baseURL: nil)
            return
        }
        let index = webDir.appendingPathComponent("sidepanel.html")
        webView.loadFileURL(index, allowingReadAccessTo: webDir)
    }

    func toggle() {
        if isVisible {
            hide()
        } else {
            show()
        }
    }

    func show() {
        guard let window else { return }
        if window.isMiniaturized {
            window.deminiaturize(nil)
        }
        ensureOnScreen()
        window.makeKeyAndOrderFront(nil)
        updateWebViewTopInset()
        NSApp.activate(ignoringOtherApps: true)
    }

    func hide() {
        saveFrame()
        window?.orderOut(nil)
    }

    func setAlwaysOnTop(_ enabled: Bool) {
        UserDefaults.standard.set(enabled, forKey: Self.alwaysOnTopKey)
        window?.level = enabled ? .floating : .normal
    }

    var alwaysOnTop: Bool {
        window?.level == .floating
    }

    func reloadUI() {
        loadUI()
    }

    private func ensureOnScreen() {
        guard let window else { return }
        let screen = window.screen ?? NSScreen.main ?? NSScreen.screens.first
        guard let visible = screen?.visibleFrame else {
            window.center()
            return
        }
        var frame = window.frame
        if frame.width < 200 || frame.height < 300 {
            frame.size = NSSize(width: 420, height: 820)
        }
        if !visible.intersects(frame) {
            frame.origin = NSPoint(
                x: visible.midX - frame.width / 2,
                y: visible.midY - frame.height / 2
            )
            window.setFrame(frame, display: true)
            return
        }
        if frame.maxX > visible.maxX {
            frame.origin.x = visible.maxX - frame.width
        }
        if frame.minX < visible.minX {
            frame.origin.x = visible.minX
        }
        if frame.maxY > visible.maxY {
            frame.origin.y = visible.maxY - frame.height
        }
        if frame.minY < visible.minY {
            frame.origin.y = visible.minY
        }
        window.setFrame(frame, display: true)
    }

    private func saveFrame() {
        guard let window else { return }
        UserDefaults.standard.set(NSStringFromRect(window.frame), forKey: Self.frameKey)
    }

    deinit {
        saveFrame()
    }

    func windowShouldClose(_ sender: NSWindow) -> Bool {
        hide()
        return false
    }

    func windowDidResize(_ notification: Notification) {
        updateWebViewTopInset()
    }

    func windowDidBecomeKey(_ notification: Notification) {
        updateWebViewTopInset()
    }
}
