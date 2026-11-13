// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package probe

import (
	"context"
	"errors"
	"fmt"
	"net"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
	"time"
)

// openvpnDir points openvpnStatusDir at a directory of the test and returns it.
func openvpnDir(t *testing.T) string {
	t.Helper()
	old := openvpnStatusDir
	openvpnStatusDir = t.TempDir()
	t.Cleanup(func() { openvpnStatusDir = old })
	return openvpnStatusDir
}

func writeFile(t *testing.T, path, content string) {
	t.Helper()
	if err := os.WriteFile(path, []byte(content), 0o600); err != nil {
		t.Fatal(err)
	}
}

var serverUnit = Target{Kind: kindUnit, Name: "openvpn-server@server.service"}

// openvpnV2 is a status file of version 2 as openvpn-server@.service has the server write it.
func openvpnV2(sep string, written time.Time, clients ...string) string {
	j := func(cells ...string) string { return strings.Join(cells, sep) + "\n" }
	s := j("TITLE", "OpenVPN 2.6.14 x86_64-pc-linux-gnu")
	s += j("TIME", written.Format("2006-01-02 15:04:05"), fmt.Sprint(written.Unix()))
	s += j("HEADER", "CLIENT_LIST", "Common Name", "Real Address", "Virtual Address")
	for i, c := range clients {
		s += j("CLIENT_LIST", c, fmt.Sprintf("198.51.100.%d:1194", i+7), fmt.Sprintf("10.8.0.%d", i+2))
	}
	s += j("HEADER", "ROUTING_TABLE", "Virtual Address", "Common Name")
	for i, c := range clients {
		s += j("ROUTING_TABLE", fmt.Sprintf("10.8.0.%d", i+2), c)
	}
	s += j("GLOBAL_STATS", "Max bcast/mcast queue length", "0")
	return s + "END\n"
}

func TestOpenVPNStatusCountsClientsOfVersion2And3(t *testing.T) {
	stubNow(t, netNow)
	for _, sep := range []string{",", "\t"} {
		writeFile(t, filepath.Join(openvpnDir(t), "status-server.log"),
			openvpnV2(sep, netNow.Add(-90*time.Second), "alice-laptop", "bob-phone"))
		values, err := openvpnStatus(context.Background(), serverUnit)
		if err != nil {
			t.Fatalf("sep %q: %v", sep, err)
		}
		if want := map[string]any{"clients": 2, "updated_age_s": int64(90)}; !reflect.DeepEqual(values, want) {
			t.Errorf("sep %q: values %v, want %v", sep, values, want)
		}
		noneOf(t, values, "alice", "bob", "198.51.100", "10.8.0")
	}
}

func TestOpenVPNStatusOfVersion1TakesTheFileTime(t *testing.T) {
	stubNow(t, netNow)
	path := filepath.Join(openvpnDir(t), "status-server.log")
	writeFile(t, path, "OpenVPN CLIENT LIST\nUpdated,Fri Nov 13 11:58:00 2026\n"+
		"Common Name,Real Address,Bytes Received,Bytes Sent,Connected Since\n"+
		"alice-laptop,198.51.100.7:1194,100,200,Fri Nov 13 10:00:00 2026\n"+
		"ROUTING TABLE\nVirtual Address,Common Name,Real Address,Last Ref\n"+
		"10.8.0.2,alice-laptop,198.51.100.7:1194,Fri Nov 13 11:57:00 2026\n"+
		"GLOBAL STATS\nMax bcast/mcast queue length,0\nEND\n")
	if err := os.Chtimes(path, netNow, netNow.Add(-2*time.Minute)); err != nil {
		t.Fatal(err)
	}
	values, err := openvpnStatus(context.Background(), serverUnit)
	if err != nil {
		t.Fatal(err)
	}
	if want := map[string]any{"clients": 1, "updated_age_s": int64(120)}; !reflect.DeepEqual(values, want) {
		t.Errorf("values %v, want %v", values, want)
	}
}

func TestOpenVPNStatusOfNoClients(t *testing.T) {
	stubNow(t, netNow)
	writeFile(t, filepath.Join(openvpnDir(t), "status-server.log"), openvpnV2(",", netNow))
	values, err := openvpnStatus(context.Background(), serverUnit)
	if err != nil {
		t.Fatal(err)
	}
	if want := map[string]any{"clients": 0, "updated_age_s": int64(0)}; !reflect.DeepEqual(values, want) {
		t.Errorf("values %v, want %v", values, want)
	}
}

func TestOpenVPNStatusReadsOnlyTheFileOfTheUnitsInstance(t *testing.T) {
	openvpnDir(t)
	for name, want := range map[string]error{
		"openvpn-client@home.service": ErrUnsupported,
		"openvpn.service":             ErrUnsupported,
		"openvpn-server@.service":     ErrInvalid,
		"openvpn-server@../x.service": ErrInvalid,
		"openvpn-server@a/b.service":  ErrInvalid,
		"openvpn-server@.hidden":      ErrInvalid,
	} {
		if _, err := openvpnStatus(context.Background(), Target{Kind: kindUnit, Name: name}); !errors.Is(err, want) {
			t.Errorf("unit %s: error %v, want %v", name, err, want)
		}
	}
}

func TestOpenVPNStatusFailsWhatItCannotRead(t *testing.T) {
	stubNow(t, netNow)
	full := openvpnV2(",", netNow, "alice-laptop")
	for name, content := range map[string]string{
		"being written": strings.TrimSuffix(full, "END\n"),
		"without time":  strings.Replace(full, "TIME,", "TOME,", 1),
		"bad time":      strings.Replace(full, fmt.Sprint(netNow.Unix()), "soon", 1),
		"of client":     "OpenVPN STATISTICS\nUpdated,now\nEND\n",
		"v1 cut":        "OpenVPN CLIENT LIST\nCommon Name,Real Address\nalice-laptop,198.51.100.7:1194\n",
		"too large":     strings.Repeat("x", maxOpenVPNStatusBytes+1),
	} {
		writeFile(t, filepath.Join(openvpnDir(t), "status-server.log"), content)
		_, err := openvpnStatus(context.Background(), serverUnit)
		if err == nil {
			t.Errorf("%s: no error", name)
			continue
		}
		if strings.Contains(err.Error(), "alice") || strings.Contains(err.Error(), "198.51.100") {
			t.Errorf("%s: error %q quotes the file", name, err)
		}
	}
	openvpnDir(t)
	if _, err := openvpnStatus(context.Background(), serverUnit); err == nil || errors.Is(err, ErrUnsupported) {
		t.Errorf("without a status file: error %v, want a failure", err)
	}
}

// keepalivedFiles points keepalivedConf at a file of the test with content and stubs the addresses of
// this host.
func keepalivedFiles(t *testing.T, content string, own ...string) string {
	t.Helper()
	dir := t.TempDir()
	old, oldAddrs := keepalivedConf, interfaceAddrs
	keepalivedConf = filepath.Join(dir, "keepalived.conf")
	t.Cleanup(func() { keepalivedConf, interfaceAddrs = old, oldAddrs })
	var addrs []net.Addr
	for _, o := range own {
		_, n, err := net.ParseCIDR(o)
		ip, _, _ := net.ParseCIDR(o)
		if err != nil {
			t.Fatal(err)
		}
		addrs = append(addrs, &net.IPNet{IP: ip, Mask: n.Mask})
	}
	interfaceAddrs = func() ([]net.Addr, error) { return addrs, nil }
	writeFile(t, keepalivedConf, content)
	return dir
}

const keepalivedSecret = "s3cr3tPw"

// keepalivedTwoInstances is a configuration of two VRRP instances with four distinct virtual
// addresses, one of them in both, and options, comments and a password around them.
var keepalivedTwoInstances = `! Configuration File for keepalived
global_defs {
   router_id lb-one # the name
}
vrrp_instance VI_1 {
    state MASTER
    interface eth0
    virtual_router_id 51
    authentication {
        auth_type PASS
        auth_pass ` + keepalivedSecret + `
    }
    virtual_ipaddress {
        192.0.2.10/24 dev eth0 label eth0:1
        192.0.2.11
    }
    virtual_ipaddress_excluded
    {
        2001:db8::10/64
    }
}
vrrp_instance VI_2 {
    interface eth1
    virtual_ipaddress { 203.0.113.5/24 }
    virtual_ipaddress {
        192.0.2.11 # also in VI_1
    }
}
`

func TestKeepalivedVIPsCountsTheAddressesThisHostHolds(t *testing.T) {
	keepalivedFiles(t, keepalivedTwoInstances, "192.0.2.2/24", "192.0.2.10/24", "2001:db8::10/64", "127.0.0.1/8")
	values, err := keepalivedVIPs(context.Background(), Target{Kind: kindUnit, Name: "keepalived.service"})
	if err != nil {
		t.Fatal(err)
	}
	if want := map[string]any{"vips": 4, "held": 2}; !reflect.DeepEqual(values, want) {
		t.Errorf("values %v, want %v", values, want)
	}
	noneOf(t, values, keepalivedSecret, "192.0.2", "2001:db8", "203.0.113", "VI_1", "eth0")
}

func TestKeepalivedVIPsOfABackupHoldsNone(t *testing.T) {
	keepalivedFiles(t, keepalivedTwoInstances, "192.0.2.3/24")
	values, err := keepalivedVIPs(context.Background(), Target{Kind: kindUnit, Name: "keepalived.service"})
	if err != nil {
		t.Fatal(err)
	}
	if want := map[string]any{"vips": 4, "held": 0}; !reflect.DeepEqual(values, want) {
		t.Errorf("values %v, want %v", values, want)
	}
}

func TestKeepalivedVIPsFollowsAbsoluteIncludes(t *testing.T) {
	dir := keepalivedFiles(t, "", "198.51.100.20/24")
	confd := filepath.Join(dir, "conf.d")
	if err := os.Mkdir(confd, 0o700); err != nil {
		t.Fatal(err)
	}
	writeFile(t, keepalivedConf, "global_defs {\n}\ninclude "+filepath.Join(confd, "*.conf")+"\n")
	writeFile(t, filepath.Join(confd, "a.conf"), "vrrp_instance A {\n virtual_ipaddress {\n  198.51.100.20\n }\n}\n")
	writeFile(t, filepath.Join(confd, "b.conf"), "vrrp_instance B {\n virtual_ipaddress {\n  198.51.100.21\n }\n}\n")
	writeFile(t, filepath.Join(confd, "c.txt"), "vrrp_instance C {\n virtual_ipaddress {\n  198.51.100.22\n }\n}\n")
	values, err := keepalivedVIPs(context.Background(), Target{Kind: kindUnit, Name: "keepalived.service"})
	if err != nil {
		t.Fatal(err)
	}
	if want := map[string]any{"vips": 2, "held": 1}; !reflect.DeepEqual(values, want) {
		t.Errorf("values %v, want %v", values, want)
	}
}

func TestKeepalivedVIPsIsUnsupportedWithoutAConfiguration(t *testing.T) {
	keepalivedFiles(t, "")
	if err := os.Remove(keepalivedConf); err != nil {
		t.Fatal(err)
	}
	if _, err := keepalivedVIPs(context.Background(), Target{Kind: kindUnit, Name: "keepalived.service"}); !errors.Is(err, ErrUnsupported) {
		t.Errorf("error %v, want %v", err, ErrUnsupported)
	}
}

func TestKeepalivedVIPsFailsWithoutQuotingTheConfiguration(t *testing.T) {
	block := func(entry string) string {
		return "vrrp_instance VI_1 {\n auth_pass " + keepalivedSecret + "\n virtual_ipaddress {\n  " + entry + "\n }\n}\n"
	}
	cases := map[string]string{
		"a name":          block(keepalivedSecret),
		"a range":         block("192.0.2.10-20"),
		"a zone":          block("fe80::1%eth0"),
		"a nested block":  block("{ 192.0.2.10 }"),
		"no end":          "vrrp_instance VI_1 {\n auth_pass " + keepalivedSecret + "\n virtual_ipaddress {\n  192.0.2.10\n",
		"no block":        "virtual_ipaddress 192.0.2.10\n auth_pass " + keepalivedSecret + "\n",
		"relative":        "include " + keepalivedSecret + ".conf\n",
		"no include file": "include\n",
		"too large":       strings.Repeat("#", maxKeepalivedBytes+1),
	}
	for name, content := range cases {
		dir := keepalivedFiles(t, content)
		_, err := keepalivedVIPs(context.Background(), Target{Kind: kindUnit, Name: "keepalived.service"})
		if err == nil {
			t.Errorf("%s: no error", name)
			continue
		}
		if strings.Contains(err.Error(), keepalivedSecret) || strings.Contains(err.Error(), dir) {
			t.Errorf("%s: error %q quotes the configuration", name, err)
		}
	}
	// An include of itself ends at the cap instead of looping.
	keepalivedFiles(t, "")
	writeFile(t, keepalivedConf, "include "+keepalivedConf+"\n")
	if _, err := keepalivedVIPs(context.Background(), Target{Kind: kindUnit, Name: "keepalived.service"}); err == nil {
		t.Error("an include of itself: no error")
	}
}

func TestTheVPNViewsAreViewsOfUnits(t *testing.T) {
	for _, view := range []string{"openvpn_status", "keepalived_vips"} {
		if v, ok := appViews[view]; !ok || !unitView(v) {
			t.Errorf("view %s: %v, want a view of a unit", view, v)
		}
	}
}
