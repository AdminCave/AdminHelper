// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package frpc

// What platform_freebsd.go shares with the rc.d script apps/agent/freebsd/adminhelper_frpc, which
// runs frpc under daemon(8). Without a build tag, so rcscript_test.go holds the script to them on
// every platform.
const (
	// rcName is the service's name and the prefix of its rcvar.
	rcName = "adminhelper_frpc"
	// rcFrpcBinary is the frpc of the package, outside PATH: the net/frp port installs its own
	// /usr/local/bin/frpc, and pkg refuses a package whose files clash with an installed one.
	rcFrpcBinary = "/usr/local/libexec/adminhelper/frpc"
)

// rcChildPidFile is daemon(8)'s -p: the pid of frpc, empty while daemon waits to restart it. A
// var only so tests can point it elsewhere.
var rcChildPidFile = "/var/run/adminhelper_frpc.child.pid"
