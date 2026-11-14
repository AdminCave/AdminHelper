// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package probe

import (
	"context"
	"errors"
	"fmt"
	"os/exec"
	"strings"
)

// serviceConfigTests are the configuration tests of the services by their unit (Debian and RHEL
// package names). Each reads the configuration at its default place and starts nothing:
//   - named-checkconf without -z checks the syntax of named.conf and loads no zone (BIND 9 ARM);
//   - unbound-checkconf checks the configuration file at the default location (unbound-checkconf(8));
//   - keepalived --config-test checks the configuration and exits, diagnostics to stderr unless a
//     file is named (keepalived(8));
//   - squid -k parse parses the configuration and exits; every other -k action, check among them,
//     signals the running copy (squid(8));
//   - fail2ban-client --test tests the configuration (fail2ban-client(1));
//   - dnsmasq --test syntax-checks the configuration files and does not start up dnsmasq (dnsmasq(8)).
var serviceConfigTests = map[string][]string{
	"named":      {"named-checkconf"},
	"bind9":      {"named-checkconf"},
	"unbound":    {"unbound-checkconf"},
	"keepalived": {"keepalived", "--config-test"},
	"squid":      {"squid", "-k", "parse"},
	"fail2ban":   {"fail2ban-client", "--test"},
	"dnsmasq":    {"dnsmasq", "--test"},
}

// serviceConfig runs the configuration test of the service of the unit and reports whether its
// configuration loads (config_ok), never what the test prints: that names files, lines and
// directives. A failed test is a value, as for web_config: the next restart or reload would fail on
// it while the running service goes on. Any exit but 0 counts as failed, also the codes keepalived
// keeps for a configuration it would still run with (4) or with scripts but no script security (5).
func serviceConfig(ctx context.Context, t Target) (map[string]any, error) {
	call, ok := serviceConfigTests[strings.TrimSuffix(t.Name, ".service")]
	if !ok {
		return nil, fmt.Errorf("%w: unit %s runs no service the view knows", ErrUnsupported, t.Name)
	}
	_, err := runTool(ctx, toolTimeout, call[0], call[1:]...)
	var exitErr *exec.ExitError
	switch {
	case err == nil:
		return map[string]any{"config_ok": true}, nil
	case errors.Is(err, exec.ErrNotFound):
		return nil, fmt.Errorf("%w: %s is not installed", ErrUnsupported, call[0])
	case ctx.Err() != nil:
		return nil, ctx.Err()
	case errors.As(err, &exitErr):
		return map[string]any{"config_ok": false}, nil
	}
	return nil, fmt.Errorf("%s: %w", call[0], err)
}
