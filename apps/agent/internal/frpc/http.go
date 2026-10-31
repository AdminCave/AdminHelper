// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package frpc

import (
	"context"
	"net/http"

	"adminhelper-agent/internal/httpclient"
)

// httpGet performs a GET request with an API-Key header; it ends with ctx.
func httpGet(ctx context.Context, client *http.Client, url, apiKey string) ([]byte, error) {
	req, err := http.NewRequestWithContext(ctx, "GET", url, nil)
	if err != nil {
		return nil, err
	}
	if apiKey != "" {
		req.Header.Set("X-API-Key", apiKey)
	}
	return httpclient.Do(client, req)
}
