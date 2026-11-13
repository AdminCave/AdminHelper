// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package probe

import (
	"context"
	"errors"
	"fmt"
	"maps"
	"net"
	"regexp"
	"strings"
	"time"
)

// ldapSockets are the ldapi sockets of slapd: where Debian and Ubuntu place it, then OpenLDAP's own
// default.
var ldapSockets = []string{"/var/run/slapd/ldapi", "/var/run/ldapi"}

// ldapDial connects to an ldapi socket through the guard.
var ldapDial = dialUnix

const (
	// maxNamingContexts caps the naming contexts the view reads the contextCSN of.
	maxNamingContexts = 16
	// maxConsumers caps the syncrepl consumers the view counts.
	maxConsumers = 64
	// ldapMonitorBase holds the entries back-monitor keeps of the syncrepl consumers, one branch per
	// database (cn=Consumer NNN,cn=Database N,cn=Databases,cn=Monitor).
	ldapMonitorBase = "cn=Databases,cn=Monitor"
	// csnTime is the layout of the time of a CSN.
	csnTime = "20060102150405.000000Z"
)

// csnForm is a CSN of OpenLDAP 2.4 and later (lutil_csnstr): time, count, server id, modifier.
var csnForm = regexp.MustCompile(`^([0-9]{14}\.[0-9]{6}Z)#[0-9a-f]{6}#[0-9a-f]{3}#[0-9a-f]{6}$`)

// The result codes of LDAP the view tells apart (RFC 4511 §4.1.9).
const (
	ldapSuccess            = 0
	ldapSizeLimitExceeded  = 4
	ldapReferral           = 10
	ldapNoSuchObject       = 32
	ldapInsufficientAccess = 50
)

// The scopes of a search (RFC 4511 §4.5.1.2).
const (
	scopeBase    = 0
	scopeSubtree = 2
)

// ldapAnyEntry is the filter (objectClass=*).
var ldapAnyEntry = berTLV(0x87, []byte("objectClass"))

// ldapConsumerEntry is the filter (objectClass=olmSyncReplInstance).
var ldapConsumerEntry = berTLV(0xa3, berTLV(0x04, []byte("objectClass")), berTLV(0x04, []byte("olmSyncReplInstance")))

// ldapReplication reads the replication state of slapd on this host over its ldapi socket, bound
// with SASL EXTERNAL as the agent's own user: how many naming contexts carry a contextCSN and the
// age of the newest CSN, and, if cn=Monitor is set up and readable, how many syncrepl consumers
// there are, how many have no connection to their provider and how many are not in the persist
// phase. It reads the root DSE, the root entry of each naming context and the consumer entries of
// cn=Monitor, each for the attributes it counts alone; it never asks for olmSRProviderURIList, the
// addresses of the providers, and quotes no name and no value it read.
func ldapReplication(ctx context.Context, _ Target) (map[string]any, error) {
	conn, err := ldapConnect(ctx)
	if err != nil {
		return nil, err
	}
	c := &ldapClient{s: newSession(ctx, bind(ctx, conn))}
	defer c.s.end()
	if err := c.bindExternal(); err != nil {
		return nil, err
	}
	contexts, err := c.namingContexts()
	if err != nil {
		return nil, err
	}
	withCSN := 0
	var newest time.Time
	for _, dn := range contexts {
		csns, err := c.contextCSN(dn)
		if err != nil {
			return nil, err
		}
		if len(csns) > 0 {
			withCSN++
		}
		for _, t := range csns {
			if t.After(newest) {
				newest = t
			}
		}
	}
	values := map[string]any{"contexts": withCSN, "monitor": false}
	if withCSN > 0 {
		values["csn_age_s"] = max(int(now().Sub(newest).Seconds()), 0)
	}
	consumers, err := c.consumers()
	if err != nil {
		return nil, err
	}
	if consumers != nil {
		values["monitor"] = true
		maps.Copy(values, consumers)
	}
	return values, nil
}

// ldapConnect connects to the first ldapi socket of ldapSockets that slapd serves.
func ldapConnect(ctx context.Context) (net.Conn, error) {
	for _, path := range ldapSockets {
		conn, err := ldapDial(ctx, path)
		if errors.Is(err, errNoListener) {
			continue
		}
		return conn, err
	}
	return nil, fmt.Errorf("%w: slapd serves no ldapi socket on this host", ErrUnsupported)
}

// ldapClient is a session of LDAP: its requests carry ascending message ids, its goodbye is an
// UnbindRequest with the next.
type ldapClient struct {
	s  *session
	id byte
}

// ldapEntry holds the values of the attributes asked for of one entry, by the name they were asked
// for.
type ldapEntry map[string][][]byte

// ask sends op, the request what, as the next message.
func (c *ldapClient) ask(what string, op []byte) error {
	c.id++
	c.s.goodbye = ldapUnbind(c.id + 1)
	return c.s.send(what, berTLV(0x30, []byte{0x02, 0x01, c.id}, op))
}

// answer reads the next answer to the request what: the tag and content of its protocolOp.
func (c *ldapClient) answer(what string) (byte, []byte, error) {
	msg, err := berMessage(c.s, what)
	if err != nil {
		return 0, nil, err
	}
	noAnswer := protoFail{"no LDAP answer to " + what}
	tag, id, rest, ok := berNext(msg)
	if !ok || tag != 0x02 || len(id) == 0 || len(id) > 4 {
		return 0, nil, noAnswer
	}
	switch berInt(id) {
	case 0:
		// Message id 0 is a notice of disconnection (RFC 4511 §4.4.1).
		return 0, nil, protoFail{"the server ended the session"}
	case int(c.id):
	default:
		return 0, nil, noAnswer
	}
	tag, op, _, ok := berNext(rest)
	if !ok {
		return 0, nil, noAnswer
	}
	return tag, op, nil
}

// ldapCode is the resultCode of the LDAPResult op, the answer to what.
func ldapCode(op []byte, what string) (int, error) {
	tag, code, _, ok := berNext(op)
	if !ok || tag != 0x0a || len(code) == 0 || len(code) > 4 {
		return 0, protoFail{"no LDAP answer to " + what}
	}
	return berInt(code), nil
}

// bindExternal binds with SASL EXTERNAL (RFC 4513 §5.2.1.2): on ldapi slapd takes the user of the
// agent's process for the identity, with no secret on the wire.
func (c *ldapClient) bindExternal() error {
	const what = "the bind with SASL EXTERNAL"
	op := berTLV(0x60, []byte{0x02, 0x01, 0x03}, berTLV(0x04), berTLV(0xa3, berTLV(0x04, []byte("EXTERNAL"))))
	if err := c.ask(what, op); err != nil {
		return err
	}
	tag, res, err := c.answer(what)
	if err != nil {
		return err
	}
	if tag != 0x61 {
		return protoFail{"no LDAP answer to " + what}
	}
	code, err := ldapCode(res, what)
	if err != nil {
		return err
	}
	if code != ldapSuccess {
		return fmt.Errorf("slapd refuses %s with result %d", what, code)
	}
	return nil
}

// search asks for attrs of the entries in scope of base that filter matches, at most limit (below
// 128), and returns them with the resultCode of the search. References it skips; an answer beyond
// limit fails.
func (c *ldapClient) search(what, base string, scope byte, filter []byte, limit byte, attrs ...string) ([]ldapEntry, int, error) {
	list := make([][]byte, len(attrs))
	for i, a := range attrs {
		list[i] = berTLV(0x04, []byte(a))
	}
	op := berTLV(0x63, berTLV(0x04, []byte(base)),
		[]byte{0x0a, 0x01, scope}, // scope
		[]byte{0x0a, 0x01, 0x00},  // derefAliases: never
		[]byte{0x02, 0x01, limit}, // sizeLimit
		[]byte{0x02, 0x01, 0x00},  // timeLimit: the probe's deadline ends the session
		[]byte{0x01, 0x01, 0x00},  // typesOnly: false
		filter, berTLV(0x30, list...))
	if err := c.ask(what, op); err != nil {
		return nil, 0, err
	}
	noAnswer := protoFail{"no LDAP answer to " + what}
	var entries []ldapEntry
	for answers := 0; ; answers++ {
		if answers > int(limit) {
			return nil, 0, protoFail{fmt.Sprintf("more than %d answers to %s", limit, what)}
		}
		tag, op, err := c.answer(what)
		if err != nil {
			return nil, 0, err
		}
		switch tag {
		case 0x64: // SearchResultEntry
			e, ok := ldapEntryOf(op, attrs)
			if !ok {
				return nil, 0, noAnswer
			}
			entries = append(entries, e)
		case 0x73: // SearchResultReference: the view follows none
		case 0x65: // SearchResultDone
			code, err := ldapCode(op, what)
			return entries, code, err
		default:
			return nil, 0, noAnswer
		}
	}
}

// ldapEntryOf reads the values of attrs of the SearchResultEntry op; ok is false if op is no such entry.
func ldapEntryOf(op []byte, attrs []string) (ldapEntry, bool) {
	tag, _, rest, ok := berNext(op)
	if !ok || tag != 0x04 {
		return nil, false
	}
	tag, list, _, ok := berNext(rest)
	if !ok || tag != 0x30 {
		return nil, false
	}
	e := ldapEntry{}
	for len(list) > 0 {
		var attr []byte
		if tag, attr, list, ok = berNext(list); !ok || tag != 0x30 {
			return nil, false
		}
		tag, name, rest, ok := berNext(attr)
		if !ok || tag != 0x04 {
			return nil, false
		}
		tag, set, _, ok := berNext(rest)
		if !ok || tag != 0x31 {
			return nil, false
		}
		var vals [][]byte
		for len(set) > 0 {
			var v []byte
			if tag, v, set, ok = berNext(set); !ok || tag != 0x04 {
				return nil, false
			}
			vals = append(vals, v)
		}
		for _, a := range attrs {
			if strings.EqualFold(a, string(name)) {
				e[a] = append(e[a], vals...)
			}
		}
	}
	return e, true
}

// namingContexts reads the naming contexts of the root DSE, at most maxNamingContexts.
func (c *ldapClient) namingContexts() ([]string, error) {
	const what = "the search of the root DSE"
	entries, code, err := c.search(what, "", scopeBase, ldapAnyEntry, 1, "namingContexts")
	switch {
	case err != nil:
		return nil, err
	case code != ldapSuccess:
		return nil, fmt.Errorf("slapd answers %s with result %d", what, code)
	case len(entries) != 1:
		return nil, fmt.Errorf("slapd answers %s with no entry", what)
	}
	vals := entries[0]["namingContexts"]
	if len(vals) > maxNamingContexts {
		return nil, fmt.Errorf("slapd holds more than %d naming contexts", maxNamingContexts)
	}
	dns := make([]string, len(vals))
	for i, v := range vals {
		dns[i] = string(v)
	}
	return dns, nil
}

// contextCSN reads the times of the contextCSN of the naming context dn, one per server id; none
// if the context holds no entry yet.
func (c *ldapClient) contextCSN(dn string) ([]time.Time, error) {
	const what = "the search of a naming context"
	entries, code, err := c.search(what, dn, scopeBase, ldapAnyEntry, 1, "contextCSN")
	switch {
	case err != nil:
		return nil, err
	case code == ldapNoSuchObject:
		return nil, nil
	case code != ldapSuccess:
		return nil, fmt.Errorf("slapd answers %s with result %d", what, code)
	}
	var times []time.Time
	for _, e := range entries {
		for _, v := range e["contextCSN"] {
			m := csnForm.FindSubmatch(v)
			if m == nil {
				return nil, errors.New("a contextCSN is not of the form of OpenLDAP 2.4 or later")
			}
			t, err := time.Parse(csnTime, string(m[1]))
			if err != nil {
				return nil, errors.New("a contextCSN holds no valid time")
			}
			times = append(times, t)
		}
	}
	return times, nil
}

// consumers counts the syncrepl consumers back-monitor lists: all, those without a connection to
// their provider (an empty olmSRConnection) and those not in the persist phase. They are nil if
// cn=Monitor is not set up on this host or not readable to the agent.
func (c *ldapClient) consumers() (map[string]any, error) {
	const what = "the search of cn=Monitor"
	entries, code, err := c.search(what, ldapMonitorBase, scopeSubtree, ldapConsumerEntry, maxConsumers,
		"olmSRConnection", "olmSRSyncPhase")
	switch {
	case err != nil:
		return nil, err
	case code == ldapNoSuchObject, code == ldapInsufficientAccess, code == ldapReferral:
		return nil, nil
	case code == ldapSizeLimitExceeded:
		return nil, fmt.Errorf("slapd has more than %d syncrepl consumers", maxConsumers)
	case code != ldapSuccess:
		return nil, fmt.Errorf("slapd answers %s with result %d", what, code)
	}
	disconnected, refreshing := 0, 0
	for _, e := range entries {
		conn, phase := e["olmSRConnection"], e["olmSRSyncPhase"]
		if len(conn) != 1 || len(phase) != 1 {
			return nil, errors.New("a syncrepl consumer of cn=Monitor shows no connection or no phase")
		}
		if len(conn[0]) == 0 {
			disconnected++
		}
		if string(phase[0]) != "Persist" {
			refreshing++
		}
	}
	return map[string]any{"consumers": len(entries), "disconnected": disconnected, "refreshing": refreshing}, nil
}

// berTLV is the element of BER of tag with content, its length in the definite form.
func berTLV(tag byte, content ...[]byte) []byte {
	n := 0
	for _, c := range content {
		n += len(c)
	}
	b := []byte{tag}
	switch {
	case n < 0x80:
		b = append(b, byte(n))
	case n <= 0xff:
		b = append(b, 0x81, byte(n))
	case n <= 0xffff:
		b = append(b, 0x82, byte(n>>8), byte(n))
	default:
		b = append(b, 0x83, byte(n>>16), byte(n>>8), byte(n))
	}
	for _, c := range content {
		b = append(b, c...)
	}
	return b
}
