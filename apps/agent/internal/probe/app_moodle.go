// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package probe

import (
	"context"
	"errors"
	"fmt"
	"os/exec"
	"path"
	"regexp"
	"slices"
	"strings"
	"time"

	"adminhelper-agent/internal/allowlist"
	"adminhelper-agent/internal/execx"
)

// moodleTimeout is how long checks.php may run: it asks each status check of the site (the database,
// the cron, the caches) and is slower than a plain tool. The probe's own timeout_s (at most 30 s)
// ends it no later.
const moodleTimeout = 30 * time.Second

// moodleMaxOutput bounds what the agent keeps of checks.php's output: a table of a few lines per
// check that is not OK. Code of the site that writes without end is stopped there.
const moodleMaxOutput = 64 << 10

// runCapped starts a call of the allowlist with its output bounded; tests stand in their own.
var runCapped = allowlist.RunCapped

// moodleStates are the states checks.php exits with, as Nagios plugins do (admin/cli/checks.php:
// NA, OK and INFO exit 0, WARNING 1, ERROR and CRITICAL 2, UNKNOWN 3; the worst result wins).
var moodleStates = map[int]string{0: "ok", 1: "warning", 2: "critical", 3: "unknown"}

// moodleFirstLine is the first line of checks.php: "OK: …" when every check passes, else the label
// and the name of the worst one ("WARNING: …", "CRITICAL: …", "UNKNOWN: …"; ERROR is labelled
// CRITICAL). PHP may print a notice before it.
var moodleFirstLine = regexp.MustCompile(`(?m)^(?:OK|WARNING|CRITICAL|UNKNOWN): `)

// moodleStatus is the first column of a result row: one word, the status as the CLI renderer prints
// it, maybe coloured. A line of a check's details that html_to_text broke goes out without the
// column; one with a '|' in it has more than a word before it.
var moodleStatus = regexp.MustCompile(`^ *(?:\x1b\[[0-9;]*m)*[A-Za-z]+(?:\x1b\[[0-9;]*m)*$`)

// moodleChecks runs the status checks of the Moodle a vhost serves, admin/cli/checks.php of its
// document root, as the user its web server runs as (nginx's user, Apache's User), never as root:
// the script runs code of the site, and as root would leave files in moodledata the web server can no
// longer write. It runs only code that is root's and that user's (moodleOwned), on the path it checked
// (the document root with its links resolved), with its output bounded (moodleMaxOutput) and its
// stderr dropped. It is called without --type, so only checks of type status run (the default): the
// performance checks may change the site. Of its output it keeps only the state (from the exit code)
// and not_ok, the number of checks that are not OK (the rows of its table; without --verbose it lists
// only warnings and errors), never their text. Options and output: moodle main admin/cli/checks.php,
// moodledev.io/docs/apis/subsystems/check (Check API since Moodle 3.9).
func moodleChecks(ctx context.Context, t Target) (map[string]any, error) {
	list, lerr := cachedVhosts(ctx)
	i := slices.IndexFunc(list, func(v Vhost) bool { return v.Name == t.Name && int(v.Port) == t.PortHint })
	switch {
	case i < 0 && lerr != nil:
		return nil, lerr
	case i < 0:
		return nil, fmt.Errorf("no web server of this host serves %s on port %d", t.Name, t.PortHint)
	case list[i].App != "moodle":
		return nil, fmt.Errorf("%w: %s serves no Moodle", ErrUnsupported, t.Name)
	case list[i].user == "" || list[i].user == "root":
		return nil, fmt.Errorf("%w: the web server of %s names no user other than root", ErrUnsupported, t.Name)
	}
	v := list[i]
	root, err := moodleOwned(v.root, v.user)
	if err != nil {
		return nil, err
	}
	script := path.Join(root, "admin/cli/checks.php")
	out, err := runCapped(ctx, moodleTimeout, moodleMaxOutput, "runuser", "-u", v.user, "--", "php", script)
	var exitErr *exec.ExitError
	code := 0
	switch {
	case errors.Is(err, exec.ErrNotFound):
		return nil, fmt.Errorf("%w: runuser is not installed", ErrUnsupported)
	case errors.Is(err, execx.ErrOutputLimit):
		return nil, fmt.Errorf("moodle checks.php wrote more than %d KiB", moodleMaxOutput>>10)
	case errors.As(err, &exitErr) && exitErr.ExitCode() == 127:
		return nil, fmt.Errorf("%w: php is not installed", ErrUnsupported)
	case errors.As(err, &exitErr):
		code = exitErr.ExitCode()
	case err != nil:
		return nil, toolError("runuser", err)
	}
	state, known := moodleStates[code]
	at := moodleFirstLine.FindIndex(out)
	if !known || at == nil {
		// runuser exits 1 itself (an unknown user), php 255 on a fatal error: no answer of checks.php.
		// Only the code goes out: the output is the site's own text.
		return nil, fmt.Errorf("moodle checks.php gave no answer of its form (exit %d)", code)
	}
	return map[string]any{"state": state, "not_ok": moodleRows(string(out[at[0]:]))}, nil
}

// moodleRows counts the results in checks.php's table: below the header and its rule
// ("----------+-…"), each row of "%10s| %-60s" whose first column is a status; a row with an empty
// first column (the summary, the details) continues the one before it.
func moodleRows(text string) int {
	n, table := 0, false
	for line := range strings.Lines(text) {
		status, _, bar := strings.Cut(line, "|")
		switch {
		case !table:
			table = strings.HasPrefix(line, "----------+")
		case bar && moodleStatus.MatchString(status):
			n++
		}
	}
	return n
}
