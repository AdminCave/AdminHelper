// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package probe

import (
	"bytes"
	"context"
	"crypto/tls"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/netip"
	"net/url"
	"regexp"
	"slices"
	"strings"
	"time"
	"unicode"
	"unicode/utf8"
)

// The network sensors talk to a service of this host: http, tls and proto over TCP through the guard,
// unixsocket over a unix socket, dns through the host's resolver.
func init() {
	sensors["http"] = httpSensor
}

// The uses of a credential (Credential.Use); useHeader is followed by the name of the header.
const (
	useBearer    = "bearer"
	useBasic     = "basic"
	useRedisAuth = "redis_auth"
	useHeader    = "header:"
)

// headerName is the name of a header a credential goes in, as the monitoring service allows it.
var headerName = regexp.MustCompile(`^[A-Za-z0-9-]{1,64}$`)

// httpTargets are the kinds of target a TCP sensor takes.
var httpTargets = []string{kindLoopback, kindPort, kindProcess, kindContainer, kindUnit}

// knownParams returns an error wrapping ErrInvalid if p has a param that is none of keys.
func knownParams(p Probe, keys ...string) error {
	for k := range p.Params {
		if !slices.Contains(keys, k) {
			return fmt.Errorf("%w: sensor %s takes no parameter %s", ErrInvalid, p.Sensor, k)
		}
	}
	return nil
}

// textParam returns the text param key of p, or def if p has none.
func textParam(p Probe, key, def string) (string, error) {
	v, ok := p.Params[key]
	if !ok {
		return def, nil
	}
	s, ok := v.(string)
	if !ok {
		return "", fmt.Errorf("%w: parameter %s of sensor %s is no text", ErrInvalid, key, p.Sensor)
	}
	return s, nil
}

// choiceParam returns the param key of p, one of choices, or def if p has none.
func choiceParam(p Probe, key, def string, choices ...string) (string, error) {
	s, err := textParam(p, key, def)
	if err != nil {
		return "", err
	}
	if !slices.Contains(choices, s) {
		return "", fmt.Errorf("%w: parameter %s of sensor %s is none of %s", ErrInvalid, key, p.Sensor,
			strings.Join(choices, ", "))
	}
	return s, nil
}

// boolParam returns the boolean param key of p, false if p has none.
func boolParam(p Probe, key string) (bool, error) {
	v, ok := p.Params[key]
	if !ok {
		return false, nil
	}
	b, ok := v.(bool)
	if !ok {
		return false, fmt.Errorf("%w: parameter %s of sensor %s is no boolean", ErrInvalid, key, p.Sensor)
	}
	return b, nil
}

// plainText says whether s is valid UTF-8 of at most maxRunes runes without space or control
// character.
func plainText(s string, maxRunes int) bool {
	return utf8.ValidString(s) && utf8.RuneCountInString(s) <= maxRunes &&
		!strings.ContainsFunc(s, func(r rune) bool { return unicode.IsSpace(r) || unicode.IsControl(r) })
}

// requestPath returns the param key of p, the path of a request ("/…" of at most maxRunes runes
// without space or control character), or def if p has none; allowEmpty lets "" through.
func requestPath(p Probe, key, def string, maxRunes int, allowEmpty bool) (string, error) {
	s, err := textParam(p, key, def)
	if err != nil {
		return "", err
	}
	if s == "" && allowEmpty {
		return s, nil
	}
	if !strings.HasPrefix(s, "/") || !plainText(s, maxRunes) {
		return "", fmt.Errorf("%w: parameter %s of sensor %s needs a path of at most %d characters without spaces",
			ErrInvalid, key, p.Sensor, maxRunes)
	}
	return s, nil
}

// credentialUse returns how p presents its credential, "" without one. A use the sensor does not take
// (uses, useHeader standing for every header) is an error wrapping ErrInvalid.
func credentialUse(p Probe, uses ...string) (string, error) {
	if p.Credential == nil {
		return "", nil
	}
	use, kind := p.Credential.Use, p.Credential.Use
	if name, ok := strings.CutPrefix(use, useHeader); ok {
		if !headerName.MatchString(name) {
			return "", fmt.Errorf("%w: a credential cannot go in header %q", ErrInvalid, name)
		}
		kind = useHeader
	}
	if !slices.Contains(uses, kind) {
		return "", fmt.Errorf("%w: sensor %s takes no credential for %q", ErrInvalid, p.Sensor, use)
	}
	return use, nil
}

// authorize puts secret in req as use says. No error quotes the secret.
func authorize(req *http.Request, use, secret string) error {
	switch {
	case use == useBearer:
		req.Header.Set("Authorization", "Bearer "+secret)
	case use == useBasic:
		user, password, ok := strings.Cut(secret, ":")
		if !ok {
			return fmt.Errorf("%w: a credential for basic needs the form user:password", ErrInvalid)
		}
		req.SetBasicAuth(user, password)
	case strings.HasPrefix(use, useHeader):
		req.Header.Set(strings.TrimPrefix(use, useHeader), secret)
	}
	return nil
}

// dialTarget connects to ep through the guard; the connection ends with ctx.
func dialTarget(ctx context.Context, ep endpoint) (net.Conn, error) {
	conn, err := NewGuard(ep.extra...).DialContext(ctx, "tcp", netip.AddrPortFrom(ep.addr, ep.port).String())
	if err != nil {
		return nil, netErr(ctx, err)
	}
	return bind(ctx, conn), nil
}

// bind lets no read or write on conn outlast ctx's deadline and closes conn once ctx ends.
func bind(ctx context.Context, conn net.Conn) net.Conn {
	if d, ok := ctx.Deadline(); ok {
		_ = conn.SetDeadline(d)
	}
	context.AfterFunc(ctx, func() { _ = conn.Close() })
	return conn
}

// ended says whether ctx is done or its deadline has passed: an I/O error then is the probe's timeout.
func ended(ctx context.Context) bool {
	if ctx.Err() != nil {
		return true
	}
	d, ok := ctx.Deadline()
	return ok && !time.Now().Before(d)
}

// netErr is the probe's error for err, met on the network: the end of ctx if it has ended, else err.
func netErr(ctx context.Context, err error) error {
	if !ended(ctx) {
		return err
	}
	if e := ctx.Err(); e != nil {
		return e
	}
	return context.DeadlineExceeded
}

// httpSensor sends a GET or HEAD to its target through the guard: status code, time to the headers
// and, for GET, fields of the JSON object the target answers.
func httpSensor(ctx context.Context, p Probe, secret string) (map[string]any, error) {
	t, err := targetOf(p, httpTargets...)
	if err != nil {
		return nil, err
	}
	if err := knownParams(p, "path", "method"); err != nil {
		return nil, err
	}
	path, err := requestPath(p, "path", "/", 512, false)
	if err != nil {
		return nil, err
	}
	method, err := choiceParam(p, "method", http.MethodGet, http.MethodGet, http.MethodHead)
	if err != nil {
		return nil, err
	}
	scheme := t.Scheme
	switch scheme {
	case "":
		scheme = "http"
	case "http", "https":
	default:
		return nil, fmt.Errorf("%w: sensor http takes no scheme %q", ErrInvalid, scheme)
	}
	use, err := credentialUse(p, useBearer, useBasic, useHeader)
	if err != nil {
		return nil, err
	}
	u, err := url.ParseRequestURI(path)
	if err != nil {
		return nil, fmt.Errorf("%w: parameter path of sensor http is no path of a request", ErrInvalid)
	}
	ep, err := resolve(ctx, t)
	if err != nil {
		return nil, err
	}
	u.Scheme, u.Host = scheme, netip.AddrPortFrom(ep.addr, ep.port).String()
	// The certificate of a service on this host is the tls sensor's business; http measures the answer,
	// and a self-signed certificate must not hide it.
	client := NewGuard(ep.extra...).HTTPClient(&tls.Config{InsecureSkipVerify: true}) //nolint:gosec // the tls sensor checks certificates
	return fetch(ctx, client, method, u.String(), use, secret, p.Fields)
}

// fetch sends one request to target with client: the status code, the time to the headers and, if a
// field asks for data (GET only), the JSON object of the body as data. 401 and 403 are ErrDenied.
func fetch(ctx context.Context, client *http.Client, method, target, use, secret string, fields []string) (map[string]any, error) {
	req, err := http.NewRequestWithContext(ctx, method, target, nil)
	if err != nil {
		return nil, fmt.Errorf("%w: %v", ErrInvalid, err)
	}
	if err := authorize(req, use, secret); err != nil {
		return nil, err
	}
	start := time.Now()
	resp, err := client.Do(req)
	if err != nil {
		var ue *url.Error
		if errors.As(err, &ue) {
			err = ue.Err
		}
		return nil, netErr(ctx, err)
	}
	defer resp.Body.Close()
	values := map[string]any{"status_code": resp.StatusCode, "duration_ms": time.Since(start).Milliseconds()}
	if resp.StatusCode == http.StatusUnauthorized || resp.StatusCode == http.StatusForbidden {
		return nil, fmt.Errorf("%w: HTTP %d", ErrDenied, resp.StatusCode)
	}
	if method != http.MethodGet || !slices.ContainsFunc(fields, func(f string) bool { return strings.HasPrefix(f, "data.") }) {
		return values, nil
	}
	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, netErr(ctx, err)
	}
	data, err := jsonObject(body)
	if err != nil {
		return nil, err
	}
	values["data"] = data
	return values, nil
}

// jsonObject decodes b, which must be one JSON object; numbers stay json.Number.
func jsonObject(b []byte) (map[string]any, error) {
	dec := json.NewDecoder(bytes.NewReader(b))
	dec.UseNumber()
	var obj map[string]any
	if err := dec.Decode(&obj); err != nil || obj == nil {
		return nil, errors.New("the answer is no JSON object")
	}
	if _, err := dec.Token(); !errors.Is(err, io.EOF) {
		return nil, errors.New("the answer is no JSON object")
	}
	return obj, nil
}
