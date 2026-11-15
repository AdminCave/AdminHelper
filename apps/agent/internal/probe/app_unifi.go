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
	"net/netip"
	"net/url"
	"regexp"
	"slices"
	"strconv"
	"strings"
)

const (
	// unifiPort is the HTTPS port of a UniFi OS Server (5.1.42).
	unifiPort = 11443
	// unifiBase is where the Network application serves its Integration API.
	unifiBase = "/proxy/network/integration"
	// unifiKeyHeader is the header the Integration API takes its key in.
	unifiKeyHeader = "X-API-KEY"
	// unifiMaxRequests caps the requests of one run of the view.
	unifiMaxRequests = 20
	// unifiMaxDetails caps the offline devices whose details the view asks for their uplink.
	unifiMaxDetails = 8
	// unifiPageSize is the largest page the Integration API returns.
	unifiPageSize = 200
)

// unifiEndpoint finds where the UniFi OS Server listens; tests point it at their server.
var unifiEndpoint = unifiResolve

// unifiResolve is resolve, but a unit owns the listeners of unifiOwner: those of its rootless
// Podman as well as its own.
func unifiResolve(ctx context.Context, t Target) (endpoint, error) {
	if t.Kind != kindUnit {
		return resolve(ctx, t)
	}
	owns, err := unifiOwner(ctx, t.Name)
	if err != nil {
		return endpoint{}, err
	}
	return ruledEndpoint(ctx, t, func() func(listener) bool {
		return func(l listener) bool { return owns(l.pid) }
	})
}

// unifiUUID is the form of the ids of sites and devices; only ids of this form go into a path.
const unifiUUID = `[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}`

var (
	// unifiPaths are the only paths the client sends a request to: the key of the Integration API can
	// restart, power-cycle, reset and reconfigure devices, and every endpoint that does so lies elsewhere
	// or takes another method.
	unifiPaths = regexp.MustCompile(`^` + unifiBase + `/v1/(info|sites|pending-devices|sites/` + unifiUUID +
		`/(devices|clients)|sites/` + unifiUUID + `/devices/` + unifiUUID + `)$`)
	// unifiQuery is the only query the client sends: a page.
	unifiQuery = regexp.MustCompile(`^(limit=[0-9]{1,3}&offset=[0-9]{1,9})?$`)
	unifiID    = regexp.MustCompile(`^` + unifiUUID + `$`)
)

// errUnifiRedirect ends a redirect of the Integration API: the key is not to follow it anywhere.
var errUnifiRedirect = fmt.Errorf("%w: the UniFi Network application answers with a redirect", ErrNotAllowed)

// unifiClient asks the Integration API of this host's UniFi OS Server, and nothing else: only GET,
// only the paths of unifiPaths with a page as query, only at its own host and port, no redirect, at
// most unifiMaxRequests requests. No error quotes the key or an answer.
type unifiClient struct {
	http   *http.Client
	host   string
	key    string
	sent   int
	budget int
}

// get asks path with query and decodes the JSON answer into out; what names the answer in errors.
func (c *unifiClient) get(ctx context.Context, path string, query url.Values, what string, out any) error {
	u := url.URL{Scheme: "https", Host: c.host, Path: path, RawQuery: query.Encode()}
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, u.String(), nil)
	if err != nil {
		return errors.New("the request to the UniFi Network application cannot be built")
	}
	resp, err := c.send(req)
	if err != nil {
		return netErr(ctx, err)
	}
	defer resp.Body.Close()
	switch resp.StatusCode {
	case http.StatusOK:
	case http.StatusUnauthorized, http.StatusForbidden:
		return fmt.Errorf("%w: HTTP %d", ErrDenied, resp.StatusCode)
	default:
		return fmt.Errorf("the UniFi Network application answers %s with HTTP %d", what, resp.StatusCode)
	}
	if err := json.NewDecoder(resp.Body).Decode(out); err != nil {
		return netErr(ctx, fmt.Errorf("the UniFi Network application answers %s with no %s", what, what))
	}
	return nil
}

// send sends req with the key if it is one the client may send; else it sends nothing.
func (c *unifiClient) send(req *http.Request) (*http.Response, error) {
	u := req.URL
	switch {
	case req.Method != http.MethodGet:
		return nil, fmt.Errorf("%w: method %s to the UniFi Network application", ErrNotAllowed, req.Method)
	case u.Scheme != "https" || u.Host != c.host || u.User != nil || u.Fragment != "" ||
		!unifiPaths.MatchString(u.Path) || u.RawPath != "" || !unifiQuery.MatchString(u.RawQuery):
		return nil, fmt.Errorf("%w: a request outside the read paths of the UniFi Network application", ErrNotAllowed)
	case c.sent >= c.budget:
		return nil, fmt.Errorf("%w: more than %d requests to the UniFi Network application", ErrUnsupported, c.budget)
	}
	c.sent++
	req.Header.Set(unifiKeyHeader, c.key)
	resp, err := c.http.Do(req)
	if err != nil {
		var ue *url.Error
		if errors.As(err, &ue) {
			err = ue.Err
		}
		return nil, err
	}
	return resp, nil
}

// unifiPage is a page of a list of the Integration API.
type unifiPage[T any] struct {
	Count      *int64 `json:"count"`
	TotalCount *int64 `json:"totalCount"`
	Data       []T    `json:"data"`
}

// list reads every page of the list at path.
func unifiList[T any](ctx context.Context, c *unifiClient, path, what string) ([]T, error) {
	var all []T
	for {
		var p unifiPage[T]
		q := url.Values{"offset": {strconv.Itoa(len(all))}, "limit": {strconv.Itoa(unifiPageSize)}}
		if err := c.get(ctx, path, q, what, &p); err != nil {
			return nil, err
		}
		if p.TotalCount == nil || *p.TotalCount < 0 || p.Count == nil || *p.Count != int64(len(p.Data)) {
			return nil, fmt.Errorf("the UniFi Network application answers %s with no %s", what, what)
		}
		all = append(all, p.Data...)
		if int64(len(all)) >= *p.TotalCount {
			return all, nil
		}
		if len(p.Data) == 0 {
			return nil, fmt.Errorf("the UniFi Network application answers %s with fewer than it counts", what)
		}
	}
}

// unifiTotal is the totalCount of the list at path, read with a page of one.
func unifiTotal(ctx context.Context, c *unifiClient, path, what string) (int64, error) {
	var p struct {
		TotalCount *int64 `json:"totalCount"`
	}
	q := url.Values{"offset": {"0"}, "limit": {"1"}}
	if err := c.get(ctx, path, q, what, &p); err != nil {
		return 0, err
	}
	if p.TotalCount == nil || *p.TotalCount < 0 {
		return 0, fmt.Errorf("the UniFi Network application answers %s with no %s", what, what)
	}
	return *p.TotalCount, nil
}

// unifiDevice is what unifi_network reads of an adopted device; its name, MAC and address are
// never read.
type unifiDevice struct {
	ID                string   `json:"id"`
	State             string   `json:"state"`
	Features          []string `json:"features"`
	FirmwareUpdatable bool     `json:"firmwareUpdatable"`
}

// unifiOffline are the states of a device the Network application does not reach.
var unifiOffline = []string{"OFFLINE", "CONNECTION_INTERRUPTED", "ISOLATED"}

// unifiNetwork reads the state of the devices the UniFi Network application of this host's UniFi OS
// Server manages, through its Integration API on the server's own HTTPS port: the sites, the adopted
// devices, those offline, those offline whose uplink is not itself offline (offline_root: the cause,
// not what hangs behind it), the gateways offline, those updating, those with a firmware update, the
// devices pending adoption and the clients. Only counts: never a name, a MAC, an address or an id.
// The key goes in header X-API-KEY only to the port the server owns (secretGuard).
//
// Integration API v11.0.97 (developer.ui.com, OpenAPI): GET /v1/info, /v1/sites,
// /v1/sites/{siteId}/devices (offset, limit ≤ 200, totalCount), /v1/sites/{siteId}/devices/{deviceId}
// (uplink.deviceId), /v1/pending-devices, /v1/sites/{siteId}/clients. An offline device whose details
// are not asked (more than unifiMaxDetails, or the request budget is spent) counts as a cause. Tested
// against UniFi OS Server 5.1.42 with Network 10.5.67: the paths, the header and the pages as above.
func unifiNetwork(ctx context.Context, t Target, c appCredential) (map[string]any, error) {
	if name, ok := strings.CutPrefix(c.use, useHeader); !ok || !strings.EqualFold(name, unifiKeyHeader) {
		return nil, fmt.Errorf("%w: view unifi_network takes its key in header %s", ErrInvalid, unifiKeyHeader)
	}
	if c.secret == "" || strings.ContainsAny(c.secret, "\r\n\x00") {
		return nil, fmt.Errorf("%w: the key of the UniFi Network application must be non-empty and on one line", ErrInvalid)
	}
	if t.Scheme != "" && t.Scheme != "https" {
		return nil, fmt.Errorf("%w: view unifi_network takes no scheme %q", ErrInvalid, t.Scheme)
	}
	port := unifiPort
	if t.PortHint > 0 {
		port = t.PortHint
	}
	t.PortHint = port
	ep, err := unifiEndpoint(ctx, t)
	if err != nil {
		return nil, err
	}
	if int(ep.port) != port {
		return nil, fmt.Errorf("%w: %s %s does not listen on the HTTPS port %d", ErrUnsupported, t.Kind, targetName(t), port)
	}
	// The certificate of the server is the tls sensor's business; UniFi OS makes its own.
	hc := secretGuard(ep).HTTPClient(&tls.Config{InsecureSkipVerify: true}) //nolint:gosec // the tls sensor checks certificates
	hc.CheckRedirect = func(*http.Request, []*http.Request) error { return errUnifiRedirect }
	cl := &unifiClient{http: hc, host: netip.AddrPortFrom(ep.addr, ep.port).String(), key: c.secret, budget: unifiMaxRequests}
	return unifiValues(ctx, cl)
}

// unifiValues asks the Integration API through c and counts.
func unifiValues(ctx context.Context, c *unifiClient) (map[string]any, error) {
	var info struct {
		ApplicationVersion *string `json:"applicationVersion"`
	}
	if err := c.get(ctx, unifiBase+"/v1/info", nil, "info", &info); err != nil {
		return nil, err
	}
	if info.ApplicationVersion == nil {
		return nil, errors.New("the UniFi Network application answers info with no info")
	}
	sites, err := unifiList[struct {
		ID string `json:"id"`
	}](ctx, c, unifiBase+"/v1/sites", "sites")
	if err != nil {
		return nil, err
	}
	type siteDevices struct {
		id      string
		devices []unifiDevice
	}
	all := make([]siteDevices, 0, len(sites))
	for _, s := range sites {
		if !unifiID.MatchString(s.ID) {
			return nil, errors.New("the UniFi Network application answers sites with no sites")
		}
		ds, err := unifiList[unifiDevice](ctx, c, unifiBase+"/v1/sites/"+s.ID+"/devices", "devices")
		if err != nil {
			return nil, err
		}
		for _, d := range ds {
			if !unifiID.MatchString(d.ID) || d.State == "" {
				return nil, errors.New("the UniFi Network application answers devices with no devices")
			}
		}
		all = append(all, siteDevices{id: s.ID, devices: ds})
	}
	// The details of offline devices take what the budget leaves after the pending devices and the
	// clients of every site.
	details := min(unifiMaxDetails, c.budget-c.sent-1-len(sites))
	var devices, offline, root, gateways, updating, updatable int64
	for _, s := range all {
		down := map[string]bool{}
		for _, d := range s.devices {
			down[d.ID] = slices.Contains(unifiOffline, d.State)
		}
		for _, d := range s.devices {
			devices++
			if d.State == "UPDATING" {
				updating++
			}
			if d.FirmwareUpdatable {
				updatable++
			}
			if !down[d.ID] {
				continue
			}
			offline++
			if slices.Contains(d.Features, "gateway") {
				gateways++
			}
			cause := true
			if details > 0 {
				details--
				var det struct {
					Uplink *struct {
						DeviceID string `json:"deviceId"`
					} `json:"uplink"`
				}
				if err := c.get(ctx, unifiBase+"/v1/sites/"+s.id+"/devices/"+d.ID, nil, "device details", &det); err != nil {
					return nil, err
				}
				cause = det.Uplink == nil || !down[det.Uplink.DeviceID]
			}
			if cause {
				root++
			}
		}
	}
	pending, err := unifiTotal(ctx, c, unifiBase+"/v1/pending-devices", "pending devices")
	if err != nil {
		return nil, err
	}
	var clients int64
	for _, s := range all {
		n, err := unifiTotal(ctx, c, unifiBase+"/v1/sites/"+s.id+"/clients", "clients")
		if err != nil {
			return nil, err
		}
		clients += n
	}
	return map[string]any{
		"sites": int64(len(sites)), "devices": devices, "offline": offline, "offline_root": root,
		"gateways_offline": gateways, "updating": updating, "firmware_updatable": updatable,
		"pending": pending, "clients": clients,
	}, nil
}
