// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build windows

package service

import (
	"bytes"
	"crypto/sha256"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"syscall"
	"time"

	"golang.org/x/sys/windows"
	"golang.org/x/sys/windows/registry"
	"golang.org/x/sys/windows/svc"
	"golang.org/x/sys/windows/svc/eventlog"
	"golang.org/x/sys/windows/svc/mgr"

	"adminhelper-agent/internal/config"
	"adminhelper-agent/internal/frpc"
	"adminhelper-agent/internal/logging"
)

const serviceName = "AdminHelper-Agent"
const serviceDisplayName = "AdminHelper Agent — FRPC Sync + Monitoring"

// prepareInstallDir creates the program directory, or takes over an existing one, with the
// protected DACL of the data directory: the service runs its binaries from there as
// LocalSystem, so only SYSTEM and the Administrators may write to it.
func prepareInstallDir(dir string) error {
	return config.EnsureSecureDir(dir)
}

// programDirName is the agent's own folder under Program Files. "AdminHelper" is the MSI folder of
// the desktop app (its productName), which a protected DACL would close to its users.
const programDirName = "AdminHelper Agent"

// programDir returns the agent's program directory. The Program Files folder comes from the
// known-folder API, not from %ProgramFiles%, which the calling environment can set.
func programDir() (string, error) {
	pf, err := windows.KnownFolderPath(windows.FOLDERID_ProgramFiles, 0)
	if err != nil {
		return "", fmt.Errorf("Program Files folder: %w", err)
	}
	return filepath.Join(pf, programDirName), nil
}

// agentExeName and frpcExeName are the files of the program directory; frpc runs from beside the
// agent (frpc.frpcExePath).
const (
	agentExeName = "adminhelper-agent.exe"
	frpcExeName  = "frpc.exe"
)

// frpcSourceNames are the names under which frpc.exe may lie beside the binary that installs: the
// release asset and the plain name.
var frpcSourceNames = []string{"frpc-windows-x86_64.exe", frpcExeName}

// frpcWantSHA256 is the hash frpc.exe must have before it is installed. A var only for tests.
var frpcWantSHA256 = frpc.ExeSHA256

// Waits of an update: the agent service needs up to its own stop wait plus frpc's to stop; its
// process, and with it the job that kills frpc, ends shortly after the service reports Stopped.
// A var for tests.
var (
	stopTimeout     = 90 * time.Second
	processExitWait = 30 * time.Second
	lockedFileWait  = 15 * time.Second
)

// installTarget is what an install puts where. Install fills it for the agent; the tests use a
// service name, event source and program directory of their own.
type installTarget struct {
	name, displayName, eventSource string
	// dir is the program directory, self the binary that installs: its folder holds frpc.exe.
	dir, self string
}

// Install registers the AdminHelper agent as a native Windows service, or updates the registered
// one in place: it stops the service, replaces the agent and frpc.exe, points the service at the
// program directory and starts it again. An install in an earlier folder moves there.
func Install() error {
	self, err := os.Executable()
	if err != nil {
		return fmt.Errorf("path of the running binary: %w", err)
	}
	dir, err := programDir()
	if err != nil {
		return err
	}
	return install(installTarget{
		name: serviceName, displayName: serviceDisplayName, eventSource: logging.EventSource,
		dir: dir, self: self,
	})
}

func install(t installTarget) error {
	agentDest := filepath.Join(t.dir, agentExeName)
	frpcDest := filepath.Join(t.dir, frpcExeName)
	// Everything is read and checked before the service stops: a wrong frpc.exe changes nothing.
	var agent []byte
	if !samePath(t.self, agentDest) {
		data, err := os.ReadFile(t.self)
		if err != nil {
			return fmt.Errorf("read the agent binary: %w", err)
		}
		agent = data
	}
	frpcData, frpcFound, err := readFrpcSource(filepath.Dir(t.self), frpcDest)
	if err != nil {
		return err
	}
	if !frpcFound {
		if _, err := os.Stat(frpcDest); err == nil {
			fmt.Printf("WARNING: no frpc.exe beside %s; %s stays as it is.\n", t.self, frpcDest)
		} else {
			fmt.Printf("WARNING: no frpc.exe beside %s; the agent runs without the tunnel until frpc %s lies in %s.\n",
				t.self, frpc.PinnedVersion, t.dir)
		}
	}

	m, err := mgr.Connect()
	if err != nil {
		return fmt.Errorf("connect to the service control manager: %w", err)
	}
	defer m.Disconnect()
	var s *mgr.Service
	defer func() {
		if s != nil {
			s.Close()
		}
	}()
	err = runInstall(installHooks{
		lookup: func() (bool, string, error) {
			found, err := m.OpenService(t.name)
			if errors.Is(err, windows.ERROR_SERVICE_DOES_NOT_EXIST) {
				return false, "", nil
			}
			if err != nil {
				return false, "", fmt.Errorf("open the service %s: %w", t.name, err)
			}
			s = found
			cfg, err := s.Config()
			if err != nil {
				return false, "", fmt.Errorf("read the configuration of %s: %w", t.name, err)
			}
			return true, serviceBinary(cfg.BinaryPathName), nil
		},
		stop: func() error { return stopService(s) },
		place: func() error {
			if err := prepareInstallDir(t.dir); err != nil {
				return fmt.Errorf("create the program directory: %w", err)
			}
			if agent != nil {
				if err := placeFile(agentDest, agent); err != nil {
					return err
				}
			}
			if frpcData != nil {
				return placeFile(frpcDest, frpcData)
			}
			return nil
		},
		create: func() error {
			created, err := m.CreateService(t.name, agentDest, mgr.Config{
				DisplayName: t.displayName, StartType: mgr.StartAutomatic, ServiceStartName: "LocalSystem",
			}, "run")
			if err != nil {
				return fmt.Errorf("register the service %s: %w", t.name, err)
			}
			s = created
			return nil
		},
		update: func() error {
			cfg, err := s.Config()
			if err != nil {
				return fmt.Errorf("read the configuration of %s: %w", t.name, err)
			}
			cfg.BinaryPathName = syscall.EscapeArg(agentDest) + " run"
			cfg.DisplayName = t.displayName
			cfg.StartType = mgr.StartAutomatic
			cfg.ServiceStartName = "LocalSystem"
			if err := s.UpdateConfig(cfg); err != nil {
				return fmt.Errorf("update the service %s: %w", t.name, err)
			}
			return nil
		},
		extras: func() {
			// Without a registered source, Windows keeps the agent's entries in the Application
			// log without a description.
			if err := registerEventSource(t.eventSource); err != nil {
				fmt.Printf("WARNING: register the event source %s: %v\n", t.eventSource, err)
			}
			// A missing restart policy would stay invisible otherwise (4.85).
			restart := mgr.RecoveryAction{Type: mgr.ServiceRestart, Delay: 60 * time.Second}
			if err := s.SetRecoveryActions([]mgr.RecoveryAction{restart, restart, restart}, 86400); err != nil {
				fmt.Printf("WARNING: set the recovery actions: %v\n", err)
			}
		},
		removeOld: removeOldAgent,
		start:     func() error { return s.Start() },
		warnf:     func(format string, args ...any) { fmt.Printf("WARNING: "+format+"\n", args...) },
	}, agentDest)
	if err != nil {
		return err
	}
	fmt.Printf("Windows service %s installed in %s.\n", t.name, t.dir)
	return nil
}

// readFrpcSource reads frpc.exe from dir and checks it against the pin. found is false if dir holds
// none; data is nil if the file found is dest itself.
func readFrpcSource(dir, dest string) (data []byte, found bool, err error) {
	for _, name := range frpcSourceNames {
		path := filepath.Join(dir, name)
		if samePath(path, dest) {
			if _, err := os.Stat(path); err == nil {
				return nil, true, nil
			}
			continue
		}
		data, err := os.ReadFile(path)
		if errors.Is(err, os.ErrNotExist) {
			continue
		}
		if err != nil {
			return nil, false, fmt.Errorf("read %s: %w", path, err)
		}
		if got := fmt.Sprintf("%x", sha256.Sum256(data)); got != frpcWantSHA256 {
			return nil, false, fmt.Errorf("%s has SHA-256 %s, not that of frpc %s (%s); nothing was changed",
				path, got, frpc.PinnedVersion, frpcWantSHA256)
		}
		return data, true, nil
	}
	return nil, false, nil
}

// placeFile puts data at dest, owned by the Administrators from the start. A file with the same
// content stays. Shortly after the service stopped, Windows may still hold dest for the ending
// process (the agent, or frpc killed with its job): such a lock is waited out.
func placeFile(dest string, data []byte) error {
	if old, err := os.ReadFile(dest); err == nil && bytes.Equal(old, data) {
		return nil
	}
	deadline := time.Now().Add(lockedFileWait)
	for {
		err := config.WriteFileOwnedByAdministrators(dest, data)
		if err == nil {
			return nil
		}
		locked := errors.Is(err, windows.ERROR_ACCESS_DENIED) || errors.Is(err, windows.ERROR_SHARING_VIOLATION)
		if !locked || time.Now().After(deadline) {
			return fmt.Errorf("write %s: %w", dest, err)
		}
		time.Sleep(250 * time.Millisecond)
	}
}

// stopService stops s and waits until its process has ended, so that its files can be replaced.
func stopService(s *mgr.Service) error {
	st, err := s.Query()
	if err != nil {
		return err
	}
	if st.State == svc.Stopped {
		return nil
	}
	var proc windows.Handle
	if st.ProcessId != 0 {
		// Opened before the stop, so that the handle still names this process when it has ended.
		if h, err := windows.OpenProcess(windows.SYNCHRONIZE, false, st.ProcessId); err == nil {
			proc = h
			defer windows.CloseHandle(proc)
		}
	}
	if st.State != svc.StopPending {
		if _, err := s.Control(svc.Stop); err != nil && !errors.Is(err, windows.ERROR_SERVICE_NOT_ACTIVE) {
			return err
		}
	}
	deadline := time.Now().Add(stopTimeout)
	for {
		st, err := s.Query()
		if err != nil {
			return err
		}
		if st.State == svc.Stopped {
			break
		}
		if time.Now().After(deadline) {
			return fmt.Errorf("the service did not stop within %s", stopTimeout)
		}
		time.Sleep(250 * time.Millisecond)
	}
	if proc != 0 {
		ev, err := windows.WaitForSingleObject(proc, uint32(processExitWait/time.Millisecond))
		if err != nil {
			return fmt.Errorf("wait for the agent process: %w", err)
		}
		if ev != windows.WAIT_OBJECT_0 {
			return fmt.Errorf("the agent process %d has not ended within %s", st.ProcessId, processExitWait)
		}
	}
	return nil
}

// removeOldAgent deletes the agent binary of an earlier install. Its folder stays: the earlier
// folder "AdminHelper" belongs to the desktop app.
func removeOldAgent(binary string) error {
	if !strings.EqualFold(filepath.Base(binary), agentExeName) {
		return fmt.Errorf("%s is no agent binary; left in place", binary)
	}
	if err := os.Remove(binary); err != nil && !errors.Is(err, os.ErrNotExist) {
		return err
	}
	return nil
}

// logger tags the hint of EnableTimer, so that it lands in agent.log and the diagnostics, not
// only on stdout.
var logger = logging.For("service")

// EnableTimer has no timer to enable on Windows: the agent's Windows service (service install)
// runs the cycles. It only gives that hint.
func EnableTimer() error {
	logger.Infof("Windows: Monitor-Push laeuft ueber den Agent-Dienst — bitte 'adminhelper-agent service install' ausfuehren.")
	return nil
}

// Uninstall stops the Windows service, waits for its process and deregisters it. A service that
// is not registered is no error, so that a later uninstall --purge still removes the files.
func Uninstall() error {
	return uninstall(serviceName, logging.EventSource)
}

func uninstall(name, eventSource string) error {
	m, err := mgr.Connect()
	if err != nil {
		return fmt.Errorf("connect to the service control manager: %w", err)
	}
	defer m.Disconnect()
	s, err := m.OpenService(name)
	switch {
	case errors.Is(err, windows.ERROR_SERVICE_DOES_NOT_EXIST):
		fmt.Printf("Windows service %s is not installed.\n", name)
	case err != nil:
		return fmt.Errorf("open the service %s: %w", name, err)
	default:
		defer s.Close()
		if err := stopService(s); err != nil {
			fmt.Printf("WARNING: stop the service %s: %v\n", name, err)
		}
		if err := s.Delete(); err != nil {
			return fmt.Errorf("remove the service %s: %w", name, err)
		}
		fmt.Printf("Windows service %s uninstalled.\n", name)
	}
	if err := removeEventSource(eventSource); err != nil {
		fmt.Printf("WARNING: remove the event source %s: %v\n", eventSource, err)
	}
	return nil
}

// PurgeSupported reports that uninstall --purge removes the files on this platform.
const PurgeSupported = true

// dataDirName is the agent's folder under ProgramData; frp and logs lie inside it.
const dataDirName = "AdminHelper"

// Purge removes the program directory and the data directory after an uninstall. Both come from
// the known-folder API, never from the environment: a user variable (ADMINHELPER_*_DIR,
// ProgramData), which an elevated console inherits, must not choose what an administrator
// deletes. The running binary cannot delete itself: if it lies in a directory to remove, Windows
// deletes it and the emptied directory at the next restart.
func Purge() error {
	dir, err := programDir()
	if err != nil {
		return err
	}
	pd, err := windows.KnownFolderPath(windows.FOLDERID_ProgramData, 0)
	if err != nil {
		return fmt.Errorf("ProgramData folder: %w", err)
	}
	for _, v := range []string{"ADMINHELPER_MONITOR_DIR", "ADMINHELPER_FRP_DIR", "ADMINHELPER_LOG_DIR"} {
		if os.Getenv(v) != "" {
			fmt.Printf("NOTE: %s is set; --purge removes only the default folders, not that one.\n", v)
		}
	}
	self, err := os.Executable()
	if err != nil {
		return fmt.Errorf("path of the running binary: %w", err)
	}
	return purge([]string{dir, filepath.Join(pd, dataDirName)}, self)
}

// purgeable reports whether dir may be purged at all: an absolute path below a volume root.
func purgeable(dir string) bool {
	dir = filepath.Clean(dir)
	if !filepath.IsAbs(dir) {
		return false
	}
	return strings.Trim(dir[len(filepath.VolumeName(dir)):], `\/`) != ""
}

func purge(dirs []string, self string) error {
	var errs []error
	for _, dir := range dirs {
		dir = filepath.Clean(dir)
		if !purgeable(dir) {
			errs = append(errs, fmt.Errorf("%q is no directory to purge", dir))
			continue
		}
		owned, err := ownedByAdministrators(dir)
		if errors.Is(err, os.ErrNotExist) {
			continue
		}
		if err != nil {
			errs = append(errs, err)
			continue
		}
		// The agent's folders belong to the Administrators (config.EnsureSecureDir); another owner
		// means a folder the agent did not set up.
		if !owned {
			errs = append(errs, fmt.Errorf("%s does not belong to the Administrators or SYSTEM; left in place", dir))
			continue
		}
		if !samePath(filepath.Dir(self), dir) {
			if err := os.RemoveAll(dir); err != nil {
				errs = append(errs, err)
			} else {
				fmt.Printf("Removed %s.\n", dir)
			}
			continue
		}
		if err := removeAllBut(dir, self); err != nil {
			errs = append(errs, err)
			continue
		}
		fmt.Printf("Removed %s except the running %s; Windows deletes both at the next restart.\n",
			dir, filepath.Base(self))
	}
	return errors.Join(errs...)
}

// ownedByAdministrators reports whether the Administrators or SYSTEM own the directory dir.
func ownedByAdministrators(dir string) (bool, error) {
	fi, err := os.Lstat(dir)
	if err != nil {
		return false, err
	}
	if !fi.IsDir() {
		return false, fmt.Errorf("%s is no directory", dir)
	}
	sd, err := windows.GetNamedSecurityInfo(dir, windows.SE_FILE_OBJECT, windows.OWNER_SECURITY_INFORMATION)
	if err != nil {
		return false, fmt.Errorf("owner of %s: %w", dir, err)
	}
	owner, _, err := sd.Owner()
	if err != nil {
		return false, fmt.Errorf("owner of %s: %w", dir, err)
	}
	return owner.IsWellKnown(windows.WinBuiltinAdministratorsSid) || owner.IsWellKnown(windows.WinLocalSystemSid), nil
}

// removeAllBut empties dir except the file keep, and has Windows delete keep and dir at the next
// restart.
func removeAllBut(dir, keep string) error {
	entries, err := os.ReadDir(dir)
	if err != nil {
		return err
	}
	for _, e := range entries {
		path := filepath.Join(dir, e.Name())
		if samePath(path, keep) {
			continue
		}
		if err := os.RemoveAll(path); err != nil {
			return err
		}
	}
	for _, path := range []string{keep, dir} {
		name, err := windows.UTF16PtrFromString(path)
		if err != nil {
			return err
		}
		if err := windows.MoveFileEx(name, nil, windows.MOVEFILE_DELAY_UNTIL_REBOOT); err != nil {
			return fmt.Errorf("delete %s at the next restart: %w", path, err)
		}
	}
	return nil
}

// eventSourcesKey is the registry key below HKEY_LOCAL_MACHINE that holds the sources
// of the Application log; eventlog installs and removes them there.
const eventSourcesKey = `SYSTEM\CurrentControlSet\Services\EventLog\Application`

// registerEventSource registers source for the Application log with EventCreate.exe as
// its message file, for errors, warnings and information. A source that is already
// registered is no error and stays as it is.
func registerEventSource(source string) error {
	// eventlog.Install reports an existing source only as an error text, so look first.
	if k, err := registry.OpenKey(registry.LOCAL_MACHINE, eventSourcesKey+`\`+source, registry.QUERY_VALUE); err == nil {
		k.Close()
		return nil
	}
	return eventlog.InstallAsEventCreate(source, eventlog.Error|eventlog.Warning|eventlog.Info)
}

// removeEventSource removes the registration of source from the Application log. A
// source that is not registered is no error.
func removeEventSource(source string) error {
	if err := eventlog.Remove(source); err != nil && !errors.Is(err, registry.ErrNotExist) {
		return err
	}
	return nil
}
