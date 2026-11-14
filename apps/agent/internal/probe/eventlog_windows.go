// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build windows

package probe

import (
	"context"
	"encoding/binary"
	"errors"
	"fmt"
	"time"
	"unsafe"

	"golang.org/x/sys/windows"
)

// x/sys/windows has no Evt* calls; they come from wevtapi.dll (winevt.h).
var (
	wevtapi                    = windows.NewLazySystemDLL("wevtapi.dll")
	procEvtQuery               = wevtapi.NewProc("EvtQuery")
	procEvtNext                = wevtapi.NewProc("EvtNext")
	procEvtClose               = wevtapi.NewProc("EvtClose")
	procEvtCreateRenderContext = wevtapi.NewProc("EvtCreateRenderContext")
	procEvtRender              = wevtapi.NewProc("EvtRender")
)

// Values from winevt.h (EVT_QUERY_FLAGS, EVT_RENDER_CONTEXT_FLAGS, EVT_RENDER_FLAGS,
// EVT_SYSTEM_PROPERTY_ID, EVT_VARIANT_TYPE).
const (
	evtQueryChannelPath      = 0x1
	evtQueryForwardDirection = 0x100
	evtQueryReverseDirection = 0x200
	evtRenderContextSystem   = 1
	evtRenderEventValues     = 0
	evtSystemEventID         = 2
	evtSystemLevel           = 4
	evtSystemTimeCreated     = 8
	evtSystemPropertyIDEnd   = 18
	evtVarTypeByte           = 4
	evtVarTypeUInt16         = 6
	evtVarTypeFileTime       = 17
	evtVariantSize           = 16 // union (8 bytes), Count, Type
	evtNextBatch             = 64
	evtNextTimeoutMillis     = 2000
	maxEventCount            = 10000
	evtVariantTypeOffset     = 12
)

// eventInfo is what the agent keeps of one event: when, which ID, which level. Never its text.
type eventInfo struct {
	at    time.Time
	id    uint16
	level uint8
}

type evtHandle uintptr

func evtClose(h evtHandle) {
	if h != 0 {
		_, _, _ = procEvtClose.Call(uintptr(h))
	}
}

// evtQuery opens the result set of q; a channel the host does not have is ErrUnsupported.
func evtQuery(q eventQuery, flags uint32) (evtHandle, error) {
	filter, err := q.xpath()
	if err != nil {
		return 0, err
	}
	path, err := windows.UTF16PtrFromString(q.channel)
	if err != nil {
		return 0, err
	}
	query, err := windows.UTF16PtrFromString(filter)
	if err != nil {
		return 0, err
	}
	r, _, callErr := procEvtQuery.Call(0, uintptr(unsafe.Pointer(path)), uintptr(unsafe.Pointer(query)),
		uintptr(evtQueryChannelPath|flags))
	if r == 0 {
		if errors.Is(callErr, windows.ERROR_EVT_CHANNEL_NOT_FOUND) {
			return 0, fmt.Errorf("events %s: %w", q.channel, ErrUnsupported)
		}
		return 0, fmt.Errorf("events %s: %w", q.channel, callErr)
	}
	return evtHandle(r), nil
}

// evtNext fills events from the result set and tells whether the set is exhausted.
func evtNext(rs evtHandle, events []evtHandle) (int, bool, error) {
	var n uint32
	r, _, callErr := procEvtNext.Call(uintptr(rs), uintptr(len(events)), uintptr(unsafe.Pointer(&events[0])),
		evtNextTimeoutMillis, 0, uintptr(unsafe.Pointer(&n)))
	if r == 0 {
		if errors.Is(callErr, windows.ERROR_NO_MORE_ITEMS) {
			return 0, true, nil
		}
		return 0, false, callErr
	}
	return int(n), false, nil
}

// countEvents counts the events q selects without rendering any of them. The count stops at
// maxEventCount, so a flooded log costs a bounded read.
func countEvents(ctx context.Context, q eventQuery) (int, error) {
	rs, err := evtQuery(q, evtQueryForwardDirection)
	if err != nil {
		return 0, err
	}
	defer evtClose(rs)
	events := make([]evtHandle, evtNextBatch)
	count := 0
	for count < maxEventCount {
		if err := ctx.Err(); err != nil {
			return 0, err
		}
		n, end, err := evtNext(rs, events)
		if err != nil {
			return 0, fmt.Errorf("events %s: %w", q.channel, err)
		}
		for _, h := range events[:n] {
			evtClose(h)
		}
		if end {
			break
		}
		count += n
	}
	return min(count, maxEventCount), nil
}

// latestEvent returns the system values of the newest event q selects; ok is false when
// there is none.
func latestEvent(ctx context.Context, q eventQuery) (eventInfo, bool, error) {
	if err := ctx.Err(); err != nil {
		return eventInfo{}, false, err
	}
	rs, err := evtQuery(q, evtQueryReverseDirection)
	if err != nil {
		return eventInfo{}, false, err
	}
	defer evtClose(rs)
	events := make([]evtHandle, 1)
	n, end, err := evtNext(rs, events)
	if err != nil {
		return eventInfo{}, false, fmt.Errorf("events %s: %w", q.channel, err)
	}
	if end || n == 0 {
		return eventInfo{}, false, nil
	}
	defer evtClose(events[0])
	values, err := renderSystem(events[0])
	if err != nil {
		return eventInfo{}, false, fmt.Errorf("events %s: %w", q.channel, err)
	}
	info, err := systemValues(values)
	if err != nil {
		return eventInfo{}, false, fmt.Errorf("events %s: %w", q.channel, err)
	}
	return info, true, nil
}

// renderSystem renders only the system section of an event as EVT_VARIANT values.
func renderSystem(event evtHandle) ([]byte, error) {
	rc, _, callErr := procEvtCreateRenderContext.Call(0, 0, evtRenderContextSystem)
	if rc == 0 {
		return nil, callErr
	}
	defer evtClose(evtHandle(rc))
	var used, count uint32
	r, _, callErr := procEvtRender.Call(rc, uintptr(event), evtRenderEventValues, 0, 0,
		uintptr(unsafe.Pointer(&used)), uintptr(unsafe.Pointer(&count)))
	if r == 0 && !errors.Is(callErr, windows.ERROR_INSUFFICIENT_BUFFER) {
		return nil, callErr
	}
	// uint64 words keep the variants 8-byte aligned.
	words := make([]uint64, (used+7)/8)
	if len(words) == 0 {
		return nil, errors.New("empty render")
	}
	r, _, callErr = procEvtRender.Call(rc, uintptr(event), evtRenderEventValues, uintptr(len(words)*8),
		uintptr(unsafe.Pointer(&words[0])), uintptr(unsafe.Pointer(&used)), uintptr(unsafe.Pointer(&count)))
	if r == 0 {
		return nil, callErr
	}
	buf := unsafe.Slice((*byte)(unsafe.Pointer(&words[0])), len(words)*8)
	if int(count) < evtSystemPropertyIDEnd || len(buf) < evtSystemPropertyIDEnd*evtVariantSize {
		return nil, fmt.Errorf("render: %d values", count)
	}
	// Copy the fixed-size variants only; their pointers into the buffer are never read.
	return append([]byte(nil), buf[:evtSystemPropertyIDEnd*evtVariantSize]...), nil
}

// systemValues reads ID, level and time from the rendered system variants.
func systemValues(values []byte) (eventInfo, error) {
	variant := func(id int) (uint64, uint32) {
		v := values[id*evtVariantSize : (id+1)*evtVariantSize]
		return binary.LittleEndian.Uint64(v),
			binary.LittleEndian.Uint32(v[evtVariantTypeOffset:])
	}
	var info eventInfo
	at, typ := variant(evtSystemTimeCreated)
	if typ != evtVarTypeFileTime {
		return eventInfo{}, fmt.Errorf("render: TimeCreated type %d", typ)
	}
	ft := windows.Filetime{LowDateTime: uint32(at), HighDateTime: uint32(at >> 32)}
	info.at = time.Unix(0, ft.Nanoseconds())
	if id, typ := variant(evtSystemEventID); typ == evtVarTypeUInt16 {
		info.id = uint16(id)
	}
	if level, typ := variant(evtSystemLevel); typ == evtVarTypeByte {
		info.level = uint8(level)
	}
	return info, nil
}
