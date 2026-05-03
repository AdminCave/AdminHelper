// Package provision implementiert den Server-zentrischen Provisioning-Flow.
//
// Ab v0.23.0 ist Provisioning nicht mehr an FRP gekoppelt. Ein einziger
// `adminhelper-agent provision`-Aufruf:
//   - loest den Provision-Token via POST /api/servers/{id}/provision/activate ein,
//   - schreibt Server-API-Key (immer),
//   - bei verfuegbarem Monitor-Service: monitor.Init mit zurueckgeliefertem Key,
//   - bei konfiguriertem FRP-Tunnel: frpc.Apply mit zurueckgeliefertem Bundle.
//
// Damit reicht ein einziger Befehl auf dem Zielserver, egal welche Komponenten
// (FRP / Monitor / nur Server-Read) konfiguriert sind.
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

// Run loest einen Provision-Token gegen den Server-Endpoint ein und
// installiert die zurueckgegebenen Bundles plattform-passend.
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

	// 1. Monitor-Init nur, wenn Service einen Key zurueckgegeben hat.
	if resp.MonitorAPIKey != nil && *resp.MonitorAPIKey != "" &&
		resp.MonitorURL != nil && *resp.MonitorURL != "" {
		fmt.Println("→ Monitor-Agent wird eingerichtet...")
		if err := monitor.Init(*resp.MonitorURL, *resp.MonitorAPIKey, serverID, "", cacert, insecure); err != nil {
			return fmt.Errorf("Monitor-Init fehlgeschlagen: %w", err)
		}
	} else {
		fmt.Println("→ Monitor-Service nicht konfiguriert oder nicht erreichbar — Monitor wird uebersprungen.")
	}

	// 2. FRP-Apply nur, wenn Server FRP-Tunnel hat.
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
