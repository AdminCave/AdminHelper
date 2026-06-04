// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package config

import (
	"os"
	"path/filepath"
	"reflect"
	"testing"
)

// writeTemp writes content to a tmp file and returns its path.
func writeTemp(t *testing.T, content string) string {
	t.Helper()
	dir := t.TempDir()
	path := filepath.Join(dir, "test.conf")
	if err := os.WriteFile(path, []byte(content), 0600); err != nil {
		t.Fatalf("tmp-Datei schreiben: %v", err)
	}
	return path
}

func TestLoadKeyValueBasic(t *testing.T) {
	content := `ADMINHELPER_URL="https://example.com"
API_KEY="secret-key"
SERVER_ID=server-42
`
	path := writeTemp(t, content)
	kv, err := LoadKeyValue(path)
	if err != nil {
		t.Fatalf("LoadKeyValue: %v", err)
	}
	want := map[string]string{
		"ADMINHELPER_URL": "https://example.com",
		"API_KEY":         "secret-key",
		"SERVER_ID":       "server-42",
	}
	if !reflect.DeepEqual(kv, want) {
		t.Errorf("LoadKeyValue = %v, erwartet %v", kv, want)
	}
}

func TestLoadKeyValueCommentsAndBlankLines(t *testing.T) {
	content := `# Dies ist ein Kommentar
ADMINHELPER_URL="https://example.com"

   # eingerueckter Kommentar
API_KEY="secret"

`
	path := writeTemp(t, content)
	kv, err := LoadKeyValue(path)
	if err != nil {
		t.Fatalf("LoadKeyValue: %v", err)
	}
	if len(kv) != 2 {
		t.Errorf("erwartete 2 Eintraege, bekam %d: %v", len(kv), kv)
	}
	if kv["ADMINHELPER_URL"] != "https://example.com" {
		t.Errorf("ADMINHELPER_URL = %q", kv["ADMINHELPER_URL"])
	}
	if kv["API_KEY"] != "secret" {
		t.Errorf("API_KEY = %q", kv["API_KEY"])
	}
	if _, ok := kv["# Dies ist ein Kommentar"]; ok {
		t.Error("Kommentarzeile wurde als Eintrag geparst")
	}
}

func TestLoadKeyValueQuotesAndWhitespace(t *testing.T) {
	content := `QUOTED="mit Quotes"
UNQUOTED=ohne Quotes
SPACED  =  getrimmt
EMPTY=""
`
	path := writeTemp(t, content)
	kv, err := LoadKeyValue(path)
	if err != nil {
		t.Fatalf("LoadKeyValue: %v", err)
	}
	checks := map[string]string{
		"QUOTED":   "mit Quotes",
		"UNQUOTED": "ohne Quotes",
		"SPACED":   "getrimmt",
		"EMPTY":    "",
	}
	for k, want := range checks {
		if got := kv[k]; got != want {
			t.Errorf("%s = %q, erwartet %q", k, got, want)
		}
	}
}

func TestLoadKeyValueLineWithoutEquals(t *testing.T) {
	content := `VALID=ok
das ist keine key-value-zeile
ANDERER=wert
`
	path := writeTemp(t, content)
	kv, err := LoadKeyValue(path)
	if err != nil {
		t.Fatalf("LoadKeyValue: %v", err)
	}
	if len(kv) != 2 {
		t.Errorf("erwartete 2 Eintraege, bekam %d: %v", len(kv), kv)
	}
}

func TestLoadKeyValueMissingKeyReturnsEmpty(t *testing.T) {
	path := writeTemp(t, "PRESENT=here\n")
	kv, err := LoadKeyValue(path)
	if err != nil {
		t.Fatalf("LoadKeyValue: %v", err)
	}
	// A missing key yields the zero value (empty string) on Go map access.
	if got := kv["NICHT_VORHANDEN"]; got != "" {
		t.Errorf("fehlender Key sollte \"\" sein, war %q", got)
	}
}

func TestLoadKeyValueFileNotFound(t *testing.T) {
	_, err := LoadKeyValue(filepath.Join(t.TempDir(), "gibtsnicht.conf"))
	if err == nil {
		t.Fatal("erwartete Fehler fuer nicht existierende Datei")
	}
	if !os.IsNotExist(err) {
		t.Errorf("erwartete os.IsNotExist, bekam %v", err)
	}
}

func TestSplitServices(t *testing.T) {
	cases := []struct {
		name  string
		input string
		want  []string
	}{
		{"leer", "", nil},
		{"einzeln", "nginx", []string{"nginx"}},
		{"mehrere", "nginx,postgres,redis", []string{"nginx", "postgres", "redis"}},
		{"mit leerraum", " nginx , postgres ,redis ", []string{"nginx", "postgres", "redis"}},
		{"leere eintraege", "nginx,,postgres,", []string{"nginx", "postgres"}},
		{"nur kommas", ",,,", nil},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			got := splitServices(tc.input)
			if !reflect.DeepEqual(got, tc.want) {
				t.Errorf("splitServices(%q) = %v, erwartet %v", tc.input, got, tc.want)
			}
		})
	}
}

func TestFrpcConfigFromKVFields(t *testing.T) {
	kv := map[string]string{
		"ADMINHELPER_URL": "https://example.com",
		"API_KEY":         "key",
		"SERVER_ID":       "srv",
		"CACERT":          "/etc/frp/ca.crt",
		"INSECURE":        "1",
	}
	cfg := frpcConfigFromKV(kv)
	if cfg.AdminHelperURL != "https://example.com" || cfg.APIKey != "key" || cfg.ServerID != "srv" {
		t.Errorf("Basisfelder falsch gemappt: %+v", cfg)
	}
	if cfg.CACert != "/etc/frp/ca.crt" {
		t.Errorf("CACert = %q", cfg.CACert)
	}
	if !cfg.Insecure {
		t.Error("INSECURE=1 sollte Insecure=true ergeben")
	}
}

func TestFrpcConfigFallbackCACert(t *testing.T) {
	// Empty CACERT + CURL_SSL containing "cacert" -> fallback to FrpCACert().
	kv := map[string]string{
		"CURL_SSL": "--cacert /etc/frp/ca.crt",
	}
	cfg := frpcConfigFromKV(kv)
	if cfg.CACert != FrpCACert() {
		t.Errorf("Fallback-CACert = %q, erwartet %q", cfg.CACert, FrpCACert())
	}
}

func TestFrpcConfigNoFallbackWhenCACertSet(t *testing.T) {
	// An explicit CACERT takes precedence; the fallback does not apply.
	kv := map[string]string{
		"CACERT":   "/custom/ca.crt",
		"CURL_SSL": "--cacert /etc/frp/ca.crt",
	}
	cfg := frpcConfigFromKV(kv)
	if cfg.CACert != "/custom/ca.crt" {
		t.Errorf("explizites CACERT sollte erhalten bleiben, war %q", cfg.CACert)
	}
}

func TestFrpcConfigNoFallbackWhenCurlSSLNoCacert(t *testing.T) {
	// CURL_SSL without the "cacert" substring -> no fallback.
	kv := map[string]string{
		"CURL_SSL": "-k",
	}
	cfg := frpcConfigFromKV(kv)
	if cfg.CACert != "" {
		t.Errorf("ohne cacert-Hinweis sollte CACert leer bleiben, war %q", cfg.CACert)
	}
}

func TestFrpcConfigNoFallbackWhenCurlSSLEmpty(t *testing.T) {
	cfg := frpcConfigFromKV(map[string]string{})
	if cfg.CACert != "" {
		t.Errorf("ohne CURL_SSL sollte CACert leer bleiben, war %q", cfg.CACert)
	}
	if cfg.Insecure {
		t.Error("ohne INSECURE sollte Insecure=false sein")
	}
}
