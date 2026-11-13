// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package probe

import (
	"context"
	"maps"
	"slices"
)

func init() {
	sensors["host"] = hostSensor
}

// hostViews are the views of the host sensor: parts of this host that belong to no unit and no
// container (software RAID, thin pools). Each reads kernel files or starts a read command with fixed
// arguments through the allowlist (runTool) and reports counts and percentages, never a name.
var hostViews = map[string]func(ctx context.Context) (map[string]any, error){
	"lvm_thin": lvmThin,
	"mdadm":    mdArrays,
}

// hostSensor reads one view of this host: no target, no parameter but the view, like the opnsense
// sensor.
func hostSensor(ctx context.Context, p Probe, _ string) (map[string]any, error) {
	if err := noTarget(p); err != nil {
		return nil, err
	}
	if err := knownParams(p, "view"); err != nil {
		return nil, err
	}
	view, err := choiceParam(p, "view", "", slices.Sorted(maps.Keys(hostViews))...)
	if err != nil {
		return nil, err
	}
	return hostViews[view](ctx)
}
