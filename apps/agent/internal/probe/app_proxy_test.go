// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package probe

import (
	"context"
	"errors"
	"io"
	"net/http"
	"net/http/httptest"
	"net/netip"
	"os"
	"strings"
	"sync"
	"testing"
	"time"
)

// caddyAdmin is Caddy's admin API on loopback the upstreams view is pointed at; it answers every
// request with status and answer and keeps what it was asked.
type caddyAdmin struct {
	mu       sync.Mutex
	requests []string
}

func (a *caddyAdmin) asked() []string {
	a.mu.Lock()
	defer a.mu.Unlock()
	return append([]string(nil), a.requests...)
}

func serveCaddy(t *testing.T, status int, answer string) (*caddyAdmin, int) {
	t.Helper()
	api := &caddyAdmin{}
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		api.mu.Lock()
		api.requests = append(api.requests, r.Method+" "+r.URL.RequestURI())
		api.mu.Unlock()
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(status)
		_, _ = io.WriteString(w, answer)
	}))
	t.Cleanup(srv.Close)
	freshSnapshot(t) // the guard is to see the listener just started
	port := portOf(t, srv.Listener.Addr().String())
	stubCaddyEndpoint(t, "127.0.0.1", port)
	return api, port
}

func stubCaddyEndpoint(t *testing.T, addr string, port int) {
	t.Helper()
	old := caddyEndpoint
	caddyEndpoint = func(context.Context, Target) (endpoint, error) {
		return endpoint{addr: netip.MustParseAddr(addr), port: uint16(port)}, nil
	}
	t.Cleanup(func() { caddyEndpoint = old })
}

func caddyUnit(port int) Target { return Target{Kind: kindUnit, Name: "caddy.service", PortHint: port} }

// caddyUpstreamsAnswer has the form of GET /reverse_proxy/upstreams (caddyserver.com/docs/api): one
// entry per upstream with its address, its requests in flight and its failed requests.
const caddyUpstreamsAnswer = `[
 {"address": "10.0.0.5:8080", "num_requests": 4, "fails": 0},
 {"address": "app-backend.internal:3000", "num_requests": 0, "fails": 1},
 {"address": "unix//run/php/php-fpm.sock", "num_requests": 1, "fails": 0}
]`

func TestCaddyUpstreamsCountsTheUpstreamsAndTheFailingOnes(t *testing.T) {
	api, port := serveCaddy(t, http.StatusOK, caddyUpstreamsAnswer)
	got, err := caddyUpstreams(context.Background(), caddyUnit(port))
	if err != nil || got["upstreams"] != 3 || got["failing"] != 1 || len(got) != 2 {
		t.Fatalf("caddy_upstreams = %v, %v; want 3 upstreams, 1 failing", got, err)
	}
	noneOf(t, got, "10.0.0.5", "app-backend", "php-fpm")
	if want := []string{"GET /reverse_proxy/upstreams"}; strings.Join(api.asked(), ",") != strings.Join(want, ",") {
		t.Errorf("asked %v, want %v", api.asked(), want)
	}
	if got, err := caddyUpstreams(context.Background(), caddyUnit(port)); err != nil || got["upstreams"] != 3 {
		t.Errorf("again = %v, %v", got, err)
	}
	for _, r := range api.asked() {
		if strings.Contains(r, "/config") {
			t.Errorf("asked %s; /config/ holds the secrets of the configuration", r)
		}
	}
}

func TestCaddyUpstreamsWithoutReverseProxies(t *testing.T) {
	_, port := serveCaddy(t, http.StatusOK, `[]`)
	got, err := caddyUpstreams(context.Background(), caddyUnit(port))
	if err != nil || got["upstreams"] != 0 || got["failing"] != 0 {
		t.Fatalf("caddy_upstreams = %v, %v; want none", got, err)
	}
}

func TestCaddyUpstreamsTakesTheDefaultAdminPort(t *testing.T) {
	var asked Target
	old := caddyEndpoint
	caddyEndpoint = func(_ context.Context, t Target) (endpoint, error) {
		asked = t
		return endpoint{}, errNotListening
	}
	t.Cleanup(func() { caddyEndpoint = old })
	if _, err := caddyUpstreams(context.Background(), caddyUnit(0)); !errors.Is(err, errNotListening) {
		t.Errorf("error %v, want the resolver's", err)
	}
	if asked.PortHint != caddyAdminPort || asked.Name != "caddy.service" {
		t.Errorf("resolved %+v, want port hint %d", asked, caddyAdminPort)
	}
}

func TestCaddyUpstreamsAsksOnlyTheAdminPortOnLoopback(t *testing.T) {
	api, port := serveCaddy(t, http.StatusOK, caddyUpstreamsAnswer)
	// The unit's one port is a site's: the hint is the admin port, the resolver answers another.
	if _, err := caddyUpstreams(context.Background(), caddyUnit(port+1)); !errors.Is(err, ErrUnsupported) {
		t.Errorf("another port = %v, want ErrUnsupported", err)
	}
	stubCaddyEndpoint(t, "192.0.2.10", port)
	if _, err := caddyUpstreams(context.Background(), caddyUnit(port)); err == nil || !strings.Contains(err.Error(), "beyond loopback") {
		t.Errorf("an admin API beyond loopback = %v", err)
	}
	if len(api.asked()) != 0 {
		t.Errorf("asked %v, want nothing", api.asked())
	}
}

func TestCaddyUpstreamsErrorsNameNoAnswer(t *testing.T) {
	cases := map[string]struct {
		status int
		answer string
		want   string
	}{
		"an error":      {http.StatusForbidden, `{"error":"host not allowed: 10.0.0.5"}`, "HTTP 403"},
		"no list":       {http.StatusOK, `{"address":"10.0.0.5:8080"}`, "no list of upstreams"},
		"no fails":      {http.StatusOK, `[{"address":"10.0.0.5:8080","num_requests":1}]`, "without fails"},
		"no JSON":       {http.StatusOK, `10.0.0.5:8080 up`, "no list of upstreams"},
		"fails as text": {http.StatusOK, `[{"address":"10.0.0.5:8080","fails":"10.0.0.5"}]`, "no list of upstreams"},
	}
	for name, c := range cases {
		t.Run(name, func(t *testing.T) {
			_, port := serveCaddy(t, c.status, c.answer)
			_, err := caddyUpstreams(context.Background(), caddyUnit(port))
			if err == nil || !strings.Contains(err.Error(), c.want) || strings.Contains(err.Error(), "10.0.0.5") {
				t.Fatalf("error %v, want %q and no address", err, c.want)
			}
		})
	}
}

func TestCaddyUpstreamsWhenCaddyIsGone(t *testing.T) {
	srv := httptest.NewServer(http.NotFoundHandler())
	port := portOf(t, srv.Listener.Addr().String())
	srv.Close()
	freshSnapshot(t)
	stubCaddyEndpoint(t, "127.0.0.1", port)
	if _, err := caddyUpstreams(context.Background(), caddyUnit(port)); err == nil {
		t.Error("a closed port answered")
	}
}

func TestTheProxyViewsAreBoundToTheirKinds(t *testing.T) {
	want := map[string][]string{
		"caddy_certs":     {kindUnit, kindContainer},
		"caddy_upstreams": {kindUnit},
		"npm_certs":       {kindContainer},
		"traefik_certs":   {kindUnit, kindContainer},
	}
	for view, kinds := range want {
		if got := appViews[view].kinds; strings.Join(got, ",") != strings.Join(kinds, ",") {
			t.Errorf("view %s takes %v, want %v", view, got, kinds)
		}
	}
	p := appProbe("npm_certs", unitTarget("npm.service"))
	if _, err := appSensor(context.Background(), p, ""); !errors.Is(err, ErrInvalid) {
		t.Errorf("npm_certs of a unit = %v, want ErrInvalid", err)
	}
}

func TestCertCountTakesTheSoonestEnd(t *testing.T) {
	stubNow(t, start)
	var c certCount
	if got := c.values(); len(got) != 2 || got["certs"] != 0 || got["expired"] != 0 {
		t.Errorf("no certificates = %v, want no min_days_left", got)
	}
	c.add(start.Add(90 * 24 * time.Hour))
	c.add(start.Add(10*24*time.Hour - time.Minute))
	c.add(start.Add(30 * 24 * time.Hour))
	if got := c.values(); got["certs"] != 3 || got["expired"] != 0 || got["min_days_left"] != 9 {
		t.Errorf("values = %v, want 3 certs, 9 days", got)
	}
	c.add(start.Add(-time.Hour))
	if got := c.values(); got["certs"] != 4 || got["expired"] != 1 || got["min_days_left"] != -1 {
		t.Errorf("values = %v, want 1 expired, -1 days", got)
	}
}

func TestLeafNotAfterSkipsWhatIsNoCertificate(t *testing.T) {
	stubNow(t, start)
	end := start.Add(42 * 24 * time.Hour).Truncate(time.Second)
	data, err := os.ReadFile(writeCert(t, end))
	if err != nil {
		t.Fatal(err)
	}
	const secret = "PRIVATE KEY s3cr3t"
	key := "-----BEGIN PRIVATE KEY-----\nczNjcjN0LWtleQ==\n-----END PRIVATE KEY-----\n"
	got, err := leafNotAfter(append([]byte(key), data...))
	if err != nil || !got.Equal(end) {
		t.Errorf("leafNotAfter = %v, %v; want %v", got, err, end)
	}
	for _, bad := range []string{key, secret, "-----BEGIN CERTIFICATE-----\nczNjcjN0\n-----END CERTIFICATE-----\n"} {
		if _, err := leafNotAfter([]byte(bad)); err == nil || strings.Contains(err.Error(), "s3cr3t") || strings.Contains(err.Error(), "czNj") {
			t.Errorf("leafNotAfter(%q) = %v, want an error naming nothing of it", bad, err)
		}
	}
}
