// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package probe

import (
	"bytes"
	"context"
	"errors"
	"fmt"
	"path"
	"runtime"
	"slices"
	"strconv"
	"strings"
)

// containerNginxConfs are where the main file of nginx lies in an image, when its command names none
// (-c): the official image and the Debian, Alpine and RHEL packages, then nginx built from source.
var containerNginxConfs = []string{"/etc/nginx/nginx.conf", "/usr/local/nginx/conf/nginx.conf"}

// listContainers returns the running containers docker knows; tests stand in their own.
var listContainers = runningContainers

// ContainerVhosts lists the names the web servers in the running Docker containers of this host serve
// on a published port, by the host port: nginx and Apache from their configuration, read from the container's
// archive (containerFS), never by running anything in it (Kevin 2026-11-17). A container without a
// published TCP port, or whose command names no web server, adds none; the application of a document
// root is not looked for (it lies in another container more often than not). A container whose
// configuration cannot be read gives an error with the names of the others.
func ContainerVhosts(ctx context.Context) ([]Vhost, error) {
	list, err := listContainers(ctx)
	if err != nil {
		return nil, err
	}
	var vhosts []Vhost
	var errs []error
	for _, c := range list {
		ports := containerPorts(c)
		if len(ports) == 0 {
			continue
		}
		var found []Vhost
		var err error
		switch containerWebServer(c) {
		case "nginx":
			found, err = containerNginxVhosts(ctx, newContainerFS(c.ID), nginxConfArg(c))
		case "apache":
			found, err = containerApacheVhosts(ctx, newContainerFS(c.ID))
		default:
			continue
		}
		if err != nil {
			errs = append(errs, fmt.Errorf("container %.12s: %w", c.ID, err))
		}
		for _, v := range found {
			for _, hostPort := range ports[v.Port] {
				vhosts = append(vhosts, Vhost{Server: v.Server, Name: v.Name, Port: hostPort, TLS: v.TLS,
					cert: v.cert, container: c.ID})
			}
		}
	}
	return vhosts, errors.Join(errs...)
}

// runningContainers are the running containers (docker ps, docker inspect); a host without a docker
// daemon serving its socket has none. Only docker on Linux.
func runningContainers(ctx context.Context) ([]containerInfo, error) {
	if runtime.GOOS != "linux" {
		return nil, nil
	}
	ids, err := dockerContainers(ctx)
	if err != nil {
		if !dockerServes(ctx) {
			return nil, nil
		}
		return nil, err
	}
	if len(ids) == 0 {
		return nil, nil
	}
	list, err := inspectContainers(ctx, ids)
	if err != nil {
		return nil, err
	}
	return slices.DeleteFunc(list, func(c containerInfo) bool { return !c.State.Running }), nil
}

// containerPorts maps each TCP port of the container docker publishes to its host ports, each once
// (docker publishes a port on 0.0.0.0 and on :: with the same host port).
func containerPorts(c containerInfo) map[uint16][]uint16 {
	ports := map[uint16][]uint16{}
	for key, binds := range c.NetworkSettings.Ports {
		num, proto, _ := strings.Cut(key, "/")
		to, err := strconv.ParseUint(num, 10, 16)
		if proto != "tcp" || err != nil {
			continue
		}
		for _, b := range binds {
			hostPort, err := strconv.ParseUint(b.HostPort, 10, 16)
			if err == nil && hostPort != 0 && !slices.Contains(ports[uint16(to)], uint16(hostPort)) {
				ports[uint16(to)] = append(ports[uint16(to)], uint16(hostPort))
			}
		}
	}
	for to, hp := range ports {
		slices.Sort(hp)
		ports[to] = hp
	}
	return ports
}

// containerWebServer is the web server the command of a container runs ("nginx", "apache", "" for none
// known): the program or an argument of it by its name, as an entrypoint script passes it on
// (/docker-entrypoint.sh nginx -g "daemon off;", docker-php-entrypoint apache2-foreground).
func containerWebServer(c containerInfo) string {
	for _, w := range append([]string{c.Path}, c.Args...) {
		switch path.Base(w) {
		case "nginx":
			return "nginx"
		case "httpd", "httpd-foreground", "apache2", "apache2-foreground", "apache2ctl", "apachectl":
			return "apache"
		}
	}
	return ""
}

// nginxConfArg is the main file the command of a container names with -c, "" for none.
func nginxConfArg(c containerInfo) string {
	if i := slices.Index(c.Args, "-c"); i >= 0 && i+1 < len(c.Args) {
		return c.Args[i+1]
	}
	return ""
}

// containerNginxVhosts reads the vhosts of the nginx in a container: its main file (conf, or the first
// of containerNginxConfs there is) and the files it includes, joined into a dump of the form of
// nginx -T for nginxVhosts. The names, the ports, TLS and the certificate file (a path in the container,
// read through its archive, webVhostCert) stay; the root and the user are left. A container without a
// main file at a known path has no nginx the agent reads.
func containerNginxVhosts(ctx context.Context, fs *containerFS, conf string) ([]Vhost, error) {
	confs := containerNginxConfs
	if conf != "" {
		confs = []string{conf}
	}
	var main []byte
	for _, conf = range confs {
		var err error
		main, err = fs.file(ctx, conf, maxApacheFileBytes)
		if err == nil {
			break
		}
		if !errors.Is(err, errNotInContainer) {
			return nil, err
		}
	}
	if main == nil {
		return nil, nil
	}
	dump, err := containerNginxDump(ctx, fs, conf, main)
	if err != nil {
		return nil, err
	}
	var vhosts []Vhost
	for _, v := range nginxVhosts(dump) {
		vhosts = append(vhosts, Vhost{Server: v.Server, Name: v.Name, Port: v.Port, TLS: v.TLS, cert: v.cert})
	}
	return vhosts, nil
}

// containerNginxDump is the dump nginx -T would print of main and the files it includes, each file once
// in the order nginx reads it (the file that includes another before it), at most maxApacheFiles. An
// include that names no file is left out, as is one of a file that looks like a key.
func containerNginxDump(ctx context.Context, fs *containerFS, conf string, main []byte) ([]byte, error) {
	prefix := path.Dir(conf)
	var dump bytes.Buffer
	seen := map[string]bool{conf: true}
	queue := []containerFile{{name: conf, text: main}}
	for len(queue) > 0 {
		f := queue[0]
		queue = queue[1:]
		dump.WriteString("# configuration file " + f.name + ":\n")
		dump.Write(nginxDumpText(f.text))
		dump.WriteString("\n")
		for _, pattern := range nginxIncludes(f.text) {
			if !path.IsAbs(pattern) {
				pattern = path.Join(prefix, pattern)
			}
			var files []containerFile
			if strings.ContainsAny(pattern, `*?[`) {
				var err error
				if files, err = fs.glob(ctx, pattern, maxApacheFileBytes); err != nil {
					return nil, err
				}
			} else if !keyPath(pattern) {
				text, err := fs.fileOf(ctx, pattern, maxApacheFileBytes, keyPath)
				switch {
				case err == nil:
					files = []containerFile{{name: pattern, text: text}}
				case !errors.Is(err, errNotInContainer) && !errors.Is(err, errContainerNoFile):
					return nil, err
				}
			}
			for _, inc := range files {
				if seen[inc.name] {
					continue
				}
				if len(seen) >= maxApacheFiles {
					return nil, errContainerConfLarge
				}
				seen[inc.name] = true
				queue = append(queue, inc)
			}
		}
	}
	return dump.Bytes(), nil
}

// nginxIncludes are the patterns of the include directives of text, in their order, in any block.
func nginxIncludes(text []byte) []string {
	var out, words []string
	for _, tok := range nginxTokens(text) {
		switch tok {
		case "{", "}":
			words = nil
		case ";":
			if len(words) == 2 && words[0] == "include" {
				out = append(out, words[1])
			}
			words = nil
		default:
			words = append(words, tok)
		}
	}
	return out
}

// nginxDumpText is a file's text as it goes into the dump: a line of it that would read as the header
// of another file (a comment "# configuration file …") is kept as a comment of another form.
func nginxDumpText(text []byte) []byte {
	var out []byte
	for line := range bytes.Lines(text) {
		if bytes.HasPrefix(line, []byte("# configuration file ")) {
			out = append(out, '#')
		}
		out = append(out, line...)
	}
	return out
}
