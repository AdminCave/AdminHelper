// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build linux

package config

func FrpDir() string     { return "/etc/frp" }
func MonitorDir() string { return "/etc/adminhelper" }
