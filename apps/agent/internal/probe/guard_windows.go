// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build windows

package probe

import (
	"context"
	"errors"
	"sync"
	"time"

	"golang.org/x/sys/windows/svc"
)

// forwardingService is the Windows service behind netsh interface portproxy: its process listens on
// the proxied ports and connects on to an end the guard never checked.
const forwardingService = "iphlpsvc"

// forwarding is the last read of forwardingService's process, shared by every guard of the process.
var forwarding struct {
	sync.Mutex
	at  time.Time
	pid int32
}

// osServiceForwarder returns forwardingService if pid is its process, read at most listenerTTL ago.
// A service that does not exist or does not run has no process; a service manager that cannot be
// read is an error.
func osServiceForwarder(_ context.Context, pid int32) (string, error) {
	forwarding.Lock()
	defer forwarding.Unlock()
	if forwarding.at.IsZero() || time.Since(forwarding.at) >= listenerTTL {
		st, err := queryService(forwardingService)
		switch {
		case errors.Is(err, errNoService):
			forwarding.pid = 0
		case err != nil:
			return "", err
		case st.State == svc.Running:
			forwarding.pid = int32(st.ProcessId)
		default:
			forwarding.pid = 0
		}
		forwarding.at = time.Now()
	}
	if forwarding.pid != 0 && pid == forwarding.pid {
		return forwardingService, nil
	}
	return "", nil
}
