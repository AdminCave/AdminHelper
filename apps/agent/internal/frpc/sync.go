// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package frpc

import (
	"bytes"
	"crypto/sha256"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"strings"
	"time"

	"adminhelper-agent/internal/config"
	"adminhelper-agent/internal/enroll"
)

// The frpc service actions are seams so tests can stub them (they shell out to systemctl).
var (
	restartService = restartFrpc
	disableService = disableFrpc
	enableService  = enableFrpcService
	isActive       = frpcActive
)

// localPreamble goes in front of the server's frpc.toml. frp defaults loginFailExit to true:
// frpc then exits when frps is unreachable at its first login, and systemd restarts it every
// 5 s. The server's generator sets no loginFailExit, so the key is never doubled.
const localPreamble = "loginFailExit = false\n"

// Sync checks for config changes and updates frpc (port of do_sync).
func Sync() error {
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
	hashBody, err := httpGet(client, hashURL, cfg.APIKey)
	if err != nil {
		// Propagate like the config fetch below (same error class): a persistently
		// broken sync (rotated API key, expired mTLS cert, wrong URL) must surface
		// as an error, not hide as a warning while the run reports success.
		return fmt.Errorf("Config-Hash abfragen: %w", err)
	}
	remoteHash, err := parseConfigHash(hashBody)
	if errors.Is(err, errNoFrpConfig) {
		return syncWithoutFrpConfig()
	}
	if err != nil {
		return fmt.Errorf("Hash-Antwort parsen: %w", err)
	}

	// Read the local hash
	localHash := ""
	if data, err := os.ReadFile(config.FrpHashFile()); err == nil {
		localHash = strings.TrimSpace(string(data))
	}

	if remoteHash == localHash {
		return nil
	}
	logger.Infof("Config-Aenderung erkannt. Aktualisiere...")

	// Fetch the new config
	configURL := fmt.Sprintf("%s/api/frp/provision/%s/config", cfg.AdminHelperURL, cfg.ServerID)
	newConfig, err := httpGet(client, configURL, cfg.APIKey)
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
	return applyConfig(newConfig)
}

// errFrpcService marks a failure to start or stop frpc, apart from a failure to write or remove
// its files: the provisioning only warns about it, since the next run retries.
var errFrpcService = errors.New("frpc service action failed")

// applyConfig puts a server-built frpc.toml in place and frpc in the matching state; Sync and
// the provisioning (Apply) share it. The stored hash is the one of the server's text, not of the
// file written (preamble, identity paths), so it matches the server's config-hash.
func applyConfig(serverToml []byte) error {
	remoteHash := hashConfig(serverToml)

	// The server sends the common part also with no tunnel left; frpc must not run without one.
	if !hasProxies(serverToml) {
		if err := stopFrpc(); err != nil {
			return err
		}
		if err := os.WriteFile(config.FrpHashFile(), []byte(remoteHash), 0644); err != nil {
			return fmt.Errorf("write the config hash: %w", err)
		}
		logger.Infof("No tunnel for this host, frpc stopped and disabled.")
		return nil
	}

	// Write the config atomically (0600: contains the frp auth token). A plain in-place WriteFile
	// truncates first, so a crash/kill between truncate and write would leave a partial frpc.toml
	// that frpc.service crash-loops on (Restart=on-failure) until the next sync ~5 min later. Stage
	// to a temp file + rename, like enroll.stageIdentity (4.82).
	tmp := config.FrpConfigFile() + ".tmp"
	if err := os.WriteFile(tmp, append([]byte(localPreamble), rewriteIdentityPaths(serverToml)...), 0600); err != nil {
		return fmt.Errorf("frpc.toml schreiben: %w", err)
	}
	if err := os.Rename(tmp, config.FrpConfigFile()); err != nil {
		return fmt.Errorf("frpc.toml aktivieren: %w", err)
	}
	// German like before, logged before frpc starts: the desktop tunnel E2E greps the
	// provisioning output for it, and its container has no systemctl to start frpc.
	logger.Infof("frpc.toml geschrieben")

	// frpc is stopped on the first tunnel and after a former run stopped it: enable it, so it
	// also runs after a reboot. A running frpc restarts onto the new file.
	started := "restarted"
	if isActive() {
		if err := restartService(); err != nil {
			return fmt.Errorf("%w: restart frpc: %w", errFrpcService, err)
		}
	} else {
		if err := enableService(); err != nil {
			return fmt.Errorf("%w: enable and start frpc: %w", errFrpcService, err)
		}
		started = "enabled and started"
	}

	// Persist the hash only AFTER frpc started on the new file (4.11): a failed start then leaves
	// the hash mismatch standing, so the next run retries the sync instead of freezing the old
	// config on disk until the next server-side change.
	if err := os.WriteFile(config.FrpHashFile(), []byte(remoteHash), 0644); err != nil {
		return fmt.Errorf("Hash schreiben: %w", err)
	}
	logger.Infof("frpc.toml updated, frpc %s.", started)
	return nil
}

// syncWithoutFrpConfig stops frpc and removes frpc.toml and the hash, on a null hash and for a
// provisioning without an FRP bundle. Neither file left means a former run already stopped it;
// returning early keeps systemctl out of every timer run.
func syncWithoutFrpConfig() error {
	_, confErr := os.Stat(config.FrpConfigFile())
	_, hashErr := os.Stat(config.FrpHashFile())
	if os.IsNotExist(confErr) && os.IsNotExist(hashErr) {
		return nil
	}
	if err := stopFrpc(); err != nil {
		return err
	}
	if err := os.Remove(config.FrpHashFile()); err != nil && !os.IsNotExist(err) {
		return fmt.Errorf("remove the config hash: %w", err)
	}
	logger.Infof("No FRP config or tunnel for this host on the server, frpc stopped and disabled.")
	return nil
}

// stopFrpc stops and disables frpc, then removes frpc.toml: it holds the frps token. The
// order keeps the file for the retry when the stop fails.
func stopFrpc() error {
	if err := disableService(); err != nil {
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
