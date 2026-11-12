// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package probe

import (
	"bufio"
	"bytes"
	"context"
	"crypto/tls"
	"encoding/binary"
	"encoding/csv"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"slices"
	"strconv"
	"strings"
	"time"
)

func init() {
	sensors["proto"] = protoSensor
}

const (
	// maxProtoLine caps one line a server answers.
	maxProtoLine = 4096
	// maxReplyLines caps the lines of one reply.
	maxReplyLines = 64
	// maxProtoBytes caps an answer of many lines (redis INFO, haproxy show stat).
	maxProtoBytes = 1 << 20
	// maxBERBytes caps one LDAP message.
	maxBERBytes = 64 << 10
	// byeWait is how long a session waits for the server to answer its goodbye and close.
	byeWait = time.Second
	// bannerWait is how long recognition waits for a server that speaks first.
	bannerWait = 1500 * time.Millisecond
	// answerWait is how long recognition waits for the answer to its request and for a TLS handshake.
	answerWait = 2 * time.Second
)

// protocols are the protocols proto speaks by name, auto aside.
var protocols = map[string]func(*session, protoOpts) (protoResult, error){
	"banner": speakBanner, "smtp": speakSMTP, "imap": speakIMAP, "pop3": speakPOP3, "ldap": speakLDAP,
	"postgres": speakPostgres, "redis": speakRedis, "fastcgi": speakFastCGI, "haproxy": speakHAProxy,
}

// startTLSProtocols are the protocols that can ask for TLS on their connection.
var startTLSProtocols = []string{"smtp", "imap", "pop3", "ldap", "postgres"}

var errLineTooLong = errors.New("line too long")

// protoFail is an answer outside what the protocol expects: the service answered, but not well.
type protoFail struct{ detail string }

func (f protoFail) Error() string { return f.detail }

// protoOpts is how proto speaks a protocol: with STARTTLS, with a credential.
type protoOpts struct {
	starttls    bool
	use, secret string
}

// protoResult is what proto found: whether the service answers well, what it is, whether the
// connection went through TLS, the data it reported and how long it took.
type protoResult struct {
	ok     bool
	detail string
	tlsOK  bool
	data   map[string]any
	took   time.Duration
}

func (r protoResult) values() map[string]any {
	v := map[string]any{"ok": r.ok, "detail": r.detail, "tls_ok": r.tlsOK, "duration_ms": r.took.Milliseconds()}
	if r.data != nil {
		v["data"] = r.data
	}
	return v
}

// session is one connection of a protocol: reads end at the probe's deadline at the latest, and end
// says goodbye in the protocol before it closes.
type session struct {
	ctx     context.Context
	conn    net.Conn
	r       *bufio.Reader
	tc      *tls.Conn
	goodbye []byte
	// idle is the time spent waiting in vain for a server that might speak first.
	idle time.Duration
}

func newSession(ctx context.Context, conn net.Conn) *session {
	return &session{ctx: ctx, conn: conn, r: bufio.NewReaderSize(conn, maxProtoLine)}
}

// within lets the next reads wait at most d, never past the probe's deadline; 0 lets them wait until it.
func (s *session) within(d time.Duration) {
	deadline, _ := s.ctx.Deadline()
	if t := time.Now().Add(d); d > 0 && (deadline.IsZero() || t.Before(deadline)) {
		deadline = t
	}
	_ = s.conn.SetReadDeadline(deadline)
}

// rawLine reads one line without its line end; on an error it returns what came of the line so far.
func (s *session) rawLine() (string, error) {
	b, err := s.r.ReadSlice('\n')
	switch {
	case err == nil:
		return string(bytes.TrimRight(b, "\r\n")), nil
	case errors.Is(err, bufio.ErrBufferFull):
		return string(b), errLineTooLong
	}
	return string(b), err
}

// line reads one line of the answer to what.
func (s *session) line(what string) (string, error) {
	l, err := s.rawLine()
	if err != nil {
		return "", s.fail(err, what)
	}
	return l, nil
}

// waitLine reads a line within d; the time it waits in vain is idle, not the service's.
func (s *session) waitLine(d time.Duration) (string, error) {
	s.within(d)
	start := time.Now()
	l, err := s.rawLine()
	s.within(0)
	if timeout(err) && !ended(s.ctx) {
		s.idle += time.Since(start)
	}
	return l, err
}

// send writes b, the request what.
func (s *session) send(what string, b []byte) error {
	if _, err := s.conn.Write(b); err != nil {
		return s.fail(err, what)
	}
	return nil
}

// fail is the probe's error for err, met at what: the end of the probe if it has ended, else a
// protoFail.
func (s *session) fail(err error, what string) error {
	switch {
	case ended(s.ctx):
		return netErr(s.ctx, err)
	case errors.Is(err, errLineTooLong):
		return protoFail{"the answer to " + what + " is too long"}
	case errors.Is(err, io.EOF), errors.Is(err, io.ErrUnexpectedEOF):
		return protoFail{"closed at " + what}
	case timeout(err):
		return protoFail{"no answer to " + what}
	}
	return protoFail{what + ": " + err.Error()}
}

// startTLS turns s into TLS without checking the server's certificate (the tls sensor reports on it).
// Bytes the server sent ahead of the handshake would pass for bytes inside TLS (the flaw behind
// CVE-2011-0411), so they fail. wait caps the handshake; 0 lets it run until the deadline. A failed
// handshake leaves no goodbye: the server waits for TLS and would read it as garbage.
func (s *session) startTLS(serverName string, wait time.Duration) error {
	goodbye := s.goodbye
	s.goodbye = nil
	if s.r.Buffered() > 0 {
		return protoFail{"data ahead of the TLS handshake"}
	}
	tc := tls.Client(s.conn, &tls.Config{InsecureSkipVerify: true, ServerName: serverName}) //nolint:gosec // the tls sensor checks certificates
	s.within(wait)
	err := tc.HandshakeContext(s.ctx)
	s.within(0)
	if err != nil {
		return s.fail(err, "the TLS handshake")
	}
	s.tc, s.conn, s.r, s.goodbye = tc, tc, bufio.NewReaderSize(tc, maxProtoLine), goodbye
	return nil
}

// end says goodbye in the protocol, gives the server a moment to answer and close, and closes s:
// a server that is left without a goodbye logs an aborted session.
func (s *session) end() {
	if s.goodbye != nil && !ended(s.ctx) {
		if _, err := s.conn.Write(s.goodbye); err == nil {
			s.within(byeWait)
			for {
				if _, err := s.rawLine(); err != nil {
					break
				}
			}
		}
	}
	_ = s.conn.Close()
}

// timeout says whether err is a deadline met on the network.
func timeout(err error) bool {
	var ne net.Error
	return errors.As(err, &ne) && ne.Timeout()
}

// protoSensor speaks a protocol with its target through the guard: whether the service answers
// well (ok), what answered (detail), whether TLS was on and how long it took. auto recognizes the
// protocol first.
func protoSensor(ctx context.Context, p Probe, secret string) (map[string]any, error) {
	t, err := targetOf(p, httpTargets...)
	if err != nil {
		return nil, err
	}
	if err := knownParams(p, "protocol", "starttls", "status_path"); err != nil {
		return nil, err
	}
	protocol, err := choiceParam(p, "protocol", "", "auto", "banner", "smtp", "imap", "pop3", "ldap",
		"postgres", "redis", "fastcgi", "haproxy")
	if err != nil {
		return nil, err
	}
	starttls, err := boolParam(p, "starttls")
	if err != nil {
		return nil, err
	}
	if starttls && !slices.Contains(startTLSProtocols, protocol) {
		return nil, fmt.Errorf("%w: protocol %s has no STARTTLS", ErrInvalid, protocol)
	}
	if err := statusPath(p, protocol); err != nil {
		return nil, err
	}
	var uses []string
	if protocol == "redis" {
		uses = []string{useRedisAuth}
	}
	use, err := credentialUse(p, uses...)
	if err != nil {
		return nil, err
	}
	ep, err := resolve(ctx, t)
	if err != nil {
		return nil, err
	}
	dial := func(ctx context.Context) (net.Conn, error) { return dialTarget(ctx, ep) }
	var res protoResult
	if protocol == "auto" {
		res, err = recognize(ctx, dial)
	} else {
		res, err = speak(ctx, dial, protocol, protoOpts{starttls: starttls, use: use, secret: secret})
	}
	if err != nil {
		return nil, err
	}
	return res.values(), nil
}

// statusPath checks the param status_path of p, for the status page of a FastCGI application: not
// yet supported, and no param of any other protocol.
func statusPath(p Probe, protocol string) error {
	path, err := requestPath(p, "status_path", "", 256, true)
	switch {
	case err != nil || path == "":
		return err
	case protocol == "fastcgi":
		return fmt.Errorf("%w: the status page of a FastCGI application is not supported yet", ErrUnsupported)
	}
	return fmt.Errorf("%w: protocol %s takes no status_path", ErrInvalid, protocol)
}

// speak connects with dial and speaks protocol.
func speak(ctx context.Context, dial func(context.Context) (net.Conn, error), protocol string, o protoOpts) (protoResult, error) {
	start := time.Now()
	conn, err := dial(ctx)
	if err != nil {
		return protoResult{}, err
	}
	s := newSession(ctx, conn)
	defer s.end()
	res, err := runProto(s, protocol, o)
	res.took = time.Since(start)
	return res, err
}

// runProto speaks protocol name on s. An answer outside the protocol is a result that is not ok.
func runProto(s *session, name string, o protoOpts) (protoResult, error) {
	res, err := protocols[name](s, o)
	var pf protoFail
	switch {
	case errors.As(err, &pf):
		res = protoResult{detail: name + ": " + pf.detail}
	case err != nil:
		return protoResult{}, err
	default:
		res.ok = true
		if res.detail == "" {
			res.detail = name
		}
	}
	res.tlsOK = s.tc != nil
	return res, nil
}

// askTLS greets the server in protocol and asks it for TLS: the handshake comes next.
func askTLS(s *session, protocol string) error {
	switch protocol {
	case "smtp":
		if err := smtpGreet(s); err != nil {
			return err
		}
		if _, err := smtpEHLO(s, true); err != nil {
			return err
		}
		if err := s.send("STARTTLS", []byte("STARTTLS\r\n")); err != nil {
			return err
		}
		_, err := smtpReply(s, "STARTTLS", "220")
		return err
	case "imap":
		preauth, err := imapGreet(s)
		if err != nil {
			return err
		}
		if preauth {
			// RFC 9051 §6.2.1: STARTTLS only before authentication.
			return protoFail{"preauthenticated, no STARTTLS"}
		}
		return imapStartTLS(s)
	case "pop3":
		if err := pop3Greet(s); err != nil {
			return err
		}
		if err := s.send("STLS", []byte("STLS\r\n")); err != nil {
			return err
		}
		l, err := s.line("STLS")
		if err != nil {
			return err
		}
		if !strings.HasPrefix(l, "+OK") {
			return protoFail{"STLS refused"}
		}
		return nil
	case "ldap":
		s.goodbye = ldapUnbind(3)
		if err := s.send("StartTLS", ldapExtended(1, oidStartTLS)); err != nil {
			return err
		}
		code, err := ldapResult(s, "StartTLS")
		if err != nil {
			return err
		}
		if code != 0 {
			return protoFail{fmt.Sprintf("StartTLS refused (result %d)", code)}
		}
		return nil
	case "postgres":
		agreed, err := pgAskTLS(s)
		if err != nil {
			return err
		}
		if !agreed {
			return protoFail{"no TLS"}
		}
		return nil
	}
	return fmt.Errorf("%w: protocol %s has no STARTTLS", ErrInvalid, protocol)
}

// speakTLS asks for TLS in protocol and shakes hands.
func speakTLS(s *session, protocol string) error {
	if err := askTLS(s, protocol); err != nil {
		return err
	}
	return s.startTLS("", 0)
}

// replyLine says whether l is a line of a reply of SMTP, FTP or the like: three digits, then a space,
// a hyphen (more lines follow) or the end.
func replyLine(l string) bool {
	if len(l) < 3 || (len(l) > 3 && l[3] != ' ' && l[3] != '-') {
		return false
	}
	for _, c := range []byte(l[:3]) {
		if c < '0' || c > '9' {
			return false
		}
	}
	return true
}

// smtpReply reads a reply of SMTP (RFC 5321 §4.2) to what, the texts of its lines; a code other than
// code fails.
func smtpReply(s *session, what, code string) ([]string, error) {
	var texts []string
	for range maxReplyLines {
		l, err := s.line(what)
		if err != nil {
			return nil, err
		}
		if !replyLine(l) {
			return nil, protoFail{"no reply to " + what}
		}
		texts = append(texts, l[min(4, len(l)):])
		if len(l) == 3 || l[3] == ' ' {
			if l[:3] != code {
				return nil, protoFail{what + " answered " + l[:3]}
			}
			return texts, nil
		}
	}
	return nil, protoFail{"the reply to " + what + " is too long"}
}

func smtpGreet(s *session) error {
	s.goodbye = []byte("QUIT\r\n")
	_, err := smtpReply(s, "the greeting", "220")
	return err
}

// smtpEHLO says EHLO; wantTLS fails unless the server offers STARTTLS (RFC 3207).
func smtpEHLO(s *session, wantTLS bool) ([]string, error) {
	if err := s.send("EHLO", []byte("EHLO "+ehloName(s.conn)+"\r\n")); err != nil {
		return nil, err
	}
	texts, err := smtpReply(s, "EHLO", "250")
	if err != nil || !wantTLS {
		return texts, err
	}
	for _, t := range texts[1:] {
		if f := strings.Fields(t); len(f) > 0 && strings.EqualFold(f[0], "STARTTLS") {
			return texts, nil
		}
	}
	return nil, protoFail{"no STARTTLS"}
}

// ehloName is the address literal of this end of c (RFC 5321 §4.1.3), the name EHLO gives.
func ehloName(c net.Conn) string {
	if a, ok := c.LocalAddr().(*net.TCPAddr); ok {
		switch ip := a.AddrPort().Addr().Unmap(); {
		case ip.Is4():
			return "[" + ip.String() + "]"
		case ip.Is6():
			return "[IPv6:" + ip.WithZone("").String() + "]"
		}
	}
	return "[127.0.0.1]"
}

func speakSMTP(s *session, o protoOpts) (protoResult, error) {
	if !o.starttls {
		return protoResult{}, smtpGreet(s)
	}
	if err := speakTLS(s, "smtp"); err != nil {
		return protoResult{}, err
	}
	_, err := smtpEHLO(s, false)
	return protoResult{}, err
}

// imapGreet reads the greeting of IMAP (RFC 9051 §7.1); preauth says the session is authenticated
// already.
func imapGreet(s *session) (preauth bool, err error) {
	l, err := s.line("the greeting")
	if err != nil {
		return false, err
	}
	switch {
	case hasPrefixFold(l, "* OK"), hasPrefixFold(l, "* PREAUTH"):
		s.goodbye = []byte("a2 LOGOUT\r\n")
		return hasPrefixFold(l, "* PREAUTH"), nil
	case hasPrefixFold(l, "* BYE"):
		return false, protoFail{"refused"}
	}
	return false, protoFail{"no greeting"}
}

func imapStartTLS(s *session) error {
	if err := s.send("STARTTLS", []byte("a1 STARTTLS\r\n")); err != nil {
		return err
	}
	for range maxReplyLines {
		l, err := s.line("STARTTLS")
		if err != nil {
			return err
		}
		if hasPrefixFold(l, "a1 ") {
			if hasPrefixFold(l, "a1 OK") {
				return nil
			}
			return protoFail{"STARTTLS refused"}
		}
	}
	return protoFail{"the reply to STARTTLS is too long"}
}

func speakIMAP(s *session, o protoOpts) (protoResult, error) {
	if !o.starttls {
		_, err := imapGreet(s)
		return protoResult{}, err
	}
	return protoResult{}, speakTLS(s, "imap")
}

// pop3Greet reads the greeting of POP3 (RFC 1939 §4).
func pop3Greet(s *session) error {
	l, err := s.line("the greeting")
	if err != nil {
		return err
	}
	switch {
	case strings.HasPrefix(l, "+OK"):
		s.goodbye = []byte("QUIT\r\n")
		return nil
	case strings.HasPrefix(l, "-ERR"):
		return protoFail{"refused"}
	}
	return protoFail{"no greeting"}
}

func speakPOP3(s *session, o protoOpts) (protoResult, error) {
	if !o.starttls {
		return protoResult{}, pop3Greet(s)
	}
	return protoResult{}, speakTLS(s, "pop3")
}

// The extended operations of LDAP that proto asks for.
const (
	oidWhoAmI   = "1.3.6.1.4.1.4203.1.11.3" // RFC 4532
	oidStartTLS = "1.3.6.1.4.1.1466.20037"  // RFC 4511 §4.14.1
)

// ldapExtended is an ExtendedRequest of LDAP (RFC 4511 §4.12) for oid, message id, in BER.
func ldapExtended(id byte, oid string) []byte {
	b := []byte{0x30, byte(7 + len(oid)), 0x02, 0x01, id, 0x77, byte(2 + len(oid)), 0x80, byte(len(oid))}
	return append(b, oid...)
}

// ldapUnbind is an UnbindRequest of LDAP (RFC 4511 §4.3), message id, in BER.
func ldapUnbind(id byte) []byte {
	return []byte{0x30, 0x05, 0x02, 0x01, id, 0x42, 0x00}
}

// ldapResult reads the ExtendedResponse to what and returns its resultCode.
func ldapResult(s *session, what string) (int, error) {
	msg, err := berMessage(s, what)
	if err != nil {
		return 0, err
	}
	noAnswer := protoFail{"no LDAP answer to " + what}
	tag, id, rest, ok := berNext(msg)
	if !ok || tag != 0x02 || len(id) == 0 || len(id) > 4 {
		return 0, noAnswer
	}
	if berInt(id) == 0 {
		// Message id 0 is a notice of disconnection (RFC 4511 §4.4.1).
		return 0, protoFail{"the server ended the session"}
	}
	tag, op, _, ok := berNext(rest)
	if !ok || tag != 0x78 {
		return 0, noAnswer
	}
	tag, code, _, ok := berNext(op)
	if !ok || tag != 0x0a || len(code) == 0 || len(code) > 4 {
		return 0, noAnswer
	}
	return berInt(code), nil
}

// berMessage reads one LDAPMessage, a SEQUENCE of definite length, and returns its content.
func berMessage(s *session, what string) ([]byte, error) {
	noMessage := protoFail{"no LDAP answer to " + what}
	head := make([]byte, 0, 5)
	for len(head) < 2 || (head[1]&0x80 != 0 && len(head) < 2+int(head[1]&0x7f)) {
		b, err := s.r.ReadByte()
		if err != nil {
			return nil, s.fail(err, what)
		}
		head = append(head, b)
		if head[0] != 0x30 || (len(head) == 2 && (head[1] == 0x80 || head[1] > 0x83)) {
			return nil, noMessage
		}
	}
	_, n, ok := berLength(head[1:])
	if !ok {
		return nil, noMessage
	}
	if n > maxBERBytes {
		return nil, protoFail{"the answer to " + what + " is too long"}
	}
	msg := make([]byte, n)
	if _, err := io.ReadFull(s.r, msg); err != nil {
		return nil, s.fail(err, what)
	}
	return msg, nil
}

// berLength reads a definite length of at most three bytes from b: the bytes it took and the length.
func berLength(b []byte) (used, n int, ok bool) {
	if len(b) == 0 {
		return 0, 0, false
	}
	if b[0]&0x80 == 0 {
		return 1, int(b[0]), true
	}
	k := int(b[0] & 0x7f)
	if k == 0 || k > 3 || len(b) < 1+k {
		return 0, 0, false
	}
	for _, c := range b[1 : 1+k] {
		n = n<<8 | int(c)
	}
	return 1 + k, n, true
}

// berNext splits the first element off b: its tag, its content and the rest. ok is false unless b
// starts with a whole element of a one-byte tag and a definite length.
func berNext(b []byte) (tag byte, content, rest []byte, ok bool) {
	if len(b) < 2 || b[0]&0x1f == 0x1f {
		return 0, nil, nil, false
	}
	used, n, ok := berLength(b[1:])
	if !ok || len(b)-1-used < n {
		return 0, nil, nil, false
	}
	start := 1 + used
	return b[0], b[start : start+n], b[start+n:], true
}

// berInt is the unsigned value of the big-endian bytes b, at most four.
func berInt(b []byte) int {
	n := 0
	for _, c := range b {
		n = n<<8 | int(c)
	}
	return n
}

// speakLDAP asks who the anonymous session is (WhoAmI, RFC 4532): every answer but busy and
// unavailable says the directory serves; another result code than success shows in the detail.
func speakLDAP(s *session, o protoOpts) (protoResult, error) {
	s.goodbye = ldapUnbind(3)
	id := byte(1)
	if o.starttls {
		if err := speakTLS(s, "ldap"); err != nil {
			return protoResult{}, err
		}
		id = 2
	}
	if err := s.send("WhoAmI", ldapExtended(id, oidWhoAmI)); err != nil {
		return protoResult{}, err
	}
	code, err := ldapResult(s, "WhoAmI")
	switch {
	case err != nil:
		return protoResult{}, err
	case code == 51:
		return protoResult{}, protoFail{"busy"}
	case code == 52:
		return protoResult{}, protoFail{"unavailable"}
	case code != 0:
		return protoResult{detail: fmt.Sprintf("ldap: result %d", code)}, nil
	}
	return protoResult{}, nil
}

// sslRequest asks a PostgreSQL server for TLS (protocol 3, SSLRequest).
var sslRequest = []byte{0, 0, 0, 8, 0x04, 0xd2, 0x16, 0x2f}

// pgAskTLS sends the SSLRequest: agreed says whether the server answered S, else it declined (N).
func pgAskTLS(s *session) (agreed bool, err error) {
	if err := s.send("SSLRequest", sslRequest); err != nil {
		return false, err
	}
	b, err := s.r.ReadByte()
	if err != nil {
		return false, s.fail(err, "SSLRequest")
	}
	switch b {
	case 'S':
		return true, nil
	case 'N':
		return false, nil
	case 'E':
		return false, protoFail{"refused"}
	}
	return false, protoFail{"no answer to SSLRequest"}
}

// speakPostgres sends the SSLRequest and nothing a server would log: after S the handshake and
// close_notify, after N the close; an aborted handshake or a half startup message would be logged.
func speakPostgres(s *session, o protoOpts) (protoResult, error) {
	agreed, err := pgAskTLS(s)
	switch {
	case err != nil:
		return protoResult{}, err
	case agreed:
		return protoResult{}, s.startTLS("", 0)
	case o.starttls:
		return protoResult{}, protoFail{"no TLS"}
	}
	return protoResult{}, nil
}

// redisCommand is args as a command of RESP: an array of bulk strings.
func redisCommand(args ...string) []byte {
	b := fmt.Appendf(nil, "*%d\r\n", len(args))
	for _, a := range args {
		b = fmt.Appendf(b, "$%d\r\n%s\r\n", len(a), a)
	}
	return b
}

// redisErr is the code of an error reply of RESP ("-NOAUTH …"), its first word.
func redisErr(l string) string {
	if f := strings.Fields(l[1:]); len(f) > 0 {
		return printable(f[0], 32)
	}
	return "an error"
}

// speakRedis reads INFO, after AUTH if the probe has a credential.
func speakRedis(s *session, o protoOpts) (protoResult, error) {
	if o.use == useRedisAuth {
		if err := s.send("AUTH", redisCommand("AUTH", o.secret)); err != nil {
			return protoResult{}, err
		}
		l, err := s.line("AUTH")
		switch {
		case err != nil:
			return protoResult{}, err
		case strings.HasPrefix(l, "-"):
			return protoResult{}, fmt.Errorf("%w: AUTH answered %s", ErrDenied, redisErr(l))
		case l != "+OK":
			return protoResult{}, protoFail{"no answer to AUTH"}
		}
	}
	if err := s.send("INFO", redisCommand("INFO")); err != nil {
		return protoResult{}, err
	}
	l, err := s.line("INFO")
	if err != nil {
		return protoResult{}, err
	}
	if strings.HasPrefix(l, "-") {
		switch code := redisErr(l); code {
		case "NOAUTH", "WRONGPASS", "NOPERM":
			return protoResult{}, fmt.Errorf("%w: INFO answered %s", ErrDenied, code)
		case "LOADING":
			return protoResult{}, protoFail{"loading"}
		default:
			return protoResult{}, protoFail{"INFO answered " + code}
		}
	}
	n, err := strconv.Atoi(strings.TrimPrefix(l, "$"))
	if !strings.HasPrefix(l, "$") || err != nil || n < 0 || n > maxProtoBytes {
		return protoResult{}, protoFail{"no answer to INFO"}
	}
	body := make([]byte, n+2)
	if _, err := io.ReadFull(s.r, body); err != nil {
		return protoResult{}, s.fail(err, "INFO")
	}
	return protoResult{data: redisInfo(body[:n])}, nil
}

// redisInfo reads the lines key:value of INFO; sections (# …) drop, a number stays json.Number.
func redisInfo(b []byte) map[string]any {
	data := map[string]any{}
	for line := range strings.Lines(string(b)) {
		k, v, ok := strings.Cut(strings.TrimRight(line, "\r\n"), ":")
		if ok && k != "" && !strings.HasPrefix(k, "#") {
			data[k] = numberOrText(v)
		}
	}
	return data
}

// numberOrText is v as json.Number if it is a number, else v.
func numberOrText(v string) any {
	if jsonNumber.MatchString(v) {
		return json.Number(v)
	}
	return v
}

// fcgiGetValues is a record FCGI_GET_VALUES (FastCGI 1.0 §4.1) for the three values every FastCGI
// application knows.
var fcgiGetValues = func() []byte {
	var body []byte
	for _, name := range []string{"FCGI_MAX_CONNS", "FCGI_MAX_REQS", "FCGI_MPXS_CONNS"} {
		body = append(append(body, byte(len(name)), 0), name...)
	}
	return append([]byte{1, 9, 0, 0, 0, byte(len(body)), 0, 0}, body...)
}()

// speakFastCGI asks for the values of the application: FCGI_GET_VALUES_RESULT reports them, an
// FCGI_UNKNOWN_TYPE says the application is there but does not tell.
func speakFastCGI(s *session, _ protoOpts) (protoResult, error) {
	if err := s.send("FCGI_GET_VALUES", fcgiGetValues); err != nil {
		return protoResult{}, err
	}
	var head [8]byte
	if _, err := io.ReadFull(s.r, head[:]); err != nil {
		return protoResult{}, s.fail(err, "FCGI_GET_VALUES")
	}
	n := int(binary.BigEndian.Uint16(head[4:6]))
	body := make([]byte, n+int(head[6]))
	if head[0] == 1 {
		if _, err := io.ReadFull(s.r, body); err != nil {
			return protoResult{}, s.fail(err, "FCGI_GET_VALUES")
		}
	}
	switch {
	case head[0] != 1:
	case head[1] == 10:
		return protoResult{data: fcgiPairs(body[:n])}, nil
	case head[1] == 11:
		return protoResult{}, nil
	}
	return protoResult{}, protoFail{"no answer to FCGI_GET_VALUES"}
}

// fcgiPairs reads name-value pairs (FastCGI 1.0 §3.4); a number stays json.Number.
func fcgiPairs(b []byte) map[string]any {
	data := map[string]any{}
	for len(b) > 0 {
		nameLen, rest, ok := fcgiLength(b)
		if !ok {
			break
		}
		valueLen, rest, ok := fcgiLength(rest)
		if !ok || len(rest) < nameLen+valueLen {
			break
		}
		data[string(rest[:nameLen])] = numberOrText(string(rest[nameLen : nameLen+valueLen]))
		b = rest[nameLen+valueLen:]
	}
	return data
}

// fcgiLength reads the length of a name or value: one byte below 128, else four with the top bit set.
func fcgiLength(b []byte) (int, []byte, bool) {
	switch {
	case len(b) > 0 && b[0] < 0x80:
		return int(b[0]), b[1:], true
	case len(b) >= 4:
		return int(binary.BigEndian.Uint32(b[:4]) & 0x7fffffff), b[4:], true
	}
	return 0, nil, false
}

// speakHAProxy reads show stat from the stats socket: data[proxy][server][field].
func speakHAProxy(s *session, _ protoOpts) (protoResult, error) {
	if err := s.send("show stat", []byte("show stat\n")); err != nil {
		return protoResult{}, err
	}
	b, err := io.ReadAll(io.LimitReader(s.r, maxProtoBytes+1))
	switch {
	case err != nil:
		return protoResult{}, s.fail(err, "show stat")
	case len(b) > maxProtoBytes:
		return protoResult{}, protoFail{"the answer to show stat is too long"}
	}
	data, ok := haproxyStat(b)
	if !ok {
		return protoResult{}, protoFail{"no answer to show stat"}
	}
	return protoResult{data: data}, nil
}

// haproxyStat reads the CSV of show stat, its header after "# ": empty values drop, a number stays
// json.Number.
func haproxyStat(b []byte) (map[string]any, bool) {
	rest, ok := bytes.CutPrefix(b, []byte("# "))
	if !ok {
		return nil, false
	}
	r := csv.NewReader(bytes.NewReader(rest))
	r.FieldsPerRecord = -1
	r.LazyQuotes = true
	header, err := r.Read()
	if err != nil || len(header) < 2 {
		return nil, false
	}
	data := map[string]any{}
	for {
		rec, err := r.Read()
		if errors.Is(err, io.EOF) {
			return data, true
		}
		if err != nil {
			return nil, false
		}
		if len(rec) < 2 {
			continue
		}
		proxy, _ := data[rec[0]].(map[string]any)
		if proxy == nil {
			proxy = map[string]any{}
			data[rec[0]] = proxy
		}
		server := map[string]any{}
		for i, name := range header[2:min(len(header), len(rec))] {
			if name != "" && rec[i+2] != "" {
				server[name] = numberOrText(rec[i+2])
			}
		}
		proxy[rec[1]] = server
	}
}

// speakBanner reads the first line the server says: its printable part is the detail.
func speakBanner(s *session, _ protoOpts) (protoResult, error) {
	l, err := s.line("the banner")
	if err != nil {
		return protoResult{}, err
	}
	return protoResult{detail: printable(l, 128)}, nil
}

// printable is s without the bytes outside printable ASCII, cut to n bytes.
func printable(s string, n int) string {
	b := make([]byte, 0, min(len(s), n))
	for i := 0; i < len(s) && len(b) < n; i++ {
		if c := s[i]; c >= 0x20 && c < 0x7f {
			b = append(b, c)
		}
	}
	return string(b)
}

// text says whether s is printable ASCII and tabs only.
func text(s string) bool {
	for i := range len(s) {
		if c := s[i]; (c < 0x20 && c != '\t') || c >= 0x7f {
			return false
		}
	}
	return true
}

func hasPrefixFold(s, prefix string) bool {
	return len(s) >= len(prefix) && strings.EqualFold(s[:len(prefix)], prefix)
}

// recognize finds out what listens behind dial and whether it answers well: first what the server
// says unasked (SMTP, FTP, IMAP, POP3, SSH, a banner), then its answer to HEAD / HTTP/1.0 (HTTP,
// Redis), and if neither tells, the same once more inside TLS.
func recognize(ctx context.Context, dial func(context.Context) (net.Conn, error)) (protoResult, error) {
	res, again, err := recognizeOnce(ctx, dial, false)
	if err != nil || !again {
		return res, err
	}
	tlsRes, _, err := recognizeOnce(ctx, dial, true)
	switch {
	case err == nil:
		return tlsRes, nil
	case ended(ctx) || errors.Is(err, ErrNotAllowed):
		return protoResult{}, netErr(ctx, err)
	}
	return res, nil
}

// recognizeOnce connects with dial, inside TLS if inTLS, and recognizes the service; again says that
// TLS may tell more. The time a server stays silent is not the service's.
func recognizeOnce(ctx context.Context, dial func(context.Context) (net.Conn, error), inTLS bool) (protoResult, bool, error) {
	start := time.Now()
	conn, err := dial(ctx)
	if err != nil {
		return protoResult{}, false, err
	}
	s := newSession(ctx, conn)
	defer s.end()
	if inTLS {
		if err := s.startTLS("", answerWait); err != nil {
			return protoResult{}, false, err
		}
	}
	name, res, again, err := recognizeOn(s)
	if err != nil {
		return protoResult{}, false, err
	}
	res.took = time.Since(start) - s.idle
	if inTLS {
		res.detail = tlsName(name) + strings.TrimPrefix(res.detail, name)
		res.tlsOK = true
	}
	return res, again, nil
}

// tlsName is the name of protocol name inside TLS.
func tlsName(name string) string {
	switch name {
	case "smtp", "imap", "pop3", "ftp":
		return name + "s"
	case "http":
		return "https"
	case "unknown":
		return "tls"
	}
	return name + "+tls"
}

// recognizeOn recognizes the service on s: its name, the result and whether TLS may tell more.
func recognizeOn(s *session) (string, protoResult, bool, error) {
	l, err := s.waitLine(bannerWait)
	switch {
	case err != nil && ended(s.ctx):
		return "", protoResult{}, false, netErr(s.ctx, err)
	case err == nil:
		name, res := recognizeBanner(s, l)
		return name, res, false, nil
	case errors.Is(err, errLineTooLong) || l != "":
		return "banner", protoResult{ok: true, detail: "banner"}, false, nil
	case !timeout(err):
		// A server that takes the connection and closes it without a word is up (frps closes what
		// is not its protocol, or a TLS connection without its SNI); TLS may tell more.
		return "unknown", protoResult{ok: true, detail: "unknown"}, true, nil
	}
	// Silence: the client speaks first. HEAD goes without Host: Redis drops a connection that sends
	// Host: or POST as an attack, and it is to answer with an error.
	if err := s.send("HEAD", []byte("HEAD / HTTP/1.0\r\n\r\n")); err != nil {
		return "", protoResult{}, false, err
	}
	l, err = s.waitLine(answerWait)
	switch {
	case err != nil && ended(s.ctx):
		return "", protoResult{}, false, netErr(s.ctx, err)
	case err == nil && strings.HasPrefix(l, "HTTP/1."):
		code := 0
		if f := strings.Fields(l); len(f) > 1 && len(f[1]) == 3 {
			code, _ = strconv.Atoi(f[1])
		}
		if code < 100 || code >= 500 {
			return "http", protoResult{detail: fmt.Sprintf("http: status %d", code)}, false, nil
		}
		// 400 is what a server of HTTPS answers to plain HTTP (nginx and others).
		return "http", protoResult{ok: true, detail: "http"}, code == 400, nil
	case err == nil && (strings.HasPrefix(l, "-ERR") || strings.HasPrefix(l, "-NOAUTH") || strings.HasPrefix(l, "-DENIED")):
		return "redis", protoResult{ok: true, detail: "redis"}, false, nil
	case (err == nil || errors.Is(err, errLineTooLong)) && text(l):
		return "unknown", protoResult{ok: true, detail: "unknown"}, false, nil
	}
	return "unknown", protoResult{ok: true, detail: "unknown"}, true, nil
}

// recognizeBanner recognizes the service by the first line it said unasked.
func recognizeBanner(s *session, l string) (string, protoResult) {
	switch {
	case replyLine(l):
		name := "banner"
		if upper := strings.ToUpper(l); strings.Contains(upper, "SMTP") {
			name = "smtp"
		} else if strings.Contains(upper, "FTP") {
			name = "ftp"
		}
		s.goodbye = []byte("QUIT\r\n")
		if l[0] == '4' || l[0] == '5' {
			return name, protoResult{detail: name + ": greeting " + l[:3]}
		}
		return name, protoResult{ok: true, detail: name}
	case hasPrefixFold(l, "* OK"), hasPrefixFold(l, "* PREAUTH"):
		s.goodbye = []byte("a1 LOGOUT\r\n")
		return "imap", protoResult{ok: true, detail: "imap"}
	case hasPrefixFold(l, "* BYE"):
		return "imap", protoResult{detail: "imap: refused"}
	case strings.HasPrefix(l, "+OK"):
		s.goodbye = []byte("QUIT\r\n")
		return "pop3", protoResult{ok: true, detail: "pop3"}
	case strings.HasPrefix(l, "-ERR"):
		return "pop3", protoResult{detail: "pop3: refused"}
	case strings.HasPrefix(l, "SSH-"):
		return "ssh", protoResult{ok: true, detail: "ssh"}
	}
	return "banner", protoResult{ok: true, detail: "banner"}
}
