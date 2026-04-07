//go:build windows

package monitor

import "fmt"

// enableMonitorService registriert den Monitor im Windows Service.
// Im Normalbetrieb wird der Monitor-Push vom SRM-Agent Windows Service gesteuert.
func enableMonitorService() error {
	// TODO: Integration mit dem SRM-Agent Windows Service
	fmt.Println("Hinweis: Bitte srm-agent service install ausfuehren um den Windows-Dienst zu registrieren.")
	return nil
}
