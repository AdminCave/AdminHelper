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
)

// esHTTPPort is the HTTP port of Elasticsearch by default (http.port 9200).
const esHTTPPort = 9200

// esEndpoint finds where Elasticsearch listens; tests point it at their server.
var esEndpoint = resolve

// esNodeStats is the part of GET /_nodes/stats esNodes reads; filter_path leaves out the rest, names
// and addresses of the nodes among it.
type esNodeStats struct {
	Nodes *struct {
		Total  *int `json:"total"`
		Failed *int `json:"failed"`
	} `json:"_nodes"`
	ByID map[string]struct {
		JVM struct {
			Mem struct {
				HeapUsedPercent *int64 `json:"heap_used_percent"`
			} `json:"mem"`
		} `json:"jvm"`
		FS struct {
			Total struct {
				Total     *int64 `json:"total_in_bytes"`
				Available *int64 `json:"available_in_bytes"`
			} `json:"total"`
		} `json:"fs"`
	} `json:"nodes"`
}

// esNodes reads the node statistics of the Elasticsearch cluster of this host on its own HTTP port:
// the nodes, those that did not answer, the highest heap use of a node in percent and the highest
// share of a node's disks in use (of the space Elasticsearch may take, available_in_bytes). Never a
// name, an id or an address. A credential of use basic goes only to the port the target owns.
//
// Nodes stats API (elastic.co/docs/api/doc/elasticsearch/operation/operation-nodes-stats-metric):
// _nodes the count of nodes asked, answered and failed; per node jvm.mem.heap_used_percent and
// fs.total.{total,available}_in_bytes. Checked against Elasticsearch 8.19.0.
func esNodes(ctx context.Context, t Target, c appCredential) (map[string]any, error) {
	scheme := t.Scheme
	switch scheme {
	case "":
		scheme = "http"
	case "http", "https":
	default:
		return nil, fmt.Errorf("%w: view es_nodes takes no scheme %q", ErrInvalid, scheme)
	}
	port := esHTTPPort
	if t.PortHint > 0 {
		port = t.PortHint
	}
	t.PortHint = port
	ep, err := esEndpoint(ctx, t)
	if err != nil {
		return nil, err
	}
	// Without its HTTP port the target's one other port would be the transport port of the cluster.
	if int(ep.port) != port {
		return nil, fmt.Errorf("%w: %s %s does not listen on the HTTP port %d", ErrUnsupported, t.Kind, targetName(t), port)
	}
	u := url.URL{Scheme: scheme, Host: netip.AddrPortFrom(ep.addr, ep.port).String(), Path: "/_nodes/stats/jvm,fs",
		RawQuery: "filter_path=_nodes,nodes.*.jvm.mem.heap_used_percent,nodes.*.fs.total"}
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, u.String(), nil)
	if err != nil {
		return nil, errors.New("the request to Elasticsearch cannot be built")
	}
	if err := authorize(req, c.use, c.secret); err != nil {
		return nil, err
	}
	g := NewGuard(ep.extra...)
	if c.use != "" {
		g = secretGuard(ep)
	}
	// The certificate of the cluster is the tls sensor's business; Elasticsearch 8 makes its own.
	resp, err := g.HTTPClient(&tls.Config{InsecureSkipVerify: true}).Do(req) //nolint:gosec // the tls sensor checks certificates
	if err != nil {
		var ue *url.Error
		if errors.As(err, &ue) {
			err = ue.Err
		}
		return nil, netErr(ctx, err)
	}
	defer resp.Body.Close()
	switch resp.StatusCode {
	case http.StatusOK:
	case http.StatusUnauthorized, http.StatusForbidden:
		return nil, fmt.Errorf("%w: HTTP %d", ErrDenied, resp.StatusCode)
	default:
		return nil, fmt.Errorf("Elasticsearch answers /_nodes/stats with HTTP %d", resp.StatusCode)
	}
	var st esNodeStats
	if err := json.NewDecoder(resp.Body).Decode(&st); err != nil {
		return nil, netErr(ctx, errors.New("Elasticsearch answers /_nodes/stats with no node statistics"))
	}
	return esValues(st)
}

// esValues reduces the node statistics to the values of es_nodes.
func esValues(st esNodeStats) (map[string]any, error) {
	malformed := errors.New("Elasticsearch answers /_nodes/stats with no node statistics")
	if st.Nodes == nil || st.Nodes.Total == nil || st.Nodes.Failed == nil || len(st.ByID) == 0 {
		return nil, malformed
	}
	heap, disk := int64(0), int64(0)
	for _, n := range st.ByID {
		h, total, avail := n.JVM.Mem.HeapUsedPercent, n.FS.Total.Total, n.FS.Total.Available
		if h == nil || total == nil || avail == nil || *total <= 0 || *avail < 0 || *avail > *total {
			return nil, malformed
		}
		heap = max(heap, *h)
		disk = max(disk, int64(float64(*total-*avail)/float64(*total)*100))
	}
	return map[string]any{
		"nodes": *st.Nodes.Total, "nodes_failed": *st.Nodes.Failed,
		"heap_used_pct_max": heap, "disk_used_pct_max": disk,
	}, nil
}
