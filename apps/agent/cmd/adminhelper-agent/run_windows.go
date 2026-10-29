// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build windows

package main

import (
	"context"

	"golang.org/x/sys/windows/svc"
)

// windowsServiceName must match the name `sc create` registers in
// internal/service/service_windows.go.
const windowsServiceName = "AdminHelper-Agent"

// agentService implements svc.Handler: it reports SERVICE_RUNNING to the SCM and
// drives the same serve() loop as runLoop(), but stops on SCM Stop/Shutdown
// instead of an OS signal (the SCM does not send SIGINT/SIGTERM).
type agentService struct{}

func (s *agentService) Execute(_ []string, r <-chan svc.ChangeRequest, changes chan<- svc.Status) (bool, uint32) {
	changes <- svc.Status{State: svc.StartPending}

	// Stop/Shutdown cancels the ctx, which reaches the cycle in flight. Execute
	// returns only once serve is back (at most stopWait): the process ends with
	// Execute, and must not end in the middle of a cycle.
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	// serve runs on its own goroutine so the SCM control loop below stays
	// responsive while a cycle runs.
	served := make(chan struct{})
	go func() {
		serve(ctx, defaultInterval, cycle)
		close(served)
	}()

	changes <- svc.Status{State: svc.Running, Accepts: svc.AcceptStop | svc.AcceptShutdown}

	for {
		c := <-r
		switch c.Cmd {
		case svc.Interrogate:
			changes <- c.CurrentStatus
		case svc.Stop, svc.Shutdown:
			changes <- svc.Status{State: svc.StopPending, WaitHint: uint32(stopWait.Milliseconds())}
			cancel()
			<-served
			return false, 0
		}
	}
}

// runService runs the agent under the Windows SCM when started by it, so
// `sc start` gets a SERVICE_RUNNING report instead of timing out (error 1053).
// When NOT launched as a service (interactive run), it returns handled=false so
// the caller falls back to the normal runLoop().
func runService() (handled bool, err error) {
	isSvc, err := svc.IsWindowsService()
	if err != nil {
		return false, err
	}
	if !isSvc {
		return false, nil
	}
	return true, svc.Run(windowsServiceName, &agentService{})
}
