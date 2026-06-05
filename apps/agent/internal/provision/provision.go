// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Package provision implements the server-centric provisioning flow.
//
// As of v0.23.0, provisioning is no longer coupled to FRP. A single
// `adminhelper-agent provision` call:
//   - redeems the provision token via POST /api/servers/{id}/provision/activate,
//   - writes the server API key (always),
//   - with an available monitor service: monitor.Init with the returned key,
//   - with a configured FRP tunnel: frpc.Apply with the returned bundle.
//
// This way a single command on the target server suffices, regardless of which
// components (FRP / monitor / server-read only) are configured.
package provision

import (
	"crypto/tls"
	"crypto/x509"
	"encoding/json"
	"encoding/pem"
	"fmt"
	"io"
	"net/http"
	"os"
	"strings"
	"time"

	"adminhelper-agent/internal/frpc"
	"adminhelper-agent/internal/monitor"
)

type frpBundle struct {
	Config    string `json:"config"`
	PkiBundle string `json:"pkiBundle"`
}

type activateResponse struct {
	ServerName    string     `json:"serverName"`
	APIKey        string     `json:"apiKey"`
	MonitorAPIKey *string    `json:"monitorApiKey"`
	MonitorURL    *string    `json:"monitorUrl"`
	FRP           *frpBundle `json:"frp"`
}

// Run redeems a provision token against the server endpoint and
// installs the returned bundles in a platform-appropriate way.
func Run(adminHelperURL, token, serverID, cacert string, insecure bool) error {
	adminHelperURL = strings.TrimRight(adminHelperURL, "/")
	if adminHelperURL == "" || token == "" || serverID == "" {
		return fmt.Errorf("--url, --token und --server-id sind erforderlich")
	}

	resp, serverCertPEM, err := callActivate(adminHelperURL, token, serverID, cacert, insecure)
	if err != nil {
		return err
	}
	if resp.APIKey == "" {
		return fmt.Errorf("kein API-Key in der Antwort erhalten")
	}

	fmt.Printf("Provisioning fuer Server %q gestartet.\n", resp.ServerName)

	// TOFU: a blind --insecure (no --cacert) would otherwise persist INSECURE=1
	// into the recurring loop, permanently disabling TLS verification and leaking
	// the long-lived API key every cycle. Instead, pin the certificate the server
	// actually presented during this activate call; the loop verifies against it.
	// --insecure thus applies only to this one-off provisioning call.
	effectiveCacert := cacert
	effectiveInsecure := insecure
	if insecure && cacert == "" && len(serverCertPEM) > 0 {
		pinnedPath, err := writePinnedCert(serverCertPEM)
		if err != nil {
			return fmt.Errorf("Server-Zertifikat pinnen: %w", err)
		}
		defer os.Remove(pinnedPath)
		effectiveCacert = pinnedPath
		effectiveInsecure = false
		fmt.Println("→ Server-Zertifikat gepinnt (TOFU) — --insecure gilt nur fuer diesen Aufruf.")
	}

	// 1. Monitor init only if the service returned a key. The agent owns the
	// host: it builds the monitoring base from the SAME server URL it just
	// provisioned against (already TLS-trusted) plus the server-declared path,
	// so the metrics push always hits the same host/cert — no reliance on the
	// server knowing its own public address. MonitorURL carries the relative
	// path (e.g. "/api/monitoring"); older/absolute values fall back to the
	// well-known path.
	if resp.MonitorAPIKey != nil && *resp.MonitorAPIKey != "" {
		monitorPath := "/api/monitoring"
		if resp.MonitorURL != nil && strings.HasPrefix(*resp.MonitorURL, "/") {
			monitorPath = *resp.MonitorURL
		}
		monitorURL := adminHelperURL + monitorPath
		fmt.Println("→ Monitor-Agent wird eingerichtet...")
		if err := monitor.Init(monitorURL, *resp.MonitorAPIKey, serverID, "", effectiveCacert, effectiveInsecure); err != nil {
			return fmt.Errorf("Monitor-Init fehlgeschlagen: %w", err)
		}
	} else {
		fmt.Println("→ Monitor-Service nicht konfiguriert oder nicht erreichbar — Monitor wird uebersprungen.")
	}

	// 2. FRP apply only if the server has an FRP tunnel.
	if resp.FRP != nil {
		fmt.Println("→ FRP-Client wird eingerichtet...")
		if err := frpc.Apply(adminHelperURL, serverID, resp.APIKey, resp.FRP.Config, resp.FRP.PkiBundle, effectiveCacert, effectiveInsecure); err != nil {
			return fmt.Errorf("FRP-Apply fehlgeschlagen: %w", err)
		}
	} else {
		fmt.Println("→ Keine FRP-Tunnel fuer diesen Server konfiguriert — FRP wird uebersprungen.")
	}

	fmt.Println("OK: Provisioning abgeschlossen.")
	return nil
}

func callActivate(adminHelperURL, token, serverID, cacert string, insecure bool) (*activateResponse, []byte, error) {
	client, err := buildHTTPClient(cacert, insecure)
	if err != nil {
		return nil, nil, fmt.Errorf("HTTP-Client: %w", err)
	}

	endpoint := fmt.Sprintf("%s/api/servers/%s/provision/activate", adminHelperURL, serverID)
	req, err := http.NewRequest("POST", endpoint, nil)
	if err != nil {
		return nil, nil, err
	}
	req.Header.Set("X-Provision-Token", token)
	req.Header.Set("Content-Type", "application/json")

	httpResp, err := client.Do(req)
	if err != nil {
		return nil, nil, fmt.Errorf("Activate-Aufruf fehlgeschlagen: %w", err)
	}
	defer httpResp.Body.Close()

	body, err := io.ReadAll(httpResp.Body)
	if err != nil {
		return nil, nil, err
	}
	if httpResp.StatusCode >= 300 {
		return nil, nil, fmt.Errorf("Activate fehlgeschlagen (HTTP %d): %s", httpResp.StatusCode, string(body))
	}

	var resp activateResponse
	if err := json.Unmarshal(body, &resp); err != nil {
		return nil, nil, fmt.Errorf("JSON-Antwort parsen: %w", err)
	}

	// Capture the certificate chain the server presented, so a blind --insecure
	// provisioning can pin it (TOFU) for the recurring loop instead of disabling
	// verification forever.
	var serverCertPEM []byte
	if httpResp.TLS != nil {
		for _, c := range httpResp.TLS.PeerCertificates {
			serverCertPEM = append(serverCertPEM, pem.EncodeToMemory(
				&pem.Block{Type: "CERTIFICATE", Bytes: c.Raw})...)
		}
	}
	return &resp, serverCertPEM, nil
}

// writePinnedCert stores the captured server certificate chain in a temp file so
// monitor.Init / frpc.Apply can copy it into the agent config as the pinned CA.
func writePinnedCert(pemBytes []byte) (string, error) {
	f, err := os.CreateTemp("", "adminhelper-server-ca-*.crt")
	if err != nil {
		return "", err
	}
	defer f.Close()
	if _, err := f.Write(pemBytes); err != nil {
		os.Remove(f.Name())
		return "", err
	}
	return f.Name(), nil
}

func buildHTTPClient(cacert string, insecure bool) (*http.Client, error) {
	tlsCfg := &tls.Config{}
	if insecure {
		tlsCfg.InsecureSkipVerify = true
	} else if cacert != "" {
		pem, err := os.ReadFile(cacert)
		if err != nil {
			return nil, fmt.Errorf("CA-Zertifikat lesen: %w", err)
		}
		pool := x509.NewCertPool()
		if !pool.AppendCertsFromPEM(pem) {
			return nil, fmt.Errorf("CA-Zertifikat ungueltig")
		}
		tlsCfg.RootCAs = pool
	}
	return &http.Client{
		Timeout:   30 * time.Second,
		Transport: &http.Transport{TLSClientConfig: tlsCfg},
	}, nil
}
