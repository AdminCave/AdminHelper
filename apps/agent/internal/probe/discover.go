// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package probe

import (
	"context"
	"net"
	"net/netip"
	"strings"
)

// What the discovery of this host reads through the guard: its listening TCP sockets, the processes
// they belong to and the protocol a port speaks.

// Listener is a listening TCP socket of this host and the process it belongs to (0: unknown).
type Listener struct {
	Addr netip.Addr
	Port uint16
	PID  int32
}

// Listeners returns the listening TCP sockets of this host, the guard's snapshot of at most
// listenerTTL.
func Listeners(ctx context.Context) ([]Listener, error) {
	list, err := currentListeners(ctx)
	if err != nil {
		return nil, err
	}
	out := make([]Listener, len(list))
	for i, l := range list {
		out[i] = Listener{Addr: l.addr, Port: l.port, PID: l.pid}
	}
	return out, nil
}

// ProcessName returns the name of the process pid in the form the guard compares names in, "" if
// it cannot be read.
func ProcessName(ctx context.Context, pid int32) string {
	name, err := processName(ctx, pid)
	if err != nil {
		return ""
	}
	return processKey(name)
}

// NeverProbed says whether no probe ever connects to port, or to a port of the process name.
func NeverProbed(port uint16, name string) bool {
	return blockedPort(port) || neverProbed(name)
}

// RecognizePort recognizes the protocol of the service that listens on port beyond loopback, as the
// sensor proto does with protocol auto, and returns its name: http, https, smtp, imap, pop3, ftp and
// their TLS forms, ssh, redis, banner, tls, unknown or closed. A port the guard refuses is an error
// that wraps ErrNotAllowed.
func RecognizePort(ctx context.Context, port uint16) (string, error) {
	// Only the listeners beyond loopback: the one on 127.0.0.1 may be another service. One on the
	// unspecified address is reached on loopback, the same socket.
	ep, err := hostEndpoint(ctx, Target{Kind: kindPort, PortHint: int(port)}, func(l listener) bool {
		return l.port == port && !l.addr.IsLoopback()
	})
	if err != nil {
		return "", err
	}
	res, err := recognize(ctx, func(ctx context.Context) (net.Conn, error) { return dialTarget(ctx, ep) })
	if err != nil {
		return "", err
	}
	name, _, _ := strings.Cut(res.detail, ":")
	return name, nil
}
