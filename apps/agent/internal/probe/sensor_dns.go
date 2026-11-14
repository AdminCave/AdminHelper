// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package probe

import (
	"context"
	"crypto/rand"
	"encoding/binary"
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
)

func init() {
	sensors["dns"] = dnsSensor
}

// dnsName is a name the dns sensor looks up: labels of letters, digits and hyphens, and underscores
// for the names of services (SRV).
var dnsName = regexp.MustCompile(`^[A-Za-z0-9_]([A-Za-z0-9_-]{0,61}[A-Za-z0-9_])?(\.[A-Za-z0-9_]([A-Za-z0-9_-]{0,61}[A-Za-z0-9_])?)*\.?$`)

// lookupDNS asks the resolver of this host for the records rrtype of name and returns how many it
// answered; tests stand in their own.
var lookupDNS = func(ctx context.Context, rrtype, name string) (int, error) {
	r := net.DefaultResolver
	switch rrtype {
	case "A", "AAAA":
		network := "ip4"
		if rrtype == "AAAA" {
			network = "ip6"
		}
		ips, err := r.LookupIP(ctx, network, name)
		return len(ips), err
	case "MX":
		mx, err := r.LookupMX(ctx, name)
		return len(mx), err
	case "TXT":
		txt, err := r.LookupTXT(ctx, name)
		return len(txt), err
	case "NS":
		ns, err := r.LookupNS(ctx, name)
		return len(ns), err
	case "SRV":
		_, srv, err := r.LookupSRV(ctx, "", "", name)
		return len(srv), err
	case "CNAME":
		// LookupCNAME answers the name itself for a name without CNAME.
		cname, err := r.LookupCNAME(ctx, name)
		if err != nil || strings.EqualFold(strings.TrimSuffix(cname, "."), strings.TrimSuffix(name, ".")) {
			return 0, err
		}
		return 1, nil
	case "PTR":
		names, err := r.LookupAddr(ctx, name)
		return len(names), err
	}
	return 0, fmt.Errorf("%w: record type %s", ErrInvalid, rrtype)
}

// dnsSensor looks name up with the resolver of this host: whether it resolved, how many answers and
// how long it took. A name that does not exist resolves to nothing; it is no error. With a target it
// asks the server listening there instead (askServer) and reports its rcode too.
func dnsSensor(ctx context.Context, p Probe, _ string) (map[string]any, error) {
	var target *Target
	if p.Target != nil {
		t, err := targetOf(p, httpTargets...)
		if err != nil {
			return nil, err
		}
		target = &t
	}
	if err := knownParams(p, "name", "rrtype"); err != nil {
		return nil, err
	}
	name, err := textParam(p, "name", "")
	if err != nil {
		return nil, err
	}
	if len(name) > 253 || !dnsName.MatchString(name) {
		return nil, fmt.Errorf("%w: parameter name of sensor dns needs a DNS name of at most 253 characters", ErrInvalid)
	}
	rrtype, err := choiceParam(p, "rrtype", "A", "A", "AAAA", "MX", "TXT", "SRV", "CNAME", "NS", "PTR")
	if err != nil {
		return nil, err
	}
	if _, err := credentialUse(p); err != nil {
		return nil, err
	}
	query := name
	if rrtype == "PTR" {
		if query, err = ptrAddr(name); err != nil {
			return nil, err
		}
	}
	if target != nil {
		return askServer(ctx, *target, rrtype, query)
	}
	start := time.Now()
	n, err := lookupDNS(ctx, rrtype, query)
	took := time.Since(start).Milliseconds()
	var de *net.DNSError
	switch {
	case n > 0 || err == nil:
	case ended(ctx):
		return nil, netErr(ctx, err)
	case errors.As(err, &de) && de.IsNotFound:
	default:
		return nil, err
	}
	return map[string]any{"resolved": n > 0, "answers": n, "duration_ms": took}, nil
}

// ptrAddr is the address a PTR lookup of name asks for: name itself if it is an address, else the
// address of a name under in-addr.arpa or ip6.arpa.
func ptrAddr(name string) (string, error) {
	n := strings.TrimSuffix(strings.ToLower(name), ".")
	if ip, err := netip.ParseAddr(n); err == nil {
		return ip.String(), nil
	}
	if rest, ok := strings.CutSuffix(n, ".in-addr.arpa"); ok {
		parts := strings.Split(rest, ".")
		slices.Reverse(parts)
		if ip, err := netip.ParseAddr(strings.Join(parts, ".")); err == nil && ip.Is4() && len(parts) == 4 {
			return ip.String(), nil
		}
	}
	if rest, ok := strings.CutSuffix(n, ".ip6.arpa"); ok {
		if ip, ok := ip6Arpa(strings.Split(rest, ".")); ok {
			return ip.String(), nil
		}
	}
	return "", fmt.Errorf("%w: a PTR lookup needs an address or a name under in-addr.arpa or ip6.arpa", ErrInvalid)
}

// ip6Arpa is the address of the 32 nibbles of a name under ip6.arpa, the last nibble first.
func ip6Arpa(nibbles []string) (netip.Addr, bool) {
	if len(nibbles) != 32 {
		return netip.Addr{}, false
	}
	var b [16]byte
	for i, s := range nibbles {
		v, err := strconv.ParseUint(s, 16, 8)
		if len(s) != 1 || err != nil {
			return netip.Addr{}, false
		}
		pos := 31 - i
		b[pos/2] |= byte(v) << (4 * (1 - pos%2))
	}
	return netip.AddrFrom16(b), true
}

// dnsTypes are the numbers of the record types the dns sensor asks for (RFC 1035 §3.2.2, RFC 2782,
// RFC 3596).
var dnsTypes = map[string]uint16{"A": 1, "NS": 2, "CNAME": 5, "PTR": 12, "MX": 15, "TXT": 16, "AAAA": 28, "SRV": 33}

// dnsRcodes name the answers of a server the checks tell apart (RFC 1035 §4.1.1); any other is "other".
var dnsRcodes = map[uint16]string{0: "noerror", 2: "servfail", 3: "nxdomain", 5: "refused"}

// dnsHeader is the size of the header of a DNS message (RFC 1035 §4.1.1).
const dnsHeader = 12

// askServer asks the DNS server listening at t for the records rrtype of name (an address for PTR),
// over TCP with the two-byte length of RFC 7766 §8, through the guard. The query asks for recursion
// and carries no EDNS; of the answer only the header is read: its rcode and how many answers it
// holds. resolved means noerror with at least one answer.
func askServer(ctx context.Context, t Target, rrtype, name string) (map[string]any, error) {
	if rrtype == "PTR" {
		name = reverseName(netip.MustParseAddr(name))
	}
	msg, id, err := dnsQuery(rrtype, name)
	if err != nil {
		return nil, err
	}
	ep, err := resolve(ctx, t)
	if err != nil {
		return nil, err
	}
	start := time.Now()
	conn, err := dialTarget(ctx, ep)
	if err != nil {
		return nil, err
	}
	defer conn.Close()
	if _, err := conn.Write(msg); err != nil {
		return nil, netErr(ctx, err)
	}
	var head [2 + dnsHeader]byte
	if _, err := io.ReadFull(conn, head[:]); err != nil {
		return nil, netErr(ctx, fmt.Errorf("the DNS server sent no answer: %w", err))
	}
	took := time.Since(start).Milliseconds()
	size, h := binary.BigEndian.Uint16(head[:2]), head[2:]
	flags := binary.BigEndian.Uint16(h[2:4])
	switch {
	case size < dnsHeader:
		return nil, errors.New("the DNS server sent an answer shorter than a header")
	case binary.BigEndian.Uint16(h[:2]) != id || flags&0x8000 == 0:
		return nil, errors.New("the DNS server sent no answer to the query")
	}
	rcode, ok := dnsRcodes[flags&0xf]
	if !ok {
		rcode = "other"
	}
	n := int(binary.BigEndian.Uint16(h[6:8]))
	return map[string]any{"resolved": rcode == "noerror" && n > 0, "answers": n, "duration_ms": took, "rcode": rcode}, nil
}

// dnsQuery is a query for the records rrtype of name with its two-byte length ahead, and its ID: one
// question of class IN, the flag RD, no other section.
func dnsQuery(rrtype, name string) ([]byte, uint16, error) {
	var idb [2]byte
	if _, err := rand.Read(idb[:]); err != nil {
		return nil, 0, err
	}
	id := binary.BigEndian.Uint16(idb[:])
	msg := []byte{0, 0, idb[0], idb[1], 0x01, 0x00, 0, 1, 0, 0, 0, 0, 0, 0}
	if n := strings.TrimSuffix(name, "."); n != "" {
		for _, label := range strings.Split(n, ".") {
			msg = append(msg, byte(len(label)))
			msg = append(msg, label...)
		}
	}
	msg = append(msg, 0)
	msg = binary.BigEndian.AppendUint16(msg, dnsTypes[rrtype])
	msg = binary.BigEndian.AppendUint16(msg, 1)
	binary.BigEndian.PutUint16(msg[:2], uint16(len(msg)-2))
	return msg, id, nil
}

// reverseName is the name under in-addr.arpa or ip6.arpa a PTR query for ip asks for.
func reverseName(ip netip.Addr) string {
	var b strings.Builder
	if ip.Is4() {
		a := ip.As4()
		for i := 3; i >= 0; i-- {
			fmt.Fprintf(&b, "%d.", a[i])
		}
		return b.String() + "in-addr.arpa."
	}
	a := ip.As16()
	for i := 15; i >= 0; i-- {
		fmt.Fprintf(&b, "%x.%x.", a[i]&0xf, a[i]>>4)
	}
	return b.String() + "ip6.arpa."
}
