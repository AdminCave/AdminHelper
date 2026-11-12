// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package frpspolicy

import (
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"io"
	"log/slog"
	"net"
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
	"time"
)

const pluginPath = "/handler"

// newTestHandler serves the plugin with the fixture policy, or without a policy file if
// policy is nil, and logs into the returned buffer.
func newTestHandler(t *testing.T, policy []byte) (http.Handler, *bytes.Buffer) {
	t.Helper()
	path := filepath.Join(t.TempDir(), "frps-policy.json")
	if policy != nil {
		writeFile(t, path, policy)
	}
	var log bytes.Buffer
	return NewHandler(NewSource(path), pluginPath, slog.New(slog.NewTextHandler(&log, nil))), &log
}

func do(h http.Handler, method, target string, body []byte) *httptest.ResponseRecorder {
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, httptest.NewRequest(method, target, bytes.NewReader(body)))
	return rec
}

// newProxyRequest is the fixture request with change applied to the fields of its
// content the decision reads; the others, such as the stcp secret, stay.
func newProxyRequest(t *testing.T, change func(*NewProxy)) []byte {
	t.Helper()
	var req struct {
		Version string         `json:"version"`
		Op      string         `json:"op"`
		Content map[string]any `json:"content"`
	}
	if err := json.Unmarshal(fixtureRequest(t), &req); err != nil {
		t.Fatal(err)
	}
	np := fixtureNewProxy(t)
	change(np)
	var changed map[string]any
	if data, err := json.Marshal(np); err != nil {
		t.Fatal(err)
	} else if err := json.Unmarshal(data, &changed); err != nil {
		t.Fatal(err)
	}
	for k, v := range changed {
		req.Content[k] = v
	}
	data, err := json.Marshal(req)
	if err != nil {
		t.Fatal(err)
	}
	return data
}

// answer decodes a plugin answer and holds it to frps' fields; a refusal must leave the
// content unchanged.
func answer(t *testing.T, rec *httptest.ResponseRecorder) map[string]any {
	t.Helper()
	if rec.Code != http.StatusOK || rec.Header().Get("Content-Type") != "application/json" {
		t.Fatalf("answer = %d %q, want 200 with JSON: %s", rec.Code, rec.Header().Get("Content-Type"), rec.Body)
	}
	var got map[string]any
	if err := json.Unmarshal(rec.Body.Bytes(), &got); err != nil {
		t.Fatal(err)
	}
	if got["reject"] == true && (got["unchange"] != true || got["content"] != nil) {
		t.Errorf("refusal %v changes the content", got)
	}
	return got
}

// fixtureContent is the content of the fixture request, generically decoded.
func fixtureContent(t *testing.T) map[string]any {
	t.Helper()
	var req struct {
		Content map[string]any `json:"content"`
	}
	if err := json.Unmarshal(fixtureRequest(t), &req); err != nil {
		t.Fatal(err)
	}
	return req.Content
}

func TestHandlerAdmitsTheOwnProxyWithoutItsKey(t *testing.T) {
	h, _ := newTestHandler(t, fixturePolicy(t))
	rec := do(h, http.MethodPost, pluginPath+"?version=0.1.0&op=NewProxy", fixtureRequest(t))
	got := answer(t, rec)
	if len(got) != 3 || got["reject"] != false || got["unchange"] != false {
		t.Fatalf("answer = %v, want reject false, unchange false and the content", got)
	}
	want := fixtureContent(t)
	delete(want["metas"].(map[string]any), KeyMeta)
	if !reflect.DeepEqual(got["content"], want) {
		t.Errorf("content = %v, want the request's content without the key: %v", got["content"], want)
	}
	if strings.Contains(rec.Body.String(), keyA) {
		t.Errorf("answer holds the host's key: %s", rec.Body)
	}
}

func TestHandlerKeepsEveryOtherFieldAsSent(t *testing.T) {
	h, _ := newTestHandler(t, fixturePolicy(t))
	// Fields the decision does not read, a number beyond float64 and a second metas entry:
	// frps takes the answer's content in place of its own.
	body := strings.Replace(string(fixtureRequest(t)), `"proxy_type": "stcp",`,
		`"proxy_type": "stcp", "use_encryption": true, "bandwidth_limit": "1MB", "annotations": {"a": "b"},
		"x_count": 9007199254740993, "x_list": [1.5, null, "s"],`, 1)
	body = strings.Replace(body, `"ahProxyKey": "`+keyA+`"`, `"ahProxyKey": "`+keyA+`", "owner": "ops"`, 1)
	rec := do(h, http.MethodPost, pluginPath+"?op=NewProxy", []byte(body))
	got := answer(t, rec)
	if got["reject"] != false {
		t.Fatalf("answer = %v, want the proxy admitted", got)
	}
	if !strings.Contains(rec.Body.String(), `"x_count":9007199254740993`) {
		t.Errorf("answer lost the exact number: %s", rec.Body)
	}
	var want, content struct {
		Content map[string]any `json:"content"`
	}
	if err := json.Unmarshal([]byte(body), &want); err != nil {
		t.Fatal(err)
	}
	if err := json.Unmarshal(rec.Body.Bytes(), &content); err != nil {
		t.Fatal(err)
	}
	delete(want.Content["metas"].(map[string]any), KeyMeta)
	if !reflect.DeepEqual(content.Content, want.Content) {
		t.Errorf("content = %v, want %v", content.Content, want.Content)
	}
	if m := content.Content["metas"].(map[string]any); len(m) != 1 || m["owner"] != "ops" {
		t.Errorf("metas = %v, want the other entry alone", m)
	}
}

func TestWithoutKeyLeavesItsInputAlone(t *testing.T) {
	content := map[string]any{"metas": map[string]any{KeyMeta: keyA}, "proxy_name": "p"}
	out := WithoutKey(content)
	if _, ok := out["metas"].(map[string]any)[KeyMeta]; ok {
		t.Errorf("WithoutKey = %v, still holds the key", out)
	}
	if content["metas"].(map[string]any)[KeyMeta] != keyA {
		t.Errorf("WithoutKey changed its input: %v", content)
	}
	if out := WithoutKey(map[string]any{"proxy_name": "p"}); len(out) != 1 || out["proxy_name"] != "p" {
		t.Errorf("WithoutKey without metas = %v", out)
	}
}

func TestHandlerRefusesAForeignProxy(t *testing.T) {
	h, _ := newTestHandler(t, fixturePolicy(t))
	for name, change := range map[string]func(*NewProxy){
		"another host's tunnel": func(np *NewProxy) { np.ProxyName = serverA + ".t-db" },
		"another allowed user":  func(np *NewProxy) { np.AllowUsers = []string{"*"} },
		"a wrong secret key":    func(np *NewProxy) { np.Sk = "guess" },
	} {
		body := newProxyRequest(t, change)
		got := answer(t, do(h, http.MethodPost, pluginPath+"?version=0.1.0&op=NewProxy", body))
		if len(got) != 3 || got["reject"] != true || got["reject_reason"] != rejectReason {
			t.Errorf("%s: answer = %v, want reject true with the general reason", name, got)
		}
	}
}

func TestHandlerRefusesEveryProxyWithoutAPolicy(t *testing.T) {
	h, log := newTestHandler(t, nil)
	got := answer(t, do(h, http.MethodPost, pluginPath+"?op=NewProxy", fixtureRequest(t)))
	if got["reject"] != true || got["reject_reason"] != rejectReason {
		t.Errorf("answer = %v, want reject true", got)
	}
	if !strings.Contains(log.String(), "level=ERROR msg=\"policy unavailable") {
		t.Errorf("log = %q, want an error about the policy", log)
	}
}

func TestHandlerRefusesOtherRequests(t *testing.T) {
	h, _ := newTestHandler(t, fixturePolicy(t))
	login := strings.Replace(string(fixtureRequest(t)), `"op": "NewProxy"`, `"op": "Login"`, 1)
	tooLarge := `{"op": "NewProxy", "content": {"proxy_name": "` + strings.Repeat("a", MaxBody) + `"}}`
	cases := []struct {
		name, method, target, body string
		want                       int
	}{
		{"GET to the plugin", http.MethodGet, pluginPath + "?op=NewProxy", "", http.StatusMethodNotAllowed},
		{"another op in the query", http.MethodPost, pluginPath + "?op=Ping", string(fixtureRequest(t)), http.StatusBadRequest},
		{"Login in the query, NewProxy in the body", http.MethodPost, pluginPath + "?op=Login", string(fixtureRequest(t)), http.StatusBadRequest},
		{"no op in the query", http.MethodPost, pluginPath, string(fixtureRequest(t)), http.StatusBadRequest},
		{"another op in the body", http.MethodPost, pluginPath + "?op=NewProxy", login, http.StatusBadRequest},
		{"no JSON", http.MethodPost, pluginPath + "?op=NewProxy", "op=NewProxy", http.StatusBadRequest},
		{"an empty body", http.MethodPost, pluginPath + "?op=NewProxy", "", http.StatusBadRequest},
		{"a body too large", http.MethodPost, pluginPath + "?op=NewProxy", tooLarge, http.StatusRequestEntityTooLarge},
		{"POST to the health path", http.MethodPost, HealthPath, "", http.StatusMethodNotAllowed},
		{"another path", http.MethodPost, "/handler/x?op=NewProxy", string(fixtureRequest(t)), http.StatusNotFound},
	}
	for _, c := range cases {
		rec := do(h, c.method, c.target, []byte(c.body))
		if rec.Code != c.want {
			t.Errorf("%s: status %d, want %d", c.name, rec.Code, c.want)
		}
		if strings.Contains(rec.Body.String(), `"reject"`) {
			t.Errorf("%s: answered as the plugin: %s", c.name, rec.Body)
		}
	}
	if allow := do(h, http.MethodGet, pluginPath, nil).Header().Get("Allow"); allow != http.MethodPost {
		t.Errorf("GET to the plugin: Allow %q, want POST", allow)
	}
}

func TestHandlerServesTheHealthPath(t *testing.T) {
	h, _ := newTestHandler(t, nil)
	rec := do(h, http.MethodGet, HealthPath, nil)
	if rec.Code != http.StatusOK || rec.Body.String() != "ok\n" {
		t.Errorf("GET %s = %d %q, want 200 ok", HealthPath, rec.Code, rec.Body)
	}
}

func TestHandlerLogsTheDecisionWithoutSecrets(t *testing.T) {
	h, log := newTestHandler(t, fixturePolicy(t))
	lb := func(np *NewProxy) {
		np.ProxyName, np.ProxyType = serverA+".t-lb", "https"
		np.CustomDomains, np.SubDomain = []string{"lb.example"}, "lb"
		np.Group, np.GroupKey = "web", groupKey
		np.Sk, np.AllowUsers = "", nil
	}
	wrongKey := func(np *NewProxy) {
		lb(np)
		np.Metas[KeyMeta] = keyB
	}
	for _, body := range [][]byte{newProxyRequest(t, lb), newProxyRequest(t, wrongKey)} {
		do(h, http.MethodPost, pluginPath+"?op=NewProxy", body)
	}
	text := log.String()
	for _, want := range []string{
		`level=INFO msg="proxy admitted" user=` + serverA + ` proxy=` + serverA + `.t-lb`,
		`level=WARN msg="proxy refused" user=` + serverA + ` proxy=` + serverA + `.t-lb reason="wrong key"`,
	} {
		if !strings.Contains(text, want) {
			t.Errorf("log lacks %q:\n%s", want, text)
		}
	}
	for _, secret := range []string{keyA, keyB, groupKey, "tunnel-secret-placeholder", "ops-admin"} {
		if strings.Contains(text, secret) {
			t.Errorf("log holds %q:\n%s", secret, text)
		}
	}
}

func TestCheckListen(t *testing.T) {
	for _, addr := range []string{"127.0.0.1:7480", "127.0.0.2:7480", "[::1]:7480"} {
		if err := CheckListen(addr); err != nil {
			t.Errorf("CheckListen(%q) = %v, want nil", addr, err)
		}
	}
	for _, addr := range []string{
		"0.0.0.0:7480", "[::]:7480", ":7480", "localhost:7480", "192.0.2.1:7480", "127.0.0.1", "",
	} {
		if err := CheckListen(addr); err == nil {
			t.Errorf("CheckListen(%q) = nil, want an error", addr)
		}
	}
}

// serve runs Serve with the fixture policy and short timeouts on a loopback port until
// the test ends, and returns its address.
func serve(t *testing.T, timeouts Timeouts) string {
	t.Helper()
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	h, _ := newTestHandler(t, fixturePolicy(t))
	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan error, 1)
	go func() { done <- Serve(ctx, ln, h, timeouts) }()
	t.Cleanup(func() {
		cancel()
		if err := <-done; err != nil {
			t.Errorf("Serve = %v", err)
		}
	})
	return ln.Addr().String()
}

// closedWithin sends data on a new connection and fails unless the server closes the
// connection within limit.
func closedWithin(t *testing.T, addr, data string, limit time.Duration) {
	t.Helper()
	conn, err := net.Dial("tcp", addr)
	if err != nil {
		t.Fatal(err)
	}
	defer conn.Close()
	if _, err := io.WriteString(conn, data); err != nil {
		t.Fatal(err)
	}
	if err := conn.SetReadDeadline(time.Now().Add(limit)); err != nil {
		t.Fatal(err)
	}
	if _, err := io.Copy(io.Discard, conn); err != nil {
		var ne net.Error
		if errors.As(err, &ne) && ne.Timeout() {
			t.Errorf("the server kept the connection open past %s", limit)
		}
	}
}

func TestServeClosesSlowClients(t *testing.T) {
	// Each case shortens only the timeout it proves; the others stay past limit, so
	// http.Server's fallbacks between them cannot stand in.
	short, long, limit := 100*time.Millisecond, 10*time.Second, 3*time.Second
	only := func(set func(*Timeouts)) Timeouts {
		to := Timeouts{ReadHeader: long, Read: long, Write: long, Idle: long}
		set(&to)
		return to
	}

	t.Run("headers never end", func(t *testing.T) {
		addr := serve(t, only(func(to *Timeouts) { to.ReadHeader = short }))
		closedWithin(t, addr, "POST "+pluginPath+"?op=NewProxy HTTP/1.1\r\nHost: frps\r\n", limit)
	})
	t.Run("the body stalls", func(t *testing.T) {
		addr := serve(t, only(func(to *Timeouts) { to.Read = short }))
		closedWithin(t, addr, "POST "+pluginPath+"?op=NewProxy HTTP/1.1\r\nHost: frps\r\n"+
			"Content-Type: application/json\r\nContent-Length: 1000\r\n\r\n{\"op\": ", limit)
	})
	t.Run("an idle connection", func(t *testing.T) {
		addr := serve(t, only(func(to *Timeouts) { to.Idle = short }))
		conn, err := net.Dial("tcp", addr)
		if err != nil {
			t.Fatal(err)
		}
		defer conn.Close()
		if _, err := io.WriteString(conn, "GET "+HealthPath+" HTTP/1.1\r\nHost: frps\r\n\r\n"); err != nil {
			t.Fatal(err)
		}
		if err := conn.SetReadDeadline(time.Now().Add(limit)); err != nil {
			t.Fatal(err)
		}
		r := bufio.NewReader(conn)
		resp, err := http.ReadResponse(r, nil)
		if err != nil {
			t.Fatal(err)
		}
		_ = resp.Body.Close()
		if resp.StatusCode != http.StatusOK {
			t.Fatalf("GET %s = %d", HealthPath, resp.StatusCode)
		}
		if _, err := io.Copy(io.Discard, r); err != nil {
			t.Errorf("the server kept the idle connection open: %v", err)
		}
	})
}

func TestServeAnswersOverTCP(t *testing.T) {
	addr := serve(t, DefaultTimeouts)
	client := &http.Client{Timeout: 10 * time.Second}
	defer client.CloseIdleConnections()
	resp, err := client.Post("http://"+addr+pluginPath+"?version=0.1.0&op=NewProxy", "application/json",
		bytes.NewReader(fixtureRequest(t)))
	if err != nil {
		t.Fatal(err)
	}
	defer resp.Body.Close()
	var got response
	if err := json.NewDecoder(resp.Body).Decode(&got); err != nil {
		t.Fatal(err)
	}
	if resp.StatusCode != http.StatusOK || got.Reject || got.Unchange || got.Content == nil {
		t.Errorf("answer = %d %+v, want 200 admitting the proxy", resp.StatusCode, got)
	}
}

func TestServeStopsWithTheContext(t *testing.T) {
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	h, _ := newTestHandler(t, nil)
	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan error, 1)
	go func() { done <- Serve(ctx, ln, h, DefaultTimeouts) }()
	cancel()
	select {
	case err := <-done:
		if err != nil {
			t.Errorf("Serve = %v, want nil", err)
		}
	case <-time.After(5 * time.Second):
		t.Fatal("Serve did not stop with the context")
	}
	if conn, err := net.Dial("tcp", ln.Addr().String()); err == nil {
		conn.Close()
		t.Error("the listener still accepts after the stop")
	}
}

func TestServeReturnsTheListenersError(t *testing.T) {
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	ln.Close()
	h, _ := newTestHandler(t, nil)
	if err := Serve(context.Background(), ln, h, DefaultTimeouts); err == nil {
		t.Error("Serve on a closed listener = nil, want an error")
	}
}

// loginRequest is frps' Login request (frp v0.72.0 pkg/plugin/server LoginContent) of user
// with key in its metadatas and the run ID runID.
func loginRequest(t *testing.T, user, key, runID string) []byte {
	t.Helper()
	content := map[string]any{
		"version": "0.72.0", "hostname": "host-01", "os": "linux", "arch": "amd64",
		"user": user, "privilege_key": "privilege-key-placeholder", "timestamp": json.Number("1762934400"),
		"run_id": runID, "metas": map[string]any{KeyMeta: key, "owner": "ops"}, "pool_count": json.Number("1"),
		"client_spec": map[string]any{}, "client_address": "192.0.2.10:51000",
	}
	data, err := json.Marshal(map[string]any{"version": "0.1.0", "op": "Login", "content": content})
	if err != nil {
		t.Fatal(err)
	}
	return data
}

// loginAnswer posts a login and returns the answer and its content.
func loginAnswer(t *testing.T, h http.Handler, body []byte) (map[string]any, map[string]any) {
	t.Helper()
	rec := do(h, http.MethodPost, pluginPath+"?version=0.1.0&op=Login", body)
	got := answer(t, rec)
	content, _ := got["content"].(map[string]any)
	if strings.Contains(rec.Body.String(), keyA) || strings.Contains(rec.Body.String(), keyB) {
		t.Errorf("answer holds a host's key: %s", rec.Body)
	}
	return got, content
}

func TestHandlerAdmitsALoginBoundToItsUser(t *testing.T) {
	h, _ := newTestHandler(t, fixturePolicy(t))
	body := loginRequest(t, serverA, keyA, "")
	got, content := loginAnswer(t, h, body)
	if len(got) != 3 || got["reject"] != false || got["unchange"] != false {
		t.Fatalf("answer = %v, want reject false, unchange false and the content", got)
	}
	runID, _ := content["run_id"].(string)
	if !strings.HasPrefix(runID, runIDPrefix(serverA)) || len(runID) != 49 {
		t.Fatalf("run_id = %q, want one under A's prefix", runID)
	}
	var want struct {
		Content map[string]any `json:"content"`
	}
	if err := json.Unmarshal(body, &want); err != nil {
		t.Fatal(err)
	}
	delete(want.Content["metas"].(map[string]any), KeyMeta)
	want.Content["run_id"] = runID
	if !reflect.DeepEqual(content, want.Content) {
		t.Errorf("content = %v, want the request's content without the key and with the run ID: %v", content, want.Content)
	}

	// frpc sends the run ID back on its next login: it stays. A run ID of another user or one
	// frps made itself is replaced, so a login never names another host's control.
	if _, again := loginAnswer(t, h, loginRequest(t, serverA, keyA, runID)); again["run_id"] != runID {
		t.Errorf("own run ID: run_id = %v, want %q", again["run_id"], runID)
	}
	_, ofB := loginAnswer(t, h, loginRequest(t, serverB, keyB, ""))
	for _, foreign := range []string{ofB["run_id"].(string), "0123456789abcdef"} {
		_, c := loginAnswer(t, h, loginRequest(t, serverA, keyA, foreign))
		if c["run_id"] == foreign || !strings.HasPrefix(c["run_id"].(string), runIDPrefix(serverA)) {
			t.Errorf("run ID %q: run_id = %v, want a fresh one under A's prefix", foreign, c["run_id"])
		}
	}
}

// The desktop's STCP visitor logs in as an AdminHelper user, no host: admitted without a key,
// with a run ID under its own prefix, so it cannot replace a host's control either.
func TestHandlerAdmitsAVisitorLoginBoundToItsUser(t *testing.T) {
	h, _ := newTestHandler(t, fixturePolicy(t))
	_, ofA := loginAnswer(t, h, loginRequest(t, serverA, keyA, ""))
	got, content := loginAnswer(t, h, loginRequest(t, "ops-admin", "", ofA["run_id"].(string)))
	if got["reject"] != false {
		t.Fatalf("answer = %v, want reject false", got)
	}
	runID, _ := content["run_id"].(string)
	if !strings.HasPrefix(runID, runIDPrefix("ops-admin")) || runID == ofA["run_id"] {
		t.Errorf("run_id = %q, want a fresh one under the visitor's prefix", runID)
	}
}

func TestHandlerRefusesALoginWithoutTheHostsKey(t *testing.T) {
	h, _ := newTestHandler(t, fixturePolicy(t))
	for name, body := range map[string][]byte{
		"another host's key": loginRequest(t, serverA, keyB, ""),
		"no key":             loginRequest(t, serverA, "", ""),
		"no user":            loginRequest(t, "", keyA, ""),
	} {
		got, _ := loginAnswer(t, h, body)
		if len(got) != 3 || got["reject"] != true || got["reject_reason"] != loginRejectReason {
			t.Errorf("%s: answer = %v, want reject true with the general reason", name, got)
		}
	}
	h, _ = newTestHandler(t, nil)
	if got, _ := loginAnswer(t, h, loginRequest(t, serverA, keyA, "")); got["reject"] != true {
		t.Errorf("without a policy: answer = %v, want reject true", got)
	}
}

func TestHandlerLogsTheLoginWithoutSecrets(t *testing.T) {
	h, log := newTestHandler(t, fixturePolicy(t))
	_, content := loginAnswer(t, h, loginRequest(t, serverA, keyA, ""))
	loginAnswer(t, h, loginRequest(t, serverA, keyB, ""))
	text := log.String()
	for _, want := range []string{
		`level=INFO msg="login admitted" user=` + serverA,
		`level=WARN msg="login refused" user=` + serverA + ` reason="wrong key"`,
	} {
		if !strings.Contains(text, want) {
			t.Errorf("log lacks %q:\n%s", want, text)
		}
	}
	for _, secret := range []string{keyA, keyB, "privilege-key-placeholder", content["run_id"].(string)} {
		if strings.Contains(text, secret) {
			t.Errorf("log holds %q:\n%s", secret, text)
		}
	}
}
