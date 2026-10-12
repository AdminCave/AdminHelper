// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package provision

import (
	"bytes"
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/rand"
	"crypto/sha256"
	"crypto/x509"
	"crypto/x509/pkix"
	"encoding/hex"
	"encoding/json"
	"encoding/pem"
	"math/big"
	"net/http"
	"net/http/httptest"
	"net/url"
	"os"
	"strconv"
	"strings"
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

	// The staged cert cannot be written: its temp path is taken by a directory. A chmod
	// would not do, Store and the check set the directory to 0700 themselves.
	if err := os.Mkdir(enroll.CertPath(dir)+".tmp", 0o755); err != nil {
		t.Fatal(err)
	}
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
	block := false
	srv := httptest.NewTLSServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		// The disk gives out between the check and Store: block the staged cert now.
		if block {
			_ = os.Mkdir(enroll.CertPath(config.AgentPkiDir())+".tmp", 0o755)
		}
		_ = json.NewEncoder(w).Encode(map[string]string{"cert": "c", "fullchain": "fullchain", "chain": "chain"})
	}))
	defer srv.Close()
	u, _ := url.Parse(srv.URL)
	port, _ := strconv.Atoi(u.Port())
	info := &enrollmentInfo{Token: "t", SubjectID: "srv-1", EnrollPort: port}
	provisionedOnce(t, srv, info)

	block = true
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
