// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build linux

package config

import "os"

// SecureDir restricts a secret-bearing directory to its owner. On Linux the Unix
// mode bits do the job (0700); the Windows build resets the ACL instead, because
// mode bits are ignored there (3.1).
func SecureDir(dir string) error {
	return os.Chmod(dir, 0o700)
}
