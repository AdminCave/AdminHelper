// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package frpc

import (
	"net/http"

	"adminhelper-agent/internal/httpclient"
)

// httpGet performs a GET request with an API-Key header.
func httpGet(client *http.Client, url, apiKey string) ([]byte, error) {
	req, err := http.NewRequest("GET", url, nil)
	if err != nil {
		return nil, err
	}
	if apiKey != "" {
		req.Header.Set("X-API-Key", apiKey)
	}
	return httpclient.Do(client, req)
}
