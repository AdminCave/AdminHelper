// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package opnsense

import (
	"bytes"
	"encoding/json"
	"errors"
	"math"
	"os"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"time"
	"unicode/utf8"
)

// errForm is every parser's answer to an output it does not know. configd prints its own failures
// ("Action not found", "Execute error") on stdout with exit 0, and a script changed by an OPNsense
// update must end in an error, not in wrong numbers.
var errForm = errors.New("unexpected output form")

// maxTextRunes matches the cut the monitoring service applies to a text field.
const maxTextRunes = 256

type serviceEntry struct {
	Name    *string         `json:"name"`
	Status  *string         `json:"status"`
	ID      json.RawMessage `json:"id"`
	Nocheck json.RawMessage `json:"nocheck"`
}

// parseServices reads `service list` (pluginctl -S): a JSON list of the registered services, each
// with the rc-style status line "<name> is running as pid N." or "<name> is not running.".
func parseServices(_ Reader, outs [][]byte) (map[string]any, error) {
	var entries []serviceEntry
	if err := decodeInto(outs[0], '[', &entries); err != nil {
		return nil, err
	}
	total := 0
	var stopped []string
	for _, e := range entries {
		if e.Name == nil || *e.Name == "" || e.Status == nil {
			return nil, errForm
		}
		// A nocheck service has no process to look for; pluginctl reports it as running anyway.
		if truthy(e.Nocheck) {
			continue
		}
		total++
		// The GUI's ServiceController::searchAction decides "running" with the same substring.
		if !strings.Contains(*e.Status, "is running") {
			stopped = append(stopped, serviceName(*e.Name, e.ID))
		}
	}
	return map[string]any{
		"total":         total,
		"running":       total - len(stopped),
		"stopped":       len(stopped),
		"stopped_names": joinNames(stopped),
	}, nil
}

type gatewayEntry struct {
	Status *string `json:"status"`
	Loss   *string `json:"loss"`
	Delay  *string `json:"delay"`
}

// parseGateways reads `interface gateways status` (gateway_status.php): an object keyed by gateway
// name, or [] without gateways. status is dpinger's verdict against the gateway's own thresholds;
// loss and delay are "0.0 %" and "1.2 ms", or "~" while nothing was measured. A gateway without
// monitoring is not counted, as a service without a process check is not.
func parseGateways(_ Reader, outs [][]byte) (map[string]any, error) {
	gateways := map[string]gatewayEntry{}
	if !emptyPHPArray(outs[0]) {
		if err := decodeInto(outs[0], '{', &gateways); err != nil {
			return nil, err
		}
	}
	var down, degraded []string
	total, forced := 0, 0
	var maxLoss, maxDelay float64
	measured := false
	for name, g := range gateways {
		if g.Status == nil || g.Loss == nil || g.Delay == nil {
			return nil, errForm
		}
		loss, lossOK, err := measurement(*g.Loss, " %")
		if err != nil {
			return nil, err
		}
		delay, delayOK, err := measurement(*g.Delay, " ms")
		if err != nil {
			return nil, err
		}
		switch *g.Status {
		case "none":
			// StaticRoute::getMonitorStatus starts a monitored gateway at "down" and only a gateway
			// with monitoring disabled at "none", so "none" without a measurement is unmonitored.
			if !lossOK && !delayOK {
				continue
			}
		case "force_down":
			// Taken down by the admin on purpose: counted, but not as a failure.
			forced++
		case "down":
			down = append(down, name)
		case "delay", "loss", "delay+loss":
			degraded = append(degraded, name)
		default:
			return nil, errForm
		}
		total++
		if lossOK || delayOK {
			measured = true
			maxLoss = math.Max(maxLoss, loss)
			maxDelay = math.Max(maxDelay, delay)
		}
	}
	fields := map[string]any{
		"total":          total,
		"down":           len(down),
		"degraded":       len(degraded),
		"forced_down":    forced,
		"down_names":     joinNames(down),
		"degraded_names": joinNames(degraded),
	}
	if measured {
		fields["max_loss_pct"] = maxLoss
		fields["max_delay_ms"] = maxDelay
	}
	return fields, nil
}

type productInfo struct {
	Version *string       `json:"product_version"`
	Latest  *string       `json:"product_latest"`
	Check   *upgradeCheck `json:"product_check"`
}

type upgradeCheck struct {
	Connection   *string           `json:"connection"`
	Repository   *string           `json:"repository"`
	NeedsReboot  json.RawMessage   `json:"needs_reboot"`
	MajorVersion string            `json:"upgrade_major_version"`
	New          []json.RawMessage `json:"new_packages"`
	Reinstall    []json.RawMessage `json:"reinstall_packages"`
	Upgrade      []json.RawMessage `json:"upgrade_packages"`
	Downgrade    []json.RawMessage `json:"downgrade_packages"`
	Remove       []json.RawMessage `json:"remove_packages"`
}

// parseFirmware reads `firmware product` (product.php): the installed version, the newest version
// the local changelog knows and, as product_check, the result of the last update check, which
// product.php reads from pkgUpgradeFile without contacting a mirror. The output also carries the
// mirror URL and, on business editions, license data: only the fields named here leave the box.
func parseFirmware(r Reader, outs [][]byte) (map[string]any, error) {
	var p productInfo
	if err := decodeInto(outs[0], '{', &p); err != nil {
		return nil, err
	}
	if p.Version == nil || *p.Version == "" || p.Latest == nil {
		return nil, errForm
	}
	fields := map[string]any{
		"version": cut(*p.Version),
		"checked": p.Check != nil,
	}
	if *p.Latest != "" {
		fields["latest"] = cut(*p.Latest)
	}
	if p.Check == nil {
		return fields, nil
	}
	c := p.Check
	if c.Connection == nil || c.Repository == nil {
		return nil, errForm
	}
	// The GUI's FirmwareController counts the same five lists as "updates available"; a reboot
	// flag only matters with an update to apply (it is also set when the admin asks to always
	// reboot after updates).
	updates := len(c.New) + len(c.Reinstall) + len(c.Upgrade) + len(c.Downgrade) + len(c.Remove)
	fields["connection"] = cut(*c.Connection)
	fields["repository"] = cut(*c.Repository)
	fields["updates"] = updates
	fields["update_available"] = updates > 0
	fields["update_reboot"] = updates > 0 && truthy(c.NeedsReboot)
	if c.MajorVersion != "" {
		fields["major_upgrade"] = cut(c.MajorVersion)
	}
	if age, ok := r.checkAge(); ok {
		fields["check_age_s"] = age
	}
	return fields, nil
}

// checkAge is the age of the last update check in whole seconds. check.sh writes last_check as
// the output of date(1) in the box's locale and zone; the file's mtime needs no parsing.
func (r Reader) checkAge() (int64, bool) {
	modTime := r.ModTime
	if modTime == nil {
		modTime = func(path string) (time.Time, error) {
			fi, err := os.Stat(path)
			if err != nil {
				return time.Time{}, err
			}
			return fi.ModTime(), nil
		}
	}
	now := time.Now
	if r.Now != nil {
		now = r.Now
	}
	mtime, err := modTime(pkgUpgradeFile)
	if err != nil {
		return 0, false
	}
	return max(int64(now().Sub(mtime)/time.Second), 0), true
}

// parseStates reads `filter diag state_size`: the line "current N" from pfctl -si and the line
// "limit N" from pfctl -s memory. The GUI's FirewallController::pfStatesAction takes the first of
// each, so this does too.
func parseStates(_ Reader, outs [][]byte) (map[string]any, error) {
	current, limit := -1, -1
	for line := range strings.SplitSeq(strings.TrimSpace(string(outs[0])), "\n") {
		parts := strings.Fields(line)
		if len(parts) != 2 {
			return nil, errForm
		}
		n, err := strconv.Atoi(parts[1])
		if err != nil || n < 0 {
			return nil, errForm
		}
		switch parts[0] {
		case "current":
			if current < 0 {
				current = n
			}
		case "limit":
			if limit < 0 {
				limit = n
			}
		default:
			return nil, errForm
		}
	}
	if current < 0 || limit <= 0 {
		return nil, errForm
	}
	return map[string]any{
		"current":  current,
		"limit":    limit,
		"used_pct": math.Round(float64(current)*1000/float64(limit)) / 10,
	}, nil
}

type carpGlobal struct {
	Demotion    json.RawMessage `json:"demotion"`
	Maintenance *bool           `json:"maintenancemode"`
}

type carpEntry struct {
	Status *string `json:"status"`
}

// parseCarp reads `interface show carp` (carp_global_status.php: the demotion sysctl as a string,
// maintenance mode as a bool) and `interface list ifconfig` (pluginctl -D: an object keyed by
// device whose "carp" member holds one entry per vhid, keyed by vhid). The state of each VIP comes
// from the second, as in the GUI's InterfaceController::getVipStatusAction.
func parseCarp(_ Reader, outs [][]byte) (map[string]any, error) {
	var global carpGlobal
	if err := decodeInto(outs[0], '{', &global); err != nil {
		return nil, err
	}
	demotion, err := intValue(global.Demotion)
	if err != nil || global.Maintenance == nil {
		return nil, errForm
	}
	devices := map[string]struct {
		Carp json.RawMessage `json:"carp"`
	}{}
	if !emptyPHPArray(outs[1]) {
		if err := decodeInto(outs[1], '{', &devices); err != nil {
			return nil, err
		}
	}
	counts := map[string]int{"MASTER": 0, "BACKUP": 0, "INIT": 0}
	vips := 0
	for _, d := range devices {
		entries, err := carpEntries(d.Carp)
		if err != nil {
			return nil, err
		}
		for _, e := range entries {
			if e.Status == nil {
				return nil, errForm
			}
			if _, ok := counts[*e.Status]; !ok {
				return nil, errForm
			}
			counts[*e.Status]++
			vips++
		}
	}
	return map[string]any{
		"vips":        vips,
		"master":      counts["MASTER"],
		"backup":      counts["BACKUP"],
		"init":        counts["INIT"],
		"demotion":    demotion,
		"maintenance": *global.Maintenance,
	}, nil
}

// carpEntries accepts the vhid-keyed object PHP emits and, should the keys ever become a dense
// 0..n list, the array json_encode turns that into.
func carpEntries(raw json.RawMessage) ([]carpEntry, error) {
	trimmed := bytes.TrimSpace(raw)
	if len(trimmed) == 0 || string(trimmed) == "null" {
		return nil, nil
	}
	if trimmed[0] == '[' {
		var list []carpEntry
		if err := json.Unmarshal(trimmed, &list); err != nil {
			return nil, errForm
		}
		return list, nil
	}
	byVhid := map[string]carpEntry{}
	if err := decodeInto(trimmed, '{', &byVhid); err != nil {
		return nil, err
	}
	list := make([]carpEntry, 0, len(byVhid))
	for _, e := range byVhid {
		list = append(list, e)
	}
	return list, nil
}

// decodeInto unmarshals out into v after checking its first byte: json.Unmarshal takes "null"
// for an empty list or object, which would read a configd failure as "nothing there".
func decodeInto(out []byte, first byte, v any) error {
	trimmed := bytes.TrimSpace(out)
	if len(trimmed) == 0 || trimmed[0] != first {
		return errForm
	}
	if err := json.Unmarshal(trimmed, v); err != nil {
		return errForm
	}
	return nil
}

// emptyPHPArray reports the "[]" PHP's json_encode writes for an empty associative array.
func emptyPHPArray(out []byte) bool {
	return string(bytes.TrimSpace(out)) == "[]"
}

// truthy is PHP's !empty() for the JSON forms a flag takes in OPNsense: true, 1, "1".
func truthy(raw json.RawMessage) bool {
	switch s := string(bytes.TrimSpace(raw)); s {
	case "", "null", "false", "0", `""`, `"0"`, "[]", "{}":
		return false
	default:
		return true
	}
}

// serviceName adds the instance id of a multi-instance service (OpenVPN, WireGuard) in the form
// OPNsense's own service_name() writes: openvpn[1].
func serviceName(name string, rawID json.RawMessage) string {
	var id string
	if err := json.Unmarshal(rawID, &id); err != nil {
		var n json.Number
		if json.Unmarshal(rawID, &n) != nil {
			return name
		}
		id = n.String()
	}
	return name + "[" + id + "]"
}

var integerText = regexp.MustCompile(`^-?[0-9]+$`)

// intValue reads a sysctl that PHP passes on as a string ("0") or, in other scripts, a number.
// net.inet.carp.demotion is a signed counter: writes add to it, and carp_set_status.php writes a
// negative difference to reset it.
func intValue(raw json.RawMessage) (int, error) {
	var s string
	if err := json.Unmarshal(raw, &s); err != nil {
		var n json.Number
		if err := json.Unmarshal(raw, &n); err != nil {
			return 0, errForm
		}
		s = n.String()
	}
	if !integerText.MatchString(s) {
		return 0, errForm
	}
	return strconv.Atoi(s)
}

var decimalText = regexp.MustCompile(`^[0-9]+(\.[0-9]+)?$`)

// measurement reads dpinger's "<n> %" or "<n> ms"; "~" means not measured.
func measurement(s, unit string) (float64, bool, error) {
	if s == "~" {
		return 0, false, nil
	}
	num, ok := strings.CutSuffix(s, unit)
	if !ok || !decimalText.MatchString(num) {
		return 0, false, errForm
	}
	v, err := strconv.ParseFloat(num, 64)
	if err != nil {
		return 0, false, errForm
	}
	return v, true, nil
}

// joinNames lists names sorted and comma-separated, cut to maxTextRunes with a trailing ellipsis.
func joinNames(names []string) string {
	sorted := append([]string(nil), names...)
	sort.Strings(sorted)
	return cut(strings.Join(sorted, ","))
}

func cut(s string) string {
	if utf8.RuneCountInString(s) <= maxTextRunes {
		return s
	}
	runes := []rune(s)
	return string(runes[:maxTextRunes-1]) + "…"
}
