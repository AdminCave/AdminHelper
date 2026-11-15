// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build windows

package probe

import (
	"errors"
	"fmt"
	"runtime"
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
// The dates come from the store's own CERT_INFO, so a certificate Go's x509 parser would
// reject still counts.
func machineCerts() ([]certValidity, error) {
	name, err := windows.UTF16PtrFromString("My")
	if err != nil {
		return nil, err
	}
	store, err := windows.CertOpenStore(windows.CERT_STORE_PROV_SYSTEM_W, 0, 0,
		windows.CERT_SYSTEM_STORE_LOCAL_MACHINE|windows.CERT_STORE_READONLY_FLAG|windows.CERT_STORE_OPEN_EXISTING_FLAG,
		uintptr(unsafe.Pointer(name)))
	// The call takes the pointer as a uintptr, which does not keep name alive.
	runtime.KeepAlive(name)
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
		certs = append(certs, certValidity{
			notBefore: fileTime(ctx.CertInfo.NotBefore),
			notAfter:  fileTime(ctx.CertInfo.NotAfter),
		})
	}
	if err != nil && !errors.Is(err, windows.Errno(windows.CRYPT_E_NOT_FOUND)) {
		return nil, fmt.Errorf("cert store: %w", err)
	}
	return certs, nil
}

// fileTime converts a FILETIME. Filetime.Nanoseconds overflows for the year 2262 on, which
// certificates with no real end date (9999) reach.
func fileTime(ft windows.Filetime) time.Time {
	const epochDiff = 11644473600 // seconds from 1601 to 1970
	ticks := uint64(ft.HighDateTime)<<32 | uint64(ft.LowDateTime)
	return time.Unix(int64(ticks/10_000_000)-epochDiff, int64(ticks%10_000_000)*100).UTC()
}
