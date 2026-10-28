// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package frpc

import (
	"context"
	"encoding/base64"
	"errors"
	"fmt"
	"os"
	"strings"

	"adminhelper-agent/internal/config"
)

// SyncConfigParams is what every later Sync needs to reach the server: its URL, this
// host's server ID, the server API key and the trust for the connection.
type SyncConfigParams struct {
	AdminHelperURL string
	ServerID       string
	APIKey         string
	TLS            config.TLSOpts
}

// ApplyParams groups frpc.Apply's arguments — 7 same-typed positionals before,
// where a swapped serverID/apiKey only surfaced at runtime as an HTTP 401.
type ApplyParams struct {
	AdminHelperURL string
	ServerID       string
	APIKey         string
	FrpConfigB64   string
	TLS            config.TLSOpts
}

// WriteSyncConfig writes adminhelper.conf, the config every later Sync runs on, and the
// CA copy it names, under the frpc lock. Provisioning writes it with and without an FRP
// bundle: a host without it never gets a tunnel created after its provisioning (R-0398).
func WriteSyncConfig(p SyncConfigParams) error {
	unlock, err := lockSyncConfigDir()
	if err != nil {
		return err
	}
	defer unlock()
	return writeSyncConfig(p)
}

// lockSyncConfigDir secures the FRP directory, then takes the frpc lock in it, for a
// provisioning: interactive, so it waits without a ctx, frpcLockWait at most.
func lockSyncConfigDir() (unlock func(), err error) {
	// Secret-bearing dir (CA cert, the auth token in the conf) -> 0700, also for
	// raw-binary provisioning where no postinst tightens it; a protected ACL on
	// Windows, after the data root above it.
	if err := config.EnsureDataDir(config.FrpDir()); err != nil {
		return nil, fmt.Errorf("Verzeichnis anlegen: %w", err)
	}
	return lockFrpc(context.Background())
}

// writeSyncConfig is WriteSyncConfig in a secured FRP directory, under the frpc lock.
func writeSyncConfig(p SyncConfigParams) error {
	adminHelperURL := strings.TrimRight(p.AdminHelperURL, "/")
	serverID := p.ServerID
	apiKey := p.APIKey
	cacert := p.TLS.CACert

	// Copy the CA cert if provided
	if cacert != "" {
		data, err := os.ReadFile(cacert)
		if err != nil {
			return fmt.Errorf("CA-Zertifikat lesen: %w", err)
		}
		if err := config.WriteFile(config.FrpCACert(), data, 0644); err != nil {
			return fmt.Errorf("CA-Zertifikat schreiben: %w", err)
		}
	}

	// The sync config names a CA or no trust at all, never INSECURE: --insecure holds for
	// the provisioning call only, and without a CA the later sync verifies the server
	// against the system CAs.
	confCACert := ""
	if cacert != "" {
		confCACert = config.FrpCACert()
	}

	// Write the AdminHelper config
	entries := []config.KeyValue{
		{Key: "ADMINHELPER_URL", Value: adminHelperURL},
		{Key: "API_KEY", Value: apiKey},
		{Key: "SERVER_ID", Value: serverID},
	}
	if confCACert != "" {
		entries = append(entries, config.KeyValue{Key: "CACERT", Value: confCACert})
	}
	if err := config.WriteKeyValue(config.FrpAdminHelperConf(), entries); err != nil {
		return fmt.Errorf("Config schreiben: %w", err)
	}
	logger.Infof("Config geschrieben: %s", config.FrpAdminHelperConf())
	return nil
}

// Apply writes the sync config (WriteSyncConfig), then applies the frpc.toml of a provisioning
// response the way Sync does (applyConfig): a running frpc restarts onto it (never a reload, see
// startFrpc), a stopped one is enabled, and a text without proxies (no active tunnel for the
// host) stops and disables it. It holds the frpc lock from securing the FRP directory to the
// end. NO HTTP call happens here anymore — the token-activate call has been centralized since
// v0.23.0 in the `provision` subcommand, which invokes `Apply` with the already-decoded values.
func Apply(p ApplyParams) error {
	unlock, err := lockSyncConfigDir()
	if err != nil {
		return err
	}
	defer unlock()
	if err := writeSyncConfig(SyncConfigParams{
		AdminHelperURL: p.AdminHelperURL,
		ServerID:       p.ServerID,
		APIKey:         p.APIKey,
		TLS:            p.TLS,
	}); err != nil {
		return err
	}

	serverToml, err := base64.StdEncoding.DecodeString(p.FrpConfigB64)
	if err != nil {
		return fmt.Errorf("Config base64 decodieren: %w", err)
	}

	return warnOnServiceFailure(applyConfig(context.Background(), serverToml, false))
}

// ApplyWithoutBundle is Apply for a provisioning without an FRP bundle: the server has no FRP
// config (an older server sends none also for a host without a tunnel; a current one sends a
// text without proxies, on which Apply stops frpc). A frpc of an earlier provisioning stops,
// like on a null hash in Sync, and the next sync sets up a tunnel created later (R-0398). It
// secures the FRP directory and holds the frpc lock like Sync on a null hash.
func ApplyWithoutBundle() error {
	if err := secureFrpDir(); err != nil {
		return err
	}
	unlock, err := lockFrpc(context.Background())
	if err != nil {
		return err
	}
	defer unlock()
	return warnOnServiceFailure(syncWithoutFrpConfig(context.Background()))
}

// warnOnServiceFailure turns a failed start or stop of frpc at provisioning into a warning, as
// before for the start: the provision token is spent by now. Removing the hash makes the next
// agent run apply the config again, also when the stored hash already matched the bundle's
// (provisioned again with unchanged tunnels). A failed write stays an error.
func warnOnServiceFailure(err error) error {
	if !errors.Is(err, errFrpcService) {
		return err
	}
	if rmErr := os.Remove(config.FrpHashFile()); rmErr != nil && !os.IsNotExist(rmErr) {
		return fmt.Errorf("remove the config hash: %w", rmErr)
	}
	logger.Warnf("%v. The next agent run tries again; if it keeps failing, see systemctl status frpc.", err)
	return nil
}
