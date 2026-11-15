// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build linux

package probe

import (
	"context"
	"errors"
	"net/netip"
	"slices"
	"strconv"
	"testing"
	"time"
)

// The cgroups of the UniFi OS Server 5.1.42 on the lab box: the unit runs as user 1001, pasta holds
// port 11443 from that user's manager.
const (
	uosUnitCgroup  = "/system.slice/uosserver.service"
	uosPastaCgroup = "/user.slice/user-1001.slice/user@1001.service/user.slice/podman-3052.scope"
)

// stubUOS puts in a systemd with the unit uosserver.service whose main process 100 runs as uid and
// processes in the cgroups of cgroups.
func stubUOS(t *testing.T, uid string, cgroups map[int32]string) *tool {
	t.Helper()
	stubUnits(t, time.Minute)
	tl := stubTool(t, "LoadState=loaded\nControlGroup="+uosUnitCgroup+"\nMainPID=100\n", nil)
	files := map[string]string{"/proc/100/status": "Name:\tuosserver-servi\nUid:\t" + uid + "\t" + uid + "\t" + uid + "\t" + uid + "\n"}
	for pid, cg := range cgroups {
		files["/proc/"+strconv.Itoa(int(pid))+"/cgroup"] = "0::" + cg + "\n"
	}
	stubProc(t, files)
	return tl
}

func TestUnifiOwnerTakesTheUnitAndItsUsersManager(t *testing.T) {
	stubUOS(t, "1001", map[int32]string{
		101: uosUnitCgroup,
		102: uosUnitCgroup + "/discovery",
		103: uosPastaCgroup,
		// Another user's manager, a login session of the same user, a uid that merely starts alike.
		104: "/user.slice/user-1002.slice/user@1002.service/user.slice/podman-1.scope",
		105: "/user.slice/user-1001.slice/session-3.scope",
		106: "/user.slice/user-10011.slice/user@10011.service/app.slice",
		107: "/system.slice/uosserver.service-other",
		108: "/system.slice/nginx.service",
	})
	owns, err := unifiOwner(context.Background(), "uosserver.service")
	if err != nil {
		t.Fatal(err)
	}
	var got []int32
	for pid := int32(101); pid <= 109; pid++ {
		if owns(pid) {
			got = append(got, pid)
		}
	}
	if want := []int32{101, 102, 103}; !slices.Equal(got, want) {
		t.Errorf("owned %v, want %v", got, want)
	}
}

func TestUnifiOwnerTakesNoManagerOfRoot(t *testing.T) {
	stubUOS(t, "0", map[int32]string{
		101: uosUnitCgroup,
		103: "/user.slice/user-0.slice/user@0.service/user.slice/podman-3052.scope",
	})
	owns, err := unifiOwner(context.Background(), "uosserver.service")
	if err != nil {
		t.Fatal(err)
	}
	if !owns(101) || owns(103) {
		t.Errorf("owns(unit) = %v, owns(root's manager) = %v; want true, false", owns(101), owns(103))
	}
}

func TestUnifiOwnerTakesNoManagerWithoutTheMainProcess(t *testing.T) {
	stubUOS(t, "1001", map[int32]string{103: uosPastaCgroup})
	stubProc(t, map[string]string{"/proc/103/cgroup": "0::" + uosPastaCgroup + "\n"})
	owns, err := unifiOwner(context.Background(), "uosserver.service")
	if err != nil {
		t.Fatal(err)
	}
	if owns(103) {
		t.Error("a manager was taken although the user of the main process could not be read")
	}
}

func TestUnifiOwnerNeedsARunningUnit(t *testing.T) {
	stubUnits(t, time.Minute)
	for _, out := range []string{
		"LoadState=loaded\nControlGroup=\nMainPID=0\n",
		"LoadState=loaded\nControlGroup=" + uosUnitCgroup + "\nMainPID=0\n",
	} {
		stubTool(t, out, nil)
		if _, err := unifiOwner(context.Background(), "uosserver.service"); !errors.Is(err, errNotListening) {
			t.Errorf("%q: err = %v, want errNotListening", out, err)
		}
	}
}

func TestUnifiResolveFindsThePortOfTheRootlessPodman(t *testing.T) {
	tl := stubUOS(t, "1001", map[int32]string{103: uosPastaCgroup, 108: "/system.slice/nginx.service"})
	any4 := netip.IPv4Unspecified()
	stubHost(t, &fakeHost{list: []listener{{addr: any4, port: 11443, pid: 103}, {addr: any4, port: 443, pid: 108}}})
	ep, err := unifiResolve(context.Background(), Target{Kind: kindUnit, Name: "uosserver.service", PortHint: 11443})
	if err != nil {
		t.Fatal(err)
	}
	if ep.port != 11443 || ep.owns == nil || !ep.owns()(listener{port: 11443, pid: 103}) || ep.owns()(listener{port: 443, pid: 108}) {
		t.Errorf("endpoint %v:%d, want 11443 with the rule of the unit and its manager", ep.addr, ep.port)
	}
	want := []string{"systemctl", "show", "-p", "LoadState,ControlGroup,MainPID", "--", "uosserver.service"}
	if !slices.Equal(tl.args, want) {
		t.Errorf("runTool %v, want %v", tl.args, want)
	}
	// The plain unit rule would not find it: the reason for unifiResolve.
	if _, err := resolve(context.Background(), Target{Kind: kindUnit, Name: "uosserver.service", PortHint: 11443}); err == nil {
		t.Error("resolve found the port of the rootless Podman by the unit's cgroup alone")
	}
}
