import {
  filterConnections,
  groupConnectionsByHost,
  normalizeConnection,
  parseTags,
  toCardMeta,
  validateConnection
} from "./connectionModel.js";
import { translations } from "./i18n.js";
import {
  createConnectionsApi,
  createPasswordApi,
  createSettingsApi,
  getClientInfo,
  getTauriBridge
} from "./platformApi.js";
import { detectSystemLanguage, getIntervalMinutes, getSettingsDefaults } from "./settingsModel.js";

(() => {
  const state = {
    connections: [],
    selectedId: null,
    filter: "single",
    search: "",
    view: "list"
  };

  let currentLanguage = "de";

  const bridge = getTauriBridge(window);
  const { isTauri, tauriEvent } = bridge;

  const listEl = document.getElementById("list");
  const treeEl = document.getElementById("tree");
  const counterEl = document.getElementById("counter");
  const statusEl = document.getElementById("status");
  const globalStatusEl = document.getElementById("globalStatus");
  const searchInput = document.getElementById("searchInput");
  const newBtn = document.getElementById("newBtn");
  const settingsBtn = document.getElementById("settingsBtn");
  const settingsModeBadge = document.getElementById("settingsModeBadge");
  const connectBtn = document.getElementById("connectBtn");
  const saveBtn = document.getElementById("saveBtn");
  const deleteBtn = document.getElementById("deleteBtn");
  const closeBtn = document.getElementById("closeBtn");
  const formTitle = document.getElementById("formTitle");
  const editorEl = document.getElementById("editor");
  const passwordPromptEl = document.getElementById("passwordPrompt");
  const passwordHint = document.getElementById("passwordHint");
  const passwordInput = document.getElementById("fieldPassword");
  const passwordRememberField = document.getElementById("passwordRememberField");
  const passwordRememberInput = document.getElementById("passwordRememberInput");
  const promptUsernameInput = document.getElementById("fieldPromptUsername");
  const promptDomainInput = document.getElementById("fieldPromptDomain");
  const passwordConfirmBtn = document.getElementById("passwordConfirmBtn");
  const passwordCancelBtn = document.getElementById("passwordCancelBtn");
  const settingsPromptEl = document.getElementById("settingsPrompt");
  const settingsSaveBtn = document.getElementById("settingsSaveBtn");
  const settingsCancelBtn = document.getElementById("settingsCancelBtn");
  const syncUrlField = document.getElementById("syncUrlField");
  const syncUrlInput = document.getElementById("syncUrlInput");
  const syncIntervalField = document.getElementById("syncIntervalField");
  const syncIntervalInput = document.getElementById("syncIntervalInput");
  const rdpScalingSelect = document.getElementById("rdpScalingSelect");
  const storePasswordsInput = document.getElementById("storePasswordsInput");
  const allowSelfSignedField = document.getElementById("allowSelfSignedField");
  const allowSelfSignedInput = document.getElementById("allowSelfSignedInput");
  const languageSelect = document.getElementById("languageSelect");

  const fieldName = document.getElementById("fieldName");
  const fieldKind = document.getElementById("fieldKind");
  const fieldHost = document.getElementById("fieldHost");
  const fieldPort = document.getElementById("fieldPort");
  const fieldUsername = document.getElementById("fieldUsername");
  const fieldDomain = document.getElementById("fieldDomain");
  const fieldTrustCert = document.getElementById("fieldTrustCert");
  const fieldKeyPath = document.getElementById("fieldKeyPath");
  const fieldUrl = document.getElementById("fieldUrl");
  const fieldNotes = document.getElementById("fieldNotes");
  const fieldTags = document.getElementById("fieldTags");
  const fieldLastUsed = document.getElementById("fieldLastUsed");

  const fieldWrappers = Array.from(document.querySelectorAll(".field"));

  const ua = navigator.userAgent.toLowerCase();
  const isLinux = ua.includes("linux");

  let pendingConnect = null;
  let syncTimer = null;
  let rdpStatusTimer = null;
  let rdpConnectId = 0;
  let rdpPendingId = null;
  let rdpErroredId = null;
  const SCROLL_ACCELERATION_LIST = 1.55;
  const SCROLL_ACCELERATION_PANEL = 1.35;

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
    updateSettingsBadge((state.settings || getSettingsDefaults()).mode);
    if (!editorEl.classList.contains("hidden")) {
      const selected = getSelectedConnection();
      formTitle.textContent = selected?.name || (selected ? t("editor.connection") : t("editor.new"));
    }
    renderConnections();
  }

  const api = createConnectionsApi(bridge, t, () => getClientInfo(window));
  const settingsApi = createSettingsApi(bridge, t);
  const passwordApi = createPasswordApi(bridge);

  function getStatusTarget() {
    if (editorEl.classList.contains("hidden") && globalStatusEl) {
      return globalStatusEl;
    }
    return statusEl;
  }

  function showStatus(message, isError = false) {
    const target = getStatusTarget();
    if (!target) {
      return;
    }
    target.textContent = message;
    target.classList.add("show");
    target.style.border = `1px solid ${isError ? "rgba(248, 113, 113, 0.4)" : "rgba(34, 197, 94, 0.35)"}`;
    target.style.color = isError ? "#fca5a5" : "#bbf7d0";
  }

  function reportError(message) {
    if (editorEl.classList.contains("hidden") && !globalStatusEl) {
      alert(message);
    } else {
      showStatus(message, true);
    }
  }

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
  }

  function updateSettingsBadge(mode) {
    if (settingsModeBadge) {
      settingsModeBadge.textContent = mode === "sync" ? t("settings.mode.sync") : t("settings.mode.local");
    }
    if (settingsBtn) {
      settingsBtn.dataset.mode = mode === "sync" ? "sync" : "local";
    }
  }

  function isSyncLocked() {
    return (state.settings || getSettingsDefaults()).mode === "sync";
  }

  function isPasswordStoreEnabled() {
    return Boolean((state.settings || getSettingsDefaults()).storePasswords);
  }

  function reportSyncLocked() {
    reportError(t("error.syncLocked"));
  }

  function clearRdpStatusTimer() {
    if (rdpStatusTimer) {
      clearTimeout(rdpStatusTimer);
      rdpStatusTimer = null;
    }
  }

  function startRdpStatus() {
    rdpConnectId += 1;
    rdpPendingId = rdpConnectId;
    rdpErroredId = null;
    clearRdpStatusTimer();
    return rdpConnectId;
  }

  function scheduleRdpStatus(connectId) {
    clearRdpStatusTimer();
    rdpStatusTimer = setTimeout(() => {
      if (rdpPendingId !== connectId || rdpErroredId === connectId) {
        return;
      }
      showStatus(t("status.rdpStarted"));
      rdpStatusTimer = null;
    }, 800);
  }

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
    settingsPromptEl.classList.remove("hidden");
    settingsPromptEl.setAttribute("aria-hidden", "false");
  }

  function closeSettingsPrompt() {
    settingsPromptEl.classList.add("hidden");
    settingsPromptEl.setAttribute("aria-hidden", "true");
  }

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
      renderConnections();
      if (showStatusMessage) {
        showStatus(t("sync.success"));
      }
    } catch (error) {
      if (showStatusMessage) {
        reportError(t("sync.error", { message: error.message || error }));
      }
    }
  }

  function clearStatus() {
    if (statusEl) {
      statusEl.classList.remove("show");
    }
    if (globalStatusEl) {
      globalStatusEl.classList.remove("show");
    }
  }

  function accelerateWheelScroll(element, factor) {
    if (!element || element.dataset.scrollAccelerationBound === "1") {
      return;
    }
    element.dataset.scrollAccelerationBound = "1";
    element.addEventListener(
      "wheel",
      (event) => {
        if (event.ctrlKey) {
          return;
        }
        if (element.scrollHeight <= element.clientHeight) {
          return;
        }
        if (event.deltaMode === 0) {
          return;
        }

        let modeScale = 1;
        if (event.deltaMode === 1) {
          modeScale = 16;
        } else if (event.deltaMode === 2) {
          modeScale = element.clientHeight;
        }

        const deltaY = event.deltaY * modeScale;
        const deltaX = event.deltaX * modeScale;
        if (Math.abs(deltaY) < 0.5 && Math.abs(deltaX) < 0.5) {
          return;
        }

        const beforeTop = element.scrollTop;
        const beforeLeft = element.scrollLeft;
        element.scrollTop += deltaY * factor;
        element.scrollLeft += deltaX * factor;
        const changed =
          Math.abs(element.scrollTop - beforeTop) > 0.1 ||
          Math.abs(element.scrollLeft - beforeLeft) > 0.1;
        if (changed) {
          event.preventDefault();
        }
      },
      { passive: false }
    );
  }

  function initScrollAcceleration() {
    accelerateWheelScroll(listEl, SCROLL_ACCELERATION_LIST);
    accelerateWheelScroll(treeEl, SCROLL_ACCELERATION_LIST);
    document.querySelectorAll(".editor-panel").forEach((panel) => {
      accelerateWheelScroll(panel, SCROLL_ACCELERATION_PANEL);
    });
  }

  function getSelectedConnection() {
    return state.connections.find((item) => item.id === state.selectedId) || null;
  }

  function buildConnectionCard(connection) {
    const card = document.createElement("div");
    card.className = `card ${connection.id === state.selectedId ? "active" : ""}`;
    card.dataset.id = connection.id;

    const cardMain = document.createElement("div");
    cardMain.className = "card-main";

    const title = document.createElement("div");
    title.className = "card-title";
    title.textContent = connection.name || t("list.noName");

    const meta = document.createElement("div");
    meta.className = "card-meta";
    meta.textContent = toCardMeta(connection);

    const typeTag = document.createElement("div");
    typeTag.className = "card-tag";
    typeTag.textContent = connection.kind.toUpperCase();

    cardMain.append(title, meta, typeTag);

    const tags = connection.tags || [];
    if (tags.length > 0) {
      const tagsBlock = document.createElement("div");
      tagsBlock.className = "card-tags";
      tags.forEach((tag) => {
        const tagEl = document.createElement("span");
        tagEl.className = "tag";
        tagEl.textContent = tag;
        tagsBlock.appendChild(tagEl);
      });
      cardMain.appendChild(tagsBlock);
    }

    const actions = document.createElement("div");
    actions.className = "card-actions";

    const connectBtn = document.createElement("button");
    connectBtn.className = "btn small accent";
    connectBtn.type = "button";
    connectBtn.dataset.action = "connect";
    connectBtn.textContent = t("action.connect");

    const editBtn = document.createElement("button");
    editBtn.className = "btn small ghost";
    editBtn.type = "button";
    editBtn.dataset.action = "edit";
    editBtn.textContent = t("action.edit");

    actions.append(connectBtn, editBtn);
    card.append(cardMain, actions);
    card.addEventListener("click", (event) => {
      if (event.target.closest("button")) {
        return;
      }
      openEditor(connection);
    });
    const connectAction = card.querySelector('[data-action="connect"]');
    const editAction = card.querySelector('[data-action="edit"]');
    connectAction.addEventListener("click", (event) => {
      event.preventDefault();
      initiateConnect(connection);
    });
    editAction.addEventListener("click", (event) => {
      event.preventDefault();
      if (isSyncLocked()) {
        reportSyncLocked();
        return;
      }
      openEditor(connection);
    });
    return card;
  }

  function preferredGroupedConnection(group) {
    for (const kind of ["ssh", "rdp", "web"]) {
      if (group.byKind[kind]) {
        return group.byKind[kind];
      }
    }
    return group.connections[0] || null;
  }

  function buildGroupedConnectionCard(group) {
    const active = group.connections.some((connection) => connection.id === state.selectedId);
    const card = document.createElement("div");
    card.className = `card ${active ? "active" : ""}`;
    card.dataset.id = group.key;

    const cardMain = document.createElement("div");
    cardMain.className = "card-main";

    const title = document.createElement("div");
    title.className = "card-title";
    title.textContent = group.displayName || t("list.noName");

    const meta = document.createElement("div");
    meta.className = "card-meta";
    meta.textContent = `${group.host} · ${t("grouped.connections", { count: group.connections.length })}`;

    const typeTag = document.createElement("div");
    typeTag.className = "card-tag";
    typeTag.textContent = ["ssh", "rdp", "web"]
      .filter((kind) => Boolean(group.byKind[kind]))
      .map((kind) => kind.toUpperCase())
      .join(" · ");

    cardMain.append(title, meta, typeTag);

    const actions = document.createElement("div");
    actions.className = "card-actions";
    ["ssh", "rdp", "web"].forEach((kind) => {
      const connection = group.byKind[kind];
      if (!connection) {
        return;
      }
      const button = document.createElement("button");
      button.className = "btn small accent";
      button.type = "button";
      button.dataset.action = `connect-${kind}`;
      button.textContent = kind.toUpperCase();
      button.addEventListener("click", (event) => {
        event.preventDefault();
        initiateConnect(connection);
      });
      actions.appendChild(button);
    });

    card.append(cardMain, actions);
    card.addEventListener("click", (event) => {
      if (event.target.closest("button")) {
        return;
      }
      const connection = preferredGroupedConnection(group);
      if (connection) {
        openEditor(connection);
      }
    });
    return card;
  }

  function renderList(filtered) {
    listEl.innerHTML = "";
    filtered.forEach((connection) => {
      listEl.appendChild(buildConnectionCard(connection));
    });
  }

  function renderGroupedList(groups) {
    listEl.innerHTML = "";
    groups.forEach((group) => {
      listEl.appendChild(buildGroupedConnectionCard(group));
    });
  }

  function groupedTagKeys(group, untaggedLabel) {
    const tags = new Map();
    group.connections.forEach((connection) => {
      const rawTags = Array.isArray(connection.tags) ? connection.tags : [];
      rawTags.forEach((tagValue) => {
        const normalized = String(tagValue || "").trim();
        if (!normalized) {
          return;
        }
        const key = normalized.toLowerCase();
        if (!tags.has(key)) {
          tags.set(key, normalized);
        }
      });
    });
    if (tags.size === 0) {
      return [untaggedLabel];
    }
    return Array.from(tags.values());
  }

  function renderGroupedTree(groups) {
    const untaggedLabel = t("tree.untagged");
    const tagGroups = new Map();

    groups.forEach((group) => {
      const tags = groupedTagKeys(group, untaggedLabel);
      tags.forEach((tag) => {
        const key = tag.trim() || untaggedLabel;
        if (!tagGroups.has(key)) {
          tagGroups.set(key, []);
        }
        tagGroups.get(key).push(group);
      });
    });

    const sortedTags = Array.from(tagGroups.keys()).sort((a, b) => a.localeCompare(b));
    treeEl.innerHTML = "";
    sortedTags.forEach((tag) => {
      const treeGroup = document.createElement("div");
      treeGroup.className = "tree-group open";

      const hostsInTag = tagGroups.get(tag) || [];
      const countLabel = t("grouped.connections", { count: hostsInTag.length });
      const header = document.createElement("div");
      header.className = "tree-header";

      const hostEl = document.createElement("div");
      hostEl.className = "tree-tag";
      hostEl.textContent = tag;

      const toggle = document.createElement("div");
      toggle.className = "tree-toggle";

      const countEl = document.createElement("span");
      countEl.className = "tree-count";
      countEl.textContent = countLabel;

      toggle.appendChild(countEl);
      header.append(hostEl, toggle);

      const list = document.createElement("div");
      list.className = "tree-list";

      hostsInTag.forEach((hostGroup) => {
        const node = document.createElement("div");
        node.className = "tree-node";
        node.appendChild(buildGroupedConnectionCard(hostGroup));
        list.appendChild(node);
      });
      treeGroup.append(header, list);

      header.addEventListener("click", () => {
        treeGroup.classList.toggle("open");
      });

      treeEl.appendChild(treeGroup);
    });
  }

  function renderTree(filtered) {
    const groups = new Map();
    const untaggedLabel = t("tree.untagged");
    filtered.forEach((connection) => {
      const tags = connection.tags && connection.tags.length > 0 ? connection.tags : [untaggedLabel];
      tags.forEach((tag) => {
        const key = tag.trim() || untaggedLabel;
        if (!groups.has(key)) {
          groups.set(key, []);
        }
        groups.get(key).push(connection);
      });
    });

    const sortedTags = Array.from(groups.keys()).sort((a, b) => a.localeCompare(b));
    treeEl.innerHTML = "";
    sortedTags.forEach((tag) => {
      const group = document.createElement("div");
      group.className = "tree-group";
      const countLabel = t("tree.connections", { count: groups.get(tag).length });
      const header = document.createElement("div");
      header.className = "tree-header";

      const tagEl = document.createElement("div");
      tagEl.className = "tree-tag";
      tagEl.textContent = tag;

      const toggle = document.createElement("div");
      toggle.className = "tree-toggle";

      const countEl = document.createElement("span");
      countEl.className = "tree-count";
      countEl.textContent = countLabel;

      toggle.appendChild(countEl);
      header.append(tagEl, toggle);

      const list = document.createElement("div");
      list.className = "tree-list";
      group.append(header, list);

      groups.get(tag).forEach((connection) => {
        const node = document.createElement("div");
        node.className = "tree-node";
        node.appendChild(buildConnectionCard(connection));
        list.appendChild(node);
      });
      header.addEventListener("click", () => {
        group.classList.toggle("open");
      });
      treeEl.appendChild(group);
    });
  }

  function renderConnections() {
    if (state.filter === "grouped") {
      const grouped = groupConnectionsByHost(state.connections, state.search);
      counterEl.textContent = String(grouped.length);
      listEl.classList.toggle("hidden", state.view !== "list");
      treeEl.classList.toggle("hidden", state.view !== "tree");
      if (state.view === "tree") {
        renderGroupedTree(grouped);
      } else {
        renderGroupedList(grouped);
      }
      return;
    }

    const filtered = filterConnections(state.connections, state.filter, state.search);
    counterEl.textContent = String(filtered.length);
    listEl.classList.toggle("hidden", state.view !== "list");
    treeEl.classList.toggle("hidden", state.view !== "tree");
    if (state.view === "tree") {
      renderTree(filtered);
    } else {
      renderList(filtered);
    }
  }

  function toggleFields(kind) {
    fieldWrappers.forEach((wrapper) => {
      const only = wrapper.dataset.only;
      if (!only) {
        wrapper.classList.remove("hidden");
        return;
      }
      if (only === kind) {
        wrapper.classList.remove("hidden");
      } else {
        wrapper.classList.add("hidden");
      }
    });
  }

  function setForm(connection) {
    const normalized = normalizeConnection(connection || {});
    fieldName.value = normalized.name || "";
    fieldKind.value = normalized.kind || "ssh";
    fieldHost.value = normalized.host || "";
    fieldPort.value = normalized.port || "";
    fieldUsername.value = normalized.username || "";
    fieldDomain.value = normalized.domain || "";
    fieldTrustCert.checked = Boolean(normalized.trustCert);
    fieldKeyPath.value = normalized.keyPath || "";
    fieldUrl.value = normalized.url || "";
    fieldNotes.value = normalized.notes || "";
    fieldTags.value = normalized.tags ? normalized.tags.join(", ") : "";
    fieldLastUsed.textContent = normalized.lastUsed ? new Date(normalized.lastUsed).toLocaleString() : "-";
    toggleFields(normalized.kind);
  }

  function collectForm() {
    return normalizeConnection({
      id: state.selectedId || crypto.randomUUID(),
      name: fieldName.value,
      kind: fieldKind.value,
      host: fieldHost.value,
      port: fieldPort.value,
      username: fieldUsername.value,
      domain: fieldDomain.value,
      trustCert: fieldTrustCert.checked,
      keyPath: fieldKeyPath.value,
      url: fieldUrl.value,
      notes: fieldNotes.value,
      tags: parseTags(fieldTags.value),
      lastUsed: getSelectedConnection()?.lastUsed || null
    });
  }

  function openEditor(connection) {
    const nextConnection = connection || { kind: "ssh" };
    state.selectedId = connection?.id || null;
    formTitle.textContent = connection?.name || t("editor.new");
    deleteBtn.disabled = !connection;
    setForm(nextConnection);
    editorEl.classList.remove("hidden");
    editorEl.setAttribute("aria-hidden", "false");
    renderConnections();
    clearStatus();
  }

  function closeEditor(options = {}) {
    const { preserveStatus = false } = options;
    editorEl.classList.add("hidden");
    editorEl.setAttribute("aria-hidden", "true");
    state.selectedId = null;
    renderConnections();
    if (!preserveStatus) {
      clearStatus();
    }
  }

  function openPasswordPrompt(connection, keepEditorOpen, options = {}) {
    const { allowRemember = false } = options;
    pendingConnect = { connection, keepEditorOpen, allowRemember };
    promptUsernameInput.value = connection.username || "";
    promptDomainInput.value = connection.domain || "";
    passwordInput.value = "";
    if (passwordRememberInput) {
      passwordRememberInput.checked = false;
    }
    if (passwordRememberField) {
      passwordRememberField.classList.toggle("hidden", !allowRemember);
    }
    if (passwordHint) {
      const key = allowRemember ? "rdp.hint.remember" : "rdp.hint";
      passwordHint.dataset.i18n = key;
      passwordHint.textContent = t(key);
    }
    passwordPromptEl.classList.remove("hidden");
    passwordPromptEl.setAttribute("aria-hidden", "false");
    if (promptUsernameInput.value) {
      passwordInput.focus();
    } else {
      promptUsernameInput.focus();
    }
  }

  function closePasswordPrompt() {
    passwordPromptEl.classList.add("hidden");
    passwordPromptEl.setAttribute("aria-hidden", "true");
    pendingConnect = null;
    promptUsernameInput.value = "";
    promptDomainInput.value = "";
    passwordInput.value = "";
    if (passwordRememberInput) {
      passwordRememberInput.checked = false;
    }
  }

  async function handleSave() {
    if (isSyncLocked()) {
      reportSyncLocked();
      return;
    }
    const connection = collectForm();
    const validation = validateConnection(connection, t);
    if (!validation.ok) {
      showStatus(validation.message, true);
      return;
    }

    const existingIndex = state.connections.findIndex((item) => item.id === connection.id);
    if (existingIndex >= 0) {
      state.connections[existingIndex] = connection;
    } else {
      state.connections.push(connection);
    }

    await api.save(state.connections);
    showStatus(t("status.saved"));
    state.selectedId = connection.id;
    formTitle.textContent = connection.name || t("editor.connection");
    renderConnections();
  }

  async function handleDelete() {
    if (isSyncLocked()) {
      reportSyncLocked();
      return;
    }
    const connection = getSelectedConnection();
    if (!connection) {
      return;
    }
    state.connections = state.connections.filter((item) => item.id !== connection.id);
    await api.save(state.connections);
    if (connection.kind === "rdp") {
      try {
        await passwordApi.delete(connection);
      } catch (error) {
        reportError(t("error.passwordStore", { message: error.message || error }));
      }
    }
    showStatus(t("status.deleted"));
    closeEditor();
  }

  async function handleConnect() {
    const connection = collectForm();
    await initiateConnect(connection, true);
  }

  async function handleRdpAuth(connection, keepEditorOpen) {
    if (!isTauri) {
      return false;
    }

    if (isPasswordStoreEnabled()) {
      try {
        const pwState = await passwordApi.state(connection);
        if (!pwState.canStore) {
          return false;
        }
        if (pwState.stored) {
          await performConnect(connection, keepEditorOpen, { useStoredPassword: true });
          return true;
        }
        openPasswordPrompt(connection, keepEditorOpen, { allowRemember: true });
        return true;
      } catch (error) {
        reportError(t("error.passwordStore", { message: error.message || error }));
      }
    }

    if (isLinux) {
      openPasswordPrompt(connection, keepEditorOpen, { allowRemember: false });
      return true;
    }

    return false;
  }

  async function initiateConnect(connection, keepEditorOpen = false) {
    const validation = validateConnection(connection, t);
    if (!validation.ok) {
      showStatus(validation.message, true);
      return;
    }

    if (connection.kind === "rdp") {
      const handled = await handleRdpAuth(connection, keepEditorOpen);
      if (handled) {
        return;
      }
    }

    await performConnect(connection, keepEditorOpen);
  }

  async function performConnect(connection, keepEditorOpen, options = {}) {
    const { password = null, useStoredPassword = false } = options;
    try {
      let rdpId = null;
      if (connection.kind === "rdp") {
        rdpId = startRdpStatus();
        const promise = useStoredPassword
          ? api.connectStored(connection)
          : api.connect(connection, password || undefined);
        promise.catch((error) => {
          if (rdpId !== null) {
            clearRdpStatusTimer();
            if (rdpPendingId === rdpId) {
              rdpErroredId = rdpId;
              rdpPendingId = null;
            }
          }
          const message = String(error?.message || error || "");
          reportError(t("error.generic", { message }));
        });
      } else if (useStoredPassword) {
        await api.connectStored(connection);
      } else {
        await api.connect(connection, password || undefined);
      }
      const index = state.connections.findIndex((item) => item.id === connection.id);
      const updated = { ...connection, lastUsed: new Date().toISOString() };
      if (index >= 0) {
        state.connections[index] = updated;
      } else {
        state.connections.push(updated);
      }
      await api.save(state.connections);
      state.selectedId = updated.id;
      setForm(updated);
      renderConnections();
      if (connection.kind === "rdp") {
        if (rdpId !== null) {
          scheduleRdpStatus(rdpId);
        }
      } else {
        showStatus(t("status.connected"));
      }
      if (!keepEditorOpen) {
        closeEditor({ preserveStatus: connection.kind === "rdp" });
      }
    } catch (error) {
      const message = String(error?.message || error || "");
      reportError(t("error.generic", { message }));
    }
  }

  function setFilter(filter) {
    state.filter = filter;
    document.querySelectorAll("[data-filter]").forEach((chip) => {
      chip.classList.toggle("active", chip.dataset.filter === filter);
    });
    renderConnections();
  }

  async function init() {
    setLanguage(getSettingsDefaults().language);
    try {
      const loadedSettings = await settingsApi.load();
      state.settings = { ...getSettingsDefaults(), ...loadedSettings };
      if (!loadedSettings.language) {
        state.settings.language = detectSystemLanguage();
        await settingsApi.save(state.settings);
      }
      setLanguage(state.settings.language || "de");
      setSyncMode(state.settings.mode || "local");
      updateSettingsBadge(state.settings.mode || "local");
      if (state.settings.mode === "sync") {
        await syncNow(false);
        startSyncTimer();
      }
      state.connections = await api.load();
      state.connections = Array.isArray(state.connections)
        ? state.connections.map((connection) => normalizeConnection(connection || {}))
        : [];
    } catch (error) {
      showStatus(t("error.loadConnections"), true);
      state.connections = [];
    }

    renderConnections();
  }

  if (tauriEvent?.listen) {
    tauriEvent.listen("rdp-error", (event) => {
      clearRdpStatusTimer();
      if (rdpPendingId !== null) {
        rdpErroredId = rdpPendingId;
        rdpPendingId = null;
      }
      const message = event?.payload || t("rdp.authFailed");
      reportError(String(message));
    });
  }

  searchInput.addEventListener("input", (event) => {
    state.search = event.target.value;
    renderConnections();
  });

  document.querySelectorAll("[data-filter]").forEach((chip) => {
    chip.addEventListener("click", () => setFilter(chip.dataset.filter));
  });

  document.querySelectorAll("[data-view]").forEach((button) => {
    button.addEventListener("click", () => {
      state.view = button.dataset.view;
      document.querySelectorAll("[data-view]").forEach((btn) => {
        btn.classList.toggle("active", btn.dataset.view === state.view);
      });
      renderConnections();
    });
  });

  fieldKind.addEventListener("change", () => {
    toggleFields(fieldKind.value);
  });

  newBtn.addEventListener("click", () => {
    if (isSyncLocked()) {
      reportSyncLocked();
      return;
    }
    openEditor();
  });

  settingsBtn.addEventListener("click", () => {
    openSettingsPrompt();
  });

  saveBtn.addEventListener("click", (event) => {
    event.preventDefault();
    handleSave();
  });

  deleteBtn.addEventListener("click", (event) => {
    event.preventDefault();
    handleDelete();
  });

  connectBtn.addEventListener("click", (event) => {
    event.preventDefault();
    handleConnect();
  });

  closeBtn.addEventListener("click", (event) => {
    event.preventDefault();
    closeEditor();
  });

  editorEl.addEventListener("click", (event) => {
    const target = event.target;
    if (target instanceof HTMLElement && target.dataset.action === "close") {
      closeEditor();
    }
  });

  passwordConfirmBtn.addEventListener("click", async (event) => {
    event.preventDefault();
    if (!pendingConnect) {
      closePasswordPrompt();
      return;
    }
    if (!promptUsernameInput.reportValidity() || !passwordInput.reportValidity()) {
      return;
    }
    const { connection, keepEditorOpen } = pendingConnect;
    const password = passwordInput.value || "";
    const updated = {
      ...connection,
      username: promptUsernameInput.value.trim(),
      domain: promptDomainInput.value.trim()
    };
    const remember =
      Boolean(pendingConnect.allowRemember) &&
      Boolean(passwordRememberInput && passwordRememberInput.checked);
    closePasswordPrompt();
    if (remember) {
      try {
        await passwordApi.save(updated, password);
      } catch (error) {
        reportError(t("error.passwordStore", { message: error.message || error }));
      }
    }
    await performConnect(updated, keepEditorOpen, { password });
  });

  passwordCancelBtn.addEventListener("click", (event) => {
    event.preventDefault();
    closePasswordPrompt();
  });

  passwordPromptEl.addEventListener("click", (event) => {
    const target = event.target;
    if (target instanceof HTMLElement && target.dataset.action === "close-password") {
      closePasswordPrompt();
    }
  });

  settingsSaveBtn.addEventListener("click", async (event) => {
    event.preventDefault();
    const mode = getSyncMode();
    const url = syncUrlInput.value.trim();
    const intervalMinutes = Number(syncIntervalInput.value);
    const language = languageSelect ? languageSelect.value : "de";
    const storePasswords = storePasswordsInput ? storePasswordsInput.checked : false;
    const allowSelfSignedCerts = allowSelfSignedInput ? allowSelfSignedInput.checked : false;
    const rdpScalingMode = rdpScalingSelect ? rdpScalingSelect.value : "auto";
    const settings = {
      mode,
      url,
      intervalMinutes: getIntervalMinutes({ intervalMinutes }),
      language,
      storePasswords,
      allowSelfSignedCerts,
      rdpScalingMode: ["auto", "normal", "hdpi"].includes(rdpScalingMode)
        ? rdpScalingMode
        : "auto"
    };
    try {
      if (mode === "sync" && !url) {
        reportError(t("sync.urlRequired"));
        return;
      }
      if (mode === "sync" && !url.startsWith("https://")) {
        reportError(t("sync.httpsOnly"));
        return;
      }
      if (mode === "sync" && !Number.isFinite(intervalMinutes)) {
        reportError(t("sync.intervalInvalid"));
        return;
      }
      state.settings = settings;
      await settingsApi.save(settings);
      setLanguage(settings.language || "de");
      updateSettingsBadge(settings.mode);
      closeSettingsPrompt();
      if (mode === "sync") {
        await syncNow(true);
        startSyncTimer();
      } else {
        stopSyncTimer();
      }
    } catch (error) {
      reportError(t("sync.error", { message: error.message || error }));
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

  initScrollAcceleration();
  init();
})();
