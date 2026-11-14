// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package probe

import (
	"bufio"
	"bytes"
	"context"
	"crypto/md5" //nolint:gosec // UrBackup's login protocol asks for it, no hash of ours
	"crypto/pbkdf2"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"io/fs"
	"net/http"
	"net/netip"
	"net/url"
	"os/exec"
	"regexp"
	"strconv"
	"strings"
	"time"
)

// --- BackupPC ---

// The paths of BackupPC_serverMesg, which is on no PATH: Debian and Ubuntu (checked against BackupPC
// 4.4.0 on Debian trixie), and EPEL (not verified). Each one is a call of the allowlist.
var backuppcMesg = []string{
	"/usr/share/backuppc/bin/BackupPC_serverMesg",
	"/usr/share/BackupPC/bin/BackupPC_serverMesg",
}

// backuppcStatus counts the hosts of the BackupPC server of this host: all, those whose last backup
// failed, those that did not answer the ping, those without a good backup, the running jobs, and the
// age of the oldest last good backup of a host. `BackupPC_serverMesg status hosts` runs as the user
// backuppc, as the server wants it; it reads the status and changes nothing. Never a host name.
//
// Checked against BackupPC 4.4.0: the answer is `Got reply: %Status = (<host> => {<key> => <value>,
// …}, …);` as Data::Dumper prints it, with per host state, activeJob, lastGoodBackupTime (epoch) and
// reason (Reason_backup_done seen). Not seen, from BackupPC's source: reason Reason_backup_failed and
// Reason_no_ping, and the jobs the server runs for itself under names that begin with a space
// (" admin ", " trashClean "), which are left out.
func backuppcStatus(ctx context.Context, _ Target) (map[string]any, error) {
	mesg := ""
	for _, p := range backuppcMesg {
		if _, err := statPath(p); err == nil {
			mesg = p
			break
		}
	}
	if mesg == "" {
		return nil, fmt.Errorf("%w: BackupPC is not installed", ErrUnsupported)
	}
	out, err := runTool(ctx, toolTimeout, "runuser", "-u", "backuppc", "--", mesg, "status", "hosts")
	if errors.Is(err, exec.ErrNotFound) {
		return nil, fmt.Errorf("%w: runuser is not installed", ErrUnsupported)
	}
	if err != nil {
		return nil, toolError("BackupPC_serverMesg", err)
	}
	hosts, err := backuppcHosts(out)
	if err != nil {
		return nil, err
	}
	n := map[string]int{}
	oldest := int64(-1)
	for name, h := range hosts {
		if strings.HasPrefix(name, " ") {
			continue
		}
		n["hosts"]++
		switch h.hash["reason"].text {
		case "Reason_backup_failed":
			n["hosts_failed"]++
		case "Reason_no_ping":
			n["hosts_no_ping"]++
		}
		if job, _ := strconv.ParseInt(h.hash["activeJob"].text, 10, 64); job != 0 {
			n["jobs_active"]++
		}
		good, err := strconv.ParseInt(h.hash["lastGoodBackupTime"].text, 10, 64)
		if err != nil || good <= 0 {
			n["hosts_never_backed_up"]++
			continue
		}
		oldest = max(oldest, ageSeconds(time.Unix(good, 0)))
	}
	values := map[string]any{}
	for _, k := range []string{"hosts", "hosts_failed", "hosts_no_ping", "hosts_never_backed_up", "jobs_active"} {
		values[k] = n[k]
	}
	if oldest >= 0 {
		values["backup_age_max_s"] = oldest
	}
	return values, nil
}

// ageSeconds is the age of t in whole seconds, 0 for a time ahead of the clock.
func ageSeconds(t time.Time) int64 {
	return max(0, int64(now().Sub(t)/time.Second))
}

// errBackupPCForm is the error of an answer of BackupPC_serverMesg that is no host status.
var errBackupPCForm = errors.New("BackupPC_serverMesg: an answer of another form")

// backuppcHosts reads the answer to `status hosts`: the hosts by name.
func backuppcHosts(out []byte) (map[string]perlValue, error) {
	rest, ok := bytes.CutPrefix(bytes.TrimSpace(out), []byte("Got reply: %Status = ("))
	if !ok {
		return nil, errBackupPCForm
	}
	p := &perlReader{src: rest}
	hosts, err := p.entries(")", 0)
	if err != nil {
		return nil, err
	}
	for _, h := range hosts {
		if h.hash == nil {
			return nil, errBackupPCForm
		}
	}
	if tok, quoted, err := p.next(); err != nil || quoted || tok != ";" || len(bytes.TrimSpace(p.src)) != 0 {
		return nil, errBackupPCForm
	}
	return hosts, nil
}

// perlValue is one value of a Data::Dumper text: a scalar (undef is the empty text), a hash with its
// entries, or a list, of which nothing is kept.
type perlValue struct {
	text string
	hash map[string]perlValue
}

// perlReader reads a Data::Dumper text: quoted strings, bare words (numbers, undef) and the signs
// ( ) { } [ ] , ; =>.
type perlReader struct {
	src []byte
}

// maxPerlDepth bounds the nesting of lists and hashes.
const maxPerlDepth = 8

const perlSigns = "(){}[],;"

// next returns the next token and whether it was a quoted string.
func (p *perlReader) next() (string, bool, error) {
	p.src = bytes.TrimLeft(p.src, " \t\r\n")
	if len(p.src) == 0 {
		return "", false, errBackupPCForm
	}
	c := p.src[0]
	switch {
	case bytes.HasPrefix(p.src, []byte("=>")):
		p.src = p.src[2:]
		return "=>", false, nil
	case strings.IndexByte(perlSigns, c) >= 0:
		p.src = p.src[1:]
		return string(c), false, nil
	case c == '"' || c == '\'':
		var b strings.Builder
		for i := 1; i < len(p.src); i++ {
			switch p.src[i] {
			case '\\':
				if i++; i < len(p.src) {
					b.WriteByte(p.src[i])
				}
			case c:
				p.src = p.src[i+1:]
				return b.String(), true, nil
			default:
				b.WriteByte(p.src[i])
			}
		}
		return "", false, errBackupPCForm
	}
	end := bytes.IndexAny(p.src, " \t\r\n=(){}[],;")
	if end < 0 {
		end = len(p.src)
	}
	if end == 0 {
		return "", false, errBackupPCForm
	}
	word := string(p.src[:end])
	p.src = p.src[end:]
	return word, false, nil
}

// entries reads the pairs key => value of a hash up to its closing sign.
func (p *perlReader) entries(closing string, depth int) (map[string]perlValue, error) {
	m := map[string]perlValue{}
	for {
		key, quoted, err := p.next()
		if err != nil {
			return nil, err
		}
		if !quoted && key == closing {
			return m, nil
		}
		if !quoted && key == "," {
			continue
		}
		if !quoted && strings.Contains(perlSigns+"=>", key) {
			return nil, errBackupPCForm
		}
		if arrow, q, err := p.next(); err != nil || q || arrow != "=>" {
			return nil, errBackupPCForm
		}
		v, err := p.value(depth)
		if err != nil {
			return nil, err
		}
		m[key] = v
	}
}

// value reads one value after "=>" or in a list.
func (p *perlReader) value(depth int) (perlValue, error) {
	tok, quoted, err := p.next()
	switch {
	case err != nil:
		return perlValue{}, err
	case quoted:
		return perlValue{text: tok}, nil
	case tok == "undef":
		return perlValue{}, nil
	case tok == "{" || tok == "[":
		if depth >= maxPerlDepth {
			return perlValue{}, errBackupPCForm
		}
		if tok == "{" {
			h, err := p.entries("}", depth+1)
			return perlValue{hash: h}, err
		}
		return perlValue{}, p.list(depth + 1)
	case strings.Contains(perlSigns+"=>", tok):
		return perlValue{}, errBackupPCForm
	}
	return perlValue{text: tok}, nil
}

// list passes over the elements of a list up to its "]".
func (p *perlReader) list(depth int) error {
	for {
		save := p.src
		tok, quoted, err := p.next()
		if err != nil {
			return err
		}
		if !quoted && tok == "]" {
			return nil
		}
		if !quoted && tok == "," {
			continue
		}
		p.src = save
		if _, err := p.value(depth); err != nil {
			return err
		}
	}
}

// --- UrBackup ---

// urbackupPort is the port of UrBackup's web interface.
const urbackupPort = 55414

// urbackupEndpoint finds where UrBackup listens; tests point it at their server.
var urbackupEndpoint = resolve

// maxUrBackupAnswer bounds an answer of UrBackup's web API.
const maxUrBackupAnswer = 4 << 20

// urbackupStatus counts the clients of the UrBackup server of this host through its web API on
// its own port, as its web interface does: all, those whose last file or image backup failed (a kind
// of backup that is turned off or not supported is no failure), those not seen for 24 hours, and the
// age of the oldest last file backup; and whether the server stopped for lack of space or reports a
// broken database. Never a client name. Without a credential it logs in as the anonymous user, which
// UrBackup has only while no web user is set up; else the credential is a web user (use basic,
// user:password) with the right status.
//
// Not verified against a running server: the protocol (GET /x?a=…, salt, login with md5 and PBKDF2,
// status) and the field names come from the author's Python wrapper
// (urbackup-server-python-web-api-wrapper), which sends the parameters in a POST body; that the server
// takes them in the query of a GET, which is all this agent sends, is assumed.
func urbackupStatus(ctx context.Context, t Target, c appCredential) (map[string]any, error) {
	switch t.Scheme {
	case "", "http":
	default:
		return nil, fmt.Errorf("%w: view urbackup_status takes no scheme %q", ErrInvalid, t.Scheme)
	}
	if t.PortHint == 0 {
		t.PortHint = urbackupPort
	}
	ep, err := urbackupEndpoint(ctx, t)
	if err != nil {
		return nil, err
	}
	if int(ep.port) != t.PortHint {
		return nil, fmt.Errorf("%w: %s %s does not listen on the port %d", ErrUnsupported, t.Kind, targetName(t), t.PortHint)
	}
	g := NewGuard(ep.extra...)
	user, password := "", ""
	if c.use != "" {
		var ok bool
		if user, password, ok = strings.Cut(c.secret, ":"); !ok || user == "" {
			return nil, fmt.Errorf("%w: a basic credential is user:password", ErrInvalid)
		}
		g = secretGuard(ep)
	}
	ub := &urbackupClient{
		client: g.HTTPClient(nil),
		base:   url.URL{Scheme: "http", Host: netip.AddrPortFrom(ep.addr, ep.port).String(), Path: "/x"},
	}
	ses, err := ub.login(ctx, user, password)
	if err != nil {
		return nil, err
	}
	var st struct {
		Status *[]struct {
			LastBackup        any  `json:"lastbackup"`
			LastSeen          any  `json:"lastseen"`
			FileOK            bool `json:"file_ok"`
			ImageOK           bool `json:"image_ok"`
			FileDisabled      bool `json:"file_disabled"`
			ImageDisabled     bool `json:"image_disabled"`
			ImageNotSupported bool `json:"image_not_supported"`
		} `json:"status"`
		NoSpaceFatal  *bool `json:"nospc_fatal"`
		DatabaseError *bool `json:"database_error"`
	}
	if err := ub.call(ctx, "status", url.Values{"ses": {ses}}, &st); err != nil {
		return nil, err
	}
	if st.Status == nil {
		return nil, errUrBackupForm
	}
	values := map[string]any{"clients": len(*st.Status)}
	fileFailed, imageFailed, unseen, oldest := 0, 0, 0, int64(-1)
	for _, cl := range *st.Status {
		if !cl.FileOK && !cl.FileDisabled {
			fileFailed++
		}
		if !cl.ImageOK && !cl.ImageDisabled && !cl.ImageNotSupported {
			imageFailed++
		}
		if seen, ok := epochOf(cl.LastSeen); !ok || ageSeconds(seen) > 24*3600 {
			unseen++
		}
		if last, ok := epochOf(cl.LastBackup); ok {
			oldest = max(oldest, ageSeconds(last))
		}
	}
	values["clients_file_failed"] = fileFailed
	values["clients_image_failed"] = imageFailed
	values["clients_unseen_24h"] = unseen
	if oldest >= 0 {
		values["file_backup_age_max_s"] = oldest
	}
	if st.NoSpaceFatal != nil {
		values["nospc_fatal"] = *st.NoSpaceFatal
	}
	if st.DatabaseError != nil {
		values["database_error"] = *st.DatabaseError
	}
	return values, nil
}

// epochOf reads a time UrBackup gives as seconds since the epoch; "-" or 0 is none.
func epochOf(v any) (time.Time, bool) {
	f, ok := v.(float64)
	if !ok || f <= 0 {
		return time.Time{}, false
	}
	return time.Unix(int64(f), 0), true
}

var errUrBackupForm = errors.New("UrBackup: an answer of another form")

// urbackupClient calls actions of UrBackup's web API.
type urbackupClient struct {
	client *http.Client
	base   url.URL
}

// login returns a session: the anonymous one without a user, else the one of user after the salted
// challenge of the web interface. The password itself never leaves the agent, only its hash with the
// server's one-time rnd.
func (ub *urbackupClient) login(ctx context.Context, user, password string) (string, error) {
	var anon struct {
		Success bool   `json:"success"`
		Session string `json:"session"`
	}
	if err := ub.call(ctx, "login", nil, &anon); err != nil {
		return "", err
	}
	if anon.Success && anon.Session != "" {
		return anon.Session, nil
	}
	if user == "" {
		return "", fmt.Errorf("%w: UrBackup wants a web user", ErrDenied)
	}
	var salt struct {
		Session string `json:"ses"`
		Salt    string `json:"salt"`
		Rnd     string `json:"rnd"`
		Rounds  int    `json:"pbkdf2_rounds"`
	}
	if err := ub.call(ctx, "salt", url.Values{"username": {user}}, &salt); err != nil {
		return "", err
	}
	if salt.Session == "" || salt.Salt == "" || salt.Rnd == "" || salt.Rounds < 0 || salt.Rounds > 10_000_000 {
		return "", fmt.Errorf("%w: UrBackup knows no such web user", ErrDenied)
	}
	hash, err := urbackupHash(salt.Salt, salt.Rnd, password, salt.Rounds)
	if err != nil {
		return "", err
	}
	var login struct {
		Success bool `json:"success"`
	}
	if err := ub.call(ctx, "login", url.Values{"username": {user}, "password": {hash}, "ses": {salt.Session}}, &login); err != nil {
		return "", err
	}
	if !login.Success {
		return "", fmt.Errorf("%w: UrBackup refuses the web user", ErrDenied)
	}
	return salt.Session, nil
}

// urbackupHash is the answer to UrBackup's login challenge: md5 of salt and password, with PBKDF2
// over it when the server asks for rounds, then md5 of rnd and that, as hex.
func urbackupHash(salt, rnd, password string, rounds int) (string, error) {
	inner := md5.Sum([]byte(salt + password)) //nolint:gosec // UrBackup's protocol
	h := hex.EncodeToString(inner[:])
	if rounds > 0 {
		key, err := pbkdf2.Key(sha256.New, string(inner[:]), []byte(salt), rounds, sha256.Size)
		if err != nil {
			return "", errors.New("UrBackup: the login hash cannot be made")
		}
		h = hex.EncodeToString(key)
	}
	outer := md5.Sum([]byte(rnd + h)) //nolint:gosec // UrBackup's protocol
	return hex.EncodeToString(outer[:]), nil
}

// call sends GET /x?a=<action>&<params> and decodes the JSON answer into v.
func (ub *urbackupClient) call(ctx context.Context, action string, params url.Values, v any) error {
	q := url.Values{"a": {action}}
	for k, vs := range params {
		q[k] = vs
	}
	u := ub.base
	u.RawQuery = q.Encode()
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, u.String(), nil)
	if err != nil {
		return errors.New("the request to UrBackup cannot be built")
	}
	resp, err := ub.client.Do(req)
	if err != nil {
		var ue *url.Error
		if errors.As(err, &ue) {
			err = ue.Err // the URL carries the session and the login hash
		}
		return netErr(ctx, err)
	}
	defer resp.Body.Close()
	switch resp.StatusCode {
	case http.StatusOK:
	case http.StatusUnauthorized, http.StatusForbidden:
		return fmt.Errorf("%w: HTTP %d", ErrDenied, resp.StatusCode)
	default:
		return fmt.Errorf("UrBackup answers %s with HTTP %d", action, resp.StatusCode)
	}
	body, err := io.ReadAll(io.LimitReader(resp.Body, maxUrBackupAnswer+1))
	if err != nil {
		return netErr(ctx, err)
	}
	if len(body) > maxUrBackupAnswer || json.Unmarshal(body, v) != nil {
		return errUrBackupForm
	}
	return nil
}

// --- rsnapshot ---

// rsnapshotConfigs are the places of rsnapshot's configuration: Linux packages and FreeBSD's port.
var rsnapshotConfigs = []string{"/etc/rsnapshot.conf", "/usr/local/etc/rsnapshot.conf"}

// The limits of what rsnapshotStatus reads: the configuration whole, of its log only the end.
const (
	maxRsnapshotConfig = 1 << 20
	rsnapshotLogTail   = 256 << 10
)

// rsnapshotLine is one line of rsnapshot's log: `[<time>] <command> <args>: <message>`.
var rsnapshotLine = regexp.MustCompile(`^\[([^\]]+)\] .*?: (started|completed successfully|completed, but with some warnings|ERROR: .*)$`)

// rsnapshotTimes are the forms of the time in rsnapshot's log, in local time: 1.4 and later (checked
// against 1.5.1), and 1.3 (not verified).
var rsnapshotTimes = []string{"2006-01-02T15:04:05", "02/Jan/2006:15:04:05"}

// rsnapshotStatus reads how the last run of rsnapshot ended from its log: last_status ok, warning or
// error ("none" when the end of the log holds no finished run), the age of the last run that
// completed successfully, whether a run is going on, and whether its lock file stays without an
// rsnapshot process (a crashed run leaves it, and every later run refuses to start). rsnapshot has no
// unit, cron starts it; the log is optional in its configuration, so without logfile the view is
// unsupported. It never runs rsnapshot, du or diff: they walk or rotate the snapshots.
func rsnapshotStatus(ctx context.Context) (map[string]any, error) {
	var conf []byte
	for _, p := range rsnapshotConfigs {
		b, err := readSmallFile(p, maxRsnapshotConfig)
		if errors.Is(err, fs.ErrNotExist) {
			continue
		}
		if err != nil {
			return nil, fmt.Errorf("rsnapshot's configuration: %w", err)
		}
		conf = b
		break
	}
	if conf == nil {
		return nil, fmt.Errorf("%w: rsnapshot is not installed", ErrUnsupported)
	}
	logfile, lockfile := rsnapshotSetting(conf, "logfile"), rsnapshotSetting(conf, "lockfile")
	if logfile == "" {
		return nil, fmt.Errorf("%w: rsnapshot writes no log (logfile)", ErrUnsupported)
	}
	if !validLocalPath(logfile) || (lockfile != "" && !validLocalPath(lockfile)) {
		return nil, errors.New("rsnapshot's configuration names a logfile or lockfile that is no local path")
	}
	tail, err := readTail(logfile, rsnapshotLogTail)
	if errors.Is(err, fs.ErrNotExist) {
		return map[string]any{"last_status": "none", "running": false, "lock_stale": false}, nil
	}
	if err != nil {
		return nil, fmt.Errorf("rsnapshot's log: %w", err)
	}
	values := rsnapshotRuns(tail)
	procs, err := findProcesses(ctx, "rsnapshot")
	if err != nil {
		return nil, err
	}
	values["running"] = len(procs) > 0
	locked := false
	if lockfile != "" {
		_, err := statPath(lockfile)
		locked = err == nil
	}
	values["lock_stale"] = locked && len(procs) == 0
	return values, nil
}

// rsnapshotSetting is the value of the last line `<name>\t<value>` of rsnapshot's configuration, ""
// without one. rsnapshot separates the two by tabs only.
func rsnapshotSetting(conf []byte, name string) string {
	value := ""
	sc := bufio.NewScanner(bytes.NewReader(conf))
	for sc.Scan() {
		k, v, ok := strings.Cut(sc.Text(), "\t")
		if ok && k == name {
			value = strings.TrimSpace(v)
		}
	}
	return value
}

// rsnapshotRuns reads the runs in the log's end: the last one that ended decides last_status.
func rsnapshotRuns(log []byte) map[string]any {
	status := "none"
	var success time.Time
	for line := range strings.Lines(string(log)) {
		m := rsnapshotLine.FindStringSubmatch(strings.TrimRight(line, "\r\n"))
		if m == nil {
			continue
		}
		var at time.Time
		for _, layout := range rsnapshotTimes {
			if t, err := time.ParseInLocation(layout, m[1], time.Local); err == nil {
				at = t
				break
			}
		}
		switch {
		case m[2] == "completed successfully":
			status, success = "ok", at
		case m[2] == "completed, but with some warnings":
			status = "warning"
		case strings.HasPrefix(m[2], "ERROR: "):
			status = "error"
		}
	}
	values := map[string]any{"last_status": status}
	if !success.IsZero() {
		values["last_success_age_s"] = ageSeconds(success)
	}
	return values
}

// readTail reads the last limit bytes of the regular file path; a first line cut in half is dropped.
func readTail(path string, limit int64) ([]byte, error) {
	f, err := openFile(path)
	if err != nil {
		return nil, err
	}
	defer f.Close()
	fi, err := f.Stat()
	if err != nil {
		return nil, err
	}
	cut := fi.Size() > limit
	if cut {
		if _, err := f.Seek(-limit, io.SeekEnd); err != nil {
			return nil, err
		}
	}
	b, err := io.ReadAll(io.LimitReader(f, limit))
	if err != nil {
		return nil, err
	}
	if cut {
		if i := bytes.IndexByte(b, '\n'); i >= 0 {
			b = b[i+1:]
		}
	}
	return b, nil
}

// --- Veeam ---

// veeamTimes are the forms of the times in `veeamconfig session list` (not verified).
var veeamTimes = []string{"2006-01-02 15:04:05", "2006-01-02 15:04"}

var errVeeamForm = errors.New("veeamconfig: an answer of another form")

// veeamSessions counts the jobs of Veeam Agent for Linux from `veeamconfig session list`: all jobs,
// those whose last finished session failed or ended with a warning, the sessions running, and the
// age of the oldest last successful session of a job. Never a job name.
//
// Not verified: Veeam documents `session list` without its output. The view takes a table with a
// header that names the columns Job name, State, Started at and Finished at, read by the columns'
// positions in the header, states Success, Warning, Failed and Running, and a closing line "Total
// amount: N"; any other answer is an error, not a guess. A row without a job name is no backup
// job's session (a restore) and is left out.
func veeamSessions(ctx context.Context, _ Target) (map[string]any, error) {
	out, err := runTool(ctx, toolTimeout, "veeamconfig", "session", "list")
	if errors.Is(err, exec.ErrNotFound) {
		return nil, fmt.Errorf("%w: Veeam Agent is not installed", ErrUnsupported)
	}
	if err != nil {
		return nil, toolError("veeamconfig", err)
	}
	return veeamValues(out)
}

// veeamSession is one row of `veeamconfig session list`.
type veeamSession struct {
	job, state string
	at         time.Time
}

func veeamValues(out []byte) (map[string]any, error) {
	lines := strings.Split(strings.ReplaceAll(string(out), "\r\n", "\n"), "\n")
	head := -1
	for i, l := range lines {
		if strings.HasPrefix(strings.TrimSpace(l), "Job name") {
			head = i
			break
		}
	}
	if head < 0 {
		return nil, errVeeamForm
	}
	cols := map[string]int{}
	for _, name := range []string{"Job name", "Type", "ID", "State", "Started at", "Finished at"} {
		cols[name] = strings.Index(lines[head], name)
	}
	if cols["Job name"] < 0 || cols["State"] < 0 || cols["Started at"] < 0 || cols["Finished at"] < 0 {
		return nil, errVeeamForm
	}
	starts := []int{}
	for _, at := range cols {
		if at >= 0 {
			starts = append(starts, at)
		}
	}
	field := func(l string, col string) string {
		from := cols[col]
		to := len(l)
		for _, s := range starts {
			if s > from && s < to {
				to = s
			}
		}
		if from >= len(l) {
			return ""
		}
		return strings.TrimSpace(l[from:min(to, len(l))])
	}
	var sessions []veeamSession
	closed := false
	for _, l := range lines[head+1:] {
		switch t := strings.TrimSpace(l); {
		case t == "" || strings.Trim(t, "-= ") == "":
			continue
		case strings.HasPrefix(t, "Total amount:"):
			closed = true
		case closed:
			return nil, errVeeamForm
		default:
			s := veeamSession{job: field(l, "Job name"), state: field(l, "State")}
			if s.state == "" {
				return nil, errVeeamForm
			}
			if s.job == "" {
				// A restore session has no job name (Veeam documents it so for session info); it
				// is no backup of a job.
				continue
			}
			stamp := field(l, "Finished at")
			if stamp == "" {
				stamp = field(l, "Started at")
			}
			for _, layout := range veeamTimes {
				if t, err := time.ParseInLocation(layout, stamp, time.Local); err == nil {
					s.at = t
					break
				}
			}
			sessions = append(sessions, s)
		}
	}
	if !closed {
		return nil, errVeeamForm
	}
	return veeamCount(sessions)
}

// veeamCount reduces the sessions to the values of veeam_sessions. Of each job the newest finished
// session decides; a session without a time that can be read is an error.
func veeamCount(sessions []veeamSession) (map[string]any, error) {
	type job struct {
		last, success time.Time
		state         string
	}
	jobs := map[string]*job{}
	running := 0
	for _, s := range sessions {
		j := jobs[s.job]
		if j == nil {
			j = &job{}
			jobs[s.job] = j
		}
		switch s.state {
		case "Running":
			running++
			continue
		case "Success", "Warning", "Failed":
		default:
			return nil, fmt.Errorf("veeamconfig: a session in the state %q", cutRunes(s.state, 32))
		}
		if s.at.IsZero() {
			return nil, errVeeamForm
		}
		if !s.at.Before(j.last) {
			j.last, j.state = s.at, s.state
		}
		if s.state == "Success" && s.at.After(j.success) {
			j.success = s.at
		}
	}
	failed, warning, oldest := 0, 0, int64(-1)
	for _, j := range jobs {
		switch j.state {
		case "Failed":
			failed++
		case "Warning":
			warning++
		}
		if !j.success.IsZero() {
			oldest = max(oldest, ageSeconds(j.success))
		}
	}
	values := map[string]any{"jobs": len(jobs), "jobs_failed": failed, "jobs_warning": warning, "sessions_running": running}
	if oldest >= 0 {
		values["last_success_age_max_s"] = oldest
	}
	return values, nil
}
