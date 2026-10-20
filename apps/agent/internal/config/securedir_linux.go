// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build linux

package config

import "os"

// EnsureSecureDir creates dir, with any missing parents, and restricts it to its
// owner (0700), also when it already exists with wider permissions. An existing
// directory keeps its contents.
func EnsureSecureDir(dir string) error {
	if err := os.MkdirAll(dir, 0o700); err != nil {
		return err
	}
	return os.Chmod(dir, 0o700)
}

// EnsureDataDir is EnsureSecureDir on Linux: the agent's directories there
// (/etc/adminhelper, /etc/frp, /var/log/adminhelper) share no root of the agent's own,
// and the directories above them belong to root.
func EnsureDataDir(dir string) error {
	return EnsureSecureDir(dir)
}

// EnsureLogDir does nothing on Linux: the logger creates the log directory itself, as
// before.
func EnsureLogDir() error {
	return nil
}

// OwnByAdministrators does nothing on Linux: a new file belongs to the account that
// writes it, whatever the local policy, and EnsureSecureDir does not check owners
// there. The Windows build sets the owner explicitly.
func OwnByAdministrators(path string) error {
	return nil
}

// SecureDir restricts a secret-bearing directory to its owner. On Linux the Unix
// mode bits do the job (0700); the Windows build resets the ACL instead, because
// mode bits are ignored there (3.1).
func SecureDir(dir string) error {
	return os.Chmod(dir, 0o700)
}
