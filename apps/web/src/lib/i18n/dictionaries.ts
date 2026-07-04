// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

/* Web UI translations. Originally seeded from the old server frontend, then pruned
 * to the keys the web client actually uses (audit 2.53) — add only keys with a real
 * caller; the i18n.test.ts "no unused keys" guard fails on dead ones. */

export type Language = 'de' | 'en';
export type Translations = Record<Language, Record<string, string>>;

export const translations: Translations = {
  de: {
    'error.generic': 'Fehler',
    // ── Login ──────────────────────────────────────────────────────────
    'login.username': 'Benutzername',
    'login.password': 'Passwort',
    'login.submit': 'Anmelden',
    'login.failed': 'Anmeldung fehlgeschlagen',

    // ── Nav ────────────────────────────────────────────────────────────
    'nav.users': 'Benutzer',
    'nav.apikeys': 'API-Keys',
    'nav.hooks': 'Hooks',
    'nav.frp': 'FRP Tunnels',
    'nav.audit': 'Audit-Log',
    'nav.logout': 'Abmelden',

    // ── Roles ──────────────────────────────────────────────────────────
    'role.admin': 'Admin',
    'role.user': 'Benutzer',

    // ── Common Actions ─────────────────────────────────────────────────
    'action.save': 'Speichern',
    'action.cancel': 'Abbrechen',
    'action.delete': 'Löschen',
    'action.edit': 'Bearbeiten',
    'action.close': 'Schließen',
    'action.copy': 'Kopieren',
    'action.create': 'Erstellen',
    'action.refresh': 'Aktualisieren',
    'action.run': 'Ausführen',
    'action.enable': 'Aktivieren',
    'action.disable': 'Deaktivieren',

    // ── Common Labels ──────────────────────────────────────────────────
    'label.name': 'Name',
    'label.type': 'Typ',
    'label.status': 'Status',
    'label.created': 'Erstellt',

    // ── Server Table Headers ──────────────────────────────────────────
    'table.type': 'Typ',

    // ── Users Page ────────────────────────────────────────────────────
    'page.users.title': 'Benutzer',
    'page.users.subtitle': 'Zugriffsverwaltung',
    'page.users.add': '+ Benutzer',
    'page.users.empty': 'Keine Benutzer vorhanden.',
    'page.users.me': '(ich)',
    'page.users.noServers': 'Keine Server vorhanden.',
    'page.users.username': 'Benutzername',
    'page.users.role': 'Rolle',

    // ── User Modal ────────────────────────────────────────────────────
    'modal.user.title': 'Benutzer bearbeiten',
    'modal.user.titleNew': 'Neuer Benutzer',
    'modal.user.username': 'Benutzername *',
    'modal.user.password': 'Passwort *',
    'modal.user.passwordEdit': 'Neues Passwort (leer = unverändert)',
    'modal.user.adminRights': 'Admin-Rechte',
    'modal.user.assignServers': 'Server zuweisen (FRP-Zugriff)',
    'modal.user.passwordRequired': 'Passwort erforderlich',

    // ── User Toasts ───────────────────────────────────────────────────
    'toast.user.saved': 'Benutzer gespeichert',
    'toast.user.created': 'Benutzer erstellt',
    'toast.user.deleted': 'Benutzer gelöscht',
    'confirm.user.delete': 'Benutzer wirklich löschen?',

    // ── Audit ──────────────────────────────────────────────────────────
    'page.audit.title': 'Audit-Log',
    'page.audit.subtitle':
      'Wer hat wann was getan — Verbindungen, Zugriffe, Anmeldungen und Änderungen.',
    'page.audit.empty': 'Keine Audit-Einträge gefunden.',
    'page.audit.loading': 'Lädt …',
    'page.audit.filter.search': 'Suche (Actor/Objekt)',
    'page.audit.filter.action': 'Aktion (z. B. connection.created)',
    'page.audit.filter.actorType': 'Actor-Typ',
    'page.audit.filter.allActors': 'Alle Actors',
    'page.audit.filter.apply': 'Filtern',
    'page.audit.filter.reset': 'Zurücksetzen',
    'page.audit.col.time': 'Zeit',
    'page.audit.col.actor': 'Actor',
    'page.audit.col.action': 'Aktion',
    'page.audit.col.object': 'Objekt',
    'page.audit.col.ip': 'IP',
    'page.audit.col.status': 'Status',
    'page.audit.truncated': 'Nur die neuesten {n} Einträge — Filter verfeinern für ältere.',

    // ── API-Keys Page ─────────────────────────────────────────────────
    'page.apikeys.title': 'API-Keys',
    'page.apikeys.subtitle': 'Programmatischer Zugriff (z. B. Client-Sync)',
    'page.apikeys.add': '+ API-Key',
    'page.apikeys.empty': 'Keine API-Keys vorhanden.',
    'page.apikeys.permission': 'Berechtigung',
    'page.apikeys.readWrite': 'Lesen & Schreiben',
    'page.apikeys.readOnly': 'Nur lesen',

    // ── API-Key Modal ─────────────────────────────────────────────────
    'modal.apikey.titleNew': 'Neuer API-Key',
    'modal.apikey.titleReveal': 'API-Key erstellt',
    'modal.apikey.revealHint': 'Dieser Schlüssel wird nur einmal angezeigt. Kopiere ihn jetzt.',
    'toast.apikey.copied': 'In Zwischenablage kopiert',
    'toast.apikey.deleted': 'API-Key gelöscht',
    'confirm.apikey.delete': 'API-Key wirklich löschen?',

    // ── Hooks Page ────────────────────────────────────────────────────
    'page.hooks.title': 'Hooks',
    'page.hooks.subtitle': 'Webhooks, Event-Hooks und Scheduled Hooks',
    'page.hooks.add': '+ Hook',
    'page.hooks.empty': 'Keine Hooks vorhanden.',
    'page.hooks.lastRun': 'Letzter Lauf',
    'page.hooks.next': 'Nächster: {time}',
    'page.hooks.active': 'Aktiv',
    'page.hooks.inactive': 'Inaktiv',
    'page.hooks.rotateToken': 'Token rotieren',

    // ── Hook Events ───────────────────────────────────────────────────
    'hook.event.connection.created': 'Verbindung erstellt',
    'hook.event.connection.updated': 'Verbindung geändert',
    'hook.event.connection.deleted': 'Verbindung gelöscht',
    'hook.event.connections.imported': 'Verbindungen importiert',
    'hook.event.user.created': 'Benutzer erstellt',
    'hook.event.user.deleted': 'Benutzer gelöscht',
    'hook.event.server.created': 'Server erstellt',
    'hook.event.server.updated': 'Server geändert',
    'hook.event.server.deleted': 'Server gelöscht',
    'hook.event.server.startup': 'App gestartet',
    'hook.event.frp.config.created': 'FRP-Config erstellt',
    'hook.event.frp.config.updated': 'FRP-Config geändert',
    'hook.event.frp.config.deleted': 'FRP-Config gelöscht',
    'hook.event.frp.tunnel.created': 'FRP-Tunnel erstellt',
    'hook.event.frp.tunnel.updated': 'FRP-Tunnel geändert',
    'hook.event.frp.tunnel.deleted': 'FRP-Tunnel gelöscht',

    // ── Hook Script Help ──────────────────────────────────────────────
    'hook.scriptHelp.webhook':
      'Kontext: <code>payload</code>, <code>headers</code>, <code>params</code>',
    'hook.scriptHelp.event': 'Kontext: <code>event_type</code>, <code>event_data</code>',
    'hook.scriptHelp.schedule': 'Kontext: <code>triggered_at</code>, <code>last_run</code>',
    'hook.scriptHelp.base':
      'Verfügbar: <code>load_connections()</code>, <code>save_connections(list)</code>, <code>uuid4()</code>, <code>result</code>, <code>logs</code>, <code>log(msg)</code> – <code>import</code> erlaubt',

    // ── Hook Modal ────────────────────────────────────────────────────
    'modal.hook.title': 'Hook bearbeiten',
    'modal.hook.titleNew': 'Neuer Hook',
    'modal.hook.description': 'Beschreibung',
    'modal.hook.descPlaceholder': 'Optionale Beschreibung',
    'modal.hook.type': 'Typ *',
    'modal.hook.typeWebhook': 'Webhook – per HTTP-Call auslösen',
    'modal.hook.typeEvent': 'Event-Hook – bei internem Ereignis',
    'modal.hook.typeSchedule': 'Scheduled Hook – nach Zeitplan',
    'modal.hook.events': 'Events *',
    'modal.hook.interval': 'Intervall *',
    'modal.hook.interval5m': 'Alle 5 Minuten',
    'modal.hook.interval15m': 'Alle 15 Minuten',
    'modal.hook.interval30m': 'Alle 30 Minuten',
    'modal.hook.interval1h': 'Jede Stunde',
    'modal.hook.interval6h': 'Alle 6 Stunden',
    'modal.hook.interval12h': 'Alle 12 Stunden',
    'modal.hook.interval24h': 'Jeden Tag',
    'modal.hook.intervalCustom': 'Cron-Ausdruck…',
    'modal.hook.cron': 'Cron-Ausdruck',
    'modal.hook.cronFormat': 'Format: Minute Stunde Tag Monat Wochentag',
    'modal.hook.script': 'Script *',
    'modal.hook.scriptPlaceholder': '# Python-Script hier eingeben',
    'modal.hook.selectEvent': 'Bitte mindestens ein Event auswählen',
    'modal.hook.selectInterval': 'Bitte ein Intervall angeben',

    // ── Hook Toasts ───────────────────────────────────────────────────
    'toast.hook.saved': 'Hook gespeichert',
    'toast.hook.created': 'Hook erstellt',
    'toast.hook.deleted': 'Hook gelöscht',
    'toast.hook.running': 'Hook wird ausgeführt…',
    'toast.hook.tokenCopied': 'Token kopiert',
    'toast.hook.tokenGenerated': 'Neuer Token generiert',
    'confirm.hook.delete': 'Hook wirklich löschen?',
    'confirm.hook.rotateToken':
      'Token fuer \u201E{name}\u201C wirklich neu generieren? Der alte Token wird ungueltig.',
    'hook.result.title': 'Ergebnis: {name}',
    'hook.webhookToken.title': 'Webhook-Token',
    'hook.webhookToken.hint': 'Dieser Token wird nur einmal angezeigt. Kopiere ihn jetzt.',
    'hook.webhookToken.triggerUrl': 'Aufruf-URL:',

    // ── FRP Page ──────────────────────────────────────────────────────
    'page.frp.title': 'FRP Tunnels',
    'page.frp.subtitle': 'Tunnel-Konfigurationen verwalten und TOML-Configs generieren',
    'page.frp.noConfig':
      'Noch keine FRP-Server Konfiguration vorhanden. Klicke auf "Konfigurieren" um zu starten.',
    'page.frp.mtlsActive': 'Immer aktiv',
    'page.frp.editConfig': 'Konfiguration bearbeiten',
    'page.frp.createConfig': 'Konfigurieren',
    'page.frp.bulkZip': 'Alle als ZIP',
    'page.frp.status': 'Status',

    // ── FRP Config Modal ──────────────────────────────────────────────
    'modal.frpConfig.title': 'FRP-Server bearbeiten',
    'modal.frpConfig.titleNew': 'Neue FRP-Server Konfiguration',
    'modal.frpConfig.serverAddr': 'Server-Adresse *',
    'modal.frpConfig.bindPort': 'Bind Port',
    'modal.frpConfig.vhostPort': 'vHost HTTPS Port',
    'modal.frpConfig.authToken': 'Auth Token',
    'modal.frpConfig.authTokenPlaceholder': 'wird auto-generiert',
    'modal.frpConfig.subdomainHost': 'Subdomain Host',
    'modal.frpConfig.maxPorts': 'Max Ports/Client',
    'modal.frpConfig.dashPort': 'Dashboard Port',
    'modal.frpConfig.dashUser': 'Dashboard User',
    'modal.frpConfig.dashPass': 'Dashboard Passwort',

    // ── FRP Toasts ────────────────────────────────────────────────────
    'toast.frpConfig.saved': 'FRP-Config gespeichert',
    'toast.frpConfig.created': 'FRP-Config erstellt',
    'toast.frp.copied': 'In Zwischenablage kopiert',
    'toast.frp.zipDownloaded': 'ZIP heruntergeladen',

    // ── FRP Status ────────────────────────────────────────────────────
    'frp.status.title': 'frps Tunnel-Status',
    'frp.status.unreachable': 'frps nicht erreichbar: {error}',
    'frp.status.noProxies': 'Keine aktiven Proxies auf dem frps-Server.',
    'frp.status.connections': 'Verbindungen',

    // ── FRP Provisioning ──────────────────────────────────────────────
    'state.loading': 'Wird geladen...',
  },

  en: {
    'error.generic': 'Error',
    // ── Login ──────────────────────────────────────────────────────────
    'login.username': 'Username',
    'login.password': 'Password',
    'login.submit': 'Sign in',
    'login.failed': 'Login failed',

    // ── Nav ────────────────────────────────────────────────────────────
    'nav.users': 'Users',
    'nav.apikeys': 'API Keys',
    'nav.hooks': 'Hooks',
    'nav.frp': 'FRP Tunnels',
    'nav.audit': 'Audit log',
    'nav.logout': 'Sign out',

    // ── Roles ──────────────────────────────────────────────────────────
    'role.admin': 'Admin',
    'role.user': 'User',

    // ── Common Actions ─────────────────────────────────────────────────
    'action.save': 'Save',
    'action.cancel': 'Cancel',
    'action.delete': 'Delete',
    'action.edit': 'Edit',
    'action.close': 'Close',
    'action.copy': 'Copy',
    'action.create': 'Create',
    'action.refresh': 'Refresh',
    'action.run': 'Run',
    'action.enable': 'Enable',
    'action.disable': 'Disable',

    // ── Common Labels ──────────────────────────────────────────────────
    'label.name': 'Name',
    'label.type': 'Type',
    'label.status': 'Status',
    'label.created': 'Created',

    // ── Server Table Headers ──────────────────────────────────────────
    'table.type': 'Type',

    // ── Users Page ────────────────────────────────────────────────────
    'page.users.title': 'Users',
    'page.users.subtitle': 'Access management',
    'page.users.add': '+ User',
    'page.users.empty': 'No users available.',
    'page.users.me': '(me)',
    'page.users.noServers': 'No servers available.',
    'page.users.username': 'Username',
    'page.users.role': 'Role',

    // ── User Modal ────────────────────────────────────────────────────
    'modal.user.title': 'Edit user',
    'modal.user.titleNew': 'New user',
    'modal.user.username': 'Username *',
    'modal.user.password': 'Password *',
    'modal.user.passwordEdit': 'New password (empty = unchanged)',
    'modal.user.adminRights': 'Admin rights',
    'modal.user.assignServers': 'Assign servers (FRP access)',
    'modal.user.passwordRequired': 'Password required',

    // ── User Toasts ───────────────────────────────────────────────────
    'toast.user.saved': 'User saved',
    'toast.user.created': 'User created',
    'toast.user.deleted': 'User deleted',
    'confirm.user.delete': 'Really delete this user?',

    // ── Audit ──────────────────────────────────────────────────────────
    'page.audit.title': 'Audit log',
    'page.audit.subtitle': 'Who did what, and when — connections, access, logins and changes.',
    'page.audit.empty': 'No audit entries found.',
    'page.audit.loading': 'Loading …',
    'page.audit.filter.search': 'Search (actor/object)',
    'page.audit.filter.action': 'Action (e.g. connection.created)',
    'page.audit.filter.actorType': 'Actor type',
    'page.audit.filter.allActors': 'All actors',
    'page.audit.filter.apply': 'Filter',
    'page.audit.filter.reset': 'Reset',
    'page.audit.col.time': 'Time',
    'page.audit.col.actor': 'Actor',
    'page.audit.col.action': 'Action',
    'page.audit.col.object': 'Object',
    'page.audit.col.ip': 'IP',
    'page.audit.col.status': 'Status',
    'page.audit.truncated': 'Showing the latest {n} entries — narrow the filters for older ones.',

    // ── API-Keys Page ─────────────────────────────────────────────────
    'page.apikeys.title': 'API Keys',
    'page.apikeys.subtitle': 'Programmatic access (e.g. client sync)',
    'page.apikeys.add': '+ API Key',
    'page.apikeys.empty': 'No API keys available.',
    'page.apikeys.permission': 'Permission',
    'page.apikeys.readWrite': 'Read & Write',
    'page.apikeys.readOnly': 'Read only',

    // ── API-Key Modal ─────────────────────────────────────────────────
    'modal.apikey.titleNew': 'New API Key',
    'modal.apikey.titleReveal': 'API Key created',
    'modal.apikey.revealHint': 'This key will only be shown once. Copy it now.',
    'toast.apikey.copied': 'Copied to clipboard',
    'toast.apikey.deleted': 'API key deleted',
    'confirm.apikey.delete': 'Really delete this API key?',

    // ── Hooks Page ────────────────────────────────────────────────────
    'page.hooks.title': 'Hooks',
    'page.hooks.subtitle': 'Webhooks, event hooks and scheduled hooks',
    'page.hooks.add': '+ Hook',
    'page.hooks.empty': 'No hooks available.',
    'page.hooks.lastRun': 'Last run',
    'page.hooks.next': 'Next: {time}',
    'page.hooks.active': 'Active',
    'page.hooks.inactive': 'Inactive',
    'page.hooks.rotateToken': 'Rotate token',

    // ── Hook Events ───────────────────────────────────────────────────
    'hook.event.connection.created': 'Connection created',
    'hook.event.connection.updated': 'Connection updated',
    'hook.event.connection.deleted': 'Connection deleted',
    'hook.event.connections.imported': 'Connections imported',
    'hook.event.user.created': 'User created',
    'hook.event.user.deleted': 'User deleted',
    'hook.event.server.created': 'Server created',
    'hook.event.server.updated': 'Server updated',
    'hook.event.server.deleted': 'Server deleted',
    'hook.event.server.startup': 'App started',
    'hook.event.frp.config.created': 'FRP config created',
    'hook.event.frp.config.updated': 'FRP config updated',
    'hook.event.frp.config.deleted': 'FRP config deleted',
    'hook.event.frp.tunnel.created': 'FRP tunnel created',
    'hook.event.frp.tunnel.updated': 'FRP tunnel updated',
    'hook.event.frp.tunnel.deleted': 'FRP tunnel deleted',

    // ── Hook Script Help ──────────────────────────────────────────────
    'hook.scriptHelp.webhook':
      'Context: <code>payload</code>, <code>headers</code>, <code>params</code>',
    'hook.scriptHelp.event': 'Context: <code>event_type</code>, <code>event_data</code>',
    'hook.scriptHelp.schedule': 'Context: <code>triggered_at</code>, <code>last_run</code>',
    'hook.scriptHelp.base':
      'Available: <code>load_connections()</code>, <code>save_connections(list)</code>, <code>uuid4()</code>, <code>result</code>, <code>logs</code>, <code>log(msg)</code> – <code>import</code> allowed',

    // ── Hook Modal ────────────────────────────────────────────────────
    'modal.hook.title': 'Edit hook',
    'modal.hook.titleNew': 'New hook',
    'modal.hook.description': 'Description',
    'modal.hook.descPlaceholder': 'Optional description',
    'modal.hook.type': 'Type *',
    'modal.hook.typeWebhook': 'Webhook – trigger via HTTP call',
    'modal.hook.typeEvent': 'Event hook – on internal event',
    'modal.hook.typeSchedule': 'Scheduled hook – on schedule',
    'modal.hook.events': 'Events *',
    'modal.hook.interval': 'Interval *',
    'modal.hook.interval5m': 'Every 5 minutes',
    'modal.hook.interval15m': 'Every 15 minutes',
    'modal.hook.interval30m': 'Every 30 minutes',
    'modal.hook.interval1h': 'Every hour',
    'modal.hook.interval6h': 'Every 6 hours',
    'modal.hook.interval12h': 'Every 12 hours',
    'modal.hook.interval24h': 'Every day',
    'modal.hook.intervalCustom': 'Cron expression…',
    'modal.hook.cron': 'Cron expression',
    'modal.hook.cronFormat': 'Format: Minute Hour Day Month Weekday',
    'modal.hook.script': 'Script *',
    'modal.hook.scriptPlaceholder': '# Enter Python script here',
    'modal.hook.selectEvent': 'Please select at least one event',
    'modal.hook.selectInterval': 'Please specify an interval',

    // ── Hook Toasts ───────────────────────────────────────────────────
    'toast.hook.saved': 'Hook saved',
    'toast.hook.created': 'Hook created',
    'toast.hook.deleted': 'Hook deleted',
    'toast.hook.running': 'Running hook…',
    'toast.hook.tokenCopied': 'Token copied',
    'toast.hook.tokenGenerated': 'New token generated',
    'confirm.hook.delete': 'Really delete this hook?',
    'confirm.hook.rotateToken':
      'Really regenerate token for "{name}"? The old token will be invalidated.',
    'hook.result.title': 'Result: {name}',
    'hook.webhookToken.title': 'Webhook token',
    'hook.webhookToken.hint': 'This token will only be shown once. Copy it now.',
    'hook.webhookToken.triggerUrl': 'Trigger URL:',

    // ── FRP Page ──────────────────────────────────────────────────────
    'page.frp.title': 'FRP Tunnels',
    'page.frp.subtitle': 'Manage tunnel configurations and generate TOML configs',
    'page.frp.noConfig': 'No FRP server configuration yet. Click "Configure" to start.',
    'page.frp.mtlsActive': 'Always active',
    'page.frp.editConfig': 'Edit configuration',
    'page.frp.createConfig': 'Configure',
    'page.frp.bulkZip': 'All as ZIP',
    'page.frp.status': 'Status',

    // ── FRP Config Modal ──────────────────────────────────────────────
    'modal.frpConfig.title': 'Edit FRP server',
    'modal.frpConfig.titleNew': 'New FRP server configuration',
    'modal.frpConfig.serverAddr': 'Server address *',
    'modal.frpConfig.bindPort': 'Bind port',
    'modal.frpConfig.vhostPort': 'vHost HTTPS port',
    'modal.frpConfig.authToken': 'Auth token',
    'modal.frpConfig.authTokenPlaceholder': 'auto-generated',
    'modal.frpConfig.subdomainHost': 'Subdomain host',
    'modal.frpConfig.maxPorts': 'Max ports/client',
    'modal.frpConfig.dashPort': 'Dashboard port',
    'modal.frpConfig.dashUser': 'Dashboard user',
    'modal.frpConfig.dashPass': 'Dashboard password',

    // ── FRP Toasts ────────────────────────────────────────────────────
    'toast.frpConfig.saved': 'FRP config saved',
    'toast.frpConfig.created': 'FRP config created',
    'toast.frp.copied': 'Copied to clipboard',
    'toast.frp.zipDownloaded': 'ZIP downloaded',

    // ── FRP Status ────────────────────────────────────────────────────
    'frp.status.title': 'frps Tunnel Status',
    'frp.status.unreachable': 'frps not reachable: {error}',
    'frp.status.noProxies': 'No active proxies on the frps server.',
    'frp.status.connections': 'Connections',

    // ── FRP Provisioning ──────────────────────────────────────────────
    'state.loading': 'Loading...',
  },
};
