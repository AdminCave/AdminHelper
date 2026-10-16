// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package monitor

import (
	"encoding/json"
	"reflect"
	"testing"
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

func TestParseRestartPolicies(t *testing.T) {
	// docker inspect output: full ID + policy; keyed by the short 12-char ID as ps prints it.
	out := []byte("abcdef012345678901234567890 always\n1234567890abcdef0000000000 no\nshort xxx")
	policies := parseRestartPolicies(out)
	if policies["abcdef012345"] != "always" {
		t.Errorf("abcdef012345 -> %q, want always", policies["abcdef012345"])
	}
	if policies["1234567890ab"] != "no" {
		t.Errorf("1234567890ab -> %q, want no", policies["1234567890ab"])
	}
	if len(policies) != 2 {
		t.Errorf("too-short ID should be skipped: %v", policies)
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
