// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build windows

package probe

import (
	"os"
	"path/filepath"
)

// dirFlags open a directory to list it; Windows opens no FIFO by a file name.
const dirFlags = os.O_RDONLY

// notDir is err: Windows names no error for a file that is no directory.
func notDir(err error) error { return err }

// openDir opens the directory name to list it, below parent when parent is not nil; any other file is
// errNotDir. BigBlueButton runs on Linux alone: on Windows the view only has to find no recording
// status.
func openDir(parent *os.File, name string) (*os.File, error) {
	if parent != nil {
		name = filepath.Join(parent.Name(), name)
	}
	f, err := os.Open(name)
	if err != nil {
		return nil, err
	}
	if fi, err := f.Stat(); err != nil || !fi.IsDir() {
		f.Close()
		return nil, errNotDir
	}
	return f, nil
}
