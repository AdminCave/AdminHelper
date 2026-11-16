// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package probe

import (
	"bytes"
	"context"
	"database/sql/driver"
	"errors"
	"fmt"
	"io"
	"net"
	"net/netip"
	"regexp"
	"slices"
	"strconv"
	"strings"
	"time"

	"github.com/go-sql-driver/mysql"
)

const (
	// wpCronMaxBytes caps the option cron the agent reads; a site with thousands of events stays far below.
	wpCronMaxBytes = 1 << 20
	// wpCronMaxDepth and wpCronMaxValues bound the parse of the option: an event nests four arrays deep, its
	// arguments may nest further.
	wpCronMaxDepth  = 32
	wpCronMaxValues = 200000
	// wpCronLate is how long an event may be due before it counts as overdue: WP-Cron runs due events on a
	// later request, so a few minutes are normal.
	wpCronLate = 10 * time.Minute
)

// errPHPForm is the error of an option not in the form of PHP's serialize(); it quotes nothing of the option.
var errPHPForm = errors.New("the option is not in the form of PHP's serialize()")

// phpValue is a value of PHP's serialize(): kind is its tag (N, b, i, d, s, a or O); num holds an int or a
// bool, items the pairs of an array or the properties of an object. The text of a string is not kept:
// nothing the view reports reads it.
type phpValue struct {
	kind  byte
	num   int64
	items []phpItem
}

type phpItem struct{ key, val phpValue }

type phpParser struct {
	data   []byte
	pos    int
	values int
}

// parsePHP parses data, the whole of one value of serialize(). It takes the tags WordPress writes into its
// options (no references, no custom serialization) and fails on anything else.
func parsePHP(data []byte) (phpValue, error) {
	p := &phpParser{data: data}
	v, err := p.value(0)
	if err != nil {
		return phpValue{}, err
	}
	if p.pos != len(p.data) {
		return phpValue{}, errPHPForm
	}
	return v, nil
}

func (p *phpParser) value(depth int) (phpValue, error) {
	p.values++
	if depth > wpCronMaxDepth || p.values > wpCronMaxValues || p.pos >= len(p.data) {
		return phpValue{}, errPHPForm
	}
	v := phpValue{kind: p.data[p.pos]}
	p.pos++
	if v.kind == 'N' {
		return v, p.expect(";")
	}
	if err := p.expect(":"); err != nil {
		return phpValue{}, err
	}
	var err error
	switch v.kind {
	case 'b':
		if v.num, err = p.integer(';'); err == nil && v.num != 0 && v.num != 1 {
			err = errPHPForm
		}
	case 'i':
		v.num, err = p.integer(';')
	case 'd':
		err = p.float()
	case 's':
		if err = p.str(); err == nil {
			err = p.expect(";")
		}
	case 'a':
		v.items, err = p.pairs(depth, false)
	case 'O':
		if err = p.str(); err == nil {
			if err = p.expect(":"); err == nil {
				v.items, err = p.pairs(depth, true)
			}
		}
	default:
		err = errPHPForm
	}
	if err != nil {
		return phpValue{}, err
	}
	return v, nil
}

// pairs reads `<n>:{` and n pairs of key and value up to `}`; the keys of an array are ints or strings, those
// of an object strings.
func (p *phpParser) pairs(depth int, object bool) ([]phpItem, error) {
	n, err := p.integer(':')
	if err != nil || n < 0 || n > int64(len(p.data)-p.pos) {
		return nil, errPHPForm
	}
	if err := p.expect("{"); err != nil {
		return nil, err
	}
	var items []phpItem
	for range n {
		key, err := p.value(depth + 1)
		if err != nil {
			return nil, err
		}
		if key.kind != 's' && (object || key.kind != 'i') {
			return nil, errPHPForm
		}
		val, err := p.value(depth + 1)
		if err != nil {
			return nil, err
		}
		items = append(items, phpItem{key, val})
	}
	return items, p.expect("}")
}

// str skips `<len>:"<len bytes>"`.
func (p *phpParser) str() error {
	n, err := p.integer(':')
	if err != nil || n < 0 || n > int64(len(p.data)-p.pos) {
		return errPHPForm
	}
	if err := p.expect(`"`); err != nil {
		return err
	}
	if int64(len(p.data)-p.pos) < n {
		return errPHPForm
	}
	p.pos += int(n)
	return p.expect(`"`)
}

// integer reads a decimal int64, an optional '-' before it, and the byte end after it. The loop stops after
// 20 digits, one more than an int64 holds, so that ParseInt refuses a longer number without the parser
// walking all of it.
func (p *phpParser) integer(end byte) (int64, error) {
	start := p.pos
	if p.pos < len(p.data) && p.data[p.pos] == '-' {
		p.pos++
	}
	digits := p.pos
	for p.pos < len(p.data) && p.pos-digits < 20 && p.data[p.pos] >= '0' && p.data[p.pos] <= '9' {
		p.pos++
	}
	if p.pos == digits || p.pos >= len(p.data) || p.data[p.pos] != end {
		return 0, errPHPForm
	}
	n, err := strconv.ParseInt(string(p.data[start:p.pos]), 10, 64)
	if err != nil {
		return 0, errPHPForm
	}
	p.pos++
	return n, nil
}

// float skips a float up to its ';': digits, sign, point, exponent, or PHP's INF and NAN.
func (p *phpParser) float() error {
	start := p.pos
	for p.pos < len(p.data) && p.pos-start <= 64 && p.data[p.pos] != ';' {
		switch c := p.data[p.pos]; {
		case c >= '0' && c <= '9', c == '-', c == '+', c == '.', c == 'E', c == 'e', c == 'I', c == 'N', c == 'F', c == 'A':
			p.pos++
		default:
			return errPHPForm
		}
	}
	if p.pos == start {
		return errPHPForm
	}
	return p.expect(";")
}

func (p *phpParser) expect(s string) error {
	if len(p.data)-p.pos < len(s) || string(p.data[p.pos:p.pos+len(s)]) != s {
		return errPHPForm
	}
	p.pos += len(s)
	return nil
}

// wpCronCounts counts the events of WordPress's option cron, as _get_cron_array() reads it: an array of
// timestamps, each an array of hooks, each an array of events by the hash of their arguments; the key
// version and any other string key are no timestamp. It returns events (all of them), overdue (those due
// for longer than wpCronLate at now) and oldest_overdue_s (how long the oldest overdue event has been due,
// 0 without one) and nothing else of the option.
func wpCronCounts(data []byte, now time.Time) (map[string]any, error) {
	if len(data) > wpCronMaxBytes {
		return nil, errPHPForm
	}
	v, err := parsePHP(data)
	if err != nil {
		return nil, err
	}
	if v.kind != 'a' {
		return nil, errPHPForm
	}
	late := now.Add(-wpCronLate).Unix()
	var events, overdue, oldest int64
	for _, ts := range v.items {
		if ts.key.kind != 'i' {
			continue
		}
		if ts.val.kind != 'a' {
			return nil, errPHPForm
		}
		for _, hook := range ts.val.items {
			if hook.val.kind != 'a' {
				return nil, errPHPForm
			}
			n := int64(len(hook.val.items))
			events += n
			if n > 0 && ts.key.num < late {
				overdue += n
				oldest = max(oldest, now.Unix()-ts.key.num)
			}
		}
	}
	return map[string]any{"events": events, "overdue": overdue, "oldest_overdue_s": oldest}, nil
}

// wpDBTimeout bounds the dial, every read and write of the connection to the database, and the query.
const wpDBTimeout = 5 * time.Second

var (
	// wpDBIdent is a name of a database or a user the view takes, wpDBPrefix a table prefix: the characters
	// WordPress allows in a table prefix. Anything else stays unsupported rather than quoted into SQL.
	wpDBIdent  = regexp.MustCompile(`^[A-Za-z0-9_]{1,64}$`)
	wpDBPrefix = regexp.MustCompile(`^[A-Za-z0-9_]{0,20}$`)
	// wpDBHostName is WORDPRESS_DB_HOST as a host name, without a port or with MySQL's 3306.
	wpDBHostName = regexp.MustCompile(`^([A-Za-z0-9][A-Za-z0-9_.-]{0,62})(:3306)?$`)
	// wpDBSockets are where the images mariadb and mysql put the server's socket, below the root of the
	// container; /var/run is a link to /run in both.
	wpDBSockets = []string{"run/mysqld/mysqld.sock", "var/run/mysqld/mysqld.sock"}
	// dialSocket connects to the first of wpDBSockets below root that is a socket.
	dialSocket = dialRootSocket

	// errWPSocket heads the errors of dialSocket; they name the socket, never where a link leads.
	errWPSocket = errors.New("the socket of its database")
)

// wpDB is the database of a WordPress container as its environment names it.
type wpDB struct {
	host, user, password, name, prefix string
}

// wpDBOf reads the database of WordPress from env, the environment of a container of the image wordpress,
// the way the image's wp-config-docker.php does: unset, WORDPRESS_DB_HOST, WORDPRESS_DB_NAME and
// WORDPRESS_TABLE_PREFIX take the image's defaults; user and password have none (the image's are
// placeholders). Its errors name variables, never their values.
func wpDBOf(env []string) (wpDB, error) {
	vars := map[string]string{}
	for _, kv := range env {
		if k, v, ok := strings.Cut(kv, "="); ok {
			vars[k] = v
		}
	}
	for _, k := range []string{"WORDPRESS_DB_HOST", "WORDPRESS_DB_USER", "WORDPRESS_DB_PASSWORD", "WORDPRESS_DB_NAME", "WORDPRESS_TABLE_PREFIX"} {
		if _, ok := vars[k+"_FILE"]; ok {
			return wpDB{}, fmt.Errorf("%w: %s_FILE names a file the view does not read", ErrUnsupported, k)
		}
	}
	for _, k := range []string{"WORDPRESS_DB_USER", "WORDPRESS_DB_PASSWORD"} {
		if _, ok := vars[k]; !ok {
			return wpDB{}, fmt.Errorf("%w: it sets no %s", ErrUnsupported, k)
		}
	}
	or := func(k, def string) string {
		if v, ok := vars[k]; ok {
			return v
		}
		return def
	}
	db := wpDB{
		user: vars["WORDPRESS_DB_USER"], password: vars["WORDPRESS_DB_PASSWORD"],
		name: or("WORDPRESS_DB_NAME", "wordpress"), prefix: or("WORDPRESS_TABLE_PREFIX", "wp_"),
	}
	host := wpDBHostName.FindStringSubmatch(or("WORDPRESS_DB_HOST", "mysql"))
	if host == nil {
		return wpDB{}, fmt.Errorf("%w: WORDPRESS_DB_HOST is no host name with port 3306 or none", ErrUnsupported)
	}
	if _, err := netip.ParseAddr(host[1]); err == nil {
		return wpDB{}, fmt.Errorf("%w: WORDPRESS_DB_HOST is an address, no name of a container", ErrUnsupported)
	}
	db.host = host[1]
	for k, ok := range map[string]bool{
		"WORDPRESS_DB_USER":      wpDBIdent.MatchString(db.user),
		"WORDPRESS_DB_NAME":      wpDBIdent.MatchString(db.name),
		"WORDPRESS_TABLE_PREFIX": wpDBPrefix.MatchString(db.prefix),
	} {
		if !ok {
			return wpDB{}, fmt.Errorf("%w: %s holds characters the view does not take", ErrUnsupported, k)
		}
	}
	return db, nil
}

// wpDBContainer finds the container of the database host: the one container on this host that carries host
// as an alias or DNS name in a network it shares with wp, a running one before stopped ones. It must run, from
// the image mariadb or mysql; mariadb tells which.
func wpDBContainer(ctx context.Context, wp containerInfo, host string) (db containerInfo, mariadb bool, err error) {
	list, err := inspectAllContainers(ctx)
	if err != nil {
		return containerInfo{}, false, err
	}
	// A stopped container keeps its names, but only a running one answers to them.
	var found, running []containerInfo
	for _, c := range list {
		if c.ID != wp.ID && carriesName(c, wp, host) {
			found = append(found, c)
			if c.State.Running {
				running = append(running, c)
			}
		}
	}
	if len(running) > 0 {
		found = running
	}
	switch {
	case len(found) == 0:
		return containerInfo{}, false, fmt.Errorf("%w: no container in a network of it carries the name of WORDPRESS_DB_HOST", ErrUnsupported)
	case len(found) > 1:
		return containerInfo{}, false, fmt.Errorf("%w: more than one container in a network of it carries the name of WORDPRESS_DB_HOST", ErrUnsupported)
	}
	db = found[0]
	switch imageBase(db.Config.Image) {
	case "mariadb":
		mariadb = true
	case "mysql":
	default:
		return containerInfo{}, false, fmt.Errorf("%w: the container of its database runs neither the image mariadb nor mysql", ErrUnsupported)
	}
	if !db.State.Running || db.State.Pid <= 0 {
		return containerInfo{}, false, errors.New("the container of its database is not running")
	}
	return db, mariadb, nil
}

// carriesName tells if c carries name as an alias or a DNS name in a network it shares with wp; docker's
// names are of any case.
func carriesName(c, wp containerInfo, name string) bool {
	same := func(s string) bool { return strings.EqualFold(s, name) }
	for nw, n := range c.NetworkSettings.Networks {
		if _, shared := wp.NetworkSettings.Networks[nw]; shared && (slices.ContainsFunc(n.Aliases, same) || slices.ContainsFunc(n.DNSNames, same)) {
			return true
		}
	}
	return false
}

// imageBase is the last part of the repository of image, without registry, tag and digest
// ("docker.io/library/mariadb:11@sha256:…" → "mariadb").
func imageBase(image string) string {
	image, _, _ = strings.Cut(image, "@")
	if i := strings.LastIndex(image, ":"); i > strings.LastIndex(image, "/") {
		image = image[:i]
	}
	return image[strings.LastIndex(image, "/")+1:]
}

// wpCronQuery is the one query of the view: the option cron of the site, if it is no larger than the view
// reads, with the statement bounded on the server as well. prefix matches wpDBPrefix.
func wpCronQuery(prefix string, mariadb bool) string {
	const sel = "option_value FROM `%soptions` WHERE option_name = 'cron' AND LENGTH(option_value) <= %d"
	if mariadb {
		return fmt.Sprintf("SET STATEMENT max_statement_time=%d FOR SELECT "+sel, int(wpDBTimeout.Seconds()), prefix, wpCronMaxBytes)
	}
	return fmt.Sprintf("SELECT /*+ MAX_EXECUTION_TIME(%d) */ "+sel, wpDBTimeout.Milliseconds(), prefix, wpCronMaxBytes)
}

// readWPCron reads the option cron of db over the one connection dial opens.
func readWPCron(ctx context.Context, dial func(context.Context) (net.Conn, error), db wpDB, mariadb bool) ([]byte, error) {
	cfg := mysql.NewConfig()
	cfg.User, cfg.Passwd, cfg.DBName = db.user, db.password, db.name
	cfg.Net = "unix"
	var guard *wpDBGuard
	cfg.DialFunc = func(ctx context.Context, _, _ string) (net.Conn, error) {
		c, err := dial(ctx)
		if err != nil {
			return nil, err
		}
		guard = &wpDBGuard{Conn: c, budget: wpDBReadBudget}
		return guard, nil
	}
	// The driver turns the guard's error into its own bad connection: the guard still knows why it stopped.
	dbError := func(err error) error {
		if guard != nil && guard.err != nil {
			return guard.err
		}
		return wpDBError(err)
	}
	cfg.Timeout, cfg.ReadTimeout, cfg.WriteTimeout = wpDBTimeout, wpDBTimeout, wpDBTimeout
	cfg.Logger = quietLogger{}
	connector, err := mysql.NewConnector(cfg)
	if err != nil {
		return nil, errors.New("the connection to its database cannot be set up")
	}
	ctx, cancel := context.WithTimeout(ctx, 2*wpDBTimeout)
	defer cancel()
	conn, err := connector.Connect(ctx)
	if err != nil {
		return nil, dbError(err)
	}
	defer conn.Close()
	q, ok := conn.(driver.QueryerContext)
	if !ok {
		return nil, errors.New("the connection to its database takes no query")
	}
	rows, err := q.QueryContext(ctx, wpCronQuery(db.prefix, mariadb), nil)
	if err != nil {
		return nil, dbError(err)
	}
	defer rows.Close()
	if len(rows.Columns()) != 1 {
		return nil, errors.New("its database answers the query with another form")
	}
	dest := make([]driver.Value, 1)
	switch err := rows.Next(dest); {
	case errors.Is(err, io.EOF):
		return nil, fmt.Errorf("its database holds no option cron of at most %d bytes", wpCronMaxBytes)
	case err != nil:
		return nil, dbError(err)
	}
	value, ok := dest[0].([]byte)
	if !ok {
		return nil, errors.New("its database answers the query with another form")
	}
	return bytes.Clone(value), nil
}

// wpDBReadBudget is all the view reads from the database server on its connection: the option cron of at most
// wpCronMaxBytes with the handshake, the column and the frames around it.
const wpDBReadBudget = 2 << 20

// errWPDBServer is what wpDBGuard returns once the server sends more or another form than the view reads.
var errWPDBServer = errors.New("its database sends more than the view reads")

// wpDBGuard bounds what the database server sends before the driver sees it: the driver allocates by the
// lengths the server names (a packet, the count of columns of a result) and a runtime out of memory is no
// panic the probe recovers from. It reads the frames of the protocol as they pass (4 bytes of header, then the
// payload; the connection carries neither TLS nor compression), takes no more than budget bytes in all and,
// after the client sends its query (COM_QUERY), lets through only an error or a result of exactly one column.
type wpDBGuard struct {
	net.Conn
	budget int
	hdr    [4]byte
	nhdr   int
	left   int  // bytes of the current payload not passed yet
	query  bool // the query went out; the next payload of the server is its answer
	answer bool // the next byte passed is the first of the answer
	err    error
}

func (g *wpDBGuard) Write(p []byte) (int, error) {
	// The driver writes each packet in one call, its header first; the command is the payload's first byte.
	if len(p) > 4 && p[3] == 0 && p[4] == 0x03 {
		g.query = true
	}
	return g.Conn.Write(p)
}

func (g *wpDBGuard) Read(p []byte) (int, error) {
	if g.err != nil {
		return 0, g.err
	}
	n, err := g.Conn.Read(p)
	for i := 0; i < n; {
		if g.left == 0 {
			g.hdr[g.nhdr] = p[i]
			g.nhdr++
			i++
			if g.nhdr < len(g.hdr) {
				continue
			}
			g.nhdr = 0
			g.left = int(g.hdr[0]) | int(g.hdr[1])<<8 | int(g.hdr[2])<<16
			if g.budget -= len(g.hdr) + g.left; g.budget < 0 {
				return g.fail()
			}
			g.answer, g.query = g.query && g.left > 0, false
			continue
		}
		if g.answer {
			// The query is a SELECT: its answer is an error or a result set of one column, whose count opens
			// it. Any other count, 0xfe (8 bytes of it) and 0xfb (a local file) stop; so does an OK, after
			// which the driver would read the next result set unguarded.
			if b := p[i]; b != 0x01 && b != 0xff {
				return g.fail()
			}
			g.answer = false
		}
		step := min(g.left, n-i)
		g.left -= step
		i += step
	}
	return n, err
}

func (g *wpDBGuard) fail() (int, error) {
	g.err = errWPDBServer
	g.Conn.Close()
	return 0, g.err
}

// wpDBError tells what failed of the connection to the database without the server's text or the driver's:
// the server's messages quote the user.
func wpDBError(err error) error {
	var me *mysql.MySQLError
	var oe *net.OpError
	switch {
	case errors.Is(err, errWPSocket):
		return err
	case errors.As(err, &me):
		return fmt.Errorf("its database refuses with error %d", me.Number)
	case errors.Is(err, context.DeadlineExceeded) || errors.As(err, &oe) && oe.Timeout():
		return fmt.Errorf("its database does not answer within %s", wpDBTimeout)
	default:
		return errors.New("the connection to its database fails")
	}
}

// quietLogger drops what the driver logs: nothing of the database goes to the agent's log.
type quietLogger struct{}

func (quietLogger) Print(...any) {}

// wordpressCron counts the events of WP-Cron of the running WordPress container t, from the option cron of
// its site's database. It reaches the database only through the unix socket of the database's container on
// this host, logs in with the user and password of t's environment and asks one fixed query; user and
// password stay in memory for that one connection and go into no error and no value.
func wordpressCron(ctx context.Context, t Target) (map[string]any, error) {
	c, err := inspectContainer(ctx, t.Name)
	if err != nil {
		return nil, err
	}
	if !c.State.Running || c.State.Pid <= 0 {
		return nil, fmt.Errorf("container %s is not running", t.Name)
	}
	db, err := wpDBOf(c.Config.Env)
	if err != nil {
		return nil, fmt.Errorf("container %s: %w", t.Name, err)
	}
	server, mariadb, err := wpDBContainer(ctx, c, db.host)
	if err != nil {
		return nil, fmt.Errorf("container %s: %w", t.Name, err)
	}
	root, err := containerRoot(server.State.Pid, server.ID)
	if errors.Is(err, ErrUnsupported) {
		return nil, err
	}
	if err != nil {
		return nil, fmt.Errorf("container %s: the root of its database cannot be opened: %v", t.Name, cause(err))
	}
	defer root.Close()
	dial := func(ctx context.Context) (net.Conn, error) { return dialSocket(ctx, root) }
	data, err := readWPCron(ctx, dial, db, mariadb)
	if err != nil {
		return nil, fmt.Errorf("container %s: %w", t.Name, err)
	}
	counts, err := wpCronCounts(data, now())
	if err != nil {
		return nil, fmt.Errorf("container %s: %w", t.Name, err)
	}
	return counts, nil
}
