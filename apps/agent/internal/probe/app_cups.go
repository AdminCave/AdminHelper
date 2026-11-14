// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package probe

import (
	"bytes"
	"context"
	"errors"
	"fmt"
	"os/exec"
	"strings"
)

// cupsQueues counts the print queues of the local CUPS server and those disabled (stopped by an
// admin or after a backend error), from `lpstat -p` in the C locale: CUPS translates the lines, and
// only the untranslated ones are "printer <name> …" with " disabled since " for a stopped queue
// (systemv/lpstat.c). The queue names stay on this host.
func cupsQueues(ctx context.Context, _ Target) (map[string]any, error) {
	out, err := runToolEnv(ctx, toolTimeout, []string{"LC_ALL=C"}, "lpstat", "-p")
	var exitErr *exec.ExitError
	switch {
	case errors.Is(err, exec.ErrNotFound):
		return nil, fmt.Errorf("%w: lpstat is not installed", ErrUnsupported)
	case errors.As(err, &exitErr) && bytes.Contains(exitErr.Stderr, []byte("No destinations added")):
		// A CUPS without queues ends with 1 and says so.
		return map[string]any{"queues": 0, "queues_disabled": 0}, nil
	case err != nil:
		return nil, toolError("lpstat", err)
	}
	return cupsValues(string(out)), nil
}

func cupsValues(out string) map[string]any {
	queues, disabled := 0, 0
	for line := range strings.SplitSeq(out, "\n") {
		if !strings.HasPrefix(line, "printer ") {
			continue
		}
		queues++
		if strings.Contains(line, " disabled since ") {
			disabled++
		}
	}
	return map[string]any{"queues": queues, "queues_disabled": disabled}
}
