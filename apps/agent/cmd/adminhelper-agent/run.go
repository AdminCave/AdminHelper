// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package main

import (
	"fmt"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/spf13/cobra"

	"adminhelper-agent/internal/frpc"
	"adminhelper-agent/internal/monitor"
)

const defaultInterval = 5 * time.Minute

func runCmd() *cobra.Command {
	var once bool

	cmd := &cobra.Command{
		Use:   "run",
		Short: "FRPC-Sync + Monitor-Push ausfuehren",
		Long:  "Ohne --once: Dauerbetrieb (alle 5 Minuten). Mit --once: einmaliger Durchlauf (fuer systemd-Timer).",
		RunE: func(cmd *cobra.Command, args []string) error {
			if once {
				runOnce()
				return nil
			}
			// On Windows, run under the SCM when started as a service (reports
			// SERVICE_RUNNING; otherwise sc start times out with error 1053).
			// Interactive runs and all other platforms fall through to runLoop.
			if handled, err := runService(); handled {
				return err
			}
			return runLoop()
		},
	}
	cmd.Flags().BoolVar(&once, "once", false, "Einmaliger Durchlauf (fuer systemd-Timer / Task Scheduler)")
	return cmd
}

func runLoop() error {
	fmt.Println("[adminhelper-agent] Starte Dauerbetrieb (Intervall: 5 Minuten)")

	sig := make(chan os.Signal, 1)
	signal.Notify(sig, syscall.SIGINT, syscall.SIGTERM)

	ticker := time.NewTicker(defaultInterval)
	defer ticker.Stop()

	runOnce()

	for {
		select {
		case <-ticker.C:
			runOnce()
		case s := <-sig:
			fmt.Printf("[adminhelper-agent] Signal %v empfangen, beende...\n", s)
			return nil
		}
	}
}

func runOnce() {
	if err := frpc.Sync(); err != nil {
		fmt.Fprintf(os.Stderr, "[adminhelper-agent] FRPC-Sync Fehler: %v\n", err)
	}
	if err := monitor.Push(); err != nil {
		fmt.Fprintf(os.Stderr, "[adminhelper-agent] Monitor-Push Fehler: %v\n", err)
	}
}
