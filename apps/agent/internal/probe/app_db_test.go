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
	"reflect"
	"strings"
	"sync"
	"testing"
	"time"
)

// esNodesAnswer has the form of GET /_nodes/stats/jvm,fs with the view's filter_path (checked against
// Elasticsearch 8.19.0), for a cluster of two nodes of which one did not answer.
const esNodesAnswer = `{"_nodes":{"total":3,"successful":2,"failed":1},"nodes":{` +
	`"aB3dEfGhIjKlMnOpQrStUv":{"jvm":{"mem":{"heap_used_percent":30}},` +
	`"fs":{"total":{"total_in_bytes":1000,"free_in_bytes":400,"available_in_bytes":350}}},` +
	`"zY9xWvUtSrQpOnMlKjIhGf":{"jvm":{"mem":{"heap_used_percent":81}},` +
	`"fs":{"total":{"total_in_bytes":2000,"free_in_bytes":1900,"available_in_bytes":1800}}}}}`

// esServer is a node of Elasticsearch the es_nodes view is pointed at; it answers every request with
// status and answer and keeps what it was asked and the Authorization it got.
type esServer struct {
	mu       sync.Mutex
	requests []string
	auth     []string
}

func (s *esServer) asked() ([]string, []string) {
	s.mu.Lock()
	defer s.mu.Unlock()
	return append([]string(nil), s.requests...), append([]string(nil), s.auth...)
}

func serveES(t *testing.T, tls bool, status int, answer string) (*esServer, int) {
	t.Helper()
	es := &esServer{}
	h := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		es.mu.Lock()
		es.requests = append(es.requests, r.Method+" "+r.URL.RequestURI())
		es.auth = append(es.auth, r.Header.Get("Authorization"))
		es.mu.Unlock()
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(status)
		_, _ = io.WriteString(w, answer)
	})
	var srv *httptest.Server
	if tls {
		srv = httptest.NewTLSServer(h)
	} else {
		srv = httptest.NewServer(h)
	}
	t.Cleanup(srv.Close)
	freshSnapshot(t) // the guard is to see the listener just started
	port := portOf(t, srv.Listener.Addr().String())
	stubESEndpoint(t, port)
	return es, port
}

func stubESEndpoint(t *testing.T, port int) {
	t.Helper()
	old := esEndpoint
	esEndpoint = func(context.Context, Target) (endpoint, error) {
		return endpoint{addr: netip.MustParseAddr("127.0.0.1"), port: uint16(port)}, nil
	}
	t.Cleanup(func() { esEndpoint = old })
}

func esUnit(port int, scheme string) Target {
	return Target{Kind: kindUnit, Name: "elasticsearch.service", PortHint: port, Scheme: scheme}
}

const esPath = "GET /_nodes/stats/jvm,fs?filter_path=_nodes,nodes.*.jvm.mem.heap_used_percent,nodes.*.fs.total"

func TestESNodesReadsTheNodesOfTheCluster(t *testing.T) {
	for _, scheme := range []string{"", "http", "https"} {
		t.Run("scheme "+scheme, func(t *testing.T) {
			es, port := serveES(t, scheme == "https", http.StatusOK, esNodesAnswer)
			got, err := esNodes(context.Background(), esUnit(port, scheme), appCredential{})
			want := map[string]any{"nodes": 3, "nodes_failed": 1, "heap_used_pct_max": int64(81), "disk_used_pct_max": int64(65)}
			if err != nil || !reflect.DeepEqual(got, want) {
				t.Fatalf("es_nodes = %v, %v; want %v", got, err, want)
			}
			noneOf(t, got, "aB3dEf", "zY9xWv")
			if asked, auth := es.asked(); strings.Join(asked, ",") != esPath || auth[0] != "" {
				t.Errorf("asked %v with %q, want %s without a credential", asked, auth, esPath)
			}
		})
	}
}

func TestESNodesSendsTheCredentialAsBasic(t *testing.T) {
	es, port := serveES(t, true, http.StatusOK, esNodesAnswer)
	p := appProbe("es_nodes", &Target{Kind: kindUnit, Name: "elasticsearch.service", PortHint: port, Scheme: "https"},
		"nodes", "heap_used_pct_max")
	p.Credential = &Credential{Ref: "es", Use: useBasic}

	got, err := appSensor(context.Background(), p, "monitor:s3cr3t")

	if err != nil || got["nodes"] != 3 {
		t.Fatalf("es_nodes = %v, %v", got, err)
	}
	// base64("monitor:s3cr3t")
	if _, auth := es.asked(); len(auth) != 1 || auth[0] != "Basic bW9uaXRvcjpzM2NyM3Q=" {
		t.Errorf("Authorization %q, want basic", auth)
	}
	p.Credential.Use = useBearer
	if _, err := appSensor(context.Background(), p, "token"); !errors.Is(err, ErrInvalid) {
		t.Errorf("a bearer credential = %v, want ErrInvalid", err)
	}
	p.Credential.Use = useBasic
	if _, err := appSensor(context.Background(), p, "no-colon"); !errors.Is(err, ErrInvalid) {
		t.Errorf("a credential without a password = %v, want ErrInvalid", err)
	}
}

func TestESNodesMapsARefusalToDenied(t *testing.T) {
	for _, status := range []int{http.StatusUnauthorized, http.StatusForbidden} {
		_, port := serveES(t, false, status, `{"error":{"type":"security_exception","reason":"user monitor"}}`)
		_, err := esNodes(context.Background(), esUnit(port, ""), appCredential{})
		if !errors.Is(err, ErrDenied) || strings.Contains(err.Error(), "monitor") {
			t.Errorf("HTTP %d = %v, want ErrDenied naming nothing", status, err)
		}
	}
}

func TestESNodesTakesTheDefaultPortAndNoOther(t *testing.T) {
	var asked Target
	old := esEndpoint
	esEndpoint = func(_ context.Context, t Target) (endpoint, error) {
		asked = t
		return endpoint{addr: netip.MustParseAddr("127.0.0.1"), port: 9300}, nil
	}
	t.Cleanup(func() { esEndpoint = old })
	_, err := esNodes(context.Background(), esUnit(0, ""), appCredential{})
	if !errors.Is(err, ErrUnsupported) || !strings.Contains(err.Error(), "HTTP port 9200") {
		t.Errorf("the transport port alone = %v, want unsupported", err)
	}
	if asked.PortHint != esHTTPPort {
		t.Errorf("resolved %+v, want port hint %d", asked, esHTTPPort)
	}
}

func TestESNodesRefusesAnotherScheme(t *testing.T) {
	_, port := serveES(t, false, http.StatusOK, esNodesAnswer)
	if _, err := esNodes(context.Background(), esUnit(port, "ftp"), appCredential{}); !errors.Is(err, ErrInvalid) {
		t.Errorf("scheme ftp = %v, want ErrInvalid", err)
	}
}

func TestESNodesErrorsNameNoAnswer(t *testing.T) {
	node := func(heap, total, avail string) string {
		return `{"_nodes":{"total":1,"successful":1,"failed":0},"nodes":{"n-1":{"jvm":{"mem":{"heap_used_percent":` + heap +
			`}},"fs":{"total":{"total_in_bytes":` + total + `,"available_in_bytes":` + avail + `}}}}}`
	}
	cases := map[string]struct {
		status int
		answer string
		want   string
	}{
		"an error":           {http.StatusServiceUnavailable, `{"error":"n-1 is down"}`, "HTTP 503"},
		"no JSON":            {http.StatusOK, `n-1 up`, "no node statistics"},
		"no _nodes":          {http.StatusOK, `{"nodes":{"n-1":{}}}`, "no node statistics"},
		"no nodes":           {http.StatusOK, `{"_nodes":{"total":1,"successful":0,"failed":1}}`, "no node statistics"},
		"no heap":            {http.StatusOK, node("null", "10", "5"), "no node statistics"},
		"no disk":            {http.StatusOK, node("10", "0", "0"), "no node statistics"},
		"more free than all": {http.StatusOK, node("10", "10", "11"), "no node statistics"},
		"heap as text":       {http.StatusOK, node(`"n-1"`, "10", "5"), "no node statistics"},
	}
	for name, c := range cases {
		t.Run(name, func(t *testing.T) {
			_, port := serveES(t, false, c.status, c.answer)
			_, err := esNodes(context.Background(), esUnit(port, ""), appCredential{})
			if err == nil || !strings.Contains(err.Error(), c.want) || strings.Contains(err.Error(), "n-1") {
				t.Fatalf("error %v, want %q and no name", err, c.want)
			}
		})
	}
}

func TestTheDatabaseViewIsBoundToItsKinds(t *testing.T) {
	if got := appViews["es_nodes"].kinds; strings.Join(got, ",") != kindUnit+","+kindContainer {
		t.Errorf("view es_nodes takes %v, want unit and container", got)
	}
	p := appProbe("es_nodes", &Target{Kind: kindLoopback, PortHint: 9200})
	if _, err := appSensor(context.Background(), p, ""); !errors.Is(err, ErrInvalid) {
		t.Errorf("es_nodes of loopback = %v, want ErrInvalid", err)
	}
}

func TestESNodesWhenElasticsearchIsGone(t *testing.T) {
	srv := httptest.NewServer(http.NotFoundHandler())
	port := portOf(t, srv.Listener.Addr().String())
	srv.Close()
	freshSnapshot(t)
	stubESEndpoint(t, port)
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	if _, err := esNodes(ctx, esUnit(port, ""), appCredential{}); err == nil {
		t.Error("a closed port answered")
	}
}
