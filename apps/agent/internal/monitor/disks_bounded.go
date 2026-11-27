// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package monitor

import (
	"strings"
	"sync"
	"time"
)

// shareStatTimeout bounds the statfs of the network mounts on FreeBSD (R-1701).
const shareStatTimeout = 5 * time.Second

// afterAnswer is a seam for the tests: it runs once the answer for mount is queued.
var afterAnswer = func(mount string) {}

// freebsdNetFS says whether a FreeBSD file system type waits on another host for its statfs and
// hangs with it: nfs, smbfs, and FUSE, whose mounts carry their subtype as "fusefs.<subtype>"
// (sshfs among them).
func freebsdNetFS(fstype string) bool {
	return fstype == "nfs" || fstype == "smbfs" || fstype == "fusefs" || strings.HasPrefix(fstype, "fusefs.")
}

// pendingStats holds the mounts whose stat has not come back yet, across runs: a hung mount keeps
// one goroutine (and with it one OS thread) in the kernel, and a long-running agent must not add
// one per run (R-1772).
var pendingStats = struct {
	sync.Mutex
	mounts map[string]bool
}{mounts: map[string]bool{}}

// uniqueMounts drops a path that is listed twice (a stacked mount shows up once per layer in
// getfsstat) so that the count of mounts left out is not raised by a path that was asked once.
func uniqueMounts(mounts []string) []string {
	seen := make(map[string]bool, len(mounts))
	var out []string
	for _, m := range mounts {
		if !seen[m] {
			seen[m] = true
			out = append(out, m)
		}
	}
	return out
}

// underNetMount says whether mount lies below one of the network mounts shares: resolving its path
// walks through the share and hangs with it.
func underNetMount(mount string, shares []string) bool {
	for _, share := range shares {
		if share != mount && strings.HasPrefix(mount, strings.TrimSuffix(share, "/")+"/") {
			return true
		}
	}
	return false
}

// boundedStats asks stat for every mount at once and waits for all of them until deadline fires:
// a mount that has not answered by then is left out, in the order of mounts otherwise. The
// goroutine of a hung mount stays in the kernel until the mount answers; the run does not wait
// for it, and later runs do not ask that mount again until it has answered, so it stays left out.
func boundedStats(mounts []string, deadline <-chan time.Time, stat func(string) (fsStat, error)) []fsStat {
	type answer struct {
		i  int
		st fsStat
		ok bool
	}
	answers := make(chan answer, len(mounts))
	queued := afterAnswer
	asked := 0
	pendingStats.Lock()
	for i, m := range mounts {
		if pendingStats.mounts[m] {
			continue
		}
		pendingStats.mounts[m] = true
		asked++
		go func() {
			st, err := stat(m)
			pendingStats.Lock()
			delete(pendingStats.mounts, m)
			pendingStats.Unlock()
			answers <- answer{i, st, err == nil}
			queued(m)
		}()
	}
	pendingStats.Unlock()
	got := make([]*fsStat, len(mounts))
wait:
	for range asked {
		select {
		case a := <-answers:
			if a.ok {
				got[a.i] = &a.st
			}
		case <-deadline:
			// Answers already queued when the deadline fires still count.
			for {
				select {
				case a := <-answers:
					if a.ok {
						got[a.i] = &a.st
					}
				default:
					break wait
				}
			}
		}
	}
	var stats []fsStat
	for _, st := range got {
		if st != nil {
			stats = append(stats, *st)
		}
	}
	return stats
}
