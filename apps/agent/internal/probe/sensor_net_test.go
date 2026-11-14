// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package probe

import (
	"context"
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/rand"
	"crypto/tls"
	"crypto/x509"
	"crypto/x509/pkix"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"math/big"
	"net"
	"net/http"
	"net/http/httptest"
	"strconv"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"
)

func TestTheNetworkSensorsAreRegistered(t *testing.T) {
	for _, name := range []string{"http", "tls", "proto", "unixsocket", "dns"} {
		if sensors[name] == nil {
			t.Errorf("sensor %s is not registered", name)
		}
	}
}

// portOf is the port of a test server's address or URL.
func portOf(t *testing.T, addr string) int {
	t.Helper()
	_, port, err := net.SplitHostPort(strings.TrimPrefix(strings.TrimPrefix(addr, "http://"), "https://"))
	if err != nil {
		t.Fatal(err)
	}
	n, err := strconv.Atoi(port)
	if err != nil {
		t.Fatal(err)
	}
	return n
}

// onLoopback is a probe of sensor on 127.0.0.1:port.
func onLoopback(sensor string, port int, params map[string]any, fields ...string) Probe {
	return Probe{Sensor: sensor, Target: &Target{Kind: kindLoopback, PortHint: port}, Params: params, Fields: fields}
}

func TestTheTCPSensorsDialThroughTheGuard(t *testing.T) {
	for _, p := range []Probe{
		onLoopback("http", 0, nil),
		onLoopback("tls", 0, nil),
		onLoopback("proto", 0, map[string]any{"protocol": "smtp"}),
		onLoopback("proto", 0, map[string]any{"protocol": "auto"}),
		onLoopback("dns", 0, map[string]any{"name": "localhost"}),
	} {
		t.Run(fmt.Sprint(p.Sensor, p.Params), func(t *testing.T) {
			srv := listen(t, func(c *fakeConn) { c.f.record("accepted") })
			stubHost(t, &fakeHost{
				list:  []listener{lst("127.0.0.1", uint16(srv.port()), 15)},
				names: map[int32]string{15: "dockerd"},
			})
			p.Target.PortHint = srv.port()
			got, err := sensors[p.Sensor](context.Background(), p, "")
			if !errors.Is(err, ErrNotAllowed) {
				t.Errorf("a port of dockerd = %v, %v; want ErrNotAllowed", got, err)
			}
			if heard := srv.close(); len(heard) != 0 {
				t.Errorf("the server heard %v", heard)
			}
		})
	}
}

func TestHTTPSensorReadsStatusTimeAndData(t *testing.T) {
	var mu sync.Mutex
	var methods []string
	srv := localServer(t, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		mu.Lock()
		methods = append(methods, r.Method+" "+r.URL.RequestURI())
		mu.Unlock()
		switch r.URL.Path {
		case "/health":
			_, _ = fmt.Fprint(w, `{"status":"ok","queue":{"depth":3},"ratio":0.5}`)
		case "/text":
			_, _ = fmt.Fprint(w, "all good")
		case "/two":
			_, _ = fmt.Fprint(w, `{"a":1} {"b":2}`)
		case "/down":
			w.WriteHeader(http.StatusServiceUnavailable)
		case "/secret":
			w.WriteHeader(http.StatusUnauthorized)
		case "/forbidden":
			w.WriteHeader(http.StatusForbidden)
		case "/away":
			http.Redirect(w, r, "http://192.0.2.1/", http.StatusFound)
		}
	}))
	ctx := context.Background()
	port := portOf(t, srv.URL)
	probe := func(params map[string]any, fields ...string) (map[string]any, error) {
		return httpSensor(ctx, onLoopback("http", port, params, fields...), "")
	}

	got, err := probe(map[string]any{"path": "/health?full=1"}, "status_code", "data.queue.depth")
	data, _ := got["data"].(map[string]any)
	queue, _ := data["queue"].(map[string]any)
	if err != nil || got["status_code"] != 200 || queue["depth"] != json.Number("3") || data["status"] != "ok" {
		t.Fatalf("GET /health = %v, %v; want 200 and the JSON object with its numbers as json.Number", got, err)
	}
	if took, ok := got["duration_ms"].(int64); !ok || took < 0 {
		t.Errorf("duration_ms = %#v, want milliseconds", got["duration_ms"])
	}
	if got, err := probe(map[string]any{"path": "/health"}, "status_code"); err != nil || got["data"] != nil || got["status_code"] != 200 {
		t.Errorf("GET without a data field = %v, %v; want no data", got, err)
	}
	if got, err := probe(map[string]any{"path": "/health", "method": "HEAD"}, "data.status"); err != nil || got["data"] != nil || got["status_code"] != 200 {
		t.Errorf("HEAD = %v, %v; want the status without data", got, err)
	}
	for _, path := range []string{"/text", "/two"} {
		if _, err := probe(map[string]any{"path": path}, "data.status"); err == nil || err.Error() != "the answer is no JSON object" {
			t.Errorf("data of %s = %v, want no JSON object", path, err)
		}
	}
	if got, err := probe(map[string]any{"path": "/down"}, "status_code"); err != nil || got["status_code"] != 503 {
		t.Errorf("GET /down = %v, %v; want the status 503 as a value", got, err)
	}
	for _, path := range []string{"/secret", "/forbidden"} {
		if _, err := probe(map[string]any{"path": path}); !errors.Is(err, ErrDenied) || !strings.Contains(err.Error(), "HTTP 40") {
			t.Errorf("GET %s = %v, want ErrDenied", path, err)
		}
	}
	if _, err := probe(map[string]any{"path": "/away"}); !errors.Is(err, ErrNotAllowed) {
		t.Errorf("a redirect to another host = %v, want ErrNotAllowed", err)
	}
	if got, err := probe(nil); err != nil || got["status_code"] != 200 {
		t.Errorf("no params = %v, %v; want GET /", got, err)
	}
	if _, err := probe(map[string]any{"path": "//192.0.2.1/x"}); err != nil {
		t.Errorf("a path like a URL = %v, want it sent to the target", err)
	}

	mu.Lock()
	defer mu.Unlock()
	want := "GET /health?full=1,GET /health,HEAD /health,GET /text,GET /two,GET /down,GET /secret,GET /forbidden,GET /away,GET /,GET //192.0.2.1/x"
	if strings.Join(methods, ",") != want {
		t.Errorf("the server saw %v\nwant %s", methods, want)
	}
}

func TestHTTPSensorComparesAShortAnswerWithoutSendingIt(t *testing.T) {
	srv := localServer(t, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/true":
			_, _ = fmt.Fprint(w, " true\r\n")
		case "/false":
			_, _ = fmt.Fprint(w, "false")
		case "/json":
			_, _ = fmt.Fprint(w, `{"status":"true"}`)
		case "/long":
			_, _ = fmt.Fprint(w, "true"+strings.Repeat(" ", maxExpectBody))
		case "/edge":
			_, _ = fmt.Fprint(w, "true"+strings.Repeat(" ", maxExpectBody-4))
		case "/down":
			w.WriteHeader(http.StatusServiceUnavailable)
			_, _ = fmt.Fprint(w, "true")
		}
	}))
	ctx := context.Background()
	port := portOf(t, srv.URL)
	probe := func(path, expect string, fields ...string) (map[string]any, error) {
		return httpSensor(ctx, onLoopback("http", port, map[string]any{"path": path, "expect": expect}, fields...), "")
	}

	for _, c := range []struct {
		path string
		want bool
	}{{"/true", true}, {"/false", false}, {"/json", false}, {"/long", false}, {"/edge", true}, {"/down", true}} {
		got, err := probe(c.path, "true", "status_code", "body_match")
		if err != nil || got["body_match"] != c.want {
			t.Errorf("%s = %v, %v; want body_match %v", c.path, got, err, c.want)
		}
		for k, v := range got {
			if s, ok := v.(string); ok || (k != "status_code" && k != "duration_ms" && k != "body_match" && k != "tls") {
				t.Errorf("%s: value %s = %#v, want no part of the body", c.path, k, s)
			}
		}
	}
	got, err := probe("/json", "OK", "data.status", "body_match")
	data, _ := got["data"].(map[string]any)
	if err != nil || got["body_match"] != false || data["status"] != "true" {
		t.Errorf("expect with data = %v, %v; want both from one answer", got, err)
	}

	for _, c := range []struct {
		name   string
		params map[string]any
		fields []string
	}{
		{"an empty expect", map[string]any{"expect": ""}, nil},
		{"an expect with a space", map[string]any{"expect": "all good"}, nil},
		{"an expect with a control character", map[string]any{"expect": "ok\n"}, nil},
		{"a long expect", map[string]any{"expect": strings.Repeat("ä", 65)}, nil},
		{"an expect of another type", map[string]any{"expect": true}, nil},
		{"an expect with HEAD", map[string]any{"expect": "true", "method": "HEAD"}, nil},
		{"body_match without expect", nil, []string{"body_match"}},
	} {
		if _, err := httpSensor(ctx, onLoopback("http", port, c.params, c.fields...), ""); !errors.Is(err, ErrInvalid) {
			t.Errorf("%s: %v, want ErrInvalid", c.name, err)
		}
	}
	if _, err := probe("/true", strings.Repeat("ä", 64), "body_match"); err != nil {
		t.Errorf("an expect of 64 characters = %v, want it taken", err)
	}
}

func TestHTTPSensorPresentsItsCredential(t *testing.T) {
	headers := make(chan http.Header, 1)
	srv := localServer(t, http.HandlerFunc(func(_ http.ResponseWriter, r *http.Request) { headers <- r.Header.Clone() }))
	ctx := context.Background()
	port := portOf(t, srv.URL)
	probe := func(use, secret string) error {
		p := onLoopback("http", port, nil)
		p.Credential = &Credential{Ref: "c1", Use: use}
		_, err := httpSensor(ctx, p, secret)
		return err
	}

	for _, c := range []struct{ use, secret, header, want string }{
		{"bearer", "s3cret", "Authorization", "Bearer s3cret"},
		{"basic", "admin:pa:ss", "Authorization", "Basic YWRtaW46cGE6c3M="},
		{"header:X-Api-Key", "s3cret", "X-Api-Key", "s3cret"},
	} {
		if err := probe(c.use, c.secret); err != nil {
			t.Fatalf("%s: %v", c.use, err)
		}
		if h := <-headers; h.Get(c.header) != c.want {
			t.Errorf("%s: header %s = %q, want %q", c.use, c.header, h.Get(c.header), c.want)
		}
	}
	for _, use := range []string{"basic", "header:X Api", "header:", "header:" + strings.Repeat("a", 65), "redis_auth", "Bearer"} {
		err := probe(use, "s3cret-without-colon")
		if !errors.Is(err, ErrInvalid) || strings.Contains(err.Error(), "s3cret") {
			t.Errorf("use %q = %v, want ErrInvalid without the secret", use, err)
		}
	}
	if len(headers) != 0 {
		t.Error("a refused credential still sent a request")
	}
}

// TestHTTPSensorSendsACredentialOnlyToItsTarget: with a credential the guard asks for the target's
// own listener on a fresh snapshot; a port docker forwards to a container is refused, without one it
// is probed as before (R-1425).
func TestHTTPSensorSendsACredentialOnlyToItsTarget(t *testing.T) {
	var hits atomic.Int32
	h := &fakeHost{live: true}
	stubHost(t, h)
	srv := httptest.NewServer(http.HandlerFunc(func(http.ResponseWriter, *http.Request) { hits.Add(1) }))
	t.Cleanup(srv.Close)
	port := portOf(t, srv.URL)
	h.pubs = []publication{{hostPort: uint16(port), to: 8080}}
	p := Probe{Sensor: "http", Target: &Target{Kind: kindPort, PortHint: port}}
	ctx := context.Background()

	if got, err := httpSensor(ctx, p, ""); err != nil || got["status_code"] != 200 {
		t.Fatalf("no credential = %v, %v; want the port probed", got, err)
	}
	p.Credential = &Credential{Ref: "c1", Use: "bearer"}
	_, err := httpSensor(ctx, p, "s3cret")
	if !errors.Is(err, ErrNotAllowed) || strings.Contains(err.Error(), "s3cret") {
		t.Fatalf("a credential to a published port = %v, want ErrNotAllowed without the secret", err)
	}
	if hits.Load() != 1 {
		t.Errorf("the server saw %d requests, want only the one without a credential", hits.Load())
	}
}

func TestHTTPSensorAsksAsLocalhostOnlyWhenTold(t *testing.T) {
	var mu sync.Mutex
	var hosts []string
	srv := localServer(t, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		mu.Lock()
		hosts = append(hosts, r.URL.Path+" "+r.Host)
		mu.Unlock()
		switch r.URL.Path {
		case "/hop":
			http.Redirect(w, r, "/end", http.StatusFound)
		case "/away":
			http.Redirect(w, r, "http://192.0.2.1/", http.StatusFound)
		case "/named":
			// The same listener under the name the param sends: the redirect names another target
			// than the one the probe asked, so the param widens no redirect.
			a, _ := r.Context().Value(http.LocalAddrContextKey).(*net.TCPAddr)
			http.Redirect(w, r, fmt.Sprintf("http://localhost:%d/end", a.Port), http.StatusFound)
		}
	}))
	ctx := context.Background()
	port := portOf(t, srv.URL)
	asLocalhost := map[string]any{"host": "localhost"}
	probe := func(path string, params map[string]any) error {
		p := map[string]any{"path": path}
		for k, v := range params {
			p[k] = v
		}
		_, err := httpSensor(ctx, onLoopback("http", port, p), "")
		return err
	}

	if err := probe("/plain", nil); err != nil {
		t.Fatal(err)
	}
	if err := probe("/asked", asLocalhost); err != nil {
		t.Fatal(err)
	}
	if err := probe("/hop", asLocalhost); err != nil {
		t.Fatalf("a redirect on the target = %v", err)
	}
	for _, path := range []string{"/away", "/named"} {
		if err := probe(path, asLocalhost); !errors.Is(err, ErrNotAllowed) {
			t.Errorf("%s: a redirect to another target = %v, want ErrNotAllowed", path, err)
		}
	}

	mu.Lock()
	defer mu.Unlock()
	addr := "127.0.0.1:" + strconv.Itoa(port)
	want := "/plain " + addr + ",/asked localhost,/hop localhost,/end localhost,/away localhost,/named localhost"
	if strings.Join(hosts, ",") != want {
		t.Errorf("the server saw %v\nwant %s", hosts, want)
	}
}

func TestHTTPSensorTakesOnlyWhatItCanSend(t *testing.T) {
	ctx := context.Background()
	for _, c := range []struct {
		name string
		p    Probe
	}{
		{"POST", onLoopback("http", 8080, map[string]any{"method": "POST"})},
		{"a method of another type", onLoopback("http", 8080, map[string]any{"method": 42})},
		{"a path without slash", onLoopback("http", 8080, map[string]any{"path": "health"})},
		{"a path with a space", onLoopback("http", 8080, map[string]any{"path": "/a b"})},
		{"a long path", onLoopback("http", 8080, map[string]any{"path": "/" + strings.Repeat("ä", 512)})},
		{"an empty path", onLoopback("http", 8080, map[string]any{"path": ""})},
		{"another param", onLoopback("http", 8080, map[string]any{"body": "x"})},
		{"a host of a site", onLoopback("http", 8080, map[string]any{"host": "example.org"})},
		{"an empty host", onLoopback("http", 8080, map[string]any{"host": ""})},
		{"localhost with a port", onLoopback("http", 8080, map[string]any{"host": "localhost:80"})},
		{"a host of another type", onLoopback("http", 8080, map[string]any{"host": 1})},
		{"a scheme of another protocol", Probe{Sensor: "http", Target: &Target{Kind: kindLoopback, PortHint: 8080, Scheme: "ftp"}}},
		{"no target", Probe{Sensor: "http"}},
	} {
		if _, err := httpSensor(ctx, c.p, ""); !errors.Is(err, ErrInvalid) {
			t.Errorf("%s: %v, want ErrInvalid", c.name, err)
		}
	}
}

func TestHTTPSensorSpeaksHTTPSWithoutCheckingTheCertificate(t *testing.T) {
	stubHost(t, &fakeHost{live: true})
	ctx := context.Background()
	p := onLoopback("http", quietHTTPS(t, newPKI(t).chain), nil)

	p.Target.Scheme = "https"
	if got, err := httpSensor(ctx, p, ""); err != nil || got["status_code"] != 200 {
		t.Errorf("https = %v, %v; want 200 despite a certificate of an unknown root", got, err)
	}
	p.Target.Scheme = "http"
	if got, err := httpSensor(ctx, p, ""); err != nil || got["status_code"] != 400 || got["tls"] != false {
		t.Errorf("http to a server of https = %v, %v; want its 400 without tls", got, err)
	}
}

func TestHTTPSensorAsksThePortWhetherItSpeaksTLS(t *testing.T) {
	ctx := context.Background()
	plain := portOf(t, localServer(t, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, _ = fmt.Fprint(w, "ok")
	})).URL)
	secure := quietHTTPS(t, newPKI(t).chain)
	for _, c := range []struct {
		name   string
		port   int
		scheme string
		tls    bool
	}{{"plain text", plain, "auto", false}, {"TLS", secure, "auto", true}, {"https", secure, "https", true}, {"no scheme", plain, "", false}} {
		p := onLoopback("http", c.port, map[string]any{"expect": "ok"}, "status_code", "tls")
		p.Target.Scheme = c.scheme
		got, err := httpSensor(ctx, p, "")
		if err != nil || got["status_code"] != 200 || got["tls"] != c.tls {
			t.Errorf("%s = %v, %v; want 200 with tls %v", c.name, got, err, c.tls)
		}
	}
}

// rawServer accepts connections on loopback and hands each to serve.
func rawServer(t *testing.T, serve func(net.Conn)) int {
	t.Helper()
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = ln.Close() })
	go func() {
		for {
			c, err := ln.Accept()
			if err != nil {
				return
			}
			go func() { defer c.Close(); serve(c) }()
		}
	}()
	return ln.Addr().(*net.TCPAddr).Port
}

// readHello reads the client's whole first TLS record before a server answers: closing with
// unread data makes Windows reset the connection, and the reset drops the answer at the client.
func readHello(c net.Conn) {
	head := make([]byte, 5)
	if _, err := io.ReadFull(c, head); err != nil {
		return
	}
	_, _ = io.CopyN(io.Discard, c, int64(head[3])<<8|int64(head[4]))
}

func TestSpeaksTLSTellsAServerOfPlainTextByItsAnswerOrSilence(t *testing.T) {
	stubHost(t, &fakeHost{live: true})
	ctx := context.Background()
	// Each server starts after the last snapshot of the listeners: age it, or the guard sees none.
	age := func() {
		snapshot.Lock()
		snapshot.at = snapshot.at.Add(-2 * listenerFresh)
		snapshot.Unlock()
	}
	check := func(port int) (bool, error) {
		age()
		ep, err := resolve(ctx, Target{Kind: kindLoopback, PortHint: port})
		if err != nil {
			t.Fatal(err)
		}
		return speaksTLS(ctx, NewGuard(ep.extra...), ep)
	}
	for _, c := range []struct {
		name  string
		serve func(net.Conn)
		want  bool
	}{
		{"an answer of HTTP", func(c net.Conn) {
			readHello(c)
			_, _ = c.Write([]byte("HTTP/1.1 400 Bad Request\r\n\r\n"))
		}, false},
		{"silence", func(c net.Conn) { _, _ = io.Copy(io.Discard, c) }, false},
		{"a closed connection", func(c net.Conn) { _, _ = c.Read(make([]byte, 16)) }, true},
		{"an alert", func(c net.Conn) {
			readHello(c)
			_, _ = c.Write([]byte{21, 3, 3, 0, 2, 2, 40})
		}, true},
	} {
		got, err := check(rawServer(t, c.serve))
		if err != nil || got != c.want {
			t.Errorf("%s = %v, %v; want %v", c.name, got, err, c.want)
		}
	}

	short, cancel := context.WithTimeout(ctx, 200*time.Millisecond)
	defer cancel()
	port := rawServer(t, func(c net.Conn) { _, _ = io.Copy(io.Discard, c) })
	age()
	ep, _ := resolve(ctx, Target{Kind: kindLoopback, PortHint: port})
	if _, err := speaksTLS(short, NewGuard(ep.extra...), ep); !errors.Is(err, context.DeadlineExceeded) {
		t.Errorf("silence until the deadline = %v, want the probe's timeout", err)
	}
}

// testPKI is a root, an intermediate and a leaf for svc.example.org that expires 30.5 days after start.
type testPKI struct {
	roots *x509.CertPool
	// chain is the leaf with the intermediate, leafOnly the leaf alone.
	chain, leafOnly tls.Certificate
	leaf            *x509.Certificate
}

func newPKI(t *testing.T) testPKI {
	t.Helper()
	key := func() *ecdsa.PrivateKey {
		k, err := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
		if err != nil {
			t.Fatal(err)
		}
		return k
	}
	issue := func(tmpl, parent *x509.Certificate, pub, signer *ecdsa.PrivateKey) *x509.Certificate {
		der, err := x509.CreateCertificate(rand.Reader, tmpl, parent, &pub.PublicKey, signer)
		if err != nil {
			t.Fatal(err)
		}
		c, err := x509.ParseCertificate(der)
		if err != nil {
			t.Fatal(err)
		}
		return c
	}
	rootKey, interKey, leafKey := key(), key(), key()
	ca := func(serial int64, name string) *x509.Certificate {
		return &x509.Certificate{
			SerialNumber: big.NewInt(serial), Subject: pkix.Name{CommonName: name, Organization: []string{"AdminHelper"}},
			NotBefore: start.Add(-time.Hour), NotAfter: start.Add(365 * 24 * time.Hour),
			IsCA: true, BasicConstraintsValid: true, KeyUsage: x509.KeyUsageCertSign,
		}
	}
	root := issue(ca(1, "Test Root"), ca(1, "Test Root"), rootKey, rootKey)
	inter := issue(ca(2, "Test Intermediate"), root, interKey, rootKey)
	leaf := issue(&x509.Certificate{
		SerialNumber: big.NewInt(3), Subject: pkix.Name{CommonName: "svc.example.org"},
		DNSNames:  []string{"svc.example.org"},
		NotBefore: start.Add(-time.Hour), NotAfter: start.Add(30*24*time.Hour + 12*time.Hour),
		KeyUsage: x509.KeyUsageDigitalSignature, ExtKeyUsage: []x509.ExtKeyUsage{x509.ExtKeyUsageServerAuth},
	}, inter, leafKey, interKey)

	pki := testPKI{roots: x509.NewCertPool(), leaf: leaf}
	pki.roots.AddCert(root)
	pki.chain = tls.Certificate{Certificate: [][]byte{leaf.Raw, inter.Raw}, PrivateKey: leafKey}
	pki.leafOnly = tls.Certificate{Certificate: [][]byte{leaf.Raw}, PrivateKey: leafKey}
	return pki
}

// stubRoots lets chain_ok trust roots.
func stubRoots(t *testing.T, roots *x509.CertPool) {
	t.Helper()
	old := certRoots
	certRoots = roots
	t.Cleanup(func() { certRoots = old })
}

// tlsServer serves cert on 127.0.0.1, lets the guard's seams see the test's own listeners alone and
// returns its port and the server names the clients asked for.
func tlsServer(t *testing.T, cert tls.Certificate) (int, chan string) {
	t.Helper()
	stubHost(t, &fakeHost{live: true})
	names := make(chan string, 8)
	srv := httptest.NewUnstartedServer(http.HandlerFunc(func(http.ResponseWriter, *http.Request) {}))
	srv.TLS = &tls.Config{
		Certificates: []tls.Certificate{cert},
		GetConfigForClient: func(hello *tls.ClientHelloInfo) (*tls.Config, error) {
			names <- hello.ServerName
			return nil, nil
		},
	}
	srv.StartTLS()
	t.Cleanup(srv.Close)
	return portOf(t, srv.URL), names
}

func TestTLSSensorReadsTheCertificateOfTheServer(t *testing.T) {
	pki := newPKI(t)
	stubNow(t, start)
	stubRoots(t, pki.roots)
	ctx := context.Background()
	port, names := tlsServer(t, pki.chain)

	got, err := tlsSensor(ctx, onLoopback("tls", port, map[string]any{"server_name": "svc.example.org", "starttls": "none"}), "")
	if err != nil {
		t.Fatal(err)
	}
	want := map[string]any{
		"not_after": pki.leaf.NotAfter.Unix(), "days_left": int64(30), "chain_ok": true, "hostname_ok": true,
		"issuer": "CN=Test Intermediate,O=AdminHelper", "hours_left": int64(732), "lifetime_pct": 99.9,
	}
	if fmt.Sprint(got) != fmt.Sprint(want) {
		t.Errorf("tls = %v\nwant %v", got, want)
	}
	if name := <-names; name != "svc.example.org" {
		t.Errorf("the server was asked for %q, want svc.example.org", name)
	}

	got, err = tlsSensor(ctx, onLoopback("tls", port, map[string]any{"server_name": "other.example.org"}), "")
	if err != nil || got["hostname_ok"] != false || got["chain_ok"] != true {
		t.Errorf("another name = %v, %v; want hostname_ok false", got, err)
	}
	<-names
	got, err = tlsSensor(ctx, onLoopback("tls", port, map[string]any{"server_name": ""}), "")
	if _, ok := got["hostname_ok"]; err != nil || ok || got["chain_ok"] != true {
		t.Errorf("no server name = %v, %v; want no hostname_ok", got, err)
	}
	if name := <-names; name != "" {
		t.Errorf("without server_name the server was asked for %q", name)
	}

	stubNow(t, start.Add(40*24*time.Hour))
	got, err = tlsSensor(ctx, onLoopback("tls", port, nil), "")
	if err != nil || got["chain_ok"] != false || got["days_left"] != int64(-10) || got["hours_left"] != int64(-228) || got["lifetime_pct"] != 0.0 {
		t.Errorf("after expiry = %v, %v; want the chain broken, -10 days, -228 hours (9.5 days ago) and 0 %%", got, err)
	}
	stubNow(t, start.Add(27*24*time.Hour+10*time.Hour+30*time.Minute))
	got, err = tlsSensor(ctx, onLoopback("tls", port, nil), "")
	if err != nil || got["hours_left"] != int64(73) || got["lifetime_pct"] != 10.0 {
		t.Errorf("73.5 hours of 733 left = %v, %v; want 73 hours and 10.0 %%", got, err)
	}
	stubNow(t, start)
	stubRoots(t, nil)
	if got, err := tlsSensor(ctx, onLoopback("tls", port, nil), ""); err != nil || got["chain_ok"] != false {
		t.Errorf("with the roots of this host = %v, %v; want the test root untrusted", got, err)
	}
}

func TestTLSSensorNeedsTheWholeChain(t *testing.T) {
	pki := newPKI(t)
	stubNow(t, start)
	stubRoots(t, pki.roots)
	port, _ := tlsServer(t, pki.leafOnly)

	got, err := tlsSensor(context.Background(), onLoopback("tls", port, nil), "")
	if err != nil || got["chain_ok"] != false || got["days_left"] != int64(30) {
		t.Errorf("a leaf without its intermediate = %v, %v; want chain_ok false", got, err)
	}
}

func TestCertValuesNeedsACertificate(t *testing.T) {
	if _, err := certValues(nil, ""); err == nil || err.Error() != "the server presented no certificate" {
		t.Errorf("no certificate = %v", err)
	}
}

func TestTLSSensorAfterSTARTTLS(t *testing.T) {
	pki := newPKI(t)
	stubNow(t, start)
	stubRoots(t, pki.roots)
	ctx := context.Background()
	srv := fakeServer(t, func(c *fakeConn) {
		c.say("220 mail.example.org ESMTP\r\n")
		if c.hear() == "" {
			return
		}
		c.say("250-mail.example.org\r\n250-PIPELINING\r\n250 STARTTLS\r\n")
		if c.hear() != "STARTTLS" {
			return
		}
		c.say("220 go ahead\r\n")
		if c.upgrade(pki.chain) && c.hear() == "QUIT" {
			c.say("221 bye\r\n")
		}
	})

	got, err := tlsSensor(ctx, onLoopback("tls", srv.port(), map[string]any{"starttls": "smtp", "server_name": "svc.example.org"}), "")
	if err != nil || got["chain_ok"] != true || got["hostname_ok"] != true {
		t.Fatalf("tls after STARTTLS = %v, %v", got, err)
	}
	if heard := srv.close(); fmt.Sprint(heard) != "[EHLO [127.0.0.1] STARTTLS QUIT]" {
		t.Errorf("the server heard %q, want EHLO, STARTTLS and QUIT inside TLS", heard)
	}
}

func TestTLSSensorWithoutTLS(t *testing.T) {
	ctx := context.Background()
	srv := fakeServer(t, func(c *fakeConn) {
		c.say("220 mail.example.org ESMTP\r\n")
		if c.hear() == "" {
			return
		}
		c.say("250-mail.example.org\r\n250 PIPELINING\r\n")
		if c.hear() == "QUIT" {
			c.say("221 bye\r\n")
		}
	})
	if _, err := tlsSensor(ctx, onLoopback("tls", srv.port(), map[string]any{"starttls": "smtp"}), ""); err == nil || err.Error() != "smtp: no STARTTLS" {
		t.Errorf("a server without STARTTLS = %v", err)
	}
	if heard := srv.close(); fmt.Sprint(heard) != "[EHLO [127.0.0.1] QUIT]" {
		t.Errorf("the server heard %q, want EHLO and QUIT", heard)
	}

	plain := fakeServer(t, func(c *fakeConn) {
		c.say("220 mail.example.org ESMTP\r\n")
		c.hear()
	})
	_, err := tlsSensor(ctx, onLoopback("tls", plain.port(), nil), "")
	if err == nil || !strings.HasPrefix(err.Error(), "tls: the TLS handshake: ") {
		t.Errorf("a server without TLS = %v, want the failed handshake", err)
	}
}

func TestTLSSensorTakesItsParams(t *testing.T) {
	ctx := context.Background()
	withCredential := onLoopback("tls", 443, nil)
	withCredential.Credential = &Credential{Ref: "c1", Use: "bearer"}
	for _, c := range []struct {
		name string
		p    Probe
	}{
		{"a server name with a space", onLoopback("tls", 443, map[string]any{"server_name": "a b"})},
		{"a long server name", onLoopback("tls", 443, map[string]any{"server_name": strings.Repeat("a", 254)})},
		{"starttls of redis", onLoopback("tls", 443, map[string]any{"starttls": "redis"})},
		{"starttls as a boolean", onLoopback("tls", 443, map[string]any{"starttls": true})},
		{"another param", onLoopback("tls", 443, map[string]any{"path": "/"})},
		{"a credential", withCredential},
		{"no target", Probe{Sensor: "tls"}},
	} {
		if _, err := tlsSensor(ctx, c.p, ""); !errors.Is(err, ErrInvalid) {
			t.Errorf("%s: %v, want ErrInvalid", c.name, err)
		}
	}
}

// query is a lookup the dns sensor asked for.
type query struct{ rrtype, name string }

// stubLookup puts in a resolver that answers n records and err and records what it was asked.
func stubLookup(t *testing.T, n int, err error) *[]query {
	t.Helper()
	asked := &[]query{}
	old := lookupDNS
	lookupDNS = func(_ context.Context, rrtype, name string) (int, error) {
		*asked = append(*asked, query{rrtype, name})
		return n, err
	}
	t.Cleanup(func() { lookupDNS = old })
	return asked
}

func dnsProbe(params map[string]any) Probe {
	return Probe{Sensor: "dns", Params: params}
}

func TestDNSSensorSaysWhetherANameResolves(t *testing.T) {
	ctx := context.Background()
	asked := stubLookup(t, 2, nil)
	got, err := dnsSensor(ctx, dnsProbe(map[string]any{"name": "svc.example.org", "rrtype": "AAAA"}), "")
	if took, ok := got["duration_ms"].(int64); err != nil || got["resolved"] != true || got["answers"] != 2 || !ok || took < 0 {
		t.Fatalf("dns = %v, %v; want two answers", got, err)
	}
	if _, err := dnsSensor(ctx, dnsProbe(map[string]any{"name": "_ldap._tcp.example.org.", "rrtype": "SRV"}), ""); err != nil {
		t.Fatalf("SRV: %v", err)
	}
	if _, err := dnsSensor(ctx, dnsProbe(map[string]any{"name": "example.org"}), ""); err != nil {
		t.Fatal(err)
	}
	want := []query{{"AAAA", "svc.example.org"}, {"SRV", "_ldap._tcp.example.org."}, {"A", "example.org"}}
	if fmt.Sprint(*asked) != fmt.Sprint(want) {
		t.Errorf("asked %v, want %v", *asked, want)
	}

	for _, c := range []struct {
		name     string
		n        int
		err      error
		resolved bool
	}{
		{"no such name", 0, &net.DNSError{Err: "no such host", Name: "x", IsNotFound: true}, false},
		{"no record of the type", 0, nil, false},
		{"answers despite an error", 1, &net.DNSError{Err: "cannot unmarshal", Name: "x"}, true},
	} {
		stubLookup(t, c.n, c.err)
		got, err := dnsSensor(ctx, dnsProbe(map[string]any{"name": "example.org"}), "")
		if err != nil || got["resolved"] != c.resolved || got["answers"] != c.n {
			t.Errorf("%s = %v, %v; want resolved %t", c.name, got, err, c.resolved)
		}
	}
	stubLookup(t, 0, &net.DNSError{Err: "server misbehaving", Name: "example.org", IsTemporary: true})
	if _, err := dnsSensor(ctx, dnsProbe(map[string]any{"name": "example.org"}), ""); err == nil || !strings.Contains(err.Error(), "server misbehaving") {
		t.Errorf("a failing server = %v, want its error", err)
	}
	canceled, cancel := context.WithCancel(ctx)
	cancel()
	stubLookup(t, 0, &net.DNSError{Err: "operation was canceled", Name: "example.org"})
	if _, err := dnsSensor(canceled, dnsProbe(map[string]any{"name": "example.org"}), ""); !errors.Is(err, context.Canceled) {
		t.Errorf("an ended probe = %v, want its end", err)
	}
}

func TestDNSSensorLooksUpTheAddressOfAPTRName(t *testing.T) {
	ctx := context.Background()
	asked := stubLookup(t, 1, nil)
	for _, name := range []string{
		"192.0.2.1",
		"1.2.0.192.in-addr.arpa",
		"1.2.0.192.IN-ADDR.ARPA.",
		"1.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.8.b.d.0.1.0.0.2.ip6.arpa.",
		"F.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.8.B.D.0.1.0.0.2.ip6.arpa",
	} {
		if _, err := dnsSensor(ctx, dnsProbe(map[string]any{"name": name, "rrtype": "PTR"}), ""); err != nil {
			t.Errorf("PTR %s: %v", name, err)
		}
	}
	want := []query{{"PTR", "192.0.2.1"}, {"PTR", "192.0.2.1"}, {"PTR", "192.0.2.1"}, {"PTR", "2001:db8::1"}, {"PTR", "2001:db8::f"}}
	if fmt.Sprint(*asked) != fmt.Sprint(want) {
		t.Errorf("asked %v\nwant %v", *asked, want)
	}

	for _, name := range []string{
		"example.org", "2.0.192.in-addr.arpa", "5.1.2.0.192.in-addr.arpa", "256.2.0.192.in-addr.arpa",
		"01.2.0.192.in-addr.arpa", "in-addr.arpa", "0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.8.b.d.0.1.0.0.2.ip6.arpa",
		"g.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.8.b.d.0.1.0.0.2.ip6.arpa",
		"10.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.8.b.d.0.1.0.0.2.ip6.arpa",
	} {
		if _, err := dnsSensor(ctx, dnsProbe(map[string]any{"name": name, "rrtype": "PTR"}), ""); !errors.Is(err, ErrInvalid) {
			t.Errorf("PTR %s: %v, want ErrInvalid", name, err)
		}
	}
	if len(*asked) != len(want) {
		t.Errorf("an invalid PTR name was looked up: %v", (*asked)[len(want):])
	}
}

func TestDNSSensorTakesItsParams(t *testing.T) {
	ctx := context.Background()
	asked := stubLookup(t, 1, nil)
	withTarget := dnsProbe(map[string]any{"name": "example.org"})
	withTarget.Target = &Target{Kind: kindLoopback}
	withCredential := dnsProbe(map[string]any{"name": "example.org"})
	withCredential.Credential = &Credential{Ref: "c1", Use: "bearer"}
	for _, c := range []struct {
		name string
		p    Probe
	}{
		{"no name", dnsProbe(nil)},
		{"an empty name", dnsProbe(map[string]any{"name": ""})},
		{"a name with a space", dnsProbe(map[string]any{"name": "a b.example.org"})},
		{"an empty label", dnsProbe(map[string]any{"name": "a..example.org"})},
		{"a label starting with a hyphen", dnsProbe(map[string]any{"name": "-a.example.org"})},
		{"a label of 64 characters", dnsProbe(map[string]any{"name": strings.Repeat("a", 64) + ".org"})},
		{"a name of 254 characters", dnsProbe(map[string]any{"name": strings.Repeat("abcdefghi.", 25) + "abcd"})},
		{"an IPv6 address", dnsProbe(map[string]any{"name": "2001:db8::1", "rrtype": "PTR"})},
		{"a name of another type", dnsProbe(map[string]any{"name": 42})},
		{"rrtype ANY", dnsProbe(map[string]any{"name": "example.org", "rrtype": "ANY"})},
		{"rrtype in lower case", dnsProbe(map[string]any{"name": "example.org", "rrtype": "a"})},
		{"another param", dnsProbe(map[string]any{"name": "example.org", "server": "192.0.2.53"})},
		{"a target without a port", withTarget},
		{"a credential", withCredential},
	} {
		if _, err := dnsSensor(ctx, c.p, ""); !errors.Is(err, ErrInvalid) {
			t.Errorf("%s: %v, want ErrInvalid", c.name, err)
		}
	}
	if len(*asked) != 0 {
		t.Errorf("an invalid probe was looked up: %v", *asked)
	}
	if _, err := dnsSensor(ctx, dnsProbe(map[string]any{"name": strings.Repeat("abcdefghi.", 25) + "abc"}), ""); err != nil {
		t.Errorf("a name of 253 characters: %v", err)
	}
	if _, err := lookupDNS0(ctx, "ANY", "example.org"); !errors.Is(err, ErrInvalid) {
		t.Errorf("the resolver asked for ANY = %v, want ErrInvalid", err)
	}
}

// lookupDNS0 is the resolver of the agent, whatever a test put in.
var lookupDNS0 = lookupDNS

func TestLifetimePctOfACertificateWithoutALifetime(t *testing.T) {
	for _, c := range []struct {
		left, lifetime time.Duration
		want           float64
	}{
		{time.Hour, 0, 0},
		{time.Hour, -time.Hour, 0},
		{-time.Hour, 10 * time.Hour, 0},
		{3 * time.Hour, 8 * time.Hour, 37.5},
		{time.Hour, 3 * time.Hour, 33.3},
	} {
		if got := lifetimePct(c.left, c.lifetime); got != c.want {
			t.Errorf("lifetimePct(%s, %s) = %v, want %v", c.left, c.lifetime, got, c.want)
		}
	}
}
