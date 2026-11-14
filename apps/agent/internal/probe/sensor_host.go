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
// container (software and hardware RAID, thin pools, IPMI sensors, sanoid's snapshot freshness,
// rsnapshot's last run; on Windows the open updates and the machine certificates). Each reads kernel
// files, its own log or a fixed Windows query, or starts a read command with fixed arguments through
// the allowlist (runTool), and reports counts and percentages, never a name.
var hostViews = map[string]func(ctx context.Context) (map[string]any, error){
	"ipmi_sensors":  ipmiSensors,
	"lvm_thin":      lvmThin,
	"mdadm":         mdArrays,
	"raid_ctrl":     raidCtrl,
	"rsnapshot":     rsnapshotStatus,
	"win_certs":     winCerts,
	"win_updates":   winUpdates,
	"zfs_snapshots": zfsSnapshots,
}

// winEventsView counts the events since the probe's last run, so it takes the interval and is
// no entry of hostViews.
const winEventsView = "win_events"

// hostSensor reads one view of this host: no target, no parameter but the view, like the opnsense
// sensor.
func hostSensor(ctx context.Context, p Probe, _ string) (map[string]any, error) {
	if err := noTarget(p); err != nil {
		return nil, err
	}
	if err := knownParams(p, "view"); err != nil {
		return nil, err
	}
	view, err := choiceParam(p, "view", "", append(slices.Sorted(maps.Keys(hostViews)), winEventsView)...)
	if err != nil {
		return nil, err
	}
	if view == winEventsView {
		return winEvents(ctx, winEventsWindow(p.IntervalS))
	}
	return hostViews[view](ctx)
}
