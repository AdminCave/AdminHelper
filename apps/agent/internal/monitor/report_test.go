// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package monitor

import (
	"context"
	"net/http"
	"net/http/httptest"
	"sync/atomic"
	"testing"
	"time"
)

func TestBuildReportBasics(t *testing.T) {
	report := BuildReport(nil)

	if got := report["report_version"]; got != 2 {
		t.Errorf("report_version = %v, erwartet 2", got)
	}

	ts, ok := report["timestamp"].(string)
	if !ok {
		t.Fatalf("timestamp fehlt oder ist kein String: %v", report["timestamp"])
	}
	if _, err := time.Parse("2006-01-02T15:04:05Z", ts); err != nil {
		t.Errorf("timestamp %q nicht im erwarteten Format: %v", ts, err)
	}

	resources, ok := report["resources"].(map[string]any)
	if !ok {
		t.Fatalf("resources fehlt oder hat falschen Typ: %v", report["resources"])
	}
	if _, ok := resources["cpu_percent"]; !ok {
		t.Error("resources.cpu_percent fehlt")
	}

	if _, ok := report["uptime_seconds"]; !ok {
		t.Error("uptime_seconds fehlt")
	}
	if _, ok := report["systemd"]; !ok {
		t.Error("systemd fehlt")
	}
	// Without watched services there must be no legacy "services" key.
	if _, ok := report["services"]; ok {
		t.Error("services gesetzt, obwohl keine Service-Namen uebergeben wurden")
	}
}

// shortenRetryDelay shrinks the push retry backoff for the test duration.
func shortenRetryDelay(t *testing.T) {
	t.Helper()
	orig := pushRetryDelay
	pushRetryDelay = time.Millisecond
	t.Cleanup(func() { pushRetryDelay = orig })
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

	if err := PushReport(context.Background(), PushReportParams{URL: srv.URL, APIKey: "key", ServerID: "srv-1", Report: map[string]any{"a": 1}}); err != nil {
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

	if err := PushReport(context.Background(), PushReportParams{URL: srv.URL, APIKey: "key", ServerID: "srv-1", Report: map[string]any{"a": 1}}); err != nil {
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

	err := PushReport(context.Background(), PushReportParams{URL: srv.URL, APIKey: "key", ServerID: "srv-1", Report: map[string]any{"a": 1}})
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
	orig := pushRetryDelay
	pushRetryDelay = 30 * time.Second
	t.Cleanup(func() { pushRetryDelay = orig })

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
	if err := PushReport(ctx, PushReportParams{URL: srv.URL, APIKey: "key", ServerID: "srv-1", Report: map[string]any{"a": 1}}); err == nil {
		t.Fatal("PushReport erwartete ctx-Fehler nach Cancel")
	}
	if elapsed := time.Since(start); elapsed > 5*time.Second {
		t.Errorf("PushReport blockierte %v — der in-flight-Request wurde nicht abgebrochen", elapsed)
	}
	if got := attempts.Load(); got != 1 {
		t.Errorf("attempts = %d, erwartet 1 (kein Retry)", got)
	}
}
