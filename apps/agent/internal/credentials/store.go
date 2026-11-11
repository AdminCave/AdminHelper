// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Package credentials keeps the credentials the monitoring probes present (R-1223) in one file on
// this host, readable by the agent's account only. The monitoring service names a credential by its
// ref and learns only which refs are stored, never a value.
package credentials

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io/fs"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"time"
	"unicode/utf8"

	"adminhelper-agent/internal/config"
	"adminhelper-agent/internal/enroll"
	"adminhelper-agent/internal/logging"
)

var logger = logging.For("credentials")

// Credential is one stored credential: the secret a probe presents and a random id that a set gives
// it anew. The access brake waits for a new id after its target refused it, so it is never derived
// from the secret.
type Credential struct {
	Secret string `json:"secret"`
	ID     string `json:"id"`
}

const (
	fileVersion = 1
	// MaxCredentials is as many refs as the monitoring service keeps of a host.
	MaxCredentials = 256
	maxRefBytes    = 255
	// MaxSecretBytes stays below the 4 KiB the CLI reads from stdin, so a read cut off there cannot
	// pass as a secret.
	MaxSecretBytes = 4000
	// maxFileBytes bounds the file: MaxCredentials entries of the longest ref and secret fit.
	maxFileBytes = 2 << 20
	lockName     = ".credentials.lock"
	lockWait     = 10 * time.Second
)

// refPattern is the monitoring service's CREDENTIAL_REF_PATTERN (check_configs.py).
var (
	refPattern = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9_.:@-]*(/[A-Za-z0-9][A-Za-z0-9_.:@-]*)*$`)
	idPattern  = regexp.MustCompile(`^[0-9a-f]{32}$`)
)

// ErrNotFound is the error of Delete for a ref nothing is stored under.
var ErrNotFound = errors.New("no credential stored under this ref")

type file struct {
	Version     int                   `json:"version"`
	Credentials map[string]Credential `json:"credentials"`
}

// ValidRef returns an error unless ref is one the monitoring service can name.
func ValidRef(ref string) error {
	if len(ref) > maxRefBytes || !refPattern.MatchString(ref) {
		return fmt.Errorf("invalid ref %q: segments of letters, digits and _ . : @ - separated by /, each starting with a letter or digit, at most %d characters", ref, maxRefBytes)
	}
	return nil
}

// validSecret returns an error unless secret can be presented: not empty, at most MaxSecretBytes,
// valid UTF-8 and without control characters, which would end a header line or a command of the
// protocols the probes speak. Its errors never quote the secret.
func validSecret(secret string) error {
	switch {
	case secret == "":
		return errors.New("the secret is empty")
	case len(secret) > MaxSecretBytes:
		return fmt.Errorf("the secret is longer than %d bytes", MaxSecretBytes)
	case !utf8.ValidString(secret):
		return errors.New("the secret is not valid UTF-8")
	}
	for _, r := range secret {
		if r < 0x20 || r == 0x7f {
			return errors.New("the secret holds a control character")
		}
	}
	return nil
}

// Load reads the credentials stored at path. A missing file holds none. A file others can read or
// change, a link and one that is no credentials file are errors: then no credential is used. An
// entry the agent would not have written is left out with a warning. Its errors never quote the file.
func Load(path string) (map[string]Credential, error) {
	data, err := readPrivate(path)
	if errors.Is(err, fs.ErrNotExist) {
		return map[string]Credential{}, nil
	}
	if err != nil {
		return nil, err
	}
	var f file
	if err := json.Unmarshal(data, &f); err != nil || f.Version != fileVersion {
		// The decoder's error would quote a character of the file, which may be one of a secret.
		return nil, fmt.Errorf("%s is no credentials file of version %d", path, fileVersion)
	}
	creds := make(map[string]Credential, len(f.Credentials))
	for ref, c := range f.Credentials {
		if ValidRef(ref) != nil || validSecret(c.Secret) != nil || !idPattern.MatchString(c.ID) {
			logger.Warnf("%s: an entry is left out, it is not as monitor credential set writes it", path)
			continue
		}
		creds[ref] = c
	}
	return creds, nil
}

// Refs returns the refs of creds, sorted.
func Refs(creds map[string]Credential) []string {
	refs := make([]string, 0, len(creds))
	for ref := range creds {
		refs = append(refs, ref)
	}
	sort.Strings(refs)
	return refs
}

// Set stores secret under ref at path with a new id, in place of what was stored there.
func Set(ctx context.Context, path, ref, secret string) error {
	if err := ValidRef(ref); err != nil {
		return err
	}
	if err := validSecret(secret); err != nil {
		return err
	}
	id := make([]byte, 16)
	if _, err := rand.Read(id); err != nil {
		return err
	}
	return update(ctx, path, func(creds map[string]Credential) error {
		if _, ok := creds[ref]; !ok && len(creds) >= MaxCredentials {
			return fmt.Errorf("%d credentials are stored already, the most the monitoring service keeps", MaxCredentials)
		}
		creds[ref] = Credential{Secret: secret, ID: hex.EncodeToString(id)}
		return nil
	})
}

// Delete removes the credential stored under ref at path; ErrNotFound when there is none.
func Delete(ctx context.Context, path, ref string) error {
	return update(ctx, path, func(creds map[string]Credential) error {
		if _, ok := creds[ref]; !ok {
			return fmt.Errorf("%w: %s", ErrNotFound, ref)
		}
		delete(creds, ref)
		return nil
	})
}

// update applies change to the credentials at path and writes them back, under a lock next to the
// file, so two sets at once do not lose one of them.
func update(ctx context.Context, path string, change func(map[string]Credential) error) error {
	dir := filepath.Dir(path)
	// 0700 on Linux, a protected ACL on Windows, after the data root above it.
	if err := config.EnsureDataDir(dir); err != nil {
		return fmt.Errorf("secure %s: %w", dir, err)
	}
	unlock, err := enroll.LockFile(ctx, filepath.Join(dir, lockName), lockWait)
	if err != nil {
		return err
	}
	defer unlock()
	creds, err := Load(path)
	if err != nil {
		return err
	}
	if err := change(creds); err != nil {
		return err
	}
	return write(path, creds)
}

// write replaces the file at path with creds: a temp file of the agent's account alone (0600; on
// Windows the directory's protected ACL and the Administrators as owner), synced, then renamed over
// the file, so a crash leaves the old file or the new one.
func write(path string, creds map[string]Credential) error {
	data, err := json.MarshalIndent(file{Version: fileVersion, Credentials: creds}, "", "  ")
	if err != nil {
		return err
	}
	tmp, err := os.CreateTemp(filepath.Dir(path), ".credentials-*.tmp")
	if err != nil {
		return err
	}
	name := tmp.Name()
	done := false
	defer func() {
		if !done {
			_ = tmp.Close()
			_ = os.Remove(name)
		}
	}()
	if _, err := tmp.Write(data); err != nil {
		return err
	}
	if err := tmp.Sync(); err != nil {
		return err
	}
	if err := tmp.Close(); err != nil {
		return err
	}
	if err := config.OwnByAdministrators(name); err != nil {
		return err
	}
	if err := os.Rename(name, path); err != nil {
		return err
	}
	done = true
	return nil
}
