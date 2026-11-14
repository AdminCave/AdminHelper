// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package probe

import (
	"bytes"
	"encoding/csv"
	"encoding/xml"
	"errors"
	"io"
	"math"
	"strconv"
	"strings"
	"time"
)

// The Windows views of the app and host sensors. What they read comes from fixed queries
// (winread.go) or fixed read commands through the allowlist; the parsers here are portable,
// so the tests run everywhere. Every view reports counts, percentages, ages and booleans,
// never a name, an address or an event text.

var (
	errRepadminForm = errors.New("repadmin: unexpected output")
	errAppcmdForm   = errors.New("appcmd: unexpected output")
)

// repadminTimeLayout is how `repadmin /showrepl /csv` writes a time, in local time. Not
// verified on a domain controller: the column names and the layout come from Microsoft's
// repadmin documentation and published samples.
const repadminTimeLayout = "2006-01-02 15:04:05"

// repadminValues reads `repadmin /showrepl localhost /csv`: one row per inbound replication
// link (naming context × source DC), after a header row showrepl_COLUMNS. A link counts as
// failing with a nonzero "Number of Failures"; the age is that of the oldest last success
// over all links. A link that never succeeded has no time and counts as never.
func repadminValues(out []byte, now time.Time) (map[string]any, error) {
	r := csv.NewReader(bytes.NewReader(out))
	r.FieldsPerRecord = -1
	r.LazyQuotes = true
	cols := map[string]int{}
	partners := map[string]bool{}
	links, failing, never := 0, 0, 0
	var oldest time.Time
	for {
		rec, err := r.Read()
		if errors.Is(err, io.EOF) {
			break
		}
		if err != nil {
			return nil, errRepadminForm
		}
		switch strings.TrimSpace(rec[0]) {
		case "showrepl_COLUMNS":
			for i, name := range rec {
				cols[strings.TrimSpace(name)] = i
			}
		case "showrepl_INFO":
			src, okSrc := cols["Source DSA"]
			fail, okFail := cols["Number of Failures"]
			last, okLast := cols["Last Success Time"]
			if !okSrc || !okFail || !okLast || len(rec) <= max(src, fail, last) {
				return nil, errRepadminForm
			}
			n, err := strconv.Atoi(strings.TrimSpace(rec[fail]))
			if err != nil || n < 0 {
				return nil, errRepadminForm
			}
			links++
			partners[strings.ToLower(strings.TrimSpace(rec[src]))] = true
			if n > 0 {
				failing++
			}
			at, err := time.ParseInLocation(repadminTimeLayout, strings.TrimSpace(rec[last]), time.Local)
			if err != nil || at.Year() < 1700 {
				never++
				continue
			}
			if oldest.IsZero() || at.Before(oldest) {
				oldest = at
			}
		}
	}
	if len(cols) == 0 {
		return nil, errRepadminForm
	}
	values := map[string]any{
		"partners":      len(partners),
		"links":         links,
		"failing_links": failing,
		"never_links":   never,
	}
	if !oldest.IsZero() {
		values["oldest_success_age_s"] = max(0, int64(now.Sub(oldest)/time.Second))
	}
	return values, nil
}

// appcmdStopped counts the elements of `appcmd list site|apppool /xml` and those whose
// state is not "Started" (Stopped, Starting, Stopping, Unknown). Not verified on IIS: the
// element names SITE and APPPOOL and the attribute state come from Microsoft's appcmd
// documentation.
func appcmdStopped(out []byte, element string) (total, stopped int, err error) {
	d := xml.NewDecoder(bytes.NewReader(out))
	root := false
	for {
		tok, err := d.Token()
		if errors.Is(err, io.EOF) {
			break
		}
		if err != nil {
			return 0, 0, errAppcmdForm
		}
		se, ok := tok.(xml.StartElement)
		if !ok {
			continue
		}
		switch se.Name.Local {
		case "appcmd":
			root = true
		case element:
			total++
			state := ""
			for _, a := range se.Attr {
				if a.Name.Local == "state" {
					state = a.Value
				}
			}
			if state != "Started" {
				stopped++
			}
		}
	}
	if !root {
		return 0, 0, errAppcmdForm
	}
	return total, stopped, nil
}

// dhcpScope is one row of PS_DhcpServerv4ScopeStatistics (root/Microsoft/Windows/DHCP).
// Not verified on a DHCP server: that the class answers a plain WQL enumeration.
type dhcpScope struct {
	InUse uint32
	Free  uint32
}

// dhcpValues reports the fullest scope and the scopes over 80 and 95 per cent in use.
func dhcpValues(scopes []dhcpScope) map[string]any {
	maxPct := 0.0
	over80, over95 := 0, 0
	for _, s := range scopes {
		size := float64(s.InUse) + float64(s.Free)
		if size == 0 {
			continue
		}
		pct := 100 * float64(s.InUse) / size
		maxPct = max(maxPct, pct)
		if pct >= 80 {
			over80++
		}
		if pct >= 95 {
			over95++
		}
	}
	return map[string]any{
		"scopes":         len(scopes),
		"max_used_pct":   math.Round(maxPct*10) / 10,
		"scopes_over_80": over80,
		"scopes_over_95": over95,
	}
}

// rdsPack is one row of Win32_TSLicenseKeyPack (root\cimv2) on a license server.
type rdsPack struct {
	TotalLicenses  uint32
	IssuedLicenses uint32
	ExpirationDate time.Time
}

// rdsUnlimited marks a built-in pack without a count. Not verified on a license server.
const rdsUnlimited = math.MaxUint32

// rdsNoExpiry: a permanent pack carries an expiration far in the future (2038 in the
// samples). Not verified on a license server.
var rdsNoExpiry = time.Date(2038, 1, 1, 0, 0, 0, 0, time.UTC)

// rdsValues sums the counted packs and reports the days to the nearest expiry.
func rdsValues(packs []rdsPack, now time.Time) map[string]any {
	var total, issued uint64
	daysLeft := -1
	for _, p := range packs {
		if p.TotalLicenses != rdsUnlimited {
			total += uint64(p.TotalLicenses)
			issued += uint64(p.IssuedLicenses)
		}
		if p.ExpirationDate.IsZero() || !p.ExpirationDate.Before(rdsNoExpiry) {
			continue
		}
		d := int(p.ExpirationDate.Sub(now).Hours() / 24)
		if daysLeft < 0 || d < daysLeft {
			daysLeft = max(d, 0)
		}
	}
	values := map[string]any{"licenses_total": total, "licenses_issued": issued}
	if total > 0 {
		values["used_pct"] = math.Round(1000*float64(issued)/float64(total)) / 10
	}
	if daysLeft >= 0 {
		values["min_days_left"] = daysLeft
	}
	return values
}

// wuaState is what the Windows Update Agent answers: the open updates of the last offline
// search, how many of them carry an MSRC severity of Critical or Important, whether a
// reboot is pending, and when Windows Update last searched successfully on its own.
type wuaState struct {
	open, security int
	reboot         bool
	lastSearch     time.Time
}

func (s wuaState) values(now time.Time) map[string]any {
	values := map[string]any{
		"updates_open":     s.open,
		"updates_security": s.security,
		"reboot_required":  s.reboot,
	}
	if !s.lastSearch.IsZero() {
		values["search_age_s"] = max(0, int64(now.Sub(s.lastSearch)/time.Second))
	}
	return values
}

// wuaSecurity reports whether an MSRC severity is one of a security update that matters.
func wuaSecurity(severity string) bool {
	return severity == "Critical" || severity == "Important"
}

// winEventsWindow is how far back win_events counts: the probe's interval, so each run
// counts the events since the one before; an hour without one, at most a day.
func winEventsWindow(intervalS int) time.Duration {
	if intervalS <= 0 {
		return time.Hour
	}
	return min(time.Duration(intervalS)*time.Second, 24*time.Hour)
}

// machineCertValues reports the certificates of LocalMachine\My: how many, how many expired, and
// the days left of the one that expires next among the others.
func machineCertValues(notAfter []time.Time, now time.Time) map[string]any {
	expired := 0
	daysLeft := -1
	for _, at := range notAfter {
		if !at.After(now) {
			expired++
			continue
		}
		d := int(at.Sub(now).Hours() / 24)
		if daysLeft < 0 || d < daysLeft {
			daysLeft = d
		}
	}
	values := map[string]any{"certs": len(notAfter), "expired": expired}
	if daysLeft >= 0 {
		values["min_days_left"] = daysLeft
	}
	return values
}
