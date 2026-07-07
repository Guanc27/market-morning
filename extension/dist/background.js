// Open side panel when extension icon is clicked
chrome.runtime.onInstalled.addListener(async () => {
  await chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true });
  // Enable globally so panel persists across tabs once opened
  await chrome.sidePanel.setOptions({
    path: "sidepanel.html",
    enabled: true,
  });
});

chrome.action.onClicked.addListener(async (tab) => {
  const windowId = tab.windowId;
  if (windowId) {
    await chrome.sidePanel.open({ windowId });
  }
});

// Keyboard shortcut: Alt+M (Cmd+Shift+M on Mac)
chrome.commands.onCommand.addListener(async (command) => {
  if (command !== "open-panel" && command !== "_execute_action") return;
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (tab?.windowId) {
      await chrome.sidePanel.open({ windowId: tab.windowId });
    }
  } catch (e) {
    console.error("Market Morning: could not open side panel", e);
  }
});

// Note: Chrome does NOT allow auto-opening the side panel on browser startup
// without a user gesture (security policy). Use the shortcut or pin the panel
// once open via Chrome's pin icon in the side panel header.
