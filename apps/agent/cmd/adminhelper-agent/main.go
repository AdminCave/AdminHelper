// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package main

import (
	"bufio"
	"context"
	"errors"
	"fmt"
	"io"
	"os"
	"strings"

	"github.com/spf13/cobra"
	"golang.org/x/term"

	"adminhelper-agent/internal/config"
	"adminhelper-agent/internal/diagnostics"
	"adminhelper-agent/internal/frpc"
	"adminhelper-agent/internal/logging"
	"adminhelper-agent/internal/monitor"
	"adminhelper-agent/internal/provision"
	"adminhelper-agent/internal/service"
)

var version = "dev"

func main() {
	frpc.SetAgentVersion(version)
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

// runProvision is provision.Run; tests swap it to see what the command hands over.
var runProvision = provision.Run

// maxStdinToken bounds what --token-stdin reads: a stdin that never sends a newline
// must not hold the command or grow its memory.
const maxStdinToken = 4 << 10

// stdinTerminal reports the descriptor of in if in is a terminal; tests swap it.
var stdinTerminal = func(in io.Reader) (int, bool) {
	f, ok := in.(*os.File)
	if !ok || !term.IsTerminal(int(f.Fd())) {
		return 0, false
	}
	return int(f.Fd()), true
}

// readTerminal reads a line from the terminal fd without echo; tests swap it.
var readTerminal = term.ReadPassword

// readStdinToken returns the first line of in, trimmed, so the token does not have to
// be a program argument (visible in the process list). On a terminal it prompts on
// prompt and reads without echo, so the token stays off the screen. Its errors never
// quote what was read.
func readStdinToken(in io.Reader, prompt io.Writer) (string, error) {
	var line string
	if fd, ok := stdinTerminal(in); ok {
		fmt.Fprint(prompt, "Provision token: ")
		b, err := readTerminal(fd)
		fmt.Fprintln(prompt)
		if err != nil {
			return "", fmt.Errorf("read the provision token from the terminal: %w", err)
		}
		line = string(b[:min(len(b), maxStdinToken)])
	} else {
		var err error
		line, err = bufio.NewReader(io.LimitReader(in, maxStdinToken)).ReadString('\n')
		if err != nil && err != io.EOF {
			return "", fmt.Errorf("read the provision token from stdin: %w", err)
		}
	}
	if token := strings.TrimSpace(line); token != "" {
		return token, nil
	}
	return "", errors.New("no provision token on stdin")
}

func provisionCmd() *cobra.Command {
	var url, token, serverID, cacert, caFP string
	var insecure, tokenStdin bool

	cmd := &cobra.Command{
		Use:   "provision",
		Short: "Provision this host against an AdminHelper server (server API key + optional monitor + FRP)",
		RunE: func(cmd *cobra.Command, args []string) error {
			if tokenStdin {
				t, err := readStdinToken(cmd.InOrStdin(), cmd.ErrOrStderr())
				if err != nil {
					return err
				}
				token = t
			}
			return runProvision(url, token, serverID, cacert, insecure, caFP)
		},
	}
	cmd.Flags().StringVar(&url, "url", "", "AdminHelper server URL (required)")
	cmd.Flags().StringVar(&token, "token", "", "provision token (or --token-stdin)")
	cmd.Flags().BoolVar(&tokenStdin, "token-stdin", false, "read the provision token from stdin")
	cmd.Flags().StringVar(&serverID, "server-id", "", "server ID (required)")
	cmd.Flags().StringVar(&cacert, "cacert", "", "CA certificate for a self-signed server")
	cmd.Flags().BoolVar(&insecure, "insecure", false, "disable TLS verification for this call (TOFU-pins the presented cert)")
	cmd.Flags().StringVar(&caFP, "ca-fp", "",
		"SHA-256 fingerprint of the internal CA (shown in the provisioning tab) — verifies the first contact instead of TOFU")
	cmd.MarkFlagRequired("url")
	cmd.MarkFlagsOneRequired("token", "token-stdin")
	cmd.MarkFlagsMutuallyExclusive("token", "token-stdin")
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
			return frpc.Sync(context.Background())
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
			return initMonitor(monitor.InitParams{
				URL:      url,
				APIKey:   apiKey,
				ServerID: serverID,
				Services: services,
				TLS:      config.TLSOpts{CACert: cacert, Insecure: insecure},
			})
		},
	}
	cmd.Flags().StringVar(&url, "url", "", "Monitoring-Basis-URL: AdminHelper-Server + /api/monitoring (z.B. https://srm.example.com/api/monitoring) (erforderlich)")
	cmd.Flags().StringVar(&apiKey, "api-key", "", "API-Key (erforderlich)")
	cmd.Flags().StringVar(&serverID, "server-id", "", "Server-ID (erforderlich)")
	cmd.Flags().StringVar(&services, "services", "", "Kommagetrennte Service-Namen")
	cmd.Flags().StringVar(&cacert, "cacert", "", "CA-Zertifikat")
	cmd.Flags().BoolVar(&insecure, "insecure", false, "disable TLS verification for this call (TOFU-pins the presented cert)")
	cmd.MarkFlagRequired("url")
	cmd.MarkFlagRequired("api-key")
	cmd.MarkFlagRequired("server-id")
	return cmd
}

// monitorInit and enableTimer are monitor.Init and service.EnableTimer; tests swap them, the real
// ones write the monitor config and run systemctl.
var (
	monitorInit = monitor.Init
	enableTimer = service.EnableTimer
)

// initMonitor sets the monitor up and only then enables the agent timer (R-0641): a setup that
// failed enables nothing, and a timer that cannot be enabled is a warning, the setup stands.
func initMonitor(p monitor.InitParams) error {
	if err := monitorInit(p); err != nil {
		return err
	}
	if err := enableTimer(); err != nil {
		logger.Warnf("Service konnte nicht aktiviert werden: %v", err)
		logger.Warnf("Bitte manuell aktivieren")
	}
	return nil
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
