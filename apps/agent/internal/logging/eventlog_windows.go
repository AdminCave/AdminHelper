// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build windows

package logging

import (
	"golang.org/x/sys/windows/svc"
	"golang.org/x/sys/windows/svc/eventlog"
)

// EventSource is the source under which the agent writes to the Windows Application
// log. Without a registration of the source, Windows still logs the entry there, but
// without a description.
const EventSource = "AdminHelper-Agent"

// unsecuredLogDirEventID is the event ID of the warning that the log directory cannot
// be secured. With EventCreate.exe as the message file it must lie between 1 and 1000.
const unsecuredLogDirEventID = 1

// platformReporter returns a report to the Application log under EventSource when the
// agent runs as a Windows service, and nil in an interactive run.
func platformReporter() reportFunc {
	if isSvc, err := svc.IsWindowsService(); err != nil || !isSvc {
		return nil
	}
	return eventLogWarning(EventSource)
}

// eventLogWarning returns a reportFunc that writes the message as one warning under
// source to the Application log.
func eventLogWarning(source string) reportFunc {
	return func(msg string) error {
		l, err := eventlog.Open(source)
		if err != nil {
			return err
		}
		defer l.Close()
		return l.Warning(unsecuredLogDirEventID, msg)
	}
}
