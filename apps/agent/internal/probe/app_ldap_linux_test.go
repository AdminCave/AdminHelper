// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package probe

import (
	"context"
	"errors"
	"net"
	"os"
	"reflect"
	"testing"
	"time"
)

func stubLDAPSockets(t *testing.T, paths ...string) {
	t.Helper()
	old := ldapSockets
	ldapSockets = paths
	t.Cleanup(func() { ldapSockets = old })
}

// The view goes through the guard of unix sockets: the socket of slapd is asked, one nobody serves is
// no slapd, and one of a process the agent never probes is refused.
func TestTheReplicationViewAsksSlapdAtItsUnixSocket(t *testing.T) {
	stubNow(t, time.Date(2026, 11, 13, 12, 0, 0, 0, time.UTC))
	h := servedBy(t, "slapd")
	log := &ldapLog{}
	path, _ := unixFake(t, replicatingSlapd().serve(log))
	stubLDAPSockets(t, path+".gone", path)

	got, err := ldapReplication(context.Background(), *unitTarget("slapd.service"))
	want := map[string]any{"contexts": 2, "csn_age_s": 30, "monitor": true, "consumers": 4, "disconnected": 2, "refreshing": 2}
	if err != nil || !reflect.DeepEqual(got, want) {
		t.Errorf("values %v, %v; want %v", got, err, want)
	}
	if requests, _ := log.heard(); len(requests) != 6 || requests[0].mech != "EXTERNAL" || requests[5].op != 0x42 {
		t.Errorf("heard %v, want a bind with SASL EXTERNAL, four searches and an unbind", requests)
	}

	stale := socketIn(t)
	ln, err := net.ListenUnix("unix", &net.UnixAddr{Name: stale, Net: "unix"})
	if err != nil {
		t.Fatal(err)
	}
	ln.SetUnlinkOnClose(false)
	_ = ln.Close()
	if _, err := os.Stat(stale); err != nil {
		t.Fatal(err)
	}
	stubLDAPSockets(t, stale, path+".gone")
	if _, err := ldapReplication(context.Background(), *unitTarget("slapd.service")); !errors.Is(err, ErrUnsupported) {
		t.Errorf("sockets nobody serves = %v, want ErrUnsupported", err)
	}

	h.names[int32(os.Getpid())] = "dockerd"
	stubLDAPSockets(t, path)
	if _, err := ldapReplication(context.Background(), *unitTarget("slapd.service")); !errors.Is(err, ErrNotAllowed) {
		t.Errorf("a socket of dockerd = %v, want ErrNotAllowed", err)
	}
}
