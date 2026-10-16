// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package frpc

import (
	"archive/tar"
	"bytes"
	"compress/gzip"
	"encoding/base64"
	"os"
	"path/filepath"
	"reflect"
	"runtime"
	"strings"
	"testing"

	"adminhelper-agent/internal/config"
)

// makeBundle builds a base64-encoded tar.gz from the given (name -> content)
// entries, as extractPkiBundle expects it.
func makeBundle(t *testing.T, entries map[string]string) string {
	t.Helper()
	var buf bytes.Buffer
	gz := gzip.NewWriter(&buf)
	tw := tar.NewWriter(gz)
	for name, content := range entries {
		if err := tw.WriteHeader(&tar.Header{
			Name:     name,
			Typeflag: tar.TypeReg,
			Mode:     0o644,
			Size:     int64(len(content)),
		}); err != nil {
			t.Fatalf("WriteHeader: %v", err)
		}
		if _, err := tw.Write([]byte(content)); err != nil {
			t.Fatalf("Write: %v", err)
		}
	}
	if err := tw.Close(); err != nil {
		t.Fatalf("tar Close: %v", err)
	}
	if err := gz.Close(); err != nil {
		t.Fatalf("gzip Close: %v", err)
	}
	return base64.StdEncoding.EncodeToString(buf.Bytes())
}

func TestExtractPkiBundleWritesFilesWithPermissions(t *testing.T) {
	dest := t.TempDir()
	bundle := makeBundle(t, map[string]string{
		"client.key": "PRIVATE-KEY-MATERIAL",
		"client.crt": "CERT-MATERIAL",
	})

	if err := extractPkiBundle(bundle, dest); err != nil {
		t.Fatalf("extractPkiBundle: %v", err)
	}

	for name, want := range map[string]string{
		"client.key": "PRIVATE-KEY-MATERIAL",
		"client.crt": "CERT-MATERIAL",
	} {
		got, err := os.ReadFile(filepath.Join(dest, name))
		if err != nil {
			t.Fatalf("read %s: %v", name, err)
		}
		if string(got) != want {
			t.Errorf("%s content = %q, erwartet %q", name, got, want)
		}
	}

	// Permission contract: keys stay 0600, certs widen to 0644. File modes are
	// not meaningful on Windows, so only assert on POSIX.
	if runtime.GOOS != "windows" {
		keyInfo, _ := os.Stat(filepath.Join(dest, "client.key"))
		if perm := keyInfo.Mode().Perm(); perm != 0o600 {
			t.Errorf("client.key mode = %o, erwartet 600", perm)
		}
		crtInfo, _ := os.Stat(filepath.Join(dest, "client.crt"))
		if perm := crtInfo.Mode().Perm(); perm != 0o644 {
			t.Errorf("client.crt mode = %o, erwartet 644", perm)
		}
	}
}

func TestExtractPkiBundleRejectsZipSlip(t *testing.T) {
	dest := t.TempDir()
	// A path-traversal member that would escape destDir.
	bundle := makeBundle(t, map[string]string{
		"../escaped.key": "OWNED",
	})

	if err := extractPkiBundle(bundle, dest); err == nil {
		t.Fatal("extractPkiBundle akzeptierte einen ../-Member (zip slip)")
	}

	// Nothing must have been written outside destDir.
	if _, err := os.Stat(filepath.Join(filepath.Dir(dest), "escaped.key")); !os.IsNotExist(err) {
		t.Error("Datei wurde ausserhalb des Zielverzeichnisses geschrieben")
	}
}

func TestExtractPkiBundleRejectsGarbageBase64(t *testing.T) {
	if err := extractPkiBundle("not-valid-base64!!!", t.TempDir()); err == nil {
		t.Fatal("extractPkiBundle akzeptierte ungueltiges Base64")
	}
}

func TestExtractPkiBundleRejectsZipBomb(t *testing.T) {
	// A single file over the 10-MiB limit must be rejected AND removed from disk. Highly
	// compressible, so the base64 bundle stays tiny while the extracted size trips the guard (6.14).
	big := strings.Repeat("A", int(maxBundleBytes)+1)
	bundle := makeBundle(t, map[string]string{"huge.crt": big})
	dest := t.TempDir()

	if err := extractPkiBundle(bundle, dest); err == nil {
		t.Fatal("Bundle > maxBundleBytes haette abgelehnt werden muessen")
	}
	if _, err := os.Stat(filepath.Join(dest, "huge.crt")); !os.IsNotExist(err) {
		t.Error("abgelehnte Datei blieb auf der Platte liegen")
	}
}

func TestExtractPkiBundleRejectsCumulativeOverLimit(t *testing.T) {
	// Two files, each under the limit, whose sum exceeds it — exercises the cumulative totalBytes
	// check, not just the single-file guard (6.14).
	half := strings.Repeat("A", int(maxBundleBytes/2)+1)
	bundle := makeBundle(t, map[string]string{"a.crt": half, "b.crt": half})
	dest := t.TempDir()

	if err := extractPkiBundle(bundle, dest); err == nil {
		t.Fatal("kumulative Summe > maxBundleBytes haette abgelehnt werden muessen")
	}
}

// R-0398: the sync config is what every later sync runs on (URL, API key, server ID,
// trust). It carries the server API key, so it and its directory are root's alone.
func TestWriteSyncConfigStoresKeyAndPinnedCA(t *testing.T) {
	// Not created yet: WriteSyncConfig makes the directory itself.
	t.Setenv("ADMINHELPER_FRP_DIR", filepath.Join(t.TempDir(), "frp"))
	pinned := filepath.Join(t.TempDir(), "pinned.crt")
	if err := os.WriteFile(pinned, []byte("PINNED-CA"), 0o600); err != nil {
		t.Fatal(err)
	}

	if err := WriteSyncConfig(SyncConfigParams{
		AdminHelperURL: "https://srv.example/",
		ServerID:       "srv-1",
		APIKey:         "key-1",
		TLS:            config.TLSOpts{CACert: pinned},
	}); err != nil {
		t.Fatalf("WriteSyncConfig: %v", err)
	}

	kv, err := config.LoadKeyValue(config.FrpAdminHelperConf())
	if err != nil {
		t.Fatalf("sync config: %v", err)
	}
	want := map[string]string{
		"ADMINHELPER_URL": "https://srv.example",
		"API_KEY":         "key-1",
		"SERVER_ID":       "srv-1",
		"CACERT":          config.FrpCACert(),
	}
	if !reflect.DeepEqual(kv, want) {
		t.Fatalf("sync config = %v, want %v", kv, want)
	}
	if got, _ := os.ReadFile(config.FrpCACert()); string(got) != "PINNED-CA" {
		t.Fatalf("ca.crt = %q, want the pinned CA copied", got)
	}
	// Mode bits mean nothing on Windows, SecureDir sets the ACL there.
	if runtime.GOOS != "windows" {
		for path, want := range map[string]os.FileMode{config.FrpAdminHelperConf(): 0o600, config.FrpDir(): 0o700} {
			info, err := os.Stat(path)
			if err != nil {
				t.Fatal(err)
			}
			if perm := info.Mode().Perm(); perm != want {
				t.Errorf("%s mode = %o, want %o", path, perm, want)
			}
		}
	}
}

func TestWriteSyncConfigStoresInsecureWithoutCA(t *testing.T) {
	t.Setenv("ADMINHELPER_FRP_DIR", t.TempDir())

	if err := WriteSyncConfig(SyncConfigParams{
		AdminHelperURL: "https://srv.example",
		ServerID:       "srv-1",
		APIKey:         "key-1",
		TLS:            config.TLSOpts{Insecure: true},
	}); err != nil {
		t.Fatalf("WriteSyncConfig: %v", err)
	}

	kv, err := config.LoadKeyValue(config.FrpAdminHelperConf())
	if err != nil {
		t.Fatalf("sync config: %v", err)
	}
	want := map[string]string{
		"ADMINHELPER_URL": "https://srv.example",
		"API_KEY":         "key-1",
		"SERVER_ID":       "srv-1",
		"INSECURE":        "1",
	}
	if !reflect.DeepEqual(kv, want) {
		t.Fatalf("sync config = %v, want %v", kv, want)
	}
	if _, err := os.Stat(config.FrpCACert()); !os.IsNotExist(err) {
		t.Fatalf("ca.crt written without a CA to copy (%v)", err)
	}
}
