// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build windows

package service

import (
	"errors"
	"fmt"
	"os"
	"path/filepath"

	"golang.org/x/sys/windows/svc/mgr"

	"adminhelper-agent/internal/logging"
)

// What the self-update (internal/selfupdate) needs of the installed service.

// ProgramDir returns the agent's program directory.
func ProgramDir() (string, error) { return programDir() }

// InstallFrom installs the agent binary at agent and the frpc.exe beside it, like service install
// run from that folder. The self-update helper calls it from its stage.
func InstallFrom(agent string) error {
	dir, err := programDir()
	if err != nil {
		return err
	}
	return install(installTarget{
		name: serviceName, displayName: serviceDisplayName, eventSource: logging.EventSource,
		dir: dir, self: agent,
	})
}

// backupSuffix marks the copies Backup keeps beside the installed files.
const backupSuffix = ".old"

// Backup copies the installed agent and frpc.exe to .old beside them, for Restore. Without an
// installed frpc.exe a stale frpc.exe.old goes, so that Restore brings back none either.
func Backup() error {
	dir, err := programDir()
	if err != nil {
		return err
	}
	return backup(dir)
}

func backup(dir string) error {
	for _, name := range []string{agentExeName, frpcExeName} {
		data, err := os.ReadFile(filepath.Join(dir, name))
		if errors.Is(err, os.ErrNotExist) && name == frpcExeName {
			if err := os.Remove(filepath.Join(dir, name+backupSuffix)); err != nil && !errors.Is(err, os.ErrNotExist) {
				return err
			}
			continue
		}
		if err != nil {
			return fmt.Errorf("read %s: %w", name, err)
		}
		if err := placeFile(filepath.Join(dir, name+backupSuffix), data); err != nil {
			return err
		}
	}
	return nil
}

// Restore stops the agent service, puts the files saved by Backup back and starts it. It does not
// go through install: the restored agent pins its own frpc, which the pin of the failed release
// would refuse.
func Restore() error {
	dir, err := programDir()
	if err != nil {
		return err
	}
	return restore(serviceName, dir)
}

func restore(serviceName, dir string) error {
	m, err := mgr.Connect()
	if err != nil {
		return fmt.Errorf("connect to the service control manager: %w", err)
	}
	defer m.Disconnect()
	s, err := m.OpenService(serviceName)
	if err != nil {
		return fmt.Errorf("open the service %s: %w", serviceName, err)
	}
	defer s.Close()
	if err := stopService(s); err != nil {
		return fmt.Errorf("stop the agent service: %w", err)
	}
	var errs []error
	for _, name := range []string{agentExeName, frpcExeName} {
		data, err := os.ReadFile(filepath.Join(dir, name+backupSuffix))
		if errors.Is(err, os.ErrNotExist) && name == frpcExeName {
			continue
		}
		if err != nil {
			errs = append(errs, fmt.Errorf("read the saved %s: %w", name, err))
			continue
		}
		if err := placeFile(filepath.Join(dir, name), data); err != nil {
			errs = append(errs, err)
		}
	}
	// Started even after a failed file: the service then runs what lies there rather than nothing.
	if err := s.Start(); err != nil {
		errs = append(errs, fmt.Errorf("start the agent service: %w", err))
	}
	return errors.Join(errs...)
}
