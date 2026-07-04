// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package config

import (
	"bufio"
	"fmt"
	"net/url"
	"os"
	"strings"
)

// FrpcConfig holds the configuration for the FRPC sync agent.
type FrpcConfig struct {
	AdminHelperURL string
	APIKey         string
	ServerID       string
	CurlSSL        string // Legacy field, not used directly in Go
	CACert         string
	Insecure       bool
}

// MonitorConfig holds the configuration for the monitor agent.
type MonitorConfig struct {
	MonitorURL string
	APIKey     string
	ServerID   string
	Services   []string
	CACert     string
	Insecure   bool
}

// TLSOpts bundles the CA-cert-path / insecure pair that travels together through
// every provisioning call (Apply, Init, PushReport). Grouping them keeps a new
// TLS option (e.g. a client-cert path) from having to be threaded through 4+
// same-typed positional args — and stops a swapped cacert/insecure at a call site.
type TLSOpts struct {
	CACert   string
	Insecure bool
}

// LoadKeyValue reads a Key=Value config file (compatible with the existing format).
func LoadKeyValue(path string) (map[string]string, error) {
	f, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	defer f.Close()

	kv := make(map[string]string)
	scanner := bufio.NewScanner(f)
	for scanner.Scan() {
		line := strings.TrimSpace(scanner.Text())
		if line == "" || strings.HasPrefix(line, "#") {
			continue
		}
		key, value, ok := strings.Cut(line, "=")
		if !ok {
			continue
		}
		kv[strings.TrimSpace(key)] = strings.Trim(strings.TrimSpace(value), "\"")
	}
	return kv, scanner.Err()
}

// WriteKeyValue writes a Key=Value config file. Values are server-/user-supplied,
// so reject control characters and quotes that would break out of the quoted
// value and inject another entry (e.g. a newline smuggling in INSECURE=1).
func WriteKeyValue(path string, entries []KeyValue) error {
	var b strings.Builder
	for _, e := range entries {
		if strings.ContainsAny(e.Key, "\n\r\"=") || strings.ContainsAny(e.Value, "\n\r\"") {
			return fmt.Errorf("ungueltiges Zeichen in Config-Eintrag %q", e.Key)
		}
		fmt.Fprintf(&b, "%s=\"%s\"\n", e.Key, e.Value)
	}
	return os.WriteFile(path, []byte(b.String()), 0600)
}

// KeyValue is a single config entry.
type KeyValue struct {
	Key   string
	Value string
}

// LoadFrpcConfig reads the FRPC sync configuration.
func LoadFrpcConfig() (*FrpcConfig, error) {
	kv, err := LoadKeyValue(FrpAdminHelperConf())
	if err != nil {
		return nil, err
	}
	return frpcConfigFromKV(kv), nil
}

// frpcConfigFromKV builds the FrpcConfig from the raw key-values and applies the
// CACert fallback logic.
func frpcConfigFromKV(kv map[string]string) *FrpcConfig {
	cfg := &FrpcConfig{
		AdminHelperURL: kv["ADMINHELPER_URL"],
		APIKey:         kv["API_KEY"],
		ServerID:       kv["SERVER_ID"],
		CurlSSL:        kv["CURL_SSL"],
		CACert:         kv["CACERT"],
		Insecure:       kv["INSECURE"] == "1",
	}
	// Fallback: CACert from the FRP directory
	if cfg.CACert == "" && cfg.CurlSSL != "" && strings.Contains(cfg.CurlSSL, "cacert") {
		cfg.CACert = FrpCACert()
	}
	return cfg
}

// LoadMonitorConfig reads the monitor configuration.
func LoadMonitorConfig() (*MonitorConfig, error) {
	kv, err := LoadKeyValue(MonitorConfFile())
	if err != nil {
		return nil, err
	}
	return &MonitorConfig{
		MonitorURL: kv["MONITOR_URL"],
		APIKey:     kv["API_KEY"],
		ServerID:   kv["SERVER_ID"],
		Services:   splitServices(kv["SERVICES"]),
		CACert:     kv["CACERT"],
		Insecure:   kv["INSECURE"] == "1",
	}, nil
}

// ServerBaseURL returns the base server URL (scheme://host[:port]) from
// whichever agent config carries one. Used for the cert-renewal endpoint
// (<base>/ca/renew on the gateway data plane).
func ServerBaseURL() (string, error) {
	if cfg, err := LoadFrpcConfig(); err == nil && cfg.AdminHelperURL != "" {
		return baseURL(cfg.AdminHelperURL)
	}
	if cfg, err := LoadMonitorConfig(); err == nil && cfg.MonitorURL != "" {
		return baseURL(cfg.MonitorURL)
	}
	return "", fmt.Errorf("keine Server-URL in der Agent-Konfiguration")
}

func baseURL(raw string) (string, error) {
	u, err := url.Parse(raw)
	if err != nil {
		return "", err
	}
	if u.Scheme == "" || u.Host == "" {
		return "", fmt.Errorf("ungueltige Server-URL %q", raw)
	}
	return u.Scheme + "://" + u.Host, nil
}

// splitServices splits a comma-separated SERVICES list, ignoring whitespace
// and empty entries.
func splitServices(s string) []string {
	if s == "" {
		return nil
	}
	var services []string
	for _, name := range strings.Split(s, ",") {
		if n := strings.TrimSpace(name); n != "" {
			services = append(services, n)
		}
	}
	return services
}
