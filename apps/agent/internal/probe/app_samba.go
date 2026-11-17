// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package probe

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"os/exec"
	"regexp"
	"strings"
	"time"
)

// sambaToolTimeout bounds a call of samba-tool: it starts Python and opens the directory database,
// which takes seconds of CPU.
const sambaToolTimeout = time.Minute

// sambaEnv is the environment of samba-tool. samba-tool prints a time of replication as
// strftime("%a %b %e %X %Y %Z") in the local time zone (lib/util/time.c, timestring), "NTTIME(0)" for
// none; in the C locale and in UTC that reads as drsTime.
var sambaEnv = []string{"LC_ALL=C", "TZ=UTC"}

// drsTime is the layout of a time samba-tool drs showrepl prints under sambaEnv.
const drsTime = "Mon Jan _2 15:04:05 2006 MST"

// drsNever is what samba-tool prints for a time that never was (nt_time_string).
const drsNever = "NTTIME(0)"

// fsmoLine is one line of samba-tool fsmo show (python/samba/netcmd/fsmo.py, cmd_fsmo_show): a role
// with its owner, a role without one, or a role that could not be read.
var fsmoLine = regexp.MustCompile(`^([A-Za-z]+MasterRole)(?: owner: (.*)| has no current owner|: \* .*)$`)

// sambaFailure is the error of a Samba command name that failed with err. It quotes no stderr: the
// tools name domain controllers, DNs and shares there.
func sambaFailure(name string, err error) error {
	var exitErr *exec.ExitError
	switch {
	case errors.Is(err, exec.ErrNotFound):
		return fmt.Errorf("%w: %s is not installed", ErrUnsupported, name)
	case errors.As(err, &exitErr):
		return fmt.Errorf("%s fails with exit %d", name, exitErr.ExitCode())
	}
	return fmt.Errorf("%s: %w", name, err)
}

// drsNeighbour is one replication link of samba-tool drs showrepl --json (python/samba/netcmd/drs.py,
// parse_neighbour); the view reads no name and no DN of it.
type drsNeighbour struct {
	DSA         string  `json:"DSA objectGUID"`
	Failures    *int    `json:"consecutive failures"`
	LastSuccess *string `json:"last success"`
	Deleted     bool    `json:"is deleted"`
}

// sambaDRS reads the replication links of this Samba AD domain controller from samba-tool drs showrepl
// --json: how many domain controllers it replicates from, over how many links, how many of them and of
// the links it notifies fail, and the age of the oldest last success of an inbound link. An inbound link
// fails with consecutive failures or without any success: the pull runs on schedule for every
// partition. An outbound link fails only with consecutive failures: Samba notifies a partner only after
// a change of the partition (source4/dsdb/repl/drepl_notify.c), so a link of a partition that seldom
// changes (schema, configuration) shows no success for good. A link to a deleted domain controller is
// left out, as --summary leaves it out.
func sambaDRS(ctx context.Context, _ Target) (map[string]any, error) {
	out, err := runToolEnv(ctx, sambaToolTimeout, sambaEnv, "samba-tool", "drs", "showrepl", "--json")
	if err != nil {
		return nil, sambaFailure("samba-tool", err)
	}
	return drsValues(out)
}

// drsValues counts the links of the JSON of samba-tool drs showrepl.
func drsValues(out []byte) (map[string]any, error) {
	var doc struct {
		From *[]drsNeighbour `json:"repsFrom"`
		To   *[]drsNeighbour `json:"repsTo"`
	}
	if err := json.Unmarshal(out, &doc); err != nil || doc.From == nil || doc.To == nil {
		return nil, errors.New("samba-tool drs showrepl answers without its links")
	}
	partners := map[string]bool{}
	links, failing := 0, 0
	var oldest time.Time
	for _, n := range *doc.From {
		if n.Deleted {
			continue
		}
		fails, last, err := drsLink(n)
		if err != nil {
			return nil, err
		}
		fails = fails || last.IsZero()
		links++
		partners[n.DSA] = true
		if fails {
			failing++
		}
		if !last.IsZero() && (oldest.IsZero() || last.Before(oldest)) {
			oldest = last
		}
	}
	outFailing := 0
	for _, n := range *doc.To {
		if n.Deleted {
			continue
		}
		fails, _, err := drsLink(n)
		if err != nil {
			return nil, err
		}
		if fails {
			outFailing++
		}
	}
	values := map[string]any{
		"partners": len(partners), "links": links, "links_failing": failing, "outbound_failing": outFailing,
	}
	switch {
	case !oldest.IsZero():
		values["last_success_age_s"] = max(int(now().Sub(oldest).Seconds()), 0)
	case links == 0:
		// The only domain controller of its domain pulls from nobody: nothing can be stale. Without a
		// value the replication check would stay unknown on it for good.
		values["last_success_age_s"] = 0
	}
	return values, nil
}

// sambaSideUnits are the units of a Samba file server, NetBIOS name server and winbind, by Debian's
// names and by Fedora's (smb, nmb; not verified on a DC there): on a DC the samba service starts smbd
// and winbindd itself, and a separate smbd, nmbd or winbind makes the DC fail (Samba wiki, "Managing
// the Samba AD DC Service Using Systemd": mask and disable smbd nmbd winbind).
var sambaSideUnits = []string{"smbd.service", "nmbd.service", "winbind.service", "smb.service", "nmb.service"}

// sambaDCUnits counts the sambaSideUnits that are active next to this domain controller, from one
// systemctl show; a unit this host does not know reads as inactive.
func sambaDCUnits(ctx context.Context, _ Target) (map[string]any, error) {
	args := append([]string{"show", "-p", "Id,Names,ActiveState,MainPID", "--"}, sambaSideUnits...)
	out, err := runToolEnv(ctx, toolTimeout, sambaEnv, "systemctl", args...)
	if err != nil {
		return nil, sambaFailure("systemctl", err)
	}
	units, active := 0, 0
	for line := range strings.Lines(string(out)) {
		k, v, _ := strings.Cut(strings.TrimRight(line, "\r\n"), "=")
		if k != "ActiveState" {
			continue
		}
		units++
		if v == "active" || v == "activating" || v == "reloading" {
			active++
		}
	}
	if units != len(sambaSideUnits) {
		return nil, errors.New("systemctl show answers in another form")
	}
	return map[string]any{"side_units_active": active}, nil
}

// drsLink says whether the link n has consecutive failures and when it last succeeded, the zero time if
// never.
func drsLink(n drsNeighbour) (fails bool, last time.Time, err error) {
	if n.Failures == nil || n.LastSuccess == nil || *n.Failures < 0 {
		return false, time.Time{}, errors.New("samba-tool drs showrepl answers with a link it cannot be read from")
	}
	if *n.LastSuccess == drsNever {
		return *n.Failures != 0, time.Time{}, nil
	}
	last, err = time.Parse(drsTime, *n.LastSuccess)
	if err != nil {
		return false, time.Time{}, errors.New("samba-tool drs showrepl answers with a time it cannot be read from")
	}
	return *n.Failures != 0, last, nil
}

// sambaFSMO counts the FSMO roles of this Samba AD domain from samba-tool fsmo show and those without a
// valid owner: none, one samba-tool could not read, or a deleted domain controller (its DN carries
// "\0ADEL:", MS-ADTS 3.1.1.5.5.1.2; as Samba prints it not verified). The owners stay on this host.
func sambaFSMO(ctx context.Context, _ Target) (map[string]any, error) {
	out, err := runToolEnv(ctx, sambaToolTimeout, sambaEnv, "samba-tool", "fsmo", "show")
	if err != nil {
		return nil, sambaFailure("samba-tool", err)
	}
	roles, orphaned := 0, 0
	for line := range strings.Lines(string(out)) {
		m := fsmoLine.FindStringSubmatch(strings.TrimRight(line, "\r\n"))
		if m == nil {
			continue
		}
		roles++
		if owner := m[2]; owner == "" || strings.Contains(owner, `\0ADEL:`) {
			orphaned++
		}
	}
	if roles == 0 {
		return nil, errors.New("samba-tool fsmo show names no role")
	}
	return map[string]any{"roles": roles, "roles_without_owner": orphaned}, nil
}

// sambaMember reads the state of this Samba file server or domain member: whether testparm accepts
// smb.conf, the sessions, share connections and open files from smbstatus --json --fast (--fast skips
// checking that the processes still live), and, with winbind installed, whether winbindd answers and
// whether it reaches its domain controller over NETLOGON (wbinfo -p, -P; each exits 0 on success,
// nsswitch/wbinfo.c). It quotes nothing of what the tools print: share names, users, clients, files.
// An smbstatus that exits with a code (one before Samba 4.17 knows no --json, source3/utils/status.c)
// leaves only the counts out: they are shown, no rule reads them, and smb.conf and winbind still count.
func sambaMember(ctx context.Context, _ Target) (map[string]any, error) {
	_, err := runToolEnv(ctx, toolTimeout, sambaEnv, "testparm", "-s")
	var exitErr *exec.ExitError
	switch {
	case err == nil, errors.As(err, &exitErr):
	default:
		return nil, sambaFailure("testparm", err)
	}
	values := map[string]any{"config_ok": err == nil}
	if err := smbstatusCounts(ctx, values); err != nil {
		return nil, err
	}
	ok, err := wbinfoOK(ctx, "-p")
	if errors.Is(err, ErrUnsupported) {
		return values, nil
	}
	if err != nil {
		return nil, err
	}
	values["winbind_ok"] = ok
	if ok {
		if ok, err = wbinfoOK(ctx, "-P"); err != nil {
			return nil, err
		}
	}
	values["dc_ok"] = ok
	return values, nil
}

// smbstatusCounts adds the sessions, share connections and open files from smbstatus --json --fast
// to values; an smbstatus that exits with a code adds none.
func smbstatusCounts(ctx context.Context, values map[string]any) error {
	out, err := runToolEnv(ctx, toolTimeout, sambaEnv, "smbstatus", "--json", "--fast")
	var exitErr *exec.ExitError
	if errors.As(err, &exitErr) {
		return nil
	}
	if err != nil {
		return sambaFailure("smbstatus", err)
	}
	var status map[string]json.RawMessage
	if err := json.Unmarshal(out, &status); err != nil {
		return errors.New("smbstatus answers with no JSON")
	}
	// smbstatus keys sessions and share connections by their ID, open_files by file
	// (source3/utils/status_json.c).
	for _, section := range []string{"sessions", "tcons", "open_files"} {
		n, err := jsonMembers(status[section])
		if err != nil {
			return fmt.Errorf("smbstatus answers with %s that is no object", section)
		}
		values[section] = n
	}
	return nil
}

// sambaTrust says whether the trust account of this domain member is valid: wbinfo -t checks it
// against the domain controller.
func sambaTrust(ctx context.Context, _ Target) (map[string]any, error) {
	ok, err := wbinfoOK(ctx, "-t")
	if err != nil {
		return nil, err
	}
	return map[string]any{"trust_ok": ok}, nil
}

// wbinfoOK says whether wbinfo with the check flag succeeds; a wbinfo that fails or takes too long
// does not. ErrUnsupported without wbinfo.
func wbinfoOK(ctx context.Context, flag string) (bool, error) {
	_, err := runToolEnv(ctx, toolTimeout, sambaEnv, "wbinfo", flag)
	var exitErr *exec.ExitError
	switch {
	case err == nil:
		return true, nil
	case errors.As(err, &exitErr), errors.Is(err, context.DeadlineExceeded) && ctx.Err() == nil:
		return false, nil
	}
	return false, sambaFailure("wbinfo", err)
}

// jsonMembers counts the members of the JSON object raw, 0 for none (smbstatus leaves a section out
// when locking.tdb was never set up).
func jsonMembers(raw json.RawMessage) (int, error) {
	if len(bytes.TrimSpace(raw)) == 0 {
		return 0, nil
	}
	var members map[string]json.RawMessage
	if err := json.Unmarshal(raw, &members); err != nil {
		return 0, err
	}
	return len(members), nil
}
