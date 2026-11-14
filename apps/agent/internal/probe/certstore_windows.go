// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build windows

package probe

import (
	"crypto/x509"
	"errors"
	"fmt"
	"time"
	"unsafe"

	"golang.org/x/sys/windows"
)

// certValidity is what the agent keeps of one certificate of the machine store.
type certValidity struct {
	notBefore time.Time
	notAfter  time.Time
}

// machineCerts reads the validity of every certificate in LocalMachine\My, opened read-only.
// A certificate the parser rejects is left out.
func machineCerts() ([]certValidity, error) {
	name, err := windows.UTF16PtrFromString("My")
	if err != nil {
		return nil, err
	}
	store, err := windows.CertOpenStore(windows.CERT_STORE_PROV_SYSTEM_W, 0, 0,
		windows.CERT_SYSTEM_STORE_LOCAL_MACHINE|windows.CERT_STORE_READONLY_FLAG|windows.CERT_STORE_OPEN_EXISTING_FLAG,
		uintptr(unsafe.Pointer(name)))
	if err != nil {
		return nil, fmt.Errorf("cert store: %w", err)
	}
	defer func() { _ = windows.CertCloseStore(store, 0) }()
	var certs []certValidity
	var ctx *windows.CertContext
	for {
		ctx, err = windows.CertEnumCertificatesInStore(store, ctx)
		if ctx == nil {
			// The enumeration ends with CRYPT_E_NOT_FOUND; it frees the last context itself.
			break
		}
		der := unsafe.Slice(ctx.EncodedCert, ctx.Length)
		if c, perr := x509.ParseCertificate(der); perr == nil {
			certs = append(certs, certValidity{notBefore: c.NotBefore, notAfter: c.NotAfter})
		}
	}
	if err != nil && !errors.Is(err, windows.Errno(windows.CRYPT_E_NOT_FOUND)) {
		return nil, fmt.Errorf("cert store: %w", err)
	}
	return certs, nil
}
