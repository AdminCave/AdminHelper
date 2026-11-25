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
// trusts only the CA bundle it got at enrollment and checks that the certificate is the
// gateway's, issued by the access intermediate, as the server push does (httpclient.NewMTLS);
// its configured cacert and insecure setting do not apply. Without an identity they stay in
// force. The repo plane :8445 asks for no client certificate, so none is presented.
func updateClient(pkiDir, cacert string, insecure bool, timeout time.Duration) (*http.Client, error) {
	if enroll.Provisioned(pkiDir) {
		return httpclient.NewGateway(enroll.CAPath(pkiDir), timeout)
	}
	return httpclient.New(cacert, insecure, timeout)
}
