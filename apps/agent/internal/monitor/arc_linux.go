// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build linux

package monitor

import (
	"bufio"
	"bytes"
	"os"
	"strconv"
	"strings"
)

// arcstatsPath is OpenZFS's ARC kstat on Linux; there is none without the zfs module.
const arcstatsPath = "/proc/spl/kstat/zfs/arcstats"

// arcReclaimable is the ARC above c_min in bytes, 0 without ZFS or when the kstat cannot be read.
func arcReclaimable() uint64 {
	data, err := os.ReadFile(arcstatsPath)
	if err != nil {
		return 0
	}
	return parseArcstats(data)
}

// parseArcstats reads size and c_min from the kstat text (a header line, then "name type data"
// lines) and returns size - c_min, 0 when either is missing or size is below c_min.
func parseArcstats(data []byte) uint64 {
	var size, cMin uint64
	var haveSize, haveMin bool
	sc := bufio.NewScanner(bytes.NewReader(data))
	for sc.Scan() {
		f := strings.Fields(sc.Text())
		if len(f) != 3 || (f[0] != "size" && f[0] != "c_min") {
			continue
		}
		v, err := strconv.ParseUint(f[2], 10, 64)
		if err != nil {
			continue
		}
		if f[0] == "size" {
			size, haveSize = v, true
		} else {
			cMin, haveMin = v, true
		}
	}
	if !haveSize || !haveMin {
		return 0
	}
	return arcAbove(size, cMin)
}
