// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build windows

package selfupdate

import (
	"context"
	"errors"
	"fmt"
	"math/rand/v2"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"syscall"
	"time"

	"golang.org/x/sys/windows"

	"adminhelper-agent/internal/config"
	"adminhelper-agent/internal/logging"
	"adminhelper-agent/internal/service"
)

var logger = logging.For("selfupdate")

// Files below the update folder of the program directory. That folder grants writing only to
// SYSTEM and the Administrators, like its parent: the helper runs from the stage.
const (
	updateDirName = "update"
	stageDirName  = "stage"
	stateFile     = "state.json"
	healthyFile   = "healthy"
	failedFile    = "failed"
)

// Seams for the tests, which must not touch the host's program directory or service.
var (
	updateDir = func() (string, error) {
		dir, err := service.ProgramDir()
		if err != nil {
			return "", err
		}
		return filepath.Join(dir, updateDirName), nil
	}
	checkNow    = check
	startHelper = startDetached
)

// Waits of the self-update. The first cycle of the new service ends within its run budget
// (4 min); the check may download two binaries over a slow line.
const (
	tickEvery     = time.Hour
	fetchTimeout  = 10 * time.Minute
	healthTimeout = 15 * time.Minute
	healthPoll    = 5 * time.Second
)

// Loop runs in the agent service until ctx ends: once an hour it looks whether the daily check is
// due. A build that is no release (dev, git describe) never updates itself.
func Loop(ctx context.Context, current string) {
	if _, ok := ParseVersion(current); !ok {
		logger.Infof("self-update off: %s is no release build", current)
		return
	}
	t := time.NewTicker(tickEvery)
	defer t.Stop()
	for {
		tick(ctx, current, time.Now())
		select {
		case <-ctx.Done():
			return
		case <-t.C:
		}
	}
}

// tick moves the schedule on and runs the check when it is due.
func tick(ctx context.Context, current string, now time.Time) {
	conf, err := config.LoadKeyValue(config.FrpAdminHelperConf())
	if err != nil {
		// Not provisioned yet: there is no server to fetch from.
		return
	}
	if !Enabled(conf) {
		return
	}
	dir, err := updateDir()
	if err != nil {
		logger.Warnf("self-update: %v", err)
		return
	}
	if err := config.EnsureSecureDir(dir); err != nil {
		logger.Warnf("self-update: create %s: %v", dir, err)
		return
	}
	statePath := filepath.Join(dir, stateFile)
	st, err := LoadState(statePath)
	if err != nil {
		logger.Warnf("self-update: read %s, starting a new schedule: %v", statePath, err)
	}
	st, due := Tick(now, st, func() time.Duration { return rand.N(CheckJitter) })
	// Saved before the check, so that a check that crashes the service is not repeated at once.
	if err := SaveState(statePath, st); err != nil {
		logger.Warnf("self-update: write %s: %v", statePath, err)
		return
	}
	if due {
		checkNow(ctx, current, dir)
	}
}

// check fetches a newer signed release into the stage and hands over to it.
func check(ctx context.Context, current, dir string) {
	cfg, err := config.LoadFrpcConfig()
	if err != nil {
		logger.Warnf("self-update: %v", err)
		return
	}
	repo, err := RepoURL(cfg.AdminHelperURL)
	if err != nil {
		logger.Warnf("self-update: %v", err)
		return
	}
	// :8445 serves the same certificate as :443, so the agent's own trust applies. The
	// signature over SHA256SUMS, not the transport, makes a release genuine.
	client, err := updateClient(config.AgentPkiDir(), cfg.CACert, cfg.Insecure, fetchTimeout)
	if err != nil {
		logger.Warnf("self-update: %v", err)
		return
	}
	failed, _ := os.ReadFile(filepath.Join(dir, failedFile))
	ctx, cancel := context.WithTimeout(ctx, fetchTimeout)
	defer cancel()
	stage := filepath.Join(dir, stageDirName)
	version, err := Fetch(ctx, Options{
		RepoURL: repo, Client: client, PublicKey: ReleasePublicKey,
		Current: current, Skip: strings.TrimSpace(string(failed)), StageDir: stage,
	})
	if errors.Is(err, ErrUpToDate) {
		return
	}
	if err != nil {
		logger.Warnf("self-update check: %v", err)
		return
	}
	logger.Infof("self-update: agent %s verified, handing over to it", version)
	if err := startHelper(filepath.Join(stage, AgentFile), version); err != nil {
		logger.Errorf("self-update: start the update helper: %v", err)
	}
}

// startDetached starts the staged agent as the update helper. It must outlive the service it
// stops: no console, its own process group, and not waited for.
func startDetached(exe, version string) error {
	cmd := exec.Command(exe, "self-update-apply", version)
	cmd.SysProcAttr = &syscall.SysProcAttr{
		CreationFlags: windows.DETACHED_PROCESS | windows.CREATE_NEW_PROCESS_GROUP,
	}
	if err := cmd.Start(); err != nil {
		return err
	}
	return cmd.Process.Release()
}

// MarkHealthy records that the service of version finished a cycle; the update helper waits for
// it. Without an update folder no update is pending, and nothing is written.
func MarkHealthy(version string) {
	dir, err := updateDir()
	if err != nil {
		return
	}
	if _, err := os.Stat(dir); err != nil {
		return
	}
	if err := writeMarker(filepath.Join(dir, healthyFile), version); err != nil {
		logger.Warnf("self-update: write the health marker: %v", err)
	}
}

// ApplyStaged swaps the installed agent for the staged release version. Only the staged agent
// runs it (self-update-apply, started by the service), so that what it installs is itself.
func ApplyStaged(version string) error {
	if _, ok := ParseVersion(version); !ok {
		return fmt.Errorf("selfupdate: %q is no release version", version)
	}
	dir, err := updateDir()
	if err != nil {
		return err
	}
	stage := filepath.Join(dir, stageDirName)
	agent := filepath.Join(stage, AgentFile)
	self, err := os.Executable()
	if err != nil {
		return err
	}
	if !strings.EqualFold(filepath.Clean(self), filepath.Clean(agent)) {
		return fmt.Errorf("selfupdate: self-update-apply runs only from %s", agent)
	}
	healthy := filepath.Join(dir, healthyFile)
	return Apply(ApplyHooks{
		ClearHealthy: func() error {
			if err := os.Remove(healthy); err != nil && !errors.Is(err, os.ErrNotExist) {
				return err
			}
			return nil
		},
		Backup:      service.Backup,
		Install:     func() error { return service.InstallFrom(agent) },
		WaitHealthy: func(v string) bool { return waitHealthy(healthy, v, healthTimeout, healthPoll) },
		Restore:     service.Restore,
		MarkFailed: func(v string) {
			if err := os.WriteFile(filepath.Join(dir, failedFile), []byte(v+"\n"), 0o600); err != nil {
				logger.Warnf("self-update: remember the failed version: %v", err)
			}
		},
		Logf: logger.Infof,
	}, version)
}
