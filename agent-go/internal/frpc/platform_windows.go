//go:build windows

package frpc

import (
	"fmt"
	"os/exec"
)

// enableFrpcService startet den frpc-Prozess unter Windows.
// Im Service-Modus wird frpc vom AdminHelper-Agent-Service selbst verwaltet.
func enableFrpcService() error {
	// frpc als Hintergrundprozess starten — im Service-Modus uebernimmt der
	// Windows Service das Management.
	// TODO: Integration mit Windows Service Manager
	return exec.Command("sc", "start", "frpc").Run()
}

// restartFrpc startet frpc unter Windows neu.
func restartFrpc() error {
	if err := exec.Command("sc", "stop", "frpc").Run(); err != nil {
		fmt.Printf("[adminhelper-agent-frpc] WARNUNG: frpc stop: %v\n", err)
	}
	return exec.Command("sc", "start", "frpc").Run()
}
