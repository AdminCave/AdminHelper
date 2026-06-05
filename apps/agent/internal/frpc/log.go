// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package frpc

import "fmt"

const logTag = "adminhelper-agent-frpc"

func logMsg(format string, args ...any) {
	fmt.Printf("[%s] %s\n", logTag, fmt.Sprintf(format, args...))
}
