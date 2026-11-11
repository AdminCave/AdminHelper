// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// frps-policy is frps' server plugin for NewProxy in the frps image
// (internal/frpspolicy). It serves on a loopback address until SIGTERM or SIGINT.
package main

import (
	"context"
	"flag"
	"fmt"
	"log/slog"
	"net"
	"os"
	"os/signal"
	"strings"
	"syscall"

	"adminhelper-agent/internal/frpspolicy"
)

func main() {
	listen := flag.String("listen", "127.0.0.1:7480", "loopback address to serve on")
	path := flag.String("path", "/handler", "path of the plugin in frps' [[httpPlugins]]")
	policy := flag.String("policy", "/etc/frp/frps-policy.json", "policy file the server writes")
	flag.Parse()

	log := slog.New(slog.NewTextHandler(os.Stderr, nil))
	if err := run(*listen, *path, *policy, log); err != nil {
		log.Error("frps-policy stopped", "err", err)
		os.Exit(1)
	}
}

func run(listen, path, policy string, log *slog.Logger) error {
	if err := frpspolicy.CheckListen(listen); err != nil {
		return err
	}
	if !strings.HasPrefix(path, "/") || path == frpspolicy.HealthPath {
		return fmt.Errorf("path %q must start with / and differ from %s", path, frpspolicy.HealthPath)
	}
	ln, err := net.Listen("tcp", listen)
	if err != nil {
		return err
	}
	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGTERM, os.Interrupt)
	defer stop()
	log.Info("frps-policy serving", "addr", ln.Addr().String(), "path", path, "policy", policy)
	handler := frpspolicy.NewHandler(frpspolicy.NewSource(policy), path, log)
	return frpspolicy.Serve(ctx, ln, handler, frpspolicy.DefaultTimeouts)
}
