// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package probe

import (
	"context"
	"math"
)

func init() {
	sensors["fs"] = fsSensor
}

// fsUsage is what statfs says of a file system: its blocks in bytes, its inodes in counts. Avail is
// what a user other than root may still write, as df counts it.
type fsUsage struct {
	total, free, avail uint64
	inodes, inodesFree uint64
}

// fsSensor reads how full the file system is that holds the directory of the parameter path: the share
// of its space in use (as df counts it, without the blocks reserved for root), the bytes a user may
// still write and the share of its inodes in use, 0 on a file system without a fixed number of inodes
// (btrfs). With a target container the path is one inside that container (containerPath). It opens the
// directory alone and reads no file.
func fsSensor(ctx context.Context, p Probe, _ string) (map[string]any, error) {
	var usage func() (fsUsage, error)
	if p.Target == nil {
		path, err := pathParam(p)
		if err != nil {
			return nil, err
		}
		usage = func() (fsUsage, error) { return dirStatfs(nil, path, path) }
	} else {
		source, rel, path, err := containerPath(ctx, p, "path")
		if err != nil {
			return nil, err
		}
		usage = func() (fsUsage, error) {
			root, rel, err := openMount(source, rel)
			if err != nil {
				return fsUsage{}, err
			}
			defer root.Close()
			return dirStatfs(root, rel, path)
		}
	}
	u, err := untilDone(ctx, usage)
	if err != nil {
		return nil, err
	}
	return fsValues(u), nil
}

// fsValues are the fields of fsSensor for u.
func fsValues(u fsUsage) map[string]any {
	return map[string]any{
		"used_pct":        share(u.total-u.free, u.total-u.free+u.avail),
		"free_bytes":      u.avail,
		"inodes_used_pct": share(u.inodes-u.inodesFree, u.inodes),
	}
}

// share is part of whole in percent, to one decimal; 0 of a whole of 0.
func share(part, whole uint64) float64 {
	if whole == 0 {
		return 0
	}
	return math.Round(float64(part)/float64(whole)*1000) / 10
}
