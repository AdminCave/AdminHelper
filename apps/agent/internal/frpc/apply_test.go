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
	"runtime"
	"testing"
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
