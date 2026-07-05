// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package frpc

import (
	"crypto/sha256"
	"encoding/json"
	"fmt"
	"os"
	"strings"
	"time"

	"adminhelper-agent/internal/config"
	"adminhelper-agent/internal/enroll"
)

// Sync checks for config changes and updates frpc (port of do_sync).
func Sync() error {
	cfg, err := config.LoadFrpcConfig()
	if err != nil {
		if os.IsNotExist(err) {
			logger.Infof("Keine Konfiguration gefunden. Ueberspringe.")
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

	// Write the config atomically (0600: contains the frp auth token). A plain in-place WriteFile
	// truncates first, so a crash/kill between truncate and write would leave a partial frpc.toml
	// that frpc.service crash-loops on (Restart=on-failure) until the next sync ~5 min later. Stage
	// to a temp file + rename, like enroll.stageIdentity (4.82).
	tmp := config.FrpConfigFile() + ".tmp"
	if err := os.WriteFile(tmp, rewriteIdentityPaths(newConfig), 0600); err != nil {
		return fmt.Errorf("frpc.toml schreiben: %w", err)
	}
	if err := os.Rename(tmp, config.FrpConfigFile()); err != nil {
		return fmt.Errorf("frpc.toml aktivieren: %w", err)
	}

	// Restart frpc
	if err := restartFrpc(); err != nil {
		return fmt.Errorf("frpc neustarten: %w", err)
	}

	// Persist the hash only AFTER a successful restart (4.11): a failed restart then leaves the
	// hash mismatch standing, so the next run retries the sync instead of freezing the old
	// config on disk until the next server-side change.
	if err := os.WriteFile(config.FrpHashFile(), []byte(remoteHash), 0644); err != nil {
		return fmt.Errorf("Hash schreiben: %w", err)
	}
	logger.Infof("frpc.toml aktualisiert und frpc neugestartet.")
	return nil
}

// parseConfigHash reads the hash value from the server response (`{"hash": "..."}`).
func parseConfigHash(body []byte) (string, error) {
	var hashResp struct {
		Hash string `json:"hash"`
	}
	if err := json.Unmarshal(body, &hashResp); err != nil {
		return "", err
	}
	return hashResp.Hash, nil
}

// hashConfig computes the hex-encoded SHA256 hash of the config bytes.
func hashConfig(data []byte) string {
	return fmt.Sprintf("%x", sha256.Sum256(data))
}

// writeConfigHash computes the SHA256 hash of the current frpc.toml.
func writeConfigHash() error {
	data, err := os.ReadFile(config.FrpConfigFile())
	if err != nil {
		return err
	}
	return os.WriteFile(config.FrpHashFile(), []byte(hashConfig(data)), 0644)
}
