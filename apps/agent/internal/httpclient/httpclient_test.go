// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package httpclient

import (
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func TestDoReturnsBodyOn2xx(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, _ = w.Write([]byte("ok-body"))
	}))
	defer srv.Close()

	req, _ := http.NewRequest("GET", srv.URL, nil)
	body, err := Do(srv.Client(), req)
	if err != nil {
		t.Fatalf("Do gab Fehler: %v", err)
	}
	if string(body) != "ok-body" {
		t.Errorf("body = %q, erwartet %q", body, "ok-body")
	}
}

func TestDoMapsErrorStatusWithBody(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusInternalServerError)
		_, _ = w.Write([]byte("boom"))
	}))
	defer srv.Close()

	req, _ := http.NewRequest("GET", srv.URL, nil)
	body, err := Do(srv.Client(), req)
	if err == nil {
		t.Fatal("erwartet Fehler bei HTTP 500")
	}
	if body != nil {
		t.Errorf("body = %q, erwartet nil bei Fehler", body)
	}
	// The consolidated helper carries both status and body (the drift 2.5 fixed:
	// the old monitor push dropped the body).
	if !strings.Contains(err.Error(), "500") || !strings.Contains(err.Error(), "boom") {
		t.Errorf("Fehler %q enthaelt nicht Status+Body", err.Error())
	}
}
