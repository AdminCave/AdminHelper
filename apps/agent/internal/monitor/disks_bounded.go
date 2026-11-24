// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package monitor

import (
	"strings"
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

// boundedStats asks stat for every mount at once and waits for all of them until deadline fires:
// a mount that has not answered by then is left out, in the order of mounts otherwise. The
// goroutine of a hung mount stays in the kernel until the mount answers; the run does not wait
// for it.
func boundedStats(mounts []string, deadline <-chan time.Time, stat func(string) (fsStat, error)) []fsStat {
	type answer struct {
		i  int
		st fsStat
		ok bool
	}
	answers := make(chan answer, len(mounts))
	queued := afterAnswer
	for i, m := range mounts {
		go func() {
			st, err := stat(m)
			answers <- answer{i, st, err == nil}
			queued(m)
		}()
	}
	got := make([]*fsStat, len(mounts))
wait:
	for range mounts {
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
