// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build linux

package probe

import (
	"context"
	"errors"
	"net"
	"os"
	"slices"
	"strings"
	"testing"
)

func TestListenInodesReadsTheListeningSocketsOfAPort(t *testing.T) {
	data := []byte(`  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode
   0: 00000000:0050 00000000:0000 0A 00000000:00000000 00:00000000 00000000     0        0 1111 1 0000000000000000 100 0 0 10 0
   1: 0100007F:0050 0100007F:9C40 01 00000000:00000000 00:00000000 00000000     0        0 2222 1 0000000000000000 20 4 30 10 -1
   2: 0100007F:1F90 00000000:0000 0A 00000000:00000000 00:00000000 00000000     0        0 3333 1 0000000000000000 100 0 0 10 0
   3: 0100007F:0050 00000000:0000 0A 00000000:00000000 00:00000000 00000000     0        0 4444 1 0000000000000000 100 0 0 10 0
`)
	if got := listenInodes(data, 80); !slices.Equal(got, []string{"1111", "4444"}) {
		t.Fatalf("inodes on port 80 = %v, want the two listening sockets, not the connected one", got)
	}
	if got := listenInodes(data, 443); len(got) != 0 {
		t.Fatalf("inodes on port 443 = %v, want none", got)
	}
}

func TestNamespaceProcessesFindsTheProcessOfAListeningSocket(t *testing.T) {
	ln, err := net.Listen("tcp4", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	defer ln.Close()
	port := uint16(ln.Addr().(*net.TCPAddr).Port)
	ctx := context.Background()

	if got, err := namespaceProcesses(ctx, int32(os.Getpid()), port); err == nil || !strings.Contains(err.Error(), "namespace of its own") {
		t.Fatalf("a process in the agent's namespace = %v, %v; want it refused", got, err)
	}
	old := agentNetNS
	agentNetNS = func() (string, error) { return "net:[1]", nil }
	t.Cleanup(func() { agentNetNS = old })
	canceled, cancel := context.WithCancel(ctx)
	cancel()
	if got, err := namespaceProcesses(canceled, int32(os.Getpid()), port); !errors.Is(err, context.Canceled) {
		t.Fatalf("an ended probe = %v, %v; want it to stop", got, err)
	}

	got, err := namespaceProcesses(ctx, int32(os.Getpid()), port)
	if err != nil || !slices.Contains(got, int32(os.Getpid())) {
		t.Fatalf("processes on port %d = %v, %v; want this test", port, got, err)
	}
	ln.Close()
	if got, err := namespaceProcesses(ctx, int32(os.Getpid()), port); err == nil {
		t.Fatalf("a closed port = %v, want an error", got)
	}
	if got, err := namespaceProcesses(ctx, 0, port); err == nil {
		t.Fatalf("a container without a process = %v, want an error", got)
	}
}
