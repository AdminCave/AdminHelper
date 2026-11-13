// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package probe

import (
	"bytes"
	"cmp"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"io/fs"
	"math"
	"net"
	"net/netip"
	"os"
	"path/filepath"
	"regexp"
	"runtime"
	"slices"
	"strings"
)

const (
	// maxKeaAnswerBytes caps Kea's answer to statistic-get-all: every statistic with its samples
	// (max-sample-count, 20 by default), a few hundred bytes per subnet.
	maxKeaAnswerBytes = 16 << 20
	// maxDnsmasqBytes caps each configuration file of dnsmasq and its lease file, maxDnsmasqFiles how
	// many configuration files conf-file and conf-dir may add.
	maxDnsmasqBytes = 4 << 20
	maxDnsmasqFiles = 64
)

// keaSockets are the control sockets of kea-dhcp4: the socket-name "kea4-ctrl-socket" of the shipped
// kea-dhcp4.conf in the runtime directory the packages' unit creates (RuntimeDirectory=kea), and the
// same under /var/run. Since Kea 2.7.9 a control socket may lie only in its socket directory.
var keaSockets = []string{"/run/kea/kea4-ctrl-socket", "/var/run/kea/kea4-ctrl-socket"}

// keaDial connects to a control socket through the guard; tests stand in their own.
var keaDial = dialUnix

// keaSubnetStat is a statistic of a whole subnet, not of one of its pools: subnet[<id>].<name>.
var keaSubnetStat = regexp.MustCompile(`^subnet\[([0-9]+)\]\.(total|assigned)-addresses$`)

// keaPools reads how full the address pools of kea-dhcp4 are: how many subnets it serves, the highest
// share of assigned addresses of any subnet, and how often it found no address to give. It asks its
// control socket statistic-get-all alone, never config-get, whose answer carries the passwords of the
// configuration in clear text, and reports no subnet, no address and no text of Kea.
//
// Kea ARM, "Management API": a command is {"command": …, "arguments": {}}, the answer {"result": 0
// (success) … 5, "arguments": …}; statistic-get-all names each statistic with its samples, newest
// first, [[value, "timestamp"], …]. "DHCPv4 Statistics": subnet[id].total-addresses,
// subnet[id].assigned-addresses and the global v4-allocation-fail.
func keaPools(ctx context.Context, _ Target) (map[string]any, error) {
	conn, err := keaConnect(ctx)
	if err != nil {
		return nil, err
	}
	conn = bind(ctx, conn)
	defer func() { _ = conn.Close() }()
	if _, err := conn.Write([]byte(`{"command": "statistic-get-all", "arguments": {}}`)); err != nil {
		return nil, netErr(ctx, err)
	}
	dec := json.NewDecoder(io.LimitReader(conn, maxKeaAnswerBytes))
	dec.UseNumber()
	var raw json.RawMessage
	if err := dec.Decode(&raw); err != nil {
		if ended(ctx) {
			return nil, netErr(ctx, err)
		}
		return nil, errors.New("kea: an answer of another form")
	}
	stats, err := keaStatistics(raw)
	if err != nil {
		return nil, err
	}
	return keaPoolValues(stats)
}

// keaConnect connects to the first control socket of keaSockets that kea-dhcp4 serves.
func keaConnect(ctx context.Context) (net.Conn, error) {
	for _, path := range keaSockets {
		conn, err := keaDial(ctx, path)
		if errors.Is(err, errNoListener) {
			continue
		}
		return conn, err
	}
	return nil, fmt.Errorf("%w: kea-dhcp4 serves no control socket at its default path", ErrUnsupported)
}

// keaStatistics reads the newest sample of each statistic out of Kea's answer, an object or, through
// the control agent, a list of one.
func keaStatistics(raw json.RawMessage) (map[string]float64, error) {
	if b := bytes.TrimSpace(raw); len(b) > 0 && b[0] == '[' {
		var list []json.RawMessage
		if err := json.Unmarshal(b, &list); err != nil || len(list) != 1 {
			return nil, errors.New("kea: an answer of another form")
		}
		raw = list[0]
	}
	var answer struct {
		Result    *int                           `json:"result"`
		Arguments map[string][][]json.RawMessage `json:"arguments"`
	}
	d := json.NewDecoder(bytes.NewReader(raw))
	d.UseNumber()
	if err := d.Decode(&answer); err != nil || answer.Result == nil {
		return nil, errors.New("kea: an answer of another form")
	}
	if *answer.Result != 0 {
		return nil, fmt.Errorf("kea: statistic-get-all failed with result %d", *answer.Result)
	}
	stats := map[string]float64{}
	for name, samples := range answer.Arguments {
		if !keaSubnetStat.MatchString(name) && name != "v4-allocation-fail" {
			continue
		}
		if len(samples) == 0 || len(samples[0]) != 2 {
			return nil, errors.New("kea: a statistic of another form")
		}
		var n json.Number
		if err := json.Unmarshal(samples[0][0], &n); err != nil {
			return nil, errors.New("kea: a statistic of another form")
		}
		v, err := n.Float64()
		if err != nil || v < 0 {
			return nil, errors.New("kea: a statistic of another form")
		}
		stats[name] = v
	}
	return stats, nil
}

// keaPoolValues are the view's values of Kea's statistics. A subnet without addresses has no share.
func keaPoolValues(stats map[string]float64) (map[string]any, error) {
	type subnet struct{ total, assigned float64 }
	subnets := map[string]*subnet{}
	for name, v := range stats {
		m := keaSubnetStat.FindStringSubmatch(name)
		if m == nil {
			continue
		}
		s := subnets[m[1]]
		if s == nil {
			s = &subnet{}
			subnets[m[1]] = s
		}
		if m[2] == "total" {
			s.total = v
		} else {
			s.assigned = v
		}
	}
	values := map[string]any{"subnets": len(subnets)}
	most := -1.0
	for _, s := range subnets {
		if s.total > 0 {
			most = max(most, s.assigned/s.total*100)
		}
	}
	if most >= 0 {
		values["max_pool_used_pct"] = math.Round(most*10) / 10
	}
	if fails, ok := stats["v4-allocation-fail"]; ok {
		values["alloc_fail"] = int64(fails)
	}
	return values, nil
}

// The files of dnsmasq the view reads; tests stand in their own. dnsmasq's config.h: CONFFILE
// /etc/dnsmasq.conf, on FreeBSD /usr/local/etc/dnsmasq.conf; LEASEFILE /var/lib/misc/dnsmasq.leases,
// on the BSDs /var/db/dnsmasq.leases. Debian's package starts dnsmasq with the configuration directory
// /etc/dnsmasq.d (CONFIG_DIR of /etc/default/dnsmasq), which no line of dnsmasq.conf names.
var (
	dnsmasqConf      = "/etc/dnsmasq.conf"
	dnsmasqLeases    = "/var/lib/misc/dnsmasq.leases"
	dnsmasqDebianDir = "/etc/dnsmasq.d"
)

func init() {
	if runtime.GOOS == "freebsd" {
		dnsmasqConf, dnsmasqLeases, dnsmasqDebianDir = "/usr/local/etc/dnsmasq.conf", "/var/db/dnsmasq.leases", ""
	}
}

// dnsmasqLeases counts the IPv4 leases of dnsmasq, the addresses of its dynamic IPv4 ranges and the
// share of them leased. Of the configuration it reads the dhcp-range, dhcp-leasefile, conf-file and
// conf-dir lines alone; of the lease file the address of each IPv4 lease. It reports no address,
// no name and no MAC, and its errors quote nothing of the files.
//
// dnsmasq(8): dhcp-range=[tag:<tag>[,tag:<tag>],][set:<tag>,]<start-addr>[,<end-addr>|<mode>]
// [,<netmask>[,<broadcast>]][,<lease time>], the modes static and proxy giving no address of their
// own. lease.c, lease_update_file: an IPv4 lease is "<expiry> <hwaddr> <address> <hostname|*>
// <client-id|*>", an IPv6 lease "<expiry> [T]<iaid> <address> …" after a line "duid …".
func dnsmasqLeaseView(ctx context.Context, _ Target) (map[string]any, error) {
	return untilDone(ctx, func() (map[string]any, error) {
		r := &dnsmasqReader{leaseFile: dnsmasqLeases}
		if err := r.read(dnsmasqConf, 0); errors.Is(err, fs.ErrNotExist) {
			return nil, fmt.Errorf("%w: dnsmasq has no configuration at its default path", ErrUnsupported)
		} else if err != nil {
			return nil, err
		}
		if dnsmasqDebianDir != "" {
			if err := r.dir(dnsmasqDebianDir+",.dpkg-dist,.dpkg-old,.dpkg-new", 0); err != nil {
				return nil, err
			}
		}
		if !r.dhcp {
			return nil, fmt.Errorf("%w: dnsmasq serves no DHCP (no dhcp-range)", ErrUnsupported)
		}
		data, err := readCapped(r.leaseFile, maxDnsmasqBytes)
		if errors.Is(err, fs.ErrNotExist) {
			return nil, errors.New("dnsmasq: there is no lease file")
		}
		if err != nil {
			return nil, fmt.Errorf("dnsmasq: the lease file %w", err)
		}
		leases, inRange := 0, 0
		for line := range strings.Lines(string(data)) {
			fields := strings.Fields(line)
			if len(fields) < 3 || fields[0] == "duid" {
				continue
			}
			addr, err := netip.ParseAddr(fields[2])
			if err != nil || !addr.Is4() {
				continue // an IPv6 lease
			}
			leases++
			if r.inRange(addr) {
				inRange++
			}
		}
		size := r.rangeSize()
		values := map[string]any{"leases": leases, "range_size": size}
		if size > 0 {
			values["used_pct"] = math.Round(float64(inRange)/float64(size)*1000) / 10
		}
		return values, nil
	})
}

// dnsmasqRange is a dynamic IPv4 range of dnsmasq, its first and last address.
type dnsmasqRange struct{ first, last uint32 }

// dnsmasqReader reads the dynamic IPv4 ranges and the lease file out of dnsmasq's configuration, the
// files of conf-file and conf-dir in the place of their line.
type dnsmasqReader struct {
	ranges    []dnsmasqRange
	leaseFile string
	files     int
	dhcp      bool // a dhcp-range of any family or mode: dnsmasq serves DHCP and keeps a lease file
}

// dnsmasqLine is a line of dnsmasq's configuration without its comment and its quotes. option.c,
// read_file: a "#" at the start or after white space outside double quotes starts a comment; the
// quotes themselves are dropped.
func dnsmasqLine(line string) string {
	var b strings.Builder
	quoted := false
	for i, c := range line {
		switch {
		case c == '"':
			quoted = !quoted
			continue
		case c == '#' && !quoted && (i == 0 || line[i-1] == ' ' || line[i-1] == '\t'):
			return b.String()
		}
		b.WriteRune(c)
	}
	return b.String()
}

func (r *dnsmasqReader) read(path string, depth int) error {
	r.files++
	if r.files > maxDnsmasqFiles || depth > 8 {
		return fmt.Errorf("dnsmasq: more than %d configuration files or conf-file nested too deep", maxDnsmasqFiles)
	}
	data, err := readCapped(path, maxDnsmasqBytes)
	if errors.Is(err, fs.ErrNotExist) {
		return err
	}
	if err != nil {
		return fmt.Errorf("dnsmasq: a configuration file %w", err)
	}
	for line := range strings.Lines(string(data)) {
		line = strings.TrimSpace(dnsmasqLine(line))
		if line == "" {
			continue
		}
		name, value, _ := strings.Cut(line, "=")
		name, value = strings.TrimSpace(name), strings.TrimSpace(value)
		switch name {
		case "dhcp-range":
			r.dhcp = true
			if err := r.addRange(value); err != nil {
				return err
			}
		case "dhcp-leasefile", "dhcp-lease-file":
			if !filepath.IsAbs(value) {
				return errors.New("dnsmasq: a relative dhcp-leasefile")
			}
			r.leaseFile = value
		case "conf-file":
			if !filepath.IsAbs(value) {
				return errors.New("dnsmasq: a relative conf-file")
			}
			if err := r.read(value, depth+1); err != nil && !errors.Is(err, fs.ErrNotExist) {
				return err
			}
		case "conf-dir":
			if err := r.dir(value, depth); err != nil {
				return err
			}
		}
	}
	return nil
}

// dir reads the files of a conf-dir value "<dir>[,<ext>…]" in name order: with an extension "*.<ext>"
// only the files with one such, else all but those ending in a plain one. dnsmasq(8): files ending in
// "~", starting with "." or starting and ending with "#" are always skipped.
func (r *dnsmasqReader) dir(value string, depth int) error {
	parts := strings.Split(value, ",")
	dir := strings.TrimSpace(parts[0])
	if !filepath.IsAbs(dir) {
		return errors.New("dnsmasq: a relative conf-dir")
	}
	var only, skip []string
	for _, p := range parts[1:] {
		p = strings.TrimSpace(p)
		if ext, ok := strings.CutPrefix(p, "*"); ok {
			only = append(only, ext)
		} else if p != "" {
			skip = append(skip, p)
		}
	}
	entries, err := os.ReadDir(dir)
	if errors.Is(err, fs.ErrNotExist) {
		return nil
	}
	if err != nil {
		return errors.New("dnsmasq: a conf-dir cannot be read")
	}
	for _, e := range entries {
		n := e.Name()
		if strings.HasSuffix(n, "~") || strings.HasPrefix(n, ".") ||
			(len(n) > 1 && strings.HasPrefix(n, "#") && strings.HasSuffix(n, "#")) {
			continue
		}
		has := func(ext string) bool { return strings.HasSuffix(n, ext) }
		if (len(only) > 0 && !slices.ContainsFunc(only, has)) || slices.ContainsFunc(skip, has) {
			continue
		}
		if !e.Type().IsRegular() && e.Type()&fs.ModeSymlink == 0 {
			continue
		}
		if err := r.read(filepath.Join(dir, n), depth+1); err != nil && !errors.Is(err, fs.ErrNotExist) {
			return err
		}
	}
	return nil
}

// addRange takes the dynamic IPv4 range of a dhcp-range value; an IPv6 range, one of mode static or
// proxy, and one without an end give no addresses of their own.
func (r *dnsmasqReader) addRange(value string) error {
	fields := strings.Split(value, ",")
	for len(fields) > 0 {
		f := strings.TrimSpace(fields[0])
		if !strings.HasPrefix(f, "tag:") && !strings.HasPrefix(f, "set:") &&
			!strings.HasPrefix(f, "net:") && !strings.HasPrefix(f, "interface:") {
			break
		}
		fields = fields[1:]
	}
	if len(fields) == 0 {
		return errors.New("dnsmasq: a dhcp-range of another form")
	}
	first, err := netip.ParseAddr(strings.TrimSpace(fields[0]))
	if err != nil || !first.Is4() {
		return nil // an IPv6 range or a constructor: not counted
	}
	if len(fields) < 2 {
		return nil
	}
	last, err := netip.ParseAddr(strings.TrimSpace(fields[1]))
	if err != nil {
		return nil // a mode or a lease time: no dynamic range
	}
	if !last.Is4() || ipv4Number(last) < ipv4Number(first) {
		return errors.New("dnsmasq: a dhcp-range of another form")
	}
	a, b := ipv4Number(first), ipv4Number(last)
	r.ranges = append(r.ranges, dnsmasqRange{a, b})
	return nil
}

// rangeSize is how many addresses the ranges hold, each once.
func (r *dnsmasqReader) rangeSize() int64 {
	ranges := slices.Clone(r.ranges)
	slices.SortFunc(ranges, func(x, y dnsmasqRange) int { return cmp.Compare(x.first, y.first) })
	var size int64
	next := int64(-1) // the first address no range counted so far covers
	for _, g := range ranges {
		from := max(int64(g.first), next)
		if int64(g.last) >= from {
			size += int64(g.last) - from + 1
			next = int64(g.last) + 1
		}
	}
	return size
}

// inRange says whether addr lies in a dynamic range.
func (r *dnsmasqReader) inRange(addr netip.Addr) bool {
	n := ipv4Number(addr)
	return slices.ContainsFunc(r.ranges, func(g dnsmasqRange) bool { return g.first <= n && n <= g.last })
}

func ipv4Number(a netip.Addr) uint32 {
	b := a.As4()
	return uint32(b[0])<<24 | uint32(b[1])<<16 | uint32(b[2])<<8 | uint32(b[3])
}
