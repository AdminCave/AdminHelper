// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package config

import (
	"bufio"
	"fmt"
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

// WriteKeyValue writes a Key=Value config file.
func WriteKeyValue(path string, entries []KeyValue) error {
	var b strings.Builder
	for _, e := range entries {
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
