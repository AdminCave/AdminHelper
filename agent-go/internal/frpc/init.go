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

// Apply writes the FRP config + PKI bundle from a provisioning response
// to disk and activates the service. NO HTTP call happens here anymore —
// the token-activate call has been centralized since v0.23.0 in the
// `provision` subcommand, which invokes `Apply` with the already-decoded
// values.
func Apply(adminHelperURL, serverID, apiKey, frpConfigB64, pkiBundleB64, cacert string, insecure bool) error {
	adminHelperURL = strings.TrimRight(adminHelperURL, "/")

	frpDir := config.FrpDir()
	pkiDir := config.FrpPkiDir()
	if err := os.MkdirAll(pkiDir, 0755); err != nil {
		return fmt.Errorf("Verzeichnis anlegen: %w", err)
	}

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
	logMsg("Config geschrieben: %s", config.FrpAdminHelperConf())

	// Write frpc.toml (base64-decoded)
	if frpConfigB64 != "" {
		decoded, err := base64.StdEncoding.DecodeString(frpConfigB64)
		if err != nil {
			return fmt.Errorf("Config base64 decodieren: %w", err)
		}
		if err := os.WriteFile(config.FrpConfigFile(), decoded, 0600); err != nil {
			return fmt.Errorf("frpc.toml schreiben: %w", err)
		}
		logMsg("frpc.toml geschrieben")
	}

	// Extract the PKI bundle (base64-encoded tar.gz)
	if pkiBundleB64 != "" {
		if err := extractPkiBundle(pkiBundleB64, frpDir); err != nil {
			logMsg("WARNUNG: PKI-Bundle konnte nicht entpackt werden: %v", err)
		} else {
			logMsg("PKI-Zertifikate installiert")
		}
	}

	// Compute the initial hash
	if err := writeConfigHash(); err != nil {
		logMsg("WARNUNG: Hash konnte nicht geschrieben werden: %v", err)
	}

	// Activate the service (platform-specific)
	if err := enableFrpcService(); err != nil {
		logMsg("WARNUNG: Service konnte nicht aktiviert werden: %v", err)
		logMsg("Bitte manuell aktivieren")
	} else {
		logMsg("FRP-Setup abgeschlossen. frpc und sync sind aktiv.")
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
			mode := os.FileMode(hdr.Mode) & 0644
			f, err := os.OpenFile(target, os.O_CREATE|os.O_WRONLY|os.O_TRUNC, mode)
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
			f.Close()
			if strings.HasSuffix(hdr.Name, ".key") {
				if err := os.Chmod(target, 0600); err != nil {
					return err
				}
			}
		}
	}
	return nil
}
