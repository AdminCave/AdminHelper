// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package provision

import (
	"bytes"
	"context"
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/rand"
	"crypto/sha256"
	"crypto/x509"
	"crypto/x509/pkix"
	"encoding/hex"
	"encoding/json"
	"encoding/pem"
	"errors"
	"math/big"
	"net/http"
	"net/http/httptest"
	"net/url"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"adminhelper-agent/internal/config"
	"adminhelper-agent/internal/enroll"
)

// TOFU (GHSA-wv93): a --insecure provisioning call must capture the certificate
// the server actually presented, so the recurring loop can pin it instead of
// disabling TLS verification forever.
func TestCallActivateCapturesServerCert(t *testing.T) {
	srv := httptest.NewTLSServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if !strings.HasSuffix(r.URL.Path, "/provision/activate") {
			http.Error(w, "not found", http.StatusNotFound)
			return
		}
		// The X-Provision-Token header is the ONLY auth for the activate call; pin it here so a
		// refactor that drops it fails this test instead of every production provisioning (6.23).
		if r.Header.Get("X-Provision-Token") != "tok" {
			http.Error(w, "missing provision token", http.StatusUnauthorized)
			return
		}
		_ = json.NewEncoder(w).Encode(map[string]any{"serverName": "s", "apiKey": "k"})
	}))
	defer srv.Close()

	// callActivate rewrites the host's port to the enroll plane; the httptest
	// server is on a random port, so pass that port through unchanged.
	u, _ := url.Parse(srv.URL)
	port, _ := strconv.Atoi(u.Port())
	resp, certPEM, err := callActivate(srv.URL, "tok", "srv-1", "", true, nil, port)
	if err != nil {
		t.Fatalf("callActivate: %v", err)
	}
	if resp.APIKey != "k" {
		t.Fatalf("apiKey = %q", resp.APIKey)
	}
	if len(certPEM) == 0 || !strings.Contains(string(certPEM), "BEGIN CERTIFICATE") {
		t.Fatal("Server-Zertifikat wurde nicht erfasst")
	}
	// The captured cert must be exactly what the server presented.
	block, _ := pem.Decode(certPEM)
	if block == nil || !bytes.Equal(block.Bytes, srv.Certificate().Raw) {
		t.Fatal("erfasstes Zertifikat passt nicht zum Server-Zertifikat")
	}
}

// writePinnedCert must produce a readable file containing the chain.
func TestWritePinnedCert(t *testing.T) {
	pemData := []byte("-----BEGIN CERTIFICATE-----\nabc\n-----END CERTIFICATE-----\n")
	path, err := writePinnedCert(pemData)
	if err != nil {
		t.Fatalf("writePinnedCert: %v", err)
	}
	defer func() { _ = os.Remove(path) }()
	got, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("ReadFile: %v", err)
	}
	if !bytes.Equal(got, pemData) {
		t.Fatalf("pinned cert content mismatch")
	}
}

func TestMonitorBaseURL(t *testing.T) {
	// 2.70: derive the push base from the provisioned server URL + the
	// server-declared relative path; nil/absolute values fall back to the
	// well-known path.
	relPath := "/api/mon2"
	absURL := "https://old.example/monitoring"
	wellKnown := "/api/monitoring"
	cases := []struct {
		name       string
		monitorURL *string
		want       string
	}{
		{"nil -> well-known", nil, "https://srv/api/monitoring"},
		{"relative path used", &relPath, "https://srv/api/mon2"},
		{"absolute value -> fallback", &absURL, "https://srv/api/monitoring"},
		{"explicit well-known", &wellKnown, "https://srv/api/monitoring"},
	}
	for _, c := range cases {
		if got := monitorBaseURL("https://srv", c.monitorURL); got != c.want {
			t.Errorf("%s: monitorBaseURL = %q, want %q", c.name, got, c.want)
		}
	}
}

func TestEnrollEndpoint(t *testing.T) {
	// Pure host/port rewrite: swap in the enroll port, drop path+query, and keep IPv6 literals
	// bracketed (Hostname() strips the brackets, JoinHostPort re-adds them) (6.22).
	cases := []struct {
		url  string
		port int
		want string
	}{
		{"https://example.com", 8444, "https://example.com:8444/enroll"},
		{"https://example.com:8443/api?x=1", 8444, "https://example.com:8444/enroll"},
		{"https://[::1]:8443/api", 8444, "https://[::1]:8444/enroll"},
	}
	for _, c := range cases {
		got, err := enrollEndpoint(c.url, c.port)
		if err != nil || got != c.want {
			t.Errorf("enrollEndpoint(%q, %d) = %q/%v, erwartet %q", c.url, c.port, got, err, c.want)
		}
	}
	if _, err := enrollEndpoint("://kaputt", 1); err == nil {
		t.Error("ungueltige URL haette Fehler ergeben muessen")
	}
	if _, err := enrollEndpoint("/no-host", 1); err == nil {
		t.Error("URL ohne Host haette Fehler ergeben muessen")
	}
}

func TestCallActivateRejectsConsumedToken(t *testing.T) {
	// A consumed/invalid provision token -> the server answers 403; callActivate must surface an
	// error, not treat the empty body as a successful activation (6.23).
	srv := httptest.NewTLSServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		http.Error(w, "token bereits verwendet", http.StatusForbidden)
	}))
	defer srv.Close()
	u, _ := url.Parse(srv.URL)
	port, _ := strconv.Atoi(u.Port())
	if _, _, err := callActivate(srv.URL, "used", "srv-1", "", true, nil, port); err == nil {
		t.Fatal("403 (verbrauchter Token) haette einen Fehler ergeben muessen")
	}
}

func TestRunRejectsCAFPCombinedWithOtherTrust(t *testing.T) {
	stubEnableTimer(t, nil)
	// One trust source per call: --ca-fp must not be silently weakened by
	// --insecure or diluted by --cacert. Validation fails BEFORE any network I/O
	// (the URL is unroutable on purpose — reaching it would hang/fail differently).
	if err := Run("https://192.0.2.1", "tok", "srv-1", "", true, "ab"); err == nil ||
		!strings.Contains(err.Error(), "--ca-fp") {
		t.Fatalf("--ca-fp + --insecure haette die Kombi-Validierung treffen muessen, war: %v", err)
	}
	if err := Run("https://192.0.2.1", "tok", "srv-1", "/tmp/ca.pem", false, "ab"); err == nil ||
		!strings.Contains(err.Error(), "--ca-fp") {
		t.Fatalf("--ca-fp + --cacert haette die Kombi-Validierung treffen muessen, war: %v", err)
	}
	// A malformed fingerprint must also die before any network I/O.
	if err := Run("https://192.0.2.1", "tok", "srv-1", "", false, "nicht-hex"); err == nil ||
		!strings.Contains(err.Error(), "SHA-256") {
		t.Fatalf("kaputter Fingerprint haette die Parse-Validierung treffen muessen, war: %v", err)
	}
}

// R-0639: with --ca-fp the first contact takes only a certificate that names the host of --url,
// as every later call does; otherwise provision stops before the token leaves the host.
func TestRunCAFingerprintRedeemsNothingForAHostTheCertDoesNotName(t *testing.T) {
	t.Setenv("ADMINHELPER_FRP_DIR", t.TempDir())
	t.Setenv("ADMINHELPER_MONITOR_DIR", t.TempDir())
	var requests atomic.Int32
	// httptest's certificate names example.com, *.example.com, 127.0.0.1 and ::1, not localhost.
	srv := httptest.NewTLSServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		requests.Add(1)
		if r.URL.Path != "/api/servers/srv-1/provision/activate" {
			http.Error(w, "not found", http.StatusNotFound)
			return
		}
		_ = json.NewEncoder(w).Encode(map[string]any{"serverName": "s", "apiKey": "k", "frp": nil})
	}))
	defer srv.Close()
	u, _ := url.Parse(srv.URL)
	port, _ := strconv.Atoi(u.Port())
	orig := activatePort
	activatePort = port
	t.Cleanup(func() { activatePort = orig })
	origApply := applyWithoutBundle
	applyWithoutBundle = func() error { return nil }
	t.Cleanup(func() { applyWithoutBundle = origApply })
	stubEnableTimer(t, nil)
	// A direct pin: the fingerprint of the presented certificate itself.
	fp := sha256.Sum256(srv.Certificate().Raw)
	caFP := hex.EncodeToString(fp[:])

	err := Run("https://localhost:"+u.Port(), "tok", "srv-1", "", false, caFP)
	if n := requests.Load(); n != 0 {
		t.Errorf("the server got %d request(s) via a host its certificate does not name, want none: the token is spent", n)
	}
	if err == nil || !strings.Contains(err.Error(), "does not name localhost") || !strings.Contains(err.Error(), "127.0.0.1") {
		t.Fatalf("error = %v, want one naming localhost and the names of the certificate", err)
	}
	if _, err := os.Stat(config.FrpAdminHelperConf()); !errors.Is(err, os.ErrNotExist) {
		t.Errorf("%s exists after the refused call (stat: %v)", config.FrpAdminHelperConf(), err)
	}

	// The counter-check: via a name the certificate carries, the same call redeems the token.
	if err := Run("https://127.0.0.1:"+u.Port(), "tok", "srv-1", "", false, caFP); err != nil {
		t.Fatalf("Run via 127.0.0.1: %v", err)
	}
	if n := requests.Load(); n != 1 {
		t.Errorf("the server got %d request(s) via 127.0.0.1, want the activate call", n)
	}
}

// One trust source per call, also for --cacert: it already verifies the server, and
// --insecure on top would switch that check off for the call and the config it writes.
// The pair is refused before the data root is secured or the token leaves the host.
func TestProvisionTrustRefusesCACertWithInsecure(t *testing.T) {
	t.Setenv("ADMINHELPER_FRP_DIR", t.TempDir())
	t.Setenv("ADMINHELPER_MONITOR_DIR", t.TempDir())
	var requests atomic.Int32
	srv := httptest.NewTLSServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		requests.Add(1)
		if r.URL.Path != "/api/servers/srv-1/provision/activate" {
			http.Error(w, "not found", http.StatusNotFound)
			return
		}
		_ = json.NewEncoder(w).Encode(map[string]any{"serverName": "s", "apiKey": "k", "frp": nil})
	}))
	defer srv.Close()
	cacert := filepath.Join(t.TempDir(), "ca.pem")
	caPEM := pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: srv.Certificate().Raw})
	if err := os.WriteFile(cacert, caPEM, 0o600); err != nil {
		t.Fatal(err)
	}
	u, _ := url.Parse(srv.URL)
	port, _ := strconv.Atoi(u.Port())
	orig := activatePort
	activatePort = port
	t.Cleanup(func() { activatePort = orig })
	origApply := applyWithoutBundle
	applyWithoutBundle = func() error { return nil }
	t.Cleanup(func() { applyWithoutBundle = origApply })
	stubEnableTimer(t, nil)

	err := Run(srv.URL, "tok", "srv-1", cacert, true, "")
	if n := requests.Load(); n != 0 {
		t.Errorf("the server got %d request(s), want none: the token is spent", n)
	}
	if err == nil || !strings.Contains(err.Error(), "--cacert") || !strings.Contains(err.Error(), "--insecure") {
		t.Fatalf("error = %v, want one naming --cacert and --insecure", err)
	}
	for _, f := range []string{config.FrpAdminHelperConf(), config.MonitorConfFile()} {
		if _, err := os.Stat(f); !errors.Is(err, os.ErrNotExist) {
			t.Errorf("%s exists after the refused call (stat: %v)", f, err)
		}
	}
}

// A blind --insecure without a certificate to pin fails instead of handing on
// insecure: the follow-up calls and the stored config would otherwise not verify.
func TestProvisionTrustBlindInsecureWithoutACertificateFails(t *testing.T) {
	path, insecure, cleanup, err := pinIfBlindInsecure("", true, nil)
	defer cleanup()
	if err == nil {
		t.Fatalf("pinIfBlindInsecure without a certificate = (%q, insecure %v), want an error", path, insecure)
	}
	if insecure {
		t.Error("insecure = true alongside the error, want false")
	}
}

// The counterpart: with the chain the activate call saw, a blind --insecure becomes
// the pinned file and verification stays on.
func TestProvisionTrustBlindInsecurePinsThePresentedCertificate(t *testing.T) {
	chain := []byte("-----BEGIN CERTIFICATE-----\nY2E=\n-----END CERTIFICATE-----\n")
	path, insecure, cleanup, err := pinIfBlindInsecure("", true, chain)
	if err != nil {
		t.Fatalf("pinIfBlindInsecure: %v", err)
	}
	t.Cleanup(cleanup)
	if insecure {
		t.Error("insecure = true, want false: the pinned file is the trust")
	}
	got, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("pinned file %q: %v", path, err)
	}
	if !bytes.Equal(got, chain) {
		t.Fatalf("pinned file = %q, want the presented chain", got)
	}
}

func TestPinVerifiedAnchorWritesOnlyTheAnchor(t *testing.T) {
	// The pinned file must contain EXACTLY the fingerprint-matched cert — pinning
	// the whole presented chain would anchor the rotating leaf too, defeating the
	// point of a CA pin.
	leafPEM := []byte("-----BEGIN CERTIFICATE-----\nbGVhZg==\n-----END CERTIFICATE-----\n")
	caPEM := []byte("-----BEGIN CERTIFICATE-----\nY2E=\n-----END CERTIFICATE-----\n")
	chain := append(append([]byte{}, leafPEM...), caPEM...)

	caBlock, _ := pem.Decode(caPEM)
	fp := sha256.Sum256(caBlock.Bytes)

	path, _, err := pinVerifiedAnchor(chain, fp)
	if err != nil {
		t.Fatalf("pinVerifiedAnchor: %v", err)
	}
	defer os.Remove(path)
	got, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	blocks := 0
	rest := got
	for {
		var b *pem.Block
		b, rest = pem.Decode(rest)
		if b == nil {
			break
		}
		blocks++
		if sha256.Sum256(b.Bytes) != fp {
			t.Fatal("gepinnter Block ist nicht der Anchor")
		}
	}
	if blocks != 1 {
		t.Fatalf("erwartet genau 1 gepinntes Zertifikat, war %d", blocks)
	}

	// Fingerprint not present in the chain -> fail closed.
	var wrong [sha256.Size]byte
	if _, _, err := pinVerifiedAnchor(chain, wrong); err == nil {
		t.Fatal("fehlender Anchor haette einen Fehler ergeben muessen")
	}
}

func TestCallActivateRejectsBadJSON(t *testing.T) {
	// A 200 with an unparseable body must not be swallowed as a success (6.23).
	srv := httptest.NewTLSServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		_, _ = w.Write([]byte("{not json"))
	}))
	defer srv.Close()
	u, _ := url.Parse(srv.URL)
	port, _ := strconv.Atoi(u.Port())
	if _, _, err := callActivate(srv.URL, "tok", "srv-1", "", true, nil, port); err == nil {
		t.Fatal("kaputtes JSON haette einen Fehler ergeben muessen")
	}
}

// R-0224: a re-provisioning names the leaf of the earlier one, so the issuer revokes
// that line; a first provisioning names nothing.
func TestRunEnrollmentNamesTheLeafItReplaces(t *testing.T) {
	t.Setenv("ADMINHELPER_MONITOR_DIR", t.TempDir())
	var bodies []map[string]any
	srv := httptest.NewTLSServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		var body map[string]any
		_ = json.NewDecoder(r.Body).Decode(&body)
		bodies = append(bodies, body)
		_ = json.NewEncoder(w).Encode(map[string]string{
			"cert": "c", "fullchain": "fullchain", "chain": "chain",
		})
	}))
	defer srv.Close()
	u, _ := url.Parse(srv.URL)
	port, _ := strconv.Atoi(u.Port())
	info := &enrollmentInfo{Token: "t", SubjectID: "srv-1", EnrollPort: port}

	if err := runEnrollment(srv.URL, info, "", true); err != nil {
		t.Fatalf("erste Provisionierung: %v", err)
	}
	// The earlier provisioning left this leaf on disk (the key Store wrote stays).
	oldLeaf := srv.Certificate().Raw
	certPath := enroll.CertPath(config.AgentPkiDir())
	if err := os.WriteFile(certPath, pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: oldLeaf}), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := runEnrollment(srv.URL, info, "", true); err != nil {
		t.Fatalf("Neu-Provisionierung: %v", err)
	}

	if len(bodies) != 2 {
		t.Fatalf("erwartet 2 Enroll-Aufrufe, bekam %d", len(bodies))
	}
	if _, ok := bodies[0]["replaces"]; ok {
		t.Fatalf("Erst-Provisionierung trägt replaces: %v", bodies[0])
	}
	sum := sha256.Sum256(oldLeaf)
	if got, want := bodies[1]["replaces"], hex.EncodeToString(sum[:]); got != want {
		t.Fatalf("replaces = %v, erwartet %q", got, want)
	}
}

// R-0293: the enrollment request lets the issuer revoke the earlier line at once, so a
// re-provisioning asks only for an identity this host can store.

// provisionedOnce provisions once against srv and leaves an old leaf on disk.
func provisionedOnce(t *testing.T, srv *httptest.Server, info *enrollmentInfo) string {
	t.Helper()
	if err := runEnrollment(srv.URL, info, "", true); err != nil {
		t.Fatalf("erste Provisionierung: %v", err)
	}
	dir := config.AgentPkiDir()
	leaf := pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: srv.Certificate().Raw})
	if err := os.WriteFile(enroll.CertPath(dir), leaf, 0o644); err != nil {
		t.Fatal(err)
	}
	return dir
}

func TestRunEnrollmentRequestsNothingWhenTheIdentityCannotBeStored(t *testing.T) {
	t.Setenv("ADMINHELPER_MONITOR_DIR", t.TempDir())
	requests := 0
	srv := httptest.NewTLSServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		requests++
		_ = json.NewEncoder(w).Encode(map[string]string{"cert": "c", "fullchain": "fullchain", "chain": "chain"})
	}))
	defer srv.Close()
	u, _ := url.Parse(srv.URL)
	port, _ := strconv.Atoi(u.Port())
	info := &enrollmentInfo{Token: "t", SubjectID: "srv-1", EnrollPort: port}
	dir := provisionedOnce(t, srv, info)
	before, _ := os.ReadFile(enroll.CertPath(dir))

	// The staged cert cannot be written. Every staged write has a temp file of its own
	// (R-0308), so nothing on disk can be put in its way; the check reports it here.
	orig := checkStorable
	checkStorable = func(string) error { return errors.New("stage agent.crt: no space left on device") }
	t.Cleanup(func() { checkStorable = orig })
	if err := runEnrollment(srv.URL, info, "", true); err == nil {
		t.Fatal("erwartet Fehler, wenn die Identität nicht gespeichert werden kann")
	}
	if requests != 1 {
		t.Fatalf("erwartet keinen zweiten Enroll-Aufruf, der Issuer bekam %d", requests)
	}
	if after, _ := os.ReadFile(enroll.CertPath(dir)); !bytes.Equal(after, before) {
		t.Fatal("das bisherige Zertifikat wurde verändert")
	}
}

func TestRunEnrollmentNamesTheWayOutWhenStoringFailsAfterTheRequest(t *testing.T) {
	t.Setenv("ADMINHELPER_MONITOR_DIR", t.TempDir())
	srv := httptest.NewTLSServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		_ = json.NewEncoder(w).Encode(map[string]string{"cert": "c", "fullchain": "fullchain", "chain": "chain"})
	}))
	defer srv.Close()
	u, _ := url.Parse(srv.URL)
	port, _ := strconv.Atoi(u.Port())
	info := &enrollmentInfo{Token: "t", SubjectID: "srv-1", EnrollPort: port}
	provisionedOnce(t, srv, info)

	// The disk gives out between the check and Store.
	orig := storeIdentity
	storeIdentity = func(string, *ecdsa.PrivateKey, *enroll.IssueResponse) error {
		return errors.New("stage agent.crt: no space left on device")
	}
	t.Cleanup(func() { storeIdentity = orig })
	err := runEnrollment(srv.URL, info, "", true)
	if err == nil {
		t.Fatal("erwartet Fehler, wenn Store nach dem Antrag scheitert")
	}
	if !strings.Contains(err.Error(), "adminhelper-agent provision") {
		t.Fatalf("Fehler ohne den Befehl zum Neu-Provisionieren: %v", err)
	}
}

// R-0312: an identity issued for another server is one this server never accepts; a
// provisioning for another server drops it before asking for a new one.

// storeIdentityOf writes a key and a leaf with the given CN into dir, as an earlier
// provisioning would have left them.
func storeIdentityOf(t *testing.T, dir, cn string) {
	t.Helper()
	key, err := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	if err != nil {
		t.Fatal(err)
	}
	tmpl := &x509.Certificate{
		SerialNumber: big.NewInt(1),
		Subject:      pkix.Name{CommonName: cn},
		NotBefore:    time.Now().Add(-time.Hour),
		NotAfter:     time.Now().Add(time.Hour),
	}
	der, err := x509.CreateCertificate(rand.Reader, tmpl, tmpl, &key.PublicKey, key)
	if err != nil {
		t.Fatal(err)
	}
	keyDER, _ := x509.MarshalPKCS8PrivateKey(key)
	if err := os.MkdirAll(dir, 0o700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(enroll.CertPath(dir), pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: der}), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(enroll.KeyPath(dir), pem.EncodeToMemory(&pem.Block{Type: "PRIVATE KEY", Bytes: keyDER}), 0o600); err != nil {
		t.Fatal(err)
	}
}

// issuerDown answers every enrollment with a 500.
func issuerDown(t *testing.T) (*httptest.Server, int) {
	t.Helper()
	srv := httptest.NewTLSServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		http.Error(w, "issuer down", http.StatusInternalServerError)
	}))
	t.Cleanup(srv.Close)
	u, _ := url.Parse(srv.URL)
	port, _ := strconv.Atoi(u.Port())
	return srv, port
}

func TestRunEnrollmentDropsTheIdentityOfAnotherServer(t *testing.T) {
	t.Setenv("ADMINHELPER_MONITOR_DIR", t.TempDir())
	dir := config.AgentPkiDir()
	storeIdentityOf(t, dir, "srv-1")
	srv, port := issuerDown(t)

	if err := runEnrollment(srv.URL, &enrollmentInfo{Token: "t", SubjectID: "srv-2", EnrollPort: port}, "", true); err == nil {
		t.Fatal("erwartet Fehler, der Issuer antwortet 500")
	}
	if enroll.Provisioned(dir) {
		t.Fatalf("die Identität von srv-1 ist nach der Provisionierung für srv-2 noch da (CN %q)", enroll.LeafCommonName(dir))
	}
}

func TestRunEnrollmentKeepsTheIdentityOfTheSameServerWhenEnrollmentFails(t *testing.T) {
	t.Setenv("ADMINHELPER_MONITOR_DIR", t.TempDir())
	dir := config.AgentPkiDir()
	storeIdentityOf(t, dir, "srv-1")
	srv, port := issuerDown(t)

	if err := runEnrollment(srv.URL, &enrollmentInfo{Token: "t", SubjectID: "srv-1", EnrollPort: port}, "", true); err == nil {
		t.Fatal("erwartet Fehler, der Issuer antwortet 500")
	}
	if got := enroll.LeafCommonName(dir); got != "srv-1" {
		t.Fatalf("die eigene Identität muss bleiben, CN = %q", got)
	}
}

// R-0384: a provisioning holds the identity lock from its first read of the identity to
// the commit, so it never interleaves with a renewal and names what one stored first.

// recordingIssuer answers every enrollment like the issuer and passes each request body
// on to the returned channel.
func recordingIssuer(t *testing.T) (*httptest.Server, int, <-chan map[string]any) {
	t.Helper()
	bodies := make(chan map[string]any, 8)
	srv := httptest.NewTLSServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		var body map[string]any
		_ = json.NewDecoder(r.Body).Decode(&body)
		bodies <- body
		_ = json.NewEncoder(w).Encode(map[string]string{"cert": "c", "fullchain": "fullchain", "chain": "chain"})
	}))
	t.Cleanup(srv.Close)
	u, _ := url.Parse(srv.URL)
	port, _ := strconv.Atoi(u.Port())
	return srv, port, bodies
}

// runEnrollmentBehindLock takes the identity lock and starts runEnrollment, which must
// neither ask the issuer nor return while the lock is held. It returns runEnrollment's
// result and the unlock of the held lock, which the cleanup calls too.
func runEnrollmentBehindLock(t *testing.T, srvURL string, info *enrollmentInfo, bodies <-chan map[string]any) (<-chan error, func()) {
	t.Helper()
	unlock, err := enroll.LockIdentity(context.Background(), config.AgentPkiDir())
	if err != nil {
		t.Fatalf("LockIdentity: %v", err)
	}
	var once sync.Once
	release := func() { once.Do(unlock) }
	t.Cleanup(release)
	res := make(chan error, 1)
	go func() { res <- runEnrollment(srvURL, info, "", true) }()
	select {
	case body := <-bodies:
		t.Fatalf("runEnrollment asked the issuer while the identity lock was held: %v", body)
	case err := <-res:
		t.Fatalf("runEnrollment returned (%v) while the identity lock was held", err)
	case <-time.After(500 * time.Millisecond):
	}
	return res, release
}

// awaitEnrollment waits for runEnrollment to succeed and returns the one request it sent.
func awaitEnrollment(t *testing.T, res <-chan error, bodies <-chan map[string]any) map[string]any {
	t.Helper()
	select {
	case err := <-res:
		if err != nil {
			t.Fatalf("runEnrollment: %v", err)
		}
	case <-time.After(10 * time.Second):
		t.Fatal("runEnrollment did not return after the identity lock was released")
	}
	select {
	case body := <-bodies:
		return body
	default:
		t.Fatal("runEnrollment returned without asking the issuer")
		return nil
	}
}

func TestRunEnrollmentWaitsForTheIdentityLock(t *testing.T) {
	t.Setenv("ADMINHELPER_MONITOR_DIR", t.TempDir())
	dir := config.AgentPkiDir()
	// The identity of another server, which runEnrollment drops: only under the lock.
	storeIdentityOf(t, dir, "srv-1")
	srv, port, bodies := recordingIssuer(t)

	res, unlock := runEnrollmentBehindLock(t, srv.URL, &enrollmentInfo{Token: "t", SubjectID: "srv-2", EnrollPort: port}, bodies)
	if got := enroll.LeafCommonName(dir); got != "srv-1" {
		t.Fatalf("runEnrollment dropped the identity while the identity lock was held, CN = %q", got)
	}
	unlock()
	awaitEnrollment(t, res, bodies)
}

// Without the identity lock runEnrollment neither touches the identity nor asks.
func TestRunEnrollmentRequestsNothingWithoutTheIdentityLock(t *testing.T) {
	t.Setenv("ADMINHELPER_MONITOR_DIR", t.TempDir())
	dir := config.AgentPkiDir()
	storeIdentityOf(t, dir, "srv-1")
	if err := os.Mkdir(filepath.Join(dir, enroll.LockFileName), 0o700); err != nil {
		t.Fatal(err)
	}
	srv, port, bodies := recordingIssuer(t)

	if err := runEnrollment(srv.URL, &enrollmentInfo{Token: "t", SubjectID: "srv-2", EnrollPort: port}, "", true); err == nil {
		t.Fatal("expected an error when the identity lock cannot be taken")
	}
	select {
	case body := <-bodies:
		t.Fatalf("runEnrollment asked the issuer without the identity lock: %v", body)
	default:
	}
	if got := enroll.LeafCommonName(dir); got != "srv-1" {
		t.Fatalf("runEnrollment changed the identity without the identity lock, CN = %q", got)
	}
}

func TestRunEnrollmentReplacesTheIdentityARenewalStoredFirst(t *testing.T) {
	t.Setenv("ADMINHELPER_MONITOR_DIR", t.TempDir())
	srv, port, bodies := recordingIssuer(t)
	info := &enrollmentInfo{Token: "t", SubjectID: "srv-1", EnrollPort: port}
	dir := provisionedOnce(t, srv, info)
	<-bodies // the earlier provisioning's request
	earlier := sha256.Sum256(srv.Certificate().Raw)

	res, unlock := runEnrollmentBehindLock(t, srv.URL, info, bodies)
	// A renewal that holds the lock first stores its certificate while runEnrollment waits.
	storeIdentityOf(t, dir, "srv-1")
	certPEM, err := os.ReadFile(enroll.CertPath(dir))
	if err != nil {
		t.Fatal(err)
	}
	block, _ := pem.Decode(certPEM)
	renewed := sha256.Sum256(block.Bytes)
	unlock()

	body := awaitEnrollment(t, res, bodies)
	if got, want := body["replaces"], hex.EncodeToString(renewed[:]); got != want {
		t.Fatalf("replaces = %v, want the renewed leaf %q, not the earlier %q", got, want, hex.EncodeToString(earlier[:]))
	}
}

// A renewal that starts while the provisioning waits for the issuer finds the new
// identity stored, not the one whose line the request has the issuer revoke.
func TestRunEnrollmentHoldsTheIdentityLockUntilItStored(t *testing.T) {
	t.Setenv("ADMINHELPER_MONITOR_DIR", t.TempDir())
	dir := config.AgentPkiDir()
	storeIdentityOf(t, dir, "srv-1")
	asked := make(chan struct{}, 1)
	answer := make(chan struct{})
	srv := httptest.NewTLSServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		asked <- struct{}{}
		<-answer
		_ = json.NewEncoder(w).Encode(map[string]string{"cert": "c", "fullchain": "fullchain", "chain": "chain"})
	}))
	t.Cleanup(srv.Close)
	t.Cleanup(func() { close(answer) })
	u, _ := url.Parse(srv.URL)
	port, _ := strconv.Atoi(u.Port())

	res := make(chan error, 1)
	go func() {
		res <- runEnrollment(srv.URL, &enrollmentInfo{Token: "t", SubjectID: "srv-1", EnrollPort: port}, "", true)
	}()
	select {
	case <-asked:
	case err := <-res:
		t.Fatalf("runEnrollment returned (%v) without asking the issuer", err)
	case <-time.After(10 * time.Second):
		t.Fatal("runEnrollment did not ask the issuer")
	}

	// What a renewal that gets the lock reads first.
	seen := make(chan []byte, 1)
	go func() {
		unlock, err := enroll.LockIdentity(context.Background(), dir)
		if err != nil {
			t.Errorf("LockIdentity: %v", err)
			seen <- nil
			return
		}
		cert, _ := os.ReadFile(enroll.CertPath(dir))
		// Before the send: Windows cannot remove the temp dir while the lock file is open.
		unlock()
		seen <- cert
	}()
	select {
	case <-seen:
		t.Fatal("the identity lock was free while runEnrollment waited for the issuer")
	case <-time.After(500 * time.Millisecond):
	}
	answer <- struct{}{}

	select {
	case err := <-res:
		if err != nil {
			t.Fatalf("runEnrollment: %v", err)
		}
	case <-time.After(10 * time.Second):
		t.Fatal("runEnrollment did not return after the issuer answered")
	}
	select {
	case cert := <-seen:
		if string(cert) != "fullchain" {
			t.Fatalf("the lock was free before the new identity was stored, a renewal read %q", cert)
		}
	case <-time.After(10 * time.Second):
		t.Fatal("the identity lock was not free after runEnrollment returned")
	}
}

// R-0398: a provisioning stores the sync config also without an FRP bundle, so a tunnel
// created later reaches the host with the next sync instead of never. It then stops a frpc of an
// earlier provisioning (frpc.ApplyWithoutBundle).
func TestRunWritesTheSyncConfigWithoutAnFRPBundle(t *testing.T) {
	t.Setenv("ADMINHELPER_FRP_DIR", t.TempDir())
	t.Setenv("ADMINHELPER_MONITOR_DIR", t.TempDir())
	srv := httptest.NewTLSServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/api/servers/srv-1/provision/activate" {
			http.Error(w, "not found", http.StatusNotFound)
			return
		}
		_ = json.NewEncoder(w).Encode(map[string]any{"serverName": "s", "apiKey": "k", "frp": nil})
	}))
	defer srv.Close()
	u, _ := url.Parse(srv.URL)
	port, _ := strconv.Atoi(u.Port())
	orig := activatePort
	activatePort = port
	t.Cleanup(func() { activatePort = orig })
	stops := 0
	origApply := applyWithoutBundle
	applyWithoutBundle = func() error {
		stops++
		if _, err := os.Stat(config.FrpAdminHelperConf()); err != nil {
			t.Errorf("frpc stopped before the sync config was written (%v)", err)
		}
		return nil
	}
	t.Cleanup(func() { applyWithoutBundle = origApply })
	stubEnableTimer(t, nil)

	if err := Run(srv.URL, "tok", "srv-1", "", true, ""); err != nil {
		t.Fatalf("Run: %v", err)
	}
	if stops != 1 {
		t.Errorf("frpc.ApplyWithoutBundle calls = %d, want 1", stops)
	}

	cfg, err := config.LoadFrpcConfig()
	if err != nil {
		t.Fatalf("no sync config after a provisioning without an FRP bundle: %v", err)
	}
	if cfg.AdminHelperURL != srv.URL || cfg.APIKey != "k" || cfg.ServerID != "srv-1" {
		t.Fatalf("sync config = %+v, want URL %q, key k, server srv-1", cfg, srv.URL)
	}
	// The blind --insecure is TOFU-pinned for the syncs to come, not stored as INSECURE.
	if cfg.Insecure || cfg.CACert != config.FrpCACert() {
		t.Fatalf("sync config trust = CACERT %q, INSECURE %v; want the pinned %q", cfg.CACert, cfg.Insecure, config.FrpCACert())
	}
	pinned, err := os.ReadFile(config.FrpCACert())
	if err != nil {
		t.Fatal(err)
	}
	if block, _ := pem.Decode(pinned); block == nil || !bytes.Equal(block.Bytes, srv.Certificate().Raw) {
		t.Fatal("ca.crt is not the certificate the server presented")
	}
}

// R-0557: the one-time token is redeemed only once the data root is secured, so a root
// that cannot be secured leaves the token unspent instead of failing after redeeming it.
func TestRunRedeemsNothingWhenTheDataRootCannotBeSecured(t *testing.T) {
	// A directory below a regular file cannot be created on either platform.
	file := filepath.Join(t.TempDir(), "file")
	if err := os.WriteFile(file, nil, 0o600); err != nil {
		t.Fatal(err)
	}
	root := filepath.Join(file, "adminhelper")
	t.Setenv("ADMINHELPER_MONITOR_DIR", root)
	// Where a provisioning that went on would write, instead of the real paths.
	t.Setenv("ADMINHELPER_FRP_DIR", t.TempDir())
	var requests atomic.Int32
	srv := httptest.NewTLSServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		requests.Add(1)
		if r.URL.Path != "/api/servers/srv-1/provision/activate" {
			http.Error(w, "not found", http.StatusNotFound)
			return
		}
		_ = json.NewEncoder(w).Encode(map[string]any{"serverName": "s", "apiKey": "k", "frp": nil})
	}))
	defer srv.Close()
	u, _ := url.Parse(srv.URL)
	port, _ := strconv.Atoi(u.Port())
	orig := activatePort
	activatePort = port
	t.Cleanup(func() { activatePort = orig })
	origApply := applyWithoutBundle
	applyWithoutBundle = func() error { return nil }
	t.Cleanup(func() { applyWithoutBundle = origApply })
	stubEnableTimer(t, nil)

	err := Run(srv.URL, "tok", "srv-1", "", true, "")
	if n := requests.Load(); n != 0 {
		t.Errorf("the server got %d request(s) before the data root was secured, want none: the token is spent", n)
	}
	if err == nil {
		t.Fatal("Run succeeded although the data root cannot be secured")
	}
	if !strings.Contains(err.Error(), root) || !strings.Contains(err.Error(), "not redeemed") {
		t.Fatalf("error = %q, want the directory %q and that the token was not redeemed", err, root)
	}
}

// stubEnableTimer puts a counter in place of service.EnableTimer (systemctl on Linux) for one
// test; the stub returns err.
func stubEnableTimer(t *testing.T, err error) *int {
	t.Helper()
	calls := 0
	orig := enableTimer
	enableTimer = func() error { calls++; return err }
	t.Cleanup(func() { enableTimer = orig })
	return &calls
}

// activateWithoutBundle serves an activate call that returns the server API key, but neither a
// monitor key nor an FRP bundle, points activatePort at it and stubs the stop of frpc.
func activateWithoutBundle(t *testing.T) *httptest.Server {
	t.Helper()
	srv := httptest.NewTLSServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/api/servers/srv-1/provision/activate" {
			http.Error(w, "not found", http.StatusNotFound)
			return
		}
		_ = json.NewEncoder(w).Encode(map[string]any{"serverName": "s", "apiKey": "k", "frp": nil})
	}))
	t.Cleanup(srv.Close)
	u, _ := url.Parse(srv.URL)
	port, _ := strconv.Atoi(u.Port())
	orig := activatePort
	activatePort = port
	t.Cleanup(func() { activatePort = orig })
	origApply := applyWithoutBundle
	applyWithoutBundle = func() error { return nil }
	t.Cleanup(func() { applyWithoutBundle = origApply })
	return srv
}

// R-0641: a provisioning enables the agent timer once, whatever the server configured, here
// without monitor key and FRP bundle, where nothing enabled it before. A provisioning that stops
// before it redeems the token enables nothing.
func TestRunEnablesTheTimerOnce(t *testing.T) {
	t.Run("without monitor and FRP bundle", func(t *testing.T) {
		t.Setenv("ADMINHELPER_FRP_DIR", t.TempDir())
		t.Setenv("ADMINHELPER_MONITOR_DIR", t.TempDir())
		srv := activateWithoutBundle(t)
		calls := stubEnableTimer(t, nil)

		if err := Run(srv.URL, "tok", "srv-1", "", true, ""); err != nil {
			t.Fatalf("Run: %v", err)
		}
		if *calls != 1 {
			t.Errorf("timer enabled %d times, want 1", *calls)
		}
	})
	t.Run("data root cannot be secured", func(t *testing.T) {
		// A directory below a regular file cannot be created on either platform.
		file := filepath.Join(t.TempDir(), "file")
		if err := os.WriteFile(file, nil, 0o600); err != nil {
			t.Fatal(err)
		}
		t.Setenv("ADMINHELPER_MONITOR_DIR", filepath.Join(file, "adminhelper"))
		t.Setenv("ADMINHELPER_FRP_DIR", t.TempDir())
		srv := activateWithoutBundle(t)
		calls := stubEnableTimer(t, nil)

		if err := Run(srv.URL, "tok", "srv-1", "", true, ""); err == nil {
			t.Fatal("Run succeeded although the data root cannot be secured")
		}
		if *calls != 0 {
			t.Errorf("timer enabled %d times by a provisioning that stopped before the token, want 0", *calls)
		}
	})
}

// A timer that cannot be enabled does not fail a provisioning that has spent its token: Run
// reports it and succeeds.
func TestRunSucceedsWhenTheTimerCannotBeEnabled(t *testing.T) {
	t.Setenv("ADMINHELPER_FRP_DIR", t.TempDir())
	t.Setenv("ADMINHELPER_MONITOR_DIR", t.TempDir())
	srv := activateWithoutBundle(t)
	calls := stubEnableTimer(t, errors.New("systemctl enable --now adminhelper-agent.timer: exit status 1"))

	if err := Run(srv.URL, "tok", "srv-1", "", true, ""); err != nil {
		t.Fatalf("Run = %v, want nil: the provisioning stands", err)
	}
	if *calls != 1 {
		t.Errorf("timer enabled %d times, want 1", *calls)
	}
}
