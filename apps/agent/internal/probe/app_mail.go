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
	"net"
	"os"
	"os/exec"
	"path"
	"regexp"
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

const (
	// mailcowRedisPort is the port of Redis in its container of Mailcow (redis-mailcow).
	mailcowRedisPort = 6379
	// watchdogEntries is how many of the newest entries of WATCHDOG_LOG mailcow_watchdog reads: the
	// watchdog pushes one per service and check and never trims the list.
	watchdogEntries = 500
	// maxWatchdogEntry caps one entry of WATCHDOG_LOG, a JSON object of some 100 bytes.
	maxWatchdogEntry = 8 << 10
	// maxMailConfBytes caps mailcow.conf and piler.conf, a few KiB each.
	maxMailConfBytes = 64 << 10
	// cvdHeaderBytes is the size of the header of a ClamAV database (.cvd, .cld).
	cvdHeaderBytes = 512
	// opendkimNoKeyTable is the exit of opendkim-testkey without a KeyTable to test (EX_CONFIG).
	opendkimNoKeyTable = 78
)

var (
	// mailcowEndpoint finds where Redis of Mailcow listens; tests point it at their server.
	mailcowEndpoint = resolve

	// mailcowQueueDir is the queue directory of Postfix in its container of Mailcow (postfix-mailcow),
	// the volume postfix-vol-1.
	mailcowQueueDir = "/var/spool/postfix"

	// pilerConfs are where piler.conf lives, below the root of this host: the packages of MailPiler,
	// then a build from source with its default prefix.
	pilerConfs = []string{"etc/piler/piler.conf", "usr/local/etc/piler/piler.conf"}
	// pilerQuery reads when the newest mail arrived in the archive, from the index on arrived.
	pilerQuery = "SELECT MAX(arrived) FROM metadata"
	// mysqlName is a user or database name piler_status hands to the client of the database.
	mysqlName = regexp.MustCompile(`^[A-Za-z0-9_]{1,64}$`)
	// mysqlError is the code of an error of the database client ("ERROR 1045 (28000): …").
	mysqlError = regexp.MustCompile(`^ERROR ([0-9]{1,5})\b`)

	// clamavDBFiles are the daily databases of ClamAV below the root of this host: freshclam keeps the
	// one or the other.
	clamavDBFiles = []string{"var/lib/clamav/daily.cld", "var/lib/clamav/daily.cvd"}

	// spamdPong is spamd's answer to PING as spamc -K prints it.
	spamdPong = regexp.MustCompile(`^SPAMD/[0-9]+(?:\.[0-9]+)* 0$`)

	// opendkimSummary is the summary opendkim-testkey -v prints after testing its KeyTable.
	opendkimSummary = regexp.MustCompile(`(?m)^[^:\n]+: ([0-9]+) keys? checked; ([0-9]+) pass, ([0-9]+) fail$`)
)

// mailcowWatchdog reads the health of the services of Mailcow from the log its watchdog keeps in
// Redis: how many services the newest entries name, how many of them stand below their full health,
// and how old the newest entry is. It reads the password of Redis from mailcow.conf in the directory
// of the compose project of the container t (redis-mailcow) and connects to the container's own
// address; the password goes to that connection alone and into no error.
func mailcowWatchdog(ctx context.Context, t Target) (map[string]any, error) {
	c, err := inspectContainer(ctx, t.Name)
	if err != nil {
		return nil, err
	}
	dir := c.Config.Labels["com.docker.compose.project.working_dir"]
	if !path.IsAbs(dir) || path.Clean(dir) != dir || strings.ContainsAny(dir, "\n\x00") {
		return nil, fmt.Errorf("%w: container %s belongs to no compose project", ErrUnsupported, t.Name)
	}
	pass, err := untilDone(ctx, func() (string, error) { return mailcowRedisPass(dir) })
	if err != nil {
		return nil, err
	}
	if t.PortHint == 0 {
		t.PortHint = mailcowRedisPort
	}
	ep, err := mailcowEndpoint(ctx, t)
	if err != nil {
		return nil, err
	}
	conn, err := dialThrough(ctx, secretGuard(ep), ep)
	if err != nil {
		return nil, err
	}
	defer conn.Close()
	entries, err := watchdogLog(conn, pass)
	if err != nil {
		return nil, netErr(ctx, err)
	}
	return watchdogValues(entries)
}

// mailcowRedisPass reads REDISPASS of mailcow.conf in dir of this host; "" if it sets none, as Mailcow
// did before its Redis took a password.
func mailcowRedisPass(dir string) (string, error) {
	root, err := hostRoot()
	if err != nil {
		return "", fmt.Errorf("the root of this host cannot be opened: %v", cause(err))
	}
	defer root.Close()
	name := strings.TrimPrefix(path.Join(dir, "mailcow.conf"), "/")
	data, err := readRootFile(root, name, "/"+name, maxMailConfBytes)
	if errors.Is(err, fs.ErrNotExist) {
		return "", fmt.Errorf("%w: %s holds no mailcow.conf", ErrUnsupported, dir)
	}
	if err != nil {
		return "", err
	}
	for line := range strings.SplitSeq(string(data), "\n") {
		if v, ok := strings.CutPrefix(strings.TrimSpace(line), "REDISPASS="); ok {
			if len(v) >= 2 && (v[0] == '"' || v[0] == '\'') && v[len(v)-1] == v[0] {
				v = v[1 : len(v)-1]
			}
			return v, nil
		}
	}
	return "", nil
}

// watchdogLog asks Redis on conn for the newest watchdogEntries entries of WATCHDOG_LOG, after AUTH
// with pass if there is one (RESP2: a command is an array of bulk strings).
func watchdogLog(conn net.Conn, pass string) ([][]byte, error) {
	w := bufio.NewWriter(conn)
	if pass != "" {
		respCommand(w, "AUTH", pass)
	}
	respCommand(w, "LRANGE", "WATCHDOG_LOG", "0", strconv.Itoa(watchdogEntries-1))
	if err := w.Flush(); err != nil {
		return nil, err
	}
	r := bufio.NewReaderSize(conn, 16<<10)
	if pass != "" {
		line, err := respLine(r)
		if err != nil {
			return nil, err
		}
		if line != "+OK" {
			return nil, fmt.Errorf("%w: Redis refuses the password of mailcow.conf", ErrDenied)
		}
	}
	line, err := respLine(r)
	if err != nil {
		return nil, err
	}
	switch {
	case strings.HasPrefix(line, "-NOAUTH"):
		return nil, fmt.Errorf("%w: Redis wants a password mailcow.conf does not set", ErrDenied)
	case strings.HasPrefix(line, "-"):
		return nil, errors.New("Redis refuses to read WATCHDOG_LOG")
	case line == "*-1":
		return nil, nil
	}
	n, err := strconv.Atoi(strings.TrimPrefix(line, "*"))
	if !strings.HasPrefix(line, "*") || err != nil || n < 0 || n > watchdogEntries {
		return nil, errors.New("Redis answers LRANGE with no list")
	}
	entries := make([][]byte, 0, n)
	for range n {
		line, err := respLine(r)
		if err != nil {
			return nil, err
		}
		size, err := strconv.Atoi(strings.TrimPrefix(line, "$"))
		if !strings.HasPrefix(line, "$") || err != nil || size < 0 || size > maxWatchdogEntry {
			return nil, errors.New("Redis answers LRANGE with an entry that is no string")
		}
		buf := make([]byte, size+2)
		if _, err := io.ReadFull(r, buf); err != nil {
			return nil, err
		}
		if !bytes.HasSuffix(buf, []byte("\r\n")) {
			return nil, errors.New("Redis answers LRANGE with an entry that is no string")
		}
		entries = append(entries, buf[:size])
	}
	return entries, nil
}

// respCommand writes a command of RESP2 to w.
func respCommand(w *bufio.Writer, args ...string) {
	fmt.Fprintf(w, "*%d\r\n", len(args))
	for _, a := range args {
		fmt.Fprintf(w, "$%d\r\n%s\r\n", len(a), a)
	}
}

// respLine reads one line of RESP2 without its CRLF.
func respLine(r *bufio.Reader) (string, error) {
	line, err := r.ReadSlice('\n')
	if errors.Is(err, bufio.ErrBufferFull) {
		return "", errors.New("Redis answers with a line that is too long")
	}
	if err != nil {
		return "", err
	}
	s, ok := strings.CutSuffix(string(line), "\r\n")
	if !ok {
		return "", errors.New("Redis answers with a line that is no line of RESP")
	}
	return s, nil
}

// watchdogEntry is an entry of WATCHDOG_LOG as the watchdog of Mailcow pushes it (watchdog.sh,
// progress and log_msg): every value a string, time in seconds since the epoch; an entry of a check
// names its service and its health now and in full, a message names none.
type watchdogEntry struct {
	Time    string `json:"time"`
	Service string `json:"service"`
	HPNow   string `json:"hpnow"`
	HPTotal string `json:"hptotal"`
}

// watchdogValues reduces the newest entries of WATCHDOG_LOG, newest first, to the values of
// mailcow_watchdog: per service its newest entry counts. Names of services stay on this host.
func watchdogValues(entries [][]byte) (map[string]any, error) {
	malformed := errors.New("WATCHDOG_LOG holds an entry that is no entry of the watchdog")
	var newest int64
	seen := map[string]bool{}
	failing := 0
	for _, raw := range entries {
		var e watchdogEntry
		if json.Unmarshal(raw, &e) != nil {
			return nil, malformed
		}
		at, err := strconv.ParseInt(e.Time, 10, 64)
		if err != nil || at <= 0 {
			return nil, malformed
		}
		newest = max(newest, at)
		if e.Service == "" || seen[e.Service] {
			continue
		}
		hp, err1 := strconv.Atoi(e.HPNow)
		total, err2 := strconv.Atoi(e.HPTotal)
		if err1 != nil || err2 != nil || hp < 0 || total <= 0 {
			return nil, malformed
		}
		seen[e.Service] = true
		if hp < total {
			failing++
		}
	}
	values := map[string]any{"services": len(seen), "services_failing": failing, "logged": newest > 0}
	if newest > 0 {
		values["last_age_s"] = max(now().Unix()-newest, 0)
	}
	return values, nil
}

// mailcowQueue counts the mails in each queue of Postfix in its container of Mailcow, t
// (postfix-mailcow), as postfixQueue does on this host: by listing the queue directories below the
// root of the container, without opening a queue file or starting a command in it.
func mailcowQueue(ctx context.Context, t Target) (map[string]any, error) {
	c, err := inspectContainer(ctx, t.Name)
	if err != nil {
		return nil, err
	}
	if !c.State.Running || c.State.Pid <= 0 {
		return nil, fmt.Errorf("container %s is not running", t.Name)
	}
	return untilDone(ctx, func() (map[string]any, error) {
		root, err := containerRoot(c.State.Pid)
		if errors.Is(err, ErrUnsupported) {
			return nil, err
		}
		if err != nil {
			return nil, fmt.Errorf("container %s: its root cannot be opened: %v", t.Name, cause(err))
		}
		defer root.Close()
		return countQueues(root, mailcowQueueDir)
	})
}

// pilerStatus reads how long ago the newest mail arrived in the archive of the local MailPiler, from
// its database with the access piler.conf names. The password goes to the database client in its
// environment (MYSQL_PWD), in no argument and no error; only the socket of this host is asked.
func pilerStatus(ctx context.Context, _ Target) (map[string]any, error) {
	conf, err := untilDone(ctx, readPilerConf)
	if err != nil {
		return nil, err
	}
	sock, user, db := conf["mysqlsocket"], conf["mysqluser"], conf["mysqldb"]
	if sock == "" {
		return nil, fmt.Errorf("%w: piler.conf names no socket of its database", ErrUnsupported)
	}
	if !path.IsAbs(sock) || path.Clean(sock) != sock || strings.ContainsAny(sock, " \t\n\x00") {
		return nil, errors.New("piler.conf names a socket that is no absolute path")
	}
	if !mysqlName.MatchString(user) || !mysqlName.MatchString(db) {
		return nil, errors.New("piler.conf names a user or database the agent does not hand on")
	}
	env := []string{"LC_ALL=C"}
	if pwd := conf["mysqlpwd"]; pwd != "" {
		if strings.ContainsRune(pwd, 0) {
			return nil, errors.New("piler.conf holds a password with a NUL byte")
		}
		env = append(env, "MYSQL_PWD="+pwd)
	}
	args := []string{"--no-defaults", "--batch", "--skip-column-names", "--connect-timeout=5", "--socket=" + sock, "--user=" + user,
		"--database=" + db, "--execute=" + pilerQuery}
	out, err := runToolEnv(ctx, toolTimeout, env, "mariadb", args...)
	if errors.Is(err, exec.ErrNotFound) {
		out, err = runToolEnv(ctx, toolTimeout, env, "mysql", args...)
	}
	if errors.Is(err, exec.ErrNotFound) {
		return nil, fmt.Errorf("%w: no client of MariaDB or MySQL is installed", ErrUnsupported)
	}
	var exitErr *exec.ExitError
	if errors.As(err, &exitErr) {
		// The client's message names the user and host; only its code leaves this host.
		if m := mysqlError.FindSubmatch(bytes.TrimSpace(exitErr.Stderr)); m != nil {
			return nil, fmt.Errorf("the database of piler answers with error %s", m[1])
		}
		return nil, fmt.Errorf("the database client fails with exit %d", exitErr.ExitCode())
	}
	if err != nil {
		return nil, fmt.Errorf("the database client: %w", err)
	}
	s := strings.TrimSpace(string(out))
	if s == "NULL" {
		return map[string]any{"archived": false}, nil
	}
	at, err := strconv.ParseInt(s, 10, 64)
	if err != nil || at <= 0 {
		return nil, errors.New("the database of piler answers with no time of arrival")
	}
	return map[string]any{"archived": true, "last_age_s": max(now().Unix()-at, 0)}, nil
}

// readPilerConf reads the settings of the first piler.conf of pilerConfs: lines of key=value.
func readPilerConf() (map[string]string, error) {
	root, err := hostRoot()
	if err != nil {
		return nil, fmt.Errorf("the root of this host cannot be opened: %v", cause(err))
	}
	defer root.Close()
	for _, name := range pilerConfs {
		data, err := readRootFile(root, name, "/"+name, maxMailConfBytes)
		if errors.Is(err, fs.ErrNotExist) {
			continue
		}
		if err != nil {
			return nil, err
		}
		conf := map[string]string{}
		for line := range strings.SplitSeq(string(data), "\n") {
			k, v, ok := strings.Cut(strings.TrimSpace(line), "=")
			if ok && !strings.HasPrefix(k, ";") && !strings.HasPrefix(k, "#") {
				conf[strings.TrimSpace(k)] = strings.TrimSpace(v)
			}
		}
		return conf, nil
	}
	return nil, fmt.Errorf("%w: this host holds no piler.conf", ErrUnsupported)
}

// clamavDB reads the version and age of the daily signature database of the local ClamAV from the
// header of daily.cld or daily.cvd, the newer of the two. It reads the 512 bytes of the header and
// nothing else of the file.
func clamavDB(ctx context.Context, _ Target) (map[string]any, error) {
	return untilDone(ctx, func() (map[string]any, error) {
		root, err := hostRoot()
		if err != nil {
			return nil, fmt.Errorf("the root of this host cannot be opened: %v", cause(err))
		}
		defer root.Close()
		version, built, found := 0, int64(0), false
		for _, name := range clamavDBFiles {
			v, b, err := cvdHeader(root, name)
			if errors.Is(err, fs.ErrNotExist) {
				continue
			}
			if err != nil {
				return nil, err
			}
			if !found || v > version {
				version, built, found = v, b, true
			}
		}
		if !found {
			return nil, fmt.Errorf("%w: this host holds no daily database of ClamAV", ErrUnsupported)
		}
		return map[string]any{"version": version, "age_s": max(now().Unix()-built, 0)}, nil
	})
}

// cvdHeader reads the version and build time of the database name below root from its header:
// "ClamAV-VDB:<build time>:<version>:<signatures>:<functionality level>:<md5>:<signature>:<builder>:
// <build time in seconds since the epoch>", padded to 512 bytes (docs.clamav.net, CVD format).
func cvdHeader(root *os.Root, name string) (version int, built int64, err error) {
	shown := "/" + name
	if _, err := root.Lstat(name); errors.Is(err, fs.ErrNotExist) {
		return 0, 0, fs.ErrNotExist
	}
	f, err := openRegular(root, name, shown)
	if err != nil {
		return 0, 0, err
	}
	defer f.Close()
	buf := make([]byte, cvdHeaderBytes)
	if _, err := io.ReadFull(f, buf); err != nil {
		return 0, 0, fmt.Errorf("%s holds no header of a ClamAV database", shown)
	}
	fields := strings.Split(string(buf), ":")
	if len(fields) < 9 || fields[0] != "ClamAV-VDB" {
		return 0, 0, fmt.Errorf("%s holds no header of a ClamAV database", shown)
	}
	version, err1 := strconv.Atoi(fields[2])
	built, err2 := strconv.ParseInt(strings.TrimRight(fields[8], " \x00"), 10, 64)
	if err1 != nil || err2 != nil || version <= 0 || built <= 0 {
		return 0, 0, fmt.Errorf("%s holds no version and build time of a ClamAV database", shown)
	}
	return version, built, nil
}

// spamdPing says whether the local spamd answers a PING of spamc -K. spamc prints spamd's answer,
// "SPAMD/<version> 0", and exits 0 only then: its safe fallback (exit 0 without spamd) does not hold for
// -K (spamc.c, main; libspamc.c, message_filter). A spamc that fails, takes too long or prints no such
// answer found no spamd answering.
func spamdPing(ctx context.Context, _ Target) (map[string]any, error) {
	out, err := runToolEnv(ctx, toolTimeout, []string{"LC_ALL=C"}, "spamc", "-K")
	var exitErr *exec.ExitError
	switch {
	case err == nil:
		return map[string]any{"reachable": spamdPong.Match(bytes.TrimSpace(out))}, nil
	case errors.Is(err, exec.ErrNotFound):
		return nil, fmt.Errorf("%w: spamc is not installed", ErrUnsupported)
	case errors.As(err, &exitErr), errors.Is(err, context.DeadlineExceeded) && ctx.Err() == nil:
		return map[string]any{"reachable": false}, nil
	}
	return nil, toolError("spamc", err)
}

// opendkimKeys tests the keys of the KeyTable of the local OpenDKIM against their records in the DNS
// with opendkim-testkey -v and counts them and those that fail, from its summary; with a KeyTable it
// exits 0 however many keys fail (opendkim-testkey.c, main). Which key fails and
// why it prints to its stderr, which names keys and domains; that stays on this host.
func opendkimKeys(ctx context.Context, _ Target) (map[string]any, error) {
	out, err := runToolEnv(ctx, toolTimeout, []string{"LC_ALL=C"}, "opendkim-testkey", "-v")
	var exitErr *exec.ExitError
	switch {
	case errors.Is(err, exec.ErrNotFound):
		return nil, fmt.Errorf("%w: opendkim-testkey is not installed", ErrUnsupported)
	case errors.As(err, &exitErr) && exitErr.ExitCode() == opendkimNoKeyTable:
		return nil, fmt.Errorf("%w: OpenDKIM signs without a KeyTable", ErrUnsupported)
	case errors.As(err, &exitErr):
		return nil, fmt.Errorf("opendkim-testkey fails with exit %d", exitErr.ExitCode())
	case err != nil:
		return nil, fmt.Errorf("opendkim-testkey: %w", err)
	}
	m := opendkimSummary.FindAllSubmatch(out, -1)
	if len(m) != 1 {
		return nil, errors.New("opendkim-testkey answers without its summary")
	}
	keys, err1 := strconv.Atoi(string(m[0][1]))
	failed, err2 := strconv.Atoi(string(m[0][3]))
	if err1 != nil || err2 != nil || failed > keys {
		return nil, errors.New("opendkim-testkey answers with a summary that does not add up")
	}
	return map[string]any{"keys": keys, "keys_failed": failed}, nil
}
