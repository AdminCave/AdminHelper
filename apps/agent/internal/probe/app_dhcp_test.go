// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package probe

import (
	"context"
	"errors"
	"net"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"sync"
	"testing"
)

// stubKea stands a Kea for the control sockets: the first socket is not served, the second answers
// each request with answer. It returns the paths dialed and the requests read.
func stubKea(t *testing.T, answer string) (*[]string, *[]string) {
	t.Helper()
	oldSockets, oldDial := keaSockets, keaDial
	t.Cleanup(func() { keaSockets, keaDial = oldSockets, oldDial })
	keaSockets = []string{"first", "second"}
	var mu sync.Mutex
	var dialed, requests []string
	keaDial = func(_ context.Context, path string) (net.Conn, error) {
		mu.Lock()
		dialed = append(dialed, path)
		mu.Unlock()
		if path == "first" {
			return nil, errNoListener
		}
		client, server := net.Pipe()
		go func() {
			defer func() { _ = server.Close() }()
			buf := make([]byte, 4096)
			n, _ := server.Read(buf)
			mu.Lock()
			requests = append(requests, string(buf[:n]))
			mu.Unlock()
			_, _ = server.Write([]byte(answer))
		}()
		return client, nil
	}
	return &dialed, &requests
}

const keaAnswer = `{"result": 0, "arguments": {
 "subnet[1].total-addresses": [[100, "2026-11-13 10:00:00.000001"], [100, "2026-11-13 09:00:00.000001"]],
 "subnet[1].assigned-addresses": [[50, "2026-11-13 10:00:00.000001"], [99, "2026-11-13 09:00:00.000001"]],
 "subnet[1].pool[0].total-addresses": [[10, "2026-11-13 10:00:00.000001"]],
 "subnet[1].pool[0].assigned-addresses": [[10, "2026-11-13 10:00:00.000001"]],
 "subnet[7].total-addresses": [[200, "2026-11-13 10:00:00.000001"]],
 "subnet[7].assigned-addresses": [[173, "2026-11-13 10:00:00.000001"]],
 "subnet[9].total-addresses": [[0, "2026-11-13 10:00:00.000001"]],
 "subnet[9].assigned-addresses": [[0, "2026-11-13 10:00:00.000001"]],
 "v4-allocation-fail": [[4, "2026-11-13 10:00:00.000001"]],
 "pkt4-received": [[12345, "2026-11-13 10:00:00.000001"]]
}}`

func TestKeaPoolsReadsTheFullestSubnetThroughStatisticGetAll(t *testing.T) {
	dialed, requests := stubKea(t, keaAnswer)
	values, err := keaPools(context.Background(), Target{Kind: kindUnit, Name: "kea-dhcp4-server.service"})
	if err != nil {
		t.Fatal(err)
	}
	// The newest sample counts; a pool's own statistics do not; subnet 9 has no addresses.
	want := map[string]any{"subnets": 3, "max_pool_used_pct": 86.5, "alloc_fail": int64(4)}
	if !reflect.DeepEqual(values, want) {
		t.Errorf("values %v, want %v", values, want)
	}
	if !reflect.DeepEqual(*dialed, []string{"first", "second"}) {
		t.Errorf("dialed %q", *dialed)
	}
	if !reflect.DeepEqual(*requests, []string{`{"command": "statistic-get-all", "arguments": {}}`}) {
		t.Errorf("requests %q", *requests)
	}
}

func TestKeaPoolsTakesTheAnswerOfTheControlAgent(t *testing.T) {
	stubKea(t, `[{"result": 0, "arguments": {"subnet[2].total-addresses": [[4, "x"]], "subnet[2].assigned-addresses": [[1, "x"]]}}]`)
	values, err := keaPools(context.Background(), Target{})
	// A Kea without the global statistic has no alloc_fail.
	want := map[string]any{"subnets": 1, "max_pool_used_pct": 25.0}
	if err != nil || !reflect.DeepEqual(values, want) {
		t.Errorf("values %v, error %v, want %v", values, err, want)
	}
}

func TestKeaPoolsFailsWhatItCannotRead(t *testing.T) {
	for name, answer := range map[string]string{
		"result not success": `{"result": 1, "text": "subnet[1] 192.0.2.0/24 secret"}`,
		"no result":          `{"arguments": {}}`,
		"not json":           `subnet[1] 192.0.2.0/24`,
		"sample of another":  `{"result": 0, "arguments": {"subnet[1].total-addresses": [["many", "x"]]}}`,
		"no sample":          `{"result": 0, "arguments": {"subnet[1].total-addresses": []}}`,
		"negative":           `{"result": 0, "arguments": {"v4-allocation-fail": [[-1, "x"]]}}`,
		"list of two":        `[{"result": 0, "arguments": {}}, {"result": 0, "arguments": {}}]`,
	} {
		t.Run(name, func(t *testing.T) {
			stubKea(t, answer)
			_, err := keaPools(context.Background(), Target{})
			if err == nil {
				t.Fatal("no error")
			}
			if strings.Contains(err.Error(), "192.0.2") || strings.Contains(err.Error(), "secret") {
				t.Errorf("error %q quotes Kea", err)
			}
		})
	}
}

func TestKeaPoolsWithoutAControlSocketIsUnsupported(t *testing.T) {
	oldSockets, oldDial := keaSockets, keaDial
	t.Cleanup(func() { keaSockets, keaDial = oldSockets, oldDial })
	keaSockets = []string{"a", "b"}
	keaDial = func(context.Context, string) (net.Conn, error) { return nil, errNoListener }
	if _, err := keaPools(context.Background(), Target{}); !errors.Is(err, ErrUnsupported) {
		t.Errorf("error %v, want ErrUnsupported", err)
	}
	keaDial = func(context.Context, string) (net.Conn, error) { return nil, ErrNotAllowed }
	if _, err := keaPools(context.Background(), Target{}); !errors.Is(err, ErrNotAllowed) {
		t.Errorf("error %v, want the guard's refusal", err)
	}
}

// stubDnsmasq lays out dnsmasq's files under a directory of the test: files maps a name to its
// content, "conf" being dnsmasq.conf, "leases" the lease file and names under "d/" the Debian directory.
func stubDnsmasq(t *testing.T, files map[string]string) string {
	t.Helper()
	dir := t.TempDir()
	if err := os.Mkdir(filepath.Join(dir, "d"), 0o755); err != nil {
		t.Fatal(err)
	}
	for name, content := range files {
		if err := os.WriteFile(filepath.Join(dir, name), []byte(strings.ReplaceAll(content, "$DIR", dir)), 0o600); err != nil {
			t.Fatal(err)
		}
	}
	oldConf, oldLeases, oldDir := dnsmasqConf, dnsmasqLeases, dnsmasqDebianDir
	t.Cleanup(func() { dnsmasqConf, dnsmasqLeases, dnsmasqDebianDir = oldConf, oldLeases, oldDir })
	dnsmasqConf, dnsmasqLeases, dnsmasqDebianDir = filepath.Join(dir, "conf"), filepath.Join(dir, "leases"), filepath.Join(dir, "d")
	return dir
}

const dnsmasqLeaseFile = `1763030000 52:54:00:aa:bb:01 192.0.2.10 laptop 01:52:54:00:aa:bb:01
0 52:54:00:aa:bb:02 192.0.2.11 * *
1763030000 52:54:00:aa:bb:03 192.0.2.200 printer *
duid 00:01:00:01:2c:5f:aa:bb:52:54:00:aa:bb:01
1763030000 12345678 2001:db8::10 laptop 00:01:00:01
`

func TestDnsmasqLeasesCountsLeasesAgainstTheDynamicRanges(t *testing.T) {
	stubDnsmasq(t, map[string]string{
		"conf": `# dhcp-range=10.0.0.1,10.0.0.254
dhcp-range=tag:lan,set:office,192.0.2.10,192.0.2.19,255.255.255.0,12h
dhcp-range=192.0.2.15,192.0.2.24
dhcp-range=198.51.100.0,static
dhcp-range=::100,::1ff,constructor:eth0
dhcp-range=2001:db8::10,2001:db8::ff
conf-file=$DIR/extra
conf-dir=$DIR/more,*.conf
`,
		"extra":          "dhcp-range=interface:eth1,203.0.113.1,203.0.113.10,1h\n",
		"leases":         dnsmasqLeaseFile,
		"d/lan":          "dhcp-range=198.51.100.100,198.51.100.109\n",
		"d/lan.dpkg-old": "dhcp-range=198.51.100.0,198.51.100.255\n",
		"d/lan~":         "dhcp-range=198.51.100.0,198.51.100.255\n",
		"d/.hidden":      "dhcp-range=198.51.100.0,198.51.100.255\n",
		"d/#autosave#":   "dhcp-range=198.51.100.0,198.51.100.255\n",
	})
	values, err := dnsmasqLeaseView(context.Background(), Target{Kind: kindUnit, Name: "dnsmasq.service"})
	if err != nil {
		t.Fatal(err)
	}
	// Ranges 192.0.2.10-24 (15, the overlap once), 203.0.113.1-10 (10), 198.51.100.100-109 (10); the
	// lease of 192.0.2.200 is a static one outside them.
	want := map[string]any{"leases": 3, "range_size": int64(35), "used_pct": 5.7}
	if !reflect.DeepEqual(values, want) {
		t.Errorf("values %v, want %v", values, want)
	}
	noneOf(t, values, "192.0.2", "laptop", "52:54")
}

func TestDnsmasqConfDirTakesOnlyItsExtensions(t *testing.T) {
	dir := stubDnsmasq(t, map[string]string{
		"conf":   "conf-dir=$DIR/more,*.conf\nconf-dir=$DIR/other,.bak\n",
		"leases": "",
	})
	for name, content := range map[string]string{
		"more/a.conf": "dhcp-range=192.0.2.1,192.0.2.4\n",
		"more/b.txt":  "dhcp-range=192.0.2.101,192.0.2.200\n",
		"other/c":     "dhcp-range=198.51.100.1,198.51.100.2\n",
		"other/d.bak": "dhcp-range=198.51.100.101,198.51.100.200\n",
	} {
		_ = os.MkdirAll(filepath.Dir(filepath.Join(dir, name)), 0o755)
		if err := os.WriteFile(filepath.Join(dir, name), []byte(content), 0o600); err != nil {
			t.Fatal(err)
		}
	}
	values, err := dnsmasqLeaseView(context.Background(), Target{})
	want := map[string]any{"leases": 0, "range_size": int64(6), "used_pct": 0.0}
	if err != nil || !reflect.DeepEqual(values, want) {
		t.Errorf("values %v, error %v, want %v", values, err, want)
	}
}

func TestDnsmasqReadsTheLeaseFileItsConfigurationNames(t *testing.T) {
	stubDnsmasq(t, map[string]string{
		"conf":  "dhcp-leasefile=$DIR/moved\ndhcp-range=192.0.2.10,192.0.2.11\n",
		"moved": "0 52:54:00:aa:bb:02 192.0.2.11 * *\n",
	})
	values, err := dnsmasqLeaseView(context.Background(), Target{})
	want := map[string]any{"leases": 1, "range_size": int64(2), "used_pct": 50.0}
	if err != nil || !reflect.DeepEqual(values, want) {
		t.Errorf("values %v, error %v, want %v", values, err, want)
	}
}

func TestDnsmasqDropsCommentsAndQuotesLikeDnsmasq(t *testing.T) {
	stubDnsmasq(t, map[string]string{
		"conf": "dhcp-range=192.0.2.10,192.0.2.19 # lan\n" +
			"dhcp-leasefile=\"$DIR/moved\"\t# moved\n" +
			"conf-dir=$DIR/more # more\n" +
			"  # dhcp-range=198.51.100.1,198.51.100.200\n",
		"moved": "0 52:54:00:aa:bb:02 192.0.2.11 * *\n",
	})
	if err := os.Mkdir(filepath.Join(filepath.Dir(dnsmasqConf), "more"), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(filepath.Dir(dnsmasqConf), "more", "x"), []byte("dhcp-range=203.0.113.1,203.0.113.10\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	values, err := dnsmasqLeaseView(context.Background(), Target{})
	want := map[string]any{"leases": 1, "range_size": int64(20), "used_pct": 5.0}
	if err != nil || !reflect.DeepEqual(values, want) {
		t.Errorf("values %v, error %v, want %v", values, err, want)
	}
	for line, want := range map[string]string{
		"a=b#c":         "a=b#c",
		"a=b #c":        "a=b ",
		"a=\"b #c\" #d": "a=b #c ",
		"#a":            "",
	} {
		if got := dnsmasqLine(line); got != want {
			t.Errorf("dnsmasqLine(%q) = %q, want %q", line, got, want)
		}
	}
}

func TestDnsmasqWithoutDHCPIsUnsupported(t *testing.T) {
	// A dnsmasq for DNS alone writes no lease file.
	stubDnsmasq(t, map[string]string{"conf": "server=192.0.2.53\n"})
	if _, err := dnsmasqLeaseView(context.Background(), Target{}); !errors.Is(err, ErrUnsupported) {
		t.Errorf("error %v, want ErrUnsupported", err)
	}
}

func TestDnsmasqWithoutDHCPRangesHasNoShare(t *testing.T) {
	stubDnsmasq(t, map[string]string{"conf": "dhcp-range=198.51.100.0,proxy\n", "leases": ""})
	values, err := dnsmasqLeaseView(context.Background(), Target{})
	want := map[string]any{"leases": 0, "range_size": int64(0)}
	if err != nil || !reflect.DeepEqual(values, want) {
		t.Errorf("values %v, error %v, want %v", values, err, want)
	}
}

func TestDnsmasqLeasesFailsWhatItCannotRead(t *testing.T) {
	for name, files := range map[string]map[string]string{
		"no lease file":      {"conf": "dhcp-range=192.0.2.1,192.0.2.9\n"},
		"range backwards":    {"conf": "dhcp-range=192.0.2.9,192.0.2.1\n", "leases": ""},
		"range across":       {"conf": "dhcp-range=192.0.2.1,2001:db8::1\n", "leases": ""},
		"range of tags only": {"conf": "dhcp-range=tag:lan,set:x\n", "leases": ""},
		"relative conf-dir":  {"conf": "conf-dir=dnsmasq.d\n", "leases": ""},
		"relative conf-file": {"conf": "conf-file=extra.conf\n", "leases": ""},
		"relative leasefile": {"conf": "dhcp-leasefile=leases\n", "leases": ""},
		"conf-file loop":     {"conf": "conf-file=$DIR/conf\n", "leases": ""},
	} {
		t.Run(name, func(t *testing.T) {
			stubDnsmasq(t, files)
			_, err := dnsmasqLeaseView(context.Background(), Target{})
			if err == nil {
				t.Fatal("no error")
			}
			if strings.Contains(err.Error(), "192.0.2") || strings.Contains(err.Error(), "dnsmasq.d") {
				t.Errorf("error %q quotes the configuration", err)
			}
		})
	}
	stubDnsmasq(t, map[string]string{})
	if _, err := dnsmasqLeaseView(context.Background(), Target{}); !errors.Is(err, ErrUnsupported) {
		t.Errorf("error %v, want ErrUnsupported", err)
	}
}

func TestTheDHCPViewsAreViewsOfUnits(t *testing.T) {
	for _, view := range []string{"kea_pools", "dnsmasq_leases"} {
		if v, ok := appViews[view]; !ok || !unitView(v) {
			t.Errorf("view %s: %v, want a view of a unit", view, v)
		}
	}
}
