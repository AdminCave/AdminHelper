// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package probe

import (
	"bufio"
	"context"
	"crypto/tls"
	"encoding/binary"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log"
	"net"
	"net/http"
	"net/http/httptest"
	"reflect"
	"slices"
	"strings"
	"sync"
	"testing"
	"time"
)

// fake is a server on 127.0.0.1 that runs serve on every connection and records what it heard.
type fake struct {
	ln    net.Listener
	wg    sync.WaitGroup
	once  sync.Once
	mu    sync.Mutex
	heard []string
}

// fakeConn is one connection of a fake.
type fakeConn struct {
	f    *fake
	conn net.Conn
	r    *bufio.Reader
}

// fakeServer serves on 127.0.0.1 and lets the guard's seams see the test's own listeners alone.
func fakeServer(t *testing.T, serve func(*fakeConn)) *fake {
	t.Helper()
	stubHost(t, &fakeHost{live: true})
	return listen(t, serve)
}

// listen serves on 127.0.0.1 without touching the guard's seams, for tests that run in parallel.
func listen(t *testing.T, serve func(*fakeConn)) *fake {
	t.Helper()
	ln, err := net.Listen("tcp4", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	return serveOn(t, ln, serve)
}

// serveOn runs serve on every connection ln accepts until the test ends.
func serveOn(t *testing.T, ln net.Listener, serve func(*fakeConn)) *fake {
	t.Helper()
	f := &fake{ln: ln}
	f.wg.Add(1)
	go func() {
		defer f.wg.Done()
		for {
			conn, err := ln.Accept()
			if err != nil {
				return
			}
			_ = conn.SetDeadline(time.Now().Add(10 * time.Second))
			f.wg.Add(1)
			go func() {
				defer f.wg.Done()
				c := &fakeConn{f: f, conn: conn, r: bufio.NewReader(conn)}
				defer func() { _ = c.conn.Close() }()
				serve(c)
			}()
		}
	}()
	t.Cleanup(func() { f.close() })
	return f
}

func (f *fake) port() int { return f.ln.Addr().(*net.TCPAddr).Port }

// close stops f, waits until its connections have ended and returns what it heard.
func (f *fake) close() []string {
	f.once.Do(func() { _ = f.ln.Close() })
	f.wg.Wait()
	f.mu.Lock()
	defer f.mu.Unlock()
	return slices.Clone(f.heard)
}

func (f *fake) record(s string) {
	f.mu.Lock()
	f.heard = append(f.heard, s)
	f.mu.Unlock()
}

func (c *fakeConn) say(s string) { _, _ = io.WriteString(c.conn, s) }

// hear reads a line without its line end; "" once the client has closed.
func (c *fakeConn) hear() string {
	l, err := c.r.ReadString('\n')
	if err != nil {
		return ""
	}
	l = strings.TrimRight(l, "\r\n")
	c.f.record(l)
	return l
}

// read reads n bytes, recorded in hex; nil once the client has closed.
func (c *fakeConn) read(n int) []byte {
	b := make([]byte, n)
	if _, err := io.ReadFull(c.r, b); err != nil {
		return nil
	}
	c.f.record(fmt.Sprintf("% x", b))
	return b
}

// drain reads until the client closes and records nothing.
func (c *fakeConn) drain() { _, _ = io.Copy(io.Discard, c.r) }

// upgrade shakes hands as a server of TLS with cert.
func (c *fakeConn) upgrade(cert tls.Certificate) bool {
	tc := tls.Server(c.conn, &tls.Config{Certificates: []tls.Certificate{cert}})
	if err := tc.Handshake(); err != nil {
		return false
	}
	c.conn, c.r = tc, bufio.NewReader(tc)
	return true
}

// says is ok, detail and tls_ok of values of proto.
func says(v map[string]any) string { return fmt.Sprintf("%v %v %v", v["ok"], v["detail"], v["tls_ok"]) }

// protoCase is a run of the proto sensor against a fake server.
type protoCase struct {
	name   string
	params map[string]any
	serve  func(*fakeConn)
	// want is ok, detail and tls_ok; heard what the server heard, data the data if any.
	want, heard string
	data        map[string]any
}

func runProtoCases(t *testing.T, cases []protoCase) {
	t.Helper()
	for _, c := range cases {
		srv := fakeServer(t, c.serve)
		got, err := protoSensor(context.Background(), onLoopback("proto", srv.port(), c.params), "")
		heard := fmt.Sprint(srv.close())
		if err != nil {
			t.Errorf("%s: %v", c.name, err)
			continue
		}
		if s := says(got); s != c.want {
			t.Errorf("%s = %s, want %s", c.name, s, c.want)
		}
		if heard != c.heard {
			t.Errorf("%s: the server heard %s, want %s", c.name, heard, c.heard)
		}
		if data, ok := got["data"]; c.data == nil && ok || c.data != nil && !reflect.DeepEqual(data, c.data) {
			t.Errorf("%s: data = %#v, want %#v", c.name, data, c.data)
		}
		if took, ok := got["duration_ms"].(int64); !ok || took < 0 {
			t.Errorf("%s: duration_ms = %#v, want milliseconds", c.name, got["duration_ms"])
		}
	}
}

const ehlo = "EHLO [127.0.0.1]"

func TestProtoSensorSpeaksSMTP(t *testing.T) {
	pki := newPKI(t)
	starttls := map[string]any{"protocol": "smtp", "starttls": true}
	smtp := map[string]any{"protocol": "smtp"}
	greets := func(greeting string) func(*fakeConn) {
		return func(c *fakeConn) {
			c.say(greeting)
			if c.hear() == "QUIT" {
				c.say("221 bye\r\n")
			}
		}
	}
	// offersTLS greets, answers EHLO with STARTTLS and STARTTLS with answer, then runs then.
	offersTLS := func(answer string, then func(*fakeConn)) func(*fakeConn) {
		return func(c *fakeConn) {
			c.say("220 mail.example.org ESMTP\r\n")
			if c.hear() != ehlo {
				return
			}
			c.say("250-mail.example.org\r\n250-PIPELINING\r\n250 STARTTLS\r\n")
			if c.hear() != "STARTTLS" {
				return
			}
			c.say(answer)
			then(c)
		}
	}
	runProtoCases(t, []protoCase{
		{name: "a greeting", params: smtp, serve: greets("220 mail.example.org ESMTP\r\n"), want: "true smtp false", heard: "[QUIT]"},
		{
			name: "a greeting of several lines", params: smtp,
			serve: greets("220-mail.example.org ESMTP\r\n220-no UCE\r\n220 ready\r\n"), want: "true smtp false", heard: "[QUIT]",
		},
		{
			name: "a refusing greeting", params: smtp, serve: greets("554 5.3.2 not now\r\n"),
			want: "false smtp: the greeting answered 554 false", heard: "[QUIT]",
		},
		{
			name: "a greeting outside SMTP", params: smtp, serve: greets("hello\r\n"),
			want: "false smtp: no reply to the greeting false", heard: "[QUIT]",
		},
		{
			name: "a line too long", params: smtp, serve: greets(strings.Repeat("2", 5000) + "\r\n"),
			want: "false smtp: the answer to the greeting is too long false", heard: "[QUIT]",
		},
		{name: "a server that closes", params: smtp, serve: func(*fakeConn) {}, want: "false smtp: closed at the greeting false", heard: "[]"},
		{
			name: "STARTTLS", params: starttls,
			serve: offersTLS("220 go ahead\r\n", func(c *fakeConn) {
				if !c.upgrade(pki.chain) || c.hear() != ehlo {
					return
				}
				c.say("250 mail.example.org\r\n")
				if c.hear() == "QUIT" {
					c.say("221 bye\r\n")
				}
			}),
			want: "true smtp true", heard: "[" + ehlo + " STARTTLS " + ehlo + " QUIT]",
		},
		{
			name: "STARTTLS refused", params: starttls, serve: offersTLS("454 4.7.0 TLS not available\r\n", func(c *fakeConn) { c.hear() }),
			want: "false smtp: STARTTLS answered 454 false", heard: "[" + ehlo + " STARTTLS QUIT]",
		},
		{
			// Bytes ahead of the handshake would pass for bytes inside TLS; the server waits for TLS, so
			// no QUIT follows.
			name: "data ahead of the TLS handshake", params: starttls,
			serve: offersTLS("220 go ahead\r\n250 injected\r\n", func(c *fakeConn) { c.hear() }),
			want:  "false smtp: data ahead of the TLS handshake false", heard: "[" + ehlo + " STARTTLS]",
		},
		{
			name: "no STARTTLS", params: starttls,
			serve: func(c *fakeConn) {
				c.say("220 mail.example.org ESMTP\r\n")
				c.hear()
				c.say("250-mail.example.org\r\n250 STARTTLSX\r\n")
				c.hear()
			},
			want: "false smtp: no STARTTLS false", heard: "[" + ehlo + " QUIT]",
		},
	})
}

func TestProtoSensorReportsAFailedHandshake(t *testing.T) {
	srv := fakeServer(t, func(c *fakeConn) {
		c.say("220 mail.example.org ESMTP\r\n")
		c.hear()
		c.say("250-mail.example.org\r\n250 STARTTLS\r\n")
		c.hear()
		c.say("220 go ahead\r\n")
		if _, err := c.r.Read(make([]byte, 512)); err == nil {
			c.say("no TLS here\r\n")
		}
		c.drain()
	})
	got, err := protoSensor(context.Background(), onLoopback("proto", srv.port(), map[string]any{"protocol": "smtp", "starttls": true}), "")
	if err != nil || got["ok"] != false || got["tls_ok"] != false || !strings.HasPrefix(fmt.Sprint(got["detail"]), "smtp: the TLS handshake: ") {
		t.Errorf("a server without TLS after STARTTLS = %v, %v; want the failed handshake", got, err)
	}
	if heard := fmt.Sprint(srv.close()); heard != "["+ehlo+" STARTTLS]" {
		t.Errorf("the server heard %s, want no QUIT after the failed handshake", heard)
	}
}

func TestProtoSensorEndsWithItsProbe(t *testing.T) {
	srv := fakeServer(t, func(c *fakeConn) {
		for c.hear() != "" {
		}
	})
	ctx, cancel := context.WithTimeout(context.Background(), 300*time.Millisecond)
	defer cancel()
	if _, err := protoSensor(ctx, onLoopback("proto", srv.port(), map[string]any{"protocol": "smtp"}), ""); !errors.Is(err, context.DeadlineExceeded) {
		t.Errorf("a silent server = %v, want the end of the probe", err)
	}
	if heard := fmt.Sprint(srv.close()); heard != "[]" {
		t.Errorf("the server heard %s after the end of the probe", heard)
	}
}

func TestProtoSensorSpeaksIMAPAndPOP3(t *testing.T) {
	pki := newPKI(t)
	imap, imapTLS := map[string]any{"protocol": "imap"}, map[string]any{"protocol": "imap", "starttls": true}
	pop3, pop3TLS := map[string]any{"protocol": "pop3"}, map[string]any{"protocol": "pop3", "starttls": true}
	logout := func(c *fakeConn) {
		if c.hear() == "a2 LOGOUT" {
			c.say("* BYE logging out\r\na2 OK done\r\n")
		}
	}
	quit := func(c *fakeConn) {
		if c.hear() == "QUIT" {
			c.say("+OK bye\r\n")
		}
	}
	greets := func(greeting string, then func(*fakeConn)) func(*fakeConn) {
		return func(c *fakeConn) {
			c.say(greeting)
			then(c)
		}
	}
	runProtoCases(t, []protoCase{
		{name: "imap", params: imap, serve: greets("* OK [CAPABILITY IMAP4rev2] ready\r\n", logout), want: "true imap false", heard: "[a2 LOGOUT]"},
		{
			name: "imap STARTTLS", params: imapTLS,
			serve: greets("* OK ready\r\n", func(c *fakeConn) {
				if c.hear() != "a1 STARTTLS" {
					return
				}
				c.say("* CAPABILITY IMAP4rev2 STARTTLS\r\na1 OK begin TLS\r\n")
				if c.upgrade(pki.chain) {
					logout(c)
				}
			}),
			want: "true imap true", heard: "[a1 STARTTLS a2 LOGOUT]",
		},
		{
			name: "imap STARTTLS refused", params: imapTLS,
			serve: greets("* OK ready\r\n", func(c *fakeConn) {
				c.hear()
				c.say("a1 BAD not now\r\n")
				logout(c)
			}),
			want: "false imap: STARTTLS refused false", heard: "[a1 STARTTLS a2 LOGOUT]",
		},
		{
			name: "imap preauthenticated", params: imapTLS, serve: greets("* PREAUTH ready\r\n", logout),
			want: "false imap: preauthenticated, no STARTTLS false", heard: "[a2 LOGOUT]",
		},
		{name: "imap refusing", params: imap, serve: greets("* BYE too many connections\r\n", logout), want: "false imap: refused false", heard: "[]"},
		{name: "imap without a greeting", params: imap, serve: greets("hello\r\n", logout), want: "false imap: no greeting false", heard: "[]"},
		{name: "pop3", params: pop3, serve: greets("+OK ready\r\n", quit), want: "true pop3 false", heard: "[QUIT]"},
		{
			name: "pop3 STLS", params: pop3TLS,
			serve: greets("+OK ready\r\n", func(c *fakeConn) {
				if c.hear() != "STLS" {
					return
				}
				c.say("+OK begin TLS\r\n")
				if c.upgrade(pki.chain) {
					quit(c)
				}
			}),
			want: "true pop3 true", heard: "[STLS QUIT]",
		},
		{
			name: "pop3 STLS refused", params: pop3TLS,
			serve: greets("+OK ready\r\n", func(c *fakeConn) {
				c.hear()
				c.say("-ERR not now\r\n")
				quit(c)
			}),
			want: "false pop3: STLS refused false", heard: "[STLS QUIT]",
		},
		{name: "pop3 refusing", params: pop3, serve: greets("-ERR busy\r\n", quit), want: "false pop3: refused false", heard: "[]"},
	})
}

// The requests of LDAP, written out byte by byte.
const (
	ldapWhoAmI1   = "30 1e 02 01 01 77 19 80 17 31 2e 33 2e 36 2e 31 2e 34 2e 31 2e 34 32 30 33 2e 31 2e 31 31 2e 33"
	ldapWhoAmI2   = "30 1e 02 01 02 77 19 80 17 31 2e 33 2e 36 2e 31 2e 34 2e 31 2e 34 32 30 33 2e 31 2e 31 31 2e 33"
	ldapStartTLS1 = "30 1d 02 01 01 77 18 80 16 31 2e 33 2e 36 2e 31 2e 34 2e 31 2e 31 34 36 36 2e 32 30 30 33 37"
	ldapUnbind3   = "30 05 02 01 03 42 00"
)

// ldapAnswer is an ExtendedResponse of message id with resultCode code.
func ldapAnswer(id, code byte) string {
	return "\x30\x0c\x02\x01" + string(rune(id)) + "\x78\x07\x0a\x01" + string(rune(code)) + "\x04\x00\x04\x00"
}

func TestProtoSensorSpeaksLDAP(t *testing.T) {
	pki := newPKI(t)
	ldap, ldapTLS := map[string]any{"protocol": "ldap"}, map[string]any{"protocol": "ldap", "starttls": true}
	answers := func(answer string) func(*fakeConn) {
		return func(c *fakeConn) {
			if c.read(32) != nil {
				c.say(answer)
				c.read(7)
			}
		}
	}
	whoAmI := "[" + ldapWhoAmI1 + " " + ldapUnbind3 + "]"
	runProtoCases(t, []protoCase{
		{name: "WhoAmI", params: ldap, serve: answers(ldapAnswer(1, 0)), want: "true ldap false", heard: whoAmI},
		{name: "busy", params: ldap, serve: answers(ldapAnswer(1, 51)), want: "false ldap: busy false", heard: whoAmI},
		{name: "unavailable", params: ldap, serve: answers(ldapAnswer(1, 52)), want: "false ldap: unavailable false", heard: whoAmI},
		{name: "another result", params: ldap, serve: answers(ldapAnswer(1, 2)), want: "true ldap: result 2 false", heard: whoAmI},
		{
			name: "a notice of disconnection", params: ldap, serve: answers(ldapAnswer(0, 52)),
			want: "false ldap: the server ended the session false", heard: whoAmI,
		},
		{
			name: "a length in the long form", params: ldap, serve: answers("\x30\x81" + ldapAnswer(1, 0)[1:]),
			want: "true ldap false", heard: whoAmI,
		},
		{
			name: "an indefinite length", params: ldap, serve: answers("\x30\x80" + ldapAnswer(1, 0)[2:] + "\x00\x00"),
			want: "false ldap: no LDAP answer to WhoAmI false", heard: whoAmI,
		},
		{
			name: "a message too long", params: ldap, serve: answers("\x30\x83\x01\x00\x01"),
			want: "false ldap: the answer to WhoAmI is too long false", heard: whoAmI,
		},
		{
			name: "a result of another operation", params: ldap, serve: answers("\x30\x0c\x02\x01\x01\x61\x07\x0a\x01\x00\x04\x00\x04\x00"),
			want: "false ldap: no LDAP answer to WhoAmI false", heard: whoAmI,
		},
		{
			name: "no LDAP", params: ldap, serve: answers("HTTP/1.1 400 Bad Request\r\n\r\n"),
			want: "false ldap: no LDAP answer to WhoAmI false", heard: whoAmI,
		},
		{
			name: "StartTLS", params: ldapTLS,
			serve: func(c *fakeConn) {
				if c.read(31) == nil {
					return
				}
				c.say(ldapAnswer(1, 0))
				if c.upgrade(pki.chain) && c.read(32) != nil {
					c.say(ldapAnswer(2, 0))
					c.read(7)
				}
			},
			want: "true ldap true", heard: "[" + ldapStartTLS1 + " " + ldapWhoAmI2 + " " + ldapUnbind3 + "]",
		},
		{
			name: "StartTLS refused", params: ldapTLS,
			serve: func(c *fakeConn) {
				if c.read(31) != nil {
					c.say(ldapAnswer(1, 2))
					c.read(7)
				}
			},
			want: "false ldap: StartTLS refused (result 2) false", heard: "[" + ldapStartTLS1 + " " + ldapUnbind3 + "]",
		},
	})
}

func TestProtoSensorAsksPostgreSQLForTLSOnly(t *testing.T) {
	pki := newPKI(t)
	pg, pgTLS := map[string]any{"protocol": "postgres"}, map[string]any{"protocol": "postgres", "starttls": true}
	answers := func(answer string, tls bool) func(*fakeConn) {
		return func(c *fakeConn) {
			if c.read(8) == nil {
				return
			}
			c.say(answer)
			if !tls || c.upgrade(pki.chain) {
				c.read(1)
			}
		}
	}
	const sslRequest = "[00 00 00 08 04 d2 16 2f]"
	runProtoCases(t, []protoCase{
		{name: "N", params: pg, serve: answers("N", false), want: "true postgres false", heard: sslRequest},
		{name: "S", params: pg, serve: answers("S", true), want: "true postgres true", heard: sslRequest},
		{name: "S with starttls", params: pgTLS, serve: answers("S", true), want: "true postgres true", heard: sslRequest},
		{name: "N with starttls", params: pgTLS, serve: answers("N", false), want: "false postgres: no TLS false", heard: sslRequest},
		{name: "E", params: pg, serve: answers("E", false), want: "false postgres: refused false", heard: sslRequest},
		{name: "another answer", params: pg, serve: answers("X", false), want: "false postgres: no answer to SSLRequest false", heard: sslRequest},
		{name: "a server that closes", params: pg, serve: func(c *fakeConn) { c.read(8) }, want: "false postgres: closed at SSLRequest false", heard: sslRequest},
	})
}

// redisInfoAnswer is a bulk string of INFO.
const redisInfoAnswer = "$83\r\n# Server\r\nredis_version:7.2.4\r\nuptime_in_seconds:42\r\n\r\n# Replication\r\nrole:master\r\n\r\n"

func TestProtoSensorReadsRedisINFO(t *testing.T) {
	redis := map[string]any{"protocol": "redis"}
	info := func(answer string) func(*fakeConn) {
		return func(c *fakeConn) {
			if c.hear() == "*1" && c.hear() == "$4" && c.hear() == "INFO" {
				c.say(answer)
			}
			c.hear()
		}
	}
	const heard = "[*1 $4 INFO]"
	runProtoCases(t, []protoCase{
		{
			name: "INFO", params: redis, serve: info(redisInfoAnswer), want: "true redis false", heard: heard,
			data: map[string]any{"redis_version": "7.2.4", "uptime_in_seconds": json.Number("42"), "role": "master"},
		},
		{name: "loading", params: redis, serve: info("-LOADING Redis is loading the dataset in memory\r\n"), want: "false redis: loading false", heard: heard},
		{name: "another error", params: redis, serve: info("-ERR unknown command 'INFO'\r\n"), want: "false redis: INFO answered ERR false", heard: heard},
		{name: "no bulk string", params: redis, serve: info("+PONG\r\n"), want: "false redis: no answer to INFO false", heard: heard},
		{
			name: "a server that closes", params: redis, want: "false redis: closed at INFO false", heard: heard,
			serve: func(c *fakeConn) {
				for range 3 {
					c.hear()
				}
				c.say("$100\r\nredis_version")
			},
		},
	})
}

func TestProtoSensorPresentsTheRedisPassword(t *testing.T) {
	probe := func(auth, info, secret string) (map[string]any, []string, error) {
		srv := fakeServer(t, func(c *fakeConn) {
			for range 5 {
				c.hear()
			}
			c.say(auth)
			if c.hear() == "*1" && c.hear() == "$4" && c.hear() == "INFO" {
				c.say(info)
			}
			c.hear()
		})
		p := onLoopback("proto", srv.port(), map[string]any{"protocol": "redis"})
		p.Credential = &Credential{Ref: "c1", Use: "redis_auth"}
		got, err := protoSensor(context.Background(), p, secret)
		return got, srv.close(), err
	}

	got, heard, err := probe("+OK\r\n", redisInfoAnswer, "s3cret")
	if err != nil || got["ok"] != true || fmt.Sprint(heard) != "[*2 $4 AUTH $6 s3cret *1 $4 INFO]" {
		t.Errorf("AUTH = %v, %v; the server heard %v", got, err, heard)
	}
	_, heard, err = probe("-WRONGPASS invalid username-password pair or user is disabled.\r\n", "", "s3cret")
	if !errors.Is(err, ErrDenied) || err.Error() != "access denied: AUTH answered WRONGPASS" || len(heard) != 5 {
		t.Errorf("a wrong password = %v; the server heard %v; want ErrDenied without INFO", err, heard)
	}
	got, _, err = probe("+QUEUED\r\n", "", "s3cret")
	if err != nil || says(got) != "false redis: no answer to AUTH false" {
		t.Errorf("an odd answer to AUTH = %v, %v", got, err)
	}

	srv := fakeServer(t, func(c *fakeConn) {
		for range 3 {
			c.hear()
		}
		c.say("-NOAUTH Authentication required.\r\n")
		c.hear()
	})
	if _, err := protoSensor(context.Background(), onLoopback("proto", srv.port(), map[string]any{"protocol": "redis"}), ""); !errors.Is(err, ErrDenied) || !strings.HasSuffix(err.Error(), "INFO answered NOAUTH") {
		t.Errorf("INFO without a password = %v, want ErrDenied", err)
	}
}

func TestProtoSensorSendsTheRedisPasswordOnlyToItsTarget(t *testing.T) {
	h := &fakeHost{live: true}
	stubHost(t, h)
	srv := listen(t, func(c *fakeConn) {
		for range 3 {
			c.hear()
		}
		c.say("-NOAUTH Authentication required.\r\n")
		c.hear()
	})
	h.pubs = []publication{{hostPort: uint16(srv.port()), to: 6379}}
	p := Probe{Sensor: "proto", Target: &Target{Kind: kindPort, PortHint: srv.port()}, Params: map[string]any{"protocol": "redis"}}
	ctx := context.Background()

	if _, err := protoSensor(ctx, p, ""); !errors.Is(err, ErrDenied) {
		t.Fatalf("no password = %v, want the port asked and NOAUTH", err)
	}
	p.Credential = &Credential{Ref: "c1", Use: "redis_auth"}
	_, err := protoSensor(ctx, p, "s3cret")
	if !errors.Is(err, ErrNotAllowed) || strings.Contains(err.Error(), "s3cret") {
		t.Fatalf("a password to a published port = %v, want ErrNotAllowed without the secret", err)
	}
	if heard := srv.close(); fmt.Sprint(heard) != "[*1 $4 INFO]" {
		t.Errorf("the server heard %v, want only INFO without AUTH", heard)
	}
}

// fcgiGetValuesRequest is the record FCGI_GET_VALUES, written out.
const fcgiGetValuesRequest = "\x01\x09\x00\x00\x00\x30\x00\x00" +
	"\x0e\x00FCGI_MAX_CONNS\x0d\x00FCGI_MAX_REQS\x0f\x00FCGI_MPXS_CONNS"

func TestProtoSensorAsksFastCGIForItsValues(t *testing.T) {
	fastcgi := map[string]any{"protocol": "fastcgi"}
	answers := func(answer string) func(*fakeConn) {
		return func(c *fakeConn) {
			if c.read(len(fcgiGetValuesRequest)) != nil {
				c.say(answer)
				c.read(1)
			}
		}
	}
	heard := fmt.Sprintf("[% x]", fcgiGetValuesRequest)
	runProtoCases(t, []protoCase{
		{
			name: "FCGI_GET_VALUES_RESULT", params: fastcgi, want: "true fastcgi false", heard: heard,
			serve: answers("\x01\x0a\x00\x00\x00\x33\x05\x00" +
				"\x0e\x01FCGI_MAX_CONNS1\x0d\x01FCGI_MAX_REQS1\x0f\x01FCGI_MPXS_CONNS0" + "\x00\x00\x00\x00\x00"),
			data: map[string]any{"FCGI_MAX_CONNS": json.Number("1"), "FCGI_MAX_REQS": json.Number("1"), "FCGI_MPXS_CONNS": json.Number("0")},
		},
		{
			name: "FCGI_UNKNOWN_TYPE", params: fastcgi, want: "true fastcgi false", heard: heard,
			serve: answers("\x01\x0b\x00\x00\x00\x08\x00\x00\x09\x00\x00\x00\x00\x00\x00\x00"),
		},
		{
			name: "another record", params: fastcgi, want: "false fastcgi: no answer to FCGI_GET_VALUES false", heard: heard,
			serve: answers("\x01\x06\x00\x01\x00\x02\x00\x00ok"),
		},
		{
			name: "no FastCGI", params: fastcgi, want: "false fastcgi: no answer to FCGI_GET_VALUES false", heard: heard,
			serve: answers("HTTP/1.0 400 Bad Request\r\n\r\n"),
		},
		{
			name: "a server that closes", params: fastcgi, want: "false fastcgi: closed at FCGI_GET_VALUES false", heard: heard,
			serve: func(c *fakeConn) {
				c.read(len(fcgiGetValuesRequest))
				c.say("\x01\x0a")
			},
		},
	})
}

func TestFastCGIPairsTakeLongLengthsAndDropTheRest(t *testing.T) {
	got := fcgiPairs([]byte("\x03\x80\x00\x00\x05abcvwxyz\x05\x05abc"))
	if !reflect.DeepEqual(got, map[string]any{"abc": "vwxyz"}) {
		t.Errorf("pairs = %#v", got)
	}
	if got := fcgiPairs([]byte("\x80\x00")); len(got) != 0 {
		t.Errorf("a cut length = %#v", got)
	}
}

func TestProtoSensorReadsTheStatsOfHAProxy(t *testing.T) {
	haproxy := map[string]any{"protocol": "haproxy"}
	answers := func(answer string) func(*fakeConn) {
		return func(c *fakeConn) {
			if c.hear() == "show stat" {
				c.say(answer)
			}
		}
	}
	runProtoCases(t, []protoCase{
		{
			name: "show stat", params: haproxy, want: "true haproxy false", heard: "[show stat]",
			serve: answers("# pxname,svname,qcur,status,check_desc,\n" +
				"web,FRONTEND,0,OPEN,,\n" +
				"web,app1,,UP,\"Layer4 check passed, 1ms\",\n" +
				"stats,BACKEND,0,UP,,\n\n"),
			data: map[string]any{
				"web": map[string]any{
					"FRONTEND": map[string]any{"qcur": json.Number("0"), "status": "OPEN"},
					"app1":     map[string]any{"status": "UP", "check_desc": "Layer4 check passed, 1ms"},
				},
				"stats": map[string]any{"BACKEND": map[string]any{"qcur": json.Number("0"), "status": "UP"}},
			},
		},
		{
			name: "another answer", params: haproxy, want: "false haproxy: no answer to show stat false", heard: "[show stat]",
			serve: answers("Unknown command. Please enter one of the following commands only :\n"),
		},
	})
}

func TestProtoSensorReadsABanner(t *testing.T) {
	banner := map[string]any{"protocol": "banner"}
	greets := func(greeting string) func(*fakeConn) {
		return func(c *fakeConn) {
			c.say(greeting)
			c.hear()
		}
	}
	runProtoCases(t, []protoCase{
		{name: "a banner", params: banner, serve: greets("SSH-2.0-OpenSSH_9.6\x01\x7f\r\n"), want: "true SSH-2.0-OpenSSH_9.6 false", heard: "[]"},
		{name: "a long banner", params: banner, serve: greets(strings.Repeat("x", 200) + "\r\n"), want: "true " + strings.Repeat("x", 128) + " false", heard: "[]"},
		{name: "no banner", params: banner, serve: func(*fakeConn) {}, want: "false banner: closed at the banner false", heard: "[]"},
	})
}

func TestProtoSensorTakesItsParams(t *testing.T) {
	ctx := context.Background()
	pr := func(params map[string]any) Probe { return onLoopback("proto", 25, params) }
	withCredential := func(p Probe, use string) Probe {
		p.Credential = &Credential{Ref: "c1", Use: use}
		return p
	}
	for _, c := range []struct {
		name string
		p    Probe
	}{
		{"no protocol", pr(nil)},
		{"an unknown protocol", pr(map[string]any{"protocol": "http"})},
		{"starttls of redis", pr(map[string]any{"protocol": "redis", "starttls": true})},
		{"starttls of auto", pr(map[string]any{"protocol": "auto", "starttls": true})},
		{"starttls as text", pr(map[string]any{"protocol": "smtp", "starttls": "yes"})},
		{"a status_path of redis", pr(map[string]any{"protocol": "redis", "status_path": "/status"})},
		{"a status_path without slash", pr(map[string]any{"protocol": "fastcgi", "status_path": "status"})},
		{"a credential for smtp", withCredential(pr(map[string]any{"protocol": "smtp"}), "basic")},
		{"a bearer token for redis", withCredential(pr(map[string]any{"protocol": "redis"}), "bearer")},
		{"another param", pr(map[string]any{"protocol": "smtp", "path": "/"})},
		{"no target", Probe{Sensor: "proto", Params: map[string]any{"protocol": "smtp"}}},
	} {
		if _, err := protoSensor(ctx, c.p, ""); !errors.Is(err, ErrInvalid) {
			t.Errorf("%s: %v, want ErrInvalid", c.name, err)
		}
	}
	if _, err := protoSensor(ctx, pr(map[string]any{"protocol": "fastcgi", "status_path": "/status"}), ""); !errors.Is(err, ErrUnsupported) {
		t.Errorf("the status page of FastCGI = %v, want ErrUnsupported", err)
	}
}

// direct dials 127.0.0.1:port without the guard, for tests that run in parallel.
func direct(port int) func(context.Context) (net.Conn, error) {
	return func(ctx context.Context) (net.Conn, error) {
		var d net.Dialer
		c, err := d.DialContext(ctx, "tcp4", fmt.Sprintf("127.0.0.1:%d", port))
		if err != nil {
			return nil, err
		}
		return bind(ctx, c), nil
	}
}

// quietHTTPS is a server of HTTPS with cert that logs nothing.
func quietHTTPS(t *testing.T, cert tls.Certificate) int {
	t.Helper()
	srv := httptest.NewUnstartedServer(http.HandlerFunc(func(http.ResponseWriter, *http.Request) {}))
	srv.TLS = &tls.Config{Certificates: []tls.Certificate{cert}}
	srv.Config.ErrorLog = log.New(io.Discard, "", 0)
	srv.StartTLS()
	t.Cleanup(srv.Close)
	return portOf(t, srv.URL)
}

// Recognition waits for servers that stay silent, so its cases run in parallel; they dial without the
// guard and touch none of its seams.
func TestRecognizeTellsWhatListens(t *testing.T) {
	pki := newPKI(t)
	greets := func(greeting string) func(*fakeConn) {
		return func(c *fakeConn) {
			c.say(greeting)
			c.hear()
		}
	}
	answersHEAD := func(answer string) func(*fakeConn) {
		return func(c *fakeConn) {
			if c.hear() == "HEAD / HTTP/1.0" && c.hear() == "" {
				c.say(answer)
			}
			c.drain()
		}
	}
	const head = "[HEAD / HTTP/1.0 ]"
	for _, c := range []struct {
		name  string
		serve func(*fakeConn)
		// want is ok, detail and tls_ok; heard is what the server heard, unless the server is of TLS.
		want, heard string
	}{
		{"smtp", greets("220 mail.example.org ESMTP Postfix\r\n"), "true smtp false", "[QUIT]"},
		{"ftp", greets("220 (vsFTPd 3.0.5)\r\n"), "true ftp false", "[QUIT]"},
		{"a refusing smtp", greets("554 5.7.1 SMTP service refused\r\n"), "false smtp: greeting 554 false", "[QUIT]"},
		{"a reply of another service", greets("200 ready\r\n"), "true banner false", "[QUIT]"},
		{"imap", greets("* OK [CAPABILITY IMAP4rev1] ready\r\n"), "true imap false", "[a1 LOGOUT]"},
		{"a refusing imap", greets("* BYE too many connections\r\n"), "false imap: refused false", "[]"},
		{"pop3", greets("+OK ready\r\n"), "true pop3 false", "[QUIT]"},
		{"a refusing pop3", greets("-ERR busy\r\n"), "false pop3: refused false", "[]"},
		{"ssh", greets("SSH-2.0-OpenSSH_9.6\r\n"), "true ssh false", "[]"},
		{"a banner", greets("hello from a service\r\n"), "true banner false", "[]"},
		{"a binary greeting", greets("\x00\x01\xfe\xff"), "true banner false", "[]"},
		{"a line too long", greets(strings.Repeat("x", 5000)), "true banner false", "[]"},
		{"http", answersHEAD("HTTP/1.1 200 OK\r\n\r\n"), "true http false", head},
		{"a failing http", answersHEAD("HTTP/1.1 503 Service Unavailable\r\n\r\n"), "false http: status 503 false", head},
		{"http without a status", answersHEAD("HTTP/1.1 OK\r\n\r\n"), "false http: status 0 false", head},
		{"redis", answersHEAD("-NOAUTH Authentication required.\r\n"), "true redis false", head},
		{"another answer", answersHEAD("unknown command\r\n"), "true unknown false", head},
		{"a server that closes", func(*fakeConn) {}, "true unknown false", "[]"},
		{"a silent server", func(c *fakeConn) { c.drain() }, "true unknown false", "[]"},
		{
			"smtps",
			func(c *fakeConn) {
				if c.upgrade(pki.chain) {
					c.say("220 mail.example.org ESMTP\r\n")
					c.hear()
				}
			},
			"true smtps true", "[QUIT]",
		},
		{
			"a silent server of TLS",
			func(c *fakeConn) {
				if c.upgrade(pki.chain) {
					c.drain()
				}
			},
			"true tls true", "[]",
		},
		{
			// frps on its bind port: TLS only, and silent to anything but its own protocol.
			"a server of TLS that closes",
			func(c *fakeConn) { c.upgrade(pki.chain) },
			"true tls true", "[]",
		},
		{
			// frps on its vhost port: it closes a connection that sends no TLS in time (before the
			// banner wait ends), and a TLS one without the name of a vhost.
			"a server of TLS that wants SNI",
			func(c *fakeConn) {
				_ = c.conn.SetReadDeadline(time.Now().Add(300 * time.Millisecond))
				_ = tls.Server(c.conn, &tls.Config{
					Certificates: []tls.Certificate{pki.chain},
					GetConfigForClient: func(h *tls.ClientHelloInfo) (*tls.Config, error) {
						if h.ServerName != "vhost.example.org" {
							return nil, errors.New("no such vhost")
						}
						return nil, nil
					},
				}).Handshake()
			},
			"true unknown false", "[]",
		},
		{"https", nil, "true https true", ""},
	} {
		t.Run(c.name, func(t *testing.T) {
			t.Parallel()
			var srv *fake
			var port int
			if c.serve == nil {
				port = quietHTTPS(t, pki.chain)
			} else {
				srv = listen(t, c.serve)
				port = srv.port()
			}
			ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
			defer cancel()
			res, err := recognize(ctx, direct(port))
			if err != nil {
				t.Fatal(err)
			}
			if s := says(res.values()); s != c.want {
				t.Errorf("recognized %s, want %s", s, c.want)
			}
			if res.took >= time.Second {
				t.Errorf("took %v, want the silence of the server left out", res.took)
			}
			if srv != nil {
				if heard := fmt.Sprint(srv.close()); heard != c.heard {
					t.Errorf("the server heard %s, want %s", heard, c.heard)
				}
			}
		})
	}
	t.Run("a closed port", func(t *testing.T) {
		t.Parallel()
		ln, err := net.Listen("tcp4", "127.0.0.1:0")
		if err != nil {
			t.Fatal(err)
		}
		port := ln.Addr().(*net.TCPAddr).Port
		_ = ln.Close()
		ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()
		if res, err := recognize(ctx, direct(port)); err == nil {
			t.Errorf("recognize on a closed port = %s, want an error", says(res.values()))
		}
	})
	t.Run("the end of the probe", func(t *testing.T) {
		t.Parallel()
		srv := listen(t, func(c *fakeConn) { c.drain() })
		ctx, cancel := context.WithTimeout(context.Background(), 300*time.Millisecond)
		defer cancel()
		if _, err := recognize(ctx, direct(srv.port())); !errors.Is(err, context.DeadlineExceeded) {
			t.Errorf("recognize past the end of the probe = %v", err)
		}
	})
}

func TestProtoSensorRecognizesThroughTheGuard(t *testing.T) {
	srv := fakeServer(t, func(c *fakeConn) {
		c.say("220 mail.example.org ESMTP\r\n")
		c.hear()
	})
	got, err := protoSensor(context.Background(), onLoopback("proto", srv.port(), map[string]any{"protocol": "auto"}), "")
	if err != nil || says(got) != "true smtp false" {
		t.Errorf("auto = %v, %v; want smtp", got, err)
	}
	if took, ok := got["duration_ms"].(int64); !ok || took < 0 {
		t.Errorf("duration_ms = %#v", got["duration_ms"])
	}
	if heard := fmt.Sprint(srv.close()); heard != "[QUIT]" {
		t.Errorf("the server heard %s", heard)
	}
}

func TestFCGIStatusRequestIsOneResponderRequestOfJSON(t *testing.T) {
	b := fcgiStatusRequest("/status")
	var types []byte
	var params []byte
	for len(b) > 0 {
		n := int(binary.BigEndian.Uint16(b[4:6]))
		if b[0] != 1 || binary.BigEndian.Uint16(b[2:4]) != 1 || b[6] != 0 {
			t.Fatalf("record % x, want version 1, request 1, no padding", b[:8])
		}
		switch b[1] {
		case fcgiBeginRequest:
			if string(b[8:8+n]) != "\x00\x01\x00\x00\x00\x00\x00\x00" {
				t.Errorf("FCGI_BEGIN_REQUEST % x, want the responder without keep-conn", b[8:8+n])
			}
		case fcgiParams:
			params = append(params, b[8:8+n]...)
		}
		types = append(types, b[1])
		b = b[8+n:]
	}
	if fmt.Sprint(types) != "[1 4 4 5]" {
		t.Errorf("records %v, want BEGIN_REQUEST, PARAMS, empty PARAMS, empty STDIN", types)
	}
	got := fmt.Sprint(fcgiPairs(params))
	if got != "map[QUERY_STRING:json REQUEST_METHOD:GET REQUEST_URI:/status?json SCRIPT_FILENAME:/status SCRIPT_NAME:/status]" {
		t.Errorf("params %s", got)
	}
}

// fcgiAnswer answers the request on the other end of the returned session with records, after
// reading the request whole.
func fcgiAnswer(t *testing.T, records ...[]byte) *session {
	t.Helper()
	client, server := net.Pipe()
	go func() {
		defer func() { _ = server.Close() }()
		if _, err := io.ReadFull(server, make([]byte, len(fcgiStatusRequest("/status")))); err != nil {
			return
		}
		for _, r := range records {
			if _, err := server.Write(r); err != nil {
				return
			}
		}
	}()
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	t.Cleanup(cancel)
	s := newSession(ctx, client)
	t.Cleanup(s.end)
	return s
}

func TestFCGIStatusPageReadsStdoutAndDropsStderr(t *testing.T) {
	padded := append(fcgiRecord(fcgiStdout, []byte("Content-Type: application/json\r\n\r\n{\"a\":")), 0, 0, 0)
	padded[6] = 3
	s := fcgiAnswer(t, padded, fcgiRecord(fcgiStderr, []byte("PHP Warning: x")),
		fcgiRecord(fcgiStdout, []byte("1}")), fcgiRecord(fcgiStdout, nil), fcgiRecord(fcgiEndRequest, make([]byte, 8)))
	page, err := fcgiStatusPage(s, "/status", 1024)
	if err != nil || string(page) != `{"a":1}` {
		t.Errorf("fcgiStatusPage = %q, %v; want the body of stdout", page, err)
	}
}

func TestFCGIStatusPageRefusesAnAnswerOutsideTheRequest(t *testing.T) {
	end := fcgiRecord(fcgiEndRequest, make([]byte, 8))
	ok := fcgiRecord(fcgiStdout, []byte("Status: 200 OK\r\n\r\n{}"))
	otherID := fcgiRecord(fcgiStdout, []byte("Status: 200 OK\r\n\r\n{}"))
	otherID[3] = 2
	overloaded := fcgiRecord(fcgiEndRequest, []byte{0, 0, 0, 0, 2, 0, 0, 0})
	for name, c := range map[string]struct {
		records [][]byte
		limit   int
		want    string
	}{
		"another request":   {[][]byte{otherID, end}, 1024, "no answer to the request for the status page"},
		"an unknown record": {[][]byte{fcgiRecord(11, make([]byte, 8)), end}, 1024, "no answer to"},
		"overloaded":        {[][]byte{ok, overloaded}, 1024, "the application refuses"},
		"too long":          {[][]byte{ok, end}, 8, "is too long"},
		"no header":         {[][]byte{fcgiRecord(fcgiStdout, []byte("{}")), end}, 1024, "no answer to"},
		"not found":         {[][]byte{fcgiRecord(fcgiStdout, []byte("Status: 404 Not Found\r\n\r\nx")), end}, 1024, "is status 404"},
		"closed":            {[][]byte{ok}, 1024, "closed at the request for the status page"},
	} {
		t.Run(name, func(t *testing.T) {
			_, err := fcgiStatusPage(fcgiAnswer(t, c.records...), "/status", c.limit)
			var pf protoFail
			if !errors.As(err, &pf) || !strings.Contains(pf.detail, c.want) || strings.Contains(pf.detail, "/status") {
				t.Errorf("fcgiStatusPage = %v, want a protoFail naming %q and not the path", err, c.want)
			}
		})
	}
	page, err := fcgiStatusPage(fcgiAnswer(t, ok, end), "/status", 1024)
	if err != nil || string(page) != "{}" {
		t.Errorf("Status 200 = %q, %v; want the body", page, err)
	}
}
