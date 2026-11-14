// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package probe

import (
	"context"
	"errors"
	"strings"
	"testing"

	"adminhelper-agent/internal/allowlist"
)

func TestServiceConfigRunsTheTestOfTheServiceOfTheUnit(t *testing.T) {
	for unit, want := range map[string][]string{
		"named.service":      {"named-checkconf"},
		"bind9.service":      {"named-checkconf"},
		"unbound.service":    {"unbound-checkconf"},
		"keepalived.service": {"keepalived", "--config-test"},
		"squid.service":      {"squid", "-k", "parse"},
		"fail2ban.service":   {"fail2ban-client", "--test"},
		"dnsmasq":            {"dnsmasq", "--test"},
	} {
		calls := stubTools(t, answer{out: "OK\n/etc/secret/path.conf\n"})
		got, err := serviceConfig(context.Background(), webUnit(unit))
		if err != nil || got["config_ok"] != true || len(got) != 1 {
			t.Errorf("%s = %v, %v; want config_ok alone", unit, got, err)
		}
		if len(*calls) != 1 || strings.Join((*calls)[0], " ") != strings.Join(want, " ") {
			t.Errorf("%s ran %q, want %q", unit, *calls, want)
		}
	}
}

// Every call the view makes must pass the allowlist, or the view fails on every host.
func TestServiceConfigTestsAreOnTheAllowlist(t *testing.T) {
	for unit, call := range serviceConfigTests {
		if !allowlist.Allowed(call[0], call[1:]) {
			t.Errorf("%s: %q is not on the allowlist", unit, call)
		}
	}
}

func TestAFailedServiceConfigTestIsAValueWithoutItsText(t *testing.T) {
	// keepalived exits 4 for a configuration it would still run with after changing it: failed too.
	for _, code := range []int{1, 3, 4, 5} {
		fail := toolExit(t, code, "Keepalived_vrrp: (/etc/keepalived/secret.conf: Line 12) Unknown keyword 'vrrp_instanse'")
		stubTools(t, answer{err: fail})
		got, err := serviceConfig(context.Background(), webUnit("keepalived.service"))
		if err != nil || got["config_ok"] != false || len(got) != 1 {
			t.Fatalf("exit %d: service_config = %v, %v; want config_ok false alone", code, got, err)
		}
		noneOf(t, got, "secret", "vrrp_instanse", "/etc/keepalived")
	}
}

func TestServiceConfigWithoutTheServiceOrForAnotherUnit(t *testing.T) {
	stubTools(t, answer{err: notInstalled("named-checkconf")})
	if _, err := serviceConfig(context.Background(), webUnit("named.service")); !errors.Is(err, ErrUnsupported) {
		t.Errorf("named-checkconf not installed = %v, want ErrUnsupported", err)
	}

	calls := stubTools(t)
	for _, unit := range []string{"nginx.service", "kea-dhcp4-server.service", "squid-exporter.service", "named-resolvconf.service", ""} {
		if _, err := serviceConfig(context.Background(), webUnit(unit)); !errors.Is(err, ErrUnsupported) {
			t.Errorf("%q = %v, want ErrUnsupported", unit, err)
		}
	}
	if len(*calls) != 0 {
		t.Errorf("ran %q, want nothing", *calls)
	}
}

func TestTheServiceConfigViewIsAViewOfUnits(t *testing.T) {
	v, ok := appViews["service_config"]
	if !ok || v.read == nil || len(v.kinds) != 1 || v.kinds[0] != kindUnit {
		t.Fatalf("appViews[service_config] = %+v, %v; want a read of units", v, ok)
	}
}
