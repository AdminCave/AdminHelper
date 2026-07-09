// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package enroll

import (
	"net/http"
	"os"
	"time"

	"adminhelper-agent/internal/httpclient"
	"adminhelper-agent/internal/logging"
)

// logger tags enroll's operational logs with component=enroll.
var logger = logging.For("enroll")

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
		// If the enrolled leaf has already expired, the mTLS handshake can never
		// complete and (under enforcement) there is no fallback — the agent would
		// otherwise just hang on generic handshake errors every cycle. Stay fail-closed
		// (still return the mTLS client), but log a clear, actionable message so the
		// operator knows to re-provision (4.8).
		if pemBytes, rerr := os.ReadFile(CertPath(dir)); rerr == nil {
			if expired, notAfter, lerr := leafExpired(pemBytes); lerr == nil && expired {
				logger.Warnf("mTLS-Client-Cert seit %s abgelaufen — Handshake kann nicht gelingen; Agent neu provisionieren (adminhelper-agent enroll --token <TOKEN>)", notAfter.Format(time.RFC3339))
			}
		}
		return httpclient.NewMTLS(CertPath(dir), KeyPath(dir), CAPath(dir), timeout)
	}
	return httpclient.New(fallbackCacert, fallbackInsecure, timeout)
}
