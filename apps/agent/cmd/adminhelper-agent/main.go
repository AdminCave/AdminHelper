// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package main

import (
	"bufio"
	"context"
	"fmt"
	"io"
	"os"
	"os/signal"
	"strings"

	"github.com/spf13/cobra"
	"golang.org/x/term"

	"adminhelper-agent/internal/config"
	"adminhelper-agent/internal/credentials"
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

// The terminal state and interrupt hooks of readTerminalRestoring; tests swap them.
var (
	termState       = term.GetState
	termRestore     = term.Restore
	notifyInterrupt = func(c chan<- os.Signal) { signal.Notify(c, os.Interrupt) }
	stopInterrupt   = func(c chan<- os.Signal) { signal.Stop(c) }
	exitProcess     = os.Exit
)

// readTerminalRestoring is readTerminal that puts the terminal state back when an
// interrupt (Ctrl-C) ends the process during the read: x/term restores the echo
// only when the read returns, and the default interrupt handling exits before that,
// leaving the shell without echo. Exits with 130, the shell's code for SIGINT.
func readTerminalRestoring(fd int, prompt io.Writer) ([]byte, error) {
	state, err := termState(fd)
	if err != nil {
		return readTerminal(fd)
	}
	sig := make(chan os.Signal, 1)
	notifyInterrupt(sig)
	done := make(chan struct{})
	defer func() {
		stopInterrupt(sig)
		close(done)
	}()
	go func() {
		select {
		case <-sig:
			_ = termRestore(fd, state)
			fmt.Fprintln(prompt)
			exitProcess(130)
		case <-done:
		}
	}()
	return readTerminal(fd)
}

// readStdinSecret returns the first line of in, trimmed, so a secret (what: "provision
// token", "API key") does not have to be a program argument (visible in the process
// list). On a terminal it prompts on prompt and reads without echo, so the secret stays
// off the screen. Its errors never quote what was read.
func readStdinSecret(in io.Reader, prompt io.Writer, what string) (string, error) {
	var line string
	if fd, ok := stdinTerminal(in); ok {
		fmt.Fprintf(prompt, "%s%s: ", strings.ToUpper(what[:1]), what[1:])
		b, err := readTerminalRestoring(fd, prompt)
		fmt.Fprintln(prompt)
		if err != nil {
			return "", fmt.Errorf("read the %s from the terminal: %w", what, err)
		}
		line = string(b[:min(len(b), maxStdinToken)])
	} else {
		var err error
		line, err = bufio.NewReader(io.LimitReader(in, maxStdinToken)).ReadString('\n')
		if err != nil && err != io.EOF {
			return "", fmt.Errorf("read the %s from stdin: %w", what, err)
		}
	}
	if token := strings.TrimSpace(line); token != "" {
		return token, nil
	}
	return "", fmt.Errorf("no %s on stdin", what)
}

func provisionCmd() *cobra.Command {
	var url, token, serverID, cacert, caFP string
	var insecure, tokenStdin bool

	cmd := &cobra.Command{
		Use:   "provision",
		Short: "Provision this host against an AdminHelper server (server API key + optional monitor + FRP)",
		RunE: func(cmd *cobra.Command, args []string) error {
			if tokenStdin {
				t, err := readStdinSecret(cmd.InOrStdin(), cmd.ErrOrStderr(), "provision token")
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
	cmd.AddCommand(monitorCredentialCmd())
	return cmd
}

func monitorInitCmd() *cobra.Command {
	var url, apiKey, serverID, services, cacert string
	var insecure, apiKeyStdin bool

	cmd := &cobra.Command{
		Use:   "init",
		Short: "Ersteinrichtung des Monitor-Agents",
		RunE: func(cmd *cobra.Command, args []string) error {
			if apiKeyStdin {
				k, err := readStdinSecret(cmd.InOrStdin(), cmd.ErrOrStderr(), "API key")
				if err != nil {
					return err
				}
				apiKey = k
			}
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
	cmd.Flags().StringVar(&apiKey, "api-key", "", "API key (or --api-key-stdin)")
	cmd.Flags().BoolVar(&apiKeyStdin, "api-key-stdin", false, "read the API key from stdin")
	cmd.Flags().StringVar(&serverID, "server-id", "", "Server-ID (erforderlich)")
	cmd.Flags().StringVar(&services, "services", "", "Kommagetrennte Service-Namen")
	cmd.Flags().StringVar(&cacert, "cacert", "", "CA-Zertifikat")
	cmd.Flags().BoolVar(&insecure, "insecure", false, "disable TLS verification for this call (TOFU-pins the presented cert)")
	cmd.MarkFlagRequired("url")
	cmd.MarkFlagsOneRequired("api-key", "api-key-stdin")
	cmd.MarkFlagsMutuallyExclusive("api-key", "api-key-stdin")
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

// monitorCredentialCmd manages the credentials the monitoring's probes present. They stay on this
// host: the monitoring service names a credential by its ref and learns only whether one is stored.
func monitorCredentialCmd() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "credential",
		Short: "Manage the credentials the monitoring probes present (kept on this host only)",
	}
	cmd.AddCommand(&cobra.Command{
		Use:   "set <ref>",
		Short: "Store the credential <ref>, read from stdin (on a terminal: prompted without echo)",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			ref := args[0]
			// Checked before the read, so a wrong ref does not cost typing the secret.
			if err := credentials.ValidRef(ref); err != nil {
				return err
			}
			secret, err := readStdinSecret(cmd.InOrStdin(), cmd.ErrOrStderr(), "credential")
			if err != nil {
				return err
			}
			if err := credentials.Set(cmd.Context(), config.MonitorCredentialsFile(), ref, secret); err != nil {
				return err
			}
			fmt.Fprintf(cmd.OutOrStdout(), "credential %s stored\n", ref)
			return nil
		},
	})
	cmd.AddCommand(&cobra.Command{
		Use:   "delete <ref>",
		Short: "Delete the credential <ref>",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			if err := credentials.Delete(cmd.Context(), config.MonitorCredentialsFile(), args[0]); err != nil {
				return err
			}
			fmt.Fprintf(cmd.OutOrStdout(), "credential %s deleted\n", args[0])
			return nil
		},
	})
	cmd.AddCommand(&cobra.Command{
		Use:   "list",
		Short: "List the refs of the stored credentials, never their values",
		Args:  cobra.NoArgs,
		RunE: func(cmd *cobra.Command, args []string) error {
			creds, err := credentials.Load(config.MonitorCredentialsFile())
			if err != nil {
				return err
			}
			for _, ref := range credentials.Refs(creds) {
				fmt.Fprintln(cmd.OutOrStdout(), ref)
			}
			return nil
		},
	})
	return cmd
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
