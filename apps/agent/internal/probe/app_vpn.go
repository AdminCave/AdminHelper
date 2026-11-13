// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package probe

import (
	"context"
	"errors"
	"fmt"
	"io/fs"
	"net"
	"net/netip"
	"path/filepath"
	"regexp"
	"strconv"
	"strings"
	"time"
)

const (
	// maxOpenVPNStatusBytes caps the status file: a line per client and per route, a few hundred bytes
	// each.
	maxOpenVPNStatusBytes = 4 << 20
	// maxKeepalivedBytes caps each configuration file of keepalived, maxKeepalivedFiles how many the
	// includes may add.
	maxKeepalivedBytes = 1 << 20
	maxKeepalivedFiles = 64
)

// The files the VPN views read; tests stand in their own.
var (
	openvpnStatusDir = "/run/openvpn-server"
	keepalivedConf   = "/etc/keepalived/keepalived.conf"
)

// openvpnInstance is the instance name of openvpn-server@<i>: it names a file of openvpnStatusDir and
// must not leave it.
var openvpnInstance = regexp.MustCompile(`^[A-Za-z0-9_][A-Za-z0-9_.-]*$`)

// openvpnStatus counts the clients connected to an OpenVPN server and how long ago it last wrote its
// status file. It reads the file the unit openvpn-server@<i> has the server write, never a path of
// the probe, and of each client row only that it is one: no name, no address, no byte count.
//
// OpenVPN's distro/systemd/openvpn-server@.service.in starts the server with
// "--status %t/openvpn-server/status-%i.log --status-version 2", rewritten every 60 s. Version 1
// lists the clients between the header "Common Name,Real Address,…" and "ROUTING TABLE"; versions 2
// (comma) and 3 (tab) write rows "CLIENT_LIST<sep>…" and "TIME<sep><text><sep><unix seconds>".
func openvpnStatus(ctx context.Context, t Target) (map[string]any, error) {
	instance, ok := strings.CutPrefix(strings.TrimSuffix(t.Name, ".service"), "openvpn-server@")
	if !ok {
		return nil, fmt.Errorf("%w: openvpn_status reads the status of a unit openvpn-server@<instance>", ErrUnsupported)
	}
	if !openvpnInstance.MatchString(instance) {
		return nil, fmt.Errorf("%w: an instance name of another form", ErrInvalid)
	}
	path := filepath.Join(openvpnStatusDir, "status-"+instance+".log")
	type status struct {
		data []byte
		mod  time.Time
	}
	st, err := untilDone(ctx, func() (status, error) {
		fi, err := statPath(path)
		if errors.Is(err, fs.ErrNotExist) {
			return status{}, fs.ErrNotExist
		}
		if err != nil {
			return status{}, errors.New("cannot be read")
		}
		data, err := readCapped(path, maxOpenVPNStatusBytes)
		return status{data, fi.ModTime()}, err
	})
	if errors.Is(err, fs.ErrNotExist) {
		return nil, errors.New("openvpn: the instance has no status file (--status)")
	}
	if err != nil {
		return nil, fmt.Errorf("openvpn: the status file %w", err)
	}
	clients, updated, err := parseOpenVPNStatus(st.data)
	if err != nil {
		return nil, err
	}
	if updated.IsZero() {
		updated = st.mod
	}
	return map[string]any{
		"clients":       clients,
		"updated_age_s": int64(max(now().Sub(updated), 0) / time.Second),
	}, nil
}

// parseOpenVPNStatus counts the client rows of a status file and returns the time it was written, zero
// for version 1, whose time is local text without a zone.
func parseOpenVPNStatus(data []byte) (int, time.Time, error) {
	text := string(data)
	switch {
	case strings.HasPrefix(text, "TITLE,"), strings.HasPrefix(text, "TITLE\t"):
		sep := text[len("TITLE") : len("TITLE")+1]
		clients, updated, ended := 0, time.Time{}, false
		for line := range strings.Lines(text) {
			cells := strings.Split(strings.TrimRight(line, "\r\n"), sep)
			switch cells[0] {
			case "CLIENT_LIST":
				clients++
			case "TIME":
				s, err := strconv.ParseInt(cells[len(cells)-1], 10, 64)
				if len(cells) != 3 || err != nil || s < 0 {
					return 0, time.Time{}, errors.New("openvpn: a status time of another form")
				}
				updated = time.Unix(s, 0)
			case "END":
				ended = true
			}
		}
		// A file without END or TIME is being written or of another form.
		if !ended || updated.IsZero() {
			return 0, time.Time{}, errors.New("openvpn: a status file of another form")
		}
		return clients, updated, nil
	case strings.HasPrefix(text, "OpenVPN CLIENT LIST\n"), strings.HasPrefix(text, "OpenVPN CLIENT LIST\r\n"):
		clients, in, routed := 0, false, false
		for line := range strings.Lines(text) {
			line = strings.TrimRight(line, "\r\n")
			switch {
			case strings.HasPrefix(line, "Common Name,"):
				in = true
			case line == "ROUTING TABLE":
				in, routed = false, true
			case in:
				clients++
			}
		}
		if !routed {
			return 0, time.Time{}, errors.New("openvpn: a status file of another form")
		}
		return clients, time.Time{}, nil
	}
	return 0, time.Time{}, errors.New("openvpn: a status file of another form")
}

// keepalivedVIPs counts the virtual addresses of keepalived's configuration and how many of them this
// host holds now. Of the configuration it reads the address of each line of the virtual_ipaddress and
// virtual_ipaddress_excluded blocks alone, never auth_pass or another value, and it reports no
// address; its errors quote nothing of the files.
//
// keepalived.conf(5): "#" and "!" start a comment; a block entry is "<address>[/<prefix>] [dev …]
// [label …] …", one per line; "include <file>" reads more files, a glob pattern allowed.
func keepalivedVIPs(ctx context.Context, _ Target) (map[string]any, error) {
	vips, err := untilDone(ctx, func() (map[netip.Addr]bool, error) {
		r := &keepalivedReader{vips: map[netip.Addr]bool{}}
		if err := r.read(keepalivedConf, 0); err != nil {
			return nil, err
		}
		if r.state != vipOutside {
			return nil, errors.New("keepalived: a virtual_ipaddress block without end")
		}
		return r.vips, nil
	})
	if errors.Is(err, fs.ErrNotExist) {
		return nil, fmt.Errorf("%w: keepalived has no configuration at its default path", ErrUnsupported)
	}
	if err != nil {
		return nil, err
	}
	addrs, err := interfaceAddrs()
	if err != nil {
		return nil, errors.New("keepalived: the addresses of this host cannot be read")
	}
	held := 0
	for _, a := range addrs {
		var ip net.IP
		switch x := a.(type) {
		case *net.IPNet:
			ip = x.IP
		case *net.IPAddr:
			ip = x.IP
		}
		if o, ok := netip.AddrFromSlice(ip); ok && vips[o.Unmap()] {
			held++
			delete(vips, o.Unmap()) // an address on two interfaces is held once
		}
	}
	return map[string]any{"vips": len(vips) + held, "held": held}, nil
}

// The states of keepalivedReader.
const (
	vipOutside = iota
	vipBrace   // after virtual_ipaddress, before its "{"
	vipInside
)

// keepalivedReader reads the virtual addresses out of keepalived's configuration, the included files
// in the place of their include.
type keepalivedReader struct {
	vips  map[netip.Addr]bool
	state int
	files int
}

func (r *keepalivedReader) read(path string, depth int) error {
	r.files++
	if r.files > maxKeepalivedFiles || depth > 8 {
		return fmt.Errorf("keepalived: more than %d configuration files or includes nested too deep", maxKeepalivedFiles)
	}
	data, err := readCapped(path, maxKeepalivedBytes)
	if errors.Is(err, fs.ErrNotExist) {
		return err
	}
	if err != nil {
		return fmt.Errorf("keepalived: a configuration file %w", err)
	}
	for line := range strings.Lines(string(data)) {
		if i := strings.IndexAny(line, "#!"); i >= 0 {
			line = line[:i]
		}
		line = strings.NewReplacer("{", " { ", "}", " } ").Replace(line)
		fields := strings.Fields(line)
		first := true
		for i := 0; i < len(fields); i++ {
			tok := fields[i]
			switch r.state {
			case vipOutside:
				switch tok {
				case "virtual_ipaddress", "virtual_ipaddress_excluded":
					r.state = vipBrace
				case "include":
					if i+1 >= len(fields) {
						return errors.New("keepalived: an include without a file")
					}
					i++
					if err := r.include(fields[i], depth); err != nil {
						return err
					}
				}
			case vipBrace:
				if tok != "{" {
					return errors.New("keepalived: a virtual_ipaddress without a block")
				}
				r.state = vipInside
			case vipInside:
				switch {
				case tok == "}":
					r.state = vipOutside
				case tok == "{":
					return errors.New("keepalived: a virtual address of another form")
				case first:
					addr, err := vipAddr(tok)
					if err != nil {
						return err
					}
					r.vips[addr] = true
				}
				first = false
			}
		}
	}
	return nil
}

// include reads the files of an include's glob pattern. A relative pattern is refused: where
// keepalived resolves it is not what this view should guess.
func (r *keepalivedReader) include(pattern string, depth int) error {
	if !filepath.IsAbs(pattern) {
		return errors.New("keepalived: a relative include")
	}
	matches, err := filepath.Glob(pattern)
	if err != nil {
		return errors.New("keepalived: an include of another form")
	}
	for _, m := range matches {
		if err := r.read(m, depth+1); err != nil && !errors.Is(err, fs.ErrNotExist) {
			return err
		}
	}
	return nil
}

// vipAddr reads the address of a block entry, with or without its prefix length.
func vipAddr(tok string) (netip.Addr, error) {
	if p, err := netip.ParsePrefix(tok); err == nil {
		return p.Addr().Unmap(), nil
	}
	if a, err := netip.ParseAddr(tok); err == nil && a.Zone() == "" {
		return a.Unmap(), nil
	}
	return netip.Addr{}, errors.New("keepalived: a virtual address of another form")
}
