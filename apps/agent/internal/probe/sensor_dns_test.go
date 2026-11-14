// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package probe

import (
	"bytes"
	"context"
	"encoding/binary"
	"errors"
	"io"
	"net"
	"strings"
	"testing"
	"time"
)

// dnsStub serves on loopback as a DNS server over TCP: it reads one query with its length, hands it
// to answer, sends back what answer returns, its length ahead unless raw, and closes. The queries it
// got come through the channel.
func dnsStub(t *testing.T, raw bool, answer func(query []byte) []byte) (int, chan []byte) {
	t.Helper()
	stubHost(t, &fakeHost{live: true})
	got := make(chan []byte, 4)
	port := rawServer(t, func(c net.Conn) {
		var size [2]byte
		if _, err := io.ReadFull(c, size[:]); err != nil {
			return
		}
		q := make([]byte, binary.BigEndian.Uint16(size[:]))
		if _, err := io.ReadFull(c, q); err != nil {
			return
		}
		got <- q
		out := answer(q)
		if !raw {
			out = append(binary.BigEndian.AppendUint16(nil, uint16(len(out))), out...)
		}
		_, _ = c.Write(out)
	})
	snapshot.Lock()
	snapshot.at = snapshot.at.Add(-2 * listenerFresh)
	snapshot.Unlock()
	return port, got
}

// reply answers a query with its ID, the flags QR and RA, rcode and n answers counted in the header;
// the records themselves the sensor never reads, so a long tail stands in for them.
func reply(rcode uint16, n uint16) func([]byte) []byte {
	return func(q []byte) []byte {
		h := []byte{q[0], q[1], 0, 0, 0, 1, 0, 0, 0, 0, 0, 0}
		binary.BigEndian.PutUint16(h[2:4], 0x8180|rcode)
		binary.BigEndian.PutUint16(h[6:8], n)
		return append(h, bytes.Repeat([]byte{0xab}, 4000)...)
	}
}

func TestDNSSensorAsksTheServerOfItsTarget(t *testing.T) {
	asked := stubLookup(t, 9, nil)
	ctx := context.Background()
	port, queries := dnsStub(t, false, reply(0, 2))
	got, err := dnsSensor(ctx, onLoopback("dns", port, map[string]any{"name": "localhost", "rrtype": "A"}), "")
	if took, ok := got["duration_ms"].(int64); err != nil || got["resolved"] != true || got["answers"] != 2 || got["rcode"] != "noerror" || !ok || took < 0 || len(got) != 4 {
		t.Fatalf("dns at a target = %v, %v; want two answers and noerror", got, err)
	}
	if len(*asked) != 0 {
		t.Errorf("the resolver of the host was asked %v", *asked)
	}
	q := <-queries
	// ID, flags RD alone, one question, no answer, authority or additional record (no EDNS OPT).
	if !bytes.Equal(q[2:12], []byte{0x01, 0x00, 0, 1, 0, 0, 0, 0, 0, 0}) {
		t.Errorf("header = % x, want RD alone and one question", q[:12])
	}
	if want := []byte("\x09localhost\x00\x00\x01\x00\x01"); !bytes.Equal(q[12:], want) {
		t.Errorf("question = %q, want %q", q[12:], want)
	}
}

func TestDNSSensorAtATargetNamesTheRcode(t *testing.T) {
	ctx := context.Background()
	for _, c := range []struct {
		rcode, n uint16
		want     string
		resolved bool
	}{
		{0, 0, "noerror", false},
		{3, 0, "nxdomain", false},
		{2, 0, "servfail", false},
		{5, 0, "refused", false},
		{4, 0, "other", false},
		{3, 1, "nxdomain", false},
	} {
		port, _ := dnsStub(t, false, reply(c.rcode, c.n))
		got, err := dnsSensor(ctx, onLoopback("dns", port, map[string]any{"name": "example.org"}), "")
		if err != nil || got["rcode"] != c.want || got["resolved"] != c.resolved || got["answers"] != int(c.n) {
			t.Errorf("rcode %d with %d answers = %v, %v; want %s, resolved %t", c.rcode, c.n, got, err, c.want, c.resolved)
		}
	}
}

func TestDNSSensorAtATargetAsksForTheReverseNameAndType(t *testing.T) {
	ctx := context.Background()
	for _, c := range []struct {
		name, rrtype, want string
	}{
		{"192.0.2.1", "PTR", "\x011\x012\x010\x03192\x07in-addr\x04arpa\x00\x00\x0c\x00\x01"},
		{"1.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.8.b.d.0.1.0.0.2.ip6.arpa", "PTR", "\x011" + strings.Repeat("\x010", 23) + "\x018\x01b\x01d\x010\x011\x010\x010\x012\x03ip6\x04arpa\x00\x00\x0c\x00\x01"},
		{"_ldap._tcp.example.org.", "SRV", "\x05_ldap\x04_tcp\x07example\x03org\x00\x00\x21\x00\x01"},
		{"example.org", "AAAA", "\x07example\x03org\x00\x00\x1c\x00\x01"},
	} {
		port, queries := dnsStub(t, false, reply(0, 1))
		if _, err := dnsSensor(ctx, onLoopback("dns", port, map[string]any{"name": c.name, "rrtype": c.rrtype}), ""); err != nil {
			t.Fatalf("%s %s: %v", c.rrtype, c.name, err)
		}
		if q := <-queries; string(q[12:]) != c.want {
			t.Errorf("%s %s asked %q, want %q", c.rrtype, c.name, q[12:], c.want)
		}
	}
}

func TestDNSSensorAtATargetTakesNoAnswerButOne(t *testing.T) {
	ctx := context.Background()
	for _, c := range []struct {
		name   string
		raw    bool
		answer func([]byte) []byte
	}{
		{"a short answer", false, func([]byte) []byte { return []byte{1, 2, 3, 4, 5} }},
		{"a length shorter than a header", true, func(q []byte) []byte {
			return append([]byte{0, 5}, reply(0, 1)(q)[:dnsHeader]...)
		}},
		{"another ID", false, func(q []byte) []byte { a := reply(0, 1)(q); a[0]++; return a }},
		{"a query, not an answer", false, func(q []byte) []byte { a := reply(0, 1)(q); a[2] &^= 0x80; return a }},
		{"nothing", false, func([]byte) []byte { return nil }},
	} {
		port, _ := dnsStub(t, c.raw, c.answer)
		if got, err := dnsSensor(ctx, onLoopback("dns", port, map[string]any{"name": "example.org"}), ""); err == nil {
			t.Errorf("%s = %v, want an error", c.name, got)
		}
	}

	// The deadline is what this checks: a server silent past it ends the probe with its timeout.
	short, cancel := context.WithTimeout(ctx, 200*time.Millisecond)
	defer cancel()
	port, _ := dnsStub(t, true, func([]byte) []byte { time.Sleep(time.Second); return nil })
	if _, err := dnsSensor(short, onLoopback("dns", port, map[string]any{"name": "example.org"}), ""); !errors.Is(err, context.DeadlineExceeded) {
		t.Errorf("a silent server = %v, want the probe's timeout", err)
	}
}

func TestDNSSensorTakesTheTargetsOfANetworkSensor(t *testing.T) {
	ctx := context.Background()
	for _, kind := range []string{"host", "url", ""} {
		p := Probe{Sensor: "dns", Target: &Target{Kind: kind, Name: "x"}, Params: map[string]any{"name": "example.org"}}
		if _, err := dnsSensor(ctx, p, ""); !errors.Is(err, ErrInvalid) {
			t.Errorf("target kind %q = %v, want ErrInvalid", kind, err)
		}
	}
	p := onLoopback("dns", 53, map[string]any{"name": "example.org"})
	p.Credential = &Credential{Use: useBearer}
	if _, err := dnsSensor(ctx, p, "s"); !errors.Is(err, ErrInvalid) {
		t.Errorf("a credential = %v, want ErrInvalid", err)
	}
}
