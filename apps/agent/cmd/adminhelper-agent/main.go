// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package main

import (
	"context"
	"fmt"
	"os"

	"github.com/spf13/cobra"

	"adminhelper-agent/internal/diagnostics"
	"adminhelper-agent/internal/frpc"
	"adminhelper-agent/internal/logging"
	"adminhelper-agent/internal/monitor"
	"adminhelper-agent/internal/provision"
	"adminhelper-agent/internal/service"
)

var version = "dev"

func main() {
	root := &cobra.Command{
		Use:   "adminhelper-agent",
		Short: "AdminHelper Agent — FRPC Sync + Monitoring (Linux & Windows)",
	}

	// Initialise logging before any subcommand runs. Output goes to stdout and a
	// rotating file (see internal/logging); the level defaults to the LOG_LEVEL
	// env var, overridable per-invocation with --log-level.
	var logLevel string
	root.PersistentFlags().StringVar(&logLevel, "log-level", envOr("LOG_LEVEL", "info"),
		"Log-Level: debug, info, warn, error")
	root.PersistentPreRun = func(cmd *cobra.Command, args []string) {
		logging.Init(logLevel)
	}

	root.AddCommand(versionCmd())
	root.AddCommand(runCmd())
	root.AddCommand(provisionCmd())
	root.AddCommand(frpcCmd())
	root.AddCommand(monitorCmd())
	root.AddCommand(serviceCmd())
	root.AddCommand(diagnosticsCmd())

	if err := root.Execute(); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}

func envOr(key, def string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return def
}

func versionCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "version",
		Short: "Zeigt die Version an",
		Run: func(cmd *cobra.Command, args []string) {
			fmt.Printf("adminhelper-agent %s\n", version)
		},
	}
}

func diagnosticsCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "diagnostics",
		Short: "Redaktierten Diagnose-Bericht fuer einen Bug-Report erstellen",
		RunE: func(cmd *cobra.Command, args []string) error {
			return diagnostics.Run(version)
		},
	}
}

// --- Provision subcommand (server-centric, replaces frpc init since v0.23.0) ---

func provisionCmd() *cobra.Command {
	var url, token, serverID, cacert string
	var insecure bool

	cmd := &cobra.Command{
		Use:   "provision",
		Short: "Server gegen AdminHelper provisionieren (Server-API-Key + optional Monitor + FRP)",
		RunE: func(cmd *cobra.Command, args []string) error {
			return provision.Run(url, token, serverID, cacert, insecure)
		},
	}
	cmd.Flags().StringVar(&url, "url", "", "AdminHelper Server URL (erforderlich)")
	cmd.Flags().StringVar(&token, "token", "", "Provision-Token (erforderlich)")
	cmd.Flags().StringVar(&serverID, "server-id", "", "Server-ID (erforderlich)")
	cmd.Flags().StringVar(&cacert, "cacert", "", "CA-Zertifikat fuer self-signed Server")
	cmd.Flags().BoolVar(&insecure, "insecure", false, "SSL-Verifikation deaktivieren")
	cmd.MarkFlagRequired("url")
	cmd.MarkFlagRequired("token")
	cmd.MarkFlagRequired("server-id")
	return cmd
}

// --- FRPC subcommands ---

func frpcCmd() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "frpc",
		Short: "FRPC Config Sync",
	}
	cmd.AddCommand(frpcSyncCmd())
	return cmd
}

func frpcSyncCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "sync",
		Short: "Einmaliger Config-Sync",
		RunE: func(cmd *cobra.Command, args []string) error {
			return frpc.Sync()
		},
	}
}

// --- Monitor subcommands ---

func monitorCmd() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "monitor",
		Short: "Monitoring Agent",
	}
	cmd.AddCommand(monitorInitCmd())
	cmd.AddCommand(monitorPushCmd())
	return cmd
}

func monitorInitCmd() *cobra.Command {
	var url, apiKey, serverID, services, cacert string
	var insecure bool

	cmd := &cobra.Command{
		Use:   "init",
		Short: "Ersteinrichtung des Monitor-Agents",
		RunE: func(cmd *cobra.Command, args []string) error {
			return monitor.Init(url, apiKey, serverID, services, cacert, insecure)
		},
	}
	cmd.Flags().StringVar(&url, "url", "", "Monitoring-Basis-URL: AdminHelper-Server + /api/monitoring (z.B. https://srm.example.com/api/monitoring) (erforderlich)")
	cmd.Flags().StringVar(&apiKey, "api-key", "", "API-Key (erforderlich)")
	cmd.Flags().StringVar(&serverID, "server-id", "", "Server-ID (erforderlich)")
	cmd.Flags().StringVar(&services, "services", "", "Kommagetrennte Service-Namen")
	cmd.Flags().StringVar(&cacert, "cacert", "", "CA-Zertifikat")
	cmd.Flags().BoolVar(&insecure, "insecure", false, "SSL-Verifikation deaktivieren")
	cmd.MarkFlagRequired("url")
	cmd.MarkFlagRequired("api-key")
	cmd.MarkFlagRequired("server-id")
	return cmd
}

func monitorPushCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "push",
		Short: "Einmaliger Metriken-Push",
		RunE: func(cmd *cobra.Command, args []string) error {
			return monitor.Push(context.Background())
		},
	}
}

// --- Service subcommands ---

func serviceCmd() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "service",
		Short: "OS-Service verwalten",
	}
	cmd.AddCommand(serviceInstallCmd())
	cmd.AddCommand(serviceUninstallCmd())
	return cmd
}

func serviceInstallCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "install",
		Short: "Service registrieren und starten",
		RunE: func(cmd *cobra.Command, args []string) error {
			return service.Install()
		},
	}
}

func serviceUninstallCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "uninstall",
		Short: "Service deregistrieren",
		RunE: func(cmd *cobra.Command, args []string) error {
			return service.Uninstall()
		},
	}
}
