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
	_, err := runTimed(context.Background(), timeout, os.Args[0], "-test.run=^TestHelperDockerProcess$")
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
	out, err := runTimed(context.Background(), time.Second, os.Args[0], "-test.run=^TestHelperDockerProcess$")
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
	_, err := runTimed(ctx, time.Minute, os.Args[0], "-test.run=^TestHelperDockerProcess$")
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
	pluginCollectors.proxmox = record("proxmox")
	pluginCollectors.zfs = record("zfs")

	ctx := context.WithValue(context.Background(), ctxKey{}, t.Name())
	buildReportWithState(ctx, nil, reportState{}, time.Now())
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
		 "exit_code": 1, "oom_killed": false, "restart_count": 3, "health": ""},
		{"id": "c1f596e07951", "name": "ah-t1-oom", "image": "alpine:3.22", "state": "exited",
		 "status": "Exited (137) 12 seconds ago", "restart_policy": "no",
		 "exit_code": 137, "oom_killed": true, "restart_count": 0, "health": ""},
		{"id": "6ae4d13d53eb", "name": "ah-t1-unhealthy", "image": "alpine:3.22", "state": "running",
		 "status": "Up 13 seconds (unhealthy)", "restart_policy": "no",
		 "exit_code": 0, "oom_killed": false, "restart_count": 0, "health": "unhealthy"},
		{"id": "a39b0754602d", "name": "ah-t1-exit3", "image": "alpine:3.22", "state": "exited",
		 "status": "Exited (3) 15 seconds ago", "restart_policy": "no",
		 "exit_code": 3, "oom_killed": false, "restart_count": 0, "health": ""}
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

func TestParseZpoolList(t *testing.T) {
	out := []byte("tank\t3.62T\t1.2T\t2.4T\t33%\tONLINE\nbackup\t1T\t900G\t100G\t90%\tDEGRADED")
	pools := parseZpoolList(out)
	if len(pools) != 2 {
		t.Fatalf("want 2 pools, got %d: %v", len(pools), pools)
	}
	if pools[0]["name"] != "tank" || pools[0]["capacity_percent"] != 33 || pools[0]["health"] != "ONLINE" {
		t.Errorf("tank: %v", pools[0])
	}
	if pools[1]["capacity_percent"] != 90 || pools[1]["health"] != "DEGRADED" {
		t.Errorf("backup: %v", pools[1])
	}
	if short := parseZpoolList([]byte("tank\t3.62T")); len(short) != 0 {
		t.Errorf("line with too few columns should be skipped: %v", short)
	}
}

// stubZpool swaps zpoolCLI for a fake zpool that is on the PATH and answers each call by its
// subcommand (list, status) from replies, like stubDocker. It returns the recorded calls; a
// subcommand without a reply fails the test.
func stubZpool(t *testing.T, replies map[string]dockerReply) *[][]string {
	t.Helper()
	old := zpoolCLI
	t.Cleanup(func() { zpoolCLI = old })
	var calls [][]string
	zpoolCLI.lookPath = func(file string) (string, error) { return "/usr/sbin/" + file, nil }
	zpoolCLI.run = func(_ context.Context, args ...string) ([]byte, error) {
		calls = append(calls, args)
		reply, ok := replies[args[0]]
		if !ok {
			t.Errorf("unexpected zpool call %v", args)
			return nil, errors.New("unexpected call")
		}
		return []byte(reply.out), reply.err
	}
	return &calls
}

var zpoolListArgs = []string{"list", "-H", "-o", "name,size,alloc,free,cap,health"}

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
	const list = "tank\t3.62T\t1.2T\t2.4T\t33%\tONLINE\nbackup\t1T\t900G\t100G\t90%\tDEGRADED\n"
	const status = "  pool: backup\n state: DEGRADED\n"
	calls := stubZpool(t, map[string]dockerReply{"list": {out: list}, "status": {out: status}})
	got := dockerWire(t, collectZFS(context.Background()))
	want := wantDockerWire(t, `{"available": true, "error": null, "pools": [
		{"name": "tank", "size": "3.62T", "allocated": "1.2T", "free": "2.4T", "capacity_percent": 33,
		 "health": "ONLINE"},
		{"name": "backup", "size": "1T", "allocated": "900G", "free": "100G", "capacity_percent": 90,
		 "health": "DEGRADED"}
	], "errors": "pool: backup\n state: DEGRADED"}`)
	if !reflect.DeepEqual(got, want) {
		t.Errorf("block =\n%v\nwant\n%v", got, want)
	}
	if !reflect.DeepEqual(*calls, [][]string{zpoolListArgs, {"status", "-x"}}) {
		t.Errorf("calls = %v, want zpool list and zpool status -x", *calls)
	}

	t.Run("all online", func(t *testing.T) {
		calls := stubZpool(t, map[string]dockerReply{"list": {out: "tank\t3.62T\t1.2T\t2.4T\t33%\tONLINE\n"}})
		got := dockerWire(t, collectZFS(context.Background()))
		if got["available"] != true || got["error"] != nil || len(got["pools"].([]any)) != 1 {
			t.Errorf("block = %v, want one available pool", got)
		}
		if _, ok := got["errors"]; ok || len(*calls) != 1 {
			t.Errorf("errors = %v, calls = %v, want neither errors nor zpool status", got["errors"], *calls)
		}
	})

	t.Run("status fails", func(t *testing.T) {
		// As before: without zpool status -x the pools still go out, only the error details are missing.
		stubZpool(t, map[string]dockerReply{"list": {out: list}, "status": {err: context.DeadlineExceeded}})
		got := dockerWire(t, collectZFS(context.Background()))
		if got["available"] != true || got["error"] != nil || len(got["pools"].([]any)) != 2 {
			t.Errorf("block = %v, want both pools available", got)
		}
		if _, ok := got["errors"]; ok {
			t.Errorf("errors = %v, want none without zpool status", got["errors"])
		}
	})
}

// stubPvesh swaps pveshCLI for a fake pvesh that is on the PATH and answers each `pvesh get` by its
// API path from replies, like stubZpool; a path without a reply fails the test. It returns the
// recorded calls.
func stubPvesh(t *testing.T, replies map[string]dockerReply) *[][]string {
	t.Helper()
	old := pveshCLI
	t.Cleanup(func() { pveshCLI = old })
	var calls [][]string
	pveshCLI.lookPath = func(file string) (string, error) { return "/usr/bin/" + file, nil }
	pveshCLI.run = func(_ context.Context, args ...string) ([]byte, error) {
		calls = append(calls, args)
		var reply dockerReply
		ok := len(args) > 1 && args[0] == "get"
		if ok {
			reply, ok = replies[args[1]]
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

// pveshBackupStorages is the API path collectProxmox asks for the local node's backup storages.
func pveshBackupStorages(t *testing.T) string {
	t.Helper()
	return pveshNode(t) + "/storage"
}

// pveshBackupContent is the API path collectProxmox asks for the backups on one storage.
func pveshBackupContent(t *testing.T, storage string) string {
	t.Helper()
	return pveshNode(t) + "/storage/" + storage + "/content"
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
	if got := collectProxmox(context.Background()); got != nil {
		t.Errorf("collectProxmox() = %v, want nil (pvesh not installed is not an outage)", got)
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
	assertProxmoxUnavailable(t, collectProxmox(context.Background()), logs, "cli_failed", "local hostname unreadable")
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
			assertProxmoxUnavailable(t, collectProxmox(context.Background()), logs, tc.code, tc.text)
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
			stubPvesh(t, map[string]dockerReply{
				pveshNodeStatus(t):     {out: pveshNodeStatusFixture},
				pveshBackupStorages(t): {out: "[]"},
				"/cluster/resources":   tc.reply,
			})
			logs := captureWarnings(t)
			assertProxmoxUnavailable(t, collectProxmox(context.Background()), logs, tc.code, tc.text)
		})
	}
}

func TestCollectProxmoxNoVMs(t *testing.T) {
	// The counter-check: an empty list is a node without VMs, and the block goes out available with
	// the node and an empty list, never null.
	stubPvesh(t, map[string]dockerReply{
		pveshNodeStatus(t):     {out: pveshNodeStatusFixture},
		pveshBackupStorages(t): {out: "[]"},
		"/cluster/resources":   {out: "[]"},
	})
	got := dockerWire(t, collectProxmox(context.Background()))
	want := wantDockerWire(t, `{"available": true, "error": null, "vms": [],
		"node": {"name": "`+strings.TrimPrefix(pveshNode(t), "/nodes/")+`", "cpu": 5, "memory_percent": 25}}`)
	if !reflect.DeepEqual(got, want) {
		t.Errorf("block =\n%v\nwant\n%v", got, want)
	}
}

// Two running guests as `pvesh get /cluster/resources --type vm` lists them.
const pveshVMsFixture = `[{"id":"qemu/100","type":"qemu","vmid":100,"name":"web","status":"running","node":"pve"},
{"id":"lxc/101","type":"lxc","vmid":101,"name":"dns","status":"running","node":"pve"}]`

// pveshStorage is one entry of `pvesh get /nodes/<node>/storage --content backup` with the given
// active value (JSON); an empty value leaves the field out.
func pveshStorage(id, active string) string {
	entry := `{"storage":"` + id + `","type":"dir","content":"backup,iso","enabled":1,"shared":0`
	if active != "" {
		entry += `,"active":` + active
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
	twoStorages := "[" + pveshStorage("local", "1") + "," + pveshStorage("nas", "1") + "]"
	localBackups := "[" + pveshBackup("local", 100, 1760000000) + "]"
	cases := []struct {
		name       string
		replies    map[string]dockerReply
		code, text string
	}{
		{"list fails", map[string]dockerReply{pveshBackupStorages(t): {err: fails}},
			"cli_failed", "pvesh get " + node + "/storage failed: exit status 3"},
		{"list times out", map[string]dockerReply{pveshBackupStorages(t): {err: context.DeadlineExceeded}},
			"timeout", "pvesh get " + node + "/storage timed out after 15s"},
		{"list not json", map[string]dockerReply{pveshBackupStorages(t): {out: "not json"}},
			"parse_failed", "pvesh get " + node + "/storage output unreadable"},
		{"list null", map[string]dockerReply{pveshBackupStorages(t): {out: "null"}},
			"parse_failed", "pvesh get " + node + "/storage output unreadable"},
		// An inactive storage gets no content call: it would fail with "storage ... is not online".
		{"storage active 0", map[string]dockerReply{
			pveshBackupStorages(t):         {out: "[" + pveshStorage("local", "1") + "," + pveshStorage("nas", "0") + "]"},
			pveshBackupContent(t, "local"): {out: localBackups},
		}, "backup_index_incomplete", "backup storage nas not active"},
		{"storage active false", map[string]dockerReply{
			pveshBackupStorages(t):         {out: "[" + pveshStorage("local", "1") + "," + pveshStorage("nas", "false") + "]"},
			pveshBackupContent(t, "local"): {out: localBackups},
		}, "backup_index_incomplete", "backup storage nas not active"},
		{"storage without active", map[string]dockerReply{
			pveshBackupStorages(t):         {out: "[" + pveshStorage("local", "1") + "," + pveshStorage("nas", "") + "]"},
			pveshBackupContent(t, "local"): {out: localBackups},
		}, "backup_index_incomplete", "backup storage nas not active"},
		{"content fails", map[string]dockerReply{
			pveshBackupStorages(t):         {out: twoStorages},
			pveshBackupContent(t, "local"): {out: localBackups},
			pveshBackupContent(t, "nas"):   {err: fails},
		}, "cli_failed", "pvesh get " + node + "/storage/nas/content failed: exit status 3"},
		{"content times out", map[string]dockerReply{
			pveshBackupStorages(t):         {out: twoStorages},
			pveshBackupContent(t, "local"): {out: localBackups},
			pveshBackupContent(t, "nas"):   {err: context.DeadlineExceeded},
		}, "timeout", "pvesh get " + node + "/storage/nas/content timed out after 15s"},
		{"content not json", map[string]dockerReply{
			pveshBackupStorages(t):         {out: twoStorages},
			pveshBackupContent(t, "local"): {out: localBackups},
			pveshBackupContent(t, "nas"):   {out: "not json"},
		}, "parse_failed", "pvesh get " + node + "/storage/nas/content output unreadable"},
		{"content null", map[string]dockerReply{
			pveshBackupStorages(t):         {out: twoStorages},
			pveshBackupContent(t, "local"): {out: localBackups},
			pveshBackupContent(t, "nas"):   {out: "null"},
		}, "parse_failed", "pvesh get " + node + "/storage/nas/content output unreadable"},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			replies := map[string]dockerReply{
				pveshNodeStatus(t):   {out: pveshNodeStatusFixture},
				"/cluster/resources": {out: pveshVMsFixture},
			}
			for path, reply := range tc.replies {
				replies[path] = reply
			}
			stubPvesh(t, replies)
			logs := captureWarnings(t)
			assertProxmoxUnavailable(t, collectProxmox(context.Background()), logs, tc.code, tc.text)
		})
	}
}

func TestCollectProxmoxBackupIndex(t *testing.T) {
	// The counter-check: with every backup storage read, a VM gets its newest backup across all of them
	// and a VM without one stays null ("No backup" on the server); an empty storage is no failure. The
	// active flag counts as 1 and as true.
	node := pveshNode(t)
	calls := stubPvesh(t, map[string]dockerReply{
		pveshNodeStatus(t): {out: pveshNodeStatusFixture},
		pveshBackupStorages(t): {out: "[" + pveshStorage("local", "1") + "," + pveshStorage("nas", "true") + "," +
			pveshStorage("pbs", "1") + "]"},
		pveshBackupContent(t, "local"): {out: "[" + pveshBackup("local", 100, 1760000000) + "]"},
		pveshBackupContent(t, "nas"): {out: "[" + pveshBackup("nas", 100, 1760086400) + "," +
			pveshBackup("nas", 100, 1759900000) + "]"},
		pveshBackupContent(t, "pbs"): {out: "[]"},
		"/cluster/resources":         {out: pveshVMsFixture},
	})
	wire := dockerWire(t, collectProxmox(context.Background()))
	want := wantDockerWire(t, `{"vms": [
		{"vmid": 100, "name": "web", "status": "running", "type": "qemu", "last_backup_ts": 1760086400},
		{"vmid": 101, "name": "dns", "status": "running", "type": "lxc", "last_backup_ts": null}
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
		{"get", node + "/storage", "--content", "backup", "--output-format", "json"},
		content("local"), content("nas"), content("pbs"),
		{"get", "/cluster/resources", "--type", "vm", "--output-format", "json"},
	}
	if !reflect.DeepEqual(*calls, wantCalls) {
		t.Errorf("calls =\n%v\nwant\n%v", *calls, wantCalls)
	}
}
