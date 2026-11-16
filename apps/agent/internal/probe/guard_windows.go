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

	"golang.org/x/sys/windows"
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

// systemPID is the process of the kernel. Its sockets are those of HTTP.sys, which serves the URL
// reservations of any account, so they count as no service account's.
const systemPID = 4

// osListenerAccount returns the uid the guard judges a listener by whose socket process pid created
// at the FILETIME created: 0 for a process under a service account (serviceAccountSID), accountUser
// for any other, nothing when the process or its token cannot be read or when the process started
// after the socket, so that its pid is the reuse of another's.
func osListenerAccount(pid int32, created int64) (uint32, bool) {
	if pid <= 0 {
		return 0, false
	}
	if pid == systemPID {
		return accountUser, true
	}
	h, err := windows.OpenProcess(windows.PROCESS_QUERY_LIMITED_INFORMATION, false, uint32(pid))
	if err != nil {
		return 0, false
	}
	defer func() { _ = windows.CloseHandle(h) }()
	var start, exit, kernel, user windows.Filetime
	if err := windows.GetProcessTimes(h, &start, &exit, &kernel, &user); err != nil {
		return 0, false
	}
	if created <= 0 || int64(start.HighDateTime)<<32|int64(start.LowDateTime) > created {
		return 0, false
	}
	var token windows.Token
	if err := windows.OpenProcessToken(h, windows.TOKEN_QUERY, &token); err != nil {
		return 0, false
	}
	defer func() { _ = token.Close() }()
	account, err := token.GetTokenUser()
	if err != nil {
		return 0, false
	}
	if serviceAccountSID(account.User.Sid.String()) {
		return 0, true
	}
	return accountUser, true
}
