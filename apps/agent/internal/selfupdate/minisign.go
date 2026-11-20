// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Package selfupdate fetches and verifies a signed agent release from the
// gateway's repo plane (:8445/windows/) and stages it for the swap.
package selfupdate

import (
	"bytes"
	"crypto/ed25519"
	"encoding/base64"
	"errors"
	"fmt"
	"strings"

	"golang.org/x/crypto/blake2b"
)

// ReleasePublicKey is the fleet's minisign key, the same one install.sh and
// update.sh pin as MINISIGN_PUBKEY (a test keeps them in lockstep).
const ReleasePublicKey = "RWTU2kEztd3UWTF8HW26S8MWWiTUe6oz38I7rTBBSOvmQ3SHmszo6llJ"

const trustedPrefix = "trusted comment: "

type publicKey struct {
	id  [8]byte
	key ed25519.PublicKey
}

// parsePublicKey decodes base64("Ed" || key_id || ed25519 public key).
func parsePublicKey(s string) (publicKey, error) {
	raw, err := base64.StdEncoding.DecodeString(strings.TrimSpace(s))
	if err != nil || len(raw) != 2+8+ed25519.PublicKeySize || string(raw[:2]) != "Ed" {
		return publicKey{}, errors.New("minisign: invalid public key")
	}
	var pk publicKey
	copy(pk.id[:], raw[2:10])
	pk.key = ed25519.PublicKey(raw[10:])
	return pk, nil
}

// Verify checks a .minisig over data against the base64 public key and
// returns the trusted comment. Only the prehashed "ED" form is accepted:
// minisign signs that by default, and the legacy "Ed" form is not needed.
func Verify(pubKey string, data, sig []byte) (string, error) {
	pk, err := parsePublicKey(pubKey)
	if err != nil {
		return "", err
	}
	lines := strings.Split(strings.TrimRight(string(sig), "\r\n"), "\n")
	if len(lines) != 4 {
		return "", errors.New("minisign: malformed signature file")
	}
	for i := range lines {
		lines[i] = strings.TrimRight(lines[i], "\r")
	}
	sigRaw, err := base64.StdEncoding.DecodeString(lines[1])
	if err != nil || len(sigRaw) != 2+8+ed25519.SignatureSize {
		return "", errors.New("minisign: malformed signature")
	}
	if string(sigRaw[:2]) != "ED" {
		return "", errors.New("minisign: unsupported signature algorithm (need prehashed ED)")
	}
	if !bytes.Equal(sigRaw[2:10], pk.id[:]) {
		return "", errors.New("minisign: signature made with a different key")
	}
	digest := blake2b.Sum512(data)
	signature := sigRaw[10:]
	if !ed25519.Verify(pk.key, digest[:], signature) {
		return "", errors.New("minisign: signature verification failed")
	}
	trusted, ok := strings.CutPrefix(lines[2], trustedPrefix)
	if !ok {
		return "", errors.New("minisign: missing trusted comment")
	}
	global, err := base64.StdEncoding.DecodeString(lines[3])
	if err != nil || len(global) != ed25519.SignatureSize {
		return "", errors.New("minisign: malformed global signature")
	}
	if !ed25519.Verify(pk.key, append(append([]byte{}, signature...), trusted...), global) {
		return "", fmt.Errorf("minisign: trusted comment verification failed")
	}
	return trusted, nil
}
