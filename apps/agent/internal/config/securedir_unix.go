// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build linux || freebsd

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

// EnsureDataDir is EnsureSecureDir on Linux and FreeBSD: the agent's directories there
// (/etc/adminhelper, /etc/frp, /var/log/adminhelper; under /usr/local/etc on FreeBSD)
// share no root of the agent's own, and the directories above them belong to root.
func EnsureDataDir(dir string) error {
	return EnsureSecureDir(dir)
}

// EnsureLogDir does nothing on Linux and FreeBSD: the logger creates the log directory
// itself, as before.
func EnsureLogDir() error {
	return nil
}

// OwnByAdministrators does nothing on Linux and FreeBSD: a new file belongs to the account that
// writes it, whatever the local policy, and EnsureSecureDir does not check owners
// there. The Windows build sets the owner explicitly.
func OwnByAdministrators(path string) error {
	return nil
}
