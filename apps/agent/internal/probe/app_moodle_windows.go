// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build windows

package probe

import "fmt"

// moodleOwned: runuser and the owners of a Moodle's files are Linux's; on Windows nothing runs.
func moodleOwned(string, string) (string, error) {
	return "", fmt.Errorf("%w: checks.php runs only on Linux", ErrUnsupported)
}
