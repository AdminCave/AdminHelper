// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build !windows

package probe

import (
	"context"
	"fmt"
	"time"
)

// The Windows views read WMI, the event log, the certificate store and the Windows tools:
// on any other host they have nothing to read.

func errNoWindows() error { return fmt.Errorf("%w: a Windows view", ErrUnsupported) }

func adReplication(context.Context, Target) (map[string]any, error) { return nil, errNoWindows() }
func dhcpScopes(context.Context, Target) (map[string]any, error)    { return nil, errNoWindows() }
func iisState(context.Context, Target) (map[string]any, error)      { return nil, errNoWindows() }
func rdsLicenses(context.Context, Target) (map[string]any, error)   { return nil, errNoWindows() }
func winUpdates(context.Context) (map[string]any, error)            { return nil, errNoWindows() }
func winCerts(context.Context) (map[string]any, error)              { return nil, errNoWindows() }
func winEvents(context.Context, time.Duration) (map[string]any, error) {
	return nil, errNoWindows()
}
