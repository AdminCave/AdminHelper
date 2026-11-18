// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package frpc

// The Windows agent starts only this frpc.exe: the one in frp_<version>_windows_amd64.zip, whose
// archive the workflows pin as FRP_VERSION and FRP_SHA256_WINDOWS_AMD64. Both pins change
// together; CI checks that they match.
const (
	frpcPinnedVersion = "0.72.0"
	frpcExeSHA256     = "b8580b916ecb2e27ecc348bc67bc8b93b0e65266f85fd5d703e2f2f69862b089"
)
