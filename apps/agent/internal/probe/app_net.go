// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package probe

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"math"
	"os/exec"
	"strconv"
	"strings"
	"time"
)

const (
	// wgStaleWarn and wgStaleCrit are the ages of a peer's last handshake past which it counts as
	// stale. WireGuard renews a session's keys every two minutes while packets flow (REKEY_AFTER_TIME,
	// 120 s), so a peer with a persistent keepalive handshakes at least that often.
	wgStaleWarn = 300 * time.Second
	wgStaleCrit = 900 * time.Second
	// maxJails caps the jails the fail2ban view reads, one call of fail2ban-client per jail.
	maxJails = 32
	// bouncerStale is the age of a bouncer's last pull past which it counts as stale.
	bouncerStale = 10 * time.Minute
)

// runAppTool runs a read command of a view through the allowlist; a tool that is not installed makes
// the view unsupported on this host.
func runAppTool(ctx context.Context, name string, args ...string) ([]byte, error) {
	out, err := runTool(ctx, toolTimeout, name, args...)
	switch {
	case errors.Is(err, exec.ErrNotFound):
		return nil, fmt.Errorf("%w: %s is not installed", ErrUnsupported, name)
	case err != nil:
		return nil, toolError(name, err)
	}
	return out, nil
}

// wgPeers counts the WireGuard peers of this host and how long ago they last completed a handshake.
// The target unit wg-quick@<if> narrows it to that interface; another unit (systemd-networkd, a
// unit of one's own) counts every interface. Stale are only peers with a persistent keepalive: a
// peer without one handshakes only while it sends, so a road warrior that sleeps is no fault. It
// asks wg(8) for the handshake times and the keepalive intervals alone, never `wg show … dump` or
// `wg showconf`, which print the private key, and it reports no key and no endpoint.
//
// wg(8): `wg show all latest-handshakes` prints "<interface>\t<public key>\t<unix seconds>", 0 for a
// peer that never completed one; `wg show all persistent-keepalive` prints "<interface>\t<public
// key>\t<seconds>" or "off".
func wgPeers(ctx context.Context, t Target) (map[string]any, error) {
	iface, one := strings.CutPrefix(strings.TrimSuffix(t.Name, ".service"), "wg-quick@")
	handshakes, err := wgTable(ctx, "latest-handshakes", iface, one)
	if err != nil {
		return nil, err
	}
	keepalives, err := wgTable(ctx, "persistent-keepalive", iface, one)
	if err != nil {
		return nil, err
	}
	if one && len(handshakes) == 0 && len(keepalives) == 0 {
		return nil, fmt.Errorf("wg: interface %s is not up", iface)
	}
	interfaces := map[string]bool{}
	values := map[string]any{"peers": 0, "keepalive_peers": 0, "stale_warn": 0, "stale_crit": 0}
	maxAge := -1
	for peer, at := range handshakes {
		interfaces[peer.iface] = true
		values["peers"] = values["peers"].(int) + 1
		every := keepalives[peer]
		if every == "off" || every == "0" || every == "" {
			continue
		}
		values["keepalive_peers"] = values["keepalive_peers"].(int) + 1
		age := wgStaleCrit + time.Second
		if at != "0" {
			s, err := strconv.ParseInt(at, 10, 64)
			if err != nil || s < 0 {
				return nil, errors.New("wg: a handshake time of another form")
			}
			age = max(now().Sub(time.Unix(s, 0)), 0)
			maxAge = max(maxAge, int(age.Seconds()))
		}
		switch {
		case age > wgStaleCrit:
			values["stale_crit"] = values["stale_crit"].(int) + 1
		case age > wgStaleWarn:
			values["stale_warn"] = values["stale_warn"].(int) + 1
		}
	}
	for peer := range keepalives {
		interfaces[peer.iface] = true
	}
	values["interfaces"] = len(interfaces)
	if maxAge >= 0 {
		values["max_handshake_age_s"] = maxAge
	}
	return values, nil
}

// wgPeer is one peer of one interface.
type wgPeer struct{ iface, key string }

// wgTable reads one table of `wg show all <what>`, the third column per peer, of the interface iface
// alone if one.
func wgTable(ctx context.Context, what, iface string, one bool) (map[wgPeer]string, error) {
	out, err := runAppTool(ctx, "wg", "show", "all", what)
	if err != nil {
		return nil, err
	}
	table := map[wgPeer]string{}
	for line := range strings.Lines(string(out)) {
		cells := strings.Split(strings.TrimRight(line, "\n"), "\t")
		if len(cells) != 3 || cells[0] == "" || cells[1] == "" {
			return nil, errors.New("wg: a line of another form")
		}
		if !one || cells[0] == iface {
			table[wgPeer{cells[0], cells[1]}] = cells[2]
		}
	}
	return table, nil
}

// fail2ban reads whether the fail2ban server answers and, per jail, how many addresses it bans and
// whether it watches any log file. A server that does not answer is a value (responding false), not
// an error. It asks fail2ban-client for ping and status alone, never unban, reload or set, and reads
// of `status <jail>` only the counts and whether the file list is empty: never the banned addresses.
//
// fail2ban's client/beautifier.py prints each status entry as "<prefix> <label>:\t<value>", a list
// value joined by spaces; server/actions.py names "Currently banned", server/filter.py's FileFilter
// "File list" (a journal backend has none). The jail list is joined by ", ".
func fail2ban(ctx context.Context, _ Target) (map[string]any, error) {
	if _, err := runTool(ctx, toolTimeout, "fail2ban-client", "ping"); err != nil {
		switch {
		case errors.Is(err, exec.ErrNotFound):
			return nil, fmt.Errorf("%w: fail2ban-client is not installed", ErrUnsupported)
		case ctx.Err() != nil:
			return nil, ctx.Err()
		}
		return map[string]any{"responding": false}, nil
	}
	out, err := runAppTool(ctx, "fail2ban-client", "status")
	if err != nil {
		return nil, err
	}
	list, ok := fail2banEntries(out)["Jail list"]
	if !ok {
		return nil, errors.New("fail2ban-client: a status of another form")
	}
	jails := strings.FieldsFunc(list, func(r rune) bool { return r == ',' || r == ' ' || r == '\t' })
	if len(jails) > maxJails {
		return nil, fmt.Errorf("fail2ban-client: more than %d jails", maxJails)
	}
	values := map[string]any{"responding": true, "jails": len(jails), "banned_total": 0, "max_banned": 0,
		"jails_without_files": 0}
	for _, jail := range jails {
		out, err := runAppTool(ctx, "fail2ban-client", "status", jail)
		if err != nil {
			return nil, err
		}
		entries := fail2banEntries(out)
		banned, err := strconv.Atoi(entries["Currently banned"])
		if err != nil || banned < 0 {
			return nil, errors.New("fail2ban-client: a jail status of another form")
		}
		values["banned_total"] = values["banned_total"].(int) + banned
		values["max_banned"] = max(values["max_banned"].(int), banned)
		if files, ok := entries["File list"]; ok && files == "" {
			values["jails_without_files"] = values["jails_without_files"].(int) + 1
		}
	}
	return values, nil
}

// fail2banEntries reads the entries of a status of fail2ban-client by their label; the values of the
// labels the view does not ask for stay unread.
func fail2banEntries(out []byte) map[string]string {
	entries := map[string]string{}
	for line := range strings.Lines(string(out)) {
		label, value, ok := strings.Cut(strings.TrimRight(line, "\n"), ":\t")
		if !ok {
			continue
		}
		label = strings.TrimLeft(label, " |`-")
		if label == "Jail list" || label == "Currently banned" || label == "File list" {
			entries[label] = strings.TrimSpace(value)
		}
	}
	return entries
}

// crowdsecBouncers counts the bouncers registered with the local CrowdSec API that are not revoked,
// and how many of them have not pulled decisions for bouncerStale or never did. It reports no name,
// address or version of a bouncer.
//
// `cscli bouncers list -o json` prints the bouncer records as a JSON array (null for none); last_pull
// is a Go *time.Time, so RFC 3339 or null.
func crowdsecBouncers(ctx context.Context, _ Target) (map[string]any, error) {
	out, err := runAppTool(ctx, "cscli", "bouncers", "list", "-o", "json")
	if err != nil {
		return nil, err
	}
	var list []struct {
		Revoked  bool       `json:"revoked"`
		LastPull *time.Time `json:"last_pull"`
	}
	if err := json.Unmarshal(out, &list); err != nil {
		return nil, errors.New("cscli: an answer of another form")
	}
	bouncers, stale, maxAge := 0, 0, -1
	for _, b := range list {
		if b.Revoked {
			continue
		}
		bouncers++
		if b.LastPull == nil {
			stale++
			continue
		}
		age := max(now().Sub(*b.LastPull), 0)
		maxAge = max(maxAge, int(age.Seconds()))
		if age > bouncerStale {
			stale++
		}
	}
	values := map[string]any{"bouncers": bouncers, "stale_bouncers": stale}
	if maxAge >= 0 {
		values["max_pull_age_s"] = maxAge
	}
	return values, nil
}

// tailscaleStatus reads whether tailscaled is connected, how many health warnings it has and in how
// many days the node key expires (absent when expiry is off). It asks without peers (--peers=false)
// and reports no address, name or key.
//
// cmd/tailscale/cli/status.go marshals an ipnstate.Status: "BackendState" (Running when connected),
// "Health" ([]string), "Self"."KeyExpiry" (*time.Time, omitted when nil).
func tailscaleStatus(ctx context.Context, _ Target) (map[string]any, error) {
	out, err := runAppTool(ctx, "tailscale", "status", "--json", "--peers=false")
	if err != nil {
		return nil, err
	}
	var st struct {
		BackendState string
		Health       []string
		Self         *struct{ KeyExpiry *time.Time }
	}
	if err := json.Unmarshal(out, &st); err != nil || st.BackendState == "" {
		return nil, errors.New("tailscale: an answer of another form")
	}
	values := map[string]any{"backend_running": st.BackendState == "Running", "health_warnings": len(st.Health)}
	if st.Self != nil && st.Self.KeyExpiry != nil {
		values["key_expiry_days"] = int(math.Floor(st.Self.KeyExpiry.Sub(now()).Hours() / 24))
	}
	return values, nil
}
