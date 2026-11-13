// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package probe

import (
	"bufio"
	"context"
	"errors"
	"fmt"
	"io"
	"net"
	"reflect"
	"strings"
	"sync"
	"testing"
	"time"
)

// slapd is a fake slapd: what it holds and how it answers.
type slapd struct {
	bind     byte                // resultCode of the bind
	contexts []string            // namingContexts of the root DSE
	csns     map[string][]string // contextCSN by naming context; a context without a key answers noSuchObject
	monitor  byte                // resultCode of the search of cn=Monitor
	// consumers are olmSRConnection and olmSRSyncPhase of each consumer; "-" leaves one out.
	consumers [][2]string
	// tamper, if set, replaces the answers to a request.
	tamper func(r ldapRequest, answers [][]byte) [][]byte
}

// ldapRequest is a request the fake slapd heard.
type ldapRequest struct {
	id     byte
	op     byte
	mech   string // of a bind
	base   string
	scope  byte
	size   int
	filter []byte
	attrs  []string
}

func (r ldapRequest) String() string {
	switch r.op {
	case 0x60:
		return "bind " + r.mech
	case 0x63:
		return fmt.Sprintf("search %q scope %d size %d filter % x attrs %v", r.base, r.scope, r.size, r.filter, r.attrs)
	case 0x42:
		return "unbind"
	}
	return fmt.Sprintf("op %#x", r.op)
}

// ldapLog is what the fake slapd heard: each request and the bytes of each message.
type ldapLog struct {
	mu       sync.Mutex
	requests []ldapRequest
	raw      []string
	dialed   []string
}

func (l *ldapLog) heard() ([]ldapRequest, []string) {
	l.mu.Lock()
	defer l.mu.Unlock()
	return append([]ldapRequest(nil), l.requests...), append([]string(nil), l.raw...)
}

// readLDAPMessage reads one LDAPMessage of the client and returns its content.
func readLDAPMessage(r *bufio.Reader) ([]byte, string, bool) {
	head := make([]byte, 2)
	if _, err := io.ReadFull(r, head); err != nil || head[0] != 0x30 {
		return nil, "", false
	}
	n, lenBytes := int(head[1]), []byte(nil)
	if n&0x80 != 0 {
		lenBytes = make([]byte, n&0x7f)
		if _, err := io.ReadFull(r, lenBytes); err != nil {
			return nil, "", false
		}
		n = 0
		for _, b := range lenBytes {
			n = n<<8 | int(b)
		}
	}
	msg := make([]byte, n)
	if _, err := io.ReadFull(r, msg); err != nil {
		return nil, "", false
	}
	return msg, fmt.Sprintf("% x", append(append(head, lenBytes...), msg...)), true
}

// berElems splits b into its elements; ok is false unless b is whole elements.
func berElems(b []byte) (tags []byte, contents [][]byte, ok bool) {
	for len(b) > 0 {
		tag, content, rest, ok := berNext(b)
		if !ok {
			return nil, nil, false
		}
		tags, contents, b = append(tags, tag), append(contents, content), rest
	}
	return tags, contents, true
}

func parseLDAPRequest(msg []byte) (ldapRequest, bool) {
	tags, parts, ok := berElems(msg)
	if !ok || len(parts) < 2 || tags[0] != 0x02 || len(parts[0]) != 1 {
		return ldapRequest{}, false
	}
	r := ldapRequest{id: parts[0][0], op: tags[1]}
	tags, parts, ok = berElems(parts[1])
	if !ok {
		return ldapRequest{}, false
	}
	switch r.op {
	case 0x60:
		if len(parts) != 3 || tags[2] != 0xa3 {
			return ldapRequest{}, false
		}
		_, sasl, ok := berElems(parts[2])
		if !ok || len(sasl) == 0 {
			return ldapRequest{}, false
		}
		r.mech = string(sasl[0])
	case 0x63:
		if len(parts) != 8 || tags[7] != 0x30 {
			return ldapRequest{}, false
		}
		r.base, r.scope, r.size, r.filter = string(parts[0]), parts[1][0], berInt(parts[3]), berTLV(tags[6], parts[6])
		_, attrs, ok := berElems(parts[7])
		if !ok {
			return ldapRequest{}, false
		}
		for _, a := range attrs {
			r.attrs = append(r.attrs, string(a))
		}
	}
	return r, true
}

func ldapMsg(id byte, op []byte) []byte { return berTLV(0x30, []byte{0x02, 0x01, id}, op) }

// ldapDone is an LDAPResult with tag and resultCode code.
func ldapDone(tag, code byte) []byte {
	return berTLV(tag, []byte{0x0a, 0x01, code}, berTLV(0x04), berTLV(0x04))
}

// ldapEntryAnswer is a SearchResultEntry of dn with the values of each attribute, in order.
func ldapEntryAnswer(dn string, attrs ...any) []byte {
	var list [][]byte
	for i := 0; i+1 < len(attrs); i += 2 {
		var vals [][]byte
		for _, v := range attrs[i+1].([]string) {
			vals = append(vals, berTLV(0x04, []byte(v)))
		}
		list = append(list, berTLV(0x30, berTLV(0x04, []byte(attrs[i].(string))), berTLV(0x31, vals...)))
	}
	return berTLV(0x64, berTLV(0x04, []byte(dn)), berTLV(0x30, list...))
}

// answers are the answers of d to r.
func (d *slapd) answers(r ldapRequest) [][]byte {
	switch {
	case r.op == 0x60:
		return [][]byte{ldapDone(0x61, d.bind)}
	case r.op != 0x63:
		return nil
	case r.base == "":
		return [][]byte{ldapEntryAnswer("", "namingContexts", d.contexts), ldapDone(0x65, 0)}
	case r.base == ldapMonitorBase:
		if d.monitor != 0 {
			return [][]byte{ldapDone(0x65, d.monitor)}
		}
		var out [][]byte
		for i, c := range d.consumers {
			var attrs []any
			if c[0] != "-" {
				attrs = append(attrs, "olmSRConnection", []string{c[0]})
			}
			if c[1] != "-" {
				attrs = append(attrs, "olmSRSyncPhase", []string{c[1]})
			}
			out = append(out, ldapEntryAnswer(fmt.Sprintf("cn=Consumer %03d,cn=Database 2,cn=Databases,cn=Monitor", i+1), attrs...))
		}
		return append(out, ldapDone(0x65, 0))
	}
	csns, ok := d.csns[r.base]
	if !ok {
		return [][]byte{ldapDone(0x65, ldapNoSuchObject)}
	}
	var attrs []any
	if csns != nil {
		attrs = []any{"contextCSN", csns}
	}
	return [][]byte{ldapEntryAnswer(r.base, attrs...), ldapDone(0x65, 0)}
}

// serve answers the requests of one connection until the client unbinds or closes.
func (d *slapd) serve(log *ldapLog) func(*fakeConn) {
	return func(c *fakeConn) {
		for {
			msg, raw, ok := readLDAPMessage(c.r)
			if !ok {
				return
			}
			r, ok := parseLDAPRequest(msg)
			log.mu.Lock()
			log.raw = append(log.raw, raw)
			if ok {
				log.requests = append(log.requests, r)
			}
			log.mu.Unlock()
			if !ok || r.op == 0x42 {
				return
			}
			answers := d.answers(r)
			if d.tamper != nil {
				answers = d.tamper(r, answers)
			}
			for _, a := range answers {
				if a == nil {
					return // the fake closes the connection
				}
				_, _ = c.conn.Write(ldapMsg(r.id, a))
			}
		}
	}
}

// serveSlapd serves d at the second of two ldapi sockets of the view and returns what it hears.
func serveSlapd(t *testing.T, d *slapd) *ldapLog {
	t.Helper()
	log := &ldapLog{}
	f := listen(t, d.serve(log))
	stubLDAPDial(t, log, func(ctx context.Context, path string) (net.Conn, error) {
		if path != "second" {
			return nil, errNoListener
		}
		var dialer net.Dialer
		return dialer.DialContext(ctx, "tcp4", f.ln.Addr().String())
	})
	return log
}

func stubLDAPDial(t *testing.T, log *ldapLog, dial func(context.Context, string) (net.Conn, error)) {
	t.Helper()
	oldSockets, oldDial := ldapSockets, ldapDial
	ldapSockets = []string{"first", "second"}
	ldapDial = func(ctx context.Context, path string) (net.Conn, error) {
		log.mu.Lock()
		log.dialed = append(log.dialed, path)
		log.mu.Unlock()
		return dial(ctx, path)
	}
	t.Cleanup(func() { ldapSockets, ldapDial = oldSockets, oldDial })
}

const (
	csnA1 = "20261113115000.123456Z#000001#001#000000"
	csnA2 = "20261113115930.000000Z#000004#002#000000" // the newest: 30 s before noon
	csnB  = "20261112120000.000000Z#000002#001#000000"
)

func replicatingSlapd() *slapd {
	return &slapd{
		contexts: []string{"dc=example,dc=org", "ou=hidden,dc=example,dc=net"},
		csns: map[string][]string{
			"dc=example,dc=org":           {csnA1, csnA2},
			"ou=hidden,dc=example,dc=net": {csnB},
		},
		consumers: [][2]string{
			{"IP=192.0.2.10:48712", "Persist"},
			{"", "Persist"},
			{"IP=192.0.2.10:48713", "Refresh"},
			{"", "Fallback Refresh"},
		},
	}
}

// ldapSecrets are what neither a value nor an error of the view may hold.
var ldapSecrets = []string{"example", "dc=", "192.0.2.10", "Consumer", "Persist", "Refresh", "000001#001"}

func TestTheReplicationViewCountsContextsAndConsumers(t *testing.T) {
	at := time.Date(2026, 11, 13, 12, 0, 0, 0, time.UTC)
	stubNow(t, at)
	log := serveSlapd(t, replicatingSlapd())
	got, err := ldapReplication(context.Background(), *unitTarget("slapd.service"))
	if err != nil {
		t.Fatal(err)
	}
	want := map[string]any{"contexts": 2, "csn_age_s": 30, "monitor": true, "consumers": 4, "disconnected": 2, "refreshing": 2}
	if !reflect.DeepEqual(got, want) {
		t.Errorf("values %v, want %v", got, want)
	}
	requests, _ := log.heard()
	var heard []string
	for _, r := range requests {
		heard = append(heard, r.String())
	}
	any := "87 0b 6f 62 6a 65 63 74 43 6c 61 73 73"
	wantHeard := []string{
		"bind EXTERNAL",
		`search "" scope 0 size 1 filter ` + any + ` attrs [namingContexts]`,
		`search "dc=example,dc=org" scope 0 size 1 filter ` + any + ` attrs [contextCSN]`,
		`search "ou=hidden,dc=example,dc=net" scope 0 size 1 filter ` + any + ` attrs [contextCSN]`,
		`search "cn=Databases,cn=Monitor" scope 2 size 64 filter a3 22 04 0b 6f 62 6a 65 63 74 43 6c 61 73 73 04 13 6f 6c 6d 53 79 6e 63 52 65 70 6c 49 6e 73 74 61 6e 63 65 attrs [olmSRConnection olmSRSyncPhase]`,
		"unbind",
	}
	if !reflect.DeepEqual(heard, wantHeard) {
		t.Errorf("heard\n%s\nwant\n%s", strings.Join(heard, "\n"), strings.Join(wantHeard, "\n"))
	}
	for i, r := range requests {
		if r.id != byte(i+1) {
			t.Errorf("request %d has message id %d, want %d", i, r.id, i+1)
		}
	}
	if !reflect.DeepEqual(log.dialed, []string{"first", "second"}) {
		t.Errorf("dialed %v, want the first socket, then the second", log.dialed)
	}
}

func TestTheReplicationViewNeverAsksForTheProviders(t *testing.T) {
	log := serveSlapd(t, replicatingSlapd())
	if _, err := ldapReplication(context.Background(), *unitTarget("slapd.service")); err != nil {
		t.Fatal(err)
	}
	requests, _ := log.heard()
	for _, r := range requests {
		for _, a := range r.attrs {
			if strings.EqualFold(a, "olmSRProviderURIList") || a == "*" || a == "+" {
				t.Errorf("%s asks for %s", r, a)
			}
		}
		if r.op == 0x63 && len(r.attrs) == 0 {
			t.Errorf("%s asks for all attributes", r)
		}
	}
}

func TestTheReplicationViewSpeaksBERByteForByte(t *testing.T) {
	log := serveSlapd(t, &slapd{})
	if _, err := ldapReplication(context.Background(), *unitTarget("slapd.service")); err != nil {
		t.Fatal(err)
	}
	_, raw := log.heard()
	want := []string{
		// LDAPMessage 1, BindRequest: version 3, name "", sasl EXTERNAL without credentials.
		"30 16 02 01 01 60 11 02 01 03 04 00 a3 0a 04 08 45 58 54 45 52 4e 41 4c",
		// LDAPMessage 2, SearchRequest: base "", baseObject, neverDerefAliases, size 1, time 0,
		// typesOnly false, (objectClass=*), attributes namingContexts.
		"30 35 02 01 02 63 30 04 00 0a 01 00 0a 01 00 02 01 01 02 01 00 01 01 00 " +
			"87 0b 6f 62 6a 65 63 74 43 6c 61 73 73 30 10 04 0e 6e 61 6d 69 6e 67 43 6f 6e 74 65 78 74 73",
	}
	if len(raw) < 2 || !reflect.DeepEqual(raw[:2], want) {
		t.Errorf("heard\n%s\nwant\n%s", strings.Join(raw, "\n"), strings.Join(want, "\n"))
	}
	if last := raw[len(raw)-1]; last != fmt.Sprintf("30 05 02 01 %02x 42 00", len(raw)) {
		t.Errorf("last message %s, want an UnbindRequest with the next message id", last)
	}
}

func TestTheReplicationViewTakesLongNames(t *testing.T) {
	stubNow(t, time.Date(2026, 11, 13, 12, 0, 0, 0, time.UTC))
	long := "ou=" + strings.Repeat("x", 300) + ",dc=example,dc=org"
	d := &slapd{contexts: []string{long}, csns: map[string][]string{long: {csnA2}}}
	log := serveSlapd(t, d)
	got, err := ldapReplication(context.Background(), *unitTarget("slapd.service"))
	if err != nil {
		t.Fatal(err)
	}
	if got["contexts"] != 1 || got["csn_age_s"] != 30 {
		t.Errorf("values %v, want one context of age 30", got)
	}
	requests, _ := log.heard()
	if len(requests) < 3 || requests[2].base != long {
		t.Errorf("requests %v, want the search of the long context", requests)
	}
}

func TestTheReplicationViewCountsOnlyContextsWithACSN(t *testing.T) {
	stubNow(t, time.Date(2026, 11, 13, 12, 0, 0, 0, time.UTC))
	cases := map[string]struct {
		d    *slapd
		want map[string]any
	}{
		"no context": {&slapd{}, map[string]any{"contexts": 0, "monitor": true, "consumers": 0, "disconnected": 0, "refreshing": 0}},
		"an empty context and one without a CSN": {
			&slapd{contexts: []string{"dc=empty", "dc=new"}, csns: map[string][]string{"dc=new": nil}},
			map[string]any{"contexts": 0, "monitor": true, "consumers": 0, "disconnected": 0, "refreshing": 0},
		},
		"a CSN ahead of the clock": {
			&slapd{contexts: []string{"dc=a"}, csns: map[string][]string{"dc=a": {"20261113121500.000000Z#000000#001#000000"}}},
			map[string]any{"contexts": 1, "csn_age_s": 0, "monitor": true, "consumers": 0, "disconnected": 0, "refreshing": 0},
		},
	}
	for name, c := range cases {
		t.Run(name, func(t *testing.T) {
			serveSlapd(t, c.d)
			got, err := ldapReplication(context.Background(), *unitTarget("slapd.service"))
			if err != nil {
				t.Fatal(err)
			}
			if !reflect.DeepEqual(got, c.want) {
				t.Errorf("values %v, want %v", got, c.want)
			}
		})
	}
}

func TestTheReplicationViewTakesTheCaseOfTheServer(t *testing.T) {
	stubNow(t, time.Date(2026, 11, 13, 12, 0, 0, 0, time.UTC))
	d := replicatingSlapd()
	d.tamper = func(r ldapRequest, answers [][]byte) [][]byte {
		if r.op == 0x63 && r.base == "dc=example,dc=org" {
			return [][]byte{ldapEntryAnswer(r.base, "CONTEXTcsn", []string{csnA2}), ldapDone(0x65, 0)}
		}
		return answers
	}
	serveSlapd(t, d)
	got, err := ldapReplication(context.Background(), *unitTarget("slapd.service"))
	if err != nil {
		t.Fatal(err)
	}
	if got["csn_age_s"] != 30 {
		t.Errorf("values %v, want csn_age_s 30", got)
	}
}

func TestTheReplicationViewWithoutAMonitor(t *testing.T) {
	stubNow(t, time.Date(2026, 11, 13, 12, 0, 0, 0, time.UTC))
	for name, code := range map[string]byte{
		"not set up":          ldapNoSuchObject,
		"not readable":        ldapInsufficientAccess,
		"held by another DSA": ldapReferral,
	} {
		t.Run(name, func(t *testing.T) {
			d := replicatingSlapd()
			d.monitor = code
			serveSlapd(t, d)
			got, err := ldapReplication(context.Background(), *unitTarget("slapd.service"))
			if err != nil {
				t.Fatal(err)
			}
			want := map[string]any{"contexts": 2, "csn_age_s": 30, "monitor": false}
			if !reflect.DeepEqual(got, want) {
				t.Errorf("values %v, want %v", got, want)
			}
		})
	}
}

func TestTheReplicationViewIsUnsupportedWithoutSlapd(t *testing.T) {
	log := &ldapLog{}
	stubLDAPDial(t, log, func(context.Context, string) (net.Conn, error) { return nil, errNoListener })
	_, err := ldapReplication(context.Background(), *unitTarget("slapd.service"))
	if !errors.Is(err, ErrUnsupported) {
		t.Errorf("error %v, want ErrUnsupported", err)
	}
	if !reflect.DeepEqual(log.dialed, []string{"first", "second"}) {
		t.Errorf("dialed %v, want both sockets", log.dialed)
	}
}

func TestTheReplicationViewStopsAtASocketItMayNotAsk(t *testing.T) {
	log := &ldapLog{}
	stubLDAPDial(t, log, func(context.Context, string) (net.Conn, error) {
		return nil, fmt.Errorf("%w: a forwarder", ErrNotAllowed)
	})
	_, err := ldapReplication(context.Background(), *unitTarget("slapd.service"))
	if !errors.Is(err, ErrNotAllowed) {
		t.Errorf("error %v, want ErrNotAllowed", err)
	}
	if !reflect.DeepEqual(log.dialed, []string{"first"}) {
		t.Errorf("dialed %v, want the first socket alone", log.dialed)
	}
}

func TestTheReplicationViewFailsWithoutLeakingAnything(t *testing.T) {
	many := func(n int) []string {
		var dns []string
		for i := range n {
			dns = append(dns, fmt.Sprintf("dc=example%d", i))
		}
		return dns
	}
	onSearchOf := func(base string, answers ...[]byte) func(ldapRequest, [][]byte) [][]byte {
		return func(r ldapRequest, own [][]byte) [][]byte {
			if r.op == 0x63 && r.base == base {
				return answers
			}
			return own
		}
	}
	consumer := func(i int) []byte {
		return ldapEntryAnswer(fmt.Sprintf("cn=Consumer %03d,cn=Monitor", i), "olmSRConnection", []string{"IP=192.0.2.10:1"}, "olmSRSyncPhase", []string{"Persist"})
	}
	var tooMany [][]byte
	for i := range maxConsumers + 1 {
		tooMany = append(tooMany, consumer(i))
	}
	cases := map[string]struct {
		change func(d *slapd)
		want   string
	}{
		"a refused bind": {func(d *slapd) { d.bind = 48 }, "refuses the bind with SASL EXTERNAL with result 48"},
		"a CSN of OpenLDAP 2.3": {func(d *slapd) {
			d.csns["dc=example,dc=org"] = []string{csnA1, "20261113115000Z#000001#00#000000"}
		}, "not of the form"},
		"a CSN of no form": {func(d *slapd) { d.csns["dc=example,dc=org"] = []string{"example Persist"} }, "not of the form"},
		"a CSN with a short server id": {func(d *slapd) {
			d.csns["dc=example,dc=org"] = []string{"20261113115000.000000Z#000001#01#000000"}
		}, "not of the form"},
		"a CSN of no time": {func(d *slapd) {
			d.csns["dc=example,dc=org"] = []string{"20261313115000.000000Z#000001#001#000000"}
		}, "no valid time"},
		"too many contexts": {func(d *slapd) {
			d.contexts = many(maxNamingContexts + 1)
		}, "more than 16 naming contexts"},
		"a consumer without a phase":      {func(d *slapd) { d.consumers[1][1] = "-" }, "no connection or no phase"},
		"a consumer without a connection": {func(d *slapd) { d.consumers[0][0] = "-" }, "no connection or no phase"},
		"too many consumers":              {func(d *slapd) { d.monitor = ldapSizeLimitExceeded }, "more than 64 syncrepl consumers"},
		"more consumers than asked": {func(d *slapd) {
			d.tamper = onSearchOf(ldapMonitorBase, append(tooMany, ldapDone(0x65, 0))...)
		}, "more than 64 answers to the search of cn=Monitor"},
		"two root entries of a context": {func(d *slapd) {
			d.tamper = onSearchOf("dc=example,dc=org", ldapEntryAnswer("dc=example,dc=org"), ldapEntryAnswer("dc=example,dc=org"), ldapDone(0x65, 0))
		}, "more than 1 answers to the search of a naming context"},
		"a failing search of a context": {func(d *slapd) {
			d.tamper = onSearchOf("dc=example,dc=org", ldapDone(0x65, 53))
		}, "naming context with result 53"},
		"a failing search of the root DSE": {func(d *slapd) {
			d.tamper = onSearchOf("", ldapDone(0x65, 50))
		}, "root DSE with result 50"},
		"a root DSE without an entry": {func(d *slapd) {
			d.tamper = onSearchOf("", ldapDone(0x65, 0))
		}, "root DSE with no entry"},
		"a failing search of cn=Monitor": {func(d *slapd) { d.monitor = 80 }, "cn=Monitor with result 80"},
		"a notice of disconnection": {func(d *slapd) {
			d.tamper = func(r ldapRequest, own [][]byte) [][]byte {
				if r.op == 0x63 && r.base == "dc=example,dc=org" {
					return [][]byte{nil}
				}
				return own
			}
		}, "closed at the search of a naming context"},
		"an answer of another operation": {func(d *slapd) {
			d.tamper = onSearchOf("", ldapDone(0x67, 0))
		}, "no LDAP answer to the search of the root DSE"},
		"a bind answered as a search": {func(d *slapd) {
			d.tamper = func(r ldapRequest, own [][]byte) [][]byte {
				if r.op == 0x60 {
					return [][]byte{ldapDone(0x65, 0)}
				}
				return own
			}
		}, "no LDAP answer to the bind"},
		"a broken entry": {func(d *slapd) {
			d.tamper = onSearchOf("dc=example,dc=org", berTLV(0x64, berTLV(0x04, []byte("dc=example,dc=org")), berTLV(0x31)), ldapDone(0x65, 0))
		}, "no LDAP answer to the search of a naming context"},
	}
	for name, c := range cases {
		t.Run(name, func(t *testing.T) {
			d := replicatingSlapd()
			c.change(d)
			serveSlapd(t, d)
			values, err := ldapReplication(context.Background(), *unitTarget("slapd.service"))
			if err == nil || !strings.Contains(err.Error(), c.want) {
				t.Fatalf("values %v, error %v; want an error naming %q", values, err, c.want)
			}
			if errors.Is(err, ErrUnsupported) {
				t.Errorf("error %v is unsupported, want a failure", err)
			}
			holdsNoSecret(t, "error", err.Error(), ldapSecrets)
			res := Run(context.Background(), appProbe("ldap_replication", unitTarget("slapd.service")), time.Now(), nil)
			if res.Status != StatusError {
				t.Errorf("status %s, want error", res.Status)
			}
			holdsNoSecret(t, "error of Run", res.Error, ldapSecrets)
		})
	}
}

func TestTheReplicationViewAnswersOnlyItsOwnMessageIDs(t *testing.T) {
	cases := map[string]struct {
		id   byte
		want string
	}{
		"a notice of disconnection": {0, "the server ended the session"},
		"another message":           {9, "no LDAP answer to the search of the root DSE"},
	}
	for name, c := range cases {
		t.Run(name, func(t *testing.T) {
			log := &ldapLog{}
			f := listen(t, func(fc *fakeConn) {
				for {
					msg, _, ok := readLDAPMessage(fc.r)
					if !ok {
						return
					}
					r, _ := parseLDAPRequest(msg)
					switch r.op {
					case 0x60:
						_, _ = fc.conn.Write(ldapMsg(r.id, ldapDone(0x61, 0)))
					case 0x63:
						_, _ = fc.conn.Write(ldapMsg(c.id, ldapDone(0x65, 0)))
					default:
						return
					}
				}
			})
			stubLDAPDial(t, log, func(ctx context.Context, path string) (net.Conn, error) {
				var dialer net.Dialer
				return dialer.DialContext(ctx, "tcp4", f.ln.Addr().String())
			})
			_, err := ldapReplication(context.Background(), *unitTarget("slapd.service"))
			if err == nil || !strings.Contains(err.Error(), c.want) {
				t.Errorf("error %v, want %q", err, c.want)
			}
		})
	}
}

func TestTheReplicationViewRunsThroughRunWithOnlyTheAskedFields(t *testing.T) {
	at := time.Date(2026, 11, 13, 12, 0, 0, 0, time.UTC)
	stubNow(t, at)
	serveSlapd(t, replicatingSlapd())
	res := Run(context.Background(), appProbe("ldap_replication", unitTarget("slapd.service"), "disconnected", "csn_age_s"), at, nil)
	if res.Status != StatusOK {
		t.Fatalf("status %s (%s), want ok", res.Status, res.Error)
	}
	want := map[string]any{"disconnected": 2, "csn_age_s": 30}
	if !reflect.DeepEqual(res.Values, want) {
		t.Errorf("values %v, want %v", res.Values, want)
	}
}

func TestBerTLVTakesTheShortestDefiniteLength(t *testing.T) {
	cases := map[int]string{0: "04 00", 0x7f: "04 7f", 0x80: "04 81 80", 0xff: "04 81 ff", 0x100: "04 82 01 00", 0x10000: "04 83 01 00 00"}
	for n, want := range cases {
		b := berTLV(0x04, make([]byte, n))
		if got := fmt.Sprintf("% x", b[:len(b)-n]); got != want {
			t.Errorf("head of %d bytes %s, want %s", n, got, want)
		}
	}
}
