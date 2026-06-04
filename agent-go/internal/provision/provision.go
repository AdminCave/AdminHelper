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

	resp, err := callActivate(adminHelperURL, token, serverID, cacert, insecure)
	if err != nil {
		return err
	}
	if resp.APIKey == "" {
		return fmt.Errorf("kein API-Key in der Antwort erhalten")
	}

	fmt.Printf("Provisioning fuer Server %q gestartet.\n", resp.ServerName)

	// 1. Monitor init only if the service returned a key.
	if resp.MonitorAPIKey != nil && *resp.MonitorAPIKey != "" &&
		resp.MonitorURL != nil && *resp.MonitorURL != "" {
		fmt.Println("→ Monitor-Agent wird eingerichtet...")
		if err := monitor.Init(*resp.MonitorURL, *resp.MonitorAPIKey, serverID, "", cacert, insecure); err != nil {
			return fmt.Errorf("Monitor-Init fehlgeschlagen: %w", err)
		}
	} else {
		fmt.Println("→ Monitor-Service nicht konfiguriert oder nicht erreichbar — Monitor wird uebersprungen.")
	}

	// 2. FRP apply only if the server has an FRP tunnel.
	if resp.FRP != nil {
		fmt.Println("→ FRP-Client wird eingerichtet...")
		if err := frpc.Apply(adminHelperURL, serverID, resp.APIKey, resp.FRP.Config, resp.FRP.PkiBundle, cacert, insecure); err != nil {
			return fmt.Errorf("FRP-Apply fehlgeschlagen: %w", err)
		}
	} else {
		fmt.Println("→ Keine FRP-Tunnel fuer diesen Server konfiguriert — FRP wird uebersprungen.")
	}

	fmt.Println("OK: Provisioning abgeschlossen.")
	return nil
}

func callActivate(adminHelperURL, token, serverID, cacert string, insecure bool) (*activateResponse, error) {
	client, err := buildHTTPClient(cacert, insecure)
	if err != nil {
		return nil, fmt.Errorf("HTTP-Client: %w", err)
	}

	endpoint := fmt.Sprintf("%s/api/servers/%s/provision/activate", adminHelperURL, serverID)
	req, err := http.NewRequest("POST", endpoint, nil)
	if err != nil {
		return nil, err
	}
	req.Header.Set("X-Provision-Token", token)
	req.Header.Set("Content-Type", "application/json")

	httpResp, err := client.Do(req)
	if err != nil {
		return nil, fmt.Errorf("Activate-Aufruf fehlgeschlagen: %w", err)
	}
	defer httpResp.Body.Close()

	body, err := io.ReadAll(httpResp.Body)
	if err != nil {
		return nil, err
	}
	if httpResp.StatusCode >= 300 {
		return nil, fmt.Errorf("Activate fehlgeschlagen (HTTP %d): %s", httpResp.StatusCode, string(body))
	}

	var resp activateResponse
	if err := json.Unmarshal(body, &resp); err != nil {
		return nil, fmt.Errorf("JSON-Antwort parsen: %w", err)
	}
	return &resp, nil
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
