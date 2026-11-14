// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package probe

import (
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"io/fs"
	"os"
	"os/exec"
	"path"
	"strconv"
	"strings"
	"time"
)

const (
	// maxQueueFiles caps the files a queue count reads; beyond it the count stops and says so.
	maxQueueFiles = 1_000_000
	// maxQueueDepth caps how deep a count descends into the hashed subdirectories of a queue
	// (hash_queue_depth, 1 by default).
	maxQueueDepth = 16
	// postqueueMax is the number of mails up to which postfix_queue_age asks showq for their arrival:
	// postqueue -j opens every queue file, which on a full queue would load the server.
	postqueueMax = 5000
	// dovecotErrorWindow is how far back dovecot_status counts the error log of Dovecot.
	dovecotErrorWindow = time.Hour
)

// postfixQueues are the queues of Postfix a count reads (src/global/mail_queue.h): what arrives, what
// is being delivered, what waits for its next try, and what an admin holds.
var postfixQueues = []string{"incoming", "active", "deferred", "hold"}

// postfixQueue counts the mails in each queue of the local Postfix by listing the queue directories:
// it opens no queue file and starts no command but postconf, which names the queue directory.
func postfixQueue(ctx context.Context, _ Target) (map[string]any, error) {
	dir, err := postfixQueueDir(ctx)
	if err != nil {
		return nil, err
	}
	return untilDone(ctx, func() (map[string]any, error) {
		root, err := hostRoot()
		if err != nil {
			return nil, fmt.Errorf("the root of this host cannot be opened: %v", cause(err))
		}
		defer root.Close()
		return countQueues(root, dir)
	})
}

// postfixQueueAge reads how long the oldest mail of the local Postfix has waited, from the arrival
// times of postqueue -j, and nothing else of its JSON (sender and recipients stay on this host). With
// postqueueMax mails or more it does not ask showq and says so in age_read.
func postfixQueueAge(ctx context.Context, t Target) (map[string]any, error) {
	counts, err := postfixQueue(ctx, t)
	if err != nil {
		return nil, err
	}
	if counts["capped"] == true || counts["total"].(int) >= postqueueMax {
		return map[string]any{"age_read": false}, nil
	}
	out, err := runToolEnv(ctx, toolTimeout, []string{"LC_ALL=C"}, "postqueue", "-j")
	if errors.Is(err, exec.ErrNotFound) {
		return nil, fmt.Errorf("%w: postqueue is not installed", ErrUnsupported)
	}
	if err != nil {
		return nil, toolError("postqueue", err)
	}
	oldest, err := oldestArrival(out)
	if err != nil {
		return nil, err
	}
	age := int64(0)
	if !oldest.IsZero() {
		age = max(int64(now().Sub(oldest)/time.Second), 0)
	}
	return map[string]any{"age_read": true, "oldest_age_s": age}, nil
}

// postfixQueueDir asks postconf where the queues live: an absolute path of one line.
func postfixQueueDir(ctx context.Context) (string, error) {
	out, err := runToolEnv(ctx, toolTimeout, []string{"LC_ALL=C"}, "postconf", "-h", "queue_directory")
	if errors.Is(err, exec.ErrNotFound) {
		return "", fmt.Errorf("%w: postconf is not installed", ErrUnsupported)
	}
	if err != nil {
		return "", toolError("postconf", err)
	}
	dir := strings.TrimSpace(string(out))
	if !path.IsAbs(dir) || strings.ContainsAny(dir, "\n\x00") || path.Clean(dir) != dir {
		return "", errors.New("postconf names no absolute queue directory")
	}
	return dir, nil
}

// countQueues counts the files in each of postfixQueues below dir of root, descending into the
// hashed subdirectories. A queue that does not exist counts 0; with no queue at all dir is no queue
// directory of Postfix.
func countQueues(root *os.Root, dir string) (map[string]any, error) {
	base := strings.TrimPrefix(dir, "/")
	values := map[string]any{}
	total, found, budget := 0, false, maxQueueFiles
	for _, q := range postfixQueues {
		n, err := countFiles(root, path.Join(base, q), 0, &budget)
		if errors.Is(err, fs.ErrNotExist) {
			values[q] = 0
			continue
		}
		if err != nil {
			return nil, err
		}
		found = true
		values[q] = n
		total += n
	}
	if !found {
		return nil, fmt.Errorf("%w: %s holds no queue of Postfix", ErrUnsupported, dir)
	}
	values["total"] = total
	values["capped"] = budget == 0
	return values, nil
}

// countFiles counts the regular files below dir from their directory entries alone, taking at most
// *budget of them. Subdirectories of one character are the hash levels of a queue; others it skips.
func countFiles(root *os.Root, dir string, depth int, budget *int) (int, error) {
	f, err := root.OpenFile(dir, dirFlags, 0)
	if errors.Is(err, fs.ErrNotExist) {
		return 0, fs.ErrNotExist
	}
	if errors.Is(notDir(err), errNotDir) {
		return 0, fmt.Errorf("/%s is no directory", dir)
	}
	if err != nil {
		return 0, fmt.Errorf("/%s cannot be read: %v", dir, cause(err))
	}
	defer f.Close()
	n := 0
	for *budget > 0 {
		entries, err := f.ReadDir(min(*budget, 1024))
		for _, e := range entries {
			switch {
			case e.Type().IsRegular():
				n++
				*budget--
			case e.IsDir() && len(e.Name()) == 1 && depth < maxQueueDepth:
				sub, err := countFiles(root, dir+"/"+e.Name(), depth+1, budget)
				if err != nil && !errors.Is(err, fs.ErrNotExist) {
					return 0, err
				}
				n += sub
			}
			if *budget <= 0 {
				break
			}
		}
		if errors.Is(err, io.EOF) || (err == nil && len(entries) == 0) {
			break
		}
		if err != nil {
			return 0, fmt.Errorf("/%s cannot be read: %v", dir, cause(err))
		}
	}
	return n, nil
}

// oldestArrival returns the earliest arrival_time of the JSON lines of postqueue -j, one object per
// queue file with arrival_time in seconds since the epoch (src/postqueue/postqueue.c, JSON OBJECT
// FORMAT); the zero time for an empty queue.
func oldestArrival(out []byte) (time.Time, error) {
	var oldest int64
	sc := bufio.NewScanner(bytes.NewReader(out))
	sc.Buffer(make([]byte, 64<<10), 4<<20)
	for sc.Scan() {
		line := bytes.TrimSpace(sc.Bytes())
		if len(line) == 0 {
			continue
		}
		var m struct {
			ArrivalTime *json.Number `json:"arrival_time"`
		}
		if json.Unmarshal(line, &m) != nil || m.ArrivalTime == nil {
			return time.Time{}, errors.New("postqueue -j answers with a line that is no queue file")
		}
		at, err := m.ArrivalTime.Int64()
		if err != nil || at <= 0 {
			return time.Time{}, errors.New("postqueue -j answers with an arrival_time that is no time")
		}
		if oldest == 0 || at < oldest {
			oldest = at
		}
	}
	if sc.Err() != nil {
		return time.Time{}, errors.New("postqueue -j answers with a line that is too long")
	}
	if oldest == 0 {
		return time.Time{}, nil
	}
	return time.Unix(oldest, 0), nil
}

// dovecotStatus reads the state of the local Dovecot: how many of its services run at their process
// limit, from doveadm service status, and how many errors and warnings its error log holds of the
// last dovecotErrorWindow, from doveadm log errors. The text of a log line, which names users and
// addresses, stays on this host.
func dovecotStatus(ctx context.Context, _ Target) (map[string]any, error) {
	out, err := runToolEnv(ctx, toolTimeout, []string{"LC_ALL=C"}, "doveadm", "-f", "tab", "service", "status")
	if errors.Is(err, exec.ErrNotFound) {
		return nil, fmt.Errorf("%w: doveadm is not installed", ErrUnsupported)
	}
	if err != nil {
		return nil, toolError("doveadm", err)
	}
	values, err := dovecotServices(string(out))
	if err != nil {
		return nil, err
	}
	since := strconv.FormatInt(now().Add(-dovecotErrorWindow).Unix(), 10)
	out, err = runToolEnv(ctx, toolTimeout, []string{"LC_ALL=C"}, "doveadm", "log", "errors", "-s", since)
	if err != nil {
		return nil, toolError("doveadm", err)
	}
	values["errors_1h"], values["warnings_1h"] = dovecotErrors(string(out))
	return values, nil
}

// dovecotServices counts the services of doveadm -f tab service status and those whose processes
// reach their process_limit (a limit of 0 sets none): a header of field names, then one row per
// service.
func dovecotServices(out string) (map[string]any, error) {
	lines := strings.Split(strings.TrimRight(out, "\n"), "\n")
	col := map[string]int{}
	for i, name := range strings.Split(lines[0], "\t") {
		col[name] = i
	}
	count, okCount := col["process_count"]
	limit, okLimit := col["process_limit"]
	if !okCount || !okLimit {
		return nil, errors.New("doveadm service status answers without process_count and process_limit")
	}
	services, atLimit := 0, 0
	for _, line := range lines[1:] {
		fields := strings.Split(line, "\t")
		if len(fields) != len(col) {
			return nil, errors.New("doveadm service status answers with a row that does not fit its header")
		}
		n, err1 := strconv.Atoi(fields[count])
		l, err2 := strconv.Atoi(fields[limit])
		if err1 != nil || err2 != nil || n < 0 || l < 0 {
			return nil, errors.New("doveadm service status answers with a process count that is no number")
		}
		services++
		if l > 0 && n >= l {
			atLimit++
		}
	}
	return map[string]any{"services": services, "services_at_limit": atLimit}, nil
}

// dovecotErrors counts the lines of doveadm log errors by their type: "<Mon> <dd> <hh:mm:ss.us>
// <Type>: <prefix><text>" (src/doveadm/doveadm-log.c); Error, Fatal and Panic are errors.
func dovecotErrors(out string) (errs, warnings int) {
	for line := range strings.SplitSeq(out, "\n") {
		fields := strings.Fields(line)
		if len(fields) < 4 {
			continue
		}
		switch fields[3] {
		case "Error:", "Fatal:", "Panic:":
			errs++
		case "Warning:":
			warnings++
		}
	}
	return errs, warnings
}
