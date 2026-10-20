// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package frpc

import (
	"archive/tar"
	"bytes"
	"compress/gzip"
	"encoding/base64"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
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
	PkiBundleB64   string
	TLS            config.TLSOpts
}

// WriteSyncConfig writes adminhelper.conf, the config every later Sync runs on, and the
// CA copy it names. Provisioning writes it with and without an FRP bundle: a host
// without it never gets a tunnel created after its provisioning (R-0398).
func WriteSyncConfig(p SyncConfigParams) error {
	adminHelperURL := strings.TrimRight(p.AdminHelperURL, "/")
	serverID := p.ServerID
	apiKey := p.APIKey
	cacert := p.TLS.CACert
	insecure := p.TLS.Insecure

	frpDir := config.FrpDir()
	pkiDir := config.FrpPkiDir()
	// Secret-bearing dirs (CA cert, client keys, the auth token in the conf) ->
	// 0700, also for raw-binary provisioning where no postinst tightens them; a
	// protected ACL on Windows, after the data root above them.
	for _, dir := range []string{frpDir, pkiDir} {
		if err := config.EnsureDataDir(dir); err != nil {
			return fmt.Errorf("Verzeichnis anlegen: %w", err)
		}
	}

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

	// Determine the SSL config for sync mode
	confCACert := ""
	confInsecure := false
	if cacert != "" {
		confCACert = config.FrpCACert()
	} else if insecure {
		confInsecure = true
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
	if confInsecure {
		entries = append(entries, config.KeyValue{Key: "INSECURE", Value: "1"})
	}
	if err := config.WriteKeyValue(config.FrpAdminHelperConf(), entries); err != nil {
		return fmt.Errorf("Config schreiben: %w", err)
	}
	logger.Infof("Config geschrieben: %s", config.FrpAdminHelperConf())
	return nil
}

// Apply writes the sync config (WriteSyncConfig) and the PKI bundle from a provisioning
// response, then applies the bundle's frpc.toml the way Sync does (applyConfig): a running frpc
// restarts onto it (never a reload, see startFrpc), a stopped one is enabled, and a text without
// proxies (no active tunnel for the host) stops and disables it. NO HTTP call happens here
// anymore — the token-activate call has been centralized since v0.23.0 in the `provision`
// subcommand, which invokes `Apply` with the already-decoded values.
func Apply(p ApplyParams) error {
	if err := WriteSyncConfig(SyncConfigParams{
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

	// Extract the PKI bundle (base64-encoded tar.gz) before frpc starts on the new config. The PKI
	// is essential for the FRP mTLS handshake — fail hard instead of warning (4.9): otherwise
	// provisioning reports "OK" while the STCP tunnel silently never establishes (cryptic TLS
	// errors in the frpc log), and since the provision token is one-time it takes manual
	// diagnosis to recover.
	if p.PkiBundleB64 != "" {
		if err := extractPkiBundle(p.PkiBundleB64, config.FrpDir()); err != nil {
			return fmt.Errorf("PKI-Bundle entpacken: %w", err)
		}
		logger.Infof("PKI-Zertifikate installiert")
	}

	return warnOnServiceFailure(applyConfig(serverToml, false))
}

// ApplyWithoutBundle is Apply for a provisioning without an FRP bundle: the server has no FRP
// config (an older server sends none also for a host without a tunnel; a current one sends a
// text without proxies, on which Apply stops frpc). A frpc of an earlier provisioning stops,
// like on a null hash in Sync, and the next sync sets up a tunnel created later (R-0398).
func ApplyWithoutBundle() error {
	return warnOnServiceFailure(syncWithoutFrpConfig())
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

// maxBundleBytes limits the total extracted size of the PKI bundle (zip-bomb protection).
const maxBundleBytes int64 = 10 * 1024 * 1024 // 10 MiB

// extractPkiBundle unpacks a base64-encoded tar.gz archive.
func extractPkiBundle(b64 string, destDir string) error {
	data, err := base64.StdEncoding.DecodeString(b64)
	if err != nil {
		return err
	}
	gz, err := gzip.NewReader(bytes.NewReader(data))
	if err != nil {
		return err
	}
	defer gz.Close()

	cleanDest, err := filepath.Abs(filepath.Clean(destDir))
	if err != nil {
		return fmt.Errorf("Zielverzeichnis aufloesen: %w", err)
	}

	var totalBytes int64
	tr := tar.NewReader(gz)
	for {
		hdr, err := tr.Next()
		if err == io.EOF {
			break
		}
		if err != nil {
			return err
		}

		target, err := filepath.Abs(filepath.Join(cleanDest, hdr.Name))
		if err != nil {
			return fmt.Errorf("Pfad aufloesen: %w", err)
		}
		rel, err := filepath.Rel(cleanDest, target)
		if err != nil || rel == ".." || strings.HasPrefix(rel, ".."+string(filepath.Separator)) {
			return fmt.Errorf("zip slip erkannt: %s", hdr.Name)
		}

		switch hdr.Typeflag {
		case tar.TypeDir:
			if err := os.MkdirAll(target, 0755); err != nil {
				return err
			}
		case tar.TypeReg:
			if err := os.MkdirAll(filepath.Dir(target), 0755); err != nil {
				return err
			}
			// Safe default permission; .key additionally gets 0600.
			// Default 0600 (covers the private keys); only public certs widen to 0644.
			f, err := os.OpenFile(target, os.O_CREATE|os.O_WRONLY|os.O_TRUNC, 0600)
			if err != nil {
				return err
			}

			remaining := maxBundleBytes - totalBytes
			written, err := io.CopyN(f, tr, remaining+1)
			if err != nil && err != io.EOF {
				f.Close()
				os.Remove(target)
				return err
			}
			if written > remaining {
				f.Close()
				os.Remove(target)
				return fmt.Errorf("zip bomb erkannt: PKI-Bundle ueberschreitet %d Bytes", maxBundleBytes)
			}
			totalBytes += written
			// Sync + checked Close: with a write-back cache the real write
			// error surfaces only at flush. A truncated .key/.crt written
			// silently would later fail the mTLS handshake cryptically.
			if err := f.Sync(); err != nil {
				f.Close()
				os.Remove(target)
				return err
			}
			if err := f.Close(); err != nil {
				os.Remove(target)
				return err
			}
			if err := config.OwnByAdministrators(target); err != nil {
				return err
			}
			if strings.HasSuffix(hdr.Name, ".crt") {
				if err := os.Chmod(target, 0644); err != nil {
					return err
				}
			}
		}
	}
	return nil
}
