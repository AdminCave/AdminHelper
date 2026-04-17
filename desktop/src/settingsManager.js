import { normalizeConnection } from "./connectionModel.js";
import {
  detectSystemLanguage,
  getIntervalMinutes,
  getSettingsDefaults,
  RDP_WINDOW_MODES,
  RDP_PERFORMANCE_PROFILES,
  RDP_CUSTOM_SIZE_PATTERN
} from "./settingsModel.js";

export function initSettings(state, t, callbacks, settingsApi, tunnelApi, authApi) {
  const settingsPromptEl = document.getElementById("settingsPrompt");
  const settingsSaveBtn = document.getElementById("settingsSaveBtn");
  const settingsCancelBtn = document.getElementById("settingsCancelBtn");
  const syncUrlField = document.getElementById("syncUrlField");
  const syncUrlInput = document.getElementById("syncUrlInput");
  const syncIntervalField = document.getElementById("syncIntervalField");
  const syncIntervalInput = document.getElementById("syncIntervalInput");
  const rdpScalingSelect = document.getElementById("rdpScalingSelect");
  const rdpWindowModeSelect = document.getElementById("rdpWindowModeSelect");
  const rdpCustomSizeField = document.getElementById("rdpCustomSizeField");
  const rdpCustomSizeInput = document.getElementById("rdpCustomSizeInput");
  const rdpPerformanceSelect = document.getElementById("rdpPerformanceSelect");
  const storePasswordsInput = document.getElementById("storePasswordsInput");
  const allowSelfSignedField = document.getElementById("allowSelfSignedField");
  const allowSelfSignedInput = document.getElementById("allowSelfSignedInput");
  const languageSelect = document.getElementById("languageSelect");
  const serverUrlField = document.getElementById("serverUrlField");
  const serverUrlInput = document.getElementById("serverUrlInput");
  const serverLogoutField = document.getElementById("serverLogoutField");
  const serverSessionUser = document.getElementById("serverSessionUser");
  const serverLogoutBtn = document.getElementById("serverLogoutBtn");
  const settingsModeBadge = document.getElementById("settingsModeBadge");
  const settingsBtn = document.getElementById("settingsBtn");

  let syncTimer = null;

  // ── Sync mode helpers ───────────────────────────────────────────────

  function getSyncMode() {
    const selected = document.querySelector('input[name="syncMode"]:checked');
    return selected ? selected.value : "local";
  }

  function setSyncMode(mode) {
    document.querySelectorAll('input[name="syncMode"]').forEach((input) => {
      input.checked = input.value === mode;
    });
    syncUrlField.classList.toggle("hidden", mode !== "sync");
    syncIntervalField.classList.toggle("hidden", mode !== "sync");
    if (allowSelfSignedField) allowSelfSignedField.classList.toggle("hidden", mode !== "sync");
    if (serverUrlField) serverUrlField.classList.toggle("hidden", mode !== "server");
    if (serverLogoutField) serverLogoutField.classList.toggle("hidden", mode !== "server" || !state.session);
    if (serverSessionUser && state.session) {
      serverSessionUser.textContent = state.session.username;
    }
  }

  function updateSettingsBadge(mode) {
    const labels = { local: t("settings.mode.local"), sync: t("settings.mode.sync"), server: "Server" };
    if (settingsModeBadge) {
      settingsModeBadge.textContent = labels[mode] || labels.local;
    }
    if (settingsBtn) {
      settingsBtn.dataset.mode = mode;
    }
  }

  function isSyncLocked() {
    const mode = (state.settings || getSettingsDefaults()).mode;
    return mode === "sync" || mode === "server";
  }

  function isPasswordStoreEnabled() {
    return Boolean((state.settings || getSettingsDefaults()).storePasswords);
  }

  function reportSyncLocked() {
    callbacks.reportError(t("error.syncLocked"));
  }

  // ── Settings prompt ─────────────────────────────────────────────────

  function openSettingsPrompt() {
    const settings = state.settings || getSettingsDefaults();
    setSyncMode(settings.mode || "local");
    syncUrlInput.value = settings.url || "";
    syncIntervalInput.value = getIntervalMinutes(settings).toString();
    if (languageSelect) {
      languageSelect.value = settings.language || detectSystemLanguage();
    }
    if (storePasswordsInput) {
      storePasswordsInput.checked = Boolean(settings.storePasswords);
    }
    if (allowSelfSignedInput) {
      allowSelfSignedInput.checked = Boolean(settings.allowSelfSignedCerts);
    }
    if (rdpScalingSelect) {
      const mode = settings.rdpScalingMode || "auto";
      rdpScalingSelect.value = ["auto", "normal", "hdpi"].includes(mode) ? mode : "auto";
    }
    if (rdpWindowModeSelect) {
      const mode = settings.rdpWindowMode || "fit";
      rdpWindowModeSelect.value = RDP_WINDOW_MODES.includes(mode) ? mode : "fit";
      toggleCustomSizeField(rdpWindowModeSelect.value);
    }
    if (rdpCustomSizeInput) {
      rdpCustomSizeInput.value = settings.rdpCustomSize || "1920x1080";
    }
    if (rdpPerformanceSelect) {
      const profile = settings.rdpPerformanceProfile || "auto";
      rdpPerformanceSelect.value = RDP_PERFORMANCE_PROFILES.includes(profile) ? profile : "auto";
    }
    if (serverUrlInput) {
      serverUrlInput.value = settings.serverUrl || "";
    }
    settingsPromptEl.classList.remove("hidden");
    settingsPromptEl.setAttribute("aria-hidden", "false");
  }

  function closeSettingsPrompt() {
    settingsPromptEl.classList.add("hidden");
    settingsPromptEl.setAttribute("aria-hidden", "true");
  }

  function toggleCustomSizeField(mode) {
    if (rdpCustomSizeField) {
      rdpCustomSizeField.classList.toggle("hidden", mode !== "custom");
    }
  }

  // ── Sync timer ──────────────────────────────────────────────────────

  function stopSyncTimer() {
    if (syncTimer) {
      clearInterval(syncTimer);
      syncTimer = null;
    }
  }

  function startSyncTimer() {
    stopSyncTimer();
    const intervalMinutes = getIntervalMinutes(state.settings || getSettingsDefaults());
    syncTimer = setInterval(() => {
      syncNow(false);
    }, intervalMinutes * 60_000);
  }

  async function syncNow(showStatusMessage) {
    const settings = state.settings || getSettingsDefaults();
    if (settings.mode !== "sync" || !settings.url) {
      return;
    }
    try {
      const connections = await settingsApi.sync(settings.url);
      state.connections = Array.isArray(connections)
        ? connections.map((connection) => normalizeConnection(connection || {}))
        : [];
      callbacks.renderConnections();
      if (showStatusMessage) {
        callbacks.showStatus(t("sync.success"));
      }
    } catch (error) {
      if (showStatusMessage) {
        callbacks.reportError(t("sync.error", { message: error.message || error }));
      }
    }
  }

  // ── Event listeners ─────────────────────────────────────────────────

  settingsSaveBtn.addEventListener("click", async (event) => {
    event.preventDefault();
    const mode = getSyncMode();
    const url = syncUrlInput.value.trim();
    const intervalMinutes = Number(syncIntervalInput.value);
    const language = languageSelect ? languageSelect.value : "de";
    const storePasswords = storePasswordsInput ? storePasswordsInput.checked : false;
    const allowSelfSignedCerts = allowSelfSignedInput ? allowSelfSignedInput.checked : false;
    const rdpScalingMode = rdpScalingSelect ? rdpScalingSelect.value : "auto";
    const rdpWindowModeRaw = rdpWindowModeSelect ? rdpWindowModeSelect.value : "fit";
    const rdpWindowMode = RDP_WINDOW_MODES.includes(rdpWindowModeRaw) ? rdpWindowModeRaw : "fit";
    const rdpCustomSize = rdpCustomSizeInput ? rdpCustomSizeInput.value.trim() : "";
    const rdpPerformanceRaw = rdpPerformanceSelect ? rdpPerformanceSelect.value : "auto";
    const rdpPerformanceProfile = RDP_PERFORMANCE_PROFILES.includes(rdpPerformanceRaw)
      ? rdpPerformanceRaw
      : "auto";
    const serverUrl = serverUrlInput ? serverUrlInput.value.trim() : "";
    const settings = {
      mode,
      url,
      intervalMinutes: getIntervalMinutes({ intervalMinutes }),
      language,
      storePasswords,
      allowSelfSignedCerts,
      rdpScalingMode: ["auto", "normal", "hdpi"].includes(rdpScalingMode)
        ? rdpScalingMode
        : "auto",
      rdpWindowMode,
      rdpCustomSize,
      rdpPerformanceProfile,
      serverUrl
    };
    try {
      if (mode === "sync" && !url) {
        callbacks.reportError(t("sync.urlRequired"));
        return;
      }
      if (mode === "sync" && !url.startsWith("https://")) {
        callbacks.reportError(t("sync.httpsOnly"));
        return;
      }
      if (mode === "sync" && !Number.isFinite(intervalMinutes)) {
        callbacks.reportError(t("sync.intervalInvalid"));
        return;
      }
      if (mode === "server" && !serverUrl) {
        callbacks.reportError(t("login.serverUrlRequired"));
        return;
      }
      if (rdpWindowMode === "custom" && !RDP_CUSTOM_SIZE_PATTERN.test(rdpCustomSize)) {
        callbacks.reportError(t("settings.rdpCustomSize.invalid"));
        return;
      }
      state.settings = settings;
      await settingsApi.save(settings);
      callbacks.setLanguage(settings.language || "de");
      updateSettingsBadge(settings.mode);
      callbacks.updateNavVisibility();
      closeSettingsPrompt();
      if (mode === "server") {
        stopSyncTimer();
        if (!state.session) {
          callbacks.showLoginScreen(serverUrl);
        }
      } else if (mode === "sync") {
        if (state.session) {
          try { await tunnelApi.stop(); } catch (_) { /* ignore */ }
        }
        state.session = null;
        callbacks.updateTunnelIndicator(null);
        await syncNow(true);
        startSyncTimer();
      } else {
        if (state.session) {
          try { await tunnelApi.stop(); } catch (_) { /* ignore */ }
        }
        state.session = null;
        callbacks.updateTunnelIndicator(null);
        stopSyncTimer();
        state.connections = await callbacks.loadConnectionsForMode();
        callbacks.renderConnections();
      }
    } catch (error) {
      callbacks.reportError(t("sync.error", { message: error.message || error }));
    }
  });

  settingsCancelBtn.addEventListener("click", (event) => {
    event.preventDefault();
    closeSettingsPrompt();
  });

  settingsPromptEl.addEventListener("click", (event) => {
    const target = event.target;
    if (target instanceof HTMLElement && target.dataset.action === "close-settings") {
      closeSettingsPrompt();
    }
  });

  document.querySelectorAll('input[name="syncMode"]').forEach((input) => {
    input.addEventListener("change", () => {
      setSyncMode(getSyncMode());
    });
  });

  if (rdpWindowModeSelect) {
    rdpWindowModeSelect.addEventListener("change", () => {
      toggleCustomSizeField(rdpWindowModeSelect.value);
    });
  }

  if (serverLogoutBtn) {
    serverLogoutBtn.addEventListener("click", async () => {
      try {
        await tunnelApi.stop();
      } catch (_) { /* ignore */ }
      try {
        await authApi.logout();
      } catch (_) { /* ignore */ }
      state.session = null;
      state.connections = [];
      callbacks.updateTunnelIndicator(null);
      callbacks.renderConnections();
      callbacks.updateNavVisibility();
      closeSettingsPrompt();
      callbacks.showLoginScreen(state.settings?.serverUrl || "");
    });
  }

  return {
    openSettingsPrompt,
    closeSettingsPrompt,
    updateSettingsBadge,
    setSyncMode,
    getSyncMode,
    isSyncLocked,
    isPasswordStoreEnabled,
    reportSyncLocked,
    syncNow,
    startSyncTimer,
    stopSyncTimer,
  };
}
