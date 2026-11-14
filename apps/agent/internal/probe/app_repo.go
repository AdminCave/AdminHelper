// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package probe

import (
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"os/exec"
	"strings"
	"time"
)

// The views restic_latest, borg_latest and kopia_latest ask a backup repository for its newest
// snapshot, with the repository's password stored on this host (use password, handed to the one
// command in its environment, passwordEnv). They read only repositories on a local disk or over
// SFTP/SSH, which root reaches already; a repository in a cloud store is unsupported. The location
// comes from the unit the target names (its Environment and EnvironmentFile), never from the
// server. Sent are has_snapshot and snapshot_age_s, never a path, a host or a snapshot's name.
//
// Every call reads without a lock: restic with --no-lock (and --no-cache, writing nothing here), borg
// with --bypass-lock, kopia's snapshot list takes none; a lock of the agent could make the customer's prune or compact fail.
//
// Checked at restic 0.18.0, borg 1.4.0 and kopia 0.23.1 (output, exit codes, the refused password).

// repoTimeout bounds a repository query: over SFTP it waits for the network.
const repoTimeout = 60 * time.Second

// maxEnvFile bounds an EnvironmentFile of a unit and kopia's repository.config.
const maxEnvFile = 64 << 10

// kopiaConfig is where kopia keeps the connection of root's repository, unless the unit names
// another in KOPIA_CONFIG_PATH.
const kopiaConfig = "/root/.config/kopia/repository.config"

// The exit codes that say a password was refused: restic 12 (since 0.17.1), borg 52 with
// BORG_EXIT_CODES=modern (1.4; borg 1.2 says 2, an error).
const (
	resticWrongPassword = 12
	borgWrongPassword   = 52
)

// unitEnvironment reads the environment the unit name gives its processes: Environment, then each
// EnvironmentFile, whose settings override (systemd.exec). Only the variables keys are kept.
func unitEnvironment(ctx context.Context, name string, keys ...string) (map[string]string, error) {
	out, err := runTool(ctx, toolTimeout, "systemctl", "show", "-p", "LoadState,Environment,EnvironmentFiles", "--", name)
	if errors.Is(err, exec.ErrNotFound) {
		return nil, fmt.Errorf("%w: systemctl is not installed", ErrUnsupported)
	}
	if err != nil {
		return nil, toolError("systemctl", err)
	}
	env := map[string]string{}
	keep := func(k, v string) {
		for _, want := range keys {
			if k == want {
				env[k] = v
			}
		}
	}
	loaded := false
	var files []string
	for line := range strings.Lines(string(out)) {
		k, v, ok := strings.Cut(strings.TrimRight(line, "\r\n"), "=")
		switch {
		case !ok:
		case k == "LoadState":
			if v == "not-found" {
				return nil, fmt.Errorf("unit %s does not exist on this host", name)
			}
			loaded = v != ""
		case k == "Environment":
			for _, word := range unitWords(v) {
				if ek, ev, ok := strings.Cut(word, "="); ok {
					keep(ek, ev)
				}
			}
		case k == "EnvironmentFiles":
			// "/etc/restic.env (ignore_errors=no)", one line per file.
			if path, _, ok := strings.Cut(v, " (ignore_errors="); ok {
				files = append(files, path)
			}
		}
	}
	if !loaded {
		return nil, errors.New("systemctl show: an answer of another form")
	}
	for _, path := range files {
		if !validLocalPath(path) {
			continue
		}
		data, err := untilDone(ctx, func() ([]byte, error) { return readSmallFile(path, maxEnvFile) })
		if err != nil {
			// systemd starts the unit without a file marked ignore_errors=yes; a file it needs and
			// the agent cannot read leaves the location unknown, as without it.
			continue
		}
		for k, v := range envFile(data) {
			keep(k, v)
		}
	}
	return env, nil
}

// unitWords splits systemctl's Environment value into its assignments: separated by spaces, a word
// with a space quoted in "..." with C escapes.
func unitWords(s string) []string {
	var words []string
	var w strings.Builder
	quoted, inWord := false, false
	for i := 0; i < len(s); i++ {
		c := s[i]
		switch {
		case c == '\\' && i+1 < len(s):
			i++
			w.WriteByte(s[i])
			inWord = true
		case c == '"':
			quoted, inWord = !quoted, true
		case c == ' ' && !quoted:
			if inWord {
				words = append(words, w.String())
				w.Reset()
				inWord = false
			}
		default:
			w.WriteByte(c)
			inWord = true
		}
	}
	if inWord {
		words = append(words, w.String())
	}
	return words
}

// envFile reads the assignments of an EnvironmentFile: KEY=VALUE per line, # and ; start a comment,
// a value may be quoted.
func envFile(data []byte) map[string]string {
	env := map[string]string{}
	sc := bufio.NewScanner(bytes.NewReader(data))
	for sc.Scan() {
		line := strings.TrimSpace(sc.Text())
		if line == "" || line[0] == '#' || line[0] == ';' {
			continue
		}
		k, v, ok := strings.Cut(line, "=")
		if !ok {
			continue
		}
		v = strings.TrimSpace(v)
		if len(v) >= 2 && (v[0] == '"' || v[0] == '\'') && v[len(v)-1] == v[0] {
			v = v[1 : len(v)-1]
		}
		env[strings.TrimSpace(k)] = v
	}
	return env
}

// needPassword returns the environment entry of the repository's password; a repository query runs
// only with one.
func needPassword(c appCredential, name string) ([]string, error) {
	if c.use == "" {
		return nil, fmt.Errorf("%w: a repository is read only with its password stored on this host (use password)", ErrInvalid)
	}
	return passwordEnv(c, name)
}

// repoRun runs one repository query; the exit code deniedCode (0: none; a process killed by a signal
// exits -1) or deniedText in stderr says the password was refused and is ErrDenied,
// any other failure names the exit code alone: the tools' messages name the repository's path.
func repoRun(ctx context.Context, env []string, deniedCode int, deniedText, name string, args ...string) ([]byte, error) {
	out, err := runToolEnv(ctx, repoTimeout, env, name, args...)
	if errors.Is(err, exec.ErrNotFound) {
		return nil, fmt.Errorf("%w: %s is not installed", ErrUnsupported, name)
	}
	var exitErr *exec.ExitError
	if errors.As(err, &exitErr) {
		if (deniedCode > 0 && exitErr.ExitCode() == deniedCode) || (deniedText != "" && bytes.Contains(exitErr.Stderr, []byte(deniedText))) {
			return nil, fmt.Errorf("%w: %s refused the repository's password", ErrDenied, name)
		}
		return nil, fmt.Errorf("%s: exit code %d", name, exitErr.ExitCode())
	}
	if err != nil {
		return nil, fmt.Errorf("%s: %w", name, err)
	}
	return out, nil
}

// snapshotValues are the values of a repository view: has_snapshot, and snapshot_age_s of the newest.
func snapshotValues(times []time.Time) map[string]any {
	values := map[string]any{"has_snapshot": len(times) > 0}
	var newest time.Time
	for _, t := range times {
		if t.After(newest) {
			newest = t
		}
	}
	if !newest.IsZero() {
		values["snapshot_age_s"] = ageSeconds(newest)
	}
	return values
}

// resticLocal says whether a restic repository lies on a local disk or behind SFTP.
func resticLocal(repo string) bool {
	return validLocalPath(repo) || strings.HasPrefix(repo, "sftp:")
}

// resticLatest reads the newest snapshot of the restic repository in the unit's RESTIC_REPOSITORY:
// `restic snapshots --json --latest 1 --no-lock --no-cache`, the last snapshot of each host and path.
func resticLatest(ctx context.Context, t Target, c appCredential) (map[string]any, error) {
	pw, err := needPassword(c, "RESTIC_PASSWORD")
	if err != nil {
		return nil, err
	}
	env, err := unitEnvironment(ctx, t.Name, "RESTIC_REPOSITORY")
	if err != nil {
		return nil, err
	}
	repo := env["RESTIC_REPOSITORY"]
	switch {
	case repo == "":
		return nil, fmt.Errorf("%w: the unit names no RESTIC_REPOSITORY", ErrUnsupported)
	case !resticLocal(repo):
		return nil, fmt.Errorf("%w: restic: only a local or SFTP repository is read", ErrUnsupported)
	}
	out, err := repoRun(ctx, append([]string{"RESTIC_REPOSITORY=" + repo}, pw...), resticWrongPassword, "",
		"restic", "snapshots", "--json", "--latest", "1", "--no-lock", "--no-cache")
	if err != nil {
		return nil, err
	}
	var snaps []struct {
		Time *time.Time `json:"time"`
	}
	if err := json.Unmarshal(out, &snaps); err != nil {
		return nil, errors.New("restic: an answer of another form")
	}
	times := make([]time.Time, 0, len(snaps))
	for _, s := range snaps {
		if s.Time == nil {
			return nil, errors.New("restic: a snapshot without a time")
		}
		times = append(times, *s.Time)
	}
	return snapshotValues(times), nil
}

// borgLocal says whether a borg repository lies on a local disk or behind SSH: a path, file://,
// ssh:// or the older user@host:path.
func borgLocal(repo string) bool {
	switch {
	case validLocalPath(repo), strings.HasPrefix(repo, "file:///"), strings.HasPrefix(repo, "ssh://"):
		return true
	case strings.Contains(repo, "://"):
		return false
	}
	host, _, ok := strings.Cut(repo, ":")
	return ok && host != "" && !strings.ContainsAny(host, "/ ")
}

// borgTime is the form of borg's archive times: local time without a zone.
const borgTime = "2006-01-02T15:04:05.000000"

// borgLatest reads the newest archive of the borg repository in the unit's BORG_REPO: `borg list
// --last 1 --json --bypass-lock`. A repository borg does not know or finds moved is not confirmed
// (BORG_*_ACCESS_IS_OK=no): borg aborts instead of waiting for an answer.
func borgLatest(ctx context.Context, t Target, c appCredential) (map[string]any, error) {
	pw, err := needPassword(c, "BORG_PASSPHRASE")
	if err != nil {
		return nil, err
	}
	env, err := unitEnvironment(ctx, t.Name, "BORG_REPO")
	if err != nil {
		return nil, err
	}
	repo := env["BORG_REPO"]
	switch {
	case repo == "":
		return nil, fmt.Errorf("%w: the unit names no BORG_REPO", ErrUnsupported)
	case !borgLocal(repo):
		return nil, fmt.Errorf("%w: borg: only a local or SSH repository is read", ErrUnsupported)
	}
	run := append([]string{"BORG_REPO=" + repo, "BORG_EXIT_CODES=modern",
		"BORG_UNKNOWN_UNENCRYPTED_REPO_ACCESS_IS_OK=no", "BORG_RELOCATED_REPO_ACCESS_IS_OK=no"}, pw...)
	out, err := repoRun(ctx, run, borgWrongPassword, "", "borg", "list", "--last", "1", "--json", "--bypass-lock")
	if err != nil {
		return nil, err
	}
	var list struct {
		Archives *[]struct {
			Start string `json:"start"`
		} `json:"archives"`
	}
	if err := json.Unmarshal(out, &list); err != nil || list.Archives == nil {
		return nil, errors.New("borg: an answer of another form")
	}
	var times []time.Time
	for _, a := range *list.Archives {
		at, err := time.ParseInLocation(borgTime, a.Start, time.Local)
		if err != nil {
			return nil, errors.New("borg: an archive without a time")
		}
		times = append(times, at)
	}
	return snapshotValues(times), nil
}

// kopiaLatest reads the newest snapshot of the kopia repository root is connected to (the unit's
// KOPIA_CONFIG_PATH, else kopiaConfig): `kopia snapshot list --json -n 1`, the last of each source.
// Only a repository of storage type filesystem or sftp is read.
func kopiaLatest(ctx context.Context, t Target, c appCredential) (map[string]any, error) {
	pw, err := needPassword(c, "KOPIA_PASSWORD")
	if err != nil {
		return nil, err
	}
	env, err := unitEnvironment(ctx, t.Name, "KOPIA_CONFIG_PATH")
	if err != nil {
		return nil, err
	}
	path := env["KOPIA_CONFIG_PATH"]
	if path == "" {
		path = kopiaConfig
	}
	if !validLocalPath(path) {
		return nil, fmt.Errorf("%w: KOPIA_CONFIG_PATH is no absolute local path", ErrInvalid)
	}
	data, err := untilDone(ctx, func() ([]byte, error) { return readSmallFile(path, maxEnvFile) })
	if err != nil {
		return nil, fmt.Errorf("%w: kopia is connected to no repository here", ErrUnsupported)
	}
	var conf struct {
		Storage struct {
			Type string `json:"type"`
		} `json:"storage"`
	}
	if err := json.Unmarshal(data, &conf); err != nil {
		return nil, errors.New("kopia: a repository.config of another form")
	}
	if conf.Storage.Type != "filesystem" && conf.Storage.Type != "sftp" {
		return nil, fmt.Errorf("%w: kopia: only a filesystem or SFTP repository is read", ErrUnsupported)
	}
	out, err := repoRun(ctx, append([]string{"KOPIA_CONFIG_PATH=" + path}, pw...), 0, "invalid repository password",
		"kopia", "snapshot", "list", "--json", "-n", "1")
	if err != nil {
		return nil, err
	}
	var snaps []struct {
		End *time.Time `json:"endTime"`
	}
	if err := json.Unmarshal(out, &snaps); err != nil {
		return nil, errors.New("kopia: an answer of another form")
	}
	times := make([]time.Time, 0, len(snaps))
	for _, s := range snaps {
		if s.End == nil {
			return nil, errors.New("kopia: a snapshot without a time")
		}
		times = append(times, *s.End)
	}
	return snapshotValues(times), nil
}

// duplicatiHealth asks the local Duplicati server whether it is healthy: `duplicati-server-util
// health`, which reads the server's database for its access and prints "Server is healthy" (exit 0)
// or "Server is unhealthy" (exit 1). Taken from Duplicati's documentation of ServerUtil, not verified
// at a server.
func duplicatiHealth(ctx context.Context, _ Target) (map[string]any, error) {
	out, err := runTool(ctx, toolTimeout, "duplicati-server-util", "health")
	if errors.Is(err, exec.ErrNotFound) {
		return nil, fmt.Errorf("%w: duplicati-server-util is not installed", ErrUnsupported)
	}
	var exitErr *exec.ExitError
	switch {
	case err == nil && bytes.Contains(out, []byte("Server is healthy")):
		return map[string]any{"healthy": true}, nil
	case errors.As(err, &exitErr) && exitErr.ExitCode() == 1 && bytes.Contains(out, []byte("Server is unhealthy")):
		return map[string]any{"healthy": false}, nil
	case errors.As(err, &exitErr):
		return nil, fmt.Errorf("duplicati-server-util: exit code %d", exitErr.ExitCode())
	case err != nil:
		return nil, fmt.Errorf("duplicati-server-util: %w", err)
	}
	return nil, errors.New("duplicati-server-util: an answer of another form")
}
