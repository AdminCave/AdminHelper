// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package service

import (
	"fmt"
	"path/filepath"
	"strings"
)

// installHooks are the steps of a Windows service install; service_windows.go fills them with the
// service control manager and the file system, the tests with fakes. The order lives in
// runInstall, so that it is testable on every platform.
type installHooks struct {
	// lookup reports whether the service is registered and, if so, the binary it runs.
	lookup func() (registered bool, binary string, err error)
	// stop stops the registered service and waits until its process has ended, so that its
	// files can be replaced.
	stop func() error
	// place puts the agent and frpc.exe into the program directory.
	place func() error
	// create registers a new service; update points the registered one at the new binary.
	create func() error
	update func() error
	// extras sets what only warns on failure: recovery actions, event source.
	extras func()
	// removeOld deletes the binary of an earlier install in another folder.
	removeOld func(binary string) error
	start     func() error
	warnf     func(format string, args ...any)
}

// runInstall installs the agent service, or updates the registered one in place: stop it, replace
// its files, point it at the new binary, start it. newBinary is the binary the service runs
// afterwards.
func runInstall(h installHooks, newBinary string) error {
	registered, oldBinary, err := h.lookup()
	if err != nil {
		return err
	}
	if registered {
		if err := h.stop(); err != nil {
			return fmt.Errorf("stop the running agent service: %w", err)
		}
	}
	// startAgain brings a stopped service back after a failed update rather than leave the host
	// without agent: it still runs its old binary, or the new one in the same place.
	startAgain := func() {
		if registered {
			if err := h.start(); err != nil {
				h.warnf("start the agent service again: %v", err)
			}
		}
	}
	if err := h.place(); err != nil {
		startAgain()
		return err
	}
	if registered {
		err = h.update()
	} else {
		err = h.create()
	}
	if err != nil {
		startAgain()
		return err
	}
	h.extras()
	if registered && oldBinary != "" && !samePath(oldBinary, newBinary) {
		if err := h.removeOld(oldBinary); err != nil {
			h.warnf("remove the agent of the earlier install: %v", err)
		}
	}
	if err := h.start(); err != nil {
		h.warnf("start the agent service: %v", err)
	}
	return nil
}

// samePath compares Windows paths, which ignore case.
func samePath(a, b string) bool {
	return strings.EqualFold(filepath.Clean(a), filepath.Clean(b))
}

// serviceBinary returns the executable of a service's command line: the quoted path, or what
// comes before the first space.
func serviceBinary(commandLine string) string {
	commandLine = strings.TrimSpace(commandLine)
	if rest, ok := strings.CutPrefix(commandLine, `"`); ok {
		if path, _, ok := strings.Cut(rest, `"`); ok {
			return path
		}
		return rest
	}
	path, _, _ := strings.Cut(commandLine, " ")
	return path
}
