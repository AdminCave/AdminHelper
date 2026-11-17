// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package probe

import (
	"archive/tar"
	"context"
	"errors"
	"io"
	"os/exec"
	"path"
	"regexp"
	"slices"
	"strings"

	"adminhelper-agent/internal/allowlist"
)

const (
	// maxContainerConfBytes bounds the archives the agent reads of one container, all together: the
	// configuration of its web server (Kevin 2026-11-17).
	maxContainerConfBytes = 4 << 20
	// maxContainerLinks bounds the links the agent follows from one path in a container.
	maxContainerLinks = 8
)

var (
	// runToolReader runs an allowlisted tool and hands its stdout to read as a stream; tests stand in
	// their own.
	runToolReader = allowlist.RunReader

	errNotInContainer     = errors.New("the container holds no such file")
	errContainerConfLarge = errors.New("the configuration in the container is larger than the agent reads")
	errContainerLinks     = errors.New("too many links in the container")
	errContainerNoFile    = errors.New("the path in the container is no regular file")

	// ctrPath is a plain absolute path in a container, the allowlist's <ctrpath>.
	ctrPath = regexp.MustCompile(`^(?:/[A-Za-z0-9_,@+-][A-Za-z0-9_.,@+-]*)+$`)
)

// containerFS reads files of one container through its archive (docker cp <id>:<path> -, the CLI of
// GET /containers/{id}/archive), never by running anything in it (Kevin 2026-11-17). docker cp sends a
// link as a link (without -L): the agent follows it itself, so it never asks for a target that looks like
// a key. Its errors name no path, the paths stay on the host.
type containerFS struct {
	id   string
	left int64 // bytes of archive the agent still reads of this container
}

func newContainerFS(id string) *containerFS {
	return &containerFS{id: id, left: maxContainerConfBytes}
}

// keyLike says whether a file looks like a private key by its name: the agent skips it unread when it
// comes in the archive of a directory (Kevin 2026-11-17).
func keyLike(name string) bool {
	name = strings.ToLower(name)
	return strings.HasSuffix(name, ".key") || strings.HasSuffix(name, ".pem")
}

// archive streams the archive of p and hands each entry to each, which reads its content or leaves it:
// tar skips what it leaves, through a small buffer, never kept. errNotInContainer for a path docker cp
// does not find (or a container gone).
func (c *containerFS) archive(ctx context.Context, p string, each func(*tar.Header, io.Reader) error) error {
	if !ctrPath.MatchString(p) {
		return errNotInContainer
	}
	err := runToolReader(ctx, toolTimeout, func(r io.Reader) error {
		tr := tar.NewReader(&budgetReader{r: r, left: &c.left})
		for {
			h, err := tr.Next()
			if errors.Is(err, io.EOF) {
				return nil
			}
			if err != nil {
				return err
			}
			if err := each(h, tr); err != nil {
				return err
			}
		}
	}, "docker", "cp", "--", c.id+":"+p, "-")
	if exitErr := (*exec.ExitError)(nil); errors.As(err, &exitErr) {
		return errNotInContainer
	}
	return err
}

// file is the content of the regular file p, at most limit bytes; a link it follows.
func (c *containerFS) file(ctx context.Context, p string, limit int64) ([]byte, error) {
	return c.fileOf(ctx, p, limit, nil)
}

// fileOf is file; a link whose target refuse names ends it with errNotInContainer, unasked.
func (c *containerFS) fileOf(ctx context.Context, p string, limit int64, refuse func(string) bool) ([]byte, error) {
	for range maxContainerLinks + 1 {
		var data []byte
		link, found := "", false
		err := c.archive(ctx, p, func(h *tar.Header, r io.Reader) error {
			if found {
				return nil
			}
			found = true
			switch h.Typeflag {
			case tar.TypeReg:
				if h.Size > limit {
					return errContainerConfLarge
				}
				var err error
				data, err = io.ReadAll(io.LimitReader(r, limit))
				return err
			case tar.TypeSymlink:
				link = h.Linkname
				return nil
			}
			return errContainerNoFile
		})
		switch {
		case err != nil:
			return nil, err
		case !found:
			return nil, errNotInContainer
		case link == "":
			return data, nil
		}
		if p = linkTarget(p, link); refuse != nil && refuse(p) {
			return nil, errNotInContainer
		}
	}
	return nil, errContainerLinks
}

// keyPath says whether the file at p looks like a key (keyLike of its name).
func keyPath(p string) bool { return keyLike(path.Base(p)) }

// linkTarget is the path a link at p points to.
func linkTarget(p, link string) string {
	if path.IsAbs(link) {
		return path.Clean(link)
	}
	return path.Join(path.Dir(p), link)
}

// containerFile is a file of a directory the agent read from a container.
type containerFile struct {
	name string
	text []byte
}

// glob is the files of the directory of pattern whose path matches it, in the order of their names (the
// order nginx and Apache read them in), each at most limit bytes: the archive of the directory, its other
// entries and the ones that look like a key (keyLike) skipped unread, a link among them followed unless it
// leads to a key. A directory that is a link is followed too; the files keep their names below the path
// the pattern names. A pattern whose directory is a pattern itself gives errNotInContainer; one that
// matches nothing, or a directory that is not there, no file.
func (c *containerFS) glob(ctx context.Context, pattern string, limit int64) ([]containerFile, error) {
	dir := path.Dir(pattern)
	if strings.ContainsAny(dir, `*?[\`) {
		return nil, errNotInContainer
	}
	from := dir
	for range maxContainerLinks + 1 {
		files, link, err := c.globIn(ctx, from, dir, path.Base(pattern), limit)
		if link == "" || err != nil {
			return files, err
		}
		from = linkTarget(from, link)
	}
	return nil, errContainerLinks
}

// globIn is glob over the archive of the directory from, its files named below dir; link is the target
// of from when from is a link.
func (c *containerFS) globIn(ctx context.Context, from, dir, base string, limit int64) (files []containerFile, link string, err error) {
	var links []string
	err = c.archive(ctx, from, func(h *tar.Header, r io.Reader) error {
		top, rest, _ := strings.Cut(h.Name, "/")
		if rest == "" && h.Typeflag == tar.TypeSymlink && top == path.Base(from) {
			link = h.Linkname
			return nil
		}
		rest = strings.TrimSuffix(rest, "/")
		if rest == "" || strings.Contains(rest, "/") || keyLike(rest) {
			return nil
		}
		if m, _ := path.Match(base, rest); !m {
			return nil
		}
		name := path.Join(dir, rest)
		switch h.Typeflag {
		case tar.TypeReg:
			if h.Size > limit {
				return errContainerConfLarge
			}
			text, err := io.ReadAll(io.LimitReader(r, limit))
			if err != nil {
				return err
			}
			files = append(files, containerFile{name: name, text: text})
		case tar.TypeSymlink:
			if target := linkTarget(path.Join(from, rest), h.Linkname); !keyPath(target) {
				links = append(links, name, target)
			}
		}
		return nil
	})
	if errors.Is(err, errNotInContainer) {
		return nil, "", nil
	}
	if err != nil || link != "" {
		return nil, link, err
	}
	for i := 0; i < len(links); i += 2 {
		text, err := c.fileOf(ctx, links[i+1], limit, keyPath)
		if errors.Is(err, errNotInContainer) || errors.Is(err, errContainerNoFile) {
			continue // dangling, a directory or a key: no file the server reads here
		}
		if err != nil {
			return nil, "", err
		}
		files = append(files, containerFile{name: links[i], text: text})
	}
	slices.SortFunc(files, func(a, b containerFile) int { return strings.Compare(a.name, b.name) })
	return files, "", nil
}

// budgetReader reads r until left runs out, then fails with errContainerConfLarge.
type budgetReader struct {
	r    io.Reader
	left *int64
}

func (b *budgetReader) Read(p []byte) (int, error) {
	if *b.left <= 0 {
		return 0, errContainerConfLarge
	}
	if int64(len(p)) > *b.left {
		p = p[:*b.left]
	}
	n, err := b.r.Read(p)
	*b.left -= int64(n)
	return n, err
}
