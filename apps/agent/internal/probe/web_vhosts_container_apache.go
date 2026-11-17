// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package probe

import (
	"context"
	"errors"
	"path"
	"slices"
	"strconv"
	"strings"
)

// containerApacheConfs are where the main file of Apache lies in an image and the ServerRoot it was built
// with: the official httpd image, the Debian package (php:apache and the like), the RHEL package.
var containerApacheConfs = []struct{ conf, root string }{
	{"/usr/local/apache2/conf/httpd.conf", "/usr/local/apache2"},
	{"/etc/apache2/apache2.conf", "/etc/apache2"},
	{"/etc/httpd/conf/httpd.conf", "/etc/httpd"},
}

// containerApacheVhosts reads the vhosts of the Apache in a container: the <VirtualHost> blocks of its main
// file and the files it includes, with ServerName, ServerAlias, SSLEngine and SSLCertificateFile. A container without a main
// file at a known path has no Apache the agent reads. apachectl -S is not there to ask: every
// <VirtualHost> counts, also one in an <IfModule> or <IfDefine> that would not load.
func containerApacheVhosts(ctx context.Context, fs *containerFS) ([]Vhost, error) {
	for _, at := range containerApacheConfs {
		text, err := fs.file(ctx, at.conf, maxApacheFileBytes)
		if errors.Is(err, errNotInContainer) {
			continue
		}
		if err != nil {
			return nil, err
		}
		a := &containerApache{fs: fs, root: at.root, seen: map[string]bool{at.conf: true}}
		dirs, err := a.directives(ctx, text)
		if err != nil {
			return nil, err
		}
		return apacheBlockVhosts(dirs), nil
	}
	return nil, nil
}

// containerApache reads the directives of Apache's configuration in a container, each file once and no
// more than maxApacheFiles of them.
type containerApache struct {
	fs   *containerFS
	root string
	seen map[string]bool
}

// directives are the directives of text with those of the files it includes (Include, IncludeOptional:
// a file, a directory, a pattern of the last part; relative to ServerRoot) in their place, as Apache
// reads them. A ServerRoot takes effect for the includes after it. An include of a file that is not there
// or looks like a key adds none.
func (a *containerApache) directives(ctx context.Context, text []byte) ([]apacheDirective, error) {
	var out []apacheDirective
	for _, d := range apacheDirectives(text) {
		key := strings.ToLower(d.f[0])
		switch {
		case key == "serverroot" && len(d.f) == 2:
			a.root = strings.Trim(d.f[1], `"`)
		case (key == "include" || key == "includeoptional") && len(d.f) == 2:
			files, err := a.include(ctx, strings.Trim(d.f[1], `"`))
			if err != nil {
				return nil, err
			}
			for _, f := range files {
				if a.seen[f.name] {
					continue
				}
				if len(a.seen) >= maxApacheFiles {
					return nil, errContainerConfLarge
				}
				a.seen[f.name] = true
				inc, err := a.directives(ctx, f.text)
				if err != nil {
					return nil, err
				}
				out = append(out, inc...)
			}
			continue
		}
		out = append(out, d)
	}
	return out, nil
}

// include is the files an Include names: the files of a pattern or of a directory (Apache reads each
// file in it), else the file.
func (a *containerApache) include(ctx context.Context, name string) ([]containerFile, error) {
	if !path.IsAbs(name) {
		name = path.Join(a.root, name)
	}
	// Debian's modules (mods-enabled: LoadModule and their settings, no <VirtualHost>) are links each,
	// and each link costs a docker cp of its own: left out.
	if path.Base(path.Dir(name)) == "mods-enabled" || path.Base(name) == "mods-enabled" {
		return nil, nil
	}
	if strings.ContainsAny(name, `*?[`) {
		return a.fs.glob(ctx, name, maxApacheFileBytes)
	}
	if keyPath(name) {
		return nil, nil
	}
	text, err := a.fs.fileOf(ctx, name, maxApacheFileBytes, keyPath)
	switch {
	case err == nil:
		return []containerFile{{name: name, text: text}}, nil
	case errors.Is(err, errContainerNoFile):
		return a.fs.glob(ctx, name+"/*", maxApacheFileBytes)
	case errors.Is(err, errNotInContainer):
		return nil, nil
	}
	return nil, err
}

// apacheBlockVhosts are the vhosts of the <VirtualHost> blocks among dirs, each name on each port its
// addresses name (<VirtualHost *:80 [::]:80>); a block on no port (<VirtualHost *>) adds none, as one
// without a ServerName adds only its aliases (apachectl -S would list it under a name it inherits).
func apacheBlockVhosts(dirs []apacheDirective) []Vhost {
	var vhosts []Vhost
	for i := 0; i < len(dirs); i++ {
		if strings.ToLower(dirs[i].f[0]) != "<virtualhost" {
			continue
		}
		var ports []uint16
		for _, addr := range dirs[i].f[1:] {
			_, p, ok := cutLast(strings.TrimSuffix(addr, ">"), ":")
			port, err := strconv.ParseUint(p, 10, 16)
			if ok && err == nil && port > 0 && !slices.Contains(ports, uint16(port)) {
				ports = append(ports, uint16(port))
			}
		}
		var b apacheVhostBlock
		for i++; i < len(dirs) && strings.ToLower(dirs[i].f[0]) != "</virtualhost>"; i++ {
			b.set(dirs[i].f)
		}
		names := b.aliases
		if b.name != "" {
			names = append([]string{apacheServerName(b.name)}, names...)
		}
		for _, port := range ports {
			for _, n := range names {
				if name := vhostName(n); name != "" {
					v := Vhost{Server: "apache", Name: name, Port: port, TLS: b.tls}
					if v.TLS {
						v.cert = b.cert
					}
					vhosts = append(vhosts, v)
				}
			}
		}
	}
	return vhosts
}

// apacheServerName is the host of a ServerName ([scheme://]host[:port]).
func apacheServerName(s string) string {
	if _, rest, ok := strings.Cut(s, "://"); ok {
		s = rest
	}
	if host, port, ok := cutLast(s, ":"); ok {
		if _, err := strconv.ParseUint(port, 10, 16); err == nil {
			return host
		}
	}
	return s
}

// cutLast is strings.Cut at the last sep.
func cutLast(s, sep string) (before, after string, found bool) {
	if i := strings.LastIndex(s, sep); i >= 0 {
		return s[:i], s[i+len(sep):], true
	}
	return s, "", false
}
