// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package discovery

import (
	"cmp"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io/fs"
	"net/netip"
	"os"
	"os/exec"
	"reflect"
	"slices"
	"strconv"
	"strings"
	"sync"
	"testing"
	"time"

	"adminhelper-agent/internal/allowlist"
	"adminhelper-agent/internal/probe"
)

// TestMain doubles as a process that exits with the code DISCOVERY_TEST_EXIT names: exitError's
// real *exec.ExitError on every platform.
func TestMain(m *testing.M) {
	if code := os.Getenv("DISCOVERY_TEST_EXIT"); code != "" {
		n, _ := strconv.Atoi(code)
		os.Exit(n)
	}
	os.Exit(m.Run())
}

// exitError is the error of a tool that exited with code.
func exitError(t *testing.T, code int) error {
	t.Helper()
	cmd := exec.Command(os.Args[0], "-test.run=^$")
	cmd.Env = append(os.Environ(), "DISCOVERY_TEST_EXIT="+strconv.Itoa(code))
	err := cmd.Run()
	var exitErr *exec.ExitError
	if !errors.As(err, &exitErr) || exitErr.ExitCode() != code {
		t.Fatalf("helper process: %v, want exit %d", err, code)
	}
	return err
}

// fakeHost is a stubbed host: its tools by name (one not named is not installed), the paths that
// exist, its listeners and their processes, the containers its processes run in and the protocols
// of its ports.
type fakeHost struct {
	mu         sync.Mutex
	tools      map[string]func(args []string) ([]byte, error)
	calls      [][]string
	paths      map[string]bool
	stat       func(path string) (os.FileInfo, error)
	listeners  []probe.Listener
	listenErr  error
	processes  map[int32]string
	cgroups    map[int32]probe.Cgroups
	cgroupRead map[int32]int
	protocols  map[uint16]string
	recognize  func(ctx context.Context, port uint16) (string, error)
	recognized []uint16
}

func stubHost(t *testing.T) *fakeHost {
	t.Helper()
	h := &fakeHost{
		tools:      map[string]func([]string) ([]byte, error){},
		paths:      map[string]bool{systemdDir: true},
		processes:  map[int32]string{},
		cgroups:    map[int32]probe.Cgroups{},
		cgroupRead: map[int32]int{},
		protocols:  map[uint16]string{},
	}
	oldLinux, oldRun, oldStat, oldList, oldName, oldRecognize, oldCgroups :=
		linuxHost, runTool, statPath, listSockets, processName, recognizePort, cgroupsOf
	t.Cleanup(func() {
		linuxHost, runTool, statPath, listSockets, processName, recognizePort, cgroupsOf =
			oldLinux, oldRun, oldStat, oldList, oldName, oldRecognize, oldCgroups
	})
	linuxHost = true
	runTool = func(_ context.Context, _ time.Duration, name string, args ...string) ([]byte, error) {
		h.mu.Lock()
		h.calls = append(h.calls, append([]string{name}, args...))
		if !allowlist.Allowed(name, args) {
			t.Errorf("call %q is not on the command allowlist", append([]string{name}, args...))
		}
		tool, ok := h.tools[name]
		h.mu.Unlock()
		if !ok {
			return nil, exec.ErrNotFound
		}
		return tool(args)
	}
	statPath = func(p string) (os.FileInfo, error) {
		if h.stat != nil {
			return h.stat(p)
		}
		if h.paths[p] {
			return nil, nil
		}
		return nil, fs.ErrNotExist
	}
	listSockets = func(context.Context) ([]probe.Listener, error) { return h.listeners, h.listenErr }
	processName = func(_ context.Context, pid int32) string { return h.processes[pid] }
	cgroupsOf = func(pid int32) probe.Cgroups {
		h.mu.Lock()
		defer h.mu.Unlock()
		h.cgroupRead[pid]++
		return h.cgroups[pid]
	}
	recognizePort = func(ctx context.Context, port uint16) (string, error) {
		h.mu.Lock()
		h.recognized = append(h.recognized, port)
		h.mu.Unlock()
		if h.recognize != nil {
			return h.recognize(ctx, port)
		}
		if name, ok := h.protocols[port]; ok {
			return name, nil
		}
		return "", errors.New("connection refused")
	}
	return h
}

// answer has the tool name answer out and err.
func (h *fakeHost) answer(name, out string, err error) {
	h.tools[name] = func([]string) ([]byte, error) { return []byte(out), err }
}

// called returns the calls of the tool name.
func (h *fakeHost) called(name string) [][]string {
	h.mu.Lock()
	defer h.mu.Unlock()
	var calls [][]string
	for _, c := range h.calls {
		if c[0] == name {
			calls = append(calls, c[1:])
		}
	}
	return calls
}

func listener(addr string, port uint16, pid int32) probe.Listener {
	return probe.Listener{Addr: netip.MustParseAddr(addr), Port: port, PID: pid}
}

func port16(p uint16) *uint16 { return &p }

var (
	idWeb  = strings.Repeat("a", 64)
	idHost = strings.Repeat("b", 64)
	idOld  = strings.Repeat("c", 64)
)

// scope is the cgroup docker runs the container id in, under cgroup v2 and the systemd driver.
func scope(id string) probe.Cgroups {
	return probe.Cgroups{"0:": "/system.slice/docker-" + id + ".scope"}
}

const units = `cron.service loaded active running Regular background program processing daemon
nginx.service loaded active running A high performance web server
ghost.service not-found inactive dead ghost.service
postfix.service masked inactive dead postfix.service
short line
`

// inspectJSON has the shape `docker inspect` printed on a Docker host (Engine API v1.47).
var inspectJSON = `[
 {"Id": "` + idWeb + `", "Name": "/web",
  "Config": {"Image": "nginx:1.27", "Env": ["SECRET=x"], "Cmd": ["nginx", "-g", "daemon off;"],
   "Labels": {"com.docker.compose.project": "site", "com.docker.compose.service": "web", "other": "x"}},
  "State": {"Status": "running", "Pid": 4100, "Health": {"Status": "healthy"}},
  "HostConfig": {"NetworkMode": "site_default"},
  "NetworkSettings": {"Ports": {
   "80/tcp": [{"HostIp": "0.0.0.0", "HostPort": "8080"}, {"HostIp": "::", "HostPort": "8080"}],
   "443/tcp": null,
   "53/udp": [{"HostIp": "127.0.0.1", "HostPort": "5353"}]}},
  "Mounts": [{"Destination": "/var/www"}, {"Destination": "/etc/nginx"}, {"Destination": "/var/www"}]},
 {"Id": "` + idHost + `", "Name": "/hostnet", "Config": {"Image": "example/hostnet:2", "Labels": null},
  "State": {"Status": "running", "Pid": 4200, "Health": null}, "HostConfig": {"NetworkMode": "host"},
  "NetworkSettings": {"Ports": {}}, "Mounts": []},
 {"Id": "` + idOld + `", "Name": "/old", "Config": {"Image": "busybox", "Labels": {}},
  "State": {"Status": "exited"}, "NetworkSettings": {"Ports": {}}, "Mounts": []}
]`

// wholeHost is a host with something of everything: units, containers on their own network and the
// host's, listeners of all kinds, markers by path and by package.
func wholeHost(t *testing.T) *fakeHost {
	h := stubHost(t)
	h.answer("systemctl", units, nil)
	h.answer("docker", "", nil)
	h.tools["docker"] = func(args []string) ([]byte, error) {
		if args[0] == "ps" {
			return []byte(idWeb + "\n" + idHost + "\n" + idOld + "\n"), nil
		}
		return []byte(inspectJSON), nil
	}
	h.listeners = []probe.Listener{
		listener("0.0.0.0", 8080, 100), listener("::", 8080, 101),
		listener("0.0.0.0", 22, 1),
		listener("127.0.0.1", 631, 5),
		listener("192.0.2.10", 9000, 200),
		listener("0.0.0.0", 2525, 300),
		listener("0.0.0.0", 9100, 400),
		listener("0.0.0.0", 80, 500), listener("0.0.0.0", 80, 501), listener("::", 80, 500),
		listener("192.0.2.10", 9001, 201),
		listener("127.0.0.1", 7000, 600),
	}
	h.processes = map[int32]string{100: "docker-proxy", 101: "docker-proxy", 1: "sshd", 5: "cupsd",
		200: "hostapp", 201: "hostapp", 300: "mariadbd", 400: "node_exporter", 500: "nginx", 501: "nginx",
		600: "lookalike"}
	hostWorker := probe.Cgroups{"0:": scope(idHost)["0:"] + "/worker"}
	h.cgroups = map[int32]probe.Cgroups{4100: scope(idWeb), 4200: scope(idHost), 200: scope(idHost),
		201: hostWorker, 100: scope(idWeb),
		// A cgroup a user may create in the subtree delegated to them, named like the container's.
		600: {"0:": "/user.slice/user-1000.slice/user@1000.service/docker-" + idHost + ".scope"}}
	h.protocols = map[uint16]string{80: "http", 8080: "http", 22: "ssh", 2525: "smtp", 9100: "http", 631: "http"}
	h.paths["/etc/nginx"] = true
	dpkgExit1 := exitError(t, 1)
	// foo is wanted, not installed (in); redis-server removed, its configuration kept (rc).
	h.answer("dpkg-query", "nginx\tii \nfoo\tin \nredis-server\trc \n", dpkgExit1)
	return h
}

var wholeMarkers = []probe.Marker{
	{ID: "nginx", Paths: []string{"/etc/nginx"}, Packages: []string{"nginx"}},
	{ID: "redis", Paths: []string{"/etc/redis"}, Packages: []string{"redis-server"}},
	{ID: "pkgonly", Packages: []string{"foo"}},
}

func TestRunDiscoversTheHost(t *testing.T) {
	h := wholeHost(t)

	inv := Run(context.Background(), wholeMarkers)

	if inv.Partial {
		t.Error("partial = true, want a whole discovery")
	}
	if inv.TS == 0 || inv.DurationMS < 0 {
		t.Errorf("ts %d, duration_ms %d: want the start and the time it took", inv.TS, inv.DurationMS)
	}
	wantUnits := []Unit{{"cron.service", "active", "running"}, {"nginx.service", "active", "running"},
		{"postfix.service", "inactive", "dead"}}
	if !reflect.DeepEqual(inv.Units, wantUnits) {
		t.Errorf("units = %+v, want %+v (a unit not found is none)", inv.Units, wantUnits)
	}
	if got := h.called("systemctl"); !reflect.DeepEqual(got, [][]string{{"list-units", "--type=service", "--all",
		"--full", "--no-legend", "--plain", "--no-pager"}}) {
		t.Errorf("systemctl calls = %q", got)
	}
	wantContainers := []Container{
		{ID: idHost, Name: "hostnet", Image: "example/hostnet:2", State: "running",
			Ports: []ContainerPort{}, Mounts: []string{}, pid: 4200},
		{ID: idOld, Name: "old", Image: "busybox", State: "exited", Ports: []ContainerPort{}, Mounts: []string{}},
		{ID: idWeb, Name: "web", Image: "nginx:1.27", ComposeProject: "site", ComposeService: "web",
			State: "running", Health: "healthy",
			Ports:  []ContainerPort{{53, port16(5353), "udp"}, {80, port16(8080), "tcp"}, {443, nil, "tcp"}},
			Mounts: []string{"/etc/nginx", "/var/www"}, pid: 4100,
			binds: []netip.AddrPort{netip.MustParseAddrPort("0.0.0.0:8080"), netip.MustParseAddrPort("[::]:8080")}},
	}
	if !reflect.DeepEqual(inv.Containers, wantContainers) {
		t.Errorf("containers =\n%+v\nwant\n%+v", inv.Containers, wantContainers)
	}
	if got := h.called("docker"); len(got) != 2 || !reflect.DeepEqual(got[0], []string{"ps", "--all", "--quiet", "--no-trunc"}) ||
		!reflect.DeepEqual(got[1], []string{"inspect", "--type", "container", idWeb, idHost, idOld}) {
		t.Errorf("docker calls = %q", got)
	}
	wantSockets := []Socket{
		{"tcp", "0.0.0.0", 22, "sshd", ""},
		{"tcp", "0.0.0.0", 80, "nginx", ""},
		{"tcp6", "::", 80, "nginx", ""},
		{"tcp", "127.0.0.1", 631, "cupsd", ""},
		{"tcp", "0.0.0.0", 2525, "mariadbd", ""},
		{"tcp", "127.0.0.1", 7000, "lookalike", ""},
		{"tcp", "0.0.0.0", 8080, "docker-proxy", "web"},
		{"tcp6", "::", 8080, "docker-proxy", "web"},
		{"tcp", "192.0.2.10", 9000, "hostapp", "hostnet"},
		{"tcp", "192.0.2.10", 9001, "hostapp", "hostnet"},
		{"tcp", "0.0.0.0", 9100, "node_exporter", ""},
	}
	if !reflect.DeepEqual(inv.Sockets, wantSockets) {
		t.Errorf("sockets =\n%+v\nwant\n%+v", inv.Sockets, wantSockets)
	}
	if h.cgroupRead[500] != 1 || h.cgroupRead[100] != 0 || h.cgroupRead[4100] != 1 || h.cgroupRead[4200] != 1 {
		t.Errorf("cgroup reads = %v, want one per process and running container, none for docker-proxy", h.cgroupRead)
	}
	wantMarkers := map[string]bool{"nginx": true, "redis": false, "pkgonly": false}
	if !reflect.DeepEqual(inv.Markers, wantMarkers) {
		t.Errorf("markers = %v, want %v", inv.Markers, wantMarkers)
	}
	if got := h.called("dpkg-query"); !reflect.DeepEqual(got, [][]string{{"--show",
		`--showformat=${Package}\t${db:Status-Abbrev}\n`, "--", "foo", "nginx", "redis-server"}}) {
		t.Errorf("dpkg-query calls = %q", got)
	}
	wantPorts := []Port{{80, "tcp", "http"}, {8080, "tcp", "http"}}
	if !reflect.DeepEqual(inv.Ports, wantPorts) {
		t.Errorf("ports = %+v, want %+v", inv.Ports, wantPorts)
	}
	// Never 22, 9100 or a port of mariadbd, never one on loopback alone; 9000 refused is left out.
	slices.Sort(h.recognized)
	if !reflect.DeepEqual(h.recognized, []uint16{80, 8080, 9000, 9001}) {
		t.Errorf("recognized ports %v, want 80, 8080, 9000 and 9001", h.recognized)
	}
}

func TestAContainerWhoseCgroupCannotBeReadRunsNoSocket(t *testing.T) {
	h := wholeHost(t)
	delete(h.cgroups, 4200)

	inv := Run(context.Background(), nil)

	for _, s := range inv.Sockets {
		if s.Container == "hostnet" {
			t.Errorf("socket %+v is the container's, whose cgroup cannot be read", s)
		}
	}
}

func TestTextsTheContractCannotCarryAreLeftEmpty(t *testing.T) {
	h := stubHost(t)
	long := strings.Repeat("x", 100_000)
	h.answer("systemctl", strings.Repeat("u", 256)+".service loaded active running too long\n"+
		"ok.service loaded "+strings.Repeat("a", 65)+" running x\n"+
		"ok2.service loaded active r\x01un x\n", nil)
	h.tools["docker"] = func(args []string) ([]byte, error) {
		if args[0] == "ps" {
			return []byte(idWeb + "\n" + idHost + "\n"), nil
		}
		return json.Marshal([]map[string]any{
			{"Id": strings.Repeat("d", 129), "Name": "/web",
				"Config": map[string]any{"Image": strings.Repeat("i", 513),
					"Labels": map[string]string{"com.docker.compose.project": "a\x7fb",
						"com.docker.compose.service": strings.Repeat("s", 255)}},
				"State": map[string]any{"Status": "running", "Health": map[string]string{"Status": "a\nb"}},
				"Mounts": []map[string]string{{"Destination": "/" + strings.Repeat("m", 1024)},
					{"Destination": "/ok"}, {"Destination": "/bad\tpath"}}},
			{"Id": idHost, "Name": "/" + strings.Repeat("n", 256)},
		})
	}
	h.listeners = []probe.Listener{listener("127.0.0.1", 1000, 10), listener("127.0.0.1", 1001, 11),
		listener("127.0.0.1", 1002, 12)}
	h.processes = map[int32]string{10: long, 11: "evil\nname", 12: strings.Repeat("ä", 255)}

	inv := Run(context.Background(), nil)

	wantUnits := []Unit{{"ok.service", "", "running"}, {"ok2.service", "active", ""}}
	if !reflect.DeepEqual(inv.Units, wantUnits) {
		t.Errorf("units = %+v, want %+v", inv.Units, wantUnits)
	}
	wantContainers := []Container{{Name: "web", ComposeService: strings.Repeat("s", 255), State: "running",
		Ports: []ContainerPort{}, Mounts: []string{"/ok"}}}
	if !reflect.DeepEqual(inv.Containers, wantContainers) {
		t.Errorf("containers = %+v, want %+v", inv.Containers, wantContainers)
	}
	wantSockets := []Socket{{"tcp", "127.0.0.1", 1000, "", ""}, {"tcp", "127.0.0.1", 1001, "", ""},
		{"tcp", "127.0.0.1", 1002, strings.Repeat("ä", 255), ""}}
	if !reflect.DeepEqual(inv.Sockets, wantSockets) {
		t.Errorf("sockets = %+v, want the names too long or with a control character empty", inv.Sockets)
	}
}

// keys returns the keys of the JSON object data.
func keys(t *testing.T, data []byte) []string {
	t.Helper()
	var m map[string]json.RawMessage
	if err := json.Unmarshal(data, &m); err != nil {
		t.Fatal(err)
	}
	var k []string
	for key := range m {
		k = append(k, key)
	}
	slices.Sort(k)
	return k
}

func TestTheInventoryHasTheContractsShape(t *testing.T) {
	wholeHost(t)
	data, err := json.Marshal(Run(context.Background(), wholeMarkers))
	if err != nil {
		t.Fatal(err)
	}
	var inv struct {
		Units, Sockets, Containers, Ports []json.RawMessage
	}
	if err := json.Unmarshal(data, &inv); err != nil {
		t.Fatal(err)
	}
	for _, c := range []struct {
		name string
		got  []string
		want string
	}{
		{"inventory", keys(t, data), "containers duration_ms markers partial ports sockets ts units"},
		{"unit", keys(t, inv.Units[0]), "name state sub"},
		{"socket", keys(t, inv.Sockets[0]), "addr container port process proto"},
		{"container", keys(t, inv.Containers[2]), "compose_project compose_service health id image mounts name ports state"},
		{"port", keys(t, inv.Ports[0]), "port proto protocol"},
	} {
		if strings.Join(c.got, " ") != c.want {
			t.Errorf("%s keys = %v, want %s", c.name, c.got, c.want)
		}
	}
	if !strings.Contains(string(inv.Containers[2]), `{"private":443,"public":null,"proto":"tcp"}`) {
		t.Errorf("container = %s, want an unpublished port with public null", inv.Containers[2])
	}
	if strings.Contains(string(data), "SECRET") || strings.Contains(string(data), "daemon off") ||
		strings.Contains(string(data), `"other"`) {
		t.Errorf("inventory = %s, want no environment, command or other label", data)
	}
}

func TestADiscoveryOfANearlyEmptyHostIsWhole(t *testing.T) {
	h := stubHost(t)
	delete(h.paths, systemdDir)

	inv := Run(context.Background(), nil)

	data, _ := json.Marshal(inv)
	for _, want := range []string{`"partial":false`, `"units":[]`, `"sockets":[]`, `"containers":[]`, `"markers":{}`, `"ports":[]`} {
		if !strings.Contains(string(data), want) {
			t.Errorf("inventory = %s, want %s", data, want)
		}
	}
	// Without systemd no systemctl; docker is not installed.
	if got := h.called("systemctl"); got != nil {
		t.Errorf("systemctl calls without systemd = %q, want none", got)
	}
	if got := h.called("docker"); len(got) != 1 {
		t.Errorf("docker calls = %q, want the one that finds it missing", got)
	}
}

func TestADiscoveryOffLinuxReadsTheSocketsAlone(t *testing.T) {
	h := wholeHost(t)
	linuxHost = false

	inv := Run(context.Background(), wholeMarkers)

	if inv.Partial || len(inv.Units) != 0 || len(inv.Containers) != 0 || len(inv.Markers) != 0 {
		t.Errorf("inventory = %+v, want sockets and ports alone, whole", inv)
	}
	if len(inv.Sockets) == 0 || len(inv.Ports) != 2 {
		t.Errorf("sockets %d, ports %+v: want them read", len(inv.Sockets), inv.Ports)
	}
	if len(h.calls) != 0 {
		t.Errorf("tool calls %q off Linux, want none", h.calls)
	}
}

func TestAPartTheDiscoveryCouldNotReadMakesItPartial(t *testing.T) {
	cases := []struct {
		name  string
		spoil func(t *testing.T, h *fakeHost)
		check func(t *testing.T, inv Inventory)
	}{
		{"systemctl fails", func(_ *testing.T, h *fakeHost) {
			h.answer("systemctl", "", errors.New("Failed to connect to bus"))
		}, func(t *testing.T, inv Inventory) {
			if len(inv.Units) != 0 {
				t.Errorf("units = %+v, want none", inv.Units)
			}
		}},
		{"docker daemon down", func(t *testing.T, h *fakeHost) {
			h.answer("docker", "", exitError(t, 1))
		}, func(t *testing.T, inv Inventory) {
			if len(inv.Containers) != 0 {
				t.Errorf("containers = %+v, want none", inv.Containers)
			}
		}},
		{"a container went away before inspect", func(t *testing.T, h *fakeHost) {
			gone := exitError(t, 1)
			h.tools["docker"] = func(args []string) ([]byte, error) {
				if args[0] == "ps" {
					return []byte(idWeb + "\n" + idOld + "\n"), nil
				}
				return []byte(`[{"Id": "` + idWeb + `", "Name": "/web", "State": {"Status": "running"}}]`), gone
			}
		}, func(t *testing.T, inv Inventory) {
			if len(inv.Containers) != 1 || inv.Containers[0].Name != "web" {
				t.Errorf("containers = %+v, want the one inspect still printed", inv.Containers)
			}
		}},
		{"inspect answers no JSON", func(_ *testing.T, h *fakeHost) {
			h.tools["docker"] = func(args []string) ([]byte, error) {
				if args[0] == "ps" {
					return []byte(idWeb + "\n"), nil
				}
				return []byte("Error response from daemon"), nil
			}
		}, func(t *testing.T, inv Inventory) {
			if len(inv.Containers) != 0 {
				t.Errorf("containers = %+v, want none", inv.Containers)
			}
		}},
		{"the listeners cannot be read", func(_ *testing.T, h *fakeHost) {
			h.listenErr = errors.New("permission denied")
		}, func(t *testing.T, inv Inventory) {
			if len(inv.Sockets) != 0 || len(inv.Ports) != 0 {
				t.Errorf("sockets %+v, ports %+v: want none", inv.Sockets, inv.Ports)
			}
		}},
		{"dpkg-query fails", func(t *testing.T, h *fakeHost) {
			h.answer("dpkg-query", "", exitError(t, 2))
		}, func(t *testing.T, inv Inventory) {
			// nginx is there by its path; the others are undecided.
			if !reflect.DeepEqual(inv.Markers, map[string]bool{"nginx": true}) {
				t.Errorf("markers = %v, want nginx alone", inv.Markers)
			}
		}},
		{"rpm runs out of time", func(_ *testing.T, h *fakeHost) {
			delete(h.tools, "dpkg-query")
			h.answer("rpm", "", context.DeadlineExceeded)
		}, func(t *testing.T, inv Inventory) {
			if !reflect.DeepEqual(inv.Markers, map[string]bool{"nginx": true}) {
				t.Errorf("markers = %v, want nginx alone", inv.Markers)
			}
		}},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			h := wholeHost(t)
			c.spoil(t, h)

			inv := Run(context.Background(), wholeMarkers)

			if !inv.Partial {
				t.Error("partial = false, want a discovery that could not read a part partial")
			}
			c.check(t, inv)
		})
	}
}

func TestRpmTellsTheInstalledPackages(t *testing.T) {
	h := wholeHost(t)
	delete(h.tools, "dpkg-query")
	notAll := exitError(t, 1)
	h.answer("rpm", "nginx\npackage foo is not installed\npackage redis-server is not installed\n", notAll)

	inv := Run(context.Background(), wholeMarkers)

	if inv.Partial || !reflect.DeepEqual(inv.Markers, map[string]bool{"nginx": true, "redis": false, "pkgonly": false}) {
		t.Errorf("partial %v, markers %v: want nginx alone installed, whole", inv.Partial, inv.Markers)
	}
	if got := h.called("rpm"); !reflect.DeepEqual(got, [][]string{{"--query", `--queryformat=%{NAME}\n`, "foo", "nginx", "redis-server"}}) {
		t.Errorf("rpm calls = %q", got)
	}
}

func TestPackagesAreAskedForInBatches(t *testing.T) {
	h := stubHost(t)
	h.tools["dpkg-query"] = func(args []string) ([]byte, error) {
		return []byte(args[3] + "\tii \n"), nil
	}
	names := make([]string, packageBatch+1)
	for i := range names {
		names[i] = "p" + strconv.Itoa(1000+i)
	}

	installed, whole := installedPackages(context.Background(), names)

	calls := h.called("dpkg-query")
	if !whole || len(calls) != 2 || len(calls[0]) != 3+packageBatch || len(calls[1]) != 4 {
		t.Fatalf("whole %v, %d calls: want two batches", whole, len(calls))
	}
	if !installed[names[0]] || !installed[names[packageBatch]] || len(installed) != 2 {
		t.Errorf("installed = %v, want the first of each batch", installed)
	}
}

func TestTheEndOfTheFrameMakesTheDiscoveryPartial(t *testing.T) {
	h := wholeHost(t)
	h.recognize = func(ctx context.Context, _ uint16) (string, error) {
		<-ctx.Done()
		return "", ctx.Err()
	}
	ctx, cancel := context.WithTimeout(context.Background(), 200*time.Millisecond)
	defer cancel()

	began := time.Now()
	inv := Run(ctx, wholeMarkers)

	if !inv.Partial {
		t.Error("partial = false, want a discovery the frame cut short partial")
	}
	if took := time.Since(began); took > 5*time.Second {
		t.Errorf("Run took %v, want it to end with its frame", took)
	}
	if len(inv.Units) == 0 || len(inv.Ports) != 0 {
		t.Errorf("units %d, ports %+v: want what was read before the end, no port", len(inv.Units), inv.Ports)
	}
}

func TestAPathThatHangsIsLeftBehind(t *testing.T) {
	h := wholeHost(t)
	release := make(chan struct{})
	t.Cleanup(func() { close(release) })
	h.stat = func(p string) (os.FileInfo, error) {
		if p == "/etc/redis" {
			<-release
		}
		if p == systemdDir || p == "/etc/nginx" {
			return nil, nil
		}
		return nil, fs.ErrNotExist
	}
	ctx, cancel := context.WithTimeout(context.Background(), 300*time.Millisecond)
	defer cancel()

	markers, whole := checkMarkers(ctx, wholeMarkers)

	if whole {
		t.Error("whole = true, want a check left behind to count")
	}
	// nginx is installed, its path checked before /etc/redis; the others are undecided.
	if !reflect.DeepEqual(markers, map[string]bool{"nginx": true}) {
		t.Errorf("markers = %v, want nginx alone", markers)
	}
}

func TestOnlyValidMarkersAreChecked(t *testing.T) {
	long := "/" + strings.Repeat("x", maxPathLen)
	many := func(f func(i int) string) []string {
		s := make([]string, 17)
		for i := range s {
			s[i] = f(i)
		}
		return s
	}
	markers := []probe.Marker{
		{ID: "ok", Paths: []string{"/etc/ok"}, Packages: []string{"ok-pkg", "libstdc++6", "python3.13"}},
		{ID: "ok", Paths: []string{"/etc/second"}},
		{ID: "Upper", Paths: []string{"/etc/x"}},
		{ID: "-dash", Paths: []string{"/etc/x"}},
		{ID: "relative", Paths: []string{"etc/x"}},
		{ID: "unclean", Paths: []string{"/etc/../x"}},
		{ID: "trailing", Paths: []string{"/etc/x/"}},
		{ID: "nul", Paths: []string{"/etc/x\x00"}},
		{ID: "backslash", Paths: []string{`/etc\x`}},
		{ID: "colon", Paths: []string{"/etc/c:x"}},
		{ID: "long", Paths: []string{long}},
		{ID: "paths", Paths: many(func(i int) string { return "/p" + strconv.Itoa(i) })},
		{ID: "option", Packages: []string{"-x"}},
		{ID: "pkgupper", Packages: []string{"Foo"}},
		{ID: "pkgs", Packages: many(func(i int) string { return "p" + strconv.Itoa(i) })},
		{ID: "last", Paths: []string{"/"}},
	}

	valid := validMarkers(markers)

	var ids []string
	for _, m := range valid {
		ids = append(ids, m.ID)
	}
	if !reflect.DeepEqual(ids, []string{"ok", "last"}) || valid[0].Paths[0] != "/etc/ok" {
		t.Errorf("valid markers = %+v, want the first ok and last", valid)
	}
	if !cleanPath("/" + strings.Repeat("x", maxPathLen-1)) {
		t.Error("a path of maxPathLen is refused, want it checked")
	}
}

func TestTheListsAreCutAtTheContractsCaps(t *testing.T) {
	t.Run("units", func(t *testing.T) {
		h := stubHost(t)
		var b strings.Builder
		for i := range maxUnits + 1 {
			b.WriteString("u" + strconv.Itoa(i) + ".service loaded active running x\n")
		}
		h.answer("systemctl", b.String(), nil)
		inv := Run(context.Background(), nil)
		if !inv.Partial || len(inv.Units) != maxUnits {
			t.Errorf("partial %v, %d units: want %d, partial", inv.Partial, len(inv.Units), maxUnits)
		}
	})
	t.Run("containers", func(t *testing.T) {
		h := stubHost(t)
		h.tools["docker"] = func(args []string) ([]byte, error) {
			if args[0] == "ps" {
				var ids []string
				for i := range maxContainers + 1 {
					ids = append(ids, fmt.Sprintf("%064x", i))
				}
				return []byte(strings.Join(ids, "\n")), nil
			}
			var out []string
			for _, id := range args[3:] {
				out = append(out, `{"Id": "`+id+`", "Name": "/c`+id+`"}`)
			}
			return []byte("[" + strings.Join(out, ",") + "]"), nil
		}
		inv := Run(context.Background(), nil)
		if inspect := h.called("docker")[1]; len(inspect) != 3+maxContainers {
			t.Errorf("inspect asked for %d containers, want %d", len(inspect)-3, maxContainers)
		}
		if !inv.Partial || len(inv.Containers) != maxContainers {
			t.Errorf("partial %v, %d containers: want %d, partial", inv.Partial, len(inv.Containers), maxContainers)
		}
	})
	t.Run("sockets", func(t *testing.T) {
		h := stubHost(t)
		for i := range maxSockets + 1 {
			h.listeners = append(h.listeners, listener("127.0.0.1", uint16(10000+i), 0))
		}
		inv := Run(context.Background(), nil)
		if !inv.Partial || len(inv.Sockets) != maxSockets || inv.Sockets[maxSockets-1].Port != 10000+maxSockets-1 {
			t.Errorf("partial %v, %d sockets: want the first %d, partial", inv.Partial, len(inv.Sockets), maxSockets)
		}
	})
	t.Run("container ports and mounts", func(t *testing.T) {
		var c inspected
		c.NetworkSettings.Ports = map[string][]portBinding{}
		for i := range maxContainerPorts + 1 {
			c.NetworkSettings.Ports[strconv.Itoa(1000+i)+"/tcp"] = nil
		}
		for i := range maxMounts + 1 {
			c.Mounts = append(c.Mounts, struct{ Destination string }{"/m" + strconv.Itoa(100+i)})
		}
		got := toContainer(c)
		if len(got.Ports) != maxContainerPorts || got.Ports[0].Private != 1000 || len(got.Mounts) != maxMounts || got.Mounts[0] != "/m100" {
			t.Errorf("%d ports, %d mounts: want %d and %d, the first kept", len(got.Ports), len(got.Mounts), maxContainerPorts, maxMounts)
		}
	})
}

func TestContainerPortsSkipWhatIsNoPort(t *testing.T) {
	got := containerPorts(map[string][]portBinding{
		"x/tcp":     nil,
		"0/tcp":     nil,
		"70000/tcp": nil,
		"8080":      nil,
		"5000/tcp":  {{HostPort: ""}, {HostPort: "abc"}},
	})
	want := []ContainerPort{{5000, nil, "tcp"}}
	if !reflect.DeepEqual(got, want) {
		t.Errorf("ports = %+v, want %+v", got, want)
	}
}

// TestDockerProxyIsMatchedByAddressAndPort: two containers publish the same host port on different
// host addresses; each docker-proxy belongs to the container whose binding it listens on, a binding
// without a host address counts for 0.0.0.0 and ::, and one no binding names to none.
func TestDockerProxyIsMatchedByAddressAndPort(t *testing.T) {
	h := stubHost(t)
	var raw []inspected
	if err := json.Unmarshal([]byte(`[
 {"Id": "`+idWeb+`", "Name": "/a", "State": {"Status": "running"},
  "NetworkSettings": {"Ports": {"80/tcp": [{"HostIp": "127.0.0.1", "HostPort": "8080"}]}}},
 {"Id": "`+idHost+`", "Name": "/b", "State": {"Status": "running"},
  "NetworkSettings": {"Ports": {"80/tcp": [{"HostIp": "192.0.2.10", "HostPort": "8080"}],
   "53/udp": [{"HostIp": "", "HostPort": "9053"}]}}},
 {"Id": "`+idOld+`", "Name": "/c", "State": {"Status": "running"},
  "NetworkSettings": {"Ports": {"443/tcp": [{"HostIp": "", "HostPort": "8443"}]}}}
]`), &raw); err != nil {
		t.Fatal(err)
	}
	var containers []Container
	for _, c := range raw {
		containers = append(containers, toContainer(c))
	}
	h.listeners = []probe.Listener{
		listener("127.0.0.1", 8080, 100), listener("192.0.2.10", 8080, 101),
		listener("0.0.0.0", 8443, 102), listener("::", 8443, 103),
		listener("::ffff:127.0.0.1", 8080, 104), listener("0.0.0.0", 8080, 105), listener("0.0.0.0", 9053, 106),
	}
	h.processes = map[int32]string{100: "docker-proxy", 101: "docker-proxy", 102: "docker-proxy",
		103: "docker-proxy", 104: "docker-proxy", 105: "docker-proxy", 106: "docker-proxy"}

	got, ok := collectSockets(context.Background(), containers)

	want := []Socket{
		{"tcp", "127.0.0.1", 8080, "docker-proxy", "a"},
		{"tcp", "192.0.2.10", 8080, "docker-proxy", "b"},
		{"tcp", "0.0.0.0", 8443, "docker-proxy", "c"},
		{"tcp6", "::", 8443, "docker-proxy", "c"},
		{"tcp6", "::ffff:127.0.0.1", 8080, "docker-proxy", "a"},
		{"tcp", "0.0.0.0", 8080, "docker-proxy", ""},
		{"tcp", "0.0.0.0", 9053, "docker-proxy", ""},
	}
	slices.SortFunc(got, func(a, b Socket) int { return cmp.Or(cmp.Compare(a.Port, b.Port), strings.Compare(a.Addr, b.Addr)) })
	slices.SortFunc(want, func(a, b Socket) int { return cmp.Or(cmp.Compare(a.Port, b.Port), strings.Compare(a.Addr, b.Addr)) })
	if !ok || !reflect.DeepEqual(got, want) {
		t.Errorf("sockets (ok %v) =\n%+v\nwant\n%+v", ok, got, want)
	}
}

func TestAPartItsTimeCutShortMakesTheDiscoveryPartial(t *testing.T) {
	wholeHost(t)
	old := partTimeout
	partTimeout = 100 * time.Millisecond
	t.Cleanup(func() { partTimeout = old })
	// The processes cannot be read before the part's time is over: the sockets come back without them.
	processName = func(ctx context.Context, _ int32) string {
		<-ctx.Done()
		return ""
	}

	inv := Run(context.Background(), wholeMarkers)

	if !inv.Partial {
		t.Error("partial = false, want a part its time cut short partial")
	}
	if len(inv.Sockets) == 0 || slices.ContainsFunc(inv.Sockets, func(s Socket) bool { return s.Process != "" }) {
		t.Errorf("sockets = %+v, want them without their processes", inv.Sockets)
	}
	// The parts after it run in a time of their own.
	if len(inv.Markers) != len(wholeMarkers) {
		t.Errorf("markers = %v, want all of them decided", inv.Markers)
	}
}

func TestThePortsAreCutAtTheContractsCap(t *testing.T) {
	h := stubHost(t)
	sockets := make([]Socket, maxPorts+1)
	for i := range sockets {
		sockets[i] = Socket{Proto: "tcp", Addr: "0.0.0.0", Port: uint16(10000 + i), Process: "app"}
		h.protocols[sockets[i].Port] = "http"
	}

	ports, whole := recognizePorts(context.Background(), sockets)

	if whole || len(ports) != maxPorts || len(h.recognized) != maxPorts {
		t.Errorf("whole %v, %d ports of %d recognized: want the first %d, partial", whole, len(ports), len(h.recognized), maxPorts)
	}
	if ports[maxPorts-1].Port != uint16(10000+maxPorts-1) {
		t.Errorf("last port = %d, want the lowest ports kept", ports[maxPorts-1].Port)
	}
}
