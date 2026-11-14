// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build linux || freebsd

package probe

import (
	"context"
	"fmt"
	"net/http"
	"strings"
	"testing"
)

func TestApacheStatusReadsTheWorkersOfItsPlace(t *testing.T) {
	srv, port := serveStatus(t, http.StatusOK, modStatusAuto)
	files := apacheFiles(t, fmt.Sprintf("Listen %d\nInclude mods-enabled/*.conf\n", port), debianStatus)
	calls := stubTools(t, answer{out: dumpIncludes(files)})

	got, err := apacheStatus(context.Background(), webUnit("apache2.service"))

	if err != nil || got["busy_workers"] != 3 || got["slots"] != 14 {
		t.Fatalf("apache_status = %v, %v", got, err)
	}
	if strings.Join((*calls)[0], " ") != "apache2ctl -t -D DUMP_INCLUDES" {
		t.Errorf("ran %q", *calls)
	}
	if want := "GET localhost /server-status?auto"; strings.Join(srv.requests(), ",") != want {
		t.Errorf("asked %q, want %q", srv.requests(), want)
	}

	calls = stubTools(t, answer{out: dumpIncludes(files)})
	if _, err := apacheStatus(context.Background(), webUnit("httpd.service")); err != nil {
		t.Errorf("httpd = %v", err)
	}
	if (*calls)[0][0] != "apachectl" {
		t.Errorf("httpd ran %q, want apachectl", *calls)
	}
}
