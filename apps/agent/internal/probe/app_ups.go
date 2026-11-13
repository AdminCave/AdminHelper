// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package probe

import (
	"context"
	"errors"
	"fmt"
	"math"
	"os/exec"
	"regexp"
	"strconv"
	"strings"
)

// upsNamePattern is the form of a UPS name the agent passes to upsc, the allowlist class upsname: no
// leading '-', no '@' or ':', which would name another host or port.
var upsNamePattern = regexp.MustCompile(`^[A-Za-z0-9_][A-Za-z0-9._-]*$`)

// nutUPS reads the UPSes the local upsd serves: how many, how many run on battery, with a low battery,
// in forced shutdown, overloaded or with a battery to replace, how many upsd has no fresh data for,
// and the lowest runtime and charge among them. It only asks upsd on localhost, never another host,
// and sends no command (upscmd, upsrw and upsmon stay off the allowlist). No UPS name leaves it.
//
// upsc(8): `upsc -l localhost` lists one UPS name per line; `upsc <ups>@localhost` prints every
// variable as "name: value" (clients/upsc.c). It fails with exit status 1 and "Error: <text>", the
// text "Data stale" or "Driver not connected" when upsd has no fresh data (clients/upsclient.c).
// nut-names: battery.charge in percent, battery.runtime in seconds; ups.status space-separated tokens
// (developer guide "Status data": OB on battery, LB low battery, FSD forced shutdown, OVER overloaded,
// RB replace battery), unknown ones to be ignored.
func nutUPS(ctx context.Context, _ Target) (map[string]any, error) {
	out, err := runAppTool(ctx, "upsc", "-l", "localhost")
	if err != nil {
		return nil, err
	}
	var ups, onBattery, low, fsd, overload, replace, stale int
	minRuntime, minCharge := math.Inf(1), math.Inf(1)
	for name := range strings.FieldsSeq(string(out)) {
		if !upsNamePattern.MatchString(name) {
			return nil, errors.New("upsc: a UPS name of another form")
		}
		ups++
		vars, err := upsVars(ctx, name)
		if errors.Is(err, errUPSStale) {
			stale++
			continue
		}
		if err != nil {
			return nil, err
		}
		for token := range strings.FieldsSeq(vars["ups.status"]) {
			switch token {
			case "OB":
				onBattery++
			case "LB":
				low++
			case "FSD":
				fsd++
			case "OVER":
				overload++
			case "RB":
				replace++
			}
		}
		if v, ok, err := upsNumber(vars, "battery.runtime"); err != nil {
			return nil, err
		} else if ok {
			minRuntime = math.Min(minRuntime, v)
		}
		if v, ok, err := upsNumber(vars, "battery.charge"); err != nil {
			return nil, err
		} else if ok {
			minCharge = math.Min(minCharge, v)
		}
	}
	values := map[string]any{
		"ups": ups, "on_battery": onBattery, "low_battery": low, "fsd": fsd, "overload": overload,
		"replace_battery": replace, "stale": stale,
	}
	// A UPS that reports no runtime or charge (many drivers lack one) adds no value; without any the
	// field stays out, so a rule on it does not fire on a made-up zero.
	if !math.IsInf(minRuntime, 1) {
		values["min_runtime_s"] = int(minRuntime)
	}
	if !math.IsInf(minCharge, 1) {
		values["min_charge_pct"] = minCharge
	}
	return values, nil
}

// errUPSStale marks a UPS upsd has no fresh data for.
var errUPSStale = errors.New("upsc: data stale")

// upsVars are the variables of the UPS name upsd on localhost serves, only the three the view reads.
func upsVars(ctx context.Context, name string) (map[string]string, error) {
	out, err := runTool(ctx, toolTimeout, "upsc", name+"@localhost")
	if err != nil {
		var exitErr *exec.ExitError
		if errors.As(err, &exitErr) {
			text := string(exitErr.Stderr)
			if strings.Contains(text, "Data stale") || strings.Contains(text, "Driver not connected") {
				return nil, errUPSStale
			}
		}
		return nil, toolError("upsc", err)
	}
	vars := map[string]string{}
	for line := range strings.Lines(string(out)) {
		key, value, ok := strings.Cut(line, ": ")
		if ok && (key == "ups.status" || key == "battery.runtime" || key == "battery.charge") {
			vars[key] = strings.TrimSpace(value)
		}
	}
	return vars, nil
}

// upsNumber is the variable key as a number; ok is false when the UPS does not report it.
func upsNumber(vars map[string]string, key string) (float64, bool, error) {
	text, ok := vars[key]
	if !ok {
		return 0, false, nil
	}
	v, err := strconv.ParseFloat(text, 64)
	if err != nil || math.IsNaN(v) || math.IsInf(v, 0) || v < 0 {
		return 0, false, fmt.Errorf("upsc: %s of another form", key)
	}
	return v, true, nil
}

// apcupsd reads the state of the UPS the local apcupsd watches: online, on battery, low battery,
// whether apcupsd lost the connection to it, the charge, the runtime and the transfers to battery
// since apcupsd started. `apcaccess -u status` asks the apcupsd on localhost:3551 and strips the units
// (apcaccess(8)); of the report only STATUS, BCHARGE, TIMELEFT and NUMXFERS are read.
//
// apcaccess(8): STATUS is one or more of CAL TRIM BOOST ONLINE ONBATT OVERLOAD LOWBATT REPLACEBATT
// NOBATT SLAVE SLAVEDOWN, or COMMLOST, or SHUTTING DOWN; BCHARGE a percentage, NUMXFERS a count.
// apcupsd's src/lib/apcstatus.c writes each line as "KEY      : value" and TIMELEFT in minutes. In
// that source the digit after the point is the remainder in seconds, not a tenth; the view takes the
// value as decimal minutes, so the runtime may be off by less than a minute. Not checked against a
// live apcupsd.
func apcupsd(ctx context.Context, _ Target) (map[string]any, error) {
	out, err := runAppTool(ctx, "apcaccess", "-u", "status")
	if err != nil {
		return nil, err
	}
	report := map[string]string{}
	for line := range strings.Lines(string(out)) {
		key, value, ok := strings.Cut(line, ":")
		if !ok {
			continue
		}
		report[strings.TrimSpace(key)] = strings.TrimSpace(value)
	}
	status, ok := report["STATUS"]
	if !ok {
		return nil, errors.New("apcaccess: a report of another form")
	}
	flags := map[string]bool{}
	for token := range strings.FieldsSeq(status) {
		flags[token] = true
	}
	values := map[string]any{
		"online":      flags["ONLINE"],
		"on_battery":  flags["ONBATT"],
		"low_battery": flags["LOWBATT"],
		"commlost":    flags["COMMLOST"],
	}
	// A UPS on a simple cable reports no charge or runtime; such a field stays out.
	for key, field := range map[string]string{"BCHARGE": "charge_pct", "TIMELEFT": "runtime_s", "NUMXFERS": "transfers"} {
		text, ok := report[key]
		if !ok {
			continue
		}
		// -u drops the unit; a unit word left behind (an apcaccess without -u support) is cut off.
		number, _, _ := strings.Cut(text, " ")
		v, err := strconv.ParseFloat(number, 64)
		if err != nil || math.IsNaN(v) || math.IsInf(v, 0) || v < 0 {
			return nil, fmt.Errorf("apcaccess: %s of another form", key)
		}
		switch field {
		case "runtime_s":
			values[field] = int(math.Round(v * 60))
		case "transfers":
			values[field] = int(v)
		default:
			values[field] = v
		}
	}
	return values, nil
}
