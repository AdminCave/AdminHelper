// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package probe

import (
	"bytes"
	"context"
	"errors"
	"fmt"
	"io"
	"io/fs"
	"math"
	"os"
	"path"
	"runtime"
	"slices"
	"strconv"
	"strings"
	"time"
)

const (
	// haproxyPortsConfig is the configuration the HAProxy of the FreeBSD ports starts with.
	haproxyPortsConfig = "/usr/local/etc/haproxy.conf"
	// opnsenseHAProxySocket is the stats socket the OPNsense plugin os-haproxy configures.
	opnsenseHAProxySocket = "/var/run/haproxy.socket"
	// maxHAProxyConfig caps the configuration haproxySocket reads.
	maxHAProxyConfig = 4 << 20
	// haproxyMaint are the bits of srv_admin_state that put a server in maintenance: set by the
	// runtime API (0x01), inherited from a tracked server (0x02), configured as disabled (0x04), by a
	// failed resolution (0x20, 0x40). 0x08 and 0x10 drain a server, which still serves its sessions.
	haproxyMaint = 0x01 | 0x02 | 0x04 | 0x20 | 0x40
)

var (
	// haproxyConfigs are the configurations that may name the stats socket; tests stand in their own.
	haproxyConfigs = []string{haproxyConfig, haproxyPortsConfig}
	// haproxyDial connects to the stats socket; tests stand in their own.
	haproxyDial = dialUnix
)

// haproxyServers counts from HAProxy's stats socket the backends, those that are down, the servers,
// those that are down and those in maintenance, never a name. The socket is one the configuration
// already declares (stats socket); without one the view is unsupported, it adds none. The two
// commands only read, at any level of the socket.
//
// Management Guide 9.3 (docs.haproxy.org/3.2/management.html): "show stat [<iid> <type> <sid>]",
// type 2 the backends, their status UP or DOWN; "show servers state", version 1, its header after
// "# ", srv_op_state 0 a stopped server, srv_admin_state the flags of haproxyMaint. Checked against
// HAProxy 3.4.7.
func haproxyServers(ctx context.Context, t Target) (map[string]any, error) {
	if webServer(t.Name) != "haproxy" {
		return nil, fmt.Errorf("%w: unit %s is no haproxy", ErrUnsupported, t.Name)
	}
	sock, err := haproxySocket()
	if err != nil {
		return nil, err
	}
	stat, err := haproxyAsk(ctx, sock, "show stat -1 2 -1")
	if err != nil {
		return nil, err
	}
	backends, backendsDown, ok := haproxyBackends(stat)
	if !ok {
		return nil, errors.New("no answer to show stat")
	}
	state, err := haproxyAsk(ctx, sock, "show servers state")
	if err != nil {
		return nil, err
	}
	servers, down, maint, ok := haproxyServerStates(state)
	if !ok {
		return nil, errors.New("no answer to show servers state")
	}
	return map[string]any{
		"backends": backends, "backends_down": backendsDown,
		"servers": servers, "servers_down": down, "servers_maint": maint,
	}, nil
}

// haproxySocket is the first unix stats socket a configuration of haproxyConfigs declares; on FreeBSD
// without one the socket of the OPNsense plugin.
func haproxySocket() (string, error) {
	for _, name := range haproxyConfigs {
		b, err := readCapped(name, maxHAProxyConfig)
		switch {
		case errors.Is(err, fs.ErrNotExist):
			continue
		case err != nil:
			return "", fmt.Errorf("the configuration %s %w", name, err)
		}
		if sock, ok := statsSocket(b); ok {
			return sock, nil
		}
	}
	if runtime.GOOS == "freebsd" {
		return opnsenseHAProxySocket, nil
	}
	return "", fmt.Errorf("%w: the configuration of haproxy declares no stats socket", ErrUnsupported)
}

// statsSocket reads the first "stats socket <path>" of a configuration with an absolute path, plain
// or as unix@<path>; an address of another family (ipv4@, abns@, fd@) is no socket of this host's
// file system.
func statsSocket(cfg []byte) (string, bool) {
	for line := range strings.Lines(string(cfg)) {
		f := strings.Fields(line)
		if i := slices.IndexFunc(f, func(w string) bool { return strings.HasPrefix(w, "#") }); i >= 0 {
			f = f[:i]
		}
		if len(f) < 3 || f[0] != "stats" || f[1] != "socket" {
			continue
		}
		path := strings.TrimPrefix(strings.Trim(f[2], `"'`), "unix@")
		if validLocalPath(path) && len(path) <= maxSocketPath {
			return path, true
		}
	}
	return "", false
}

// haproxyAsk sends cmd to the stats socket sock and returns the answer; a socket nobody serves is
// unsupported.
func haproxyAsk(ctx context.Context, sock, cmd string) ([]byte, error) {
	conn, err := haproxyDial(ctx, sock)
	switch {
	case errors.Is(err, errNoListener) && !ended(ctx):
		return nil, fmt.Errorf("%w: nobody serves the stats socket of haproxy", ErrUnsupported)
	case err != nil:
		return nil, netErr(ctx, err)
	}
	s := newSession(ctx, bind(ctx, conn))
	defer s.end()
	return haproxyAnswer(s, cmd)
}

// haproxyBackends counts the backends of show stat and those whose status is DOWN.
func haproxyBackends(b []byte) (backends, down int, ok bool) {
	data, ok := haproxyStat(b)
	if !ok {
		return 0, 0, false
	}
	for _, proxy := range data {
		row, _ := proxy.(map[string]any)["BACKEND"].(map[string]any)
		if row == nil {
			continue
		}
		backends++
		if row["status"] == "DOWN" {
			down++
		}
	}
	return backends, down, true
}

// haproxyServerStates counts the servers of show servers state, those stopped outside maintenance
// (down) and those in maintenance (maint).
func haproxyServerStates(b []byte) (servers, down, maint int, ok bool) {
	version, rest, _ := bytes.Cut(b, []byte("\n"))
	header, rest, _ := bytes.Cut(rest, []byte("\n"))
	cols, found := bytes.CutPrefix(header, []byte("# "))
	if string(bytes.TrimSpace(version)) != "1" || !found {
		return 0, 0, 0, false
	}
	names := strings.Fields(string(cols))
	opCol, adminCol := slices.Index(names, "srv_op_state"), slices.Index(names, "srv_admin_state")
	if opCol < 0 || adminCol < 0 {
		return 0, 0, 0, false
	}
	for line := range strings.Lines(string(rest)) {
		f := strings.Fields(line)
		if len(f) == 0 {
			continue
		}
		if len(f) <= max(opCol, adminCol) {
			return 0, 0, 0, false
		}
		op, err1 := strconv.Atoi(f[opCol])
		admin, err2 := strconv.Atoi(f[adminCol])
		if err1 != nil || err2 != nil {
			return 0, 0, 0, false
		}
		servers++
		switch {
		case admin&haproxyMaint != 0:
			maint++
		case op == 0:
			down++
		}
	}
	return servers, down, maint, true
}

// maxHAProxyCerts caps the certificate files haproxyCerts reads.
const maxHAProxyCerts = 256

// haproxyReserved are the endings of the files HAProxy loads beside a certificate of a directory, not
// as one (configuration manual 3.2, bind option crt).
var haproxyReserved = []string{".key", ".issuer", ".ocsp", ".sctl"}

// haproxyCerts reads when the certificates HAProxy serves expire: the files of every "crt" of a bind
// line, a relative one below crt-base, a directory as HAProxy reads it (each file in it but those
// starting with a dot and those of haproxyReserved). certs counts them, min_days_left is the fewest
// days one has left, expiring_14d those with fewer than 14. Of each file it reads the first
// certificate; the private key HAProxy keeps in the same file it skips unparsed. A file that is not
// there is left out; crt-list and crt-store are not read. reload_missing counts the files whose
// certificate lasts longer than the one HAProxy has loaded under that name (haproxyLoaded): it was
// renewed and HAProxy not reloaded. It is there only when the stats socket answered for one file at
// least.
func haproxyCerts(ctx context.Context, t Target) (map[string]any, error) {
	if webServer(t.Name) != "haproxy" {
		return nil, fmt.Errorf("%w: unit %s is no haproxy", ErrUnsupported, t.Name)
	}
	return untilDone(ctx, func() (map[string]any, error) {
		cfg, err := haproxyConfigText()
		if err != nil {
			return nil, err
		}
		files, err := haproxyCertFiles(haproxyCertPaths(cfg))
		if err != nil {
			return nil, err
		}
		values := map[string]any{"certs": 0, "expiring_14d": 0}
		var least int64
		ends := map[string]time.Time{}
		for _, name := range files {
			data, err := readCapped(name, maxCertFileBytes)
			if errors.Is(err, fs.ErrNotExist) {
				continue
			}
			if err != nil {
				return nil, fmt.Errorf("a certificate file of haproxy %w", err)
			}
			cert, err := leafCert(data)
			if err != nil {
				return nil, fmt.Errorf("a certificate file of haproxy %w", err)
			}
			ends[name] = cert.NotAfter
			left := int64(math.Floor(cert.NotAfter.Sub(now()).Hours() / 24))
			if values["certs"] == 0 || left < least {
				least = left
			}
			values["certs"] = values["certs"].(int) + 1
			if left < 14 {
				values["expiring_14d"] = values["expiring_14d"].(int) + 1
			}
		}
		if values["certs"] != 0 {
			values["min_days_left"] = least
		}
		if loaded := haproxyLoaded(ctx, ends); len(loaded) > 0 {
			missing := 0
			for name, end := range loaded {
				if ends[name].After(end) {
					missing++
				}
			}
			values["reload_missing"] = missing
		}
		return values, nil
	})
}

// haproxyNotAfterLayout is how show ssl cert prints notAfter, OpenSSL's ASN1_TIME_print, always in GMT.
const haproxyNotAfterLayout = "Jan _2 15:04:05 2006 GMT"

// haproxyLoaded asks the stats socket when the certificates HAProxy has loaded under the names of files
// expire: "show ssl cert" lists the files it loaded, "show ssl cert <file>" tells of one its notAfter.
// Both need level operator (HAProxy 3.2.0 src/ssl_ckch.c, cli_parse_show_cert); a socket that refuses,
// that is not there or that answers otherwise gives none, and so does a name HAProxy writes otherwise
// than the agent (a crt-base joined another way). A name with a blank, a backslash or a semicolon (a
// file of a crt directory may be named anyhow) is not asked: the CLI would split or unescape it, or run
// what follows the semicolon as a command of its own. Management Guide 9.3 (docs.haproxy.org/3.2/management.html).
func haproxyLoaded(ctx context.Context, files map[string]time.Time) map[string]time.Time {
	if len(files) == 0 {
		return nil
	}
	sock, err := haproxySocket()
	if err != nil {
		return nil
	}
	list, err := haproxyAsk(ctx, sock, "show ssl cert")
	if err != nil {
		return nil
	}
	names, ok := haproxyCertList(list)
	if !ok {
		return nil
	}
	loaded := map[string]time.Time{}
	for _, name := range names {
		if _, ok := files[name]; !ok || strings.ContainsAny(name, " \t\\;") {
			continue
		}
		b, err := haproxyAsk(ctx, sock, "show ssl cert "+name)
		if err != nil {
			continue
		}
		if end, ok := haproxyCertEnd(b, name); ok {
			loaded[name] = end
		}
	}
	return loaded
}

// haproxyCertList reads the answer of show ssl cert, the files HAProxy loaded, one a line below
// "# filename". The file of an open transaction it lists as '*' and the path, below "# transaction": no
// file of a bind line is called so. An answer without "# filename" (an error, a refusal) is none.
func haproxyCertList(b []byte) ([]string, bool) {
	var names []string
	ok := false
	for line := range strings.Lines(string(b)) {
		switch line = strings.TrimRight(line, "\r\n"); {
		case line == "# filename":
			ok = true
		case line != "" && !strings.HasPrefix(line, "#"):
			names = append(names, line)
		}
	}
	return names, ok
}

// haproxyCertEnd reads notAfter from the answer of show ssl cert <name>, an answer only if its
// Filename is name.
func haproxyCertEnd(b []byte, name string) (time.Time, bool) {
	var file, after string
	for line := range strings.Lines(string(b)) {
		key, value, ok := strings.Cut(strings.TrimRight(line, "\r\n"), ": ")
		switch {
		case !ok:
		case key == "Filename" && file == "":
			file = value
		case key == "notAfter" && after == "":
			after = value
		}
	}
	if file != name {
		return time.Time{}, false
	}
	end, err := time.ParseInLocation(haproxyNotAfterLayout, after, time.UTC)
	return end, err == nil
}

// haproxyConfigText is the first configuration of haproxyConfigs there is.
func haproxyConfigText() ([]byte, error) {
	for _, name := range haproxyConfigs {
		b, err := readCapped(name, maxHAProxyConfig)
		switch {
		case errors.Is(err, fs.ErrNotExist):
			continue
		case err != nil:
			return nil, fmt.Errorf("the configuration %s %w", name, err)
		}
		return b, nil
	}
	return nil, fmt.Errorf("%w: haproxy has no configuration here", ErrUnsupported)
}

// haproxyCertPaths are the plain absolute paths the crt of the bind lines of cfg name, each once.
func haproxyCertPaths(cfg []byte) []string {
	var lines [][]string
	base := ""
	for line := range strings.Lines(string(cfg)) {
		f := strings.Fields(line)
		if i := slices.IndexFunc(f, func(w string) bool { return strings.HasPrefix(w, "#") }); i >= 0 {
			f = f[:i]
		}
		switch {
		case len(f) == 2 && f[0] == "crt-base":
			base = strings.Trim(f[1], `"'`)
		case len(f) > 0 && f[0] == "bind":
			lines = append(lines, f)
		}
	}
	var paths []string
	for _, f := range lines {
		for i := 1; i+1 < len(f); i++ {
			if f[i] != "crt" {
				continue
			}
			p := strings.Trim(f[i+1], `"'`)
			if !path.IsAbs(p) && base != "" {
				p = path.Join(base, p)
			}
			if safePath.MatchString(p) && !slices.Contains(paths, p) {
				paths = append(paths, p)
			}
		}
	}
	return paths
}

// haproxyCertFiles are the files of paths, a directory as HAProxy reads it, at most maxHAProxyCerts.
func haproxyCertFiles(paths []string) ([]string, error) {
	var files []string
	add := func(name string) error {
		if slices.Contains(files, name) {
			return nil
		}
		if len(files) == maxHAProxyCerts {
			return fmt.Errorf("haproxy names more than %d certificate files", maxHAProxyCerts)
		}
		files = append(files, name)
		return nil
	}
	for _, p := range paths {
		fi, err := os.Stat(p)
		switch {
		case errors.Is(err, fs.ErrNotExist):
			continue
		case err != nil:
			return nil, errors.New("a certificate file of haproxy cannot be read")
		case !fi.IsDir():
			if err := add(p); err != nil {
				return nil, err
			}
			continue
		}
		names, err := haproxyCertDir(p)
		if err != nil {
			return nil, err
		}
		for _, n := range names {
			if err := add(path.Join(p, n)); err != nil {
				return nil, err
			}
		}
	}
	return files, nil
}

// haproxyCertDir lists the certificate files of the directory dir in alphabetic order, as HAProxy
// loads them; past maxHAProxyCerts entries it stops with an error.
func haproxyCertDir(dir string) ([]string, error) {
	root, err := os.OpenRoot(dir)
	if err != nil {
		return nil, errors.New("a directory of certificates of haproxy cannot be read")
	}
	defer root.Close()
	d, err := root.Open(".")
	if err != nil {
		return nil, errors.New("a directory of certificates of haproxy cannot be read")
	}
	defer d.Close()
	entries, err := d.ReadDir(maxHAProxyCerts + 1)
	if err != nil && !errors.Is(err, io.EOF) {
		return nil, errors.New("a directory of certificates of haproxy cannot be read")
	}
	if len(entries) > maxHAProxyCerts {
		return nil, fmt.Errorf("a directory of certificates of haproxy holds more than %d entries", maxHAProxyCerts)
	}
	var names []string
	for _, e := range entries {
		n := e.Name()
		if e.IsDir() || strings.HasPrefix(n, ".") ||
			slices.ContainsFunc(haproxyReserved, func(s string) bool { return strings.HasSuffix(n, s) }) {
			continue
		}
		names = append(names, n)
	}
	slices.Sort(names)
	return names, nil
}
