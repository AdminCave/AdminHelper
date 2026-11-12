// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package frpspolicy

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"log/slog"
	"net"
	"net/http"
	"time"
)

// MaxBody bounds a request body; a NewProxy content is a few hundred bytes.
const MaxBody = 64 << 10

// HealthPath answers GET with 200 while the plugin serves.
const HealthPath = "/healthz"

// rejectReason is all frpc learns about a refused proxy.
const rejectReason = "proxy not allowed by the server's tunnel policy"

// Timeouts of the plugin's HTTP server. frps calls the plugin without a timeout of its
// own and waits for it in the read loop of the client's connection (frp v0.72.0), so the
// plugin must not let a request hang.
type Timeouts struct {
	ReadHeader, Read, Write, Idle time.Duration
}

// DefaultTimeouts are the plugin's timeouts in frps' container.
var DefaultTimeouts = Timeouts{
	ReadHeader: 2 * time.Second,
	Read:       5 * time.Second,
	Write:      5 * time.Second,
	Idle:       60 * time.Second,
}

type request struct {
	Op      string          `json:"op"`
	Content json.RawMessage `json:"content"`
}

type response struct {
	Reject       bool           `json:"reject"`
	RejectReason string         `json:"reject_reason,omitempty"`
	Unchange     bool           `json:"unchange"`
	Content      map[string]any `json:"content,omitempty"`
}

// NewHandler serves frps' plugin requests for NewProxy at path and GET HealthPath.
// A refusal leaves the content unchanged; an admitted proxy comes back whole without the
// host's key (WithoutKey).
func NewHandler(src *Source, path string, log *slog.Logger) http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc(HealthPath, func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodGet {
			w.Header().Set("Allow", http.MethodGet)
			http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
			return
		}
		_, _ = w.Write([]byte("ok\n"))
	})
	mux.HandleFunc(path, func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			w.Header().Set("Allow", http.MethodPost)
			http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
			return
		}
		if op := r.URL.Query().Get("op"); op != "NewProxy" {
			http.Error(w, "only the op NewProxy", http.StatusBadRequest)
			return
		}
		var req request
		if err := json.NewDecoder(http.MaxBytesReader(w, r.Body, MaxBody)).Decode(&req); err != nil {
			var tooLarge *http.MaxBytesError
			if errors.As(err, &tooLarge) {
				http.Error(w, "request too large", http.StatusRequestEntityTooLarge)
				return
			}
			http.Error(w, "no NewProxy request", http.StatusBadRequest)
			return
		}
		if req.Op != "NewProxy" {
			http.Error(w, "only the op NewProxy", http.StatusBadRequest)
			return
		}
		// The content twice: the fields the decision reads, and all of it with its numbers
		// exact for the answer, since frps decodes the answer into a fresh NewProxy.
		np := &NewProxy{}
		var content map[string]any
		dec := json.NewDecoder(bytes.NewReader(req.Content))
		dec.UseNumber()
		if json.Unmarshal(req.Content, np) != nil || dec.Decode(&content) != nil || content == nil {
			http.Error(w, "no NewProxy request", http.StatusBadRequest)
			return
		}
		reason := "no policy"
		policy, err := src.Current()
		if err != nil {
			log.Error("policy unavailable, refusing every proxy", "err", err)
		} else {
			reason = policy.Decide(np)
		}
		// Only the user and the proxy name: the request also carries the host's key, the
		// stcp secret and a group key.
		if reason == "" {
			log.Info("proxy admitted", "user", np.User.User, "proxy", np.ProxyName)
		} else {
			log.Warn("proxy refused", "user", np.User.User, "proxy", np.ProxyName, "reason", reason)
		}
		resp := response{Reject: reason != "", Unchange: true}
		if resp.Reject {
			resp.RejectReason = rejectReason
		} else {
			resp.Unchange, resp.Content = false, WithoutKey(content)
		}
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(resp)
	})
	return mux
}

// CheckListen accepts only an address on a loopback IP: frps reaches the plugin in its
// own container, nothing else needs to.
func CheckListen(addr string) error {
	host, _, err := net.SplitHostPort(addr)
	if err != nil {
		return err
	}
	ip := net.ParseIP(host)
	if ip == nil || !ip.IsLoopback() {
		return fmt.Errorf("listen address %q is no loopback IP", addr)
	}
	return nil
}

// Serve serves h on ln with the timeouts until ctx ends, then shuts down.
func Serve(ctx context.Context, ln net.Listener, h http.Handler, t Timeouts) error {
	srv := &http.Server{
		Handler:           h,
		ReadHeaderTimeout: t.ReadHeader,
		ReadTimeout:       t.Read,
		WriteTimeout:      t.Write,
		IdleTimeout:       t.Idle,
		MaxHeaderBytes:    16 << 10,
	}
	done := make(chan error, 1)
	go func() { done <- srv.Serve(ln) }()
	select {
	case err := <-done:
		return err
	case <-ctx.Done():
	}
	shutdown, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()
	if err := srv.Shutdown(shutdown); err != nil {
		return err
	}
	if err := <-done; !errors.Is(err, http.ErrServerClosed) {
		return err
	}
	return nil
}
