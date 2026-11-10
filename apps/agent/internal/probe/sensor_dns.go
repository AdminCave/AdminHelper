// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package probe

import (
	"context"
	"errors"
	"fmt"
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
// how long it took. A name that does not exist resolves to nothing; it is no error.
func dnsSensor(ctx context.Context, p Probe, _ string) (map[string]any, error) {
	if err := noTarget(p); err != nil {
		return nil, err
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
