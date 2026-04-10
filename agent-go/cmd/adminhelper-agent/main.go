package main

import (
	"fmt"
	"os"

	"github.com/spf13/cobra"
)

var version = "dev"

func main() {
	root := &cobra.Command{
		Use:   "adminhelper-agent",
		Short: "AdminHelper Agent — FRPC Sync + Monitoring (Linux & Windows)",
	}

	root.AddCommand(versionCmd())
	root.AddCommand(runCmd())
	root.AddCommand(frpcCmd())
	root.AddCommand(monitorCmd())
	root.AddCommand(serviceCmd())

	if err := root.Execute(); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
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

// --- FRPC Subcommands ---

func frpcCmd() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "frpc",
		Short: "FRPC Config Sync",
	}
	cmd.AddCommand(frpcInitCmd())
	cmd.AddCommand(frpcSyncCmd())
	return cmd
}

func frpcInitCmd() *cobra.Command {
	var url, token, serverID, cacert string
	var insecure bool

	cmd := &cobra.Command{
		Use:   "init",
		Short: "Ersteinrichtung mit Provision-Token",
		RunE: func(cmd *cobra.Command, args []string) error {
			return frpcInitRun(url, token, serverID, cacert, insecure)
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

func frpcSyncCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "sync",
		Short: "Einmaliger Config-Sync",
		RunE: func(cmd *cobra.Command, args []string) error {
			return frpcSyncRun()
		},
	}
}

// --- Monitor Subcommands ---

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
			return monitorInitRun(url, apiKey, serverID, services, cacert, insecure)
		},
	}
	cmd.Flags().StringVar(&url, "url", "", "Monitoring-Service URL (erforderlich)")
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
			return monitorPushRun()
		},
	}
}

// --- Service Subcommands ---

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
			return serviceInstallRun()
		},
	}
}

func serviceUninstallCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "uninstall",
		Short: "Service deregistrieren",
		RunE: func(cmd *cobra.Command, args []string) error {
			return serviceUninstallRun()
		},
	}
}
