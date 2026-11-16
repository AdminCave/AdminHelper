// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package probe

import (
	"bytes"
	"context"
	"fmt"
	"math"
	"slices"
	"sync"
	"time"
)

// vhostTTL is how long the list of vhosts is kept: the certificate checks of many domains run at the
// same time, and each would else dump the configuration of the web servers once more.
const vhostTTL = 60 * time.Second

// vhostCache holds the last list of vhosts and when it was read.
var vhostCache struct {
	sync.Mutex
	at   time.Time
	list []Vhost
	err  error
}

// cachedVhosts is WebVhosts, at most vhostTTL old. A caller whose context ended while it waited for the
// lock reads nothing, and a read the caller's own context cut short is not kept: the next caller, with
// a context of its own, would else get that error for a minute.
func cachedVhosts(ctx context.Context) ([]Vhost, error) {
	vhostCache.Lock()
	defer vhostCache.Unlock()
	if !vhostCache.at.IsZero() && time.Since(vhostCache.at) < vhostTTL {
		return vhostCache.list, vhostCache.err
	}
	if err := ctx.Err(); err != nil {
		return nil, err
	}
	list, err := WebVhosts(ctx)
	if ctx.Err() != nil {
		return list, err
	}
	vhostCache.list, vhostCache.err = list, err
	vhostCache.at = time.Now()
	return list, err
}

// servedVhost finds the vhost t again among those the web servers of this host serve (cachedVhosts), by
// name and port. A probe of a vhost sends its name as Host and SNI to a port of this host; a name no
// web server here serves would let it pose as any site the web server answers or passes on.
func servedVhost(ctx context.Context, t Target) (Vhost, error) {
	list, lerr := cachedVhosts(ctx)
	i := slices.IndexFunc(list, func(v Vhost) bool { return v.Name == t.Name && int(v.Port) == t.PortHint })
	switch {
	case i < 0 && lerr != nil:
		return Vhost{}, lerr
	case i < 0:
		return Vhost{}, fmt.Errorf("no web server of this host serves %s on port %d", t.Name, t.PortHint)
	}
	return list[i], nil
}

// webVhostCert compares the certificate a vhost's file holds with the one its web server serves.
// It finds the vhost again in the configuration (cachedVhosts): the server never names the file. It
// shakes hands with the vhost's port through the guard, the domain as SNI, and reads the served
// certificate as the tls sensor does (served_days_left, hostname_ok for the domain, chain_ok). From
// the file it reads only the first certificate (file_days_left); a private key in the same file it
// skips unparsed, a key file it never opens. reload_missing: the file holds another certificate than
// is served, and one that lasts longer, so the server was not reloaded since it was renewed. A vhost
// whose file the agent does not know (none in its block, or a path that is no plain absolute one)
// gives the served values alone.
func webVhostCert(ctx context.Context, t Target) (map[string]any, error) {
	v, err := servedVhost(ctx, t)
	if err != nil {
		return nil, err
	}
	if !v.TLS {
		return nil, fmt.Errorf("%s is served without TLS on port %d", t.Name, t.PortHint)
	}
	ep, err := resolve(ctx, t)
	if err != nil {
		return nil, err
	}
	conn, err := dialTarget(ctx, ep)
	if err != nil {
		return nil, err
	}
	s := newSession(ctx, conn)
	defer s.end()
	if err := s.startTLS(t.Name, 0); err != nil {
		return nil, protoErr("tls", err)
	}
	certs := s.tc.ConnectionState().PeerCertificates
	served, err := certValues(certs, t.Name)
	if err != nil {
		return nil, err
	}
	values := map[string]any{
		"served_days_left": served["days_left"],
		"hostname_ok":      served["hostname_ok"],
		"chain_ok":         served["chain_ok"],
	}
	if v.cert == "" || !safePath.MatchString(v.cert) {
		return values, nil
	}
	data, err := untilDone(ctx, func() ([]byte, error) { return readCapped(v.cert, maxCertFileBytes) })
	if err != nil {
		return nil, fmt.Errorf("the certificate file of %s %w", t.Name, err)
	}
	file, err := leafCert(data)
	if err != nil {
		return nil, fmt.Errorf("the certificate file of %s %w", t.Name, err)
	}
	values["file_days_left"] = int64(math.Floor(file.NotAfter.Sub(now()).Hours() / 24))
	values["reload_missing"] = !bytes.Equal(file.Raw, certs[0].Raw) && file.NotAfter.After(certs[0].NotAfter)
	return values, nil
}
