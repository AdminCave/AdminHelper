// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package probe

import (
	"context"
	"errors"
	"fmt"
	"net"
	"net/http"
	"sync"
	"time"
)

func init() {
	sensors["unixsocket"] = unixSocketSensor
}

// maxSocketPath is the longest path of a unix socket: sun_path holds 108 bytes, the last a NUL.
const maxSocketPath = 107

// errNoListener is a unix socket that does not exist or that nobody serves.
var errNoListener = errors.New("nobody serves the socket")

// unixSocketSensor connects to a unix socket of this host: whether it accepts (connected) and how long
// it took; with protocol http, redis, fastcgi or haproxy also what the service answers. A socket served
// by a process the agent never probes is not allowed (dialUnix).
func unixSocketSensor(ctx context.Context, p Probe, secret string) (map[string]any, error) {
	if err := noTarget(p); err != nil {
		return nil, err
	}
	if err := knownParams(p, "path", "protocol", "http_path", "status_path"); err != nil {
		return nil, err
	}
	path, err := textParam(p, "path", "")
	if err != nil {
		return nil, err
	}
	if !validLocalPath(path) || len(path) > maxSocketPath {
		return nil, fmt.Errorf("%w: sensor unixsocket needs an absolute local path of at most %d bytes", ErrInvalid, maxSocketPath)
	}
	protocol, err := choiceParam(p, "protocol", "connect", "connect", "http", "redis", "fastcgi", "haproxy")
	if err != nil {
		return nil, err
	}
	httpPath, err := requestPath(p, "http_path", "/", 512, false)
	if err != nil {
		return nil, err
	}
	if err := statusPath(p, protocol); err != nil {
		return nil, err
	}
	var uses []string
	switch protocol {
	case "http":
		uses = []string{useBearer, useBasic, useHeader}
	case "redis":
		uses = []string{useRedisAuth, useRedisACL}
	}
	use, err := credentialUse(p, uses...)
	if err != nil {
		return nil, err
	}
	start := time.Now()
	conn, err := dialUnix(ctx, path)
	switch {
	case errors.Is(err, errNoListener) && !ended(ctx):
		return map[string]any{"connected": false}, nil
	case err != nil:
		return nil, netErr(ctx, err)
	}
	conn = bind(ctx, conn)
	switch protocol {
	case "connect":
		took := time.Since(start)
		_ = conn.Close()
		return map[string]any{"connected": true, "duration_ms": took.Milliseconds()}, nil
	case "http":
		return unixHTTP(ctx, conn, path, httpPath, use, secret, p.Fields)
	}
	s := newSession(ctx, conn)
	defer s.end()
	res, err := runProto(s, protocol, protoOpts{use: use, secret: secret})
	if err != nil {
		return nil, err
	}
	if !res.ok {
		return nil, errors.New(res.detail)
	}
	values := map[string]any{"connected": true, "duration_ms": time.Since(start).Milliseconds()}
	if res.data != nil {
		values["data"] = res.data
	}
	return values, nil
}

// unixHTTP sends a GET for httpPath over conn, a connection to the socket path; a redirect connects
// anew (dialUnix).
func unixHTTP(ctx context.Context, conn net.Conn, path, httpPath, use, secret string, fields []string) (map[string]any, error) {
	var mu sync.Mutex
	first := conn
	dial := func(ctx context.Context, _, _ string) (net.Conn, error) {
		mu.Lock()
		c := first
		first = nil
		mu.Unlock()
		if c != nil {
			return c, nil
		}
		c, err := dialUnix(ctx, path)
		if err != nil {
			return nil, err
		}
		return bind(ctx, c), nil
	}
	values, err := fetch(ctx, httpClient(dial, nil), http.MethodGet, "http://localhost"+httpPath, "", use, secret, fields)
	mu.Lock()
	if first != nil {
		_ = first.Close()
	}
	mu.Unlock()
	if err != nil {
		return nil, err
	}
	values["connected"] = true
	return values, nil
}
