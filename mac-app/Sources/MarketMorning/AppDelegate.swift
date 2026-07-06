import AppKit

final class AppDelegate: NSObject, NSApplicationDelegate {
    private var statusItem: NSStatusItem!
    private let panel = PanelWindowController()
    private var globalMonitor: Any?
    private var localMonitor: Any?

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.regular)
        setupStatusItem()
        setupHotkeys()
        BackendManager.shared.onStatusChange = { [weak self] online in
            self?.updateStatusIcon(online: online)
        }
        BackendManager.shared.start()
        updateStatusIcon(online: BackendManager.shared.isOnline)

        DispatchQueue.main.asyncAfter(deadline: .now() + 0.35) { [weak self] in
            self?.panel.show()
        }
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        false
    }

    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        panel.show()
        return true
    }

    func applicationDidBecomeActive(_ notification: Notification) {
        panel.cancelAttention()
        if !panel.isVisible {
            panel.show()
        }
    }

    func applicationWillTerminate(_ notification: Notification) {
        if let globalMonitor { NSEvent.removeMonitor(globalMonitor) }
        if let localMonitor { NSEvent.removeMonitor(localMonitor) }
        BackendManager.shared.stop()
    }

    private func setupStatusItem() {
        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.squareLength)
        updateStatusIcon(online: false)

        if let button = statusItem.button {
            button.target = self
            button.action = #selector(statusItemClicked(_:))
            button.sendAction(on: [.leftMouseUp])
        }
    }

    @objc private func statusItemClicked(_ sender: NSStatusBarButton) {
        let event = NSApp.currentEvent
        if event?.modifierFlags.contains(.control) == true || event?.type == .rightMouseUp {
            showContextMenu(at: sender)
            return
        }
        panel.toggle()
    }

    private func showContextMenu(at button: NSStatusBarButton) {
        let menu = NSMenu()
        let showTitle = panel.isVisible ? "Hide Panel" : "Show Panel"
        menu.addItem(withTitle: showTitle, action: #selector(togglePanel), keyEquivalent: "m")
            .keyEquivalentModifierMask = [.command, .shift]

        let pin = NSMenuItem(
            title: "Always on Top",
            action: #selector(toggleAlwaysOnTop),
            keyEquivalent: ""
        )
        pin.state = panel.alwaysOnTop ? .on : .off
        menu.addItem(pin)

        menu.addItem(.separator())
        menu.addItem(withTitle: "Reload UI", action: #selector(reloadUI), keyEquivalent: "r")
        menu.addItem(withTitle: "Restart Backend", action: #selector(restartBackend), keyEquivalent: "")
        menu.addItem(.separator())
        menu.addItem(withTitle: "Quit Market Morning", action: #selector(quitApp), keyEquivalent: "q")

        menu.items.forEach { $0.target = self }
        menu.popUp(positioning: nil, at: NSPoint(x: 0, y: button.bounds.height + 4), in: button)
    }

    private func setupHotkeys() {
        localMonitor = NSEvent.addLocalMonitorForEvents(matching: .keyDown) { [weak self] event in
            guard let self else { return event }
            if event.modifierFlags.contains([.command, .shift]),
               event.charactersIgnoringModifiers?.lowercased() == "m" {
                self.panel.toggle()
                return nil
            }
            return event
        }

        globalMonitor = NSEvent.addGlobalMonitorForEvents(matching: .keyDown) { [weak self] event in
            guard let self else { return }
            if event.modifierFlags.contains([.command, .shift]),
               event.charactersIgnoringModifiers?.lowercased() == "m" {
                DispatchQueue.main.async { self.panel.toggle() }
            }
        }
    }

    @objc private func togglePanel() {
        panel.toggle()
    }

    @objc private func toggleAlwaysOnTop() {
        panel.setAlwaysOnTop(!panel.alwaysOnTop)
    }

    @objc private func reloadUI() {
        panel.reloadUI()
    }

    @objc private func restartBackend() {
        BackendManager.shared.stop()
        BackendManager.shared.start()
    }

    @objc private func quitApp() {
        NSApp.terminate(nil)
    }

    private func updateStatusIcon(online: Bool) {
        guard let button = statusItem.button else { return }
        let symbol = online ? "sun.max.fill" : "sun.max"
        if #available(macOS 11.0, *) {
            button.image = NSImage(systemSymbolName: symbol, accessibilityDescription: "Market Morning")
            button.image?.isTemplate = true
        } else {
            button.title = "MM"
        }
        button.toolTip = online
            ? "Market Morning — backend online (click to toggle panel)"
            : "Market Morning — backend offline (starting…)"
    }
}
