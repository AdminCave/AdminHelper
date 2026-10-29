// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Package provision implements the server-centric provisioning flow.
//
// As of v0.23.0, provisioning is no longer coupled to FRP. A single
// `adminhelper-agent provision` call:
//   - secures the data root (config.EnsureDataDir(config.MonitorDir())) first, so a
//     root that cannot be secured leaves the token unspent,
//   - redeems the provision token via POST /api/servers/{id}/provision/activate,
//   - writes the server API key to the FRP sync config (always: frpc.WriteSyncConfig,
//     so a tunnel created later reaches the host with the next sync),
//   - with an available monitor service: monitor.Init with the returned key,
//   - with an FRP config on the server: frpc.Apply with the returned bundle (without an
//     active tunnel its text has no proxies and frpc stops); without an FRP config
//     frpc.ApplyWithoutBundle (stops the frpc of an earlier provisioning),
//   - at the end, always: service.EnableTimer (the agent timer, also without monitor and FRP).
//
// This way a single command on the target server suffices, regardless of which
// components (FRP / monitor / server-read only) are configured.
package provision

import (
	"context"
	"crypto/sha256"
	"encoding/json"
	"encoding/pem"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/url"
	"os"
	"strconv"
	"strings"
	"time"

	"adminhelper-agent/internal/config"
	"adminhelper-agent/internal/enroll"
	"adminhelper-agent/internal/frpc"
	"adminhelper-agent/internal/httpclient"
	"adminhelper-agent/internal/monitor"
	"adminhelper-agent/internal/service"
)

type frpBundle struct {
	Config string `json:"config"`
}

// enrollmentInfo is the one-time grant the server returns so the agent can fetch
// its mTLS client cert from the ca-issuer (A4). The host is not carried: the
// agent reuses the server URL it already provisioned against + this port.
type enrollmentInfo struct {
	Token      string `json:"token"`
	SubjectID  string `json:"subjectId"`
	Scope      string `json:"scope"`
	EnrollPort int    `json:"enrollPort"`
}

type activateResponse struct {
	ServerName    string          `json:"serverName"`
	APIKey        string          `json:"apiKey"`
	MonitorAPIKey *string         `json:"monitorApiKey"`
	MonitorURL    *string         `json:"monitorUrl"`
	FRP           *frpBundle      `json:"frp"`
	Enrollment    *enrollmentInfo `json:"enrollment"`
}

// activatePort is the gateway's certless enroll plane, which the activate call
// goes to; tests point it at an httptest server.
var activatePort = 8444

// applyWithoutBundle is frpc.ApplyWithoutBundle; tests swap it, the real one runs systemctl.
var applyWithoutBundle = frpc.ApplyWithoutBundle

// enableTimer is service.EnableTimer; tests swap it, the real one runs systemctl.
var enableTimer = service.EnableTimer

// Run redeems a provision token against the server endpoint and
// installs the returned bundles in a platform-appropriate way. A non-empty
// caFP (SHA-256 of the internal CA, handed over out-of-band via the desktop's
// provisioning tab) upgrades the first contact from trust-on-first-use to a
// VERIFIED handshake: the token never leaves the host unless the presented
// chain proves the pinned CA and its leaf names the host of adminHelperURL
// (httpclient.NewCAFingerprint).
func Run(adminHelperURL, token, serverID, cacert string, insecure bool, caFP string) error {
	adminHelperURL = strings.TrimRight(adminHelperURL, "/")
	if adminHelperURL == "" || token == "" || serverID == "" {
		return fmt.Errorf("--url, --token und --server-id sind erforderlich")
	}
	if err := config.RequireHTTPS(adminHelperURL); err != nil {
		return err
	}
	// One trust source per call, the same rule for all three: --ca-fp verifies
	// against a CA fingerprint, --cacert against a CA file, --insecure pins blind.
	// Any combination would silently weaken the stronger one (beside --insecure,
	// httpclient.New skips the check even with a CA file), so refuse them instead
	// of guessing.
	if caFP != "" && (cacert != "" || insecure) {
		return fmt.Errorf("--ca-fp cannot be combined with --cacert/--insecure")
	}
	if cacert != "" && insecure {
		return fmt.Errorf("--cacert cannot be combined with --insecure: --cacert already verifies the server")
	}
	var fingerprint *[sha256.Size]byte
	if caFP != "" {
		fp, err := httpclient.ParseCAFingerprint(caFP)
		if err != nil {
			return err
		}
		fingerprint = &fp
	}

	// The token can be redeemed only once: secure the data root (on Windows with the
	// tree below it) before sending it, so a root that cannot be secured stops the
	// provisioning while the token is still unspent.
	dataRoot := config.MonitorDir()
	if err := config.EnsureDataDir(dataRoot); err != nil {
		return fmt.Errorf("secure the data directory %s: %w; the provision token was not redeemed", dataRoot, err)
	}

	resp, serverCertPEM, err := callActivate(adminHelperURL, token, serverID, cacert, insecure, fingerprint, activatePort)
	if err != nil {
		return err
	}
	if resp.APIKey == "" {
		return fmt.Errorf("kein API-Key in der Antwort erhalten")
	}

	fmt.Printf("Provisioning fuer Server %q gestartet.\n", resp.ServerName)

	var effectiveCacert string
	var effectiveInsecure bool
	cleanupPin := func() {}
	if fingerprint != nil {
		effectiveCacert, cleanupPin, err = pinVerifiedAnchor(serverCertPEM, *fingerprint)
	} else {
		effectiveCacert, effectiveInsecure, cleanupPin, err = pinIfBlindInsecure(cacert, insecure, serverCertPEM)
	}
	if err != nil {
		return err
	}
	defer cleanupPin()

	// 0. mTLS enrollment: fetch the agent's client cert from the ca-issuer with
	// the one-time token. Best-effort — during the permissive rollout (A4) the
	// agent still works via API key alone, so a failed enroll must not abort
	// provisioning. The TLS trust for this bootstrap call is the same one the
	// activate call used (TOFU-pinned gateway cert); the enroll response's chain
	// is then persisted as the permanent pinned root.
	if resp.Enrollment != nil && resp.Enrollment.Token != "" {
		if err := runEnrollment(adminHelperURL, resp.Enrollment, effectiveCacert, effectiveInsecure); err != nil {
			fmt.Printf("→ Enrollment uebersprungen (%v) — Agent nutzt vorerst nur den API-Key.\n", err)
		} else {
			fmt.Println("→ mTLS-Client-Zertifikat enrollt und gepinnt.")
		}
	}

	// 1. Monitor init only if the service returned a key. The agent owns the
	// host: it builds the monitoring base from the SAME server URL it just
	// provisioned against (already TLS-trusted) plus the server-declared path,
	// so the metrics push always hits the same host/cert — no reliance on the
	// server knowing its own public address. MonitorURL carries the relative
	// path (e.g. "/api/monitoring"); older/absolute values fall back to the
	// well-known path.
	if resp.MonitorAPIKey != nil && *resp.MonitorAPIKey != "" {
		monitorURL := monitorBaseURL(adminHelperURL, resp.MonitorURL)
		fmt.Println("→ Monitor-Agent wird eingerichtet...")
		if err := monitor.Init(monitor.InitParams{
			URL:      monitorURL,
			APIKey:   *resp.MonitorAPIKey,
			ServerID: serverID,
			TLS:      config.TLSOpts{CACert: effectiveCacert, Insecure: effectiveInsecure},
		}); err != nil {
			return fmt.Errorf("Monitor-Init fehlgeschlagen: %w", err)
		}
	} else {
		fmt.Println("→ Monitor-Service nicht konfiguriert oder nicht erreichbar — Monitor wird uebersprungen.")
	}

	// 2. The sync config always (Apply writes it along with frpc's config): without it the
	// API key is lost and a tunnel created later never reaches this host (R-0398). The
	// bundle is missing only without an FRP config (from an older server also without a
	// tunnel); a host without an active tunnel gets a text without proxies, on which
	// Apply stops frpc. Without a tunnel no frpc runs, also not one an earlier
	// provisioning set up.
	if resp.FRP != nil {
		fmt.Println("→ FRP-Client wird eingerichtet...")
		if err := frpc.Apply(frpc.ApplyParams{
			AdminHelperURL: adminHelperURL,
			ServerID:       serverID,
			APIKey:         resp.APIKey,
			FrpConfigB64:   resp.FRP.Config,
			TLS:            config.TLSOpts{CACert: effectiveCacert, Insecure: effectiveInsecure},
		}); err != nil {
			return fmt.Errorf("FRP-Apply fehlgeschlagen: %w", err)
		}
	} else {
		if err := frpc.WriteSyncConfig(frpc.SyncConfigParams{
			AdminHelperURL: adminHelperURL,
			ServerID:       serverID,
			APIKey:         resp.APIKey,
			TLS:            config.TLSOpts{CACert: effectiveCacert, Insecure: effectiveInsecure},
		}); err != nil {
			return fmt.Errorf("write the FRP sync config: %w", err)
		}
		if err := applyWithoutBundle(); err != nil {
			return fmt.Errorf("stop the frpc of an earlier provisioning: %w", err)
		}
		fmt.Println("→ Keine FRP-Tunnel fuer diesen Server konfiguriert — FRP wird uebersprungen.")
	}

	// 3. The timer runs the agent from now on, whatever the server configured, also without
	// monitor and tunnel (R-0641). A timer that cannot be enabled leaves the provisioning
	// standing: the token is spent.
	if err := enableTimer(); err != nil {
		fmt.Printf("→ Agent timer not enabled (%v) — enable it by hand; until then no run syncs or pushes.\n", err)
	}

	fmt.Println("OK: Provisioning abgeschlossen.")
	return nil
}

// pinVerifiedAnchor persists the --ca-fp-verified trust for the follow-up calls
// (enroll, monitor init, frpc apply): it extracts EXACTLY the fingerprint-matched
// certificate from the chain the (already handshake-verified) activate call saw
// and writes it as the pinned CA file. Only the anchor — pinning the whole
// presented chain would also anchor the rotating leaf, defeating the point of a
// CA pin. The chain is handshake-verified, so a missing match here is a bug,
// not an attack — still fail closed.
func pinVerifiedAnchor(serverCertPEM []byte, fp [sha256.Size]byte) (string, func(), error) {
	rest := serverCertPEM
	for {
		var block *pem.Block
		block, rest = pem.Decode(rest)
		if block == nil {
			return "", func() {}, fmt.Errorf("verified CA anchor not found in the presented chain")
		}
		if block.Type != "CERTIFICATE" || sha256.Sum256(block.Bytes) != fp {
			continue
		}
		pinnedPath, err := writePinnedCert(pem.EncodeToMemory(block))
		if err != nil {
			return "", func() {}, fmt.Errorf("pinning the verified CA anchor: %w", err)
		}
		fmt.Println("→ CA fingerprint verified — chain cryptographically checked, CA pinned as trust anchor.")
		return pinnedPath, func() { os.Remove(pinnedPath) }, nil
	}
}

// pinIfBlindInsecure turns a blind --insecure (no --cacert) into TOFU-pinned trust:
// it writes the cert the server presented on the activate call and returns that as
// the effective cacert with insecure=false, so the recurring loop verifies against
// it instead of persisting INSECURE=1 and leaking the API key every cycle. Without a
// presented cert there is nothing to pin, and it fails instead of handing insecure
// on: it never returns insecure=true. The returned cleanup removes the pinned file
// (a no-op when nothing was pinned); --insecure thus applies only to this one-off
// provisioning call.
func pinIfBlindInsecure(cacert string, insecure bool, serverCertPEM []byte) (string, bool, func(), error) {
	if !insecure || cacert != "" {
		return cacert, false, func() {}, nil
	}
	if len(serverCertPEM) == 0 {
		return "", false, func() {}, fmt.Errorf("--insecure: the server presented no certificate to pin; provision again with a new token and --ca-fp or --cacert")
	}
	pinnedPath, err := writePinnedCert(serverCertPEM)
	if err != nil {
		return "", false, func() {}, fmt.Errorf("Server-Zertifikat pinnen: %w", err)
	}
	fmt.Println("→ Server-Zertifikat gepinnt (TOFU) — --insecure gilt nur fuer diesen Aufruf.")
	// Print the pinned cert's fingerprint so the operator can verify it out-of-band
	// against the server's own cert hash: with --insecure at first contact, an on-path
	// attacker could otherwise pin its own cert as the permanent trust anchor (3.45).
	if block, _ := pem.Decode(serverCertPEM); block != nil {
		fp := sha256.Sum256(block.Bytes)
		fmt.Printf("  SHA-256-Fingerprint: %x\n", fp)
		fmt.Println("  Bitte gegen den im AdminHelper-Server angezeigten Fingerprint pruefen —")
		fmt.Println("  ohne Pruefung kann ein aktiver MITM im Erstkontakt den Trust-Anchor faelschen.")
	}
	return pinnedPath, false, func() { os.Remove(pinnedPath) }, nil
}

// monitorBaseURL derives the metrics-push base from the just-provisioned server URL
// plus the server-declared relative path (e.g. "/api/monitoring"); an absent or
// absolute MonitorURL falls back to the well-known path, so the push hits the same
// TLS-trusted host without the server knowing its own public address.
func monitorBaseURL(adminHelperURL string, monitorURL *string) string {
	path := "/api/monitoring"
	if monitorURL != nil && strings.HasPrefix(*monitorURL, "/") {
		path = *monitorURL
	}
	return adminHelperURL + path
}

// checkStorable and storeIdentity are enroll.CheckStorable and enroll.Store; tests swap
// them to make the identity directory give out.
var (
	checkStorable = enroll.CheckStorable
	storeIdentity = enroll.Store
)

// runEnrollment generates an on-device key + CSR and redeems the enrollment
// token at the gateway's enroll plane, persisting the issued identity.
func runEnrollment(adminHelperURL string, info *enrollmentInfo, cacert string, insecure bool) error {
	port := info.EnrollPort
	if port == 0 {
		port = 8444 // the gateway's default enroll plane
	}
	endpoint, err := enrollEndpoint(adminHelperURL, port)
	if err != nil {
		return fmt.Errorf("Enroll-URL bilden: %w", err)
	}
	client, err := httpclient.New(cacert, insecure, 30*time.Second)
	if err != nil {
		return fmt.Errorf("HTTP-Client: %w", err)
	}
	key, err := enroll.GenerateKey()
	if err != nil {
		return err
	}
	csr, err := enroll.BuildCSR(key, info.SubjectID)
	if err != nil {
		return err
	}
	dir := config.AgentPkiDir()
	// Held from the first read of the identity to the commit of the new one (R-0384): a
	// renewal that finished first is the identity Replaces names, and one that waits
	// finds the new certificate fresh, instead of storing a renewal of the line this
	// request has the issuer revoke.
	unlock, err := enroll.LockIdentity(context.Background(), dir)
	if err != nil {
		return err
	}
	defer unlock()
	// An identity issued for another server is one this server never accepts (R-0283):
	// drop it before asking, so a failed enrollment leaves the agent on its API key, as
	// the best-effort enrollment promises (R-0312).
	if cn := enroll.LeafCommonName(dir); cn != "" && cn != info.SubjectID {
		if err := enroll.RemoveIdentity(dir); err != nil {
			return fmt.Errorf("drop the identity of server %q: %w", cn, err)
		}
		fmt.Printf("→ Dropped the identity of server %q: this host is provisioned for %q now.\n", cn, info.SubjectID)
	}
	// The request below lets the issuer revoke the earlier line at once: ask only for an
	// identity this host can store (R-0293).
	if err := checkStorable(dir); err != nil {
		return fmt.Errorf("the identity cannot be stored, nothing was requested: %w", err)
	}
	// The identity of an earlier provisioning is still on disk until Store replaces it:
	// naming it lets the issuer revoke the old line (R-0224).
	req := enroll.Request{
		Token:    info.Token,
		CSR:      string(csr),
		Replaces: enroll.LeafFingerprint(dir),
	}
	issued, err := enroll.Submit(context.Background(), client, endpoint, req)
	if err != nil {
		return err
	}
	if err := storeIdentity(dir, key, issued); err != nil {
		return fmt.Errorf("store the new identity: %w; provision again with a new token: %s", err, enroll.ReprovisionHint)
	}
	return nil
}

// enrollEndpoint reuses the host of the already-trusted server URL and swaps in
// the gateway's enroll port — the server cannot know its own public address.
func enrollEndpoint(adminHelperURL string, port int) (string, error) {
	u, err := url.Parse(adminHelperURL)
	if err != nil {
		return "", err
	}
	host := u.Hostname()
	if host == "" {
		return "", fmt.Errorf("kein Host in %q", adminHelperURL)
	}
	u.Host = net.JoinHostPort(host, strconv.Itoa(port))
	u.Path = "/enroll"
	u.RawQuery = ""
	return u.String(), nil
}

// activateEndpoint targets the provision-activate bootstrap door on the gateway's
// certless enroll plane (:8444), not the mTLS data plane — a fresh agent has no
// client cert yet, and :443 CERT_REQUIREs one under MTLS_ENFORCE=true (A8). Mirrors
// enrollEndpoint: reuse the already-trusted host, swap in the enroll port.
func activateEndpoint(adminHelperURL string, port int, serverID string) (string, error) {
	u, err := url.Parse(adminHelperURL)
	if err != nil {
		return "", err
	}
	host := u.Hostname()
	if host == "" {
		return "", fmt.Errorf("kein Host in %q", adminHelperURL)
	}
	u.Host = net.JoinHostPort(host, strconv.Itoa(port))
	u.Path = fmt.Sprintf("/api/servers/%s/provision/activate", serverID)
	u.RawQuery = ""
	return u.String(), nil
}

func callActivate(adminHelperURL, token, serverID, cacert string, insecure bool, fingerprint *[sha256.Size]byte, enrollPort int) (*activateResponse, []byte, error) {
	var client *http.Client
	if fingerprint != nil {
		u, err := url.Parse(adminHelperURL)
		if err != nil {
			return nil, nil, fmt.Errorf("parse --url: %w", err)
		}
		// Anchor and hostname verify inside the handshake: the provision token below is
		// only ever sent over a connection that proved the pinned CA (3.45 hardened) and
		// names the host of --url, which every later call verifies (R-0639).
		client = httpclient.NewCAFingerprint(*fingerprint, u.Hostname(), 30*time.Second)
	} else {
		var err error
		client, err = httpclient.New(cacert, insecure, 30*time.Second)
		if err != nil {
			return nil, nil, fmt.Errorf("HTTP-Client: %w", err)
		}
	}

	// Activate is a token-gated bootstrap door on the gateway's certless enroll
	// plane (:8444), NOT the mTLS data plane (:443): the agent has no client cert
	// yet, and :443 rejects certless connections under MTLS_ENFORCE=true (A8).
	endpoint, err := activateEndpoint(adminHelperURL, enrollPort, serverID)
	if err != nil {
		return nil, nil, fmt.Errorf("Activate-URL bilden: %w", err)
	}
	req, err := http.NewRequest("POST", endpoint, nil)
	if err != nil {
		return nil, nil, err
	}
	req.Header.Set("X-Provision-Token", token)
	req.Header.Set("Content-Type", "application/json")

	// Hand-rolled (not httpclient.Do): TOFU pinning below needs the raw
	// *http.Response's TLS.PeerCertificates, which the []byte helper doesn't expose.
	httpResp, err := client.Do(req)
	if err != nil {
		return nil, nil, fmt.Errorf("Activate-Aufruf fehlgeschlagen: %w", err)
	}
	defer httpResp.Body.Close()

	body, err := io.ReadAll(io.LimitReader(httpResp.Body, httpclient.MaxResponseBytes+1))
	if err != nil {
		return nil, nil, err
	}
	if int64(len(body)) > httpclient.MaxResponseBytes {
		return nil, nil, fmt.Errorf("Activate-Antwort ueberschreitet %d Bytes", httpclient.MaxResponseBytes)
	}
	if httpResp.StatusCode >= 300 {
		return nil, nil, fmt.Errorf("Activate fehlgeschlagen (HTTP %d): %s", httpResp.StatusCode, string(body))
	}

	var resp activateResponse
	if err := json.Unmarshal(body, &resp); err != nil {
		return nil, nil, fmt.Errorf("JSON-Antwort parsen: %w", err)
	}

	// Capture the certificate chain the server presented, so a blind --insecure
	// provisioning can pin it (TOFU) for the recurring loop instead of disabling
	// verification forever.
	var serverCertPEM []byte
	if httpResp.TLS != nil {
		for _, c := range httpResp.TLS.PeerCertificates {
			serverCertPEM = append(serverCertPEM, pem.EncodeToMemory(
				&pem.Block{Type: "CERTIFICATE", Bytes: c.Raw})...)
		}
	}
	return &resp, serverCertPEM, nil
}

// writePinnedCert stores the captured server certificate chain in a temp file so
// monitor.Init / frpc.Apply can copy it into the agent config as the pinned CA.
func writePinnedCert(pemBytes []byte) (string, error) {
	f, err := os.CreateTemp("", "adminhelper-server-ca-*.crt")
	if err != nil {
		return "", err
	}
	defer f.Close()
	if _, err := f.Write(pemBytes); err != nil {
		os.Remove(f.Name())
		return "", err
	}
	return f.Name(), nil
}
