// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build linux

package probe

import (
	"context"
	"errors"
	"fmt"
	"io/fs"
	"net"
	"os"
	"strconv"

	"golang.org/x/sys/unix"
)

// dialRootSocket connects to the first of wpDBSockets below root that exists. It opens the name as a path
// (O_PATH, to which os.Root adds O_NOFOLLOW; no link out of root), checks that it is a socket and connects
// through /proc/self/fd to that very inode: a link put at the name since is never followed out of the
// container.
func dialRootSocket(ctx context.Context, root *os.Root) (net.Conn, error) {
	for _, name := range wpDBSockets {
		p, err := root.OpenFile(name, unix.O_PATH, 0)
		if errors.Is(err, fs.ErrNotExist) {
			continue
		}
		if err != nil {
			return nil, fmt.Errorf("%w: /%s cannot be opened: %v", errWPSocket, name, cause(err))
		}
		defer p.Close()
		if fi, err := p.Stat(); err != nil || fi.Mode().Type() != fs.ModeSocket {
			return nil, fmt.Errorf("%w: /%s is no socket", errWPSocket, name)
		}
		var d net.Dialer
		c, err := d.DialContext(ctx, "unix", "/proc/self/fd/"+strconv.Itoa(int(p.Fd())))
		if err != nil {
			var oe *net.OpError
			if errors.As(err, &oe) {
				err = oe.Err
			}
			return nil, fmt.Errorf("%w: /%s takes no connection: %v", errWPSocket, name, err)
		}
		return c, nil
	}
	return nil, fmt.Errorf("%w: it holds neither /%s nor /%s", errWPSocket, wpDBSockets[0], wpDBSockets[1])
}
