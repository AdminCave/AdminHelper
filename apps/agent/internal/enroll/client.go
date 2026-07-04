// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package enroll

import (
	"net/http"
	"time"

	"adminhelper-agent/internal/httpclient"
)

// ServerClient returns the HTTP client the agent uses for server pushes: mTLS
// with the enrolled identity when present (client cert + custom-root-only),
// otherwise the legacy fallback (pinned cacert / insecure) so pre-enrollment
// and not-yet-migrated agents keep working during the permissive rollout.
//
// It lives in the enroll package (not httpclient) because it depends on
// Provisioned/CertPath/KeyPath/CAPath here — moving it to httpclient would form
// an import cycle. Consumed by frpc.Sync and monitor.PushReport.
func ServerClient(dir, fallbackCacert string, fallbackInsecure bool, timeout time.Duration) (*http.Client, error) {
	if Provisioned(dir) {
		return httpclient.NewMTLS(CertPath(dir), KeyPath(dir), CAPath(dir), timeout)
	}
	return httpclient.New(fallbackCacert, fallbackInsecure, timeout)
}
