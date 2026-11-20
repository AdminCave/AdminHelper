// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package probe

import (
	"context"
	"errors"
	"fmt"
	"math"
	"runtime"
	"strconv"
	"strings"
	"time"
)

// shareTimeout bounds the statfs of a share: a share that answers no later hangs (R-1267).
const shareTimeout = 10 * time.Second

// netShareGOOS and mountTable are seams for the tests.
var (
	netShareGOOS = runtime.GOOS
	mountTable   = Mounts
)

// netShareUsage reads how full the network share mounted at the target's mount point is. It asks
// statfs only of a mount point the mount table names as a network share, and asks it in a process of
// its own (stat -f through the allowlist, shareTimeout): a share that hangs leaves a statfs in the
// kernel that no goroutine gets back from. The process is killed at the timeout, but whether the
// kernel ends a statfs on a hung NFS or CIFS mount then is not verified on a real hung share; the
// check does not wait for it and reports hung=true.
// A mount point the table no longer lists is mounted=false, one that holds a local file system is
// refused; a stat that does not end in time is hung=true. The source of the share stays unread.
func netShareUsage(ctx context.Context, t Target) (map[string]any, error) {
	if netShareGOOS != "linux" {
		return nil, fmt.Errorf("%w: network shares are checked on Linux alone", ErrUnsupported)
	}
	mounts, err := mountTable()
	if err != nil {
		return nil, fmt.Errorf("%w: the mount table cannot be read", ErrUnsupported)
	}
	fstype, mounted := "", false
	for _, m := range mounts {
		if m.Mountpoint == t.Name {
			fstype, mounted = m.FSType, true
		}
	}
	switch {
	case !mounted:
		return map[string]any{"mounted": false, "hung": false}, nil
	case !NetFSTypes[fstype]:
		return nil, fmt.Errorf("%w: %s holds no network share", ErrInvalid, t.Name)
	}
	out, err := runTool(ctx, shareTimeout, "stat", "-f", "-c", "%S %b %f %a", "--", t.Name)
	switch {
	case errors.Is(err, context.DeadlineExceeded) && ctx.Err() == nil:
		return map[string]any{"mounted": true, "hung": true}, nil
	case err != nil:
		return nil, toolError("stat", err)
	}
	u, err := parseStatF(out)
	if err != nil {
		return nil, err
	}
	return map[string]any{
		"mounted":      true,
		"hung":         false,
		"used_percent": share(u.total-u.free, u.total-u.free+u.avail),
		"free_gb":      math.Round(float64(u.avail)/(1<<30)*10) / 10,
	}, nil
}

// parseStatF reads the line stat -f -c "%S %b %f %a" writes: the block size, then the blocks in all,
// free and free to a user other than root.
func parseStatF(out []byte) (fsUsage, error) {
	f := strings.Fields(string(out))
	if len(f) != 4 {
		return fsUsage{}, fmt.Errorf("%w: stat -f wrote %d fields", ErrUnsupported, len(f))
	}
	var n [4]uint64
	for i, s := range f {
		v, err := strconv.ParseUint(s, 10, 64)
		if err != nil {
			return fsUsage{}, fmt.Errorf("%w: stat -f wrote no number", ErrUnsupported)
		}
		n[i] = v
	}
	size := n[0]
	if size == 0 || n[1] > math.MaxUint64/size || n[2] > n[1] || n[3] > n[2] {
		return fsUsage{}, fmt.Errorf("%w: stat -f wrote sizes out of range", ErrUnsupported)
	}
	return fsUsage{total: n[1] * size, free: n[2] * size, avail: n[3] * size}, nil
}
