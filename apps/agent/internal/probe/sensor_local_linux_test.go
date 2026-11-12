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
	"sync/atomic"
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

// stubDockerServes makes the docker daemon of this host one that serves (true) or one that does not.
func stubDockerServes(t *testing.T, serves bool) *int {
	t.Helper()
	calls := 0
	old := dockerServes
	dockerServes = func(context.Context) bool {
		calls++
		return serves
	}
	t.Cleanup(func() { dockerServes = old })
	return &calls
}

const inspectTwo = `[
 {"Id": "` + containerID + `", "State": {"Running": true}, "NetworkSettings": {"Ports": {
   "3306/tcp": [{"HostIp": "", "HostPort": "13306"}, {"HostIp": "::", "HostPort": "13306"}],
   "80/tcp": [{"HostIp": "127.0.0.1", "HostPort": "8092"}],
   "53/udp": [{"HostIp": "0.0.0.0", "HostPort": "5353"}],
   "9100/tcp": null}}},
 {"Id": "abababababababababababababababababababababababababababababababab", "State": {"Running": false}, "NetworkSettings": {"Ports": {"22/tcp": [{"HostIp": "0.0.0.0", "HostPort": "2222"}]}}}
]`

func TestDockerPublicationsReadsThePublishedTCPPortsOfTheRunningContainers(t *testing.T) {
	other := strings.Repeat("ab", 32)
	calls := stubTools(t, answer{out: containerID + "\n" + other + "\n"}, answer{out: inspectTwo})

	got, err := dockerPublications(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	want := []publication{
		{hostPort: 13306, to: 3306}, {hostIP: netip.MustParseAddr("::"), hostPort: 13306, to: 3306},
		{hostIP: netip.MustParseAddr("127.0.0.1"), hostPort: 8092, to: 80},
	}
	sortPubs := func(l []publication) {
		slices.SortFunc(l, func(a, b publication) int {
			if a.hostPort != b.hostPort {
				return int(a.hostPort) - int(b.hostPort)
			}
			return a.hostIP.Compare(b.hostIP)
		})
	}
	sortPubs(got)
	sortPubs(want)
	if !slices.Equal(got, want) {
		t.Fatalf("got %+v, want %+v", got, want)
	}
	if wantArgs := []string{"docker", "inspect", "--type", "container", containerID, other}; !slices.Equal((*calls)[1], wantArgs) {
		t.Fatalf("inspect called as %q, want %q", (*calls)[1], wantArgs)
	}
}

func TestDockerPublicationsTakesTheAnswerOfDockerWhenTheContainersLeftOutAreGone(t *testing.T) {
	other := strings.Repeat("cd", 32)
	ids := containerID + "\n" + strings.Repeat("ab", 32) + "\n" + other + "\n"
	calls := stubTools(t, answer{out: ids}, answer{out: inspectTwo, err: &exec.ExitError{}}, answer{out: containerID + "\n"})

	got, err := dockerPublications(context.Background())
	if err != nil || len(got) != 3 {
		t.Fatalf("got %+v, %v, want the 3 publications docker printed", got, err)
	}
	if len(*calls) != 3 || (*calls)[2][1] != "ps" {
		t.Fatalf("calls %q, want docker ps asked again for the container left out", *calls)
	}
}

func TestDockerPublicationsFailsWhenDockerLeavesOutAContainerItStillLists(t *testing.T) {
	stubDockerServes(t, true)
	for name, answers := range map[string][]answer{
		// A daemon gone between the calls: docker prints [] and fails.
		"empty":    {{out: containerID + "\n"}, {out: "[]", err: &exec.ExitError{}}, {out: containerID + "\n"}},
		"ps again": {{out: containerID + "\n"}, {out: "[]", err: &exec.ExitError{}}, {err: &exec.ExitError{}}},
	} {
		stubTools(t, answers...)
		if got, err := dockerPublications(context.Background()); err == nil {
			t.Errorf("%s: %+v, want an error", name, got)
		}
	}
}

func TestDockerPublicationsFindsNoneWithoutADaemon(t *testing.T) {
	stubDockerServes(t, false)
	for name, a := range map[string]answer{
		"no CLI":    {err: &exec.Error{Name: "docker", Err: exec.ErrNotFound}},
		"ps failed": {err: &exec.ExitError{}},
	} {
		stubTools(t, a)
		if got, err := dockerPublications(context.Background()); err != nil || got != nil {
			t.Errorf("%s: %+v, %v, want none", name, got, err)
		}
	}

	stubTools(t, answer{out: "\n"})
	if got, err := dockerPublications(context.Background()); err != nil || got != nil {
		t.Fatalf("without containers: %+v, %v, want none", got, err)
	}
}

func TestDockerPublicationsFailsForADaemonServingWithoutTheCLI(t *testing.T) {
	stubDockerServes(t, true)
	stubTools(t, answer{err: &exec.Error{Name: "docker", Err: exec.ErrNotFound}})

	if got, err := dockerPublications(context.Background()); err == nil {
		t.Fatalf("%+v, want an error: a daemon serves, its containers cannot be read", got)
	}
}

func TestDockerPublicationsFailsWhenTheServingDaemonCannotBeRead(t *testing.T) {
	stubDockerServes(t, true)
	for name, answers := range map[string][]answer{
		"ps":             {{err: &exec.ExitError{}}},
		"inspect":        {{out: containerID}, {err: errors.New("signal: killed")}},
		"inspect exit":   {{out: containerID}, {out: "permission denied", err: &exec.ExitError{}}},
		"form":           {{out: containerID}, {out: `{"not": "a list"}`}},
		"container port": {{out: containerID}, {out: `[{"State":{"Running":true},"NetworkSettings":{"Ports":{"x/tcp":[{"HostPort":"1"}]}}}]`}},
		"host port":      {{out: containerID}, {out: `[{"State":{"Running":true},"NetworkSettings":{"Ports":{"22/tcp":[{"HostPort":"70000"}]}}}]`}},
		"host address":   {{out: containerID}, {out: `[{"State":{"Running":true},"NetworkSettings":{"Ports":{"22/tcp":[{"HostIp":"x","HostPort":"1"}]}}}]`}},
	} {
		stubTools(t, answers...)
		if got, err := dockerPublications(context.Background()); err == nil {
			t.Errorf("%s: %+v, want an error", name, got)
		}
	}
}

// TestDockerSocketServes says no only without a socket or an acceptor on it and without dockerd;
// short for the socket paths.
func TestDockerSocketServes(t *testing.T) {
	dir := filepath.Dir(socketIn(t))
	old, oldRunning := dockerSocket, dockerdRunning
	t.Cleanup(func() { dockerSocket, dockerdRunning = old, oldRunning })
	running := false
	dockerdRunning = func(context.Context) bool { return running }

	dockerSocket = filepath.Join(dir, "m.sock")
	if dockerSocketServes(context.Background()) {
		t.Error("a missing socket serves")
	}
	// A dockerd on another socket (rootless, -H) publishes ports as much.
	running = true
	if !dockerSocketServes(context.Background()) {
		t.Error("a missing socket with dockerd running does not serve")
	}
	running = false

	dockerSocket = filepath.Join(dir, "s.sock")
	l, err := net.Listen("unix", dockerSocket)
	if err != nil {
		t.Fatal(err)
	}
	if !dockerSocketServes(context.Background()) {
		t.Error("a socket with an acceptor does not serve")
	}
	// Closing the listener removes the socket file; one left behind takes no connection.
	l.(*net.UnixListener).SetUnlinkOnClose(false)
	_ = l.Close()
	if dockerSocketServes(context.Background()) {
		t.Error("a socket nobody accepts on serves")
	}
	running = true
	if !dockerSocketServes(context.Background()) {
		t.Error("a socket nobody accepts on, with dockerd running, does not serve")
	}
	running = false

	// A socket the agent may not reach may well have a daemon behind it.
	locked := filepath.Join(dir, "l")
	if err := os.Mkdir(locked, 0o700); err != nil {
		t.Fatal(err)
	}
	dockerSocket = filepath.Join(locked, "s.sock")
	l, err = net.Listen("unix", dockerSocket)
	if err != nil {
		t.Fatal(err)
	}
	defer l.Close()
	if err := os.Chmod(locked, 0); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = os.Chmod(locked, 0o700) })
	if os.Geteuid() == 0 {
		t.Log("root reaches the locked socket; the denied path is not shown")
		return
	}
	if !dockerSocketServes(context.Background()) {
		t.Error("a socket the agent may not reach does not count as serving")
	}
}

func TestUnixSocketSensorNeverConnectsToASocketOfAControlService(t *testing.T) {
	servedBy(t, "nginx")
	path, _ := unixFake(t, func(c *fakeConn) { c.drain() })
	probe := func(path string) (map[string]any, error) {
		return unixSocketSensor(context.Background(), unixProbe(map[string]any{"path": path}), "")
	}
	if got, err := probe(path); err != nil || got["connected"] != true {
		t.Fatalf("before = %v, %v; want it connected", got, err)
	}
	link := filepath.Join(filepath.Dir(socketIn(t)), "l.sock")
	if err := os.Symlink(path, link); err != nil {
		t.Fatal(err)
	}
	old := controlSockets
	t.Cleanup(func() { controlSockets = old })
	controlSockets = append(slices.Clone(old), filepath.Dir(path)+"/")

	for _, p := range []string{path, link} {
		if got, err := probe(p); !errors.Is(err, ErrNotAllowed) || !strings.Contains(err.Error(), "a socket of a service the agent never probes") {
			t.Errorf("%s = %v, %v; want it refused", p, got, err)
		}
	}
	for _, p := range []string{"/run/docker.sock", "/var/run/docker.sock", "/run/user/0/bus"} {
		if got, err := probe(p); !errors.Is(err, ErrNotAllowed) {
			t.Errorf("%s = %v, %v; want it refused before any dial", p, got, err)
		}
	}
	if got, err := probe(filepath.Join(filepath.Dir(link), "gone.sock")); err != nil || fmt.Sprint(got) != "map[connected:false]" {
		t.Errorf("a missing socket = %v, %v; want it not connected", got, err)
	}
}

// TestUnixSocketSensorNeverConnectsToAForwarder: a forwarder serving a socket hands the connection on
// to an end the guard never checked (R-1376).
func TestUnixSocketSensorNeverConnectsToAForwarder(t *testing.T) {
	h := servedBy(t, "socat")
	path, _ := unixFake(t, func(c *fakeConn) { c.drain() })
	probe := func() (map[string]any, error) {
		return unixSocketSensor(context.Background(), unixProbe(map[string]any{"path": path}), "")
	}
	pid := int32(os.Getpid())
	h.args = map[int32][]string{}
	for _, c := range []struct {
		name string
		args []string
		want string
	}{
		{"socat", nil, "belongs to socat, which forwards"},
		{"sslh-select", nil, "belongs to sslh-select, which forwards"},
		{"exe", []string{"/usr/libexec/podman/rootlessport"}, "belongs to rootlessport, which forwards"},
		{"exe", nil, "the process exe serving " + path + " cannot be told"},
	} {
		h.names[pid] = c.name
		delete(h.args, pid)
		if c.args != nil {
			h.args[pid] = c.args
		}
		if got, err := probe(); !errors.Is(err, ErrNotAllowed) || !strings.Contains(err.Error(), c.want) {
			t.Errorf("served by %s %v = %v, %v; want it refused: %s", c.name, c.args, got, err, c.want)
		}
	}
	h.names[pid], h.args[pid] = "exe", []string{"/usr/bin/caddy", "run"}
	if got, err := probe(); err != nil || got["connected"] != true {
		t.Errorf("served by a reexec of caddy = %v, %v; want it connected", got, err)
	}
}

// listenCounting serves path and counts the connections it accepts.
func listenCounting(t *testing.T, path string) *atomic.Int32 {
	t.Helper()
	ln, err := net.Listen("unix", path)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = ln.Close() })
	var n atomic.Int32
	go func() {
		for {
			c, err := ln.Accept()
			if err != nil {
				return
			}
			n.Add(1)
			_ = c.Close()
		}
	}()
	return &n
}

func TestDialUnixFollowsTheSocketNotItsName(t *testing.T) {
	servedBy(t, "nginx")
	dir := filepath.Dir(socketIn(t))
	ctx := context.Background()
	old := controlSockets
	t.Cleanup(func() { controlSockets = old })
	refused := func(p, why string) {
		t.Helper()
		c, err := dialUnix(ctx, p)
		if c != nil {
			_ = c.Close()
		}
		if !errors.Is(err, ErrNotAllowed) || !strings.Contains(err.Error(), why) {
			t.Errorf("dialUnix(%s) = %v; want it refused: %s", p, err, why)
		}
	}

	// A second name of a single control socket is refused before the dial.
	ctl := filepath.Join(dir, "ctl.sock")
	accepted := listenCounting(t, ctl)
	controlSockets = append(slices.Clone(old), ctl)
	hard := filepath.Join(dir, "h.sock")
	if err := os.Link(ctl, hard); err != nil {
		t.Fatal(err)
	}
	refused(hard, "under another name")
	if n := accepted.Load(); n != 0 {
		t.Errorf("the control socket took %d connections; want none", n)
	}

	// A directory of controlSockets renamed after the bind: the name its server bound gives it away.
	if err := os.Mkdir(filepath.Join(dir, "a"), 0o700); err != nil {
		t.Fatal(err)
	}
	listenCounting(t, filepath.Join(dir, "a", "s.sock"))
	controlSockets = append(slices.Clone(old), filepath.Join(dir, "a")+"/")
	if err := os.Rename(filepath.Join(dir, "a"), filepath.Join(dir, "b")); err != nil {
		t.Fatal(err)
	}
	refused(filepath.Join(dir, "b", "s.sock"), "a socket of a service the agent never probes")
	controlSockets = old
	if c, err := dialUnix(ctx, filepath.Join(dir, "b", "s.sock")); err != nil {
		t.Errorf("the renamed socket outside controlSockets = %v; want it connected", err)
	} else {
		_ = c.Close()
	}

	// A server that bound a relative path says nothing about where its socket is.
	t.Chdir(dir)
	listenCounting(t, "r.sock")
	refused(filepath.Join(dir, "r.sock"), "bound no absolute path")
}
