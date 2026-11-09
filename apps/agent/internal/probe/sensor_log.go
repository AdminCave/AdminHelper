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
	"unicode"
)

// The log sensor counts the entries of the systemd journal since its probe's last run, at a priority
// or worse, of one unit or of all: a number, never a line of what was logged.
func init() {
	cursorSensors["log"] = logSensor
}

const (
	// defaultLogPriority is err, as the monitoring service has it.
	defaultLogPriority = 3
	// maxCursorBytes caps a journal cursor the report state keeps; journalctl's have about 150 bytes.
	maxCursorBytes = 512
	// cursorLine starts the line journalctl --show-cursor ends its output with.
	cursorLine = "-- cursor: "
	// maxToolLineRunes caps the line of a tool's stderr an error quotes.
	maxToolLineRunes = 160
)

var (
	// journalUnitPattern is a systemd unit name, as unitPattern is on Linux. It holds no glob character:
	// journalctl --unit reads one as a pattern of all units it matches.
	journalUnitPattern = regexp.MustCompile(`^[A-Za-z0-9:_.@\\-]{1,255}$`)
	// logMatchPattern is the param match: a field that names who logged an entry, never one of what it
	// says, and a plain value. Counting by what entries say would let whoever sets the params read it,
	// one count at a time.
	logMatchPattern = regexp.MustCompile(`^(SYSLOG_IDENTIFIER|_COMM|CONTAINER_NAME)=[A-Za-z0-9._@/:+-]{1,100}$`)
	// journalHere returns why this host has no journal the sensor reads, nil if it has one; a seam for
	// the tests.
	journalHere = journalOfThisHost
)

// logQuery is what one probe of the log sensor counts.
type logQuery struct {
	unit     string
	priority int
	match    string
}

// logSensor counts the journal entries p asks for since cursor, where its last run stopped, and returns
// the count and the cursor of the last entry. Without a cursor it counts the probe's interval: its first
// run, a run after one that failed, and every run until an entry comes.
func logSensor(ctx context.Context, p Probe, cursor string) (map[string]any, string, error) {
	q, err := logParams(p)
	if err != nil {
		return nil, "", err
	}
	if err := journalHere(); err != nil {
		return nil, "", err
	}
	from := cursor
	n, next, err := countJournal(ctx, q, from, p.IntervalS)
	var exitErr *exec.ExitError
	if errors.As(err, &exitErr) && from != "" && ctx.Err() == nil {
		// journalctl exits with an error on a cursor it cannot seek to: the interval then.
		from = ""
		n, next, err = countJournal(ctx, q, from, p.IntervalS)
	}
	if err != nil {
		// Dropped: a journal that took longer than the timeout to count from the cursor would take
		// longer still on the next run.
		return nil, "", err
	}
	if next == "" {
		// No entry since: the next run starts where this one did.
		next = from
	}
	return map[string]any{"count": n}, next, nil
}

// logParams reads the params of the log sensor: unit (none: all units), priority (0 emerg … 7 debug,
// this level or worse) and match.
func logParams(p Probe) (logQuery, error) {
	if err := noTarget(p); err != nil {
		return logQuery{}, err
	}
	if err := knownParams(p, "unit", "priority", "match"); err != nil {
		return logQuery{}, err
	}
	q := logQuery{priority: defaultLogPriority}
	var err error
	if q.unit, err = textParam(p, "unit", ""); err != nil {
		return logQuery{}, err
	}
	if q.unit != "" && !journalUnitPattern.MatchString(q.unit) {
		return logQuery{}, fmt.Errorf("%w: parameter unit of sensor log is no systemd unit name", ErrInvalid)
	}
	if v, ok := p.Params["priority"]; ok {
		f, isNumber := v.(float64)
		if !isNumber || f != math.Trunc(f) || f < 0 || f > 7 {
			return logQuery{}, fmt.Errorf("%w: parameter priority of sensor log is no whole number from 0 to 7", ErrInvalid)
		}
		q.priority = int(f)
	}
	if q.match, err = textParam(p, "match", ""); err != nil {
		return logQuery{}, err
	}
	if q.match != "" && !logMatchPattern.MatchString(q.match) {
		return logQuery{}, fmt.Errorf("%w: parameter match of sensor log is none of SYSLOG_IDENTIFIER=, _COMM=, "+
			"CONTAINER_NAME= with a plain value", ErrInvalid)
	}
	return q, nil
}

// countJournal counts the entries of q after cursor, or of the last intervalS seconds without one, and
// returns their number and the cursor journalctl printed, "" for none. journalctl prints each entry's
// priority alone: what an entry says is never read.
func countJournal(ctx context.Context, q logQuery, cursor string, intervalS int) (int, string, error) {
	args := []string{"--no-pager", "--quiet", "--output=cat", "--output-fields=PRIORITY", "--show-cursor",
		"--priority=" + strconv.Itoa(q.priority)}
	if q.unit != "" {
		args = append(args, "--unit="+q.unit)
	}
	if cursor != "" {
		args = append(args, "--after-cursor="+cursor)
	} else {
		args = append(args, "--since=-"+strconv.Itoa(intervalS)+"s")
	}
	if q.match != "" {
		args = append(args, "--", q.match)
	}
	out, err := runTool(ctx, toolTimeout, "journalctl", args...)
	if errors.Is(err, exec.ErrNotFound) {
		return 0, "", fmt.Errorf("%w: journalctl is not installed", ErrUnsupported)
	}
	if err != nil {
		return 0, "", toolError("journalctl", err)
	}
	lines := strings.Split(strings.TrimRight(string(out), "\n"), "\n")
	next := ""
	// The cursor is the last line: an entry's field may hold a line that looks like one.
	if last := lines[len(lines)-1]; strings.HasPrefix(last, cursorLine) {
		lines = lines[:len(lines)-1]
		next = strings.TrimPrefix(last, cursorLine)
		if len(next) > maxCursorBytes || strings.ContainsFunc(next, unicode.IsSpace) {
			next = ""
		}
	}
	n := 0
	for _, line := range lines {
		if line != "" {
			n++
		}
	}
	return n, next, nil
}

// toolError is err of the external tool name with the first line the tool wrote to stderr, if any,
// without the name the tool may start it with and cut after its first "="; it keeps err (a timeout
// stays context.DeadlineExceeded). A client quotes a line of its option files it does not know as
// name=value: one with a mistyped password key would hand the password on.
func toolError(name string, err error) error {
	var exitErr *exec.ExitError
	if errors.As(err, &exitErr) {
		line, _, _ := strings.Cut(strings.TrimSpace(string(exitErr.Stderr)), "\n")
		if before, _, cut := strings.Cut(line, "="); cut {
			line = before + "=…"
		}
		if line = strings.TrimSpace(strings.TrimPrefix(line, name+": ")); line != "" {
			return fmt.Errorf("%s: %s (%w)", name, cutRunes(line, maxToolLineRunes), err)
		}
	}
	return fmt.Errorf("%s: %w", name, err)
}
