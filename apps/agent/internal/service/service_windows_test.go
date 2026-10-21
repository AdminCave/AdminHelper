// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build windows

package service

import (
	"errors"
	"fmt"
	"os"
	"strings"
	"testing"
	"time"

	"golang.org/x/sys/windows/registry"
	"golang.org/x/sys/windows/svc/eventlog"

	"adminhelper-agent/internal/logging"
)

// A repeated service install and uninstall must not fail on the event source: the
// helpers register it once and keep it on a second registration, and remove it once
// and accept its absence on a second removal. The source has a name of its own, so
// that the test leaves the source of an installed agent alone, and the cleanup removes
// it also when the test fails.
func TestEventSourceRegistrationAndRemovalAreRepeatable(t *testing.T) {
	source := fmt.Sprintf("%s-Test-%d-%d", logging.EventSource, os.Getpid(), time.Now().UnixNano())
	key := `SYSTEM\CurrentControlSet\Services\EventLog\Application\` + source
	t.Cleanup(func() {
		if err := eventlog.Remove(source); err != nil && !errors.Is(err, registry.ErrNotExist) {
			t.Errorf("remove the test source %s: %v", source, err)
		}
	})

	if err := registerEventSource(source); err != nil {
		t.Fatalf("first registration: %v", err)
	}
	if err := registerEventSource(source); err != nil {
		t.Errorf("second registration of an existing source: %v", err)
	}
	k, err := registry.OpenKey(registry.LOCAL_MACHINE, key, registry.QUERY_VALUE)
	if err != nil {
		t.Fatalf(`HKLM\%s is missing after the registration: %v`, key, err)
	}
	msgFile, _, err := k.GetStringValue("EventMessageFile")
	if err != nil || !strings.HasSuffix(strings.ToLower(msgFile), `\eventcreate.exe`) {
		t.Errorf("EventMessageFile is %q (%v), want EventCreate.exe", msgFile, err)
	}
	types, _, err := k.GetIntegerValue("TypesSupported")
	if want := uint64(eventlog.Error | eventlog.Warning | eventlog.Info); err != nil || types != want {
		t.Errorf("TypesSupported is %d (%v), want %d (errors, warnings, information)", types, err, want)
	}
	k.Close()

	if err := removeEventSource(source); err != nil {
		t.Fatalf("first removal: %v", err)
	}
	if err := removeEventSource(source); err != nil {
		t.Errorf("second removal of a missing source: %v", err)
	}
	if k, err := registry.OpenKey(registry.LOCAL_MACHINE, key, registry.QUERY_VALUE); err == nil {
		k.Close()
		t.Errorf(`HKLM\%s is still there after the removal`, key)
	} else if !errors.Is(err, registry.ErrNotExist) {
		t.Errorf(`open HKLM\%s after the removal: %v`, key, err)
	}
}
