// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package probe

import (
	"bytes"
	"context"
	"errors"
	"fmt"
	"io"
	"io/fs"
	"os"
	"path"
	"strings"
)

// The files of linuxmuster.net 7 the views read (linuxmuster-common lib/environment.py: WIMPORTDATA,
// DHCPDEVCONF, LOGDIR, LINBOIMGDIR; import_devices.py, writeDhcpDevicesConfig), relative to the root of
// this host. Only the default school is read; the devices of further schools stand in files of their
// own. The import writes the DHCP file of the school it imports, and devices.conf on the import of any
// school; the file of the school is read, devices.conf only where it is missing.
const (
	lmnDevicesCSV     = "etc/linuxmuster/sophomorix/default-school/devices.csv"
	lmnDevicesConf    = "etc/dhcp/devices/default-school.conf"
	lmnDevicesConfAll = "etc/dhcp/devices.conf"
	lmnImportLog      = "var/log/linuxmuster/import-devices.log"
	lmnImageDir       = "srv/linbo/images"
)

const (
	// lmnLogTail is how much of the end of import-devices.log lmn_devices reads.
	lmnLogTail = 256 << 10
	// maxLinboEntries caps the directory entries lmn_linbo reads in one directory.
	maxLinboEntries = 4096
)

// The lines linuxmuster-import-devices writes to its log (linuxmuster-base7,
// src/linuxmuster_base7/cli/import_devices.py, main and runSophomorixDeviceSync): where a run starts
// and ends and how a step fails.
const (
	lmnImportStarted   = "linuxmuster-import-devices started"
	lmnImportCompleted = "linuxmuster-import-devices completed"
)

var lmnImportFailures = []string{"failed with return code", "errors detected"}

// linboImageExts are the images linbo-torrent seeds (linuxmuster-linbo7, usr/sbin/linbo-torrent,
// LINBOIMGEXT); the torrent of an image is its name with ".torrent" appended.
var linboImageExts = []string{".qcow2", ".qdiff", ".iso"}

// lmnDevices says whether devices.csv of the default school changed after its last import
// (linuxmuster-import-devices writes the DHCP file of the school anew on every run that gets that far) and how old
// that import is; from the last run in import-devices.log, if the log has one, whether it completed
// and how many of its steps failed. It reads the modification times of the two files and the end of
// the log, and quotes none of them.
func lmnDevices(ctx context.Context, _ Target) (map[string]any, error) {
	return untilDone(ctx, func() (map[string]any, error) {
		root, err := hostRoot()
		if err != nil {
			return nil, fmt.Errorf("the root of this host cannot be opened: %v", cause(err))
		}
		defer root.Close()
		csv, err := root.Lstat(lmnDevicesCSV)
		if errors.Is(err, fs.ErrNotExist) {
			return nil, fmt.Errorf("%w: this host holds no devices.csv of linuxmuster.net", ErrUnsupported)
		}
		if err != nil {
			return nil, fmt.Errorf("/%s cannot be read: %v", lmnDevicesCSV, cause(err))
		}
		values := map[string]any{"import_pending": true}
		name := lmnDevicesConf
		conf, err := root.Lstat(name)
		if errors.Is(err, fs.ErrNotExist) {
			name = lmnDevicesConfAll
			conf, err = root.Lstat(name)
		}
		switch {
		case err == nil:
			values["import_pending"] = csv.ModTime().After(conf.ModTime())
			values["last_import_age_s"] = max(int(now().Sub(conf.ModTime()).Seconds()), 0)
		case !errors.Is(err, fs.ErrNotExist):
			return nil, fmt.Errorf("/%s cannot be read: %v", name, cause(err))
		}
		tail, err := logTail(root, lmnImportLog, lmnLogTail)
		if errors.Is(err, fs.ErrNotExist) {
			return values, nil
		}
		if err != nil {
			return nil, err
		}
		i := bytes.LastIndex(tail, []byte(lmnImportStarted))
		if i < 0 {
			return values, nil
		}
		run := string(tail[i:])
		failures := 0
		for line := range strings.Lines(run) {
			for _, f := range lmnImportFailures {
				if strings.Contains(line, f) {
					failures++
					break
				}
			}
		}
		values["import_completed"] = strings.Contains(run, lmnImportCompleted)
		values["import_errors"] = failures
		return values, nil
	})
}

// logTail reads the last n bytes of the regular file name below root, from the first whole line on.
// fs.ErrNotExist if there is no such file.
func logTail(root *os.Root, name string, n int64) ([]byte, error) {
	shown := "/" + name
	if _, err := root.Lstat(name); errors.Is(err, fs.ErrNotExist) {
		return nil, fs.ErrNotExist
	}
	f, err := openRegular(root, name, shown)
	if err != nil {
		return nil, err
	}
	defer f.Close()
	fi, err := f.Stat()
	if err != nil {
		return nil, fmt.Errorf("%s cannot be read: %v", shown, cause(err))
	}
	start := max(fi.Size()-n, 0)
	buf, err := io.ReadAll(io.NewSectionReader(f, start, n))
	if err != nil {
		return nil, fmt.Errorf("%s cannot be read: %v", shown, cause(err))
	}
	if start > 0 {
		if _, rest, cut := bytes.Cut(buf, []byte("\n")); cut {
			buf = rest
		} else {
			buf = nil
		}
	}
	return buf, nil
}

// lmnLinbo counts the images of LINBO below /srv/linbo/images, as linbo-torrent finds them (in the
// directory and one level down), and those whose torrent is missing or older than the image: clients
// would fetch the old image over BitTorrent. A directory whose name begins with "." is left out: there
// the image sync stages an upload (.incoming). It reads directory entries and modification times, no
// image and no torrent.
func lmnLinbo(ctx context.Context, _ Target) (map[string]any, error) {
	return untilDone(ctx, func() (map[string]any, error) {
		root, err := hostRoot()
		if err != nil {
			return nil, fmt.Errorf("the root of this host cannot be opened: %v", cause(err))
		}
		defer root.Close()
		top, err := readDirCapped(root, lmnImageDir)
		if errors.Is(err, fs.ErrNotExist) {
			return nil, fmt.Errorf("%w: this host holds no images of LINBO", ErrUnsupported)
		}
		if err != nil {
			return nil, err
		}
		images, stale := 0, 0
		count := func(dir string, entries []fs.DirEntry) error {
			for _, e := range entries {
				if !e.Type().IsRegular() || !slicesHasSuffix(e.Name(), linboImageExts) {
					continue
				}
				outdated, err := torrentStale(root, path.Join(dir, e.Name()))
				if err != nil {
					return err
				}
				images++
				if outdated {
					stale++
				}
			}
			return nil
		}
		if err := count(lmnImageDir, top); err != nil {
			return nil, err
		}
		for _, e := range top {
			if !e.IsDir() || strings.HasPrefix(e.Name(), ".") {
				continue
			}
			dir := path.Join(lmnImageDir, e.Name())
			entries, err := readDirCapped(root, dir)
			if err != nil {
				return nil, err
			}
			if err := count(dir, entries); err != nil {
				return nil, err
			}
		}
		return map[string]any{"images": images, "torrents_stale": stale}, nil
	})
}

// torrentStale says whether the torrent of the image name below root is missing or older than it.
func torrentStale(root *os.Root, name string) (bool, error) {
	img, err := root.Lstat(name)
	if err != nil {
		return false, fmt.Errorf("/%s cannot be read: %v", name, cause(err))
	}
	t, err := root.Lstat(name + ".torrent")
	switch {
	case errors.Is(err, fs.ErrNotExist):
		return true, nil
	case err != nil:
		return false, fmt.Errorf("/%s.torrent cannot be read: %v", name, cause(err))
	}
	return !t.Mode().IsRegular() || t.ModTime().Before(img.ModTime()), nil
}

// readDirCapped reads at most maxLinboEntries entries of the directory dir below root.
func readDirCapped(root *os.Root, dir string) ([]fs.DirEntry, error) {
	f, err := root.OpenFile(dir, dirFlags, 0)
	if errors.Is(err, fs.ErrNotExist) {
		return nil, fs.ErrNotExist
	}
	if errors.Is(notDir(err), errNotDir) {
		return nil, fmt.Errorf("/%s is no directory", dir)
	}
	if err != nil {
		return nil, fmt.Errorf("/%s cannot be read: %v", dir, cause(err))
	}
	defer f.Close()
	entries, err := f.ReadDir(maxLinboEntries)
	if err != nil && !errors.Is(err, io.EOF) {
		return nil, fmt.Errorf("/%s cannot be read: %v", dir, cause(err))
	}
	return entries, nil
}

// slicesHasSuffix says whether name ends in one of suffixes.
func slicesHasSuffix(name string, suffixes []string) bool {
	for _, s := range suffixes {
		if strings.HasSuffix(name, s) {
			return true
		}
	}
	return false
}
