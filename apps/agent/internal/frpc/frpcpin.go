// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package frpc

// The Windows agent starts only this frpc.exe: the one in frp_<version>_windows_amd64.zip, whose
// archive the workflows pin as FRP_VERSION and FRP_SHA256_WINDOWS_AMD64. Both pins change
// together; CI checks that they match. service install checks frpc.exe against it as well, before
// it puts the file beside the agent.
const (
	PinnedVersion = "0.72.0"
	ExeSHA256     = "b8580b916ecb2e27ecc348bc67bc8b93b0e65266f85fd5d703e2f2f69862b089"
)
