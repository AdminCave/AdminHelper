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
	sensors["app"] = appSensor
}

// appView is one view of the app sensor: the kind of target it is bound to and what reads it.
type appView struct {
	kind string
	read func(ctx context.Context, t Target) (map[string]any, error)
}

// appViews are the views of the app sensor. Each reads the inside of one application on this host,
// read only and without starting a program: files, the application's API on its own port, its
// local socket. The server names a view, never a path, a command or a query.
var appViews = map[string]appView{
	"bbb_meetings":     {kindUnit, bbbMeetings},
	"bbb_recordings":   {kindUnit, bbbRecordings},
	"ldap_replication": {kindUnit, ldapReplication},
}

// appSensor reads the view the probe names of the application its target belongs to.
func appSensor(ctx context.Context, p Probe, _ string) (map[string]any, error) {
	if err := knownParams(p, "view"); err != nil {
		return nil, err
	}
	view, err := choiceParam(p, "view", "", slices.Sorted(maps.Keys(appViews))...)
	if err != nil {
		return nil, err
	}
	v := appViews[view]
	t, err := targetOf(p, v.kind)
	if err != nil {
		return nil, err
	}
	return v.read(ctx, t)
}
