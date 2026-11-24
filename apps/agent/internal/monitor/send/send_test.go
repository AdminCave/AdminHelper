// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package send

import (
	"context"
	"net/http"
	"net/http/httptest"
	"sync/atomic"
	"testing"
	"time"

	"adminhelper-agent/internal/monitor"
)

// shortenRetryDelay shrinks the push retry backoff for the test duration.
func shortenRetryDelay(t *testing.T) {
	t.Helper()
	orig := RetryDelay
	RetryDelay = time.Millisecond
	t.Cleanup(func() { RetryDelay = orig })
}

func TestPushReportSuccessNoRetry(t *testing.T) {
	shortenRetryDelay(t)
	var attempts atomic.Int32
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		attempts.Add(1)
		if r.Header.Get("X-API-Key") != "key" {
			t.Errorf("X-API-Key = %q, erwartet %q", r.Header.Get("X-API-Key"), "key")
		}
		w.WriteHeader(http.StatusOK)
	}))
	defer srv.Close()

	if err := Report(context.Background(), Params{URL: srv.URL, APIKey: "key", ServerID: "srv-1", Report: &monitor.Report{}}); err != nil {
		t.Fatalf("PushReport: %v", err)
	}
	if got := attempts.Load(); got != 1 {
		t.Errorf("attempts = %d, erwartet 1 (kein Retry bei Erfolg)", got)
	}
}

func TestPushReportRetriesOnceOnTransientError(t *testing.T) {
	shortenRetryDelay(t)
	var attempts atomic.Int32
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if attempts.Add(1) == 1 {
			w.WriteHeader(http.StatusInternalServerError)
			return
		}
		w.WriteHeader(http.StatusOK)
	}))
	defer srv.Close()

	if err := Report(context.Background(), Params{URL: srv.URL, APIKey: "key", ServerID: "srv-1", Report: &monitor.Report{}}); err != nil {
		t.Fatalf("PushReport nach Retry: %v", err)
	}
	if got := attempts.Load(); got != 2 {
		t.Errorf("attempts = %d, erwartet 2 (genau ein Retry)", got)
	}
}

func TestPushReportFailsAfterSingleRetry(t *testing.T) {
	shortenRetryDelay(t)
	var attempts atomic.Int32
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		attempts.Add(1)
		w.WriteHeader(http.StatusBadGateway)
	}))
	defer srv.Close()

	err := Report(context.Background(), Params{URL: srv.URL, APIKey: "key", ServerID: "srv-1", Report: &monitor.Report{}})
	if err == nil {
		t.Fatal("PushReport erwartete Fehler, bekam keinen")
	}
	if got := attempts.Load(); got != 2 {
		t.Errorf("attempts = %d, erwartet 2 (genau ein Retry, kein Loop)", got)
	}
}

func TestPushReportAbortsInFlightRequestOnContextCancel(t *testing.T) {
	// The handler hangs on its request's ctx. Without 2.67 (ctx reaching the
	// request) the client would block until its own 15s timeout; cancelling
	// mid-flight must abort the in-flight request itself, so PushReport returns
	// promptly. The long backoff would also stall a stray retry, so returning
	// fast proves the ctx short-circuits both the request and the retry.
	orig := RetryDelay
	RetryDelay = 30 * time.Second
	t.Cleanup(func() { RetryDelay = orig })

	ctx, cancel := context.WithCancel(context.Background())
	var attempts atomic.Int32
	reached := make(chan struct{})
	release := make(chan struct{})
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if attempts.Add(1) == 1 {
			close(reached)
		}
		<-release // block until the test releases the handler
	}))
	defer srv.Close()
	defer close(release) // let the blocked handler finish so srv.Close() returns

	go func() {
		<-reached
		cancel()
	}()

	start := time.Now()
	if err := Report(ctx, Params{URL: srv.URL, APIKey: "key", ServerID: "srv-1", Report: &monitor.Report{}}); err == nil {
		t.Fatal("PushReport erwartete ctx-Fehler nach Cancel")
	}
	if elapsed := time.Since(start); elapsed > 5*time.Second {
		t.Errorf("PushReport blockierte %v — der in-flight-Request wurde nicht abgebrochen", elapsed)
	}
	if got := attempts.Load(); got != 1 {
		t.Errorf("attempts = %d, erwartet 1 (kein Retry)", got)
	}
}
