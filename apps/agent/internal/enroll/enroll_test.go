// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package enroll

import (
	"bytes"
	"context"
	"crypto/elliptic"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
	"time"

	"crypto/x509"
	"encoding/pem"
)

func TestGenerateKeyIsP256(t *testing.T) {
	key, err := GenerateKey()
	if err != nil {
		t.Fatalf("GenerateKey: %v", err)
	}
	if key.Curve != elliptic.P256() {
		t.Fatalf("erwartet P-256, bekam %v", key.Curve.Params().Name)
	}
}

func TestBuildCSRRoundtrips(t *testing.T) {
	key, _ := GenerateKey()
	csrPEM, err := BuildCSR(key, "srv-123")
	if err != nil {
		t.Fatalf("BuildCSR: %v", err)
	}
	block, _ := pem.Decode(csrPEM)
	if block == nil || block.Type != "CERTIFICATE REQUEST" {
		t.Fatalf("kein CSR-PEM: %q", string(csrPEM))
	}
	csr, err := x509.ParseCertificateRequest(block.Bytes)
	if err != nil {
		t.Fatalf("CSR parsen: %v", err)
	}
	if csr.Subject.CommonName != "srv-123" {
		t.Fatalf("CN = %q, erwartet srv-123", csr.Subject.CommonName)
	}
	if err := csr.CheckSignature(); err != nil {
		t.Fatalf("CSR-Signatur ungueltig: %v", err)
	}
}

func TestSubmitParsesIssueResponse(t *testing.T) {
	want := IssueResponse{Cert: "C", Fullchain: "leaf+int", Chain: "int+root"}
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("Content-Type") != "application/json" {
			t.Errorf("Content-Type fehlt: %q", r.Header.Get("Content-Type"))
		}
		var got Request
		_ = json.NewDecoder(r.Body).Decode(&got)
		if got.Token != "tok" || got.CSR != "csr-pem" {
			t.Errorf("Body falsch: %+v", got)
		}
		_ = json.NewEncoder(w).Encode(want)
	}))
	defer srv.Close()

	got, err := Submit(context.Background(), srv.Client(), srv.URL, Request{Token: "tok", CSR: "csr-pem"})
	if err != nil {
		t.Fatalf("Submit: %v", err)
	}
	if got.Fullchain != want.Fullchain || got.Chain != want.Chain {
		t.Fatalf("Antwort falsch: %+v", got)
	}
}

func TestSubmitRejectsHTTPError(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		http.Error(w, "bad token", http.StatusForbidden)
	}))
	defer srv.Close()
	if _, err := Submit(context.Background(), srv.Client(), srv.URL, Request{}); err == nil {
		t.Fatal("erwartet Fehler bei HTTP 403")
	}
}

func TestSubmitRejectsIncompleteResponse(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		// leaf only, no fullchain/chain -> unusable
		_ = json.NewEncoder(w).Encode(IssueResponse{Cert: "leaf"})
	}))
	defer srv.Close()
	if _, err := Submit(context.Background(), srv.Client(), srv.URL, Request{}); err == nil {
		t.Fatal("erwartet Fehler bei unvollstaendiger Antwort")
	}
}

func TestStoreAndProvisioned(t *testing.T) {
	dir := filepath.Join(t.TempDir(), "identity") // not pre-created -> Store must mkdir
	if Provisioned(dir) {
		t.Fatal("frisches Verzeichnis darf nicht provisioned sein")
	}

	key, _ := GenerateKey()
	resp := &IssueResponse{Cert: "leaf", Fullchain: "leaf+int", Chain: "int+root"}
	if err := Store(dir, key, resp); err != nil {
		t.Fatalf("Store: %v", err)
	}
	if !Provisioned(dir) {
		t.Fatal("nach Store muss provisioned sein")
	}

	if b, _ := os.ReadFile(CertPath(dir)); string(b) != "leaf+int" {
		t.Fatalf("agent.crt = %q, erwartet fullchain", string(b))
	}
	if b, _ := os.ReadFile(CAPath(dir)); string(b) != "int+root" {
		t.Fatalf("ca.crt = %q, erwartet chain", string(b))
	}
	// The key must be a parseable EC PKCS#8 PEM.
	keyBytes, _ := os.ReadFile(KeyPath(dir))
	block, _ := pem.Decode(keyBytes)
	if block == nil {
		t.Fatal("agent.key ist kein PEM")
	}
	if _, err := x509.ParsePKCS8PrivateKey(block.Bytes); err != nil {
		t.Fatalf("agent.key nicht parsebar: %v", err)
	}

	// The private key must not be world-readable (POSIX only).
	if runtime.GOOS != "windows" {
		info, _ := os.Stat(KeyPath(dir))
		if perm := info.Mode().Perm(); perm != 0600 {
			t.Fatalf("agent.key Perm = %o, erwartet 600", perm)
		}
	}
}

// TestStoreStagesBeforeCommit reproduces the F5 lockout window: a renewal mints a
// NEW key, so a crash between writing the key and the cert must NOT leave a new
// key paired with the old cert (the mismatch breaks mTLS → silent lockout, ADR
// 0001 §3.3). The staged write keeps the live identity untouched until the
// atomic commit, so an interrupted renew leaves the consistent old pair.
func TestStoreStagesBeforeCommit(t *testing.T) {
	dir := filepath.Join(t.TempDir(), "identity")

	keyA, _ := GenerateKey()
	respA := &IssueResponse{Cert: "leafA", Fullchain: "fullA", Chain: "chainA"}
	if err := Store(dir, keyA, respA); err != nil {
		t.Fatalf("Store A: %v", err)
	}
	keyABytes, _ := os.ReadFile(KeyPath(dir))

	// Stage a renewal (new key + new cert) but do NOT commit — this is the
	// power-loss-before-rename window.
	keyB, _ := GenerateKey()
	respB := &IssueResponse{Cert: "leafB", Fullchain: "fullB", Chain: "chainB"}
	commit, err := stageIdentity(dir, keyB, respB)
	if err != nil {
		t.Fatalf("stageIdentity B: %v", err)
	}

	// Before the commit the live identity must still be the consistent A pair.
	if b, _ := os.ReadFile(CertPath(dir)); string(b) != "fullA" {
		t.Fatalf("vor commit: agent.crt = %q, erwartet fullA", string(b))
	}
	if b, _ := os.ReadFile(KeyPath(dir)); string(b) != string(keyABytes) {
		t.Fatal("vor commit: agent.key wurde bereits veraendert (Mismatch-Fenster!)")
	}

	// The commit swaps atomically to B.
	if err := commit(); err != nil {
		t.Fatalf("commit B: %v", err)
	}
	if b, _ := os.ReadFile(CertPath(dir)); string(b) != "fullB" {
		t.Fatalf("nach commit: agent.crt = %q, erwartet fullB", string(b))
	}
	if b, _ := os.ReadFile(CAPath(dir)); string(b) != "chainB" {
		t.Fatalf("nach commit: ca.crt = %q, erwartet chainB", string(b))
	}

	// No staging leftovers in the identity dir.
	entries, _ := os.ReadDir(dir)
	for _, e := range entries {
		if strings.HasSuffix(e.Name(), tmpSuffix) {
			t.Fatalf("Staging-Datei nicht aufgeraeumt: %s", e.Name())
		}
	}
}

// failWriteOf makes the staged write of the identity file name fail after its temp file
// was created: createTemp hands that file out opened read-only. It returns the paths of
// all temp files created meanwhile.
func failWriteOf(t *testing.T, name string) *[]string {
	t.Helper()
	orig := createTemp
	var created []string
	createTemp = func(dir, pattern string) (*os.File, error) {
		f, err := orig(dir, pattern)
		if err != nil {
			return nil, err
		}
		created = append(created, f.Name())
		if !strings.HasPrefix(pattern, name+".") {
			return f, nil
		}
		if err := f.Close(); err != nil {
			return nil, err
		}
		return os.Open(f.Name())
	}
	t.Cleanup(func() { createTemp = orig })
	return &created
}

// TestStageIdentityCleansUpStagedTempsOnWriteError pins the best-effort cleanup in stageIdentity:
// if a later staging write fails, the temps already written must be removed so no .tmp corpses linger
// to confuse the next renewal (6.98).
func TestStageIdentityCleansUpStagedTempsOnWriteError(t *testing.T) {
	dir := filepath.Join(t.TempDir(), "identity")
	if err := os.MkdirAll(dir, 0o755); err != nil {
		t.Fatal(err)
	}

	key, _ := GenerateKey()
	resp := &IssueResponse{Cert: "leaf", Fullchain: "full", Chain: "chain"}

	// Fail the SECOND staging write (agent.crt). The first write (agent.key) succeeds and must then
	// be cleaned up.
	created := failWriteOf(t, CertFileName)

	if _, err := stageIdentity(dir, key, resp); err == nil {
		t.Fatal("erwartet Schreibfehler, wenn agent.crt nicht geschrieben werden kann")
	}

	// The already-written key temp must be gone — no .tmp leftovers after the aborted staging,
	// and neither the cert temp whose write failed.
	if len(*created) != 2 {
		t.Fatalf("erwartet die Temp-Dateien für agent.key und agent.crt, angelegt: %v", *created)
	}
	for _, p := range *created {
		if _, statErr := os.Stat(p); !os.IsNotExist(statErr) {
			t.Errorf("%s muss nach dem Schreibfehler aufgeraeumt sein, stat err = %v", filepath.Base(p), statErr)
		}
	}
}

// R-0224: re-provisioning names the leaf it replaces, so the issuer revokes its line.

func TestLeafFingerprintIsTheSHA256OfTheStoredLeaf(t *testing.T) {
	dir := t.TempDir()
	if got := LeafFingerprint(dir); got != "" {
		t.Fatalf("ohne Identität erwartet leer, bekam %q", got)
	}
	now := time.Now()
	leaf, key := selfSigned(t, "srv-1", now.Add(-time.Hour), now.Add(time.Hour))
	other, _ := selfSigned(t, "intermediate", now.Add(-time.Hour), now.Add(time.Hour))
	mustWrite(t, CertPath(dir), append(append([]byte{}, leaf...), other...)) // fullchain
	mustWrite(t, KeyPath(dir), key)

	block, _ := pem.Decode(leaf)
	sum := sha256.Sum256(block.Bytes)
	if got, want := LeafFingerprint(dir), hex.EncodeToString(sum[:]); got != want {
		t.Fatalf("Fingerprint = %q, erwartet %q (das erste Zertifikat der Fullchain)", got, want)
	}
}

func TestRequestNamesReplacesOnlyWhenSet(t *testing.T) {
	first, _ := json.Marshal(Request{Token: "t", CSR: "c"})
	if strings.Contains(string(first), "replaces") {
		t.Fatalf("Erst-Provisionierung trägt replaces: %s", first)
	}
	again, _ := json.Marshal(Request{Token: "t", CSR: "c", Replaces: "ab12"})
	if !strings.Contains(string(again), `"replaces":"ab12"`) {
		t.Fatalf("replaces fehlt: %s", again)
	}
}

func TestReprovisionHintNamesTheProvisionCommand(t *testing.T) {
	// R-0280: the agent has no "enroll" subcommand; a new identity comes from provision.
	for _, part := range []string{"adminhelper-agent provision", "--url", "--token", "--server-id"} {
		if !strings.Contains(reprovisionHint, part) {
			t.Fatalf("Hinweis ohne %q: %q", part, reprovisionHint)
		}
	}
	if strings.Contains(reprovisionHint, "enroll") {
		t.Fatalf("Hinweis nennt den falschen Befehl: %q", reprovisionHint)
	}
}

// R-0293: the check before an enrollment request does the staged writes of Store and
// leaves nothing behind.

func TestCheckStorableLeavesNothingBehind(t *testing.T) {
	dir := filepath.Join(t.TempDir(), "identity") // not there yet, as on a first provisioning
	if err := CheckStorable(dir); err != nil {
		t.Fatalf("CheckStorable: %v", err)
	}
	entries, err := os.ReadDir(dir)
	if err != nil {
		t.Fatal(err)
	}
	if len(entries) != 0 {
		t.Fatalf("Reste der Prüfung: %v", entries)
	}
}

func TestCheckStorableReportsAStagedFileThatCannotBeWritten(t *testing.T) {
	dir := t.TempDir()
	// A file the check did not write, as a renewal stages it.
	foreign := filepath.Join(dir, CertFileName+".1"+tmpSuffix)
	mustWrite(t, foreign, []byte("staged"))
	created := failWriteOf(t, CertFileName)
	if err := CheckStorable(dir); err == nil {
		t.Fatal("erwartet Fehler, wenn agent.crt nicht geschrieben werden kann")
	}
	if len(*created) != 2 {
		t.Fatalf("erwartet die Proben für agent.key und agent.crt, angelegt: %v", *created)
	}
	for _, p := range *created {
		if _, err := os.Stat(p); !os.IsNotExist(err) {
			t.Errorf("die Probe %s blieb liegen, stat err = %v", filepath.Base(p), err)
		}
	}
	// What the check did not write is not the check's to remove.
	if b, err := os.ReadFile(foreign); err != nil || string(b) != "staged" {
		t.Errorf("die fremde Datei ist weg oder verändert: %q, %v", b, err)
	}
}

// R-0308: a provisioning's check and the service's renewal write files of their own, so
// a check between the staging and the commit of a renewal leaves the renewal intact.

func TestCheckStorableDuringAStagedRenewKeepsTheRenewal(t *testing.T) {
	dir := filepath.Join(t.TempDir(), "identity")
	if err := os.MkdirAll(dir, 0o700); err != nil {
		t.Fatal(err)
	}
	now := time.Now()
	leaf, _ := selfSigned(t, "srv-1", now.Add(-time.Hour), now.Add(time.Hour))
	chain, _ := selfSigned(t, "intermediate", now.Add(-time.Hour), now.Add(time.Hour))
	fullchain := append(append([]byte{}, leaf...), chain...)
	key, _ := GenerateKey()
	keyPEM, err := encodeKeyPEM(key)
	if err != nil {
		t.Fatal(err)
	}

	// The service stages a renewal, a provisioning checks the directory, the renewal commits.
	commit, err := stageIdentity(dir, key, &IssueResponse{Cert: string(leaf), Fullchain: string(fullchain), Chain: string(chain)})
	if err != nil {
		t.Fatalf("stageIdentity: %v", err)
	}
	if err := CheckStorable(dir); err != nil {
		t.Fatalf("CheckStorable: %v", err)
	}
	if err := commit(); err != nil {
		t.Fatalf("commit: %v", err)
	}

	head := func(b []byte) []byte { return b[:min(len(b), 24)] }
	for _, f := range []struct {
		path string
		want []byte
	}{{KeyPath(dir), keyPEM}, {CertPath(dir), fullchain}, {CAPath(dir), chain}} {
		got, err := os.ReadFile(f.path)
		if err != nil {
			t.Errorf("%s: %v", filepath.Base(f.path), err)
			continue
		}
		if !bytes.Equal(got, f.want) {
			t.Errorf("%s: erwartet die Erneuerung %q, beobachtet %q", filepath.Base(f.path), head(f.want), head(got))
		}
	}
	entries, err := os.ReadDir(dir)
	if err != nil {
		t.Fatal(err)
	}
	if len(entries) != 3 {
		t.Errorf("erwartet nur agent.key, agent.crt und ca.crt, im Verzeichnis: %v", entries)
	}
}

// R-0312: reading the CN of the stored leaf and dropping an identity.

func TestLeafCommonNameIsTheCNOfTheFirstCertificate(t *testing.T) {
	dir := t.TempDir()
	if got := LeafCommonName(dir); got != "" {
		t.Fatalf("ohne Identität erwartet leer, bekam %q", got)
	}
	now := time.Now()
	leaf, key := selfSigned(t, "srv-9", now.Add(-time.Hour), now.Add(time.Hour))
	other, _ := selfSigned(t, "intermediate", now.Add(-time.Hour), now.Add(time.Hour))
	mustWrite(t, CertPath(dir), append(append([]byte{}, leaf...), other...)) // fullchain
	mustWrite(t, KeyPath(dir), key)
	if got := LeafCommonName(dir); got != "srv-9" {
		t.Fatalf("CN = %q, erwartet srv-9 (das erste Zertifikat der Fullchain)", got)
	}
}

func TestRemoveIdentityRemovesKeyCertAndCA(t *testing.T) {
	dir := t.TempDir()
	for _, p := range []string{KeyPath(dir), CertPath(dir), CAPath(dir)} {
		mustWrite(t, p, []byte("x"))
	}
	if err := RemoveIdentity(dir); err != nil {
		t.Fatalf("RemoveIdentity: %v", err)
	}
	for _, p := range []string{KeyPath(dir), CertPath(dir), CAPath(dir)} {
		if _, err := os.Stat(p); !os.IsNotExist(err) {
			t.Errorf("%s ist noch da: %v", p, err)
		}
	}
	if err := RemoveIdentity(dir); err != nil {
		t.Fatalf("ein zweites RemoveIdentity ohne Dateien: %v", err)
	}
}
