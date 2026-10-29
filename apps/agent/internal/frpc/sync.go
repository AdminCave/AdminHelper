// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package frpc

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"time"

	"adminhelper-agent/internal/config"
	"adminhelper-agent/internal/enroll"
)

// The frpc service actions are seams so tests can stub them (they shell out to systemctl and frpc).
var (
	restartService = restartFrpc
	disableService = disableFrpc
	enableService  = enableFrpcService
	isActive       = frpcActive
	reloadService  = reloadFrpc
	isDown         = frpcDown
	ownsAdminPort  = frpcOwnsAdminPort
)

// ensureDataDir secures a directory of the agent's data; a seam, so that a test can have it fail.
var ensureDataDir = config.EnsureDataDir

// localPreamble goes in front of the server's frpc.toml, followed by the admin API's head
// (adminAPI.head). frp defaults loginFailExit to true: frpc then exits when frps is unreachable
// at its first login, and systemd restarts it every 5 s. The head stands before every table, so
// its keys land in the root; the server sets none of them (checkServerConfig).
const localPreamble = "loginFailExit = false\n"

// Sync checks for config changes and updates frpc (port of do_sync). Its requests to the server
// end with ctx.
func Sync(ctx context.Context) error {
	cfg, err := config.LoadFrpcConfig()
	if err != nil {
		if os.IsNotExist(err) {
			// Every provisioning writes it since R-0398; a host provisioned without a tunnel
			// before has none and no API key to sync with.
			logger.Infof("No sync config at %s, skipping. Provisioned without a tunnel before this agent version? "+
				"To get its tunnels, provision this host once more: %s", config.FrpAdminHelperConf(), enroll.ReprovisionHint)
			return nil
		}
		return fmt.Errorf("Config laden: %w", err)
	}

	if cfg.AdminHelperURL == "" || cfg.APIKey == "" || cfg.ServerID == "" {
		return fmt.Errorf("adminhelper.conf unvollstaendig")
	}

	// mTLS with the enrolled client cert when present; legacy fallback otherwise.
	client, err := enroll.ServerClient(config.AgentPkiDir(), cfg.CACert, cfg.Insecure, 30*time.Second)
	if err != nil {
		return fmt.Errorf("HTTP-Client: %w", err)
	}
	// Close idle keep-alive connections on return: a fresh client is built per sync, so otherwise
	// the discarded transport's idle conns linger up to ~90s (IdleConnTimeout) before GC (5.6).
	defer client.CloseIdleConnections()

	// Fetch the remote hash
	hashURL := fmt.Sprintf("%s/api/frp/provision/%s/config-hash", cfg.AdminHelperURL, cfg.ServerID)
	hashBody, err := httpGet(ctx, client, hashURL, cfg.APIKey)
	if err != nil {
		// Propagate like the config fetch below (same error class): a persistently
		// broken sync (rotated API key, expired mTLS cert, wrong URL) must surface
		// as an error, not hide as a warning while the run reports success.
		return fmt.Errorf("Config-Hash abfragen: %w", err)
	}
	remoteHash, err := parseConfigHash(hashBody)
	if errors.Is(err, errNoFrpConfig) {
		if frpcGone() {
			return nil
		}
		if err := secureFrpDir(); err != nil {
			return err
		}
		unlock, err := lockFrpc(ctx)
		if err != nil {
			return err
		}
		defer unlock()
		return syncWithoutFrpConfig(ctx)
	}
	if err != nil {
		return fmt.Errorf("Hash-Antwort parsen: %w", err)
	}

	// Read the local hash
	localHash := ""
	if data, err := os.ReadFile(config.FrpHashFile()); err == nil {
		localHash = strings.TrimSpace(string(data))
	}

	// Checked whatever the hash says: a changed config does not free a held admin port. Without an
	// answer from systemd a frpc that may run must not count as stuck, which would renew its admin
	// API and restart it; a changed config then reaches it only by a reload (startFrpc), so the sync
	// goes on only while frpc listens on its admin API, and otherwise changes nothing.
	stuck, err := frpcStuck(ctx)
	if err != nil {
		if remoteHash == localHash || !adminAPIListens() {
			return err
		}
		logger.Warnf("%v; frpc listens on its admin API, the sync tries a reload", err)
	}
	// After an agent update the text in place has not been through this agent's check yet: fetch
	// and check it once, even with the same hash.
	recheck := localHash != "" && checkedBy() != checkedByLine(localHash)
	unchanged := remoteHash == localHash && !stuck && !configWithoutTunnel()
	if remoteHash == localHash {
		if unchanged && !recheck {
			return nil
		}
	} else {
		logger.Infof("Config-Aenderung erkannt. Aktualisiere...")
	}

	// Fetch the new config
	configURL := fmt.Sprintf("%s/api/frp/provision/%s/config", cfg.AdminHelperURL, cfg.ServerID)
	newConfig, err := httpGet(ctx, client, configURL, cfg.APIKey)
	if err != nil {
		return fmt.Errorf("neue Config laden: %w", err)
	}

	// Verify the delivered bytes match the advertised hash before trusting them (4.10). The
	// hash and config endpoints both return sha256(generate_frpc_toml(...)), so a truncated or
	// garbled 200 (gateway error page, mid-flight config change) is caught here instead of being
	// written and sealed with remoteHash — which would crash-loop frpc on broken TOML with no
	// self-repair, since localHash would then equal remoteHash.
	if got := hashConfig(newConfig); got != remoteHash {
		return fmt.Errorf("gelieferte Config passt nicht zum Hash (erwartet %s, erhalten %s)", remoteHash, got)
	}
	if err := secureFrpDir(); err != nil {
		return err
	}
	// Taken only on a change, and nothing above is checked again under it: what the sync applies
	// is the server's config, checked against its hash, and should a provisioning have held the
	// lock meanwhile, the next run compares the hashes again.
	unlock, err := lockFrpc(ctx)
	if err != nil {
		return err
	}
	defer unlock()
	if unchanged {
		// The check passes the text frpc runs on: nothing to write, reload or restart. A text
		// without a tunnel runs nothing, and applyConfig never checks one either.
		if hasProxies(newConfig) {
			if err := checkServerConfig(newConfig); err != nil {
				return refuseServerConfig(ctx, err)
			}
		}
		return writeCheckedBy(remoteHash)
	}
	// Without a tunnel applyConfig stops frpc, which needs no admin API.
	if stuck && hasProxies(newConfig) {
		logger.Warnf("frpc is not running although %s is in place; renewing its admin API (new port and "+
			"password, after a reboot another process may hold the old port) and starting it again.", config.FrpConfigFile())
		if _, err := renewAdminAPI(); err != nil {
			return err
		}
	}
	return applyConfig(ctx, newConfig, true)
}

// secureFrpDir secures the FRP directory, on Windows the data root first, before Sync changes
// a file in it. Sync writes and removes there by path, so it does that only in a directory it
// secured in the same run: the Windows service keeps running when its start could not secure
// the data root. Sync does not call it on a run without a change, which so walks no tree.
func secureFrpDir() error {
	dir := config.FrpDir()
	if err := ensureDataDir(dir); err != nil {
		return fmt.Errorf("secure the FRP directory %s: %w; frpc and its files stay as they are", dir, err)
	}
	return nil
}

// frpcLockWait is how long a change to frpc's state waits for the frpc lock before it gives
// up. The sync and the provisioning hold the lock for a few service calls, on Linux of 15 s at
// most each (systemctlTimeout).
var frpcLockWait = 60 * time.Second

// frpcLockFile is the file in the FRP directory whose exclusive lock serializes the changes to
// frpc's state: frpc.toml (staged under the fixed name frpc.toml.tmp), the hashes, admin.conf,
// adminhelper.conf and the frpc service. A run of the agent (Sync) and a provisioning (Apply)
// would otherwise change them at the same time.
func frpcLockFile() string { return filepath.Join(config.FrpDir(), "frpc.lock") }

// lockFrpc waits for the frpc lock, at most frpcLockWait or until ctx ends, and returns the
// function that releases it. The lock file is created only in a directory the same call has
// secured (secureFrpDir, EnsureDataDir), like every other file there.
func lockFrpc(ctx context.Context) (unlock func(), err error) {
	unlock, err = enroll.LockFile(ctx, frpcLockFile(), frpcLockWait)
	if err != nil {
		return nil, fmt.Errorf("lock the frpc state: %w; frpc and its files stay as they are", err)
	}
	return unlock, nil
}

// frpcStuck reports whether frpc should run but does not. It should run while frpc.toml is in
// place: the sync removes it when no tunnel is left. frpc does not start without its admin port.
func frpcStuck(ctx context.Context) (bool, error) {
	if _, err := os.Stat(config.FrpConfigFile()); err != nil {
		return false, nil
	}
	return isDown(ctx)
}

// configWithoutTunnel reports whether frpc.toml is in place without a tunnel. An older agent may
// have written the server's text without one and left frpc running on it; the stored hash then
// matches the server's, and only the file shows that frpc must stop.
func configWithoutTunnel() bool {
	data, err := os.ReadFile(config.FrpConfigFile())
	return err == nil && !hasProxies(data)
}

// errFrpcService marks a failure to start or stop frpc, apart from a failure to write or remove
// its files: the provisioning only warns about it, since the next run retries.
var errFrpcService = errors.New("frpc service action failed")

// applyConfig puts a server-built frpc.toml in place and frpc in the matching state; Sync and
// the provisioning (Apply) share it. The stored hash is the one of the server's text, not of the
// file written (preamble, identity paths), so it matches the server's config-hash. mayReload lets
// a running frpc take the new proxies by a reload (startFrpc).
func applyConfig(ctx context.Context, serverToml []byte, mayReload bool) error {
	remoteHash := hashConfig(serverToml)

	// The server sends the common part also with no tunnel left; frpc must not run without one.
	if !hasProxies(serverToml) {
		if err := stopFrpc(ctx); err != nil {
			return err
		}
		if err := config.WriteFile(config.FrpHashFile(), []byte(remoteHash), 0644); err != nil {
			return fmt.Errorf("write the config hash: %w", err)
		}
		if err := writeCheckedBy(remoteHash); err != nil {
			return err
		}
		logger.Infof("No tunnel for this host, frpc stopped and disabled.")
		return nil
	}

	if err := checkServerConfig(serverToml); err != nil {
		return refuseServerConfig(ctx, err)
	}
	api, err := loadAdminAPI()
	if err != nil {
		return err
	}
	frpcToml := append([]byte(localPreamble+api.head()), rewriteIdentityPaths(serverToml)...)

	// Write the config atomically (0600: contains the frp auth token). A plain in-place WriteFile
	// truncates first, so a crash/kill between truncate and write would leave a partial frpc.toml
	// that frpc.service crash-loops on (Restart=on-failure) until the next sync ~5 min later. Stage
	// to a temp file + rename, like enroll.stageIdentity (4.82).
	tmp := config.FrpConfigFile() + ".tmp"
	if err := config.WriteFile(tmp, frpcToml, 0600); err != nil {
		return fmt.Errorf("frpc.toml schreiben: %w", err)
	}
	if err := os.Rename(tmp, config.FrpConfigFile()); err != nil {
		return fmt.Errorf("frpc.toml aktivieren: %w", err)
	}
	// German like before, logged before frpc starts: the desktop tunnel E2E greps the
	// provisioning output for it, and its container has no systemctl to start frpc.
	logger.Infof("frpc.toml geschrieben")

	started, err := startFrpc(ctx, frpcToml, api.port, mayReload)
	if err != nil {
		return err
	}

	// Persist the hash only AFTER frpc started on the new file (4.11): a failed start then leaves
	// the hash mismatch standing, so the next run retries the sync instead of freezing the old
	// config on disk until the next server-side change.
	if err := config.WriteFile(config.FrpHashFile(), []byte(remoteHash), 0644); err != nil {
		return fmt.Errorf("Hash schreiben: %w", err)
	}
	if err := writeCheckedBy(remoteHash); err != nil {
		return err
	}
	logger.Infof("frpc.toml updated, frpc %s.", started)
	return nil
}

// agentVersion is the version of this agent, set by main. A text stored under another version
// (or none: every agent before this file existed) is checked once more by the next sync.
var agentVersion = "dev"

// SetAgentVersion records the agent's version for the check after an update.
func SetAgentVersion(v string) { agentVersion = v }

// checkedByFile holds the agent version that last checked the stored text, with that text's
// hash: a text another agent wrote under the same version's marker (a downgrade in between)
// does not count as checked.
func checkedByFile() string { return filepath.Join(config.FrpDir(), ".checked-by") }

// checkedByLine is what checkedByFile holds once this agent checked the text with hash.
func checkedByLine(hash string) string { return agentVersion + " " + hash }

// checkedBy is what checkedByFile records, "" without one.
func checkedBy() string {
	data, err := os.ReadFile(checkedByFile())
	if err != nil {
		return ""
	}
	return strings.TrimSpace(string(data))
}

func writeCheckedBy(hash string) error {
	if err := config.WriteFile(checkedByFile(), []byte(checkedByLine(hash)), 0644); err != nil {
		return fmt.Errorf("write %s: %w", checkedByFile(), err)
	}
	return nil
}

func removeCheckedBy() error {
	if err := os.Remove(checkedByFile()); err != nil && !os.IsNotExist(err) {
		return fmt.Errorf("remove %s: %w", checkedByFile(), err)
	}
	return nil
}

// refuseServerConfig stops frpc on a server text the check refuses: what frpc runs on must be a
// text the check accepted, and the frpc.toml in place may predate the check or this server's
// text. Without the hash the next run fetches and checks again; with nothing left (frpcGone) a
// former run already stopped frpc, which keeps systemctl out of every timer run.
func refuseServerConfig(ctx context.Context, refusal error) error {
	if frpcGone() {
		return refusal
	}
	// Not wrapped: the provisioning turns an errFrpcService failure into a warning, and a
	// refusal must stay an error even when stopping frpc failed as well.
	if err := stopFrpc(ctx); err != nil {
		return fmt.Errorf("%w; stopping frpc failed as well: %v", refusal, err)
	}
	if err := os.Remove(config.FrpHashFile()); err != nil && !os.IsNotExist(err) {
		return errors.Join(refusal, fmt.Errorf("remove the config hash: %w", err))
	}
	if err := removeCheckedBy(); err != nil {
		return errors.Join(refusal, err)
	}
	return fmt.Errorf("frpc stopped until the server sends a config that passes: %w", refusal)
}

// startFrpc puts frpc onto the frpc.toml just written and says how. frpc is stopped on the first
// tunnel and after a former run stopped it: enable it, so it also runs after a reboot. A running
// frpc reloads over its admin API on adminPort, which keeps unchanged tunnels and their
// connections; frp takes only the proxies from a reload, so it stands in for a restart only while
// the common part is the one frpc started on. The reload goes only to the agent's own frpc
// (ownsAdminPort). The provisioning (mayReload false) always restarts: it may have enrolled a new
// identity, and a reload does not connect to frps anew, only a restart does. Without an answer
// from systemd the reload is the only way to drop a removed tunnel while others remain.
func startFrpc(ctx context.Context, frpcToml []byte, adminPort int, mayReload bool) (string, error) {
	common := hashConfig(commonPart(frpcToml))
	reloadable := mayReload && startedCommon() == common
	active, err := isActive(ctx)
	if err != nil {
		// Fails like a start: the hash stays for the next run, the provisioning only warns.
		if !reloadable || !ownsAdminPort(adminPort) {
			return "", fmt.Errorf("%w: %w", errFrpcService, err)
		}
		if reloadErr := reloadService(ctx); reloadErr != nil {
			return "", fmt.Errorf("%w: %w; the reload over the admin API failed too: %v", errFrpcService, err, reloadErr)
		}
		return "reloaded without an answer from systemd", nil
	}
	if !active {
		if err := startedOn(ctx, common, enableService, "enable and start frpc"); err != nil {
			return "", err
		}
		return "enabled and started", nil
	}
	if reloadable {
		if !ownsAdminPort(adminPort) {
			logger.Warnf("frpc does not listen on its admin port 127.0.0.1:%d, restarting frpc instead of a reload", adminPort)
		} else if err := reloadService(ctx); err != nil {
			logger.Warnf("frpc reload failed, restarting frpc instead: %v", err)
		} else {
			return "reloaded", nil
		}
	}
	if err := startedOn(ctx, common, restartService, "restart frpc"); err != nil {
		return "", err
	}
	return "restarted", nil
}

// startedHashFile holds the hash of the common part of the frpc.toml frpc last started on.
func startedHashFile() string { return filepath.Join(config.FrpDir(), ".started-hash") }

// startedOn runs start (enable or restart) and records the common part frpc started on. The old
// record goes first: after a failed start frpc may still run on the old common part, and the next
// run must restart it rather than reload. A run that has ended starts nothing and keeps the record:
// nothing was started, so frpc still runs on the common part recorded.
func startedOn(ctx context.Context, common string, start func(context.Context) error, what string) error {
	if err := ctx.Err(); err != nil {
		return fmt.Errorf("%w: %s: %w", errFrpcService, what, err)
	}
	if err := os.Remove(startedHashFile()); err != nil && !os.IsNotExist(err) {
		return fmt.Errorf("remove %s: %w", startedHashFile(), err)
	}
	if err := start(ctx); err != nil {
		return fmt.Errorf("%w: %s: %w", errFrpcService, what, err)
	}
	if err := config.WriteFile(startedHashFile(), []byte(common), 0600); err != nil {
		return fmt.Errorf("write %s: %w", startedHashFile(), err)
	}
	return nil
}

// startedCommon is the hash startedOn recorded, "" without one.
func startedCommon() string {
	data, err := os.ReadFile(startedHashFile())
	if err != nil {
		return ""
	}
	return string(data)
}

// commonPart is the text of a frpc.toml before its first [[proxies]] table, the part frp takes
// only at start. The server's generator puts every common key there.
func commonPart(toml []byte) []byte {
	rest := toml
	for len(rest) > 0 {
		line, next, _ := bytes.Cut(rest, []byte("\n"))
		if string(bytes.TrimSpace(line)) == "[[proxies]]" {
			return toml[:len(toml)-len(rest)]
		}
		rest = next
	}
	return toml
}

// syncWithoutFrpConfig stops frpc and removes frpc.toml and the hash, on a null hash and for a
// provisioning without an FRP bundle. Neither file left (frpcGone) means a former run already
// stopped it; returning early keeps systemctl out of every timer run.
func syncWithoutFrpConfig(ctx context.Context) error {
	if frpcGone() {
		return nil
	}
	if err := stopFrpc(ctx); err != nil {
		return err
	}
	if err := os.Remove(config.FrpHashFile()); err != nil && !os.IsNotExist(err) {
		return fmt.Errorf("remove the config hash: %w", err)
	}
	if err := removeCheckedBy(); err != nil {
		return err
	}
	logger.Infof("No FRP config or tunnel for this host on the server, frpc stopped and disabled.")
	return nil
}

// frpcGone reports whether neither frpc.toml nor the hash is left: without an FRP config on the
// server, a run then has nothing to change.
func frpcGone() bool {
	_, confErr := os.Stat(config.FrpConfigFile())
	_, hashErr := os.Stat(config.FrpHashFile())
	return os.IsNotExist(confErr) && os.IsNotExist(hashErr)
}

// stopFrpc stops and disables frpc, then removes frpc.toml: it holds the frps token. The
// order keeps the file for the retry when the stop fails.
func stopFrpc(ctx context.Context) error {
	if err := disableService(ctx); err != nil {
		return fmt.Errorf("%w: stop and disable frpc: %w", errFrpcService, err)
	}
	if err := os.Remove(config.FrpConfigFile()); err != nil && !os.IsNotExist(err) {
		return fmt.Errorf("remove frpc.toml: %w", err)
	}
	return nil
}

// hasProxies reports whether a server-built frpc.toml has a tunnel: the generator writes
// each one as a [[proxies]] table.
func hasProxies(toml []byte) bool {
	for _, line := range bytes.Split(toml, []byte("\n")) {
		if string(bytes.TrimSpace(line)) == "[[proxies]]" {
			return true
		}
	}
	return false
}

// errNoFrpConfig is parseConfigHash's answer to `{"hash": null}`: the server has no FRP
// config for this host (R-0398). A missing field stays "" as before.
var errNoFrpConfig = errors.New("no FRP config for this host on the server")

// parseConfigHash reads the hash value from the server response (`{"hash": "..."}`).
func parseConfigHash(body []byte) (string, error) {
	var hashResp struct {
		Hash json.RawMessage `json:"hash"`
	}
	if err := json.Unmarshal(body, &hashResp); err != nil {
		return "", err
	}
	if hashResp.Hash == nil {
		return "", nil
	}
	if string(hashResp.Hash) == "null" {
		return "", errNoFrpConfig
	}
	var hash string
	if err := json.Unmarshal(hashResp.Hash, &hash); err != nil {
		return "", err
	}
	return hash, nil
}

// hashConfig computes the hex-encoded SHA256 hash of the config bytes.
func hashConfig(data []byte) string {
	return fmt.Sprintf("%x", sha256.Sum256(data))
}
