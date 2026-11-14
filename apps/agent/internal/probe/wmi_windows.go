// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build windows

package probe

import (
	"context"
	"errors"
	"fmt"
	"reflect"

	"github.com/go-ole/go-ole"
	"github.com/yusufpapurcu/wmi"
)

// WBEM codes for a class or namespace the host does not have: the role is not installed.
const (
	wbemInvalidNamespace = 0x8004100E
	wbemInvalidClass     = 0x80041010
)

// wmiSlot lets one WMI query run at a time. A query WMI never answers keeps its slot, so a
// hung provider costs one goroutine, not one per interval.
var wmiSlot = make(chan struct{}, 1)

// run reads q into dst, a pointer to a slice of structs. dst changes only on success: a
// query that outlives ctx keeps writing into its own copy.
func (q wmiQuery) run(ctx context.Context, dst any) error {
	query, err := q.wql(dst)
	if err != nil {
		return err
	}
	select {
	case wmiSlot <- struct{}{}:
	case <-ctx.Done():
		return ctx.Err()
	}
	rows := reflect.New(reflect.TypeOf(dst).Elem())
	done := make(chan error, 1)
	go func() {
		defer func() { <-wmiSlot }()
		done <- wmi.QueryNamespace(query, rows.Interface(), q.namespace)
	}()
	select {
	case err := <-done:
		if err != nil {
			return wmiError(q, err)
		}
		reflect.ValueOf(dst).Elem().Set(rows.Elem())
		return nil
	case <-ctx.Done():
		return ctx.Err()
	}
}

// wmiError maps a missing class or namespace to ErrUnsupported. go-ole reports a failed
// call as DISP_E_EXCEPTION and puts the WBEM code into the exception info.
func wmiError(q wmiQuery, err error) error {
	var oe *ole.OleError
	if errors.As(err, &oe) {
		code := uint32(oe.Code())
		if ei, ok := oe.SubError().(ole.EXCEPINFO); ok && ei.SCODE() != 0 {
			code = ei.SCODE()
		}
		if code == wbemInvalidClass || code == wbemInvalidNamespace {
			return fmt.Errorf("wmi %s %s: %w", q.namespace, q.class, ErrUnsupported)
		}
	}
	return fmt.Errorf("wmi %s %s: %w", q.namespace, q.class, err)
}
