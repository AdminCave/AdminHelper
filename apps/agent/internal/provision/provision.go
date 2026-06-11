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
	"encoding/json"
	"encoding/pem"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/url"
	"os"
	"strconv"
	"strings"
	"time"

	"adminhelper-agent/internal/config"
	"adminhelper-agent/internal/enroll"
	"adminhelper-agent/internal/frpc"
	"adminhelper-agent/internal/httpclient"
	"adminhelper-agent/internal/monitor"
)

type frpBundle struct {
	Config    string `json:"config"`
	PkiBundle string `json:"pkiBundle"`
}

// enrollmentInfo is the one-time grant the server returns so the agent can fetch
// its mTLS client cert from the ca-issuer (A4). The host is not carried: the
// agent reuses the server URL it already provisioned against + this port.
type enrollmentInfo struct {
	Token      string `json:"token"`
	SubjectID  string `json:"subjectId"`
	Scope      string `json:"scope"`
	EnrollPort int    `json:"enrollPort"`
}

type activateResponse struct {
	ServerName    string          `json:"serverName"`
	APIKey        string          `json:"apiKey"`
	MonitorAPIKey *string         `json:"monitorApiKey"`
	MonitorURL    *string         `json:"monitorUrl"`
	FRP           *frpBundle      `json:"frp"`
	Enrollment    *enrollmentInfo `json:"enrollment"`
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

	// 0. mTLS enrollment: fetch the agent's client cert from the ca-issuer with
	// the one-time token. Best-effort — during the permissive rollout (A4) the
	// agent still works via API key alone, so a failed enroll must not abort
	// provisioning. The TLS trust for this bootstrap call is the same one the
	// activate call used (TOFU-pinned gateway cert); the enroll response's chain
	// is then persisted as the permanent pinned root.
	if resp.Enrollment != nil && resp.Enrollment.Token != "" {
		if err := runEnrollment(adminHelperURL, resp.Enrollment, effectiveCacert, effectiveInsecure); err != nil {
			fmt.Printf("→ Enrollment uebersprungen (%v) — Agent nutzt vorerst nur den API-Key.\n", err)
		} else {
			fmt.Println("→ mTLS-Client-Zertifikat enrollt und gepinnt.")
		}
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

// runEnrollment generates an on-device key + CSR and redeems the enrollment
// token at the gateway's enroll plane, persisting the issued identity.
func runEnrollment(adminHelperURL string, info *enrollmentInfo, cacert string, insecure bool) error {
	port := info.EnrollPort
	if port == 0 {
		port = 8444 // the gateway's default enroll plane
	}
	endpoint, err := enrollEndpoint(adminHelperURL, port)
	if err != nil {
		return fmt.Errorf("Enroll-URL bilden: %w", err)
	}
	client, err := httpclient.New(cacert, insecure, 30*time.Second)
	if err != nil {
		return fmt.Errorf("HTTP-Client: %w", err)
	}
	key, err := enroll.GenerateKey()
	if err != nil {
		return err
	}
	csr, err := enroll.BuildCSR(key, info.SubjectID)
	if err != nil {
		return err
	}
	issued, err := enroll.Submit(client, endpoint, enroll.EnrollRequest{Token: info.Token, CSR: string(csr)})
	if err != nil {
		return err
	}
	return enroll.Store(config.AgentPkiDir(), key, issued)
}

// enrollEndpoint reuses the host of the already-trusted server URL and swaps in
// the gateway's enroll port — the server cannot know its own public address.
func enrollEndpoint(adminHelperURL string, port int) (string, error) {
	u, err := url.Parse(adminHelperURL)
	if err != nil {
		return "", err
	}
	host := u.Hostname()
	if host == "" {
		return "", fmt.Errorf("kein Host in %q", adminHelperURL)
	}
	u.Host = net.JoinHostPort(host, strconv.Itoa(port))
	u.Path = "/enroll"
	u.RawQuery = ""
	return u.String(), nil
}

func callActivate(adminHelperURL, token, serverID, cacert string, insecure bool) (*activateResponse, []byte, error) {
	client, err := httpclient.New(cacert, insecure, 30*time.Second)
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
