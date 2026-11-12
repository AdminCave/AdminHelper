// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package probe

import (
	"context"
	"errors"
	"fmt"
	"io/fs"
	"time"

	"adminhelper-agent/internal/opnsense"
)

func init() {
	sensors["opnsense"] = opnsenseSensor
}

// opnsenseSensor reads one view of an OPNsense firewall through configctl (internal/opnsense): no
// target, no credential, the view from the allowlist. A host without configctl is no OPNsense, so
// the sensor is unsupported there, on Linux and Windows too.
func opnsenseSensor(ctx context.Context, p Probe, _ string) (map[string]any, error) {
	if err := noTarget(p); err != nil {
		return nil, err
	}
	if err := knownParams(p, "view"); err != nil {
		return nil, err
	}
	view, err := choiceParam(p, "view", "", opnsense.Views()...)
	if err != nil {
		return nil, err
	}
	if _, err := statPath(opnsense.Configctl); err != nil {
		if errors.Is(err, fs.ErrNotExist) {
			return nil, fmt.Errorf("%w: configctl is not installed, this host runs no OPNsense", ErrUnsupported)
		}
		return nil, errors.New("configctl cannot be checked")
	}
	r := opnsense.Reader{Run: runTool, ModTime: modTime, Now: now}
	return r.Read(ctx, view)
}

// modTime is the mtime of path through the sensors' seam to the host.
func modTime(path string) (time.Time, error) {
	info, err := statPath(path)
	if err != nil {
		return time.Time{}, err
	}
	return info.ModTime(), nil
}
