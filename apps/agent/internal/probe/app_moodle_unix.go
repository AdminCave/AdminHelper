// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build linux || freebsd

package probe

import (
	"bytes"
	"errors"
	"fmt"
	"io/fs"
	"os"
	"os/user"
	"path/filepath"
	"regexp"
	"strconv"
	"syscall"
)

// moodleLookup finds the user checks.php runs as; tests stand in their own.
var moodleLookup = user.Lookup

// moodleFiles are the files of a Moodle that checks.php runs first, below its document root.
var moodleFiles = []string{"admin", "admin/cli", "admin/cli/checks.php", "config.php", "lib", "lib/moodlelib.php"}

// moodleDataFiles are the files below the dataroot that the setup of a Moodle includes as PHP: the
// configuration of its caches (muc/config.php) and the class map (cache/core_component.php), with the
// directories that hold them and the local cache. Before the first run they are missing. Not verified
// against the source of Moodle that these are all.
var moodleDataFiles = []string{"muc", "muc/config.php", "cache", "cache/core_component.php", "localcache"}

// moodleMoved are the settings of config.php that move these files out of the dataroot: a Moodle
// that sets one is not run.
var moodleMoved = [][]byte{[]byte("$CFG->cachedir"), []byte("$CFG->localcachedir"), []byte("$CFG->altcacheconfigpath")}

// maxMoodleConfig caps what is read of config.php: a few hundred lines of assignments.
const maxMoodleConfig = 64 << 10

// moodleDataroot is the one assignment of the dataroot in config.php that the agent takes: a literal
// in single quotes on a line of its own. Any other form (a variable, a concatenation, a second
// assignment) names a directory only PHP can tell.
var moodleDataroot = regexp.MustCompile(`(?m)^[ \t]*\$CFG->dataroot[ \t]*=[ \t]*'([^'\\\n]+)'[ \t]*;`)

// moodleOwned tells whether the code checks.php would run is the web server's own, and returns the
// document root with its links resolved: the agent runs checks.php below that path, the one it checked.
// The document root, each directory above it and the files of moodleFiles belong to root or to the
// user name, and no one else may write them (a group only if it is root's; a directory anyone may write
// only with the sticky bit, as /tmp); none of the files is a link. The dataroot of config.php belongs to
// the user itself, the directories above it and the files of moodleDataFiles follow the same rules:
// where each site has a PHP user of its own, that user owns its dataroot, and the PHP it may write there
// the agent never starts as the web server's user. A user of uid 0 is root under another name.
func moodleOwned(root, name string) (string, error) {
	u, err := moodleLookup(name)
	if err != nil {
		return "", fmt.Errorf("%w: the user %s of the web server is unknown", ErrUnsupported, name)
	}
	n, err := strconv.ParseUint(u.Uid, 10, 32)
	if err != nil {
		return "", fmt.Errorf("%w: the user %s of the web server has no numeric id", ErrUnsupported, name)
	}
	uid := uint32(n)
	if uid == 0 {
		return "", fmt.Errorf("%w: the user %s of the web server is root", ErrUnsupported, name)
	}
	real, err := moodleTree(root, moodleFiles, false, uid)
	if err != nil {
		return "", err
	}
	conf, err := readCapped(filepath.Join(real, "config.php"), maxMoodleConfig)
	if err != nil {
		return "", fmt.Errorf("%w: the config.php of the Moodle cannot be read", ErrUnsupported)
	}
	m := moodleDataroot.FindSubmatch(conf)
	if m == nil || bytes.Count(conf, []byte("$CFG->dataroot")) != 1 || !filepath.IsAbs(string(m[1])) {
		return "", fmt.Errorf("%w: the config.php of the Moodle names no dataroot the agent can tell", ErrUnsupported)
	}
	for _, moved := range moodleMoved {
		if bytes.Contains(conf, moved) {
			return "", fmt.Errorf("%w: the config.php of the Moodle moves its caches", ErrUnsupported)
		}
	}
	data, err := moodleTree(string(m[1]), moodleDataFiles, true, uid)
	if err != nil {
		return "", err
	}
	var st *syscall.Stat_t
	if fi, err := os.Lstat(data); err == nil {
		st, _ = fi.Sys().(*syscall.Stat_t)
	}
	if st == nil || st.Uid != uid {
		return "", fmt.Errorf("%w: the dataroot of the Moodle is not its web server's user's", ErrUnsupported)
	}
	return real, nil
}

// moodleTree resolves the links of dir and checks it, each directory above it and the files below it
// (moodleSafe, none of the files a link; missing files only if mayMiss). It returns dir resolved.
func moodleTree(dir string, files []string, mayMiss bool, uid uint32) (string, error) {
	real, err := filepath.EvalSymlinks(dir)
	if err != nil {
		return "", fmt.Errorf("%w: a directory of the Moodle cannot be read", ErrUnsupported)
	}
	var paths []string
	for d := real; ; d = filepath.Dir(d) {
		paths = append(paths, d)
		if d == filepath.Dir(d) {
			break
		}
	}
	above := len(paths)
	for _, f := range files {
		paths = append(paths, filepath.Join(real, f))
	}
	for i, p := range paths {
		fi, err := os.Lstat(p)
		switch {
		case errors.Is(err, fs.ErrNotExist) && mayMiss && i >= above:
			continue
		case err != nil:
			return "", fmt.Errorf("%w: a file of the Moodle cannot be read", ErrUnsupported)
		}
		st, ok := fi.Sys().(*syscall.Stat_t)
		if !ok || fi.Mode()&os.ModeSymlink != 0 || !moodleSafe(st, fi.Mode(), uid) {
			return "", fmt.Errorf("%w: the files of the Moodle are not only root's and its web server's", ErrUnsupported)
		}
	}
	return real, nil
}

// moodleSafe: the file belongs to root or uid, its group may write it only if it is root's (a group
// of the user's own may hold other users too), and anyone only if it is a directory with the sticky bit.
func moodleSafe(st *syscall.Stat_t, mode os.FileMode, uid uint32) bool {
	switch {
	case st.Uid != 0 && st.Uid != uid:
		return false
	case mode.Perm()&0o020 != 0 && st.Gid != 0:
		return false
	case mode.Perm()&0o002 != 0 && !(mode.IsDir() && mode&os.ModeSticky != 0):
		return false
	}
	return true
}
