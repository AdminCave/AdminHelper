// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package monitor

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"log/slog"
	"maps"
	"os"
	"os/exec"
	"reflect"
	"strings"
	"testing"
	"time"
)

func TestGetFloat(t *testing.T) {
	cases := []struct {
		name     string
		m        map[string]any
		key      string
		fallback float64
		want     float64
	}{
		{"float64", map[string]any{"k": 3.5}, "k", -1, 3.5},
		{"int", map[string]any{"k": 7}, "k", -1, 7},
		{"json.Number", map[string]any{"k": json.Number("2.25")}, "k", -1, 2.25},
		{"json.Number int", map[string]any{"k": json.Number("42")}, "k", -1, 42},
		// Invalid json.Number: Float64() fails, the error is discarded -> 0.
		{"json.Number invalid", map[string]any{"k": json.Number("abc")}, "k", -1, 0},
		{"string -> fallback", map[string]any{"k": "5"}, "k", -1, -1},
		{"bool -> fallback", map[string]any{"k": true}, "k", -1, -1},
		{"missing key -> fallback", map[string]any{"x": 1.0}, "k", 9, 9},
		{"nil map -> fallback", nil, "k", 9, 9},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			if got := getFloat(c.m, c.key, c.fallback); got != c.want {
				t.Errorf("getFloat(%v, %q, %v) = %v, erwartet %v",
					c.m, c.key, c.fallback, got, c.want)
			}
		})
	}
}

func TestParseDockerPS(t *testing.T) {
	out := []byte(`{"ID":"abc123","Names":"web","Image":"nginx","State":"running","Status":"Up 2h"}
{"ID":"def456","Names":"db","Image":"postgres","State":"exited","Status":"Exited (0)"}

not-json`)
	containers, ids, skipped := parseDockerPS(out)
	if len(containers) != 2 {
		t.Fatalf("want 2 containers (blank + non-json skipped), got %d: %v", len(containers), containers)
	}
	if containers[0]["name"] != "web" || containers[0]["state"] != "running" {
		t.Errorf("container 0: %v", containers[0])
	}
	if containers[1]["image"] != "postgres" || containers[1]["state"] != "exited" {
		t.Errorf("container 1: %v", containers[1])
	}
	if !reflect.DeepEqual(ids, []string{"abc123", "def456"}) {
		t.Errorf("ids = %v", ids)
	}
	if skipped != 1 {
		t.Errorf("skipped = %d, want 1 (the non-json line; blank lines are not counted)", skipped)
	}

	t.Run("docker CLI 29 line with nested Platform", func(t *testing.T) {
		// A real `docker ps -a --format '{{json .}}'` line of Docker CLI 29 (anonymized). Since 28.2 the
		// CLI prints Platform as an object; decoding into map[string]string dropped every line.
		out := []byte(`{"Command":"\"docker-entrypoint.s…\"","CreatedAt":"2026-09-25 09:28:43 +0000 UTC","HealthStatus":"none","ID":"0123456789ab","Image":"example/app:1.0","Labels":"com.docker.compose.project=demo,com.docker.compose.service=app","LocalVolumes":"0","Mounts":"demo_data","Names":"demo-app-1","Networks":"demo_default","Platform":{"architecture":"amd64","os":"linux"},"Ports":"80/tcp","RunningFor":"3 weeks ago","Size":"1.41MB (virtual 829MB)","State":"running","Status":"Up 3 weeks"}`)
		containers, ids, skipped := parseDockerPS(out)
		want := []map[string]string{{
			"id": "0123456789ab", "name": "demo-app-1", "image": "example/app:1.0",
			"state": "running", "status": "Up 3 weeks",
		}}
		if !reflect.DeepEqual(containers, want) {
			t.Errorf("containers = %v, want %v", containers, want)
		}
		if !reflect.DeepEqual(ids, []string{"0123456789ab"}) {
			t.Errorf("ids = %v", ids)
		}
		if skipped != 0 {
			t.Errorf("skipped = %d, want 0", skipped)
		}
	})
}

// Real `docker ps -a --format '{{json .}}'` and `docker inspect --type container` output of Docker 29.8
// (API 1.56) for four throwaway containers: on-failure:3 exiting 1 (RestartCount 3), OOM-killed under an
// 8 MiB limit, a running one whose healthcheck fails, and one that exited 3 without a healthcheck. The
// inspect objects are trimmed to a subset of their fields, which still leaves plenty the agent does not
// read (nested objects, arrays, null, Platform as a string where ps prints an object).
const dockerPSFixture = `{"Command":"\"sh -c 'exit 1'\"","CreatedAt":"2026-10-16 19:41:07 +0200 CEST","HealthStatus":"none","ID":"611889c0d0d7","Image":"alpine:3.22","Labels":"","LocalVolumes":"0","Mounts":"","Names":"ah-t1-restart3","Networks":"bridge","Platform":{"architecture":"amd64","os":"linux"},"Ports":"","RunningFor":"11 seconds ago","Size":"4.1kB (virtual 8.99MB)","State":"exited","Status":"Exited (1) 7 seconds ago"}
{"Command":"\"sh -c 'x=aaaaaaaaaa…\"","CreatedAt":"2026-10-16 19:41:05 +0200 CEST","HealthStatus":"none","ID":"c1f596e07951","Image":"alpine:3.22","Labels":"","LocalVolumes":"0","Mounts":"","Names":"ah-t1-oom","Networks":"bridge","Platform":{"architecture":"amd64","os":"linux"},"Ports":"","RunningFor":"13 seconds ago","Size":"4.1kB (virtual 8.99MB)","State":"exited","Status":"Exited (137) 12 seconds ago"}
{"Command":"\"sleep 600\"","CreatedAt":"2026-10-16 19:41:04 +0200 CEST","HealthStatus":"unhealthy","ID":"6ae4d13d53eb","Image":"alpine:3.22","Labels":"","LocalVolumes":"0","Mounts":"","Names":"ah-t1-unhealthy","Networks":"bridge","Platform":{"architecture":"amd64","os":"linux"},"Ports":"","RunningFor":"14 seconds ago","Size":"4.1kB (virtual 8.99MB)","State":"running","Status":"Up 13 seconds (unhealthy)"}
{"Command":"\"sh -c 'exit 3'\"","CreatedAt":"2026-10-16 19:41:02 +0200 CEST","HealthStatus":"none","ID":"a39b0754602d","Image":"alpine:3.22","Labels":"","LocalVolumes":"0","Mounts":"","Names":"ah-t1-exit3","Networks":"bridge","Platform":{"architecture":"amd64","os":"linux"},"Ports":"","RunningFor":"16 seconds ago","Size":"4.1kB (virtual 8.99MB)","State":"exited","Status":"Exited (3) 15 seconds ago"}
`

const dockerInspectFixture = `[
{"Id":"611889c0d0d7e85968cbd9136e6ddf4b6790e04289e0ee340eecad49ded0e4a6","Created":"2026-10-16T17:41:07.856453074Z","Path":"sh","Args":["-c","exit 1"],"State":{"Status":"exited","Running":false,"Paused":false,"Restarting":false,"OOMKilled":false,"Dead":false,"Pid":0,"ExitCode":1,"Error":"","StartedAt":"2026-10-16T17:41:11.314899378Z","FinishedAt":"2026-10-16T17:41:11.584936386Z"},"Image":"sha256:5291449c3df73caf6ed85e649dec1b9e818b39a5d8c871e97afc13e9cd5e8fa8","Name":"/ah-t1-restart3","RestartCount":3,"Driver":"overlayfs","Platform":"linux","ImageManifestDescriptor":{"mediaType":"application/vnd.oci.image.manifest.v1+json","digest":"sha256:3e9b4b680bfc9fb5269227cffbd6d42be39fbf7c0b908123913864aa4447e764","size":1022,"platform":{"architecture":"amd64","os":"linux"}},"ExecIDs":null,"HostConfig":{"NetworkMode":"bridge","RestartPolicy":{"Name":"on-failure","MaximumRetryCount":3},"AutoRemove":false,"Memory":0,"MemorySwap":0,"LogConfig":{"Type":"json-file","Config":{}}},"Config":{"Hostname":"611889c0d0d7","Image":"alpine:3.22","Cmd":["sh","-c","exit 1"],"Labels":{}}},
{"Id":"c1f596e079510de0ea28cdfb62ffddb54c4e3d1fd23422178410763d6034e584","Created":"2026-10-16T17:41:05.445938312Z","Path":"sh","Args":["-c","x=aaaaaaaaaaaaaaaa; while true; do x=$x$x; done"],"State":{"Status":"exited","Running":false,"Paused":false,"Restarting":false,"OOMKilled":true,"Dead":false,"Pid":0,"ExitCode":137,"Error":"","StartedAt":"2026-10-16T17:41:06.069249246Z","FinishedAt":"2026-10-16T17:41:06.334811141Z"},"Image":"sha256:5291449c3df73caf6ed85e649dec1b9e818b39a5d8c871e97afc13e9cd5e8fa8","Name":"/ah-t1-oom","RestartCount":0,"Driver":"overlayfs","Platform":"linux","ImageManifestDescriptor":{"mediaType":"application/vnd.oci.image.manifest.v1+json","digest":"sha256:3e9b4b680bfc9fb5269227cffbd6d42be39fbf7c0b908123913864aa4447e764","size":1022,"platform":{"architecture":"amd64","os":"linux"}},"ExecIDs":null,"HostConfig":{"NetworkMode":"bridge","RestartPolicy":{"Name":"no","MaximumRetryCount":0},"AutoRemove":false,"Memory":8388608,"MemorySwap":8388608,"LogConfig":{"Type":"json-file","Config":{}}},"Config":{"Hostname":"c1f596e07951","Image":"alpine:3.22","Cmd":["sh","-c","x=aaaaaaaaaaaaaaaa; while true; do x=$x$x; done"],"Labels":{}}},
{"Id":"6ae4d13d53eb370cc507102a98da6fea20a04131a33553a58009e6189750ec40","Created":"2026-10-16T17:41:04.587683385Z","Path":"sleep","Args":["600"],"State":{"Status":"running","Running":true,"Paused":false,"Restarting":false,"OOMKilled":false,"Dead":false,"Pid":2188023,"ExitCode":0,"Error":"","StartedAt":"2026-10-16T17:41:04.985345113Z","FinishedAt":"0001-01-01T00:00:00Z","Health":{"Status":"unhealthy","FailingStreak":12,"Log":[{"Start":"2026-10-16T19:41:18.406311395+02:00","End":"2026-10-16T19:41:18.481354759+02:00","ExitCode":1,"Output":""}]}},"Image":"sha256:5291449c3df73caf6ed85e649dec1b9e818b39a5d8c871e97afc13e9cd5e8fa8","Name":"/ah-t1-unhealthy","RestartCount":0,"Driver":"overlayfs","Platform":"linux","ImageManifestDescriptor":{"mediaType":"application/vnd.oci.image.manifest.v1+json","digest":"sha256:3e9b4b680bfc9fb5269227cffbd6d42be39fbf7c0b908123913864aa4447e764","size":1022,"platform":{"architecture":"amd64","os":"linux"}},"ExecIDs":null,"HostConfig":{"NetworkMode":"bridge","RestartPolicy":{"Name":"no","MaximumRetryCount":0},"AutoRemove":false,"Memory":0,"MemorySwap":0,"LogConfig":{"Type":"json-file","Config":{}}},"Config":{"Hostname":"6ae4d13d53eb","Image":"alpine:3.22","Cmd":["sleep","600"],"Healthcheck":{"Test":["CMD-SHELL","false"],"Interval":1000000000,"Retries":1},"Labels":{}}},
{"Id":"a39b0754602d3b2c3c7fc994f26b46e2479db35c2b5bb686025ef37127309e61","Created":"2026-10-16T17:41:02.922375469Z","Path":"sh","Args":["-c","exit 3"],"State":{"Status":"exited","Running":false,"Paused":false,"Restarting":false,"OOMKilled":false,"Dead":false,"Pid":0,"ExitCode":3,"Error":"","StartedAt":"2026-10-16T17:41:03.418916849Z","FinishedAt":"2026-10-16T17:41:03.824467125Z"},"Image":"sha256:5291449c3df73caf6ed85e649dec1b9e818b39a5d8c871e97afc13e9cd5e8fa8","Name":"/ah-t1-exit3","RestartCount":0,"Driver":"overlayfs","Platform":"linux","ImageManifestDescriptor":{"mediaType":"application/vnd.oci.image.manifest.v1+json","digest":"sha256:3e9b4b680bfc9fb5269227cffbd6d42be39fbf7c0b908123913864aa4447e764","size":1022,"platform":{"architecture":"amd64","os":"linux"}},"ExecIDs":null,"HostConfig":{"NetworkMode":"bridge","RestartPolicy":{"Name":"no","MaximumRetryCount":0},"AutoRemove":false,"Memory":0,"MemorySwap":0,"LogConfig":{"Type":"json-file","Config":{}}},"Config":{"Hostname":"a39b0754602d","Image":"alpine:3.22","Cmd":["sh","-c","exit 3"],"Labels":{}}}
]
`

// dockerReply is what the fake docker answers to one subcommand.
type dockerReply struct {
	out string
	err error
}

// stubDocker swaps dockerCLI for a fake docker that is on the PATH and answers each call by its
// subcommand (info, ps, inspect) from replies. It returns the recorded calls; a subcommand without a
// reply fails the test.
func stubDocker(t *testing.T, replies map[string]dockerReply) *[][]string {
	t.Helper()
	old := dockerCLI
	t.Cleanup(func() { dockerCLI = old })
	var calls [][]string
	dockerCLI.lookPath = func(file string) (string, error) { return "/usr/bin/" + file, nil }
	dockerCLI.run = func(_ context.Context, args ...string) ([]byte, error) {
		calls = append(calls, args)
		checkAllowed(t, "docker", args)
		reply, ok := replies[args[0]]
		if !ok {
			t.Errorf("unexpected docker call %v", args)
			return nil, errors.New("unexpected call")
		}
		return []byte(reply.out), reply.err
	}
	return &calls
}

// dockerWire is the docker block as the monitoring service receives it: encoded and decoded again, so
// the tests check the wire format (null vs. [], numbers, booleans), not Go types.
func dockerWire(t *testing.T, block map[string]any) map[string]any {
	t.Helper()
	raw, err := json.Marshal(block)
	if err != nil {
		t.Fatalf("marshal %v: %v", block, err)
	}
	var wire map[string]any
	if err := json.Unmarshal(raw, &wire); err != nil {
		t.Fatalf("unmarshal %s: %v", raw, err)
	}
	return wire
}

func wantDockerWire(t *testing.T, want string) map[string]any {
	t.Helper()
	var wire map[string]any
	if err := json.Unmarshal([]byte(want), &wire); err != nil {
		t.Fatalf("bad want %s: %v", want, err)
	}
	return wire
}

// A fork/exec failure names the binary's path; the report must carry neither it nor stderr.
var errDockerExec = &exec.Error{Name: "/opt/some-path/docker", Err: exec.ErrNotFound}

func assertDockerUnavailable(t *testing.T, wire map[string]any, code string) {
	t.Helper()
	if wire["available"] != false || wire["error"] != code {
		t.Errorf("available/error = %v/%v, want false/%s", wire["available"], wire["error"], code)
	}
	if c, ok := wire["containers"].([]any); !ok || len(c) != 0 {
		t.Errorf("containers = %#v, want an empty list", wire["containers"])
	}
	if msg, _ := wire["error_message"].(string); msg == "" || strings.Contains(msg, "/") {
		t.Errorf("error_message = %q, want a short text without paths", msg)
	}
}

func TestCollectDockerCLIMissing(t *testing.T) {
	calls := stubDocker(t, nil)
	dockerCLI.lookPath = func(string) (string, error) { return "", exec.ErrNotFound }
	if got := collectDocker(context.Background()); got != nil {
		t.Errorf("collectDocker() = %v, want nil (docker not installed is not an outage)", got)
	}
	if len(*calls) != 0 {
		t.Errorf("docker was called without a docker binary: %v", *calls)
	}
}

func TestCollectDockerDaemonUnreachable(t *testing.T) {
	calls := stubDocker(t, map[string]dockerReply{"info": {err: errDockerExec}})
	block := collectDocker(context.Background())
	if block == nil {
		t.Fatal("collectDocker() = nil, want an unavailable block")
	}
	assertDockerUnavailable(t, dockerWire(t, block), "daemon_unreachable")
	if len(*calls) != 1 {
		t.Errorf("calls = %v, want only docker info", *calls)
	}
}

func TestCollectDockerTimeout(t *testing.T) {
	for _, hung := range []string{"info", "ps", "inspect"} {
		t.Run(hung, func(t *testing.T) {
			replies := map[string]dockerReply{
				"info":    {},
				"ps":      {out: dockerPSFixture},
				"inspect": {out: dockerInspectFixture},
			}
			replies[hung] = dockerReply{err: context.DeadlineExceeded}
			stubDocker(t, replies)
			assertDockerUnavailable(t, dockerWire(t, collectDocker(context.Background())), "timeout")
		})
	}
}

// dockerHelperEnv tells TestHelperDockerProcess, run as a child process, how to behave.
const dockerHelperEnv = "AH_DOCKER_HELPER"

// grandchildLifetime bounds the "chatter" grandchild of "orphan". It ends at its first failed write,
// once runTimed has closed the pipe; without a WaitDelay that never happens, and the call lasts this
// long. A grandchild that outlived the test would keep go test from deleting the test binary on Windows.
const grandchildLifetime = 20 * time.Second

// spinCPU is the CPU time the "spin" helper burns before it exits.
const spinCPU = 300 * time.Millisecond

// orphanStarted is what the "orphan" helper prints once its grandchild runs.
const orphanStarted = "grandchild started"

// TestHelperDockerProcess is no test of its own: the runTimed tests start the test binary as their
// child process, which then hangs or fails as dockerHelperEnv says. Without it, it returns at once.
func TestHelperDockerProcess(t *testing.T) {
	switch os.Getenv(dockerHelperEnv) {
	case "hang":
		time.Sleep(time.Minute)
	case "fail":
		os.Exit(3)
	case "spin":
		// A tool that costs CPU time: the self-measurement counts it to the collector that waited for it.
		for processCPUTime() < spinCPU {
		}
	case "orphan":
		// A tool that starts a grandchild with its own stdout (a daemon, a pager) and then hangs.
		grandchild := exec.Command(os.Args[0], "-test.run=^TestHelperDockerProcess$")
		grandchild.Env = append(os.Environ(), dockerHelperEnv+"=chatter")
		grandchild.Stdout = os.Stdout
		if err := grandchild.Start(); err != nil {
			os.Exit(4)
		}
		fmt.Println(orphanStarted)
		time.Sleep(time.Minute)
	case "chatter":
		for end := time.Now().Add(grandchildLifetime); time.Now().Before(end); {
			if _, err := fmt.Println("chatter"); err != nil {
				os.Exit(0)
			}
			time.Sleep(100 * time.Millisecond)
		}
	}
}

// runHelperDocker runs the test binary through runTimed as a child process that behaves as mode says.
func runHelperDocker(t *testing.T, mode string, timeout time.Duration) error {
	t.Helper()
	t.Setenv(dockerHelperEnv, mode)
	_, err := execTimed(context.Background(), timeout, nil, os.Args[0], "-test.run=^TestHelperDockerProcess$")
	return err
}

func TestDockerRunTimedHungCall(t *testing.T) {
	// The stubs above hand collectDocker a context.DeadlineExceeded; this is the proof that runTimed
	// returns it for a real process the timeout killed, which exec reports as "signal: killed".
	start := time.Now()
	err := runHelperDocker(t, "hang", 100*time.Millisecond)
	if !errors.Is(err, context.DeadlineExceeded) {
		t.Fatalf("err = %v, want context.DeadlineExceeded", err)
	}
	if elapsed := time.Since(start); elapsed > 30*time.Second {
		t.Errorf("runTimed returned after %s, the timeout did not stop the hung call", elapsed)
	}
}

func TestRunTimedEndsWhenAGrandchildHoldsStdout(t *testing.T) {
	// The timeout kills the tool, not the grandchild that holds its stdout; without a WaitDelay,
	// Output read the pipe until the grandchild ended (here after grandchildLifetime). The timeout
	// leaves the helper time to start its grandchild; the marker in the output proves it did.
	t.Setenv(dockerHelperEnv, "orphan")
	start := time.Now()
	out, err := execTimed(context.Background(), time.Second, nil, os.Args[0], "-test.run=^TestHelperDockerProcess$")
	elapsed := time.Since(start)
	if !strings.Contains(string(out), orphanStarted) {
		t.Fatalf("output = %q, the grandchild did not start before the timeout", out)
	}
	if !errors.Is(err, context.DeadlineExceeded) {
		t.Errorf("err = %v, want context.DeadlineExceeded", err)
	}
	if elapsed > 10*time.Second {
		t.Errorf("runTimed returned after %s, the grandchild held it past the timeout", elapsed)
	}
}

func TestRunTimedEndsWithTheContext(t *testing.T) {
	// The caller's context ends a call long before its own timeout, and the call says why: Canceled,
	// neither the ExitError of the kill nor a timeout.
	t.Setenv(dockerHelperEnv, "hang")
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	time.AfterFunc(100*time.Millisecond, cancel)
	start := time.Now()
	_, err := execTimed(ctx, time.Minute, nil, os.Args[0], "-test.run=^TestHelperDockerProcess$")
	if !errors.Is(err, context.Canceled) {
		t.Errorf("err = %v, want context.Canceled", err)
	}
	if elapsed := time.Since(start); elapsed > 5*time.Second {
		t.Errorf("runTimed returned after %s, the context did not end the call", elapsed)
	}
}

func TestBuildReportPassesItsContextToThePlugins(t *testing.T) {
	type ctxKey struct{}
	stubReportHost(t)
	got := map[string]context.Context{}
	record := func(name string) func(context.Context) map[string]any {
		return func(ctx context.Context) map[string]any {
			got[name] = ctx
			return nil
		}
	}
	pluginCollectors.docker = record("docker")
	proxmox := record("proxmox")
	pluginCollectors.proxmox = func(ctx context.Context, _ *backupIndexCheck, _ time.Time) (map[string]any, *backupIndexCheck) {
		return proxmox(ctx), nil
	}
	pluginCollectors.zfs = record("zfs")

	ctx := context.WithValue(context.Background(), ctxKey{}, t.Name())
	buildReportWithState(ctx, nil, nil, reportState{}, time.Now())
	for _, name := range []string{"docker", "proxmox", "zfs"} {
		if c := got[name]; c == nil || c.Value(ctxKey{}) != t.Name() {
			t.Errorf("%s collector got context %v, want the report's", name, c)
		}
	}
}

func TestDockerRunTimedFailingCall(t *testing.T) {
	// The counter-check: a call that fails on its own well within the timeout is no timeout.
	err := runHelperDocker(t, "fail", time.Minute)
	var exitErr *exec.ExitError
	if errors.Is(err, context.DeadlineExceeded) || !errors.As(err, &exitErr) || exitErr.ExitCode() != 3 {
		t.Errorf("err = %v, want the ExitError with status 3", err)
	}
}

func TestCollectDockerCLIOrParseFailed(t *testing.T) {
	cases := []struct {
		name    string
		replies map[string]dockerReply
		want    string
	}{
		{"ps fails", map[string]dockerReply{"info": {}, "ps": {err: errDockerExec}}, "cli_failed"},
		{"ps output unreadable", map[string]dockerReply{"info": {}, "ps": {out: "not-json\nalso not"}}, "parse_failed"},
		// What the CLI prints when the daemon goes away between ps and inspect: an empty list, exit 1.
		{"inspect finds nothing", map[string]dockerReply{"info": {}, "ps": {out: dockerPSFixture},
			"inspect": {out: "[]\n", err: errDockerExec}}, "cli_failed"},
		{"inspect output unreadable", map[string]dockerReply{"info": {}, "ps": {out: dockerPSFixture},
			"inspect": {out: "{{.Id}}"}}, "parse_failed"},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			stubDocker(t, c.replies)
			assertDockerUnavailable(t, dockerWire(t, collectDocker(context.Background())), c.want)
		})
	}
}

func TestCollectDockerNoContainers(t *testing.T) {
	calls := stubDocker(t, map[string]dockerReply{"info": {}, "ps": {out: "\n"}})
	got := dockerWire(t, collectDocker(context.Background()))
	want := wantDockerWire(t, `{"available": true, "error": null, "containers": []}`)
	if !reflect.DeepEqual(got, want) {
		t.Errorf("block = %v, want %v", got, want)
	}
	if len(*calls) != 2 {
		t.Errorf("calls = %v, want info and ps only (nothing to inspect)", *calls)
	}
}

func TestCollectDockerInspectFields(t *testing.T) {
	calls := stubDocker(t, map[string]dockerReply{
		"info": {}, "ps": {out: dockerPSFixture}, "inspect": {out: dockerInspectFixture},
	})
	got := dockerWire(t, collectDocker(context.Background()))
	want := wantDockerWire(t, `{"available": true, "error": null, "containers": [
		{"id": "611889c0d0d7", "name": "ah-t1-restart3", "image": "alpine:3.22", "state": "exited",
		 "status": "Exited (1) 7 seconds ago", "restart_policy": "on-failure",
		 "exit_code": 1, "oom_killed": false, "restart_count": 3, "health": "", "started_at": 1792172471},
		{"id": "c1f596e07951", "name": "ah-t1-oom", "image": "alpine:3.22", "state": "exited",
		 "status": "Exited (137) 12 seconds ago", "restart_policy": "no",
		 "exit_code": 137, "oom_killed": true, "restart_count": 0, "health": "", "started_at": 1792172466},
		{"id": "6ae4d13d53eb", "name": "ah-t1-unhealthy", "image": "alpine:3.22", "state": "running",
		 "status": "Up 13 seconds (unhealthy)", "restart_policy": "no",
		 "exit_code": 0, "oom_killed": false, "restart_count": 0, "health": "unhealthy",
		 "started_at": 1792172464},
		{"id": "a39b0754602d", "name": "ah-t1-exit3", "image": "alpine:3.22", "state": "exited",
		 "status": "Exited (3) 15 seconds ago", "restart_policy": "no",
		 "exit_code": 3, "oom_killed": false, "restart_count": 0, "health": "", "started_at": 1792172463}
	]}`)
	if !reflect.DeepEqual(got, want) {
		t.Errorf("block =\n%v\nwant\n%v", got, want)
	}
	// ONE batch inspect for all containers, restricted to containers, with the default JSON output.
	wantInspect := []string{"inspect", "--type", "container",
		"611889c0d0d7", "c1f596e07951", "6ae4d13d53eb", "a39b0754602d"}
	if len(*calls) != 3 || !reflect.DeepEqual((*calls)[2], wantInspect) {
		t.Errorf("calls = %v, want info, ps and %v", *calls, wantInspect)
	}

	t.Run("unknown fields of any type", func(t *testing.T) {
		stubDocker(t, map[string]dockerReply{
			"info": {},
			"ps":   {out: `{"ID":"0123456789ab","Names":"app","Image":"app:1","State":"running","Status":"Up 1 hour"}`},
			"inspect": {out: `[{"Id":"0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
				"FutureObject":{"nested":[1,{"x":null}]},"FutureList":[true,"a",2.5],"RestartCount":2,
				"State":{"Status":"running","ExitCode":0,"OOMKilled":false,"FutureFlag":true,
					"Health":{"Status":"healthy","FailingStreak":0,"FutureHealth":{"a":1}}},
				"HostConfig":{"RestartPolicy":{"Name":"always","MaximumRetryCount":0,"Future":[]},"Future":"x"}}]`},
		})
		got := dockerWire(t, collectDocker(context.Background()))
		want := wantDockerWire(t, `{"available": true, "error": null, "containers": [
			{"id": "0123456789ab", "name": "app", "image": "app:1", "state": "running", "status": "Up 1 hour",
			 "restart_policy": "always", "exit_code": 0, "oom_killed": false, "restart_count": 2,
			 "health": "healthy"}]}`)
		if !reflect.DeepEqual(got, want) {
			t.Errorf("block = %v, want %v", got, want)
		}
	})
}

func TestCollectDockerInspectPartial(t *testing.T) {
	// a39b0754602d vanished between ps and inspect: the CLI prints the other three and exits 1.
	var all []json.RawMessage
	if err := json.Unmarshal([]byte(dockerInspectFixture), &all); err != nil {
		t.Fatalf("fixture: %v", err)
	}
	partial, _ := json.Marshal(all[:3])
	stubDocker(t, map[string]dockerReply{
		"info": {}, "ps": {out: dockerPSFixture}, "inspect": {out: string(partial), err: errDockerExec},
	})
	wire := dockerWire(t, collectDocker(context.Background()))
	if wire["available"] != true || wire["error"] != nil {
		t.Fatalf("available/error = %v/%v, want true/null (a vanished container is no outage)",
			wire["available"], wire["error"])
	}
	var names []any
	for _, c := range wire["containers"].([]any) {
		names = append(names, c.(map[string]any)["name"])
	}
	if !reflect.DeepEqual(names, []any{"ah-t1-restart3", "ah-t1-oom", "ah-t1-unhealthy"}) {
		t.Errorf("containers = %v, want the three inspect still found", names)
	}
}

func TestCollectDockerStateFromInspect(t *testing.T) {
	// ps saw the container running, inspect a moment later sees it exited: state, exit_code and
	// oom_killed come from the same inspect snapshot, so they never contradict each other.
	stubDocker(t, map[string]dockerReply{
		"info": {},
		"ps":   {out: `{"ID":"0123456789ab","Names":"app","Image":"app:1","State":"running","Status":"Up 1 hour"}`},
		"inspect": {out: `[{"Id":"0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef","RestartCount":0,
			"State":{"Status":"exited","ExitCode":2,"OOMKilled":false},"HostConfig":{"RestartPolicy":{"Name":""}}}]`},
	})
	c := dockerWire(t, collectDocker(context.Background()))["containers"].([]any)[0].(map[string]any)
	if c["state"] != "exited" || c["exit_code"] != float64(2) || c["restart_policy"] != "" {
		t.Errorf("container = %v, want state exited, exit_code 2, restart_policy \"\"", c)
	}
}

// Real `docker ps -a --format '{{json .}}'` and `docker inspect --type container` output of Docker 29.9
// (API 1.56) for three throwaway containers: two with compose labels (one publishing 80/tcp on 127.0.0.1
// and ::1 and 53/udp on 127.0.0.1 and exposing 9000/tcp unpublished, one exposing 80/tcp only) and one
// created but never started, without compose labels. The inspect objects are trimmed to a subset of
// their fields.
const dockerComposePSFixture = `{"Command":"\"/docker-entrypoint.…\"","CreatedAt":"2026-11-12 11:56:46 +0100 CET","HealthStatus":"none","ID":"10cc445f4945","Image":"nginx:1.30.6-alpine","Labels":"maintainer=NGINX Docker Maintainers \u003cdocker-maint@nginx.com\u003e","LocalVolumes":"0","Mounts":"","Names":"ah-t3-created","Networks":"bridge","Platform":{"architecture":"amd64","os":"linux"},"Ports":"","RunningFor":"1 second ago","Size":"4.1kB (virtual 66.6MB)","State":"created","Status":"Created"}
{"Command":"\"/docker-entrypoint.…\"","CreatedAt":"2026-11-12 11:56:45 +0100 CET","HealthStatus":"none","ID":"84aeb0e7cb3d","Image":"nginx:1.30.6-alpine","Labels":"com.docker.compose.project=demo,com.docker.compose.service=db,maintainer=NGINX Docker Maintainers \u003cdocker-maint@nginx.com\u003e","LocalVolumes":"0","Mounts":"","Names":"ah-t3-db","Networks":"bridge","Platform":{"architecture":"amd64","os":"linux"},"Ports":"80/tcp","RunningFor":"2 seconds ago","Size":"4.1kB (virtual 66.6MB)","State":"running","Status":"Up Less than a second"}
{"Command":"\"/docker-entrypoint.…\"","CreatedAt":"2026-11-12 11:56:43 +0100 CET","HealthStatus":"none","ID":"9a8eff593ad7","Image":"nginx:1.30.6-alpine","Labels":"com.docker.compose.project=demo,com.docker.compose.service=web,maintainer=NGINX Docker Maintainers \u003cdocker-maint@nginx.com\u003e","LocalVolumes":"0","Mounts":"","Names":"ah-t3-web","Networks":"bridge","Platform":{"architecture":"amd64","os":"linux"},"Ports":"9000/tcp, 127.0.0.1:18053-\u003e53/udp, 127.0.0.1:18080-\u003e80/tcp, [::1]:18080-\u003e80/tcp","RunningFor":"4 seconds ago","Size":"4.1kB (virtual 66.6MB)","State":"running","Status":"Up 2 seconds"}
`

const dockerComposeInspectFixture = `[
{"Id":"10cc445f49455605e254058a1f5b9678e4b9ea657ceb22d428825b52526bfc59","Created":"2026-11-12T10:56:46.543835374Z","Name":"/ah-t3-created","RestartCount":0,"State":{"Status":"created","Running":false,"OOMKilled":false,"Pid":0,"ExitCode":0,"StartedAt":"0001-01-01T00:00:00Z","FinishedAt":"0001-01-01T00:00:00Z"},"HostConfig":{"NetworkMode":"bridge","PortBindings":{},"RestartPolicy":{"Name":"no","MaximumRetryCount":0}},"Config":{"Image":"nginx:1.30.6-alpine","ExposedPorts":{"80/tcp":{}},"Labels":{"maintainer":"NGINX Docker Maintainers <docker-maint@nginx.com>"}},"NetworkSettings":{"Ports":{}}},
{"Id":"84aeb0e7cb3d0e34e3ba54cbfe64d988605e4ad3265b97b7a84231592fa3301e","Created":"2026-11-12T10:56:45.383148Z","Name":"/ah-t3-db","RestartCount":0,"State":{"Status":"running","Running":true,"OOMKilled":false,"Pid":2322333,"ExitCode":0,"StartedAt":"2026-11-12T10:56:46.095428722Z","FinishedAt":"0001-01-01T00:00:00Z"},"HostConfig":{"NetworkMode":"bridge","PortBindings":{},"RestartPolicy":{"Name":"no","MaximumRetryCount":0}},"Config":{"Image":"nginx:1.30.6-alpine","ExposedPorts":{"80/tcp":{}},"Labels":{"com.docker.compose.project":"demo","com.docker.compose.service":"db","maintainer":"NGINX Docker Maintainers <docker-maint@nginx.com>"}},"NetworkSettings":{"Ports":{"80/tcp":null}}},
{"Id":"9a8eff593ad7c9c4238f524fe2c5cb3b8aaeda7e7fd58c69879add19c36542b5","Created":"2026-11-12T10:56:43.931982003Z","Name":"/ah-t3-web","RestartCount":0,"State":{"Status":"running","Running":true,"OOMKilled":false,"Pid":2322199,"ExitCode":0,"StartedAt":"2026-11-12T10:56:44.842674964Z","FinishedAt":"0001-01-01T00:00:00Z"},"HostConfig":{"NetworkMode":"bridge","PortBindings":{"53/udp":[{"HostIp":"127.0.0.1","HostPort":"18053"}],"80/tcp":[{"HostIp":"127.0.0.1","HostPort":"18080"},{"HostIp":"::1","HostPort":"18080"}]},"RestartPolicy":{"Name":"no","MaximumRetryCount":0}},"Config":{"Image":"nginx:1.30.6-alpine","ExposedPorts":{"53/udp":{},"80/tcp":{},"9000/tcp":{}},"Labels":{"com.docker.compose.project":"demo","com.docker.compose.service":"web","maintainer":"NGINX Docker Maintainers <docker-maint@nginx.com>"}},"NetworkSettings":{"Ports":{"53/udp":[{"HostIp":"127.0.0.1","HostPort":"18053"}],"80/tcp":[{"HostIp":"127.0.0.1","HostPort":"18080"},{"HostIp":"::1","HostPort":"18080"}],"9000/tcp":null}}}
]
`

func TestCollectDockerComposeAndPorts(t *testing.T) {
	stubDocker(t, map[string]dockerReply{
		"info": {}, "ps": {out: dockerComposePSFixture}, "inspect": {out: dockerComposeInspectFixture},
	})
	got := dockerWire(t, collectDocker(context.Background()))
	// The ports in the order the CLI's Ports column lists them; a never started container has no
	// started_at, one without compose labels no compose fields, one without published ports no ports.
	want := wantDockerWire(t, `{"available": true, "error": null, "containers": [
		{"id": "10cc445f4945", "name": "ah-t3-created", "image": "nginx:1.30.6-alpine", "state": "created",
		 "status": "Created", "restart_policy": "no", "exit_code": 0, "oom_killed": false,
		 "restart_count": 0, "health": ""},
		{"id": "84aeb0e7cb3d", "name": "ah-t3-db", "image": "nginx:1.30.6-alpine", "state": "running",
		 "status": "Up Less than a second", "restart_policy": "no", "exit_code": 0, "oom_killed": false,
		 "restart_count": 0, "health": "", "compose_project": "demo", "compose_service": "db",
		 "started_at": 1794481006},
		{"id": "9a8eff593ad7", "name": "ah-t3-web", "image": "nginx:1.30.6-alpine", "state": "running",
		 "status": "Up 2 seconds", "restart_policy": "no", "exit_code": 0, "oom_killed": false,
		 "restart_count": 0, "health": "", "compose_project": "demo", "compose_service": "web",
		 "ports": ["127.0.0.1:18053->53/udp", "127.0.0.1:18080->80/tcp", "[::1]:18080->80/tcp"],
		 "started_at": 1794481004}
	]}`)
	if !reflect.DeepEqual(got, want) {
		t.Errorf("block =\n%v\nwant\n%v", got, want)
	}

	t.Run("partial inspect objects", func(t *testing.T) {
		// Labels and the port map null, StartedAt missing or unreadable: each field just stays out.
		stubDocker(t, map[string]dockerReply{
			"info": {},
			"ps": {out: `{"ID":"0123456789ab","Names":"a","Image":"app:1","State":"running","Status":"Up"}
{"ID":"123456789abc","Names":"b","Image":"app:1","State":"running","Status":"Up"}`},
			"inspect": {out: `[
				{"Id":"0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef","State":{"Status":"running"},
				 "Config":{"Labels":null},"NetworkSettings":{"Ports":null}},
				{"Id":"123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef0","State":{"Status":"running",
				 "StartedAt":"yesterday"},"Config":{"Labels":{"com.docker.compose.service":"only-service"}},
				 "NetworkSettings":{}}]`},
		})
		containers := dockerWire(t, collectDocker(context.Background()))["containers"].([]any)
		if len(containers) != 2 {
			t.Fatalf("containers = %v, want 2", containers)
		}
		for _, key := range []string{"compose_project", "ports", "started_at"} {
			for _, c := range containers {
				if v, ok := c.(map[string]any)[key]; ok {
					t.Errorf("%s = %v in %v, want it left out", key, v, c)
				}
			}
		}
		if _, ok := containers[0].(map[string]any)["compose_service"]; ok {
			t.Errorf("container a = %v, want no compose_service", containers[0])
		}
		if s := containers[1].(map[string]any)["compose_service"]; s != "only-service" {
			t.Errorf("compose_service = %v, want only-service (a service label without a project)", s)
		}
	})
}

func TestCollectDockerPublishedPorts(t *testing.T) {
	b := func(ip, port string) dockerPortBinding { return dockerPortBinding{HostIP: ip, HostPort: port} }
	cases := []struct {
		name string
		m    map[string][]dockerPortBinding
		want []string
	}{
		{"nil map", nil, []string{}},
		// `docker run -p 8080:80` binds both wildcards; the CLI writes them 0.0.0.0:8080 and [::]:8080.
		{"IPv4 and IPv6 wildcard",
			map[string][]dockerPortBinding{"80/tcp": {b("0.0.0.0", "8080"), b("::", "8080")}},
			[]string{"0.0.0.0:8080->80/tcp", "[::]:8080->80/tcp"}},
		{"binding without address", map[string][]dockerPortBinding{"80/tcp": {b("", "8080")}},
			[]string{"8080->80/tcp"}},
		{"sctp", map[string][]dockerPortBinding{"9/sctp": {b("192.0.2.1", "9")}}, []string{"192.0.2.1:9->9/sctp"}},
		{"duplicate binding once", map[string][]dockerPortBinding{"80/tcp": {b("::", "80"), b("::", "80")}},
			[]string{"[::]:80->80/tcp"}},
		{"leading zeros normalized", map[string][]dockerPortBinding{"080/tcp": {b("::", "080"), b("", "0443")}},
			[]string{"443->80/tcp", "[::]:80->80/tcp"}},
		{"unreadable bindings left out", map[string][]dockerPortBinding{"80/tcp": {
			b("::", ""), b("::", "0"), b("::", "65536"), b("::", "8080-8090"), b("not-an-ip", "1"),
			b("192.0.2.1:1", "1")}}, []string{}},
		{"unreadable keys left out", map[string][]dockerPortBinding{
			"80": {b("::", "80")}, "80/http": {b("::", "80")}, "x/tcp": {b("::", "80")},
			"0/tcp": {b("::", "80")}, "80/tcp/x": {b("::", "80")}}, []string{}},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			got := publishedPorts(c.m)
			if len(got) == 0 && len(c.want) == 0 {
				return
			}
			if !reflect.DeepEqual(got, c.want) {
				t.Errorf("publishedPorts = %q, want %q", got, c.want)
			}
		})
	}

	t.Run("capped", func(t *testing.T) {
		m := map[string][]dockerPortBinding{}
		for port := 10000; port < 10000+maxDockerPorts+6; port++ {
			m[fmt.Sprintf("%d/tcp", port)] = []dockerPortBinding{b("192.0.2.1", fmt.Sprint(port))}
		}
		got := publishedPorts(m)
		if len(got) != maxDockerPorts || got[0] != "192.0.2.1:10000->10000/tcp" ||
			got[maxDockerPorts-1] != fmt.Sprintf("192.0.2.1:%d->%d/tcp", 10000+maxDockerPorts-1, 10000+maxDockerPorts-1) {
			t.Errorf("publishedPorts = %d ports from %q to %q, want the first %d in order",
				len(got), got[0], got[len(got)-1], maxDockerPorts)
		}
	})
}

func TestCollectDockerComposeLabel(t *testing.T) {
	const key = "com.docker.compose.project"
	long := strings.Repeat("ä", maxComposeLabel)
	cases := []struct {
		name, label, want string
	}{
		{"plain", "mailcow", "mailcow"},
		{"at the limit in characters, not bytes", long, long},
		{"over the limit is dropped, not cut", long + "x", ""},
		{"control character", "demo\nother", ""},
		{"DEL", "demo\x7f", ""},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			if got := composeLabel(map[string]string{key: c.label}, key); got != c.want {
				t.Errorf("composeLabel(%q) = %q, want %q", c.label, got, c.want)
			}
		})
	}
	if got := composeLabel(nil, key); got != "" {
		t.Errorf("composeLabel(nil) = %q, want \"\"", got)
	}
}

func TestParseZpoolList(t *testing.T) {
	out := []byte("tank\t3.62T\t1.2T\t2.4T\t33%\tONLINE\t12%\nbackup\t1T\t900G\t100G\t90%\tDEGRADED\t-")
	pools := parseZpoolList(out)
	if len(pools) != 2 {
		t.Fatalf("want 2 pools, got %d: %v", len(pools), pools)
	}
	if pools[0]["name"] != "tank" || pools[0]["capacity_percent"] != 33 || pools[0]["health"] != "ONLINE" ||
		pools[0]["fragmentation_percent"] != 12 {
		t.Errorf("tank: %v", pools[0])
	}
	if pools[1]["capacity_percent"] != 90 || pools[1]["health"] != "DEGRADED" {
		t.Errorf("backup: %v", pools[1])
	}
	if frag, ok := pools[1]["fragmentation_percent"]; ok {
		t.Errorf("backup: fragmentation_percent = %v, want none for \"-\" (unknown)", frag)
	}
	if short := parseZpoolList([]byte("tank\t3.62T")); len(short) != 0 {
		t.Errorf("line with too few columns should be skipped: %v", short)
	}

	// The fragmentation column is read only as zpool prints a percentage, 0 to 100; anything else
	// leaves the key out and the pool as before.
	for frag, want := range map[string]any{
		"0%": 0, "100%": 100, "7%": 7,
		"-": nil, "": nil, "12": nil, "abc%": nil, "101%": nil, "-1%": nil, "1.5%": nil, "%": nil,
	} {
		pools := parseZpoolList([]byte("tank\t3.62T\t1.2T\t2.4T\t33%\tONLINE\t" + frag))
		if len(pools) != 1 {
			t.Fatalf("frag %q: want 1 pool, got %v", frag, pools)
		}
		got, ok := pools[0]["fragmentation_percent"]
		if (want == nil && ok) || (want != nil && got != want) {
			t.Errorf("frag %q: fragmentation_percent = %v (present %v), want %v", frag, got, ok, want)
		}
		if pools[0]["health"] != "ONLINE" || pools[0]["capacity_percent"] != 33 {
			t.Errorf("frag %q: pool = %v, want the other columns unchanged", frag, pools[0])
		}
	}
	if pools := parseZpoolList([]byte("tank\t3.62T\t1.2T\t2.4T\t33%\tONLINE")); len(pools) != 1 ||
		pools[0]["fragmentation_percent"] != nil {
		t.Errorf("six columns: %v, want one pool without fragmentation_percent", pools)
	}
}

// stubZpool swaps zpoolCLI for a fake zpool that is on the PATH and answers each call by its
// subcommand (list, status; "status -j" for the pool details) from replies, like stubDocker. It
// returns the recorded calls; a subcommand without a reply fails the test.
func stubZpool(t *testing.T, replies map[string]dockerReply) *[][]string {
	t.Helper()
	old := zpoolCLI
	t.Cleanup(func() { zpoolCLI = old })
	var calls [][]string
	zpoolCLI.lookPath = func(file string) (string, error) { return "/usr/sbin/" + file, nil }
	zpoolCLI.run = func(_ context.Context, args ...string) ([]byte, error) {
		calls = append(calls, args)
		checkAllowed(t, "zpool", args)
		key := args[0]
		if len(args) > 1 && args[1] == "-j" {
			key += " -j"
		}
		reply, ok := replies[key]
		if !ok {
			t.Errorf("unexpected zpool call %v", args)
			return nil, errors.New("unexpected call")
		}
		return []byte(reply.out), reply.err
	}
	return &calls
}

var (
	zpoolListArgs   = []string{"list", "-H", "-o", "name,size,alloc,free,cap,health,frag"}
	zpoolStatusArgs = []string{"status", "-j", "--json-int", "--json-flat-vdevs"}
)

func assertZFSUnavailable(t *testing.T, wire map[string]any, code string) {
	t.Helper()
	if wire["available"] != false || wire["error"] != code {
		t.Errorf("available/error = %v/%v, want false/%s", wire["available"], wire["error"], code)
	}
	if p, ok := wire["pools"].([]any); !ok || len(p) != 0 {
		t.Errorf("pools = %#v, want an empty list", wire["pools"])
	}
	if msg, _ := wire["error_message"].(string); msg == "" || strings.Contains(msg, "/") {
		t.Errorf("error_message = %q, want a short text without paths", msg)
	}
}

func TestCollectZFSCLIMissing(t *testing.T) {
	calls := stubZpool(t, nil)
	zpoolCLI.lookPath = func(string) (string, error) { return "", exec.ErrNotFound }
	if got := collectZFS(context.Background()); got != nil {
		t.Errorf("collectZFS() = %v, want nil (zpool not installed is not an outage)", got)
	}
	if len(*calls) != 0 {
		t.Errorf("zpool was called without a zpool binary: %v", *calls)
	}
}

func TestCollectZFSListFailed(t *testing.T) {
	calls := stubZpool(t, map[string]dockerReply{
		"list": {err: &exec.Error{Name: "/opt/some-path/zpool", Err: exec.ErrNotFound}},
	})
	block := collectZFS(context.Background())
	if block == nil {
		t.Fatal("collectZFS() = nil, want an unavailable block")
	}
	assertZFSUnavailable(t, dockerWire(t, block), "cli_failed")
	if len(*calls) != 1 {
		t.Errorf("calls = %v, want only zpool list", *calls)
	}
}

func TestCollectZFSTimeout(t *testing.T) {
	stubZpool(t, map[string]dockerReply{"list": {err: context.DeadlineExceeded}})
	wire := dockerWire(t, collectZFS(context.Background()))
	assertZFSUnavailable(t, wire, "timeout")
	if msg, _ := wire["error_message"].(string); !strings.Contains(msg, "timed out") {
		t.Errorf("error_message = %q, want it to say the call timed out", msg)
	}
}

func TestCollectZFSRealZpoolCall(t *testing.T) {
	// The stubs above hand collectZFS a ready error; here a real child process goes through runTimed,
	// the runner runZpool uses, with only the binary and the timeout swapped: a hung zpool the timeout
	// killed (exec: "signal: killed") must be timeout, one that fails on its own cli_failed.
	stubZpool(t, nil)
	zpoolCLI.run = func(context.Context, ...string) ([]byte, error) {
		return nil, runHelperDocker(t, "hang", 100*time.Millisecond)
	}
	assertZFSUnavailable(t, dockerWire(t, collectZFS(context.Background())), "timeout")

	zpoolCLI.run = func(context.Context, ...string) ([]byte, error) { return nil, runHelperDocker(t, "fail", time.Minute) }
	wire := dockerWire(t, collectZFS(context.Background()))
	assertZFSUnavailable(t, wire, "cli_failed")
	if wire["error_message"] != "zpool list failed: exit status 3" {
		t.Errorf("error_message = %q, want the exit status", wire["error_message"])
	}
}

func TestCollectZFSNoPools(t *testing.T) {
	calls := stubZpool(t, map[string]dockerReply{"list": {out: ""}})
	got := dockerWire(t, collectZFS(context.Background()))
	want := wantDockerWire(t, `{"available": true, "error": null, "pools": []}`)
	if !reflect.DeepEqual(got, want) {
		t.Errorf("block = %v, want %v", got, want)
	}
	if !reflect.DeepEqual(*calls, [][]string{zpoolListArgs}) {
		t.Errorf("calls = %v, want only %v", *calls, zpoolListArgs)
	}
}

func TestCollectZFSPools(t *testing.T) {
	const list = "tank\t3.62T\t1.2T\t2.4T\t33%\tONLINE\t4%\nbackup\t1T\t900G\t100G\t90%\tDEGRADED\t-\n"
	const status = "  pool: backup\n state: DEGRADED\n"
	const details = `{"output_version": {"command": "zpool status", "vers_major": 0, "vers_minor": 1},
		"pools": {
		"tank": {"name": "tank", "state": "ONLINE", "error_count": 0, "vdevs": {
			"tank": {"name": "tank", "vdev_type": "root", "read_errors": 0, "write_errors": 0, "checksum_errors": 0}}},
		"backup": {"name": "backup", "state": "DEGRADED",
			"scan_stats": {"function": "SCRUB", "state": "FINISHED", "start_time": 1794480000,
				"end_time": 1794483164, "errors": 2, "scrub_pause": 0},
			"vdevs": {
			"backup": {"name": "backup", "vdev_type": "root", "read_errors": 0, "write_errors": 0, "checksum_errors": 0},
			"ada1": {"name": "ada1", "vdev_type": "disk", "read_errors": 3, "write_errors": 0, "checksum_errors": 7}}}}}`
	calls := stubZpool(t, map[string]dockerReply{
		"list": {out: list}, "status": {out: status}, "status -j": {out: details},
	})
	got := dockerWire(t, collectZFS(context.Background()))
	want := wantDockerWire(t, `{"available": true, "error": null, "pools": [
		{"name": "tank", "size": "3.62T", "allocated": "1.2T", "free": "2.4T", "capacity_percent": 33,
		 "health": "ONLINE", "fragmentation_percent": 4},
		{"name": "backup", "size": "1T", "allocated": "900G", "free": "100G", "capacity_percent": 90,
		 "health": "DEGRADED", "scrub": {"state": "FINISHED", "errors": 2, "end": 1794483164},
		 "vdev_errors": [{"name": "ada1", "read": 3, "write": 0, "checksum": 7}]}
	], "errors": "pool: backup\n state: DEGRADED"}`)
	if !reflect.DeepEqual(got, want) {
		t.Errorf("block =\n%v\nwant\n%v", got, want)
	}
	if !reflect.DeepEqual(*calls, [][]string{zpoolListArgs, {"status", "-x"}, zpoolStatusArgs}) {
		t.Errorf("calls = %v, want zpool list, zpool status -x and zpool status -j", *calls)
	}

	t.Run("all online", func(t *testing.T) {
		calls := stubZpool(t, map[string]dockerReply{
			"list": {out: "tank\t3.62T\t1.2T\t2.4T\t33%\tONLINE\t4%\n"}, "status -j": {out: details},
		})
		got := dockerWire(t, collectZFS(context.Background()))
		if got["available"] != true || got["error"] != nil || len(got["pools"].([]any)) != 1 {
			t.Errorf("block = %v, want one available pool", got)
		}
		if _, ok := got["errors"]; ok || !reflect.DeepEqual(*calls, [][]string{zpoolListArgs, zpoolStatusArgs}) {
			t.Errorf("errors = %v, calls = %v, want no errors and no zpool status -x", got["errors"], *calls)
		}
	})

	t.Run("status fails", func(t *testing.T) {
		// As before: without zpool status the pools still go out, only the error details and the pool
		// details are missing.
		stubZpool(t, map[string]dockerReply{
			"list": {out: list}, "status": {err: context.DeadlineExceeded}, "status -j": {err: context.DeadlineExceeded},
		})
		got := dockerWire(t, collectZFS(context.Background()))
		want := wantDockerWire(t, `{"available": true, "error": null, "pools": [
			{"name": "tank", "size": "3.62T", "allocated": "1.2T", "free": "2.4T", "capacity_percent": 33,
			 "health": "ONLINE", "fragmentation_percent": 4},
			{"name": "backup", "size": "1T", "allocated": "900G", "free": "100G", "capacity_percent": 90,
			 "health": "DEGRADED"}
		]}`)
		if !reflect.DeepEqual(got, want) {
			t.Errorf("block =\n%v\nwant\n%v", got, want)
		}
	})
}

// TestCollectZFSDetails drives collectZFS with the output of a real zpool status -j (OpenZFS 2.4.2 on
// FreeBSD 15.1: a file-backed mirror with a log vdev, one side overwritten, then scrubbed) and with
// the ways the call fails on a zpool that cannot give it: the pools go out as zpool list has them.
func TestCollectZFSDetails(t *testing.T) {
	fixture, err := os.ReadFile("testdata/zpool-status-scrub.json")
	if err != nil {
		t.Fatal(err)
	}
	const list = "probe\t240M\t64.3M\t176M\t26%\tONLINE\t15%\n"
	plain := wantDockerWire(t, `{"available": true, "error": null, "pools": [
		{"name": "probe", "size": "240M", "allocated": "64.3M", "free": "176M", "capacity_percent": 26,
		 "health": "ONLINE", "fragmentation_percent": 15}]}`)

	calls := stubZpool(t, map[string]dockerReply{"list": {out: list}, "status -j": {out: string(fixture)}})
	got := dockerWire(t, collectZFS(context.Background()))
	want := wantDockerWire(t, `{"available": true, "error": null, "pools": [
		{"name": "probe", "size": "240M", "allocated": "64.3M", "free": "176M", "capacity_percent": 26,
		 "health": "ONLINE", "fragmentation_percent": 15,
		 "scrub": {"state": "FINISHED", "errors": 0, "end": 1794483164},
		 "vdev_errors": [{"name": "/var/tmp/ahprobe/a", "read": 0, "write": 0, "checksum": 380}]}]}`)
	if !reflect.DeepEqual(got, want) {
		t.Errorf("block =\n%v\nwant\n%v", got, want)
	}
	if !reflect.DeepEqual(*calls, [][]string{zpoolListArgs, zpoolStatusArgs}) {
		t.Errorf("calls = %v, want zpool list and zpool status -j", *calls)
	}

	for name, reply := range map[string]dockerReply{
		// OpenZFS 2.2 and older: zpool knows no -j and exits with its usage (status 2).
		"old zpool":  {out: "invalid option 'j'\nusage:\n", err: errors.New("exit status 2")},
		"timeout":    {err: context.DeadlineExceeded},
		"garbage":    {out: "  pool: probe\n state: ONLINE\n"},
		"other pool": {out: `{"pools": {"tank": {"scan_stats": {"function": "SCRUB", "state": "FINISHED", "end_time": 1, "errors": 0}}}}`},
		// A call that fails gives no details, even where it printed some: they may be of only some pools.
		"fails with output": {out: string(fixture), err: errors.New("exit status 1")},
	} {
		t.Run(name, func(t *testing.T) {
			stubZpool(t, map[string]dockerReply{"list": {out: list}, "status -j": reply})
			if got := dockerWire(t, collectZFS(context.Background())); !reflect.DeepEqual(got, plain) {
				t.Errorf("block =\n%v\nwant\n%v", got, plain)
			}
		})
	}
}

// zpoolStatusWire is parseZpoolStatus(out) as JSON reads it back, nil for no details at all.
func zpoolStatusWire(t *testing.T, out string) any {
	t.Helper()
	raw, err := json.Marshal(parseZpoolStatus([]byte(out)))
	if err != nil {
		t.Fatalf("marshal: %v", err)
	}
	var wire any
	if err := json.Unmarshal(raw, &wire); err != nil {
		t.Fatalf("unmarshal %s: %v", raw, err)
	}
	return wire
}

// zpoolScan is a zpool status -j of one pool "p" with the scan stats scan and no vdev errors.
func zpoolScan(scan string) string {
	return `{"pools": {"p": {"name": "p", "scan_stats": ` + scan + `, "vdevs": {
		"p": {"name": "p", "read_errors": 0, "write_errors": 0, "checksum_errors": 0}}}}}`
}

func TestCollectZFSParseStatus(t *testing.T) {
	// The states and times of the paused and the canceled scrub are those OpenZFS 2.4.2 wrote for
	// `zpool scrub -p` and `zpool scrub -s` on the probe pool of the fixture.
	cases := []struct {
		name, out, want string
	}{
		{"finished", zpoolScan(`{"function": "SCRUB", "state": "FINISHED", "end_time": 1794483164, "errors": 3, "scrub_pause": 0}`),
			`{"p": {"scrub": {"state": "FINISHED", "errors": 3, "end": 1794483164}}}`},
		{"running", zpoolScan(`{"function": "SCRUB", "state": "SCANNING", "end_time": 0, "errors": 0, "scrub_pause": 0}`),
			`{"p": {"scrub": {"state": "SCANNING", "errors": 0}}}`},
		{"running with a stale end", zpoolScan(`{"function": "SCRUB", "state": "SCANNING", "end_time": 1794483164, "errors": 0}`),
			`{"p": {"scrub": {"state": "SCANNING", "errors": 0}}}`},
		{"paused", zpoolScan(`{"function": "SCRUB", "state": "SCANNING", "start_time": 1794483226, "end_time": 0, "errors": 0, "scrub_pause": 1794483226}`),
			`{"p": {"scrub": {"state": "PAUSED", "errors": 0}}}`},
		{"canceled", zpoolScan(`{"function": "SCRUB", "state": "CANCELED", "start_time": 1794483226, "end_time": 1794483226, "errors": 0, "scrub_pause": 1794483226}`),
			`{"p": {"scrub": {"state": "CANCELED", "errors": 0, "end": 1794483226}}}`},
		{"finished without an end", zpoolScan(`{"function": "SCRUB", "state": "FINISHED", "end_time": 0, "errors": 0}`),
			`{"p": {"scrub": {"state": "FINISHED", "errors": 0}}}`},
		// The pool keeps only its last scan: after a resilver or an error scrub there is no scrub to name.
		{"resilver", zpoolScan(`{"function": "RESILVER", "state": "FINISHED", "end_time": 1794483164, "errors": 0}`), `{}`},
		{"error scrub", zpoolScan(`{"function": "ERRORSCRUB", "state": "FINISHED", "end_time": 1794483164, "errors": 0}`), `{}`},
		{"no scan", zpoolScan(`{"function": "NONE", "state": "NONE", "end_time": 0, "errors": 0}`), `{}`},
		{"unknown state", zpoolScan(`{"function": "SCRUB", "state": "ERRORSCRUBBING", "end_time": 1, "errors": 0}`), `{}`},
		{"vdev errors", `{"pools": {"p": {"vdevs": {
			"p": {"name": "p", "read_errors": 1, "write_errors": 0, "checksum_errors": 0},
			"mirror-0": {"name": "mirror-0", "read_errors": 0, "write_errors": 0, "checksum_errors": 0},
			"da1": {"name": "da1", "read_errors": 0, "write_errors": 2, "checksum_errors": 0},
			"bad": {"name": "da\u0007x", "read_errors": 0, "write_errors": 0, "checksum_errors": 9},
			"spare": {"name": "da9"}}}}}`,
			`{"p": {"vdev_errors": [
				{"name": "", "read": 0, "write": 0, "checksum": 9},
				{"name": "da1", "read": 0, "write": 2, "checksum": 0},
				{"name": "p", "read": 1, "write": 0, "checksum": 0}]}}`},
		{"no pools", `{"pools": {}}`, `{}`},
		// Counts as strings are zpool status -j without --json-int: not what was asked for, so nothing.
		{"counts as strings", `{"pools": {"p": {"vdevs": {"p": {"name": "p", "read_errors": "1", "write_errors": "0", "checksum_errors": "0"}}}}}`, `null`},
		{"broken", `{"pools": {"p": `, `null`},
		{"empty", ``, `null`},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			var want any
			if err := json.Unmarshal([]byte(c.want), &want); err != nil {
				t.Fatalf("bad want %s: %v", c.want, err)
			}
			if got := zpoolStatusWire(t, c.out); !reflect.DeepEqual(got, want) {
				t.Errorf("details = %v, want %v", got, want)
			}
		})
	}

	t.Run("capped and sorted", func(t *testing.T) {
		vdevs := []string{}
		for i := 40; i > 0; i-- {
			name := fmt.Sprintf("da%02d", i)
			vdevs = append(vdevs, fmt.Sprintf(`%q: {"name": %q, "read_errors": 0, "write_errors": 0, "checksum_errors": %d}`, name, name, i))
		}
		got := parseZpoolStatus([]byte(`{"pools": {"p": {"vdevs": {` + strings.Join(vdevs, ",") + `}}}}`))
		errs, _ := got["p"]["vdev_errors"].([]map[string]any)
		if len(errs) != maxZpoolVdevErrors {
			t.Fatalf("vdev_errors = %d entries, want %d", len(errs), maxZpoolVdevErrors)
		}
		for i, e := range errs {
			if want := fmt.Sprintf("da%02d", i+1); e["name"] != want {
				t.Errorf("vdev_errors[%d] = %v, want %s (sorted by name, the first %d kept)", i, e["name"], want, maxZpoolVdevErrors)
			}
		}
	})
}

// stubPvesh swaps pveshCLI for a fake pvesh that is on the PATH and answers each `pvesh get` by its
// API path from replies, like stubZpool; a call with --type is answered by "<path>?type=<type>"
// (pveshVMs, pveshStorages). A path without a reply fails the test. It returns the recorded calls.
func stubPvesh(t *testing.T, replies map[string]dockerReply) *[][]string {
	t.Helper()
	old := pveshCLI
	t.Cleanup(func() { pveshCLI = old })
	var calls [][]string
	pveshCLI.lookPath = func(file string) (string, error) { return "/usr/bin/" + file, nil }
	pveshCLI.run = func(_ context.Context, args ...string) ([]byte, error) {
		calls = append(calls, args)
		checkAllowed(t, "pvesh", args)
		var reply dockerReply
		ok := len(args) > 1 && args[0] == "get"
		if ok {
			key := args[1]
			if len(args) > 3 && args[2] == "--type" {
				key += "?type=" + args[3]
			}
			reply, ok = replies[key]
		}
		if !ok {
			t.Errorf("unexpected pvesh call %v", args)
			return nil, errors.New("unexpected call")
		}
		return []byte(reply.out), reply.err
	}
	return &calls
}

// pveshNode is the API path of the local node, below which collectProxmox asks for its status and
// its backup storages.
func pveshNode(t *testing.T) string {
	t.Helper()
	host, err := os.Hostname()
	if err != nil {
		t.Fatalf("hostname: %v", err)
	}
	node, _, _ := strings.Cut(host, ".")
	return "/nodes/" + node
}

// pveshNodeStatus is the API path collectProxmox asks for the local node's status.
func pveshNodeStatus(t *testing.T) string {
	t.Helper()
	return pveshNode(t) + "/status"
}

// The keys stubPvesh answers `pvesh get /cluster/resources --type vm|storage` by, and the API path of
// the backup jobs.
const (
	pveshVMs      = "/cluster/resources?type=vm"
	pveshStorages = "/cluster/resources?type=storage"
	pveshJobs     = "/cluster/backup"
)

// pveshBackupContent is the API path collectProxmox asks for the backups on one storage.
func pveshBackupContent(t *testing.T, storage string) string {
	t.Helper()
	return pveshNode(t) + "/storage/" + storage + "/content"
}

// pveshTasks is the API path collectProxmox asks for the last failed vzdump task of the local node.
func pveshTasks(t *testing.T) string {
	t.Helper()
	return pveshNode(t) + "/tasks"
}

// pveshTaskLog is the API path of the log of the task upid on the local node.
func pveshTaskLog(t *testing.T, upid string) string {
	t.Helper()
	return pveshNode(t) + "/tasks/" + upid + "/log"
}

// noBackupDetails are the replies of the backup details' calls without jobs and without a failed task.
func noBackupDetails(t *testing.T) map[string]dockerReply {
	t.Helper()
	return map[string]dockerReply{pveshJobs: {out: "[]"}, pveshTasks(t): {out: "[]"}}
}

// withReplies is replies with more added.
func withReplies(replies map[string]dockerReply, more map[string]dockerReply) map[string]dockerReply {
	out := make(map[string]dockerReply, len(replies)+len(more))
	maps.Copy(out, replies)
	maps.Copy(out, more)
	return out
}

// captureWarnings routes the package logger into a buffer for the duration of the test.
func captureWarnings(t *testing.T) *bytes.Buffer {
	t.Helper()
	var buf bytes.Buffer
	prev := slog.Default()
	slog.SetDefault(slog.New(slog.NewTextHandler(&buf, &slog.HandlerOptions{Level: slog.LevelWarn})))
	t.Cleanup(func() { slog.SetDefault(prev) })
	return &buf
}

const pveshNodeStatusFixture = `{"cpu":0.05,"memory":{"total":1000,"used":250}}`

// A fork/exec failure names pvesh's path; the report must carry neither it nor stderr.
var errPveshExec = &exec.Error{Name: "/opt/some-path/pvesh", Err: exec.ErrNotFound}

// assertProxmoxUnavailable checks that block is the outage block with code and text as it goes on the
// wire, and that the log (diagnose) names both.
func assertProxmoxUnavailable(t *testing.T, block map[string]any, logs *bytes.Buffer, code, text string) {
	t.Helper()
	got := dockerWire(t, block)
	want := map[string]any{"available": false, "error": code, "error_message": text, "node": nil, "vms": []any{}}
	if !reflect.DeepEqual(got, want) {
		t.Errorf("block =\n%v\nwant\n%v", got, want)
	}
	if line := text + ", proxmox reported as unavailable (" + code + ")"; !strings.Contains(logs.String(), line) {
		t.Errorf("log = %q, want it to name %q", logs.String(), line)
	}
}

func TestCollectProxmoxCLIMissing(t *testing.T) {
	calls := stubPvesh(t, nil)
	pveshCLI.lookPath = func(string) (string, error) { return "", exec.ErrNotFound }
	saved := &backupIndexCheck{Node: "pve", Index: map[int]int64{}}
	if got, check := collectProxmox(context.Background(), saved, time.Now()); got != nil || check != nil {
		t.Errorf("collectProxmox() = %v, %v, want nil, nil (pvesh not installed is not an outage, "+
			"and a Proxmox gone keeps no index)", got, check)
	}
	if len(*calls) != 0 {
		t.Errorf("pvesh was called without a pvesh binary: %v", *calls)
	}
}

func TestCollectProxmoxHostnameUnreadable(t *testing.T) {
	// Without the hostname there is no node to ask: an outage, without the error text (it can name a
	// path) and without a pvesh call.
	calls := stubPvesh(t, nil)
	pveshCLI.hostname = func() (string, error) {
		return "", &os.PathError{Op: "open", Path: "/proc/sys/kernel/hostname", Err: os.ErrPermission}
	}
	logs := captureWarnings(t)
	assertProxmoxUnavailable(t, proxmoxBlock(t), logs, "cli_failed", "local hostname unreadable")
	if len(*calls) != 0 {
		t.Errorf("pvesh was called without a node name: %v", *calls)
	}
}

func TestCollectProxmoxNodeStatusFails(t *testing.T) {
	// A node status that failed, hung or printed no JSON object is an outage, no longer a block
	// without the node; nothing after it is asked.
	status := "pvesh get " + pveshNodeStatus(t)
	for name, tc := range map[string]struct {
		reply      dockerReply
		code, text string
	}{
		"fails": {dockerReply{err: runHelperDocker(t, "fail", time.Minute)}, "cli_failed",
			status + " failed: exit status 3"},
		"does not start": {dockerReply{err: errPveshExec}, "cli_failed", status + " failed: pvesh did not start"},
		"times out":      {dockerReply{err: context.DeadlineExceeded}, "timeout", status + " timed out after 15s"},
		"not json":       {dockerReply{out: "not json"}, "parse_failed", status + " output unreadable"},
		"null":           {dockerReply{out: "null\n"}, "parse_failed", status + " output unreadable"},
		"no object":      {dockerReply{out: "[]"}, "parse_failed", status + " output unreadable"},
	} {
		t.Run(name, func(t *testing.T) {
			calls := stubPvesh(t, map[string]dockerReply{pveshNodeStatus(t): tc.reply})
			logs := captureWarnings(t)
			assertProxmoxUnavailable(t, proxmoxBlock(t), logs, tc.code, tc.text)
			if len(*calls) != 1 {
				t.Errorf("calls = %v, want only the node status", *calls)
			}
		})
	}
}

func TestCollectProxmoxVMCallFails(t *testing.T) {
	// A VM call that failed, hung or printed no JSON array is no "no VMs": a block with the node alone
	// reads on the server as "No VMs/CTs found" = ok. It is an outage instead, and the log (diagnose)
	// names the reason, short and without stderr.
	for name, tc := range map[string]struct {
		reply      dockerReply
		code, text string
	}{
		"fails": {dockerReply{err: runHelperDocker(t, "fail", time.Minute)}, "cli_failed",
			"pvesh get /cluster/resources failed: exit status 3"},
		"does not start": {dockerReply{err: errPveshExec}, "cli_failed",
			"pvesh get /cluster/resources failed: pvesh did not start"},
		"times out": {dockerReply{err: context.DeadlineExceeded}, "timeout",
			"pvesh get /cluster/resources timed out after 15s"},
		"not json": {dockerReply{out: "not json"}, "parse_failed", "pvesh get /cluster/resources output unreadable"},
		"null":     {dockerReply{out: "null"}, "parse_failed", "pvesh get /cluster/resources output unreadable"},
	} {
		t.Run(name, func(t *testing.T) {
			stubPvesh(t, withReplies(noBackupDetails(t), map[string]dockerReply{
				pveshNodeStatus(t): {out: pveshNodeStatusFixture},
				pveshStorages:      {out: "[]"},
				pveshVMs:           tc.reply,
			}))
			logs := captureWarnings(t)
			assertProxmoxUnavailable(t, proxmoxBlock(t), logs, tc.code, tc.text)
		})
	}
}

func TestCollectProxmoxNoVMs(t *testing.T) {
	// The counter-check: an empty list is a node without VMs, and the block goes out available with
	// the node and an empty list, never null.
	stubPvesh(t, withReplies(noBackupDetails(t), map[string]dockerReply{
		pveshNodeStatus(t): {out: pveshNodeStatusFixture},
		pveshStorages:      {out: "[]"},
		pveshVMs:           {out: "[]"},
	}))
	got := dockerWire(t, proxmoxBlock(t))
	want := wantDockerWire(t, `{"available": true, "error": null, "vms": [],
		"node": {"name": "`+strings.TrimPrefix(pveshNode(t), "/nodes/")+`", "cpu": 5, "memory_percent": 25}}`)
	if !reflect.DeepEqual(got, want) {
		t.Errorf("block =\n%v\nwant\n%v", got, want)
	}
}

// Two running guests as `pvesh get /cluster/resources --type vm` lists them.
const pveshVMsFixture = `[{"id":"qemu/100","type":"qemu","vmid":100,"name":"web","status":"running","node":"pve"},
{"id":"lxc/101","type":"lxc","vmid":101,"name":"dns","status":"running","node":"pve"}]`

// pveshStorage is one entry of `pvesh get /cluster/resources --type storage` on the local node, with
// the given status; an empty status leaves the field out.
func pveshStorage(t *testing.T, id, status string) string {
	t.Helper()
	return pveshStorageOn(t, strings.TrimPrefix(pveshNode(t), "/nodes/"), id, "backup,iso", status)
}

// pveshStorageOn is such an entry of any node, with the given content list.
func pveshStorageOn(t *testing.T, node, id, content, status string) string {
	t.Helper()
	entry := fmt.Sprintf(`{"id":"storage/%s/%s","type":"storage","storage":"%s","node":"%s","content":"%s",`+
		`"plugintype":"nfs","shared":0,"disk":1,"maxdisk":2`, node, id, id, node, content)
	if status != "" {
		entry += `,"status":"` + status + `"`
	}
	return entry + "}"
}

// pveshBackup is one entry of `pvesh get /nodes/<node>/storage/<storage>/content --content backup`.
func pveshBackup(storage string, vmid int, ctime int64) string {
	return fmt.Sprintf(`{"volid":"%s:backup/vzdump-qemu-%d-%d.vma.zst","format":"vma.zst","size":1048576,`+
		`"vmid":%d,"ctime":%d}`, storage, vmid, ctime, vmid, ctime)
}

func TestCollectProxmoxBackupIndexIncomplete(t *testing.T) {
	// A backup index that misses a backup storage is no index: every VM whose backups sit there would
	// read on the server as "No backup", critical. It is an outage instead, with its own code for an
	// inactive storage, and the log (diagnose) names the reason, short and without stderr.
	node := pveshNode(t)
	fails := runHelperDocker(t, "fail", time.Minute)
	twoStorages := "[" + pveshStorage(t, "local", "available") + "," + pveshStorage(t, "nas", "available") + "]"
	localBackups := "[" + pveshBackup("local", 100, 1760000000) + "]"
	cases := []struct {
		name       string
		replies    map[string]dockerReply
		code, text string
	}{
		{"list fails", map[string]dockerReply{pveshStorages: {err: fails}},
			"cli_failed", "pvesh get /cluster/resources failed: exit status 3"},
		{"list times out", map[string]dockerReply{pveshStorages: {err: context.DeadlineExceeded}},
			"timeout", "pvesh get /cluster/resources timed out after 15s"},
		{"list not json", map[string]dockerReply{pveshStorages: {out: "not json"}},
			"parse_failed", "pvesh get /cluster/resources output unreadable"},
		{"list null", map[string]dockerReply{pveshStorages: {out: "null"}},
			"parse_failed", "pvesh get /cluster/resources output unreadable"},
		// A storage that is not available gets no content call: it would fail with "storage ... is not
		// online", or hang on its share. Nothing is read before the outage.
		{"storage unknown", map[string]dockerReply{
			pveshStorages: {out: "[" + pveshStorage(t, "local", "available") + "," + pveshStorage(t, "nas", "unknown") + "]"},
		}, "backup_index_incomplete", "backup storage nas not active"},
		{"storage without status", map[string]dockerReply{
			pveshStorages: {out: "[" + pveshStorage(t, "local", "available") + "," + pveshStorage(t, "nas", "") + "]"},
		}, "backup_index_incomplete", "backup storage nas not active"},
		{"content fails", map[string]dockerReply{
			pveshStorages:                  {out: twoStorages},
			pveshBackupContent(t, "local"): {out: localBackups},
			pveshBackupContent(t, "nas"):   {err: fails},
		}, "cli_failed", "pvesh get " + node + "/storage/nas/content failed: exit status 3"},
		{"content times out", map[string]dockerReply{
			pveshStorages:                  {out: twoStorages},
			pveshBackupContent(t, "local"): {out: localBackups},
			pveshBackupContent(t, "nas"):   {err: context.DeadlineExceeded},
		}, "timeout", "pvesh get " + node + "/storage/nas/content timed out after 15s"},
		{"content not json", map[string]dockerReply{
			pveshStorages:                  {out: twoStorages},
			pveshBackupContent(t, "local"): {out: localBackups},
			pveshBackupContent(t, "nas"):   {out: "not json"},
		}, "parse_failed", "pvesh get " + node + "/storage/nas/content output unreadable"},
		{"content null", map[string]dockerReply{
			pveshStorages:                  {out: twoStorages},
			pveshBackupContent(t, "local"): {out: localBackups},
			pveshBackupContent(t, "nas"):   {out: "null"},
		}, "parse_failed", "pvesh get " + node + "/storage/nas/content output unreadable"},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			replies := map[string]dockerReply{
				pveshNodeStatus(t): {out: pveshNodeStatusFixture},
				pveshVMs:           {out: pveshVMsFixture},
			}
			for path, reply := range tc.replies {
				replies[path] = reply
			}
			stubPvesh(t, replies)
			logs := captureWarnings(t)
			assertProxmoxUnavailable(t, proxmoxBlock(t), logs, tc.code, tc.text)
		})
	}
}

func TestCollectProxmoxBackupIndex(t *testing.T) {
	// The counter-check: with every backup storage read, a VM gets its newest backup across all of them
	// and a VM without one stays null ("No backup" on the server); an empty storage is no failure.
	// Storages of other nodes and storages without backup content are no backup storages of this node:
	// their status does not count and their content is not read. The storage list never comes from
	// /nodes/<node>/storage, which activates every storage it lists.
	node := pveshNode(t)
	calls := stubPvesh(t, withReplies(noBackupDetails(t), map[string]dockerReply{
		pveshNodeStatus(t): {out: pveshNodeStatusFixture},
		pveshStorages: {out: "[" + pveshStorage(t, "nas", "available") + "," + pveshStorage(t, "local", "available") + "," +
			pveshStorageOn(t, "other-node", "nas", "backup", "unknown") + "," +
			pveshStorageOn(t, strings.TrimPrefix(node, "/nodes/"), "images", "images,rootdir", "unknown") + "," +
			pveshStorageOn(t, strings.TrimPrefix(node, "/nodes/"), "backup2", "iso,vztmpl", "available") + "," +
			pveshStorage(t, "pbs", "available") + "]"},
		pveshBackupContent(t, "local"): {out: "[" + pveshBackup("local", 100, 1760000000) + "]"},
		pveshBackupContent(t, "nas"): {out: "[" + pveshBackup("nas", 100, 1760086400) + "," +
			pveshBackup("nas", 100, 1759900000) + "]"},
		pveshBackupContent(t, "pbs"): {out: "[]"},
		pveshVMs:                     {out: pveshVMsFixture},
	}))
	now := time.Unix(1760090000, 0)
	block, check := collectProxmox(context.Background(), nil, now)
	wire := dockerWire(t, block)
	want := wantDockerWire(t, `{"vms": [
		{"vmid": 100, "name": "web", "status": "running", "type": "qemu", "last_backup_ts": 1760086400,
		 "backup_storage": "nas", "backup_size": 1048576, "backup_jobs": []},
		{"vmid": 101, "name": "dns", "status": "running", "type": "lxc", "last_backup_ts": null, "backup_jobs": []}
	]}`)
	if !reflect.DeepEqual(wire["vms"], want["vms"]) {
		t.Errorf("vms =\n%v\nwant\n%v", wire["vms"], want["vms"])
	}
	if wire["available"] != true || wire["error"] != nil || wire["node"] == nil {
		t.Errorf("available/error/node = %v/%v/%v, want true/null and the node status",
			wire["available"], wire["error"], wire["node"])
	}
	content := func(storage string) []string {
		return []string{"get", node + "/storage/" + storage + "/content", "--content", "backup", "--output-format", "json"}
	}
	wantCalls := [][]string{
		{"get", node + "/status", "--output-format", "json"},
		{"get", "/cluster/resources", "--type", "storage", "--output-format", "json"},
		content("local"), content("nas"), content("pbs"),
		{"get", "/cluster/backup", "--output-format", "json"},
		{"get", node + "/tasks", "--typefilter", "vzdump", "--statusfilter", "error", "--limit", "1", "--output-format", "json"},
		{"get", "/cluster/resources", "--type", "vm", "--output-format", "json"},
	}
	if !reflect.DeepEqual(*calls, wantCalls) {
		t.Errorf("calls =\n%v\nwant\n%v", *calls, wantCalls)
	}
	wantCheck := &backupIndexCheck{CheckedUnix: now.Unix(), Node: strings.TrimPrefix(node, "/nodes/"),
		Storages: []string{"local", "nas", "pbs"}, Index: map[int]int64{100: 1760086400},
		Newest: map[int]backupDetail{100: {Storage: "nas", Size: 1048576}}, Jobs: []backupJob{}}
	if !reflect.DeepEqual(check, wantCheck) {
		t.Errorf("check = %+v, want %+v", check, wantCheck)
	}
}

// proxmoxBlock is collectProxmox's block for a report without a saved backup index.
func proxmoxBlock(t *testing.T) map[string]any {
	t.Helper()
	block, _ := collectProxmox(context.Background(), nil, time.Now())
	return block
}

func TestCollectProxmoxBackupIndexCache(t *testing.T) {
	// The content of the backup storages is read at most every proxmoxBackupsEvery: a saved index that
	// is fresh for the same node and storages is the index, without a content call. An old one, one
	// from the future, one of another node or other storages, and one without an index are read anew.
	node := strings.TrimPrefix(pveshNode(t), "/nodes/")
	now := time.Unix(1760090000, 0)
	storages := []string{"local", "nas"}
	savedIndex := map[int]int64{100: 1750000000, 101: 1750000001}
	readIndex := map[int]int64{100: 1760000000}
	saved := func(age time.Duration, mutate func(*backupIndexCheck)) *backupIndexCheck {
		c := &backupIndexCheck{CheckedUnix: now.Add(-age).Unix(), Node: node, Storages: storages, Index: savedIndex}
		if mutate != nil {
			mutate(c)
		}
		return c
	}
	cases := []struct {
		name  string
		saved *backupIndexCheck
		read  bool
	}{
		{"fresh", saved(10*time.Minute, nil), false},
		{"just under the interval", saved(proxmoxBackupsEvery-time.Second, nil), false},
		{"old", saved(proxmoxBackupsEvery, nil), true},
		{"from the future", saved(-time.Minute, nil), true},
		{"no state", nil, true},
		{"state without index", saved(time.Minute, func(c *backupIndexCheck) { c.Index = nil }), true},
		{"other node", saved(time.Minute, func(c *backupIndexCheck) { c.Node = "other-node" }), true},
		{"storage added", saved(time.Minute, func(c *backupIndexCheck) { c.Storages = []string{"local"} }), true},
		{"empty fresh index", saved(time.Minute, func(c *backupIndexCheck) { c.Index = map[int]int64{} }), false},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			calls := stubPvesh(t, withReplies(noBackupDetails(t), map[string]dockerReply{
				pveshNodeStatus(t):             {out: pveshNodeStatusFixture},
				pveshStorages:                  {out: "[" + pveshStorage(t, "nas", "available") + "," + pveshStorage(t, "local", "available") + "]"},
				pveshBackupContent(t, "local"): {out: "[" + pveshBackup("local", 100, 1760000000) + "]"},
				pveshBackupContent(t, "nas"):   {out: "[]"},
				pveshVMs:                       {out: pveshVMsFixture},
			}))
			block, check := collectProxmox(context.Background(), tc.saved, now)
			contentCalls := 0
			for _, c := range *calls {
				if strings.HasSuffix(c[1], "/content") {
					contentCalls++
				}
			}
			wantTS := map[int]any{}
			if tc.read {
				if contentCalls != 2 {
					t.Errorf("content calls = %d, want 2 (one per storage): %v", contentCalls, *calls)
				}
				want := &backupIndexCheck{CheckedUnix: now.Unix(), Node: node, Storages: storages, Index: readIndex,
					Newest: map[int]backupDetail{100: {Storage: "local", Size: 1048576}}, Jobs: []backupJob{}}
				if !reflect.DeepEqual(check, want) {
					t.Errorf("check = %+v, want the index just read %+v", check, want)
				}
				wantTS[100], wantTS[101] = float64(1760000000), nil
			} else {
				if contentCalls != 0 {
					t.Errorf("content calls = %d, want none with a fresh index: %v", contentCalls, *calls)
				}
				if check != tc.saved {
					t.Errorf("check = %+v, want the saved one %+v unchanged", check, tc.saved)
				}
				for vmid := range map[int]bool{100: true, 101: true} {
					if ts, ok := tc.saved.Index[vmid]; ok {
						wantTS[vmid] = float64(ts)
					} else {
						wantTS[vmid] = nil
					}
				}
			}
			vms, _ := dockerWire(t, block)["vms"].([]any)
			if len(vms) != 2 {
				t.Fatalf("vms = %v, want both guests", vms)
			}
			for _, vm := range vms {
				m := vm.(map[string]any)
				vmid := int(m["vmid"].(float64))
				if !reflect.DeepEqual(m["last_backup_ts"], wantTS[vmid]) {
					t.Errorf("vm %d last_backup_ts = %v, want %v", vmid, m["last_backup_ts"], wantTS[vmid])
				}
			}
		})
	}
}

func TestCollectProxmoxOutageKeepsSavedIndex(t *testing.T) {
	// An outage reads no index, so the saved one goes on unchanged: the storage list that failed this
	// time says nothing about the backups read before. A storage that is not available is such an
	// outage, even with a fresh index.
	node := strings.TrimPrefix(pveshNode(t), "/nodes/")
	now := time.Unix(1760090000, 0)
	saved := &backupIndexCheck{CheckedUnix: now.Unix() - 60, Node: node, Storages: []string{"nas"},
		Index: map[int]int64{100: 1750000000}}
	for name, storages := range map[string]dockerReply{
		"list fails":            {err: context.DeadlineExceeded},
		"storage not available": {out: "[" + pveshStorage(t, "nas", "unknown") + "]"},
	} {
		t.Run(name, func(t *testing.T) {
			stubPvesh(t, map[string]dockerReply{
				pveshNodeStatus(t): {out: pveshNodeStatusFixture},
				pveshStorages:      storages,
			})
			captureWarnings(t)
			block, check := collectProxmox(context.Background(), saved, now)
			if block["available"] != false {
				t.Errorf("block = %v, want the outage", block)
			}
			if check != saved {
				t.Errorf("check = %+v, want the saved one %+v", check, saved)
			}
		})
	}
}

// Five guests as `pvesh get /cluster/resources --type vm` lists them, on two nodes, one in a pool.
const pveshGuestsFixture = `[
{"id":"qemu/100","type":"qemu","vmid":100,"name":"web","status":"running","node":"pve","pool":"prod"},
{"id":"lxc/101","type":"lxc","vmid":101,"name":"dns","status":"running","node":"pve2"},
{"id":"qemu/102","type":"qemu","vmid":102,"name":"db","status":"stopped","node":"pve"},
{"id":"qemu/103","type":"qemu","vmid":103,"name":"ci","status":"stopped","node":"pve"},
{"id":"qemu/104","type":"qemu","vmid":104,"name":"mail","status":"running","node":"pve"}]`

// The UPID and start of the last failed vzdump task the detail tests list.
const (
	backupTaskUPID  = "UPID:pve:0000ABCD:0123ABCD:68E89650:vzdump::root@pam:"
	backupTaskStart = 1760073296
)

// pveshFailedTask is the reply of the task list with one failed vzdump task.
func pveshFailedTask(upid string, start int64) string {
	return fmt.Sprintf(`[{"upid":%q,"node":"pve","pid":43981,"pstart":19088333,"starttime":%d,"type":"vzdump",`+
		`"id":"","user":"root@pam","status":"job errors","endtime":%d}]`, upid, start, start+600)
}

// pveshLog is a task log as `pvesh get /nodes/<node>/tasks/<upid>/log` prints it.
func pveshLog(t *testing.T, lines ...string) string {
	t.Helper()
	type line struct {
		N int    `json:"n"`
		T string `json:"t"`
	}
	out := make([]line, len(lines))
	for i, l := range lines {
		out[i] = line{i + 1, l}
	}
	raw, err := json.Marshal(out)
	if err != nil {
		t.Fatal(err)
	}
	return string(raw)
}

// collectBackupDetails runs collectProxmox at backupDetailsNow over the storages local and pbs with the
// content given, the guests of pveshGuestsFixture and the replies more (the details' calls). It returns
// the guests as they go on the wire by vmid, the check and the calls.
func collectBackupDetails(t *testing.T, local, pbs string, more map[string]dockerReply, saved *backupIndexCheck) (
	map[int]map[string]any, *backupIndexCheck, *[][]string) {
	t.Helper()
	calls := stubPvesh(t, withReplies(map[string]dockerReply{
		pveshNodeStatus(t):             {out: pveshNodeStatusFixture},
		pveshStorages:                  {out: "[" + pveshStorage(t, "local", "available") + "," + pveshStorage(t, "pbs", "available") + "]"},
		pveshBackupContent(t, "local"): {out: local},
		pveshBackupContent(t, "pbs"):   {out: pbs},
		pveshVMs:                       {out: pveshGuestsFixture},
	}, more))
	block, check := collectProxmox(context.Background(), saved, backupDetailsNow)
	wire := dockerWire(t, block)
	if wire["available"] != true {
		t.Fatalf("block = %v, want it available", wire)
	}
	vms := map[int]map[string]any{}
	for _, vm := range wire["vms"].([]any) {
		m := vm.(map[string]any)
		vms[int(m["vmid"].(float64))] = m
	}
	if len(vms) != 5 {
		t.Fatalf("vms = %v, want all five guests", vms)
	}
	return vms, check, calls
}

var backupDetailsNow = time.Unix(1760090000, 0)

// backupFields are the fields of a guest on the wire that begin with prefix.
func backupFields(vm map[string]any, prefix string) map[string]any {
	out := map[string]any{}
	for key, value := range vm {
		if strings.HasPrefix(key, prefix) {
			out[key] = value
		}
	}
	return out
}

func TestCollectProxmoxBackupDetails(t *testing.T) {
	// Storage, size and verification state of each guest's newest backup, across the storages. PBS lists
	// a size it does not know as 1: no size then, as for a missing one and one past what a float64
	// holds exactly. A verification state that is no short lowercase word is left out.
	local := "[" + pveshBackup("local", 100, 1760000000) + "," +
		`{"volid":"local:backup/vzdump-qemu-102-x.vma.zst","vmid":102,"ctime":1760000000},` +
		`{"volid":"local:backup/vzdump-qemu-103-x.vma.zst","vmid":103,"ctime":1760000000,"size":9007199254740992}]`
	pbs := `[{"volid":"pbs:backup/vm/100/2025-10-10T09:46:40Z","vmid":100,"ctime":1760086400,"size":2147483648,` +
		`"verification":{"state":"ok","upid":"UPID:pbs:00001234:00005678:00000001:68E89650:verify:store:root@pam:"}},` +
		`{"volid":"pbs:backup/ct/101/2025-10-09T08:53:20Z","vmid":101,"ctime":1760000000,"size":1,"verification":{"state":"failed"}},` +
		`{"volid":"pbs:backup/vm/104/2025-10-09T08:53:20Z","vmid":104,"ctime":1760000000,"size":4096,` +
		`"verification":{"state":"OK; see /var/log/proxmox-backup"}}]`
	vms, check, _ := collectBackupDetails(t, local, pbs, noBackupDetails(t), nil)
	want := map[int]map[string]any{
		100: {"backup_storage": "pbs", "backup_size": float64(2147483648), "backup_verify": "ok"},
		101: {"backup_storage": "pbs", "backup_verify": "failed"},
		102: {"backup_storage": "local"},
		103: {"backup_storage": "local"},
		104: {"backup_storage": "pbs", "backup_size": float64(4096)},
	}
	for vmid, w := range want {
		got := backupFields(vms[vmid], "backup_")
		delete(got, "backup_jobs")
		if !reflect.DeepEqual(got, w) {
			t.Errorf("vm %d details = %v, want %v", vmid, got, w)
		}
	}
	if check.Newest[100] != (backupDetail{Storage: "pbs", Size: 2147483648, Verify: "ok"}) || len(check.Newest) != 5 {
		t.Errorf("check.Newest = %+v, want the newest backup of each guest", check.Newest)
	}
}

// pveshJobsFixture are backup jobs as `pvesh get /cluster/backup` lists them, with the booleans as
// numbers, strings and JSON booleans, as the API hands them on.
const pveshJobsFixture = `[
{"id":"backup-a","type":"vzdump","enabled":1,"schedule":"daily","storage":"local","vmid":"100,101"},
{"id":"backup-b","type":"vzdump","schedule":"sun 01:00","storage":"pbs","all":1,"exclude":"101 102;103,104"},
{"id":"backup-c","type":"vzdump","enabled":"1","schedule":"hourly","storage":"pbs","pool":"prod","vmid":"102"},
{"id":"backup-d","type":"vzdump","enabled":true,"schedule":"weekly","storage":"local","all":"yes","node":"pve2"},
{"id":"backup-e","type":"vzdump","enabled":0,"schedule":"daily","storage":"local","all":1},
{"id":"backup-f","type":"vzdump","enabled":"off","schedule":"daily","storage":"local","vmid":"102"},
{"id":"backup-g","type":"vzdump","enabled":"True","schedule":"02:30","storage":"pbs","vmid":102,
 "mailto":"admin@example.com","comment":"db nightly","notes-template":"{{guestname}}","mailnotification":"always"},
{"id":"bad\nid","type":"vzdump","schedule":"daily","storage":"local","vmid":"104"},
{"id":"backup-i","type":"vzdump","schedule":"daily","storage":"local"},
{"id":"backup-j","type":"vzdump","schedule":"daily","storage":"local","pool":"Prod"},
{"id":"backup-k","type":"vzdump","schedule":"daily","storage":"local","all":0,"node":"pve"}
]`

func TestCollectProxmoxBackupJobs(t *testing.T) {
	// Each guest names the enabled jobs that back it up, by vzdump's rule: a pool selects its members
	// (exactly), else a VMID list its guests, else all but the excluded; a job bound to a node only the
	// guests on it. A disabled job and one that selects nothing name no guest; a guest without a job
	// gets an empty list. An id that is no label is left out; mail addresses, comments and note
	// templates are never kept.
	vms, check, _ := collectBackupDetails(t, "[]", "[]", withReplies(noBackupDetails(t),
		map[string]dockerReply{pveshJobs: {out: pveshJobsFixture}}), nil)
	job := func(id, schedule, storage string) map[string]any {
		out := map[string]any{"schedule": schedule, "storage": storage}
		if id != "" {
			out["id"] = id
		}
		return out
	}
	want := map[int][]map[string]any{
		100: {job("backup-a", "daily", "local"), job("backup-b", "sun 01:00", "pbs"), job("backup-c", "hourly", "pbs")},
		101: {job("backup-a", "daily", "local"), job("backup-d", "weekly", "local")},
		102: {job("backup-g", "02:30", "pbs")},
		103: {},
		104: {job("", "daily", "local")},
	}
	for vmid, w := range want {
		wantWire := dockerWire(t, map[string]any{"backup_jobs": w})["backup_jobs"]
		if got := vms[vmid]["backup_jobs"]; !reflect.DeepEqual(got, wantWire) {
			t.Errorf("vm %d backup_jobs = %v, want %v", vmid, got, wantWire)
		}
	}
	if len(check.Jobs) != 9 {
		t.Errorf("check.Jobs = %+v, want the nine enabled jobs", check.Jobs)
	}
	raw, err := json.Marshal(check.Jobs)
	if err != nil {
		t.Fatal(err)
	}
	for _, field := range []string{"admin@example.com", "db nightly", "guestname", "mailnotification", "always"} {
		if strings.Contains(string(raw), field) {
			t.Errorf("saved jobs %s keep %q", raw, field)
		}
	}
}

func TestCollectProxmoxBackupJobsCapped(t *testing.T) {
	// At most maxBackupJobs jobs are kept, in the order of the list; disabled jobs do not count.
	items := []string{`{"id":"off-1","enabled":0,"all":1}`, `{"id":"off-2","enabled":"0","all":1}`}
	for i := range maxBackupJobs + 6 {
		items = append(items, fmt.Sprintf(`{"id":"job-%d","schedule":"daily","storage":"local","all":1}`, i))
	}
	vms, check, _ := collectBackupDetails(t, "[]", "[]", withReplies(noBackupDetails(t),
		map[string]dockerReply{pveshJobs: {out: "[" + strings.Join(items, ",") + "]"}}), nil)
	var ids []string
	for _, job := range check.Jobs {
		ids = append(ids, job.ID)
	}
	if len(ids) != maxBackupJobs || ids[0] != "job-0" || ids[maxBackupJobs-1] != fmt.Sprintf("job-%d", maxBackupJobs-1) {
		t.Errorf("check.Jobs = %v, want job-0 … job-%d", ids, maxBackupJobs-1)
	}
	if jobs, _ := vms[100]["backup_jobs"].([]any); len(jobs) != maxBackupJobs {
		t.Errorf("vm 100 names %d jobs, want %d", len(jobs), maxBackupJobs)
	}
}

func TestCollectProxmoxReadsPVEBooleansAndVMIDLists(t *testing.T) {
	// The booleans and VMID lists of the PVE API in the forms pvesh prints them (PVE::JSONSchema
	// parse_boolean, PVE::Tools split_list).
	for _, tc := range []struct {
		v         any
		def, want bool
	}{
		{true, false, true}, {false, true, false}, {float64(1), false, true}, {float64(0), true, false},
		{"1", false, true}, {"ON", false, true}, {"yes", false, true}, {"True", false, true},
		{"0", true, false}, {"off", true, false}, {"No", true, false}, {"FALSE", true, false},
		{"maybe", true, true}, {"maybe", false, false}, {nil, true, true}, {nil, false, false},
		{[]any{}, true, true},
	} {
		if got := pveBool(tc.v, tc.def); got != tc.want {
			t.Errorf("pveBool(%#v, %v) = %v, want %v", tc.v, tc.def, got, tc.want)
		}
	}
	for _, tc := range []struct {
		v    any
		want []int
	}{
		{"100,101", []int{100, 101}},
		{"100 101;102,\t103", []int{100, 101, 102, 103}},
		{"100\x00101", []int{100, 101}},
		{"100\x00101 102", []int{100}},
		{float64(102), []int{102}},
		{"0,100,-1,1e3,abc,101x,", []int{100}},
		{"", nil},
		{nil, nil},
		{true, nil},
	} {
		if got := vmidList(tc.v); !reflect.DeepEqual(got, tc.want) {
			t.Errorf("vmidList(%#v) = %v, want %v", tc.v, got, tc.want)
		}
	}
}

func TestCollectProxmoxBackupErrors(t *testing.T) {
	// The errors vzdump logged per guest in the node's last failed vzdump task, capped and without
	// control characters. A guest whose newest backup is newer than that task's start shows none: its
	// error is over. Other lines, and lines that only look alike, name no guest.
	local := "[" + pveshBackup("local", 100, 1760000000) + "," + pveshBackup("local", 101, backupTaskStart+600) + "]"
	long := "disk\afull " + strings.Repeat("ü", 300)
	vms, check, calls := collectBackupDetails(t, local, "[]", map[string]dockerReply{
		pveshJobs:     {out: "[]"},
		pveshTasks(t): {out: pveshFailedTask(backupTaskUPID, backupTaskStart)},
		pveshTaskLog(t, backupTaskUPID): {out: pveshLog(t,
			"INFO: starting new backup job: vzdump 100 101 102 103 --storage local --mode snapshot",
			"INFO: Starting Backup of VM 100 (qemu)",
			"ERROR: Backup of VM 100 failed - unable to create temporary directory '/var/tmp/vzdumptmp1' at /usr/share/perl5/PVE/VZDump.pm line 1000.",
			"ERROR: Backup of VM 101 failed - old error",
			"INFO: Finished Backup of VM 101 (00:00:10)",
			"ERROR: Backup of VM 102 failed - "+long,
			" ERROR: Backup of VM 103 failed - indented",
			"ERROR: Backup of VM abc failed - no vmid",
			"ERROR: Backup of VM 0 failed - vmid 0",
			"ERROR: Backup job failed with errors",
		)},
	}, nil)
	capped := "disk full " + strings.Repeat("ü", maxBackupErrorRunes-len("disk full "))
	wantErrors := map[int]backupError{
		100: {backupTaskStart, "unable to create temporary directory '/var/tmp/vzdumptmp1' at /usr/share/perl5/PVE/VZDump.pm line 1000."},
		101: {backupTaskStart, "old error"},
		102: {backupTaskStart, capped},
	}
	if check.ErrorTask != backupTaskUPID || !reflect.DeepEqual(check.Errors, wantErrors) {
		t.Errorf("check = %q %+v, want %q %+v", check.ErrorTask, check.Errors, backupTaskUPID, wantErrors)
	}
	want := map[int]map[string]any{
		100: {"backup_error": wantErrors[100].Text, "backup_error_ts": float64(backupTaskStart)},
		101: {},
		102: {"backup_error": capped, "backup_error_ts": float64(backupTaskStart)},
		103: {},
		104: {},
	}
	for vmid, w := range want {
		if got := backupFields(vms[vmid], "backup_error"); !reflect.DeepEqual(got, w) {
			t.Errorf("vm %d = %v, want %v", vmid, got, w)
		}
	}
	wantLog := []string{"get", pveshTaskLog(t, backupTaskUPID), "--limit", "10000", "--output-format", "json"}
	if last := (*calls)[len(*calls)-2]; !reflect.DeepEqual(last, wantLog) {
		t.Errorf("log call = %q, want %q", last, wantLog)
	}
}

func TestCollectProxmoxBackupErrorsTask(t *testing.T) {
	// The log of the task the saved index names is not read again: its errors are the saved ones. The
	// log of another task is read; a task whose UPID is no vzdump task of PVE's form, or that has no
	// start, stays unread; no failed task leaves no errors.
	node := strings.TrimPrefix(pveshNode(t), "/nodes/")
	old := backupDetailsNow.Add(-proxmoxBackupsEvery).Unix()
	savedErrors := map[int]backupError{100: {backupTaskStart, "saved error"}}
	saved := func(task string) *backupIndexCheck {
		return &backupIndexCheck{CheckedUnix: old, Node: node, Storages: []string{"local", "pbs"},
			Index: map[int]int64{}, ErrorTask: task, Errors: savedErrors}
	}
	logged := map[int]backupError{100: {backupTaskStart, "read error"}}
	logReply := dockerReply{out: pveshLog(t, "ERROR: Backup of VM 100 failed - read error")}
	cases := []struct {
		name       string
		saved      *backupIndexCheck
		tasks      string
		logUPID    string
		wantTask   string
		wantErrors map[int]backupError
		warn       bool
	}{
		{"same task saved", saved(backupTaskUPID), pveshFailedTask(backupTaskUPID, backupTaskStart), "",
			backupTaskUPID, savedErrors, false},
		{"other task saved", saved("UPID:pve:0000ABCD:0123ABCD:68E80000:vzdump::root@pam:"),
			pveshFailedTask(backupTaskUPID, backupTaskStart), backupTaskUPID, backupTaskUPID, logged, false},
		{"no task saved", saved(""), pveshFailedTask(backupTaskUPID, backupTaskStart), backupTaskUPID,
			backupTaskUPID, logged, false},
		{"token user", nil, pveshFailedTask("UPID:pve:0000ABCD:0123ABCD:68E89650:vzdump:100:root@pam!backup:", backupTaskStart),
			"UPID:pve:0000ABCD:0123ABCD:68E89650:vzdump:100:root@pam!backup:",
			"UPID:pve:0000ABCD:0123ABCD:68E89650:vzdump:100:root@pam!backup:", logged, false},
		{"other task type", nil, pveshFailedTask("UPID:pve:0000ABCD:0123ABCD:68E89650:qmstart:100:root@pam:", backupTaskStart),
			"", "", nil, true},
		{"path in the user", nil, pveshFailedTask("UPID:pve:0000ABCD:0123ABCD:68E89650:vzdump::root@pam/../x:", backupTaskStart),
			"", "", nil, true},
		{"no start", nil, pveshFailedTask(backupTaskUPID, 0), "", "", nil, true},
		{"no upid", nil, `[{"starttime":1760073296,"type":"vzdump","status":"job errors"}]`, "", "", nil, true},
		{"no failed task", saved(backupTaskUPID), "[]", "", "", nil, false},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			more := map[string]dockerReply{pveshJobs: {out: "[]"}, pveshTasks(t): {out: tc.tasks}}
			if tc.logUPID != "" {
				more[pveshTaskLog(t, tc.logUPID)] = logReply
			}
			logs := captureWarnings(t)
			_, check, calls := collectBackupDetails(t, "[]", "[]", more, tc.saved)
			if check.ErrorTask != tc.wantTask || !reflect.DeepEqual(check.Errors, tc.wantErrors) {
				t.Errorf("check = %q %+v, want %q %+v", check.ErrorTask, check.Errors, tc.wantTask, tc.wantErrors)
			}
			logCalls := 0
			for _, c := range *calls {
				if strings.HasSuffix(c[1], "/log") {
					logCalls++
				}
			}
			wantCalls := 0
			if tc.logUPID != "" {
				wantCalls = 1
			}
			if logCalls != wantCalls {
				t.Errorf("log calls = %d, want %d: %v", logCalls, wantCalls, *calls)
			}
			line := "last failed backup task of " + node + " unreadable, backup errors left out"
			if strings.Contains(logs.String(), line) != tc.warn {
				t.Errorf("log = %q, want the warning %q: %v", logs.String(), line, tc.warn)
			}
		})
	}
}

func TestCollectProxmoxBackupDetailCallFails(t *testing.T) {
	// A detail that cannot be read leaves only its part out, logged (diagnose); the block stays
	// available with the index and the other details.
	node := pveshNode(t)
	fails := runHelperDocker(t, "fail", time.Minute)
	logPath := pveshTaskLog(t, backupTaskUPID)
	local := "[" + pveshBackup("local", 100, 1760000000) + "]"
	ok := map[string]dockerReply{
		pveshJobs:     {out: `[{"id":"backup-a","schedule":"daily","storage":"local","all":1}]`},
		pveshTasks(t): {out: pveshFailedTask(backupTaskUPID, backupTaskStart)},
		logPath:       {out: pveshLog(t, "ERROR: Backup of VM 100 failed - no space left on device")},
	}
	cases := []struct {
		name       string
		replies    map[string]dockerReply
		jobs, errs bool
		warning    string
	}{
		{"jobs fail", map[string]dockerReply{pveshJobs: {err: fails}}, false, true,
			"pvesh get /cluster/backup failed: exit status 3, backup jobs left out (cli_failed)"},
		{"jobs time out", map[string]dockerReply{pveshJobs: {err: context.DeadlineExceeded}}, false, true,
			"pvesh get /cluster/backup timed out after 15s, backup jobs left out (timeout)"},
		{"jobs null", map[string]dockerReply{pveshJobs: {out: "null"}}, false, true,
			"pvesh get /cluster/backup output unreadable, backup jobs left out (parse_failed)"},
		{"tasks fail", map[string]dockerReply{pveshTasks(t): {err: fails}}, true, false,
			"pvesh get " + node + "/tasks failed: exit status 3, backup errors left out (cli_failed)"},
		{"tasks not json", map[string]dockerReply{pveshTasks(t): {out: "not json"}}, true, false,
			"pvesh get " + node + "/tasks output unreadable, backup errors left out (parse_failed)"},
		{"log fails", map[string]dockerReply{logPath: {err: fails}}, true, false,
			"pvesh get " + logPath + " failed: exit status 3, backup errors left out (cli_failed)"},
		{"log times out", map[string]dockerReply{logPath: {err: context.DeadlineExceeded}}, true, false,
			"pvesh get " + logPath + " timed out after 15s, backup errors left out (timeout)"},
		{"log null", map[string]dockerReply{logPath: {out: "null"}}, true, false,
			"pvesh get " + logPath + " output unreadable, backup errors left out (parse_failed)"},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			logs := captureWarnings(t)
			vms, check, _ := collectBackupDetails(t, local, "[]", withReplies(ok, tc.replies), nil)
			vm := vms[100]
			if vm["last_backup_ts"] != float64(1760000000) || vm["backup_storage"] != "local" {
				t.Errorf("vm 100 = %v, want its backup and its storage", vm)
			}
			if _, has := vm["backup_jobs"]; has != tc.jobs || (check.Jobs != nil) != tc.jobs {
				t.Errorf("vm 100 backup_jobs = %v, check.Jobs = %+v, want them: %v", vm["backup_jobs"], check.Jobs, tc.jobs)
			}
			if _, has := vm["backup_error"]; has != tc.errs || (check.ErrorTask != "") != tc.errs {
				t.Errorf("vm 100 backup_error = %v, check.ErrorTask = %q, want them: %v", vm["backup_error"], check.ErrorTask, tc.errs)
			}
			if !strings.Contains(logs.String(), tc.warning) {
				t.Errorf("log = %q, want it to name %q", logs.String(), tc.warning)
			}
		})
	}
}

func TestCollectProxmoxBackupDetailsOfASavedIndex(t *testing.T) {
	// A fresh saved index is the index with its details, without a call for them; one an older agent
	// saved has no details, and its guests go out without them until the next read.
	node := strings.TrimPrefix(pveshNode(t), "/nodes/")
	fresh := func(details bool) *backupIndexCheck {
		c := &backupIndexCheck{CheckedUnix: backupDetailsNow.Unix() - 60, Node: node, Storages: []string{"local", "pbs"},
			Index: map[int]int64{100: 1760000000}}
		if details {
			c.Newest = map[int]backupDetail{100: {Storage: "pbs", Size: 4096, Verify: "ok"}}
			c.Jobs = []backupJob{{ID: "backup-a", Schedule: "daily", Storage: "pbs", VMIDs: []int{100}}}
			c.ErrorTask = backupTaskUPID
			c.Errors = map[int]backupError{102: {backupTaskStart, "no space left on device"}}
		}
		return c
	}
	t.Run("older agent", func(t *testing.T) {
		vms, _, calls := collectBackupDetails(t, "[]", "[]", nil, fresh(false))
		for vmid, vm := range vms {
			if got := backupFields(vm, "backup_"); len(got) != 0 {
				t.Errorf("vm %d details = %v, want none", vmid, got)
			}
		}
		if len(*calls) != 3 {
			t.Errorf("calls = %v, want status, storages and guests only", *calls)
		}
	})
	t.Run("with details", func(t *testing.T) {
		vms, _, calls := collectBackupDetails(t, "[]", "[]", nil, fresh(true))
		want := wantDockerWire(t, `{"backup_storage": "pbs", "backup_size": 4096, "backup_verify": "ok",
			"backup_jobs": [{"id": "backup-a", "schedule": "daily", "storage": "pbs"}]}`)
		if got := backupFields(vms[100], "backup_"); !reflect.DeepEqual(got, want) {
			t.Errorf("vm 100 details = %v, want %v", got, want)
		}
		wantError := map[string]any{"backup_error": "no space left on device", "backup_error_ts": float64(backupTaskStart)}
		if got := backupFields(vms[102], "backup_error"); !reflect.DeepEqual(got, wantError) {
			t.Errorf("vm 102 = %v, want %v", got, wantError)
		}
		if len(*calls) != 3 {
			t.Errorf("calls = %v, want status, storages and guests only", *calls)
		}
	})
}
