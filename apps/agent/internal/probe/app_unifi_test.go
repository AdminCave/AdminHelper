// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package probe

import (
	"context"
	"crypto/tls"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"net/http/httptest"
	"net/netip"
	"net/url"
	"reflect"
	"strconv"
	"strings"
	"sync"
	"testing"
)

// The ids of the sites and devices of the tests, in the form of the Integration API.
const (
	uSite1   = "88f7af54-98f8-306a-a1c7-c9349722b1f6"
	uSite2   = "1b2c3d4e-0000-4000-8000-00000000aaaa"
	uGateway = "aaaaaaaa-0000-4000-8000-000000000001"
	uSwitch  = "aaaaaaaa-0000-4000-8000-000000000002"
	uAP1     = "aaaaaaaa-0000-4000-8000-000000000003"
	uAP2     = "aaaaaaaa-0000-4000-8000-000000000004"
	uAP3     = "aaaaaaaa-0000-4000-8000-000000000005"
	uKey     = "k3y-s3cr3t-0f-the-integration-api"
)

// uDev is an adopted device as the Integration API lists it (OpenAPI v11.0.97, "Adopted device
// overview"), with a name, a MAC and an address the view must never pass on.
type uDev struct {
	id, state string
	gateway   bool
	updatable bool
	uplink    string
}

func (d uDev) overview() map[string]any {
	features := []string{"switching"}
	if d.gateway {
		features = []string{"gateway", "switching"}
	}
	return map[string]any{
		"id": d.id, "name": "Device " + d.id[len(d.id)-1:], "model": "USW-24", "macAddress": "94:2a:6f:26:c6:ca",
		"ipAddress": "192.0.2.55", "state": d.state, "supported": true, "firmwareVersion": "7.1.66",
		"firmwareUpdatable": d.updatable, "features": features, "interfaces": []string{"ports"},
	}
}

// unifiServer is the Integration API of a UniFi OS Server: sites with their devices, pending devices
// and clients. It keeps every request it got, with its method and key.
type unifiServer struct {
	mu       sync.Mutex
	requests []string
	keys     []string
	sites    map[string][]uDev
	order    []string
	pending  int
	clients  int
	status   int
	// answer, if set, answers every request in place of the API.
	answer http.HandlerFunc
}

func (s *unifiServer) asked() []string {
	s.mu.Lock()
	defer s.mu.Unlock()
	return append([]string(nil), s.requests...)
}

func (s *unifiServer) page(w http.ResponseWriter, r *http.Request, items []any, total int) {
	off, _ := strconv.Atoi(r.URL.Query().Get("offset"))
	lim, _ := strconv.Atoi(r.URL.Query().Get("limit"))
	end := min(len(items), off+lim)
	data := []any{}
	if off < end {
		data = items[off:end]
	}
	_ = json.NewEncoder(w).Encode(map[string]any{
		"offset": off, "limit": lim, "count": len(data), "totalCount": total, "data": data,
	})
}

func (s *unifiServer) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	s.mu.Lock()
	s.requests = append(s.requests, r.Method+" "+r.URL.RequestURI())
	s.keys = append(s.keys, r.Header.Get("X-API-KEY"))
	s.mu.Unlock()
	if s.answer != nil {
		s.answer(w, r)
		return
	}
	if s.status != 0 {
		w.WriteHeader(s.status)
		_, _ = fmt.Fprint(w, `{"statusCode":401,"statusName":"UNAUTHORIZED","message":"`+uKey+`"}`)
		return
	}
	w.Header().Set("Content-Type", "application/json")
	parts := strings.Split(strings.TrimPrefix(r.URL.Path, unifiBase+"/v1/"), "/")
	switch {
	case len(parts) == 1 && parts[0] == "info":
		_, _ = fmt.Fprint(w, `{"applicationVersion":"10.1.84"}`)
	case len(parts) == 1 && parts[0] == "sites":
		var items []any
		for _, id := range s.order {
			items = append(items, map[string]any{"id": id, "internalReference": "default", "name": "School " + id[:4]})
		}
		s.page(w, r, items, len(items))
	case len(parts) == 1 && parts[0] == "pending-devices":
		items := []any{map[string]any{"macAddress": "94:2a:6f:00:00:01", "ipAddress": "192.0.2.77", "state": "PENDING_ADOPTION"}}
		s.page(w, r, items, s.pending)
	case len(parts) == 3 && parts[2] == "devices":
		var items []any
		for _, d := range s.sites[parts[1]] {
			items = append(items, d.overview())
		}
		s.page(w, r, items, len(items))
	case len(parts) == 4 && parts[2] == "devices":
		for _, d := range s.sites[parts[1]] {
			if d.id == parts[3] {
				det := d.overview()
				if d.uplink != "" {
					det["uplink"] = map[string]any{"deviceId": d.uplink}
				}
				_ = json.NewEncoder(w).Encode(det)
				return
			}
		}
		w.WriteHeader(http.StatusNotFound)
	case len(parts) == 3 && parts[2] == "clients":
		items := []any{map[string]any{"name": "laptop-of-pupil", "macAddress": "94:2a:6f:00:00:02", "ipAddress": "192.0.2.99"}}
		s.page(w, r, items, s.clients)
	default:
		w.WriteHeader(http.StatusNotFound)
	}
}

// serveUnifi starts s behind TLS on loopback and points the view at it.
func serveUnifi(t *testing.T, s *unifiServer) int {
	t.Helper()
	srv := httptest.NewTLSServer(s)
	t.Cleanup(srv.Close)
	freshSnapshot(t) // the guard is to see the listener just started
	port := portOf(t, srv.Listener.Addr().String())
	old := unifiEndpoint
	unifiEndpoint = func(context.Context, Target) (endpoint, error) {
		return endpoint{addr: netip.MustParseAddr("127.0.0.1"), port: uint16(port)}, nil
	}
	t.Cleanup(func() { unifiEndpoint = old })
	return port
}

func uosUnit(port int) Target {
	return Target{Kind: kindUnit, Name: "uosserver.service", PortHint: port}
}

var uosKey = appCredential{use: "header:X-API-KEY", secret: uKey}

// aSchool is a site with a gateway, a switch behind it and three APs behind the switch: the switch is
// offline, two APs hang behind it and are offline with it, one AP is updating.
func aSchool() *unifiServer {
	return &unifiServer{
		order: []string{uSite1},
		sites: map[string][]uDev{uSite1: {
			{id: uGateway, state: "ONLINE", gateway: true, updatable: true},
			{id: uSwitch, state: "OFFLINE", uplink: uGateway},
			{id: uAP1, state: "CONNECTION_INTERRUPTED", uplink: uSwitch},
			{id: uAP2, state: "ISOLATED", uplink: uSwitch, updatable: true},
			{id: uAP3, state: "UPDATING", uplink: uGateway},
		}},
		pending: 2,
		clients: 345,
	}
}

func TestUnifiNetworkCountsTheDevicesAndTheirCause(t *testing.T) {
	s := aSchool()
	port := serveUnifi(t, s)

	got, err := unifiNetwork(context.Background(), uosUnit(port), uosKey)

	want := map[string]any{
		"sites": int64(1), "devices": int64(5), "offline": int64(3), "offline_root": int64(1),
		"gateways_offline": int64(0), "updating": int64(1), "firmware_updatable": int64(2),
		"pending": int64(2), "clients": int64(345),
	}
	if err != nil || !reflect.DeepEqual(got, want) {
		t.Fatalf("unifi_network = %v, %v; want %v", got, err, want)
	}
	noneOf(t, got, "Device", "94:2a", "192.0.2", "School", "laptop", uSite1, uSwitch, uKey)
	b := unifiBase + "/v1/"
	wantAsked := []string{
		"GET " + b + "info",
		"GET " + b + "sites?limit=200&offset=0",
		"GET " + b + "sites/" + uSite1 + "/devices?limit=200&offset=0",
		"GET " + b + "sites/" + uSite1 + "/devices/" + uSwitch,
		"GET " + b + "sites/" + uSite1 + "/devices/" + uAP1,
		"GET " + b + "sites/" + uSite1 + "/devices/" + uAP2,
		"GET " + b + "pending-devices?limit=1&offset=0",
		"GET " + b + "sites/" + uSite1 + "/clients?limit=1&offset=0",
	}
	if asked := s.asked(); !reflect.DeepEqual(asked, wantAsked) {
		t.Errorf("asked\n%s\nwant\n%s", strings.Join(asked, "\n"), strings.Join(wantAsked, "\n"))
	}
	for i, k := range s.keys {
		if k != uKey {
			t.Errorf("request %d carried key %q", i, k)
		}
	}
}

func TestUnifiNetworkCountsAGatewayOfflineAsACause(t *testing.T) {
	s := &unifiServer{order: []string{uSite1, uSite2}, sites: map[string][]uDev{
		uSite1: {{id: uGateway, state: "OFFLINE", gateway: true}, {id: uSwitch, state: "OFFLINE", uplink: uGateway}},
		uSite2: {{id: uAP1, state: "ONLINE"}},
	}, clients: 4}
	port := serveUnifi(t, s)

	got, err := unifiNetwork(context.Background(), uosUnit(port), uosKey)

	if err != nil || got["gateways_offline"] != int64(1) || got["offline_root"] != int64(1) || got["offline"] != int64(2) ||
		got["sites"] != int64(2) || got["devices"] != int64(3) || got["clients"] != int64(8) {
		t.Fatalf("unifi_network = %v, %v", got, err)
	}
}

func TestUnifiNetworkReadsEveryPageOfTheDevices(t *testing.T) {
	var devs []uDev
	for i := range 450 {
		devs = append(devs, uDev{id: fmt.Sprintf("bbbbbbbb-0000-4000-8000-%012d", i), state: "ONLINE"})
	}
	s := &unifiServer{order: []string{uSite1}, sites: map[string][]uDev{uSite1: devs}}
	port := serveUnifi(t, s)

	got, err := unifiNetwork(context.Background(), uosUnit(port), uosKey)

	if err != nil || got["devices"] != int64(450) || got["offline"] != int64(0) {
		t.Fatalf("unifi_network = %v, %v", got, err)
	}
	var pages []string
	for _, a := range s.asked() {
		if strings.Contains(a, "/devices?") {
			pages = append(pages, a[strings.Index(a, "?"):])
		}
	}
	if want := []string{"?limit=200&offset=0", "?limit=200&offset=200", "?limit=200&offset=400"}; !reflect.DeepEqual(pages, want) {
		t.Errorf("pages %v, want %v", pages, want)
	}
}

func TestUnifiNetworkStaysWithinItsRequests(t *testing.T) {
	// Twelve offline devices: details for eight, the rest count as causes; never more than twenty requests.
	var devs []uDev
	devs = append(devs, uDev{id: uGateway, state: "ONLINE", gateway: true})
	for i := range 12 {
		devs = append(devs, uDev{id: fmt.Sprintf("cccccccc-0000-4000-8000-%012d", i), state: "OFFLINE", uplink: uGateway})
	}
	s := &unifiServer{order: []string{uSite1}, sites: map[string][]uDev{uSite1: devs}}
	port := serveUnifi(t, s)

	got, err := unifiNetwork(context.Background(), uosUnit(port), uosKey)

	if err != nil || got["offline"] != int64(12) || got["offline_root"] != int64(12) {
		t.Fatalf("unifi_network = %v, %v", got, err)
	}
	details := 0
	for _, a := range s.asked() {
		if strings.Count(a, "/devices/") == 1 {
			details++
		}
	}
	if n := len(s.asked()); details != unifiMaxDetails || n > unifiMaxRequests {
		t.Errorf("%d requests, %d of them details; want %d details and at most %d", n, details, unifiMaxDetails, unifiMaxRequests)
	}

	// Sites enough to spend the budget: the view stops at twenty requests and sends no more.
	many := &unifiServer{sites: map[string][]uDev{}}
	for i := range 10 {
		id := fmt.Sprintf("dddddddd-0000-4000-8000-%012d", i)
		many.order = append(many.order, id)
		many.sites[id] = []uDev{{id: fmt.Sprintf("eeeeeeee-0000-4000-8000-%012d", i), state: "OFFLINE"}}
	}
	port = serveUnifi(t, many)
	if _, err := unifiNetwork(context.Background(), uosUnit(port), uosKey); !errors.Is(err, ErrUnsupported) {
		t.Errorf("ten sites = %v, want ErrUnsupported", err)
	}
	if n := len(many.asked()); n != unifiMaxRequests {
		t.Errorf("ten sites took %d requests, want exactly %d", n, unifiMaxRequests)
	}
}

func TestUnifiNetworkMapsARefusalToDenied(t *testing.T) {
	for _, status := range []int{http.StatusUnauthorized, http.StatusForbidden} {
		port := serveUnifi(t, &unifiServer{status: status})
		_, err := unifiNetwork(context.Background(), uosUnit(port), uosKey)
		if !errors.Is(err, ErrDenied) || strings.Contains(err.Error(), uKey) {
			t.Errorf("HTTP %d = %v, want ErrDenied without the key", status, err)
		}
	}
}

func TestUnifiNetworkFollowsNoRedirect(t *testing.T) {
	s := &unifiServer{}
	s.answer = func(w http.ResponseWriter, r *http.Request) {
		http.Redirect(w, r, unifiBase+"/v1/sites?limit=200&offset=0", http.StatusFound)
	}
	port := serveUnifi(t, s)

	_, err := unifiNetwork(context.Background(), uosUnit(port), uosKey)

	if !errors.Is(err, ErrNotAllowed) || strings.Contains(err.Error(), uKey) {
		t.Errorf("a redirect = %v, want ErrNotAllowed without the key", err)
	}
	if asked := s.asked(); len(asked) != 1 {
		t.Errorf("asked %v, want only the first request", asked)
	}
}

func TestTheUnifiClientSendsOnlyReadRequestsOfItsList(t *testing.T) {
	s := aSchool()
	port := serveUnifi(t, s)
	host := netip.AddrPortFrom(netip.MustParseAddr("127.0.0.1"), uint16(port)).String()
	hc := NewGuard().HTTPClient(&tls.Config{InsecureSkipVerify: true}) //nolint:gosec // the test server's own certificate
	c := &unifiClient{http: hc, host: host, key: uKey, budget: unifiMaxRequests}
	b := "https://" + host + unifiBase + "/v1/"
	cases := map[string]struct{ method, url string }{
		"POST to a device":        {http.MethodPost, b + "sites/" + uSite1 + "/devices/" + uSwitch + "/actions"},
		"POST to a list path":     {http.MethodPost, b + "sites/" + uSite1 + "/devices"},
		"DELETE of a device":      {http.MethodDelete, b + "sites/" + uSite1 + "/devices/" + uSwitch},
		"PUT of a site":           {http.MethodPut, b + "sites/" + uSite1 + "/devices"},
		"PATCH":                   {http.MethodPatch, b + "info"},
		"HEAD":                    {http.MethodHead, b + "info"},
		"a port action":           {http.MethodGet, b + "sites/" + uSite1 + "/devices/" + uSwitch + "/interfaces/ports/1/actions"},
		"statistics":              {http.MethodGet, b + "sites/" + uSite1 + "/devices/" + uSwitch + "/statistics/latest"},
		"the wlans":               {http.MethodGet, b + "sites/" + uSite1 + "/wifi/broadcasts"},
		"another API":             {http.MethodGet, "https://" + host + "/proxy/network/api/s/default/stat/device"},
		"a dot segment":           {http.MethodGet, b + "sites/" + uSite1 + "/devices/../../../info"},
		"an encoded slash":        {http.MethodGet, b + "sites/" + uSite1 + "%2Fdevices"},
		"an id of no uuid":        {http.MethodGet, b + "sites/default/devices"},
		"a filter":                {http.MethodGet, b + "sites?filter=name.eq('x')"},
		"another host":            {http.MethodGet, "https://192.0.2.1:" + strconv.Itoa(port) + unifiBase + "/v1/info"},
		"plain HTTP":              {http.MethodGet, "http://" + host + unifiBase + "/v1/info"},
		"a user in the URL":       {http.MethodGet, "https://u:p@" + host + unifiBase + "/v1/info"},
		"a query on the info":     {http.MethodGet, b + "info?limit=1"},
		"a query of another form": {http.MethodGet, b + "sites?offset=0&limit=200"},
	}
	for name, cs := range cases {
		t.Run(name, func(t *testing.T) {
			u, err := url.Parse(cs.url)
			if err != nil {
				t.Fatal(err)
			}
			req := &http.Request{Method: cs.method, URL: u, Header: http.Header{}}
			if _, err := c.send(req); !errors.Is(err, ErrNotAllowed) || strings.Contains(err.Error(), uKey) {
				t.Errorf("%s %s = %v, want ErrNotAllowed without the key", cs.method, cs.url, err)
			}
		})
	}
	if asked := s.asked(); len(asked) != 0 || c.sent != 0 {
		t.Errorf("the client sent %v", asked)
	}
	// What the view reads goes through, with the key.
	req, _ := http.NewRequest(http.MethodGet, b+"sites/"+uSite1+"/devices/"+uSwitch, nil)
	resp, err := c.send(req)
	if err != nil {
		t.Fatalf("details = %v", err)
	}
	_ = resp.Body.Close()
	if asked := s.asked(); len(asked) != 1 || s.keys[0] != uKey || c.sent != 1 {
		t.Errorf("asked %v with %q", asked, s.keys)
	}
}

func TestUnifiNetworkTakesOnlyItsKeyHeader(t *testing.T) {
	port := serveUnifi(t, aSchool())
	cases := map[string]appCredential{
		"no credential":    {},
		"bearer":           {use: useBearer, secret: uKey},
		"another header":   {use: "header:Authorization", secret: uKey},
		"an empty key":     {use: "header:X-API-KEY"},
		"a key over lines": {use: "header:X-API-KEY", secret: uKey + "\r\nX-Other: 1"},
	}
	for name, c := range cases {
		if _, err := unifiNetwork(context.Background(), uosUnit(port), c); !errors.Is(err, ErrInvalid) ||
			strings.Contains(err.Error(), uKey) {
			t.Errorf("%s = %v, want ErrInvalid without the key", name, err)
		}
	}
	if _, err := unifiNetwork(context.Background(), uosUnit(port), appCredential{use: "header:x-api-key", secret: uKey}); err != nil {
		t.Errorf("the header in lower case = %v", err)
	}
	p := appProbe("unifi_network", &Target{Kind: kindUnit, Name: "uosserver.service", PortHint: port}, "offline")
	p.Credential = &Credential{Ref: "unifi", Use: "header:X-API-KEY"}
	if got, err := appSensor(context.Background(), p, uKey); err != nil || got["offline"] != int64(3) {
		t.Errorf("through the app sensor = %v, %v", got, err)
	}
	p.Target = &Target{Kind: kindContainer, Name: "uosserver"}
	if _, err := appSensor(context.Background(), p, uKey); !errors.Is(err, ErrInvalid) {
		t.Errorf("a container target = %v, want ErrInvalid", err)
	}
}

func TestUnifiNetworkTakesTheDefaultPortAndNoOther(t *testing.T) {
	var asked Target
	old := unifiEndpoint
	unifiEndpoint = func(_ context.Context, t Target) (endpoint, error) {
		asked = t
		return endpoint{addr: netip.MustParseAddr("127.0.0.1"), port: 8080}, nil
	}
	t.Cleanup(func() { unifiEndpoint = old })

	_, err := unifiNetwork(context.Background(), Target{Kind: kindUnit, Name: "uosserver.service"}, uosKey)

	if asked.PortHint != unifiPort || !errors.Is(err, ErrUnsupported) {
		t.Errorf("asked port %d, error %v; want %d and ErrUnsupported", asked.PortHint, err, unifiPort)
	}
	if _, err := unifiNetwork(context.Background(), Target{Kind: kindUnit, Name: "uosserver.service", Scheme: "http"}, uosKey); !errors.Is(err, ErrInvalid) {
		t.Errorf("scheme http = %v, want ErrInvalid", err)
	}
}

func TestUnifiNetworkErrorsNameNoAnswer(t *testing.T) {
	cases := map[string]struct {
		answer string
		want   string
	}{
		"no JSON":             {`School 1b2c is up`, "no info"},
		"no version":          {`{"name":"School 1b2c"}`, "no info"},
		"a page of no count":  {`{"applicationVersion":"1","data":[{"id":"School 1b2c"}],"totalCount":1}`, "no sites"},
		"an id of no uuid":    {`{"applicationVersion":"1","count":1,"data":[{"id":"School 1b2c"}],"totalCount":1}`, "no sites"},
		"fewer than it says":  {`{"applicationVersion":"1","count":0,"data":[],"totalCount":3}`, "fewer than it counts"},
		"a negative total":    {`{"applicationVersion":"1","count":0,"data":[],"totalCount":-1}`, "no sites"},
		"a count of the data": {`{"applicationVersion":"1","count":2,"data":[{"id":"School 1b2c"}],"totalCount":2}`, "no sites"},
	}
	for name, c := range cases {
		t.Run(name, func(t *testing.T) {
			s := &unifiServer{answer: func(w http.ResponseWriter, _ *http.Request) { _, _ = fmt.Fprint(w, c.answer) }}
			port := serveUnifi(t, s)
			_, err := unifiNetwork(context.Background(), uosUnit(port), uosKey)
			if err == nil || !strings.Contains(err.Error(), c.want) || strings.Contains(err.Error(), "School") ||
				strings.Contains(err.Error(), uKey) {
				t.Fatalf("error %v, want %q and no name", err, c.want)
			}
		})
	}
	s := &unifiServer{answer: func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusInternalServerError)
		_, _ = fmt.Fprint(w, `{"message":"School 1b2c broke"}`)
	}}
	port := serveUnifi(t, s)
	if _, err := unifiNetwork(context.Background(), uosUnit(port), uosKey); err == nil ||
		!strings.Contains(err.Error(), "HTTP 500") || strings.Contains(err.Error(), "School") {
		t.Errorf("HTTP 500 = %v", err)
	}
}
