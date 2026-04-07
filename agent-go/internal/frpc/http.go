package frpc

import (
	"crypto/tls"
	"crypto/x509"
	"fmt"
	"io"
	"net/http"
	"os"
	"time"
)

// httpClient erstellt einen HTTP-Client mit optionalen TLS-Einstellungen.
func httpClient(cacert string, insecure bool) (*http.Client, error) {
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
		Timeout: 30 * time.Second,
		Transport: &http.Transport{
			TLSClientConfig: tlsCfg,
		},
	}, nil
}

// httpGet fuehrt einen GET-Request mit API-Key Header aus.
func httpGet(client *http.Client, url, apiKey string) ([]byte, error) {
	req, err := http.NewRequest("GET", url, nil)
	if err != nil {
		return nil, err
	}
	if apiKey != "" {
		req.Header.Set("X-API-Key", apiKey)
	}
	resp, err := client.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, err
	}
	if resp.StatusCode >= 300 {
		return nil, fmt.Errorf("HTTP %d: %s", resp.StatusCode, string(body))
	}
	return body, nil
}
