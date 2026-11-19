// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build !linux

package monitor

import "context"

// serviceLogsSupported: outside Linux no error lines are sent yet (R-1391).
const serviceLogsSupported = false

func readServiceLog(context.Context, string) ([]string, bool) {
	return nil, false
}
