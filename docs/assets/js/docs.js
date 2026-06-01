(function () {
  const tabs = document.querySelectorAll("[data-connect-tab]");
  const panels = document.querySelectorAll("[data-connect-panel]");

  if (tabs.length === 0 || panels.length === 0) {
    return;
  }

  function activateTab(tabId) {
    for (const tab of tabs) {
      const isActive = tab.dataset.connectTab === tabId;
      tab.classList.toggle("connect-tab--active", isActive);
      tab.setAttribute("aria-selected", isActive ? "true" : "false");
    }

    for (const panel of panels) {
      const isActive = panel.dataset.connectPanel === tabId;
      panel.hidden = !isActive;
    }
  }

  for (const tab of tabs) {
    tab.addEventListener("click", () => {
      activateTab(tab.dataset.connectTab);
    });
  }

  activateTab("cursor");
})();
