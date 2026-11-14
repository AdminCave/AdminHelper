// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package probe

import (
	"bytes"
	"context"
	"errors"
	"fmt"
	"io/fs"
	"runtime"
	"slices"
	"strconv"
	"strings"
)

const (
	// haproxyPortsConfig is the configuration the HAProxy of the FreeBSD ports starts with.
	haproxyPortsConfig = "/usr/local/etc/haproxy.conf"
	// opnsenseHAProxySocket is the stats socket the OPNsense plugin os-haproxy configures.
	opnsenseHAProxySocket = "/var/run/haproxy.socket"
	// maxHAProxyConfig caps the configuration haproxySocket reads.
	maxHAProxyConfig = 4 << 20
	// haproxyMaint are the bits of srv_admin_state that put a server in maintenance: set by the
	// runtime API (0x01), inherited from a tracked server (0x02), configured as disabled (0x04), by a
	// failed resolution (0x20, 0x40). 0x08 and 0x10 drain a server, which still serves its sessions.
	haproxyMaint = 0x01 | 0x02 | 0x04 | 0x20 | 0x40
)

var (
	// haproxyConfigs are the configurations that may name the stats socket; tests stand in their own.
	haproxyConfigs = []string{haproxyConfig, haproxyPortsConfig}
	// haproxyDial connects to the stats socket; tests stand in their own.
	haproxyDial = dialUnix
)

// haproxyServers counts from HAProxy's stats socket the backends, those that are down, the servers,
// those that are down and those in maintenance, never a name. The socket is one the configuration
// already declares (stats socket); without one the view is unsupported, it adds none. The two
// commands only read, at any level of the socket.
//
// Management Guide 9.3 (docs.haproxy.org/3.2/management.html): "show stat [<iid> <type> <sid>]",
// type 2 the backends, their status UP or DOWN; "show servers state", version 1, its header after
// "# ", srv_op_state 0 a stopped server, srv_admin_state the flags of haproxyMaint. Checked against
// HAProxy 3.4.7.
func haproxyServers(ctx context.Context, t Target) (map[string]any, error) {
	if webServer(t.Name) != "haproxy" {
		return nil, fmt.Errorf("%w: unit %s is no haproxy", ErrUnsupported, t.Name)
	}
	sock, err := haproxySocket()
	if err != nil {
		return nil, err
	}
	stat, err := haproxyAsk(ctx, sock, "show stat -1 2 -1")
	if err != nil {
		return nil, err
	}
	backends, backendsDown, ok := haproxyBackends(stat)
	if !ok {
		return nil, errors.New("no answer to show stat")
	}
	state, err := haproxyAsk(ctx, sock, "show servers state")
	if err != nil {
		return nil, err
	}
	servers, down, maint, ok := haproxyServerStates(state)
	if !ok {
		return nil, errors.New("no answer to show servers state")
	}
	return map[string]any{
		"backends": backends, "backends_down": backendsDown,
		"servers": servers, "servers_down": down, "servers_maint": maint,
	}, nil
}

// haproxySocket is the first unix stats socket a configuration of haproxyConfigs declares; on FreeBSD
// without one the socket of the OPNsense plugin.
func haproxySocket() (string, error) {
	for _, name := range haproxyConfigs {
		b, err := readCapped(name, maxHAProxyConfig)
		switch {
		case errors.Is(err, fs.ErrNotExist):
			continue
		case err != nil:
			return "", fmt.Errorf("the configuration %s %w", name, err)
		}
		if sock, ok := statsSocket(b); ok {
			return sock, nil
		}
	}
	if runtime.GOOS == "freebsd" {
		return opnsenseHAProxySocket, nil
	}
	return "", fmt.Errorf("%w: the configuration of haproxy declares no stats socket", ErrUnsupported)
}

// statsSocket reads the first "stats socket <path>" of a configuration with an absolute path, plain
// or as unix@<path>; an address of another family (ipv4@, abns@, fd@) is no socket of this host's
// file system.
func statsSocket(cfg []byte) (string, bool) {
	for line := range strings.Lines(string(cfg)) {
		f := strings.Fields(line)
		if i := slices.IndexFunc(f, func(w string) bool { return strings.HasPrefix(w, "#") }); i >= 0 {
			f = f[:i]
		}
		if len(f) < 3 || f[0] != "stats" || f[1] != "socket" {
			continue
		}
		path := strings.TrimPrefix(strings.Trim(f[2], `"'`), "unix@")
		if validLocalPath(path) && len(path) <= maxSocketPath {
			return path, true
		}
	}
	return "", false
}

// haproxyAsk sends cmd to the stats socket sock and returns the answer; a socket nobody serves is
// unsupported.
func haproxyAsk(ctx context.Context, sock, cmd string) ([]byte, error) {
	conn, err := haproxyDial(ctx, sock)
	switch {
	case errors.Is(err, errNoListener) && !ended(ctx):
		return nil, fmt.Errorf("%w: nobody serves the stats socket of haproxy", ErrUnsupported)
	case err != nil:
		return nil, netErr(ctx, err)
	}
	s := newSession(ctx, bind(ctx, conn))
	defer s.end()
	return haproxyAnswer(s, cmd)
}

// haproxyBackends counts the backends of show stat and those whose status is DOWN.
func haproxyBackends(b []byte) (backends, down int, ok bool) {
	data, ok := haproxyStat(b)
	if !ok {
		return 0, 0, false
	}
	for _, proxy := range data {
		row, _ := proxy.(map[string]any)["BACKEND"].(map[string]any)
		if row == nil {
			continue
		}
		backends++
		if row["status"] == "DOWN" {
			down++
		}
	}
	return backends, down, true
}

// haproxyServerStates counts the servers of show servers state, those stopped outside maintenance
// (down) and those in maintenance (maint).
func haproxyServerStates(b []byte) (servers, down, maint int, ok bool) {
	version, rest, _ := bytes.Cut(b, []byte("\n"))
	header, rest, _ := bytes.Cut(rest, []byte("\n"))
	cols, found := bytes.CutPrefix(header, []byte("# "))
	if string(bytes.TrimSpace(version)) != "1" || !found {
		return 0, 0, 0, false
	}
	names := strings.Fields(string(cols))
	opCol, adminCol := slices.Index(names, "srv_op_state"), slices.Index(names, "srv_admin_state")
	if opCol < 0 || adminCol < 0 {
		return 0, 0, 0, false
	}
	for line := range strings.Lines(string(rest)) {
		f := strings.Fields(line)
		if len(f) == 0 {
			continue
		}
		if len(f) <= max(opCol, adminCol) {
			return 0, 0, 0, false
		}
		op, err1 := strconv.Atoi(f[opCol])
		admin, err2 := strconv.Atoi(f[adminCol])
		if err1 != nil || err2 != nil {
			return 0, 0, 0, false
		}
		servers++
		switch {
		case admin&haproxyMaint != 0:
			maint++
		case op == 0:
			down++
		}
	}
	return servers, down, maint, true
}
