// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package probe

import (
	"context"
	"errors"
	"fmt"
	"io"
	"io/fs"
	"regexp"
)

// maxWPVersionBytes caps version.php, about 1 KiB in WordPress 6 and 7.
const maxWPVersionBytes = 16 << 10

var (
	// wpVersionFile is the file of the WordPress code that sets its version, below the document root of
	// the official image (VOLUME /var/www/html), relative to the root of the container.
	wpVersionFile = "var/www/html/wp-includes/version.php"

	// containerRoot opens the root directory of the process pid of the container id, the root of that
	// container.
	containerRoot = openContainerRoot

	// wpVersionLine is a line of version.php that sets $wp_version.
	wpVersionLine = regexp.MustCompile(`(?m)^\$wp_version\b.*$`)
	// wpVersion is that line with a version of WordPress: a release (6.8.3) or a build of an alpha, a
	// beta or a release candidate, with its build number in a nightly (7.2-beta5-65467).
	wpVersion = regexp.MustCompile(`^\$wp_version = '([0-9]{1,3}(?:\.[0-9]{1,3}){1,2}(?:-(?:alpha|beta|RC)[0-9]{0,2}(?:-[0-9]{1,8})?)?)';\r?$`)
)

// wordpressVersion reads the version of WordPress the running container t ships: the value of
// $wp_version in its version.php, if the file sets it once and in the form of a version of WordPress.
// It reads that one file through the root of the container's process, follows no link out of that
// root nor one at the file, reads nothing but a regular file and quotes nothing it read.
func wordpressVersion(ctx context.Context, t Target) (map[string]any, error) {
	c, err := inspectContainer(ctx, t.Name)
	if err != nil {
		return nil, err
	}
	if !c.State.Running || c.State.Pid <= 0 {
		return nil, fmt.Errorf("container %s is not running", t.Name)
	}
	data, err := untilDone(ctx, func() ([]byte, error) { return readWPVersionFile(c.State.Pid, c.ID) })
	if err != nil {
		return nil, fmt.Errorf("container %s: %w", t.Name, err)
	}
	lines := wpVersionLine.FindAll(data, 2)
	if len(lines) != 1 {
		return nil, fmt.Errorf("container %s: /%s does not set $wp_version once", t.Name, wpVersionFile)
	}
	m := wpVersion.FindSubmatch(lines[0])
	if m == nil {
		return nil, fmt.Errorf("container %s: /%s sets $wp_version to no version of WordPress", t.Name, wpVersionFile)
	}
	return map[string]any{"version": string(m[1])}, nil
}

// readWPVersionFile reads wpVersionFile below the root of the process pid of the container id. Its
// errors name the file, never its content or where a link in it leads.
func readWPVersionFile(pid int, id string) ([]byte, error) {
	root, err := containerRoot(pid, id)
	if errors.Is(err, ErrUnsupported) {
		return nil, err
	}
	if err != nil {
		return nil, fmt.Errorf("its root cannot be opened: %v", cause(err))
	}
	defer root.Close()
	name := "/" + wpVersionFile
	f, err := openRegular(root, wpVersionFile, name)
	if err != nil {
		return nil, err
	}
	defer f.Close()
	data, err := io.ReadAll(io.LimitReader(f, maxWPVersionBytes+1))
	if err != nil {
		return nil, fmt.Errorf("%s cannot be read: %v", name, cause(err))
	}
	if len(data) > maxWPVersionBytes {
		return nil, fmt.Errorf("%s is larger than %d bytes", name, maxWPVersionBytes)
	}
	return data, nil
}

// cause is the error of the system call behind a *fs.PathError, without the path the error names.
func cause(err error) error {
	var pe *fs.PathError
	if errors.As(err, &pe) {
		return pe.Err
	}
	return err
}
