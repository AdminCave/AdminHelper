// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Package opnsense reads the state of an OPNsense firewall the way its own web GUI does: through
// configctl, the client of the configd daemon, and only through read actions from a fixed list. Each
// view turns one or two outputs into flat scalar fields for the monitoring service. No API key and
// no network: configd runs the same scripts the GUI's status pages call.
package opnsense

import (
	"context"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"sort"
	"time"
)

// Configctl is the configd client of every OPNsense install. It exits 0 even when configd rejects
// an action and prints the reason instead, so a view's parser, not the exit code, decides whether
// the answer is one.
const Configctl = "/usr/local/sbin/configctl"

// pkgUpgradeFile is where the last firmware check (System → Firmware → Check for updates) leaves
// its result; `firmware product` embeds its content but not its age.
const pkgUpgradeFile = "/tmp/pkg_upgrade.json"

// Runner runs a command under a timeout; allowlist.Run has this shape.
type Runner func(ctx context.Context, timeout time.Duration, name string, args ...string) ([]byte, error)

// Reader reads views through Run. ModTime and Now are nil in production (os.Stat, time.Now).
type Reader struct {
	Run     Runner
	ModTime func(path string) (time.Time, error)
	Now     func() time.Time
}

// ErrUnknownView is returned for a view outside the allowlist; no command runs for it.
var ErrUnknownView = errors.New("opnsense: unknown view")

type view struct {
	// calls are the configctl arguments, one entry per call; all are configd read actions.
	calls   [][]string
	timeout time.Duration
	parse   func(r Reader, outs [][]byte) (map[string]any, error)
}

// views is the allowlist. The timeouts sit above what each action needs on a busy box and below
// configctl's own socket timeout of 120 s; `firmware product` starts several PHP and shell tools.
var views = map[string]view{
	"services": {calls: [][]string{{"service", "list"}}, timeout: 30 * time.Second, parse: parseServices},
	"gateways": {calls: [][]string{{"interface", "gateways", "status"}}, timeout: 15 * time.Second, parse: parseGateways},
	"firmware": {calls: [][]string{{"firmware", "product"}}, timeout: 60 * time.Second, parse: parseFirmware},
	"states":   {calls: [][]string{{"filter", "diag", "state_size"}}, timeout: 15 * time.Second, parse: parseStates},
	"carp": {
		calls:   [][]string{{"interface", "show", "carp"}, {"interface", "list", "ifconfig"}},
		timeout: 15 * time.Second,
		parse:   parseCarp,
	},
}

// Views returns the names of the views in the allowlist, sorted.
func Views() []string {
	names := make([]string, 0, len(views))
	for name := range views {
		names = append(names, name)
	}
	sort.Strings(names)
	return names
}

// Read runs the configctl calls of one view and returns its fields. Errors name the view and the
// kind of failure, never the command's output or a path: they go to the monitoring service as a
// check result.
func (r Reader) Read(ctx context.Context, name string) (map[string]any, error) {
	v, ok := views[name]
	if !ok {
		return nil, ErrUnknownView
	}
	outs := make([][]byte, 0, len(v.calls))
	for _, args := range v.calls {
		if err := ctx.Err(); err != nil {
			return nil, fmt.Errorf("opnsense: %s: %w", name, err)
		}
		out, err := r.Run(ctx, v.timeout, Configctl, args...)
		if err != nil {
			return nil, runError(name, err)
		}
		outs = append(outs, out)
	}
	fields, err := v.parse(r, outs)
	if err != nil {
		return nil, fmt.Errorf("opnsense: %s: %w", name, err)
	}
	return fields, nil
}

// runError keeps the context errors matchable and drops everything else to its kind: an
// *exec.Error carries the binary's path and an *exec.ExitError the process state.
func runError(name string, err error) error {
	for _, ctxErr := range []error{context.DeadlineExceeded, context.Canceled} {
		if errors.Is(err, ctxErr) {
			return fmt.Errorf("opnsense: %s: configctl: %w", name, ctxErr)
		}
	}
	var exitErr *exec.ExitError
	if errors.As(err, &exitErr) {
		return fmt.Errorf("opnsense: %s: configctl exited with %d", name, exitErr.ExitCode())
	}
	if errors.Is(err, exec.ErrNotFound) || errors.Is(err, os.ErrNotExist) {
		return fmt.Errorf("opnsense: %s: configctl not found", name)
	}
	return fmt.Errorf("opnsense: %s: configctl failed", name)
}
