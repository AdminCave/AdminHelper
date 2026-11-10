// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build linux

package probe

import (
	"context"
	"errors"
	"fmt"
	"io/fs"
	"net"
	"net/netip"
	"os"
	"os/exec"
	"path/filepath"
	"slices"
	"strings"
	"syscall"
	"testing"
	"time"
)

// stubUnits puts in a systemd that runs this host and a monotonic clock at mono.
func stubUnits(t *testing.T, mono time.Duration) {
	t.Helper()
	oldBooted, oldMono := systemdBooted, monotonicNow
	systemdBooted = func() bool { return true }
	monotonicNow = func() (time.Duration, error) { return mono, nil }
	t.Cleanup(func() { systemdBooted, monotonicNow = oldBooted, oldMono })
}

// stubProc puts in a /proc of files.
func stubProc(t *testing.T, files map[string]string) {
	t.Helper()
	old := readProcFile
	readProcFile = func(name string) ([]byte, error) {
		data, ok := files[name]
		if !ok {
			return nil, &fs.PathError{Op: "open", Path: name, Err: fs.ErrNotExist}
		}
		return []byte(data), nil
	}
	t.Cleanup(func() { readProcFile = old })
}

func TestUnitSensorReadsTheStateOfASystemdUnit(t *testing.T) {
	stubNow(t, start)
	stubUnits(t, 65*time.Second)
	ctx := context.Background()
	p := Probe{Sensor: "unit", Target: &Target{Kind: kindUnit, Name: "nginx.service"}}

	tl := stubTool(t, "LoadState=loaded\nActiveState=active\nSubState=running\nNRestarts=2\nActiveEnterTimestampMonotonic=5000000\n", nil)
	got, err := unitSensor(ctx, p, "")
	want := map[string]any{"active_state": "active", "sub_state": "running", "restarts": 2, "active_since": start.Unix() - 60}
	if err != nil || fmt.Sprint(got) != fmt.Sprint(want) {
		t.Fatalf("unit = %v, %v; want %v", got, err, want)
	}
	wantArgs := []string{"systemctl", "show", "-p", "LoadState,ActiveState,SubState,NRestarts,ActiveEnterTimestampMonotonic", "--", "nginx.service"}
	if !slices.Equal(tl.args, wantArgs) {
		t.Errorf("runTool %v, want %v", tl.args, wantArgs)
	}

	tl.out = "LoadState=loaded\nActiveState=inactive\nSubState=dead\nActiveEnterTimestampMonotonic=5000000\n"
	got, err = unitSensor(ctx, p, "")
	want = map[string]any{"active_state": "inactive", "sub_state": "dead"}
	if err != nil || fmt.Sprint(got) != fmt.Sprint(want) {
		t.Errorf("an inactive unit without restarts = %v, %v; want %v", got, err, want)
	}
	tl.out = "LoadState=loaded\nActiveState=active\nSubState=mounted\nActiveEnterTimestampMonotonic=0\n"
	if got, err = unitSensor(ctx, p, ""); err != nil || got["active_since"] != nil {
		t.Errorf("an active unit without a timestamp = %v, %v; want no active_since", got, err)
	}

	for out, want := range map[string]string{
		"LoadState=not-found\nActiveState=inactive\n": "unit nginx.service does not exist on this host",
		"":          "systemctl show nginx.service: an answer of another form",
		"garbage\n": "systemctl show nginx.service: an answer of another form",
	} {
		tl.out = out
		if _, err := unitSensor(ctx, p, ""); err == nil || err.Error() != want {
			t.Errorf("answer %q = %v, want %q", out, err, want)
		}
	}
	tl.out, tl.err = "", &exec.Error{Name: "systemctl", Err: exec.ErrNotFound}
	if _, err := unitSensor(ctx, p, ""); !errors.Is(err, ErrUnsupported) {
		t.Errorf("no systemctl = %v, want ErrUnsupported", err)
	}
	tl.err = &exec.ExitError{}
	if _, err := unitSensor(ctx, p, ""); err == nil || errors.Is(err, ErrUnsupported) {
		t.Errorf("systemctl failing = %v, want an error", err)
	}

	systemdBooted = func() bool { return false }
	tl.args = nil
	if _, err := unitSensor(ctx, p, ""); !errors.Is(err, ErrUnsupported) || tl.args != nil {
		t.Errorf("no systemd = %v (ran %v), want ErrUnsupported without running systemctl", err, tl.args)
	}
}

func TestUnitSensorOnThisHost(t *testing.T) {
	ctx := context.Background()
	if !systemdBooted() {
		_, err := measureUnit(ctx, "init.scope")
		if !errors.Is(err, ErrUnsupported) {
			t.Fatalf("without systemd: %v, want ErrUnsupported", err)
		}
		return
	}
	got, err := measureUnit(ctx, "init.scope")
	since, ok := got["active_since"].(int64)
	if err != nil || got["active_state"] != "active" || !ok || since > time.Now().Unix() || since < time.Now().Add(-10*365*24*time.Hour).Unix() {
		t.Fatalf("init.scope = %v, %v; want active since boot", got, err)
	}
	if _, err := measureUnit(ctx, "no-such-unit-of-adminhelper.service"); err == nil || !strings.Contains(err.Error(), "does not exist") {
		t.Errorf("an unknown unit = %v, want it not to exist", err)
	}
}

func TestAUnitTargetListensWithTheProcessesOfItsCgroup(t *testing.T) {
	stubUnits(t, time.Minute)
	stubHost(t, &fakeHost{list: []listener{
		lst("0.0.0.0", 80, 7), lst("127.0.0.1", 8080, 8), lst("0.0.0.0", 9000, 9), lst("::", 22, 0),
		lst("0.0.0.0", 81, 10),
	}})
	stubProc(t, map[string]string{
		"/proc/7/cgroup":  "0::/system.slice/nginx.service\n",
		"/proc/8/cgroup":  "0::/system.slice/nginx.service/worker\n",
		"/proc/9/cgroup":  "0::/system.slice/nginx.service2\n",
		"/proc/10/cgroup": "4:memory:/\n1:name=systemd:/user.slice/user-1000.slice\n",
	})
	tl := stubTool(t, "LoadState=loaded\nControlGroup=/system.slice/nginx.service\n", nil)
	ctx := context.Background()

	_, err := resolve(ctx, Target{Kind: kindUnit, Name: "nginx.service"})
	if !errors.Is(err, ErrAmbiguousTarget) || !strings.Contains(err.Error(), "ports 80, 8080 ") {
		t.Fatalf("resolve = %v, want ambiguous between 80 and 8080 alone", err)
	}
	if want := []string{"systemctl", "show", "-p", "LoadState,ControlGroup", "--", "nginx.service"}; !slices.Equal(tl.args, want) {
		t.Errorf("runTool %v, want %v", tl.args, want)
	}
	ep, err := resolve(ctx, Target{Kind: kindUnit, Name: "nginx.service", PortHint: 8080})
	if err != nil || ep.port != 8080 || ep.addr != netip.MustParseAddr("127.0.0.1") {
		t.Errorf("resolve with hint = %v, %v", ep, err)
	}

	tl.out = "LoadState=loaded\nControlGroup=\n"
	p := Probe{ID: "u1", Sensor: "socket", Target: &Target{Kind: kindUnit, Name: "nginx.service"}, TimeoutS: 5, Fields: []string{"listening"}}
	if res := Run(ctx, p, start, nil); res.Status != StatusOK || res.Values["listening"] != false {
		t.Errorf("a stopped unit = %+v, want not listening", res)
	}
	// Under cgroup v1 a controller's root holds every process it does not limit (process 10): the
	// root slice's listeners are not those of one unit.
	tl.out = "LoadState=loaded\nControlGroup=/\n"
	if _, err := resolve(ctx, Target{Kind: kindUnit, Name: "-.slice", PortHint: 81}); !errors.Is(err, errNotListening) {
		t.Errorf("resolve of the root slice = %v, want it not listening", err)
	}
}

func TestAContainerTargetListensInItsNetwork(t *testing.T) {
	stubHost(t, &fakeHost{list: []listener{lst("0.0.0.0", 25, 7), lst("0.0.0.0", 9000, 8)}})
	tcp := "  sl  local_address rem_address   st\n" +
		"   0: 00000000:0050 00000000:0000 0A\n" + // 0.0.0.0:80
		"   1: 0100007F:2328 00000000:0000 0A\n" + // 127.0.0.1:9000, the container's own loopback
		"   2: 050200C0:01BB 00000000:0000 0A\n" + // 192.0.2.5:443
		"   3: 090200C0:0016 00000000:0000 0A\n" //  192.0.2.9:22, no address of the container
	files := map[string]string{
		"/proc/4242/net/tcp": tcp,
		"/proc/4242/cgroup":  "0::/system.slice/docker-" + containerID + ".scope\n",
		"/proc/7/cgroup":     "0::/system.slice/docker-" + containerID + ".scope/init\n",
		// A cgroup a user created in their own, named like the container's: not the container's.
		"/proc/8/cgroup": "0::/user.slice/user-1000.slice/user@1000.service/docker-" + containerID + ".scope\n",
	}
	stubProc(t, files)
	tl := stubTool(t, inspectJSON(t, "running", "healthy", "bridge"), nil)
	ctx := context.Background()
	addrs := []netip.Addr{netip.MustParseAddr("192.0.2.5"), netip.MustParseAddr("192.0.2.6"), netip.MustParseAddr("2001:db8::5")}

	_, err := resolve(ctx, Target{Kind: kindContainer, Name: "web"})
	if !errors.Is(err, ErrAmbiguousTarget) || !strings.Contains(err.Error(), "ports 80, 443 ") {
		t.Fatalf("resolve = %v, want ambiguous between 80 and 443 alone", err)
	}
	for hint, want := range map[int]string{443: "192.0.2.5:443", 80: "192.0.2.5:80"} {
		ep, err := resolve(ctx, Target{Kind: kindContainer, Name: "web", PortHint: hint})
		if err != nil || netip.AddrPortFrom(ep.addr, ep.port).String() != want || !slices.Equal(ep.extra, addrs) {
			t.Errorf("resolve(hint %d) = %v, %v; want %s with the container's addresses", hint, ep, err, want)
		}
	}

	files["/proc/4242/net/tcp6"] = "   0: 00000000000000000000000000000000:1F90 00000000000000000000000000000000:0000 0A\n"
	ep, err := resolve(ctx, Target{Kind: kindContainer, Name: "web", PortHint: 8080})
	if err != nil || ep.port != 8080 || ep.addr != addrs[0] {
		t.Errorf("resolve on tcp6 = %v, %v; want 192.0.2.5:8080", ep, err)
	}
	delete(files, "/proc/4242/net/tcp")
	if _, err := resolve(ctx, Target{Kind: kindContainer, Name: "web", PortHint: 80}); err == nil || !strings.Contains(err.Error(), "cannot be read") {
		t.Errorf("resolve without the tcp file = %v, want an error", err)
	}

	tl.out = inspectJSON(t, "running", "", "host")
	ep, err = resolve(ctx, Target{Kind: kindContainer, Name: "web"})
	if err != nil || ep.port != 25 || ep.addr != netip.MustParseAddr("127.0.0.1") || ep.extra != nil {
		t.Errorf("resolve on the host's network = %v, %v; want 127.0.0.1:25 of its process alone", ep, err)
	}
	delete(files, "/proc/4242/cgroup")
	if _, err := resolve(ctx, Target{Kind: kindContainer, Name: "web"}); err == nil || !strings.Contains(err.Error(), "the cgroup of container web cannot be read") {
		t.Errorf("resolve without the container's cgroup = %v, want an error", err)
	}
	for _, mode := range []string{"none", "container:" + containerID} {
		tl.out = inspectJSON(t, "running", "", mode)
		if _, err := resolve(ctx, Target{Kind: kindContainer, Name: "web"}); err == nil || !strings.Contains(err.Error(), "no network of its own") {
			t.Errorf("resolve in mode %s = %v, want an error", mode, err)
		}
	}
	tl.out = strings.ReplaceAll(inspectJSON(t, "running", "", "bridge"), `"IPAddress":"192.0.2.`, `"IPAddress":"x`)
	tl.out = strings.Replace(tl.out, "2001:db8::5", "", 1)
	if _, err := resolve(ctx, Target{Kind: kindContainer, Name: "web"}); err == nil || !strings.Contains(err.Error(), "no network address") {
		t.Errorf("resolve without addresses = %v, want an error", err)
	}

	tl.out = inspectJSON(t, "exited", "", "bridge")
	p := Probe{ID: "c1", Sensor: "socket", Target: &Target{Kind: kindContainer, Name: "web"}, TimeoutS: 5, Fields: []string{"listening"}}
	if res := Run(ctx, p, start, nil); res.Status != StatusOK || res.Values["listening"] != false {
		t.Errorf("an exited container = %+v, want not listening", res)
	}
}

func TestNamespaceListenersReadsTheKernelsTable(t *testing.T) {
	ln, err := net.Listen("tcp4", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	defer ln.Close()
	want := []listener{lst("127.0.0.1", uint16(ln.Addr().(*net.TCPAddr).Port), 0)}
	if ln6, err := net.Listen("tcp6", "[::1]:0"); err == nil {
		defer ln6.Close()
		want = append(want, lst("::1", uint16(ln6.Addr().(*net.TCPAddr).Port), 0))
	}
	list, err := namespaceListeners(os.Getpid())
	if err != nil {
		t.Fatal(err)
	}
	for _, l := range want {
		if !slices.Contains(list, l) {
			t.Errorf("namespaceListeners = %v, want %v among them", list, l)
		}
	}
}

func TestCertfileSensorNeverReadsAFileOfTheKernel(t *testing.T) {
	_, err := certfileSensor(context.Background(), certfile(t, "/proc/self/status"), "")
	if err == nil || !strings.Contains(err.Error(), "file system of the kernel") {
		t.Errorf("certfile on /proc/self/status = %v, want it refused", err)
	}
}

func TestReadSmallFileNeverWaitsForAFIFO(t *testing.T) {
	path := filepath.Join(t.TempDir(), "fifo")
	if err := syscall.Mkfifo(path, 0o600); err != nil {
		t.Fatal(err)
	}
	probe := certfile(t, path)
	done := make(chan error, 1)
	go func() {
		_, err := certfileSensor(context.Background(), probe, "")
		done <- err
	}()
	select {
	case err := <-done:
		if err == nil || !strings.Contains(err.Error(), "is no regular file") {
			t.Errorf("certfile on a FIFO = %v, want no regular file", err)
		}
	case <-time.After(5 * time.Second):
		t.Fatal("certfile waits on a FIFO")
	}

	f, err := openNoWait(path)
	if err != nil {
		t.Fatalf("openNoWait(FIFO) = %v, want it opened without a writer", err)
	}
	_ = f.Close()
}
