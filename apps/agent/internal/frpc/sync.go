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

	// Write the config (0600: contains the frp auth token).
	if err := os.WriteFile(config.FrpConfigFile(), rewriteIdentityPaths(newConfig), 0600); err != nil {
		return fmt.Errorf("frpc.toml schreiben: %w", err)
	}
	if err := os.WriteFile(config.FrpHashFile(), []byte(remoteHash), 0644); err != nil {
		return fmt.Errorf("Hash schreiben: %w", err)
	}

	// Restart frpc
	if err := restartFrpc(); err != nil {
		return fmt.Errorf("frpc neustarten: %w", err)
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
