package main

import (
	"fmt"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/spf13/cobra"

	"srm-agent/internal/frpc"
	"srm-agent/internal/monitor"
)

const defaultInterval = 5 * time.Minute

func runCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "run",
		Short: "Dauerbetrieb: FRPC-Sync + Monitor-Push alle 5 Minuten",
		RunE: func(cmd *cobra.Command, args []string) error {
			return runLoop()
		},
	}
}

func runLoop() error {
	fmt.Println("[srm-agent] Starte Dauerbetrieb (Intervall: 5 Minuten)")

	// Signal-Handling fuer sauberes Beenden
	sig := make(chan os.Signal, 1)
	signal.Notify(sig, syscall.SIGINT, syscall.SIGTERM)

	ticker := time.NewTicker(defaultInterval)
	defer ticker.Stop()

	// Sofort beim Start einmal ausfuehren
	runOnce()

	for {
		select {
		case <-ticker.C:
			runOnce()
		case s := <-sig:
			fmt.Printf("[srm-agent] Signal %v empfangen, beende...\n", s)
			return nil
		}
	}
}

func runOnce() {
	// FRPC Sync (Fehler werden geloggt, nicht abgebrochen)
	if err := frpc.Sync(); err != nil {
		fmt.Fprintf(os.Stderr, "[srm-agent] FRPC-Sync Fehler: %v\n", err)
	}

	// Monitor Push
	if err := monitor.Push(); err != nil {
		fmt.Fprintf(os.Stderr, "[srm-agent] Monitor-Push Fehler: %v\n", err)
	}
}
