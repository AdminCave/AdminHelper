// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package selfupdate

import (
	"net/http"
	"time"

	"adminhelper-agent/internal/enroll"
	"adminhelper-agent/internal/httpclient"
)

// updateClient is the client the self-update fetches the release with. An enrolled host
// trusts the CA bundle it got at enrollment, as the server push does (enroll.ServerClient);
// without an identity the configured cacert or insecure setting stays in force. The repo
// plane :8445 asks for no client certificate, so none is presented.
func updateClient(pkiDir, cacert string, insecure bool, timeout time.Duration) (*http.Client, error) {
	if enroll.Provisioned(pkiDir) {
		return httpclient.New(enroll.CAPath(pkiDir), false, timeout)
	}
	return httpclient.New(cacert, insecure, timeout)
}
