// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package probe

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io/fs"
	"net"
	"net/netip"
	"os"
	"path/filepath"
	"regexp"
	"runtime"
	"slices"
	"strconv"
	"strings"
)

const (
	// maxFPMFiles, maxFPMFileBytes and maxFPMPools cap what fpmPools reads of the pool directory.
	maxFPMFiles     = 256
	maxFPMFileBytes = 1 << 20
	maxFPMPools     = 128
	// maxFPMStatusPath caps pm.status_path: fcgiPair takes values shorter than 128 bytes, and
	// REQUEST_URI is the path with "?json".
	maxFPMStatusPath = 122
)

var (
	// fpmPoolDir is the pool directory of a PHP-FPM unit; tests stand in their own.
	fpmPoolDir = poolDirOf
	// fpmDialUnix and fpmEndpoint reach the socket of a pool; tests stand in their own.
	fpmDialUnix = dialUnix
	fpmEndpoint = resolve
	// debianFPM is the unit of PHP-FPM on Debian and Ubuntu, php<version>-fpm.
	debianFPM = regexp.MustCompile(`^php([0-9]+\.[0-9]+)-fpm$`)
)

// fpmPool is a pool of a PHP-FPM configuration with the settings fpmPools reads.
type fpmPool struct {
	listen, statusPath, allowedClients string
}

// fpmStatus are the counters of the status page fpmPools adds up.
type fpmStatus struct {
	ListenQueue        *int64 `json:"listen queue"`
	MaxChildrenReached *int64 `json:"max children reached"`
	SlowRequests       *int64 `json:"slow requests"`
}

// fpmPools reads the pools of a PHP-FPM unit from its pool directory and, of each pool that sets
// pm.status_path, the status page on the pool's own socket: the sums of listen queue (requests
// waiting for a free process), max children reached and slow requests (both counted since the start,
// the server takes their growth). exposed counts the pools that listen on TCP beyond loopback without
// listen.allowed_clients, which take a request from every host that reaches the port. Never a name, an
// address or a path.
//
// The status page (php.net/manual/en/fpm.status.php) answers on the SCRIPT_NAME pm.status_path, with
// the query json in JSON; checked against PHP 8.4.27. The pool settings
// (php.net/manual/en/install.fpm.configuration.php): listen "ip:port", "[ipv6]:port", "port" (every
// address) or a path; listen.allowed_clients the addresses that may connect; $pool the name of the
// pool.
func fpmPools(ctx context.Context, t Target) (map[string]any, error) {
	dir, err := fpmPoolDir(t.Name)
	if err != nil {
		return nil, err
	}
	pools, err := readFPMPools(dir)
	if err != nil {
		return nil, err
	}
	if len(pools) == 0 {
		return nil, fmt.Errorf("%w: the pool directory of unit %s holds no pool", ErrUnsupported, t.Name)
	}
	var queue, maxChildren, slow int64
	read, exposed := 0, 0
	for _, p := range pools {
		if fpmExposed(p) {
			exposed++
		}
		if p.statusPath == "" {
			continue
		}
		st, err := fpmAsk(ctx, t, p)
		if err != nil {
			return nil, err
		}
		queue += *st.ListenQueue
		maxChildren += *st.MaxChildrenReached
		slow += *st.SlowRequests
		read++
	}
	return map[string]any{
		"pools": len(pools), "pools_read": read, "pools_exposed": exposed,
		"listen_queue": queue, "max_children_reached": maxChildren, "slow_requests": slow,
	}, nil
}

// poolDirOf is the pool directory the packages give the unit: /etc/php/<version>/fpm/pool.d (Debian,
// Ubuntu: php<version>-fpm), /etc/php-fpm.d (RHEL: php-fpm), /usr/local/etc/php-fpm.d (FreeBSD ports:
// php_fpm or php-fpm).
func poolDirOf(unit string) (string, error) {
	name := strings.TrimSuffix(unit, ".service")
	switch m := debianFPM.FindStringSubmatch(name); {
	case m != nil && runtime.GOOS == "linux":
		return "/etc/php/" + m[1] + "/fpm/pool.d", nil
	case name == "php-fpm" && runtime.GOOS == "linux":
		return "/etc/php-fpm.d", nil
	case (name == "php-fpm" || name == "php_fpm") && runtime.GOOS == "freebsd":
		return "/usr/local/etc/php-fpm.d", nil
	}
	return "", fmt.Errorf("%w: unit %s is no php-fpm of the packages", ErrUnsupported, unit)
}

// readFPMPools reads the pools of the *.conf files of dir in the order PHP-FPM includes them (sorted
// by name). A pool of several sections, in one file or several, takes each setting from the last one
// that sets it, as PHP-FPM does; [global] is no pool. $pool stands for the name of the pool in any
// setting (php-fpm -tt: pm.status_path = /status-$pool is /status-www).
func readFPMPools(dir string) ([]fpmPool, error) {
	if _, err := os.Stat(dir); errors.Is(err, fs.ErrNotExist) {
		return nil, fmt.Errorf("%w: the unit has no pool directory", ErrUnsupported)
	}
	files, err := filepath.Glob(filepath.Join(dir, "*.conf"))
	switch {
	case err != nil:
		return nil, err
	case len(files) > maxFPMFiles:
		return nil, fmt.Errorf("the pool directory holds more than %d files", maxFPMFiles)
	}
	slices.Sort(files)
	var names []string
	settings := map[string]map[string]string{}
	for _, name := range files {
		b, err := readCapped(name, maxFPMFileBytes)
		if err != nil {
			return nil, fmt.Errorf("a file of the pool directory %w", err)
		}
		pool := ""
		for line := range strings.Lines(string(b)) {
			line = strings.TrimSpace(line)
			if line == "" || line[0] == ';' || line[0] == '#' {
				continue
			}
			if section, ok := strings.CutPrefix(line, "["); ok {
				pool, _, _ = strings.Cut(section, "]")
				if pool == "global" {
					pool = ""
				} else if _, seen := settings[pool]; !seen {
					if len(names) == maxFPMPools {
						return nil, fmt.Errorf("the pool directory declares more than %d pools", maxFPMPools)
					}
					names = append(names, pool)
					settings[pool] = map[string]string{}
				}
				continue
			}
			key, value, ok := strings.Cut(line, "=")
			if !ok || pool == "" {
				continue
			}
			settings[pool][strings.TrimSpace(key)] = iniValue(value)
		}
	}
	pools := make([]fpmPool, 0, len(names))
	for _, name := range names {
		s := settings[name]
		expand := func(v string) string { return strings.ReplaceAll(v, "$pool", name) }
		pools = append(pools, fpmPool{
			listen: expand(s["listen"]), statusPath: expand(s["pm.status_path"]),
			allowedClients: expand(s["listen.allowed_clients"]),
		})
	}
	return pools, nil
}

// iniValue is the value of an ini line without a trailing comment and quotes.
func iniValue(v string) string {
	v = strings.TrimSpace(v)
	if len(v) >= 2 && (v[0] == '"' || v[0] == '\'') {
		if end := strings.IndexByte(v[1:], v[0]); end >= 0 {
			return v[1 : end+1]
		}
	}
	if i := strings.IndexByte(v, ';'); i >= 0 {
		v = strings.TrimSpace(v[:i])
	}
	return v
}

// fpmTCP splits the listen of a pool on TCP into its host ("" for a port alone, every address) and
// port; ok is false for a path.
func fpmTCP(listen string) (host string, port int, ok bool) {
	if strings.HasPrefix(listen, "/") {
		return "", 0, false
	}
	portText := listen
	if h, p, err := net.SplitHostPort(listen); err == nil {
		host, portText = h, p
	}
	port, err := strconv.Atoi(portText)
	if err != nil || port < 1 || port > 65535 {
		return "", 0, false
	}
	return host, port, true
}

// fpmExposed says whether a pool listens on TCP beyond loopback without listen.allowed_clients.
func fpmExposed(p fpmPool) bool {
	host, _, ok := fpmTCP(p.listen)
	if !ok || p.allowedClients != "" || host == "localhost" {
		return false
	}
	a, err := netip.ParseAddr(host)
	return err != nil || !a.IsLoopback()
}

// fpmAsk reads the status page of pool p from its own socket: a path, or the port the unit listens on.
func fpmAsk(ctx context.Context, t Target, p fpmPool) (fpmStatus, error) {
	if len(p.statusPath) > maxFPMStatusPath || !safePath.MatchString(p.statusPath) {
		return fpmStatus{}, errors.New("a pool sets a pm.status_path the agent does not ask for")
	}
	var conn net.Conn
	var err error
	if _, port, ok := fpmTCP(p.listen); ok {
		conn, err = fpmDialPort(ctx, t, port)
	} else if validLocalPath(p.listen) && len(p.listen) <= maxSocketPath {
		conn, err = fpmDialUnix(ctx, p.listen)
		if errors.Is(err, errNoListener) && !ended(ctx) {
			return fpmStatus{}, fmt.Errorf("%w: nobody serves the socket of a pool of unit %s", ErrUnsupported, t.Name)
		}
		if err == nil {
			conn = bind(ctx, conn)
		}
	} else {
		return fpmStatus{}, fmt.Errorf("%w: a pool of unit %s listens on no address the agent reads", ErrUnsupported, t.Name)
	}
	if err != nil {
		return fpmStatus{}, netErr(ctx, err)
	}
	s := newSession(ctx, conn)
	defer s.end()
	page, err := fcgiStatusPage(s, p.statusPath, maxStatusPage)
	var pf protoFail
	if errors.As(err, &pf) {
		return fpmStatus{}, fmt.Errorf("the status page of a pool of unit %s: %s", t.Name, pf.detail)
	}
	if err != nil {
		return fpmStatus{}, err
	}
	var st fpmStatus
	if json.Unmarshal(page, &st) != nil || st.ListenQueue == nil || st.MaxChildrenReached == nil || st.SlowRequests == nil {
		return fpmStatus{}, fmt.Errorf("the status page of a pool of unit %s is no status page of php-fpm", t.Name)
	}
	return st, nil
}

// fpmDialPort connects to port where the unit listens on it, through the guard.
func fpmDialPort(ctx context.Context, t Target, port int) (net.Conn, error) {
	t.PortHint = port
	ep, err := fpmEndpoint(ctx, t)
	if err != nil {
		return nil, err
	}
	if int(ep.port) != port {
		return nil, fmt.Errorf("%w: unit %s does not listen on the port of its pool", ErrUnsupported, t.Name)
	}
	return dialThrough(ctx, NewGuard(ep.extra...), ep)
}
