// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package probe

import (
	"bytes"
	"context"
	"errors"
	"fmt"
	"net"
	"net/netip"
	"os"
	"os/exec"
	"path"
	"regexp"
	"slices"
	"strconv"
	"strings"
)

// Vhost is a name a web server of this host serves: the server (nginx), the name, the port and
// whether it speaks TLS there, and the application its document root holds ("" for none known).
// Only these go into the discovery; where the root and the certificate lie stays on the host, a view
// finds them again when it runs.
type Vhost struct {
	Server string
	Name   string
	Port   uint16
	TLS    bool
	App    string
	root   string
	cert   string
}

// maxVhostName is the longest name a vhost is reported by, the longest instance key of the monitoring
// service.
const maxVhostName = 120

// vhostStat looks at a path of a document root; tests stand in their own.
var vhostStat = os.Stat

// vhostPattern is a DNS name a vhost is reported by: lowercase labels of letters, digits and hyphens.
var vhostPattern = regexp.MustCompile(`^([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)*[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$`)

// vhostName is name as a vhost is reported, "" for one that names no single host: a wildcard, a
// regular expression, the catch-all "_", localhost or an address.
func vhostName(name string) string {
	name = strings.TrimSuffix(strings.ToLower(name), ".")
	if len(name) > maxVhostName || name == "localhost" || !vhostPattern.MatchString(name) {
		return ""
	}
	if _, err := netip.ParseAddr(name); err == nil {
		return ""
	}
	return name
}

// WebVhosts lists the names the web servers of this host serve, a name once: nginx from the dump of
// nginx -T. A web server that is not installed adds none; one whose configuration cannot be read
// gives an error with the names of the others, so the caller knows the list is not whole.
func WebVhosts(ctx context.Context) ([]Vhost, error) {
	var vhosts []Vhost
	var errs []error
	out, err := runTool(ctx, toolTimeout, "nginx", "-T")
	var exitErr *exec.ExitError
	switch {
	case errors.Is(err, exec.ErrNotFound):
	case errors.As(err, &exitErr):
		errs = append(errs, errors.New("nginx -T fails: the configuration does not load"))
	case err != nil:
		errs = append(errs, fmt.Errorf("nginx: %w", err))
	default:
		vhosts = append(vhosts, nginxVhosts(out)...)
	}
	return uniqueVhosts(vhosts), errors.Join(errs...)
}

// uniqueVhosts keeps each name once, in the order given: the first web server that serves it, and
// there the TLS port before a plain one, the lower port before the higher.
func uniqueVhosts(vhosts []Vhost) []Vhost {
	var out []Vhost
	at := map[string]int{}
	for _, v := range vhosts {
		i, seen := at[v.Name]
		switch {
		case !seen:
			at[v.Name] = len(out)
			out = append(out, v)
		case out[i].Server != v.Server:
		case v.TLS && !out[i].TLS, v.TLS == out[i].TLS && v.Port < out[i].Port:
			out[i] = v
		}
	}
	return out
}

// nginxVhost is what nginxVhosts keeps of a server block.
type nginxVhost struct {
	listens    []nginxListen
	listened   bool
	sslOn      bool
	names      []string
	root, cert string
}

type nginxListen struct {
	port uint16
	tls  bool
}

// nginxFrame is a block of the nginx configuration: its directive ("http", "server", "location" …)
// and the server block it lies in.
type nginxFrame struct {
	name   string
	server *nginxVhost
}

// nginxInclude is an include directive: its pattern, absolute, and the block that holds it.
type nginxInclude struct {
	pattern string
	in      nginxFrame
}

// nginxDumpFiles splits the dump of nginx -T into its files, each with its path, the main file
// first; what precedes the first file (the result of the test) is dropped.
func nginxDumpFiles(dump []byte) (names []string, texts [][]byte) {
	parts := splitNginxDump(dump)
	for line := range bytes.Lines(dump) {
		if name, ok := bytes.CutPrefix(line, []byte("# configuration file ")); ok {
			names = append(names, strings.TrimSuffix(strings.TrimSpace(string(name)), ":"))
		}
	}
	return names, parts[1:]
}

// nginxVhosts reads the server blocks of the http block from the dump of nginx -T: a server's listen
// directives (a port, "ssl" for TLS; "quic" listens on UDP and is left out), its server_name, its
// root and its ssl_certificate, else the ssl_certificate of the http block.
//
// nginx -T dumps each file once, as it first reads it, so the include that names a file comes before
// it: a file is read inside the block that includes it, a snippet inside its server, a site inside
// http. A file no include is known for is read as if http held it, without its http directives.
// Relative include paths are relative to the directory of the main file (the prefix of a packaged
// nginx).
//
// Directives: nginx.org/en/docs/http/ngx_http_core_module.html (listen, server_name, root),
// ngx_http_ssl_module.html (ssl_certificate; "ssl on" is gone since 1.25.1, still read here) and
// ngx_core_module.html#include.
func nginxVhosts(dump []byte) []Vhost {
	var servers []*nginxVhost
	var includes []nginxInclude
	httpCert := ""
	names, texts := nginxDumpFiles(dump)
	prefix := ""
	if len(names) > 0 {
		prefix = path.Dir(names[0])
	}
	for i, file := range texts {
		bases := []nginxFrame{{}}
		if i > 0 {
			bases = nil
			for _, inc := range includes {
				if ok, _ := path.Match(inc.pattern, names[i]); ok && !slices.Contains(bases, inc.in) {
					bases = append(bases, inc.in)
				}
			}
			if len(bases) == 0 {
				bases = []nginxFrame{{name: "?"}} // included, but by no include read
			}
		}
		for _, base := range bases {
			servers, includes, httpCert = nginxRead(file, base, prefix, servers, includes, httpCert)
		}
	}
	return nginxVhostsOf(servers, httpCert)
}

// nginxRead reads one file of the dump inside the block base and adds what it finds.
func nginxRead(file []byte, base nginxFrame, prefix string, servers []*nginxVhost, includes []nginxInclude,
	httpCert string) ([]*nginxVhost, []nginxInclude, string) {
	stack := []nginxFrame{base}
	var words []string
	for _, tok := range nginxTokens(file) {
		top := stack[len(stack)-1]
		switch tok {
		case "{":
			f := nginxFrame{server: top.server}
			if len(words) > 0 {
				f.name = words[0]
			}
			if f.name == "server" && (top.name == "http" || top.name == "?") {
				f.server = &nginxVhost{}
				servers = append(servers, f.server)
			}
			stack = append(stack, f)
			words = nil
		case "}":
			if len(stack) > 1 {
				stack = stack[:len(stack)-1]
			}
			words = nil
		case ";":
			switch {
			case len(words) < 2:
			case words[0] == "include":
				pattern := words[1]
				if !path.IsAbs(pattern) {
					pattern = path.Join(prefix, pattern)
				}
				includes = append(includes, nginxInclude{pattern: pattern, in: top})
			case top.name == "http" && words[0] == "ssl_certificate":
				if httpCert == "" {
					httpCert = words[1]
				}
			case top.name != "server" || top.server == nil:
			case words[0] == "listen":
				top.server.listened = true
				if l, ok := nginxListenOf(words[1:]); ok {
					top.server.listens = append(top.server.listens, l)
				}
			case words[0] == "ssl" && words[1] == "on":
				top.server.sslOn = true
			case words[0] == "server_name":
				top.server.names = append(top.server.names, words[1:]...)
			case words[0] == "root":
				top.server.root = words[1]
			case words[0] == "ssl_certificate" && top.server.cert == "":
				top.server.cert = words[1] // the first of several (RSA beside ECDSA)
			}
			words = nil
		default:
			words = append(words, tok)
		}
	}
	return servers, includes, httpCert
}

// nginxVhostsOf are the vhosts of the server blocks read, each name at each port of its server.
func nginxVhostsOf(servers []*nginxVhost, httpCert string) []Vhost {
	var vhosts []Vhost
	for _, s := range servers {
		listens := s.listens
		if !s.listened {
			listens = []nginxListen{{port: 80}} // nginx's default listen (as root)
		}
		cert := s.cert
		if cert == "" {
			cert = httpCert
		}
		app := webApp(s.root)
		for _, n := range s.names {
			name := vhostName(n)
			if name == "" {
				continue
			}
			for _, l := range listens {
				v := Vhost{Server: "nginx", Name: name, Port: l.port, TLS: l.tls || s.sslOn, App: app, root: s.root}
				if v.TLS {
					v.cert = cert
				}
				vhosts = append(vhosts, v)
			}
		}
	}
	return vhosts
}

// nginxListenOf reads the arguments of a listen directive: an address and port, a port or an
// address ("127.0.0.1:8443", "[::]:443", "443", "localhost"), then its parameters. A Unix socket and
// a QUIC listen are none.
func nginxListenOf(args []string) (nginxListen, bool) {
	addr, params := args[0], args[1:]
	if strings.HasPrefix(addr, "unix:") || slices.Contains(params, "quic") {
		return nginxListen{}, false
	}
	portText := "80"
	if _, err := strconv.Atoi(addr); err == nil {
		portText = addr
	} else if _, p, err := net.SplitHostPort(addr); err == nil {
		portText = p
	}
	port, err := strconv.ParseUint(portText, 10, 16)
	if err != nil || port == 0 {
		return nginxListen{}, false
	}
	return nginxListen{port: uint16(port), tls: slices.Contains(params, "ssl")}, true
}

// webApps are the applications a document root is known by, each by files only it has: Nextcloud
// (occ and status.php), Moodle (admin/cli/checks.php and lib/moodlelib.php), WordPress (wp-login.php
// and wp-includes/version.php) and BookStack, whose root is its public directory (the model of a
// bookshelf beside it).
var webApps = []struct {
	name  string
	files []string
}{
	{"nextcloud", []string{"occ", "status.php"}},
	{"moodle", []string{"admin/cli/checks.php", "lib/moodlelib.php"}},
	{"wordpress", []string{"wp-login.php", "wp-includes/version.php"}},
	{"bookstack", []string{"../artisan", "../app/Entities/Models/Bookshelf.php"}},
}

// webApp is the application the document root holds, "" for none known or a root that is no plain
// absolute path (one with a variable of nginx).
func webApp(root string) string {
	if !safePath.MatchString(root) {
		return ""
	}
	for _, a := range webApps {
		if slices.IndexFunc(a.files, func(f string) bool {
			_, err := vhostStat(path.Join(root, f))
			return err != nil
		}) < 0 {
			return a.name
		}
	}
	return ""
}
