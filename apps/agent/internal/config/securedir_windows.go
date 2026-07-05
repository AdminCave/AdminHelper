// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build windows

package config

import "os/exec"

// SecureDir hardens a secret-bearing directory's ACL. Unix mode bits (os.Chmod
// 0700) are no-ops for Windows ACLs, so without this the inherited %ProgramData%
// ACL leaves the agent's API key and mTLS private key readable by any local user.
// It first resets the owner to Administrators (evicting a squatter who pre-created
// the dir from its owner-implicit WRITE_DAC), then locks the DACL as the final
// mutation — a full replacement, so no ACE a squatter injected can survive (3.1).
func SecureDir(dir string) error {
	// Best-effort owner reset FIRST (SID-based, locale-independent; *S-1-5-32-544 =
	// Administrators): a squatter who owns the dir keeps owner-implicit WRITE_DAC, so
	// it must lose ownership before the DACL is locked — otherwise it could race an
	// inheritable read ACE back in between the two icacls calls, and /setowner does
	// not touch the DACL to wipe it.
	_ = exec.Command("icacls", dir, "/setowner", "*S-1-5-32-544").Run()
	// DACL lock as the FINAL mutation — a full replacement that wipes every inherited
	// ACE (incl. the BUILTIN\Users read) plus any ACE a squatter set. *S-1-5-18 =
	// SYSTEM; (OI)(CI)F = object+container inherit, full control. This is the primary
	// protection, so its error is the one propagated.
	return exec.Command("icacls", dir, "/inheritance:r",
		"/grant:r", "*S-1-5-18:(OI)(CI)F",
		"/grant:r", "*S-1-5-32-544:(OI)(CI)F",
	).Run()
}
