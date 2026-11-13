// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package probe

import (
	"context"
	"errors"
	"os"
	"os/exec"
	"path/filepath"
	"slices"
	"testing"
)

// versionPHP is wp-includes/version.php of WordPress 7 (trimmed) with line where it sets $wp_version.
func versionPHP(line string) string {
	return "<?php\n/**\n * WordPress Version\n *\n * Contains version information for the current WordPress release.\n" +
		" *\n * @package WordPress\n * @since 1.2.0\n */\n\n/**\n * The WordPress version string.\n *\n" +
		" * @global string $wp_version\n */\n" + line + "\n\n/**\n * Holds the WordPress DB revision.\n *\n" +
		" * @global int $wp_db_version\n */\n$wp_db_version = 60717;\n\n/**\n * Holds the TinyMCE version.\n *\n" +
		" * @global string $tinymce_version\n */\n$tinymce_version = '49110-20250317';\n"
}

// wpContainer is the root of a running container web whose version.php holds content (none if
// content is empty); it stubs docker and containerRoot and returns the pids the view opened roots of.
func wpContainer(t *testing.T, content string) (string, *[]int) {
	t.Helper()
	root := t.TempDir()
	if content != "" {
		writeWPFile(t, root, content)
	}
	stubTool(t, inspectJSON(t, "running", "", "bridge"), nil)
	return root, stubContainerRoot(t, func(int) (*os.Root, error) { return os.OpenRoot(root) })
}

func writeWPFile(t *testing.T, root, content string) {
	t.Helper()
	path := filepath.Join(root, filepath.FromSlash(wpVersionFile))
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, []byte(content), 0o644); err != nil {
		t.Fatal(err)
	}
}

func stubContainerRoot(t *testing.T, open func(int) (*os.Root, error)) *[]int {
	t.Helper()
	var pids []int
	old := containerRoot
	containerRoot = func(pid int) (*os.Root, error) {
		pids = append(pids, pid)
		return open(pid)
	}
	t.Cleanup(func() { containerRoot = old })
	return &pids
}

func wpTarget() Target { return Target{Kind: kindContainer, Name: "web"} }

func TestTheWordPressViewAsksARunningContainer(t *testing.T) {
	_, pids := wpContainer(t, versionPHP("$wp_version = '6.8.12';"))
	tl := stubTool(t, inspectJSON(t, "exited", "", "bridge"), nil)
	if _, err := wordpressVersion(context.Background(), wpTarget()); err == nil || err.Error() != "container web is not running" {
		t.Errorf("a stopped container = %v, want it not running", err)
	}
	if len(*pids) != 0 {
		t.Errorf("opened the roots of %v, want none of a stopped container", *pids)
	}
	if want := []string{"docker", "inspect", "--type", "container", "--", "web"}; !slices.Equal(tl.args, want) {
		t.Errorf("runTool %v, want %v", tl.args, want)
	}
	tl.out, tl.err = "", &exec.Error{Name: "docker", Err: exec.ErrNotFound}
	if _, err := wordpressVersion(context.Background(), wpTarget()); !errors.Is(err, ErrUnsupported) {
		t.Errorf("no docker = %v, want ErrUnsupported", err)
	}
}

func TestTheWordPressViewOutsideLinux(t *testing.T) {
	stubTool(t, inspectJSON(t, "running", "", "bridge"), nil)
	stubContainerRoot(t, func(int) (*os.Root, error) { return nil, errors.Join(ErrUnsupported, errors.New("not linux")) })
	if _, err := wordpressVersion(context.Background(), wpTarget()); !errors.Is(err, ErrUnsupported) {
		t.Errorf("error %v, want ErrUnsupported", err)
	}
	stubContainerRoot(t, func(int) (*os.Root, error) {
		return nil, &os.PathError{Op: "openat", Path: "/proc/4242/root", Err: errors.New("gone")}
	})
	_, err := wordpressVersion(context.Background(), wpTarget())
	if err == nil || err.Error() != "container web: its root cannot be opened: gone" {
		t.Errorf("a root that cannot be opened = %v", err)
	}
}
