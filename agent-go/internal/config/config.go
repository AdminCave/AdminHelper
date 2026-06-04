package config

import (
	"bufio"
	"fmt"
	"os"
	"strings"
)

// FrpcConfig enthaelt die Konfiguration fuer den FRPC-Sync Agent.
type FrpcConfig struct {
	AdminHelperURL string
	APIKey         string
	ServerID       string
	CurlSSL        string // Legacy-Feld, wird in Go nicht direkt genutzt
	CACert         string
	Insecure       bool
}

// MonitorConfig enthaelt die Konfiguration fuer den Monitor Agent.
type MonitorConfig struct {
	MonitorURL string
	APIKey     string
	ServerID   string
	Services   []string
	CACert     string
	Insecure   bool
}

// LoadKeyValue liest eine Key=Value Config-Datei (kompatibel mit bestehendem Format).
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

// WriteKeyValue schreibt eine Key=Value Config-Datei.
func WriteKeyValue(path string, entries []KeyValue) error {
	var b strings.Builder
	for _, e := range entries {
		fmt.Fprintf(&b, "%s=\"%s\"\n", e.Key, e.Value)
	}
	return os.WriteFile(path, []byte(b.String()), 0600)
}

// KeyValue ist ein einzelner Config-Eintrag.
type KeyValue struct {
	Key   string
	Value string
}

// LoadFrpcConfig liest die FRPC-Sync Konfiguration.
func LoadFrpcConfig() (*FrpcConfig, error) {
	kv, err := LoadKeyValue(FrpAdminHelperConf())
	if err != nil {
		return nil, err
	}
	cfg := &FrpcConfig{
		AdminHelperURL: kv["ADMINHELPER_URL"],
		APIKey:         kv["API_KEY"],
		ServerID:       kv["SERVER_ID"],
		CurlSSL:        kv["CURL_SSL"],
		CACert:         kv["CACERT"],
		Insecure:       kv["INSECURE"] == "1",
	}
	// Fallback: CACert aus FRP-Verzeichnis
	if cfg.CACert == "" && cfg.CurlSSL != "" && strings.Contains(cfg.CurlSSL, "cacert") {
		cfg.CACert = FrpCACert()
	}
	return cfg, nil
}

// LoadMonitorConfig liest die Monitor Konfiguration.
func LoadMonitorConfig() (*MonitorConfig, error) {
	kv, err := LoadKeyValue(MonitorConfFile())
	if err != nil {
		return nil, err
	}
	var services []string
	if s := kv["SERVICES"]; s != "" {
		for _, name := range strings.Split(s, ",") {
			if n := strings.TrimSpace(name); n != "" {
				services = append(services, n)
			}
		}
	}
	return &MonitorConfig{
		MonitorURL: kv["MONITOR_URL"],
		APIKey:     kv["API_KEY"],
		ServerID:   kv["SERVER_ID"],
		Services:   services,
		CACert:     kv["CACERT"],
		Insecure:   kv["INSECURE"] == "1",
	}, nil
}
