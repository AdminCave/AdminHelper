// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build freebsd

package probe

import (
	"context"
	"fmt"
)

// unitOwner is not supported: an rc.d service has no cgroup to tie its processes to.
func unitOwner(context.Context, string) (func(pid int32) bool, error) {
	return nil, fmt.Errorf("%w: a unit target on FreeBSD", ErrUnsupported)
}

// containerEndpoint: the agent resolves no container networks on FreeBSD.
func containerEndpoint(context.Context, Target) (endpoint, error) {
	return endpoint{}, fmt.Errorf("%w: a container target on FreeBSD", ErrUnsupported)
}
