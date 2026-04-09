import { translations } from "./i18n.js";
import { createMonitoringApi } from "./monitoringApi.js";
import { initMonitoring } from "./monitoring.js";
import { createAnsibleApi } from "./ansibleApi.js";
import { initAnsible } from "./ansible.js";
import {
  createAuthApi,
  createConnectionsApi,
  createPasswordApi,
  createSettingsApi,
  createTunnelApi,
  getClientInfo,
  getTauriBridge
} from "./platformApi.js";
import { detectSystemLanguage, getSettingsDefaults } from "./settingsModel.js";

import { initScrollAcceleration } from "./scrollUtils.js";
import { initStatus } from "./statusMessages.js";
import { initRendering } from "./connectionRenderer.js";
import { initEditor } from "./connectionEditor.js";
import { initPasswordPrompt } from "./passwordPrompt.js";
import { initConnectFlow } from "./connectFlow.js";
import { initSettings } from "./settingsManager.js";
import { initAuth } from "./authLogin.js";
import { initDashboard } from "./dashboard.js";

(() => {
  // ── Shared state ────────────────────────────────────────────────────

  const state = {
    connections: [],
    selectedId: null,
    filter: "single",
    search: "",
    view: "list",
    session: null,
    tunnels: [],
    activeView: "dashboard",
    monitorChecks: [],
    monitorAlertRules: [],
    monitorAlertLog: [],
    monitorServers: [],
    monitorTab: "overview",
    monitorFilters: { server: "", type: "", status: "", search: "" },
    settings: null,
  };

  let currentLanguage = "de";

  // ── Platform APIs ───────────────────────────────────────────────────

  const bridge = getTauriBridge(window);
  const { isTauri, tauriEvent } = bridge;
  const authApi = createAuthApi(bridge);
  const tunnelApi = createTunnelApi(bridge);
  const settingsApi = createSettingsApi(bridge, t);

  const apiFactory = () => createConnectionsApi(bridge, t, () => getClientInfo(window));
  const passwordApiFactory = () => createPasswordApi(bridge);

  // ── i18n ────────────────────────────────────────────────────────────

  function t(key, vars = {}) {
    const dict = translations[currentLanguage] || translations.en;
    const fallback = translations.en || {};
    let text = dict[key] || fallback[key] || key;
    text = text.replace(/\{(\w+)\}/g, (_, token) => {
      const value = vars[token];
      return value === undefined || value === null ? "" : String(value);
    });
    return text;
  }

  function applyTranslations() {
    document.querySelectorAll("[data-i18n]").forEach((el) => {
      const key = el.dataset.i18n;
      if (key) {
        el.textContent = t(key);
      }
    });
    document.querySelectorAll("[data-i18n-placeholder]").forEach((el) => {
      const key = el.dataset.i18nPlaceholder;
      if (key) {
        el.setAttribute("placeholder", t(key));
      }
    });
    document.querySelectorAll("[data-i18n-aria]").forEach((el) => {
      const key = el.dataset.i18nAria;
      if (key) {
        el.setAttribute("aria-label", t(key));
      }
    });
    document.title = t("app.title");
  }

  function setLanguage(language) {
    const normalized = translations[language] ? language : "en";
    currentLanguage = normalized;
    document.documentElement.lang = normalized;
    if (state.settings) {
      state.settings.language = normalized;
    }
    applyTranslations();
    settings.updateSettingsBadge((state.settings || getSettingsDefaults()).mode);
    const editorEl = document.getElementById("editor");
    if (editorEl && !editorEl.classList.contains("hidden")) {
      const selected = renderer.getSelectedConnection();
      const formTitle = document.getElementById("formTitle");
      if (formTitle) {
        formTitle.textContent = selected?.name || (selected ? t("editor.connection") : t("editor.new"));
      }
    }
    renderer.renderConnections();
    if (state.activeView === "dashboard") {
      dashboard.render();
    }
  }

  // ── Navigation ──────────────────────────────────────────────────────

  const pageTitle = document.getElementById("pageTitle");
  const monitoringSection = document.getElementById("monitoringSection");
  const connectionsSection = document.getElementById("connectionsSection");
  const ansibleSection = document.getElementById("ansibleSection");
  const dashboardSection = document.getElementById("dashboardSection");
  const newBtn = document.getElementById("newBtn");
  const settingsBtn = document.getElementById("settingsBtn");

  const monitoring = initMonitoring(state, t, createMonitoringApi);
  const ansible = initAnsible(state, t, createAnsibleApi);
  const dashboard = initDashboard(state, t, {
    initiateConnect: (conn) => connect.initiateConnect(conn),
    switchView,
    openEditor: () => editor.openEditor(),
  });

  const pageTitles = {
    dashboard: "nav.dashboard",
    connections: "connections.title",
    monitoring: "monitoring.title",
    ansible: "ansible.title",
  };

  function switchView(view) {
    state.activeView = view;

    // Update sidebar active state
    document.querySelectorAll(".sidebar-item[data-nav]").forEach((btn) => {
      btn.classList.toggle("active", btn.dataset.nav === view);
    });

    // Update page title
    if (pageTitle) {
      pageTitle.textContent = t(pageTitles[view] || view);
    }

    // Toggle sections
    dashboardSection.classList.toggle("hidden", view !== "dashboard");
    connectionsSection.classList.toggle("hidden", view !== "connections");
    monitoringSection.classList.toggle("hidden", view !== "monitoring");
    ansibleSection.classList.toggle("hidden", view !== "ansible");

    // Activate/deactivate subsystems
    if (view === "monitoring") {
      monitoring.activate();
    } else {
      monitoring.deactivate();
    }
    if (view === "ansible") {
      ansible.activate();
    } else {
      ansible.deactivate();
    }
    if (view === "dashboard") {
      dashboard.render();
    }
  }

  function updateNavVisibility() {
    const mode = (state.settings || getSettingsDefaults()).mode;
    const showServerNav = mode === "server" && state.session;
    const navMonitoring = document.getElementById("navMonitoring");
    const navAnsible = document.getElementById("navAnsible");
    if (navMonitoring) navMonitoring.classList.toggle("disabled", !showServerNav);
    if (navAnsible) navAnsible.classList.toggle("disabled", !showServerNav);
    if (!showServerNav && (state.activeView === "monitoring" || state.activeView === "ansible")) {
      switchView("dashboard");
    }
  }

  // ── Sidebar collapse ───────────────────────────────────────────────

  const sidebarToggle = document.getElementById("sidebarToggle");
  const appShell = document.getElementById("appMain");

  function initSidebar() {
    const collapsed = localStorage.getItem("srm-sidebar-collapsed") === "true";
    if (collapsed) {
      appShell.classList.add("sidebar-collapsed");
    }
    if (sidebarToggle) {
      sidebarToggle.addEventListener("click", () => {
        appShell.classList.toggle("sidebar-collapsed");
        localStorage.setItem(
          "srm-sidebar-collapsed",
          appShell.classList.contains("sidebar-collapsed")
        );
      });
    }
  }

  // ── Callbacks mediator ──────────────────────────────────────────────

  const callbacks = {};

  const status = initStatus();
  const renderer = initRendering(state, t, callbacks);
  const editor = initEditor(state, t, callbacks, apiFactory, passwordApiFactory);
  const prompt = initPasswordPrompt(state, t, callbacks, passwordApiFactory);
  const connect = initConnectFlow(state, t, callbacks, apiFactory, tunnelApi, tauriEvent, isTauri);
  const settings = initSettings(state, t, callbacks, settingsApi, tunnelApi, authApi);
  const auth = initAuth(state, t, callbacks, authApi, tunnelApi, apiFactory);

  Object.assign(callbacks, {
    // Status
    showStatus: status.showStatus,
    reportError: status.reportError,
    clearStatus: status.clearStatus,
    // Rendering
    renderConnections: renderer.renderConnections,
    getSelectedConnection: renderer.getSelectedConnection,
    // Editor
    openEditor: editor.openEditor,
    closeEditor: editor.closeEditor,
    setForm: editor.setForm,
    // Password
    openPasswordPrompt: prompt.openPasswordPrompt,
    passwordState: (connection) => {
      const pApi = passwordApiFactory();
      return pApi.state(connection);
    },
    // Connect
    initiateConnect: connect.initiateConnect,
    performConnect: connect.performConnect,
    startTunnelIfServerMode: connect.startTunnelIfServerMode,
    updateTunnelIndicator: connect.updateTunnelIndicator,
    // Settings
    openSettingsPrompt: settings.openSettingsPrompt,
    closeSettingsPrompt: settings.closeSettingsPrompt,
    updateSettingsBadge: settings.updateSettingsBadge,
    setSyncMode: settings.setSyncMode,
    isSyncLocked: settings.isSyncLocked,
    isPasswordStoreEnabled: settings.isPasswordStoreEnabled,
    reportSyncLocked: settings.reportSyncLocked,
    syncNow: settings.syncNow,
    startSyncTimer: settings.startSyncTimer,
    stopSyncTimer: settings.stopSyncTimer,
    // Auth
    showLoginScreen: auth.showLoginScreen,
    hideLoginScreen: auth.hideLoginScreen,
    loadConnectionsForMode: auth.loadConnectionsForMode,
    // App-level
    setLanguage,
    updateNavVisibility,
    saveSettings: (s) => settingsApi.save(s),
    switchView,
  });

  // ── Global listeners ────────────────────────────────────────────────

  newBtn.addEventListener("click", () => {
    if (settings.isSyncLocked()) {
      settings.reportSyncLocked();
      return;
    }
    editor.openEditor();
  });

  settingsBtn.addEventListener("click", () => {
    settings.openSettingsPrompt();
  });

  // Sidebar navigation
  document.querySelectorAll(".sidebar-item[data-nav]").forEach((btn) => {
    btn.addEventListener("click", () => {
      if (btn.classList.contains("disabled")) return;
      switchView(btn.dataset.nav);
    });
  });

  // ── Bootstrap ───────────────────────────────────────────────────────

  async function init() {
    initSidebar();
    setLanguage(getSettingsDefaults().language);
    try {
      const loadedSettings = await settingsApi.load();
      state.settings = { ...getSettingsDefaults(), ...loadedSettings };
      if (!loadedSettings.language) {
        state.settings.language = detectSystemLanguage();
        await settingsApi.save(state.settings);
      }
      setLanguage(state.settings.language || "de");
      settings.setSyncMode(state.settings.mode || "local");
      settings.updateSettingsBadge(state.settings.mode || "local");

      if (state.settings.mode === "server") {
        const session = await authApi.checkSession();
        if (session) {
          const certValid = await authApi.checkServerCert(session.serverUrl);
          if (!certValid) {
            const accepted = confirm(t("cert.warning.message", { url: session.serverUrl }));
            if (!accepted) {
              await authApi.logout();
              auth.showLoginScreen(state.settings.serverUrl || "");
              updateNavVisibility();
              return;
            }
          }
          state.session = session;
          auth.hideLoginScreen();
          state.connections = await auth.loadConnectionsForMode();
          connect.startTunnelIfServerMode();
        } else {
          auth.showLoginScreen(state.settings.serverUrl || "");
          updateNavVisibility();
          return;
        }
      } else {
        auth.hideLoginScreen();
        state.connections = await auth.loadConnectionsForMode();
      }
      updateNavVisibility();
    } catch (error) {
      status.showStatus(t("error.loadConnections"), true);
      state.connections = [];
    }

    renderer.renderConnections();
    dashboard.render();
  }

  initScrollAcceleration();
  init();
})();
