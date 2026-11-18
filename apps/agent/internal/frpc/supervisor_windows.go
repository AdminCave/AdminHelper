// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build windows

package frpc

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"sync"
	"sync/atomic"
	"syscall"
	"time"
	"unsafe"

	"golang.org/x/sys/windows"

	"adminhelper-agent/internal/config"
)

// On Windows frpc runs as a child of the agent service, not as a service of its own: the
// supervisor starts frpc.exe from the agent's program folder, restarts it when it ends and stops
// it with the service. The child sits in a job object that kills it when the job handle closes,
// so it also ends when the agent process dies.

// errNotSupervised is what the frpc hooks report outside the agent service: only the service
// process runs frpc, and a hook that claimed success there would hide dead tunnels (R-0708).
var errNotSupervised = errors.New("frpc runs only under the AdminHelper-Agent service; this process does not run it")

// current is the supervisor of the service process, nil in every other process.
var current atomic.Pointer[supervisor]

// frpcExePath is frpc.exe beside the agent binary, where service install puts it. A var for tests.
var frpcExePath = func() (string, error) {
	exe, err := os.Executable()
	if err != nil {
		return "", err
	}
	return filepath.Join(filepath.Dir(exe), "frpc.exe"), nil
}

// frpcWantSHA256 is the pinned hash frpc.exe must have. A var only so tests can run a fake frpc.
var frpcWantSHA256 = frpcExeSHA256

// Restart backoff after frpc ends: from restartMin, doubled up to restartMax; a run of at least
// restartMax starts over at restartMin. Vars for tests.
var (
	restartMin = time.Second
	restartMax = time.Minute
)

// frpcStopWait bounds the wait for a killed frpc to end.
var frpcStopWait = 10 * time.Second

// reloadTimeout bounds `frpc reload`, as on Linux.
const reloadTimeout = 15 * time.Second

type supervisor struct {
	ctx context.Context
	exe string
	job windows.Handle

	mu      sync.Mutex
	want    bool      // frpc should run: set by enable, cleared by disable
	gen     uint64    // changes with every start and stop; a pending restart of an older one drops
	cmd     *exec.Cmd // the running frpc, nil when none runs
	done    chan struct{}
	started time.Time
	backoff time.Duration
}

// Supervise makes this process the one that runs frpc, until ctx ends or stop is called; the
// agent service calls it once. stop kills frpc and waits for it to end.
func Supervise(ctx context.Context) (stop func(), err error) {
	exe, err := frpcExePath()
	if err != nil {
		return nil, fmt.Errorf("frpc.exe path: %w", err)
	}
	job, err := newKillOnCloseJob()
	if err != nil {
		return nil, err
	}
	s := &supervisor{ctx: ctx, exe: exe, job: job}
	current.Store(s)
	return func() {
		current.CompareAndSwap(s, nil)
		if err := s.disable(); err != nil {
			logger.Warnf("stop frpc: %v", err)
		}
		windows.CloseHandle(s.job)
	}, nil
}

// newKillOnCloseJob creates a job object that kills its processes when its last handle closes.
func newKillOnCloseJob() (windows.Handle, error) {
	job, err := windows.CreateJobObject(nil, nil)
	if err != nil {
		return 0, fmt.Errorf("create the job object for frpc: %w", err)
	}
	info := windows.JOBOBJECT_EXTENDED_LIMIT_INFORMATION{
		BasicLimitInformation: windows.JOBOBJECT_BASIC_LIMIT_INFORMATION{
			LimitFlags: windows.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE,
		},
	}
	if _, err := windows.SetInformationJobObject(job, windows.JobObjectExtendedLimitInformation,
		uintptr(unsafe.Pointer(&info)), uint32(unsafe.Sizeof(info))); err != nil {
		windows.CloseHandle(job)
		return 0, fmt.Errorf("set up the job object for frpc: %w", err)
	}
	return job, nil
}

// verifyFrpcExe checks that path holds the pinned frpc. The program folder grants writing only
// to SYSTEM and the Administrators, who could replace the agent itself.
func verifyFrpcExe(path string) error {
	f, err := os.Open(path)
	if err != nil {
		return fmt.Errorf("frpc.exe: %w; put frpc %s beside the agent (service install)", err, frpcPinnedVersion)
	}
	defer f.Close()
	h := sha256.New()
	if _, err := io.Copy(h, f); err != nil {
		return fmt.Errorf("read %s: %w", path, err)
	}
	if got := hex.EncodeToString(h.Sum(nil)); got != frpcWantSHA256 {
		return fmt.Errorf("%s is not the pinned frpc %s (sha256 %s), frpc stays stopped", path, frpcPinnedVersion, got)
	}
	return nil
}

// frpcCommand is frpc.exe with args, without a console window.
func frpcCommand(ctx context.Context, exe string, args ...string) *exec.Cmd {
	cmd := exec.CommandContext(ctx, exe, args...)
	cmd.SysProcAttr = &syscall.SysProcAttr{CreationFlags: windows.CREATE_NO_WINDOW}
	return cmd
}

// enable has frpc run: it starts frpc unless it runs already.
func (s *supervisor) enable() error {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.want = true
	return s.startLocked()
}

// startLocked starts frpc on frpc.toml if none runs. s.mu is held.
func (s *supervisor) startLocked() error {
	if s.cmd != nil {
		return nil
	}
	if err := s.ctx.Err(); err != nil {
		return err
	}
	if err := verifyFrpcExe(s.exe); err != nil {
		return err
	}
	out := &lineTail{max: 20}
	cmd := frpcCommand(context.Background(), s.exe, "-c", config.FrpConfigFile())
	cmd.Stdout, cmd.Stderr = out, out
	if err := cmd.Start(); err != nil {
		return fmt.Errorf("start frpc: %w", err)
	}
	// frpc starts no children of its own, so a child that ran before it joined the job is none.
	if err := assignToJob(s.job, cmd.Process.Pid); err != nil {
		_ = cmd.Process.Kill()
		_ = cmd.Wait()
		return err
	}
	s.gen++
	s.cmd, s.done, s.started = cmd, make(chan struct{}), time.Now()
	go s.watch(cmd, s.gen, s.done, out)
	return nil
}

func assignToJob(job windows.Handle, pid int) error {
	h, err := windows.OpenProcess(windows.PROCESS_SET_QUOTA|windows.PROCESS_TERMINATE, false, uint32(pid))
	if err != nil {
		return fmt.Errorf("open frpc (pid %d): %w", pid, err)
	}
	defer windows.CloseHandle(h)
	if err := windows.AssignProcessToJobObject(job, h); err != nil {
		return fmt.Errorf("put frpc into its job object: %w", err)
	}
	return nil
}

// watch waits for frpc to end and, while frpc should still run, restarts it after the backoff.
func (s *supervisor) watch(cmd *exec.Cmd, gen uint64, done chan struct{}, out *lineTail) {
	err := cmd.Wait()
	s.mu.Lock()
	defer s.mu.Unlock()
	close(done)
	if s.cmd == cmd {
		s.cmd = nil
	}
	if s.gen != gen || !s.want || s.ctx.Err() != nil {
		return
	}
	if time.Since(s.started) >= restartMax || s.backoff == 0 {
		s.backoff = restartMin
	} else {
		s.backoff = min(2*s.backoff, restartMax)
	}
	logger.Warnf("frpc ended (%v), restarting it in %s; its last output: %s", err, s.backoff, out)
	go s.restartAfter(gen, s.backoff)
}

// restartAfter starts frpc again after delay, unless a start or stop came in between.
func (s *supervisor) restartAfter(gen uint64, delay time.Duration) {
	t := time.NewTimer(delay)
	defer t.Stop()
	select {
	case <-s.ctx.Done():
		return
	case <-t.C:
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.gen != gen || !s.want || s.cmd != nil {
		return
	}
	if err := s.startLocked(); err != nil {
		s.backoff = min(2*s.backoff, restartMax)
		logger.Warnf("restart frpc: %v; next try in %s", err, s.backoff)
		go s.restartAfter(gen, s.backoff)
	}
}

// disable stops frpc and keeps it stopped until the next enable.
func (s *supervisor) disable() error {
	s.mu.Lock()
	s.want = false
	s.gen++
	cmd, done := s.cmd, s.done
	s.mu.Unlock()
	return stopCmd(cmd, done)
}

// restart stops frpc and starts it again on frpc.toml.
func (s *supervisor) restart() error {
	s.mu.Lock()
	s.gen++
	cmd, done := s.cmd, s.done
	s.mu.Unlock()
	if err := stopCmd(cmd, done); err != nil {
		return err
	}
	return s.enable()
}

func stopCmd(cmd *exec.Cmd, done chan struct{}) error {
	if cmd == nil {
		return nil
	}
	if err := cmd.Process.Kill(); err != nil && !errors.Is(err, os.ErrProcessDone) {
		return fmt.Errorf("stop frpc: %w", err)
	}
	select {
	case <-done:
		return nil
	case <-time.After(frpcStopWait):
		return fmt.Errorf("frpc (pid %d) did not end within %s", cmd.Process.Pid, frpcStopWait)
	}
}

// pid is the process id of the running frpc, 0 when none runs.
func (s *supervisor) pid() uint32 {
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.cmd == nil {
		return 0
	}
	return uint32(s.cmd.Process.Pid)
}

// lineTail keeps the last max lines written to it, for the log when frpc ends.
type lineTail struct {
	mu    sync.Mutex
	max   int
	lines []string
	part  []byte
}

func (t *lineTail) Write(p []byte) (int, error) {
	t.mu.Lock()
	defer t.mu.Unlock()
	t.part = append(t.part, p...)
	for {
		i := bytes.IndexByte(t.part, '\n')
		if i < 0 {
			break
		}
		t.add(string(bytes.TrimRight(t.part[:i], "\r")))
		t.part = t.part[i+1:]
	}
	if len(t.part) > 4096 {
		t.add(string(t.part))
		t.part = nil
	}
	return len(p), nil
}

func (t *lineTail) add(line string) {
	t.lines = append(t.lines, line)
	if len(t.lines) > t.max {
		t.lines = t.lines[len(t.lines)-t.max:]
	}
}

func (t *lineTail) String() string {
	t.mu.Lock()
	defer t.mu.Unlock()
	lines := t.lines
	if len(t.part) > 0 {
		lines = append(lines[:len(lines):len(lines)], string(t.part))
	}
	if len(lines) == 0 {
		return "(none)"
	}
	return strings.Join(lines, " | ")
}

var procGetExtendedTcpTable = windows.NewLazySystemDLL("iphlpapi.dll").NewProc("GetExtendedTcpTable")

// tcpTableOwnerPidListener is TCP_TABLE_OWNER_PID_LISTENER of TCP_TABLE_CLASS.
const tcpTableOwnerPidListener = 3

// tcpListeners returns the IPv4 listeners with their owning process (MIB_TCPTABLE_OWNER_PID).
func tcpListeners() ([]byte, error) {
	var size uint32
	var buf []byte
	for range 4 {
		var p unsafe.Pointer
		if len(buf) > 0 {
			p = unsafe.Pointer(&buf[0])
		}
		r, _, _ := procGetExtendedTcpTable.Call(uintptr(p), uintptr(unsafe.Pointer(&size)), 0,
			windows.AF_INET, tcpTableOwnerPidListener, 0)
		switch windows.Errno(r) {
		case windows.ERROR_SUCCESS:
			return buf, nil
		case windows.ERROR_INSUFFICIENT_BUFFER:
			buf = make([]byte, size)
		default:
			return nil, fmt.Errorf("GetExtendedTcpTable: %w", windows.Errno(r))
		}
	}
	return nil, errors.New("GetExtendedTcpTable: the table kept growing")
}
