// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Package frpspolicy is frps' server plugin for the ops NewProxy and Login: it admits a proxy
// only if the policy file the AdminHelper server writes (apps/server/app/modules/frp/policy.py)
// holds it for the host that registers it, with the fields the server's frpc.toml
// generator writes for that tunnel, and a login only for a host of the policy with its key.
// Everything else is refused, and so is everything while the policy file is missing or
// broken. An admitted proxy or login goes on without the host's key, so frps does not keep it.
package frpspolicy

import (
	"bytes"
	"crypto/rand"
	"crypto/sha256"
	"crypto/subtle"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"slices"
	"strings"
	"sync"
)

// Version is the policy format this plugin reads.
const Version = 2

// KeyMeta is the metadatas field of a proxy and of a login that carries the host's key
// (proxy_key.py).
const KeyMeta = "ahProxyKey"

// MaxPolicySize bounds the policy file; a few hundred bytes per tunnel leave room for
// tens of thousands.
const MaxPolicySize = 8 << 20

// Proxy is one tunnel of a host, with the fields the generator writes for it.
type Proxy struct {
	Type          string   `json:"type"`
	CustomDomains []string `json:"customDomains"`
	Subdomain     string   `json:"subdomain"`
	Group         string   `json:"group"`
	// SHA-256 of loadBalancer.groupKey as hex, "" without one.
	GroupKeyHash string `json:"groupKeyHash"`
	// allowUsers of an stcp tunnel, compared as a set; empty for https.
	AllowUsers []string `json:"allowUsers"`
	// SHA-256 of secretKey as hex, "" without one.
	SkHash string `json:"skHash"`
}

// Server is one host: the SHA-256 of its key as hex and its tunnels by ID.
type Server struct {
	KeyHash string           `json:"keyHash"`
	Proxies map[string]Proxy `json:"proxies"`
}

// Policy is the content of the policy file: the hosts by server ID.
type Policy struct {
	Version int               `json:"version"`
	Servers map[string]Server `json:"servers"`
}

// NewProxy holds the fields of frps' NewProxy content (frp v0.72.0,
// pkg/plugin/server/types.go NewProxyContent) the decision reads.
type NewProxy struct {
	User struct {
		User string `json:"user"`
	} `json:"user"`
	ProxyName     string            `json:"proxy_name"`
	ProxyType     string            `json:"proxy_type"`
	Group         string            `json:"group"`
	GroupKey      string            `json:"group_key"`
	Metas         map[string]string `json:"metas"`
	RemotePort    int               `json:"remote_port"`
	CustomDomains []string          `json:"custom_domains"`
	SubDomain     string            `json:"subdomain"`
	Sk            string            `json:"sk"`
	AllowUsers    []string          `json:"allow_users"`
}

// Login holds the fields of frps' Login content (frp v0.72.0, pkg/msg/msg.go Login) the
// decision reads.
type Login struct {
	User  string            `json:"user"`
	RunID string            `json:"run_id"`
	Metas map[string]string `json:"metas"`
}

// Parse reads a policy and holds it to the format: version 2, no unknown field, hashes
// as 64 lowercase hex digits, the tunnel types the server writes.
func Parse(data []byte) (*Policy, error) {
	dec := json.NewDecoder(bytes.NewReader(data))
	dec.DisallowUnknownFields()
	var p Policy
	if err := dec.Decode(&p); err != nil {
		return nil, fmt.Errorf("policy: %w", err)
	}
	if _, err := dec.Token(); err != io.EOF {
		return nil, errors.New("policy: data after the JSON object")
	}
	if p.Version != Version {
		return nil, fmt.Errorf("policy: version %d, want %d", p.Version, Version)
	}
	if p.Servers == nil {
		return nil, errors.New("policy: no servers")
	}
	for id, srv := range p.Servers {
		if id == "" {
			return nil, errors.New("policy: a server without an ID")
		}
		if !isHash(srv.KeyHash) {
			return nil, fmt.Errorf("policy: server %q: keyHash is no SHA-256 in hex", id)
		}
		for name, proxy := range srv.Proxies {
			if name == "" {
				return nil, fmt.Errorf("policy: server %q: a proxy without an ID", id)
			}
			if proxy.Type != "stcp" && proxy.Type != "https" {
				return nil, fmt.Errorf("policy: proxy %q: type %q", name, proxy.Type)
			}
			if proxy.GroupKeyHash != "" && !isHash(proxy.GroupKeyHash) {
				return nil, fmt.Errorf("policy: proxy %q: groupKeyHash is no SHA-256 in hex", name)
			}
			if proxy.SkHash != "" && !isHash(proxy.SkHash) {
				return nil, fmt.Errorf("policy: proxy %q: skHash is no SHA-256 in hex", name)
			}
		}
	}
	return &p, nil
}

func isHash(s string) bool {
	return len(s) == 2*sha256.Size && isHex(s)
}

// isHex reports whether s holds lowercase hex digits only.
func isHex(s string) bool {
	for _, c := range s {
		if !('0' <= c && c <= '9' || 'a' <= c && c <= 'f') {
			return false
		}
	}
	return true
}

// hashEqual compares the SHA-256 of secret with wantHex in constant time.
func hashEqual(secret, wantHex string) bool {
	want, err := hex.DecodeString(wantHex)
	if err != nil || len(want) != sha256.Size {
		return false
	}
	sum := sha256.Sum256([]byte(secret))
	return subtle.ConstantTimeCompare(sum[:], want) == 1
}

// host returns the user's entry if the metas carry its key, otherwise why not.
func (p *Policy) host(user string, metas map[string]string) (Server, string) {
	srv, ok := p.Servers[user]
	if user == "" || !ok {
		return Server{}, "unknown user"
	}
	key, ok := metas[KeyMeta]
	if !ok || key == "" {
		return Server{}, "no key"
	}
	if !hashEqual(key, srv.KeyHash) {
		return Server{}, "wrong key"
	}
	return srv, ""
}

// DecideLogin returns "" if the policy admits the login: a host of the policy only with its key
// in the login's metadatas. Another user is no host (the desktop's STCP visitor logs in as an
// AdminHelper user) and gets no proxy through Decide; BoundRunID keeps it off the hosts'
// controls. Otherwise why not, for the plugin's log only.
func (p *Policy) DecideLogin(l *Login) string {
	if l.User == "" {
		return "no user"
	}
	if _, isHost := p.Servers[l.User]; !isHost {
		return ""
	}
	_, reason := p.host(l.User, l.Metas)
	return reason
}

// Decide returns "" if the policy admits the proxy, otherwise why not. The reason goes to
// the plugin's log only; it names no value from the request.
func (p *Policy) Decide(np *NewProxy) string {
	user := np.User.User
	srv, reason := p.host(user, np.Metas)
	if reason != "" {
		return reason
	}
	// frpc registers a proxy as "<user>.<name>"; the name is the tunnel ID.
	tunnel, ok := strings.CutPrefix(np.ProxyName, user+".")
	if !ok {
		return "name without the user prefix"
	}
	want, ok := srv.Proxies[tunnel]
	if !ok {
		return "no tunnel of this user"
	}
	switch {
	case np.ProxyType != want.Type:
		return "other type"
	case !slices.Equal(np.CustomDomains, want.CustomDomains):
		return "other custom domains"
	case np.SubDomain != want.Subdomain:
		return "other subdomain"
	case np.Group != want.Group:
		return "other group"
	case want.GroupKeyHash == "" && np.GroupKey != "":
		return "other group key"
	case want.GroupKeyHash != "" && !hashEqual(np.GroupKey, want.GroupKeyHash):
		return "other group key"
	case !sameSet(np.AllowUsers, want.AllowUsers):
		return "other allowed users"
	case want.SkHash == "" && np.Sk != "":
		return "other secret key"
	case want.SkHash != "" && !hashEqual(np.Sk, want.SkHash):
		return "other secret key"
	case np.RemotePort != 0:
		return "remote port"
	}
	return ""
}

// runIDRandom is the number of random bytes of a run ID BoundRunID hands out.
const runIDRandom = 16

// runIDPrefix is the part of a run ID that names its user: frps keys a client's control by
// its run ID, and a login naming the run ID of a running control replaces that control.
func runIDPrefix(user string) string {
	sum := sha256.Sum256([]byte("frps-run-id:" + user))
	return hex.EncodeToString(sum[:8]) + "-"
}

// BoundRunID returns the run ID an admitted login of user goes on with: runID if it lies under
// the user's prefix, as frpc sends back the one it got on its last login, otherwise a fresh one
// there. So a login can name only a control of its own user. frps takes at most 64 bytes;
// these are 49.
func BoundRunID(user, runID string) (string, error) {
	prefix := runIDPrefix(user)
	if rest, ok := strings.CutPrefix(runID, prefix); ok && len(rest) == 2*runIDRandom && isHex(rest) {
		return runID, nil
	}
	b := make([]byte, runIDRandom)
	if _, err := rand.Read(b); err != nil {
		return "", err
	}
	return prefix + hex.EncodeToString(b), nil
}

// sameSet reports whether a and b hold the same strings, regardless of order and repeats.
func sameSet(a, b []string) bool {
	in := func(s string, list []string) bool { return slices.Contains(list, s) }
	for _, s := range a {
		if !in(s, b) {
			return false
		}
	}
	for _, s := range b {
		if !in(s, a) {
			return false
		}
	}
	return true
}

// WithoutKey returns content, frps' NewProxy or Login content decoded with UseNumber, without
// the host's key in its metas: frps takes the answer's content in place of its own, keeps it
// for the proxy or the client and shows proxy metas on its dashboard. Everything else stays
// as sent.
func WithoutKey(content map[string]any) map[string]any {
	out := make(map[string]any, len(content))
	for k, v := range content {
		out[k] = v
	}
	if metas, ok := content["metas"].(map[string]any); ok {
		kept := make(map[string]any, len(metas))
		for k, v := range metas {
			if k != KeyMeta {
				kept[k] = v
			}
		}
		out["metas"] = kept
	}
	return out
}

// Source reads the policy file and reads it again only when it changed: another file at
// the path (the server replaces it atomically), another size or another mtime.
type Source struct {
	path string

	mu     sync.Mutex
	info   os.FileInfo // of the file policy and err come from; nil to read again
	policy *Policy
	err    error
}

// NewSource returns a Source for the policy file at path.
func NewSource(path string) *Source {
	return &Source{path: path}
}

// Current returns the policy the file holds now, or why there is none: the file is
// missing, no regular file (a link counts as none), larger than MaxPolicySize or broken.
func (s *Source) Current() (*Policy, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	fi, err := os.Lstat(s.path)
	if err != nil {
		s.info = nil
		return nil, err
	}
	if !fi.Mode().IsRegular() {
		s.info = nil
		return nil, fmt.Errorf("policy: %s is no regular file", s.path)
	}
	if s.info != nil && os.SameFile(s.info, fi) && s.info.Size() == fi.Size() &&
		s.info.ModTime().Equal(fi.ModTime()) {
		return s.policy, s.err
	}
	info, policy, err := read(s.path, fi)
	s.info, s.policy, s.err = info, policy, err
	return policy, err
}

// read opens the file Lstat found and parses it. The returned info is nil when the file
// changed in between, so the next call reads again.
func read(path string, lstat os.FileInfo) (os.FileInfo, *Policy, error) {
	f, err := os.Open(path)
	if err != nil {
		return nil, nil, err
	}
	defer f.Close()
	info, err := f.Stat()
	if err != nil {
		return nil, nil, err
	}
	if !os.SameFile(lstat, info) {
		return nil, nil, fmt.Errorf("policy: %s changed while it was opened", path)
	}
	data, err := io.ReadAll(io.LimitReader(f, MaxPolicySize+1))
	if err != nil {
		return nil, nil, err
	}
	if len(data) > MaxPolicySize {
		return info, nil, fmt.Errorf("policy: %s is larger than %d bytes", path, MaxPolicySize)
	}
	policy, err := Parse(data)
	return info, policy, err
}
