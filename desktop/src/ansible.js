import { buildAnsibleTargets, groupServersByTag } from "./ansibleModel.js";

export function initAnsible(state, t, ansibleApiFactory) {
  let ansibleApi = null;
  let selectedPlaybookId = null;
  let selectedServerIds = new Set();
  let targetMode = "servers"; // "servers" or "tags"
  let playbooks = [];
  let servers = [];

  const section = document.getElementById("ansibleSection");
  const playbookList = document.getElementById("ansiblePlaybookList");
  const serverList = document.getElementById("ansibleServerList");
  const tagList = document.getElementById("ansibleTagList");
  const runSummary = document.getElementById("ansibleRunSummary");
  const runBtn = document.getElementById("ansibleRunBtn");

  function ensureApi() {
    if (!state.session) return false;
    if (!ansibleApi) {
      ansibleApi = ansibleApiFactory(state.session);
    }
    return true;
  }

  // ── Data Loading ──────────────────────────────────────────────────────
  async function loadData() {
    if (!ensureApi()) return;
    try {
      const [pb, srv] = await Promise.all([
        ansibleApi.fetchPlaybooks(),
        ansibleApi.fetchServers(),
      ]);
      playbooks = pb || [];
      servers = srv || [];
      renderPlaybooks();
      renderStep2();
      updateRunSummary();
    } catch (err) {
      playbookList.innerHTML = `<div class="ansible-empty">${t("ansible.error.load") || "Fehler beim Laden."}</div>`;
    }
  }

  // ── Step 1: Playbook Selection ────────────────────────────────────────
  function renderPlaybooks() {
    playbookList.innerHTML = "";
    if (playbooks.length === 0) {
      playbookList.innerHTML = `<div class="ansible-empty">${t("ansible.noPlaybooks")}</div>`;
      return;
    }
    for (const pb of playbooks) {
      const card = document.createElement("div");
      card.className = `ansible-playbook-card${pb.id === selectedPlaybookId ? " selected" : ""}`;
      const tags = (pb.tags || []).map((tg) => `<span class="ansible-tag">${esc(tg)}</span>`).join("");
      card.innerHTML = `
        <div class="ansible-playbook-name">${esc(pb.name)}</div>
        <div class="ansible-playbook-desc">${esc(pb.description || "")}</div>
        <div class="ansible-playbook-meta">
          <span class="ansible-playbook-file">${esc(pb.filename)}</span>
          ${tags}
        </div>
      `;
      card.addEventListener("click", () => {
        selectedPlaybookId = pb.id;
        renderPlaybooks();
        updateStepStates();
        updateRunSummary();
      });
      playbookList.appendChild(card);
    }
  }

  // ── Step 2: Server/Tag Selection ──────────────────────────────────────
  function renderStep2() {
    renderServerList();
    renderTagList();
    updateStep2Visibility();
  }

  function updateStep2Visibility() {
    serverList.classList.toggle("hidden", targetMode !== "servers");
    tagList.classList.toggle("hidden", targetMode !== "tags");
  }

  function renderServerList() {
    serverList.innerHTML = "";
    if (servers.length === 0) {
      serverList.innerHTML = `<div class="ansible-empty">${t("ansible.noServers")}</div>`;
      return;
    }
    for (const srv of servers) {
      const row = document.createElement("label");
      row.className = "ansible-server-row";
      const tags = (srv.tags || []).map((tg) => `<span class="ansible-tag">${esc(tg)}</span>`).join("");
      row.innerHTML = `
        <input type="checkbox" value="${esc(srv.id)}" ${selectedServerIds.has(srv.id) ? "checked" : ""} />
        <div class="ansible-server-info">
          <span class="ansible-server-name">${esc(srv.name)}</span>
          <span class="ansible-server-host">${esc(srv.hostname)}</span>
          ${tags}
        </div>
      `;
      row.querySelector("input").addEventListener("change", (e) => {
        if (e.target.checked) {
          selectedServerIds.add(srv.id);
        } else {
          selectedServerIds.delete(srv.id);
        }
        updateRunSummary();
      });
      serverList.appendChild(row);
    }
  }

  function renderTagList() {
    tagList.innerHTML = "";
    const groups = groupServersByTag(servers);
    const sortedTags = Object.keys(groups).sort();
    if (sortedTags.length === 0) {
      tagList.innerHTML = `<div class="ansible-empty">Keine Tags vorhanden.</div>`;
      return;
    }
    for (const tag of sortedTags) {
      const chip = document.createElement("button");
      chip.className = "ansible-tag-chip";
      const tagServerIds = groups[tag].map((s) => s.id);
      const allSelected = tagServerIds.every((id) => selectedServerIds.has(id));
      if (allSelected) chip.classList.add("active");
      chip.textContent = `${tag} (${tagServerIds.length})`;
      chip.addEventListener("click", () => {
        if (allSelected) {
          tagServerIds.forEach((id) => selectedServerIds.delete(id));
        } else {
          tagServerIds.forEach((id) => selectedServerIds.add(id));
        }
        renderTagList();
        renderServerList();
        updateRunSummary();
      });
      tagList.appendChild(chip);
    }
  }

  // ── Step 3: Run ───────────────────────────────────────────────────────
  function updateRunSummary() {
    const pb = playbooks.find((p) => p.id === selectedPlaybookId);
    if (!pb || selectedServerIds.size === 0) {
      runSummary.innerHTML = "";
      runBtn.disabled = true;
      return;
    }
    runSummary.innerHTML = `<strong>${esc(pb.name)}</strong> ${t("ansible.runOn") || "auf"} <strong>${selectedServerIds.size}</strong> ${t("ansible.servers") || "Server(n)"}`;
    runBtn.disabled = false;
  }

  async function runPlaybook() {
    if (!selectedPlaybookId) return;
    if (selectedServerIds.size === 0) return;
    if (!ensureApi()) return;

    const playbook = playbooks.find((p) => p.id === selectedPlaybookId);
    if (!playbook) return;

    const selectedServers = servers.filter((s) => selectedServerIds.has(s.id));
    const targets = buildAnsibleTargets(selectedServers);

    try {
      runBtn.disabled = true;
      runBtn.textContent = t("ansible.running") || "Ansible wird im Terminal gestartet...";

      // 1. Playbook-Inhalt vom Server holen
      const { content } = await ansibleApi.fetchContent(selectedPlaybookId);

      // 2. Inventory-Datei generieren
      const inventoryPath = await window.__TAURI__.core.invoke(
        "ansible_generate_inventory",
        { servers: targets }
      );

      // 3. Playbook in temporaere Datei schreiben
      const playbookPath = await window.__TAURI__.core.invoke(
        "ansible_write_playbook",
        { filename: playbook.filename, content }
      );

      // 4. Ansible im Terminal starten
      await window.__TAURI__.core.invoke("ansible_launch", {
        inventoryPath,
        playbookPath,
      });
    } catch (err) {
      runSummary.innerHTML = `<span style="color:var(--danger)">${esc(err.toString())}</span>`;
    } finally {
      runBtn.disabled = false;
      runBtn.textContent = t("ansible.action.run") || "Playbook ausfuehren";
    }
  }

  function updateStepStates() {
    const steps = section.querySelectorAll(".ansible-step");
    steps.forEach((step) => {
      const stepName = step.dataset.step;
      if (stepName === "playbook") {
        step.classList.add("active");
      } else if (stepName === "targets") {
        step.classList.toggle("active", !!selectedPlaybookId);
      } else if (stepName === "run") {
        step.classList.toggle("active", !!selectedPlaybookId && selectedServerIds.size > 0);
      }
    });
  }

  // ── Event Listeners ───────────────────────────────────────────────────
  section.querySelectorAll("[data-target-mode]").forEach((btn) => {
    btn.addEventListener("click", () => {
      targetMode = btn.dataset.targetMode;
      section.querySelectorAll("[data-target-mode]").forEach((b) =>
        b.classList.toggle("active", b.dataset.targetMode === targetMode)
      );
      updateStep2Visibility();
    });
  });

  runBtn.addEventListener("click", runPlaybook);

  // ── Lifecycle ─────────────────────────────────────────────────────────
  function activate() {
    ansibleApi = null;
    selectedPlaybookId = null;
    selectedServerIds = new Set();
    loadData();
    updateStepStates();
  }

  function deactivate() {
    // Cleanup wenn noetig
  }

  return { activate, deactivate };
}

function esc(str) {
  return String(str ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}
