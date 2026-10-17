// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package monitor

import (
	"errors"
	"os/exec"
	"reflect"
	"runtime"
	"testing"

	"github.com/shirou/gopsutil/v4/process"
)

// stubHostFacts swaps hostFactsCalls for an Ubuntu KVM guest whose PATH holds exactly the binaries in
// found. It returns the binaries looked up, in call order.
func stubHostFacts(t *testing.T, found ...string) *[]string {
	t.Helper()
	old := hostFactsCalls
	t.Cleanup(func() { hostFactsCalls = old })
	hostFactsCalls.platform = func() (string, string, string, error) { return "ubuntu", "debian", "24.04", nil }
	hostFactsCalls.virtualization = func() (string, string, error) { return "kvm", "guest", nil }
	var looked []string
	hostFactsCalls.lookPath = func(file string) (string, error) {
		looked = append(looked, file)
		for _, f := range found {
			if f == file {
				return "/usr/bin/" + file, nil
			}
		}
		return "", exec.ErrNotFound
	}
	return &looked
}

// wantHostFacts is the expected block: os is the platform the test runs on, fields the rest.
func wantHostFacts(t *testing.T, fields string) map[string]any {
	t.Helper()
	return wantDockerWire(t, `{"os": "`+runtime.GOOS+`", `+fields+`}`)
}

func TestCollectHostFactsAllFields(t *testing.T) {
	looked := stubHostFacts(t, "docker", "zpool", "pvesh")
	got := dockerWire(t, collectHostFacts())
	want := wantHostFacts(t, `"platform": "ubuntu", "platform_version": "24.04",
		"virtualization": {"system": "kvm", "role": "guest"},
		"subsystems": ["docker", "zfs", "proxmox"]`)
	if !reflect.DeepEqual(got, want) {
		t.Errorf("host facts = %v, want %v", got, want)
	}
	if want := []string{"docker", "zpool", "pvesh"}; !reflect.DeepEqual(*looked, want) {
		t.Errorf("looked up %v, want %v", *looked, want)
	}
}

func TestCollectHostFactsOnlyFoundSubsystems(t *testing.T) {
	cases := []struct {
		name  string
		found []string
		want  []any
	}{
		// [] rather than null, so the service never has to tell "none found" from "not sent".
		{"none", nil, []any{}},
		{"zpool only", []string{"zpool"}, []any{"zfs"}},
		// The report order is fixed, whatever order the binaries turn up in.
		{"pvesh and docker", []string{"pvesh", "docker"}, []any{"docker", "proxmox"}},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			stubHostFacts(t, c.found...)
			got := dockerWire(t, collectHostFacts())
			if !reflect.DeepEqual(got["subsystems"], c.want) {
				t.Errorf("subsystems = %#v, want %#v", got["subsystems"], c.want)
			}
		})
	}
}

func TestCollectHostFactsPartFails(t *testing.T) {
	// A failed part drops only its own fields; os and the subsystems never depend on gopsutil.
	failPlatform := func() (string, string, string, error) { return "", "", "", errors.New("open /etc/os-release") }
	failVirt := func() (string, string, error) { return "", "", errors.New("open /proc/cpuinfo") }
	cases := []struct {
		name           string
		platform, virt bool
		want           string
	}{
		{"platform", true, false, `"virtualization": {"system": "kvm", "role": "guest"}, "subsystems": ["docker"]`},
		{"virtualization", false, true, `"platform": "ubuntu", "platform_version": "24.04", "subsystems": ["docker"]`},
		{"both", true, true, `"subsystems": ["docker"]`},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			stubHostFacts(t, "docker")
			if c.platform {
				hostFactsCalls.platform = failPlatform
			}
			if c.virt {
				hostFactsCalls.virtualization = failVirt
			}
			got := dockerWire(t, collectHostFacts())
			if want := wantHostFacts(t, c.want); !reflect.DeepEqual(got, want) {
				t.Errorf("host facts = %v, want %v", got, want)
			}
		})
	}
}

func TestCollectHostFactsNotImplemented(t *testing.T) {
	// gopsutil has no virtualization on Windows and answers its "not implemented" error, which
	// host.Info itself counts as no error. The error comes from gopsutil (IOnice is not implemented on
	// Linux or Windows), so a gopsutil that renames it fails here instead of dropping the block.
	_, notImplemented := (&process.Process{}).IOnice()
	if notImplemented == nil {
		t.Fatal("gopsutil IOnice returned no error, pick another unimplemented call")
	}
	stubHostFacts(t)
	hostFactsCalls.virtualization = func() (string, string, error) { return "", "", notImplemented }
	got := dockerWire(t, collectHostFacts())
	want := wantHostFacts(t, `"platform": "ubuntu", "platform_version": "24.04",
		"virtualization": {"system": "", "role": ""}, "subsystems": []`)
	if !reflect.DeepEqual(got, want) {
		t.Errorf("host facts = %v, want %v", got, want)
	}
}

func TestBuildReportHost(t *testing.T) {
	// stubReportHost leaves the docker collector without a block: the subsystem still counts, so a
	// broken plugin collector cannot keep the template suggestion away.
	stubReportHost(t)
	stubHostFacts(t, "docker")
	report := BuildReport(nil)
	if _, ok := report["docker"]; ok {
		t.Fatalf("docker block set, the stubbed collector returns none")
	}
	got := dockerWire(t, map[string]any{"host": report["host"]})
	want := map[string]any{"host": wantHostFacts(t, `"platform": "ubuntu", "platform_version": "24.04",
		"virtualization": {"system": "kvm", "role": "guest"}, "subsystems": ["docker"]`)}
	if !reflect.DeepEqual(got, want) {
		t.Errorf("report host = %v, want %v", got, want)
	}
}
