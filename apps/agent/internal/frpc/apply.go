// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package frpc

import (
	"archive/tar"
	"bytes"
	"compress/gzip"
	"encoding/base64"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"

	"adminhelper-agent/internal/config"
)

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

// Apply writes the FRP config + PKI bundle from a provisioning response
// to disk and activates the service. NO HTTP call happens here anymore —
// the token-activate call has been centralized since v0.23.0 in the
// `provision` subcommand, which invokes `Apply` with the already-decoded
// values.
func Apply(p ApplyParams) error {
	adminHelperURL := p.AdminHelperURL
	serverID := p.ServerID
	apiKey := p.APIKey
	frpConfigB64 := p.FrpConfigB64
	pkiBundleB64 := p.PkiBundleB64
	cacert := p.TLS.CACert
	insecure := p.TLS.Insecure

	adminHelperURL = strings.TrimRight(adminHelperURL, "/")

	frpDir := config.FrpDir()
	pkiDir := config.FrpPkiDir()
	// Secret-bearing dirs (CA cert, client keys, the auth token in the conf) ->
	// 0700, also for raw-binary provisioning where no postinst tightens them.
	if err := os.MkdirAll(pkiDir, 0700); err != nil {
		return fmt.Errorf("Verzeichnis anlegen: %w", err)
	}
	// Harden the ACL on Windows (mode bits are ignored there) / chmod 0700 on Linux.
	_ = config.SecureDir(frpDir)
	_ = config.SecureDir(pkiDir)

	// Copy the CA cert if provided
	if cacert != "" {
		data, err := os.ReadFile(cacert)
		if err != nil {
			return fmt.Errorf("CA-Zertifikat lesen: %w", err)
		}
		if err := os.WriteFile(config.FrpCACert(), data, 0644); err != nil {
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

	// Write frpc.toml (base64-decoded)
	if frpConfigB64 != "" {
		decoded, err := base64.StdEncoding.DecodeString(frpConfigB64)
		if err != nil {
			return fmt.Errorf("Config base64 decodieren: %w", err)
		}
		if err := os.WriteFile(config.FrpConfigFile(), rewriteIdentityPaths(decoded), 0600); err != nil {
			return fmt.Errorf("frpc.toml schreiben: %w", err)
		}
		logger.Infof("frpc.toml geschrieben")
	}

	// Extract the PKI bundle (base64-encoded tar.gz)
	if pkiBundleB64 != "" {
		if err := extractPkiBundle(pkiBundleB64, frpDir); err != nil {
			logger.Warnf("PKI-Bundle konnte nicht entpackt werden: %v", err)
		} else {
			logger.Infof("PKI-Zertifikate installiert")
		}
	}

	// Compute the initial hash
	if err := writeConfigHash(); err != nil {
		logger.Warnf("Hash konnte nicht geschrieben werden: %v", err)
	}

	// Activate the service (platform-specific)
	if err := enableFrpcService(); err != nil {
		logger.Warnf("Service konnte nicht aktiviert werden: %v", err)
		logger.Warnf("Bitte manuell aktivieren")
	} else {
		logger.Infof("FRP-Setup abgeschlossen. frpc und sync sind aktiv.")
	}

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
			if strings.HasSuffix(hdr.Name, ".crt") {
				if err := os.Chmod(target, 0644); err != nil {
					return err
				}
			}
		}
	}
	return nil
}
