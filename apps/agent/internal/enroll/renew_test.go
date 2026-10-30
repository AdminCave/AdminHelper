// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package enroll

import (
	"context"
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/rand"
	"crypto/tls"
	"crypto/x509"
	"crypto/x509/pkix"
	"encoding/json"
	"encoding/pem"
	"errors"
	"math/big"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

// selfSigned builds a self-signed leaf + PKCS#8 key PEM with the given validity.
func selfSigned(t *testing.T, cn string, notBefore, notAfter time.Time) (certPEM, keyPEM []byte) {
	t.Helper()
	key, err := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	if err != nil {
		t.Fatal(err)
	}
	tmpl := &x509.Certificate{
		SerialNumber:          big.NewInt(1),
		Subject:               pkix.Name{CommonName: cn},
		NotBefore:             notBefore,
		NotAfter:              notAfter,
		KeyUsage:              x509.KeyUsageDigitalSignature,
		BasicConstraintsValid: true,
	}
	der, err := x509.CreateCertificate(rand.Reader, tmpl, tmpl, &key.PublicKey, key)
	if err != nil {
		t.Fatal(err)
	}
	certPEM = pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: der})
	keyDER, _ := x509.MarshalPKCS8PrivateKey(key)
	keyPEM = pem.EncodeToMemory(&pem.Block{Type: "PRIVATE KEY", Bytes: keyDER})
	return certPEM, keyPEM
}

func TestNeedsRenewal(t *testing.T) {
	now := time.Now()
	day := 24 * time.Hour
	cases := []struct {
		name          string
		before, after time.Time
		wantDue       bool
	}{
		{"fresh 11pct", now.Add(-10 * day), now.Add(80 * day), false},
		{"just past half", now.Add(-46 * day), now.Add(44 * day), true},
		{"well past half", now.Add(-80 * day), now.Add(10 * day), true},
		{"degenerate window", now, now, true},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			certPEM, _ := selfSigned(t, "x", tc.before, tc.after)
			due, err := NeedsRenewal(certPEM, RenewalFraction)
			if err != nil {
				t.Fatalf("NeedsRenewal: %v", err)
			}
			if due != tc.wantDue {
				t.Fatalf("due = %v, erwartet %v", due, tc.wantDue)
			}
		})
	}
}

func TestNeedsRenewalRejectsGarbage(t *testing.T) {
	if _, err := NeedsRenewal([]byte("nope"), RenewalFraction); err == nil {
		t.Fatal("erwartet Fehler bei Nicht-PEM")
	}
}

func TestServerClientFallsBackWhenNotProvisioned(t *testing.T) {
	dir := t.TempDir() // empty -> not provisioned
	client, err := ServerClient(dir, "", true, time.Second)
	if err != nil || client == nil {
		t.Fatalf("Fallback-Client erwartet, err=%v", err)
	}
}

func TestServerClientUsesIdentityWhenProvisioned(t *testing.T) {
	dir := t.TempDir()
	now := time.Now()
	certPEM, keyPEM := selfSigned(t, "agent", now.Add(-time.Hour), now.Add(time.Hour))
	mustWrite(t, CertPath(dir), certPEM)
	mustWrite(t, KeyPath(dir), keyPEM)
	mustWrite(t, CAPath(dir), certPEM) // any valid CA bundle
	if !Provisioned(dir) {
		t.Fatal("sollte provisioned sein")
	}
	client, err := ServerClient(dir, "", false, time.Second)
	if err != nil || client == nil {
		t.Fatalf("mTLS-Client erwartet, err=%v", err)
	}
}

// TestRenewSwapsIdentity drives a real renewal against a TLS test server: the
// agent presents its current cert (mTLS), the server returns a new fullchain,
// and Renew must persist it (new key + cert).
func TestRenewSwapsIdentity(t *testing.T) {
	dir := t.TempDir()
	now := time.Now()
	certPEM, keyPEM := selfSigned(t, "agent", now.Add(-time.Hour), now.Add(time.Hour))
	mustWrite(t, CertPath(dir), certPEM)
	mustWrite(t, KeyPath(dir), keyPEM)

	// Enforce mTLS: the server must actually demand + verify the agent's client cert, so a
	// regression where the client stops presenting it (or falls into the legacy fallback) fails the
	// handshake instead of staying green (6.13). The agent cert is self-signed, so it is its own
	// client CA.
	pool := x509.NewCertPool()
	if !pool.AppendCertsFromPEM(certPEM) {
		t.Fatal("Agent-Cert nicht als Client-CA ladbar")
	}
	srv := httptest.NewUnstartedServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/ca/renew" {
			t.Errorf("Pfad = %q, erwartet /ca/renew", r.URL.Path)
		}
		if len(r.TLS.PeerCertificates) == 0 {
			t.Error("Server sah kein Client-Zertifikat (mTLS nicht präsentiert)")
		}
		var body RenewRequest
		_ = json.NewDecoder(r.Body).Decode(&body)
		if body.CSR == "" {
			t.Error("CSR fehlt im Renew-Body")
		}
		_ = json.NewEncoder(w).Encode(IssueResponse{
			Cert: "new-leaf", Fullchain: "new-leaf+int", Chain: "int+root",
		})
	}))
	srv.TLS = &tls.Config{ClientAuth: tls.RequireAndVerifyClientCert, ClientCAs: pool}
	srv.StartTLS()
	defer srv.Close()

	// Trust the test server's own cert (so the client verifies it under custom-root).
	srvCertPEM := pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: srv.Certificate().Raw})
	mustWrite(t, CAPath(dir), srvCertPEM)

	if err := Renew(context.Background(), dir, srv.URL, 5*time.Second); err != nil {
		t.Fatalf("Renew: %v", err)
	}

	if got, _ := os.ReadFile(CertPath(dir)); string(got) != "new-leaf+int" {
		t.Fatalf("agent.crt = %q, erwartet new-leaf+int", string(got))
	}
	if got, _ := os.ReadFile(KeyPath(dir)); string(got) == string(keyPEM) {
		t.Fatal("Key wurde nicht rotiert")
	}
}

// The ctx of a run ends a renewal whose request the issuer holds, long before the
// client's timeout, and the stored identity stays as it was.
func TestRenewEndsWithTheContext(t *testing.T) {
	dir := t.TempDir()
	now := time.Now()
	certPEM, keyPEM := selfSigned(t, "agent", now.Add(-time.Hour), now.Add(time.Hour))
	mustWrite(t, CertPath(dir), certPEM)
	mustWrite(t, KeyPath(dir), keyPEM)

	pool := x509.NewCertPool()
	if !pool.AppendCertsFromPEM(certPEM) {
		t.Fatal("agent cert not loadable as a client CA")
	}
	arrived := make(chan struct{}, 1)
	release := make(chan struct{})
	srv := httptest.NewUnstartedServer(http.HandlerFunc(func(http.ResponseWriter, *http.Request) {
		select {
		case arrived <- struct{}{}:
		default:
		}
		// Released when the test ends; the empty answer is no identity to store.
		<-release
	}))
	srv.TLS = &tls.Config{ClientAuth: tls.RequireAndVerifyClientCert, ClientCAs: pool}
	srv.StartTLS()
	defer srv.Close()
	defer close(release) // runs first: Close waits for the held handler
	srvCertPEM := pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: srv.Certificate().Raw})
	mustWrite(t, CAPath(dir), srvCertPEM)

	files := []string{KeyPath(dir), CertPath(dir), CAPath(dir)}
	before := make([][]byte, len(files))
	for i, p := range files {
		data, err := os.ReadFile(p)
		if err != nil {
			t.Fatal(err)
		}
		before[i] = data
	}

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	res := make(chan error, 1)
	go func() { res <- Renew(ctx, dir, srv.URL, 30*time.Second) }()
	select {
	case <-arrived:
	case <-time.After(10 * time.Second):
		t.Fatal("the renewal request did not reach the issuer")
	}
	cancel()
	select {
	case err := <-res:
		if !errors.Is(err, context.Canceled) {
			t.Fatalf("want an error that wraps context.Canceled, got %v", err)
		}
	case <-time.After(2 * time.Second):
		t.Fatal("Renew did not end with its ctx (client timeout 30s)")
	}

	for i, p := range files {
		got, err := os.ReadFile(p)
		if err != nil {
			t.Fatal(err)
		}
		if string(got) != string(before[i]) {
			t.Errorf("%s changed by a renewal that ended with its ctx", filepath.Base(p))
		}
	}
}

// TestServerClientMTLSPresentationVsFallback proves the security-critical property directly: the
// provisioned client presents its cert and is accepted by an mTLS-enforcing server, while the
// fallback (unprovisioned) client — which presents no client cert — is rejected at the handshake.
// A plain `client != nil` assertion cannot tell these two apart (6.13).
func TestServerClientMTLSPresentationVsFallback(t *testing.T) {
	dir := t.TempDir()
	now := time.Now()
	certPEM, keyPEM := selfSigned(t, "agent", now.Add(-time.Hour), now.Add(time.Hour))
	mustWrite(t, CertPath(dir), certPEM)
	mustWrite(t, KeyPath(dir), keyPEM)

	pool := x509.NewCertPool()
	if !pool.AppendCertsFromPEM(certPEM) {
		t.Fatal("Agent-Cert nicht als Client-CA ladbar")
	}
	srv := httptest.NewUnstartedServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusOK)
	}))
	srv.TLS = &tls.Config{ClientAuth: tls.RequireAndVerifyClientCert, ClientCAs: pool}
	srv.StartTLS()
	defer srv.Close()
	srvCertPEM := pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: srv.Certificate().Raw})
	mustWrite(t, CAPath(dir), srvCertPEM)

	// Provisioned client presents the agent cert -> accepted.
	client, err := ServerClient(dir, "", false, 5*time.Second)
	if err != nil {
		t.Fatalf("ServerClient (provisioned): %v", err)
	}
	resp, err := client.Get(srv.URL)
	if err != nil {
		t.Fatalf("provisionierter Client abgelehnt: %v", err)
	}
	resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		t.Fatalf("Status = %d, erwartet 200", resp.StatusCode)
	}

	// Fallback client (unprovisioned dir, insecure so it trusts the server cert) presents no client
	// cert -> the mTLS server rejects the handshake.
	fallback, err := ServerClient(t.TempDir(), "", true, 5*time.Second)
	if err != nil {
		t.Fatalf("ServerClient (fallback): %v", err)
	}
	if _, err := fallback.Get(srv.URL); err == nil {
		t.Fatal("Fallback-Client ohne Client-Cert wurde akzeptiert — erwartet Handshake-Fehler")
	}
}

func mustWrite(t *testing.T, path string, data []byte) {
	t.Helper()
	if err := os.WriteFile(path, data, 0600); err != nil {
		t.Fatal(err)
	}
}

func TestMaybeRenewSkipsWhenNotProvisioned(t *testing.T) {
	orig := renewFunc
	called := false
	renewFunc = func(context.Context, string, string, time.Duration) error { called = true; return nil }
	t.Cleanup(func() { renewFunc = orig })

	dir := filepath.Join(t.TempDir(), "identity")
	done, err := MaybeRenew(context.Background(), dir, "https://x", time.Second)
	if err != nil || done {
		t.Fatalf("not provisioned -> (false, nil), got (%v, %v)", done, err)
	}
	if called {
		t.Error("renewFunc darf bei nicht-provisioniert nicht laufen")
	}
	// No lock either: taking it would create the directory and the lock file.
	if _, err := os.Stat(dir); !os.IsNotExist(err) {
		t.Errorf("not provisioned -> no identity directory, Stat: %v", err)
	}
}

func TestMaybeRenewSkipsWhenNotDue(t *testing.T) {
	orig := renewFunc
	called := false
	renewFunc = func(context.Context, string, string, time.Duration) error { called = true; return nil }
	t.Cleanup(func() { renewFunc = orig })

	dir := t.TempDir()
	now := time.Now()
	day := 24 * time.Hour
	certPEM, keyPEM := selfSigned(t, "agent", now.Add(-10*day), now.Add(80*day)) // 11% through -> not due
	mustWrite(t, CertPath(dir), certPEM)
	mustWrite(t, KeyPath(dir), keyPEM)

	done, err := MaybeRenew(context.Background(), dir, "https://x", time.Second)
	if err != nil || done {
		t.Fatalf("not due -> (false, nil), got (%v, %v)", done, err)
	}
	if called {
		t.Error("renewFunc darf bei nicht-faelligem Cert nicht laufen")
	}
}

func TestMaybeRenewRenewsWhenDue(t *testing.T) {
	orig := renewFunc
	called := false
	renewFunc = func(context.Context, string, string, time.Duration) error { called = true; return nil }
	t.Cleanup(func() { renewFunc = orig })

	dir := t.TempDir()
	now := time.Now()
	day := 24 * time.Hour
	certPEM, keyPEM := selfSigned(t, "agent", now.Add(-80*day), now.Add(10*day)) // well past half -> due
	mustWrite(t, CertPath(dir), certPEM)
	mustWrite(t, KeyPath(dir), keyPEM)

	done, err := MaybeRenew(context.Background(), dir, "https://x", time.Second)
	if err != nil || !done {
		t.Fatalf("due -> (true, nil), got (%v, %v)", done, err)
	}
	if !called {
		t.Error("renewFunc muss bei faelligem Cert laufen")
	}
}

// R-0384: MaybeRenew holds the identity lock from reading the certificate to the
// commit, so it never interleaves with a provisioning and sees what one stored first.

type renewResult struct {
	done bool
	err  error
}

// maybeRenewBehindLock stores a due identity in dir, takes the identity lock and starts
// MaybeRenew, which must neither renew nor return while the lock is held. It returns
// MaybeRenew's result, the calls of renewFunc and the unlock of the held lock.
func maybeRenewBehindLock(t *testing.T, dir string) (<-chan renewResult, <-chan struct{}, func()) {
	t.Helper()
	orig := renewFunc
	renewed := make(chan struct{}, 1)
	renewFunc = func(context.Context, string, string, time.Duration) error { renewed <- struct{}{}; return nil }
	t.Cleanup(func() { renewFunc = orig })

	now := time.Now()
	day := 24 * time.Hour
	certPEM, keyPEM := selfSigned(t, "agent", now.Add(-80*day), now.Add(10*day)) // due
	mustWrite(t, CertPath(dir), certPEM)
	mustWrite(t, KeyPath(dir), keyPEM)

	unlock, err := LockIdentity(context.Background(), dir)
	if err != nil {
		t.Fatalf("LockIdentity: %v", err)
	}
	res := make(chan renewResult, 1)
	go func() {
		done, err := MaybeRenew(context.Background(), dir, "https://x", time.Second)
		res <- renewResult{done, err}
	}()
	select {
	case <-renewed:
		unlock()
		t.Fatal("MaybeRenew renewed while the identity lock was held")
	case r := <-res:
		unlock()
		t.Fatalf("MaybeRenew returned (%v, %v) while the identity lock was held", r.done, r.err)
	case <-time.After(500 * time.Millisecond):
	}
	return res, renewed, unlock
}

func awaitRenewResult(t *testing.T, res <-chan renewResult) renewResult {
	t.Helper()
	select {
	case r := <-res:
		return r
	case <-time.After(10 * time.Second):
		t.Fatal("MaybeRenew did not return after the identity lock was released")
		return renewResult{}
	}
}

func TestMaybeRenewWaitsForTheIdentityLock(t *testing.T) {
	res, renewed, unlock := maybeRenewBehindLock(t, t.TempDir())
	unlock()
	if r := awaitRenewResult(t, res); r.err != nil || !r.done {
		t.Fatalf("after unlock -> (true, nil), got (%v, %v)", r.done, r.err)
	}
	select {
	case <-renewed:
	default:
		t.Fatal("MaybeRenew reported a renewal without calling renewFunc")
	}
}

// What a provisioning that holds the lock first leaves behind is what MaybeRenew
// checks: it reads the identity only under the lock.
func TestMaybeRenewChecksTheIdentityUnderTheLock(t *testing.T) {
	cases := []struct {
		name   string
		change func(t *testing.T, dir string)
	}{
		{"a fresh identity was stored", func(t *testing.T, dir string) {
			now := time.Now()
			day := 24 * time.Hour
			certPEM, keyPEM := selfSigned(t, "agent", now.Add(-10*day), now.Add(80*day)) // not due
			mustWrite(t, CertPath(dir), certPEM)
			mustWrite(t, KeyPath(dir), keyPEM)
		}},
		{"the identity was removed", func(t *testing.T, dir string) {
			if err := RemoveIdentity(dir); err != nil {
				t.Fatalf("RemoveIdentity: %v", err)
			}
		}},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			dir := t.TempDir()
			res, renewed, unlock := maybeRenewBehindLock(t, dir)
			tc.change(t, dir)
			unlock()
			if r := awaitRenewResult(t, res); r.err != nil || r.done {
				t.Fatalf("after unlock -> (false, nil), got (%v, %v)", r.done, r.err)
			}
			select {
			case <-renewed:
				t.Fatal("MaybeRenew renewed an identity it had read before the lock")
			default:
			}
		})
	}
}

// A lock that is not released holds up the service cycle for the wait of
// LockIdentity at most, and only when the identity is due.

// recordRenewals swaps renewFunc for one that counts its calls; read the count only
// after MaybeRenew has returned.
func recordRenewals(t *testing.T) *int {
	t.Helper()
	orig := renewFunc
	calls := new(int)
	renewFunc = func(context.Context, string, string, time.Duration) error { *calls++; return nil }
	t.Cleanup(func() { renewFunc = orig })
	return calls
}

// storeIdentityAt writes a key and a cert into dir that is due for renewal or not.
func storeIdentityAt(t *testing.T, dir string, due bool) {
	t.Helper()
	now := time.Now()
	day := 24 * time.Hour
	notBefore, notAfter := now.Add(-10*day), now.Add(80*day) // 11% through -> not due
	if due {
		notBefore, notAfter = now.Add(-80*day), now.Add(10*day)
	}
	certPEM, keyPEM := selfSigned(t, "agent", notBefore, notAfter)
	mustWrite(t, CertPath(dir), certPEM)
	mustWrite(t, KeyPath(dir), keyPEM)
}

func TestMaybeRenewDoesNotLockAnIdentityThatIsNotDue(t *testing.T) {
	shortenLockWait(t, 300*time.Millisecond)
	renewals := recordRenewals(t)
	dir := t.TempDir()
	storeIdentityAt(t, dir, false)
	unlock, err := LockIdentity(context.Background(), dir)
	if err != nil {
		t.Fatalf("LockIdentity: %v", err)
	}
	defer unlock()

	// Had it waited for the held lock, it would return the error of LockIdentity.
	done, err := MaybeRenew(context.Background(), dir, "https://x", time.Second)
	if err != nil || done {
		t.Fatalf("not due, lock held -> (false, nil), got (%v, %v)", done, err)
	}
	if *renewals != 0 {
		t.Errorf("renewFunc ran %d times for an identity that is not due", *renewals)
	}
}

func TestMaybeRenewGivesUpOnAnIdentityLockThatIsNotReleased(t *testing.T) {
	shortenLockWait(t, 300*time.Millisecond)
	renewals := recordRenewals(t)
	dir := t.TempDir()
	storeIdentityAt(t, dir, true)
	unlock, err := LockIdentity(context.Background(), dir)
	if err != nil {
		t.Fatalf("LockIdentity: %v", err)
	}
	defer unlock()

	res := make(chan renewResult, 1)
	go func() {
		done, err := MaybeRenew(context.Background(), dir, "https://x", time.Second)
		res <- renewResult{done, err}
	}()
	select {
	case r := <-res:
		if r.err == nil || r.done {
			t.Fatalf("lock not released -> (false, error), got (%v, %v)", r.done, r.err)
		}
		if lockFile := filepath.Join(dir, LockFileName); !strings.Contains(r.err.Error(), lockFile) {
			t.Fatalf("the error does not name the lock file %s: %v", lockFile, r.err)
		}
	case <-time.After(10 * time.Second):
		t.Fatal("MaybeRenew did not give up on the held identity lock")
	}
	if *renewals != 0 {
		t.Errorf("renewFunc ran %d times without the identity lock", *renewals)
	}
}

func TestMaybeRenewReportsAnIdentityLockItCannotTake(t *testing.T) {
	renewals := recordRenewals(t)
	dir := t.TempDir()
	storeIdentityAt(t, dir, true)
	if err := os.Mkdir(filepath.Join(dir, LockFileName), 0700); err != nil {
		t.Fatal(err)
	}

	done, err := MaybeRenew(context.Background(), dir, "https://x", time.Second)
	if err == nil || done {
		t.Fatalf("lock file unusable -> (false, error), got (%v, %v)", done, err)
	}
	if *renewals != 0 {
		t.Errorf("renewFunc ran %d times without the identity lock", *renewals)
	}
}

// The ctx of a run ends MaybeRenew's wait for a held lock, long before the wait of
// LockIdentity, and nothing is renewed.
func TestMaybeRenewLockEndsWithTheContext(t *testing.T) {
	renewals := recordRenewals(t)
	dir := t.TempDir()
	storeIdentityAt(t, dir, true)
	unlock, err := LockIdentity(context.Background(), dir)
	if err != nil {
		t.Fatalf("LockIdentity: %v", err)
	}
	defer unlock()

	ctx, cancel := context.WithTimeout(context.Background(), 100*time.Millisecond)
	defer cancel()
	res := make(chan renewResult, 1)
	go func() {
		done, err := MaybeRenew(ctx, dir, "https://x", time.Second)
		res <- renewResult{done, err}
	}()
	select {
	case r := <-res:
		if r.err == nil || r.done {
			t.Fatalf("ctx ended, lock held -> (false, error), got (%v, %v)", r.done, r.err)
		}
		if !errors.Is(r.err, context.DeadlineExceeded) {
			t.Fatalf("want an error that wraps context.DeadlineExceeded, got %v", r.err)
		}
	case <-time.After(2 * time.Second):
		t.Fatalf("MaybeRenew did not end with its ctx (identityLockWait %s)", identityLockWait)
	}
	if *renewals != 0 {
		t.Errorf("renewFunc ran %d times without the identity lock", *renewals)
	}
}

func TestLeafExpired(t *testing.T) {
	now := time.Now()

	valid, _ := selfSigned(t, "agent", now.Add(-time.Hour), now.Add(time.Hour))
	if exp, _, err := leafExpired(valid); err != nil || exp {
		t.Errorf("gueltiges Leaf: expired=%v err=%v, want false/nil", exp, err)
	}

	stale, _ := selfSigned(t, "agent", now.Add(-2*time.Hour), now.Add(-time.Hour))
	exp, notAfter, err := leafExpired(stale)
	if err != nil || !exp {
		t.Errorf("abgelaufenes Leaf: expired=%v err=%v, want true/nil", exp, err)
	}
	if notAfter.After(now) {
		t.Errorf("abgelaufenes Leaf: notAfter %v sollte in der Vergangenheit liegen", notAfter)
	}

	if _, _, err := leafExpired([]byte("kein PEM")); err == nil {
		t.Error("Muell-PEM: want error, got nil")
	}
}

// R-0385: a due renewal holds the identity lock and removes what an interrupted one left;
// an identity that is not due takes no lock and touches nothing.
func TestStaleTempsRemovedByMaybeRenew(t *testing.T) {
	orig := renewFunc
	renewFunc = func(context.Context, string, string, time.Duration) error { return nil }
	t.Cleanup(func() { renewFunc = orig })
	now := time.Now()
	day := 24 * time.Hour
	for name, c := range map[string]struct {
		notBefore, notAfter time.Time
		removed             bool
	}{
		"due":     {now.Add(-80 * day), now.Add(10 * day), true},
		"not due": {now.Add(-1 * day), now.Add(89 * day), false},
	} {
		dir := t.TempDir()
		certPEM, keyPEM := selfSigned(t, "agent", c.notBefore, c.notAfter)
		mustWrite(t, CertPath(dir), certPEM)
		mustWrite(t, KeyPath(dir), keyPEM)
		stale := filepath.Join(dir, "agent.key.77.tmp")
		mustWrite(t, stale, []byte("x"))

		if _, err := MaybeRenew(context.Background(), dir, "https://x", time.Second); err != nil {
			t.Fatalf("%s: %v", name, err)
		}
		if _, err := os.Lstat(stale); os.IsNotExist(err) != c.removed {
			t.Errorf("%s: stale staged file removed %v, want %v", name, os.IsNotExist(err), c.removed)
		}
	}
}
