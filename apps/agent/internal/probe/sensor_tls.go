// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package probe

import (
	"context"
	"crypto/x509"
	"errors"
	"fmt"
	"math"
	"time"
)

func init() {
	sensors["tls"] = tlsSensor
}

// certRoots are the roots chain_ok trusts, nil for those of this host; tests stand in their own.
var certRoots *x509.CertPool

// tlsSensor shakes hands with its target through the guard, after STARTTLS of a protocol if starttls
// names one, and reads the server's certificate: when it expires, who issued it, whether its chain
// leads to a root of this host and, if server_name is set, whether it is valid for that name.
func tlsSensor(ctx context.Context, p Probe, _ string) (map[string]any, error) {
	t, err := targetOf(p, httpTargets...)
	if err != nil {
		return nil, err
	}
	if err := knownParams(p, "server_name", "starttls"); err != nil {
		return nil, err
	}
	serverName, err := textParam(p, "server_name", "")
	if err != nil {
		return nil, err
	}
	if !plainText(serverName, 253) {
		return nil, fmt.Errorf("%w: parameter server_name of sensor tls needs a name of at most 253 characters without spaces", ErrInvalid)
	}
	starttls, err := choiceParam(p, "starttls", "none", append([]string{"none"}, startTLSProtocols...)...)
	if err != nil {
		return nil, err
	}
	if _, err := credentialUse(p); err != nil {
		return nil, err
	}
	ep, err := resolve(ctx, t)
	if err != nil {
		return nil, err
	}
	conn, err := dialTarget(ctx, ep)
	if err != nil {
		return nil, err
	}
	s := newSession(ctx, conn)
	defer s.end()
	if starttls != "none" {
		if err := askTLS(s, starttls); err != nil {
			return nil, protoErr(starttls, err)
		}
	}
	if err := s.startTLS(serverName, 0); err != nil {
		return nil, protoErr("tls", err)
	}
	return certValues(s.tc.ConnectionState().PeerCertificates, serverName)
}

// protoErr is the probe's error for err of protocol name: an answer outside the protocol says which.
func protoErr(name string, err error) error {
	var pf protoFail
	if errors.As(err, &pf) {
		return fmt.Errorf("%s: %s", name, pf.detail)
	}
	return err
}

// certValues reads the certificate a server presented (certs, leaf first). chain_ok checks the chain
// against the roots of this host; on Windows the platform's verifier may fetch a missing intermediate.
// hostname_ok comes only with a serverName: without one, the sensor cannot know which name to ask for.
func certValues(certs []*x509.Certificate, serverName string) (map[string]any, error) {
	if len(certs) == 0 {
		return nil, errors.New("the server presented no certificate")
	}
	leaf := certs[0]
	inter := x509.NewCertPool()
	for _, c := range certs[1:] {
		inter.AddCert(c)
	}
	_, verr := leaf.Verify(x509.VerifyOptions{Roots: certRoots, Intermediates: inter, CurrentTime: now()})
	left := leaf.NotAfter.Sub(now())
	values := map[string]any{
		"not_after":    leaf.NotAfter.Unix(),
		"days_left":    int64(math.Floor(left.Hours() / 24)),
		"hours_left":   int64(math.Floor(left.Hours())),
		"lifetime_pct": lifetimePct(left, leaf.NotAfter.Sub(leaf.NotBefore)),
		"issuer":       leaf.Issuer.String(),
		"chain_ok":     verr == nil,
	}
	if serverName != "" {
		values["hostname_ok"] = leaf.VerifyHostname(serverName) == nil
	}
	return values, nil
}

// lifetimePct is the share of its lifetime a certificate has left, in percent to one decimal and never
// below 0. A certificate without a lifetime has nothing left: a quotient by zero is no number JSON carries.
func lifetimePct(left, lifetime time.Duration) float64 {
	if left <= 0 || lifetime <= 0 {
		return 0
	}
	return math.Round(float64(left)/float64(lifetime)*1000) / 10
}
