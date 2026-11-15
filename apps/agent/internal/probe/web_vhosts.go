// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package probe

import (
	"bytes"
	"context"
	"errors"
	"fmt"
	"io/fs"
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
// nginx -T, Apache from apache2ctl -S (Debian) or apachectl -S (RHEL). A web server that is not
// installed adds none; one whose configuration cannot be read gives an error with the names of the
// others, so the caller knows the list is not whole.
func WebVhosts(ctx context.Context) ([]Vhost, error) {
	var vhosts []Vhost
	var errs []error
	out, err := webServerOut(ctx, "nginx", "-T")
	switch {
	case errors.Is(err, exec.ErrNotFound):
	case err != nil:
		errs = append(errs, err)
	default:
		vhosts = append(vhosts, nginxVhosts(out)...)
	}
	out, err = webServerOut(ctx, "apache2ctl", "-S")
	if errors.Is(err, exec.ErrNotFound) {
		out, err = webServerOut(ctx, "apachectl", "-S")
	}
	switch {
	case errors.Is(err, exec.ErrNotFound):
	case err != nil:
		errs = append(errs, err)
	default:
		v, err := apacheVhosts(out)
		vhosts = append(vhosts, v...)
		if err != nil {
			errs = append(errs, err)
		}
	}
	return uniqueVhosts(vhosts), errors.Join(errs...)
}

// webServerOut runs the dump of a web server's configuration; exec.ErrNotFound for one not installed.
func webServerOut(ctx context.Context, name, flag string) ([]byte, error) {
	out, err := runTool(ctx, toolTimeout, name, flag)
	var exitErr *exec.ExitError
	switch {
	case errors.Is(err, exec.ErrNotFound):
		return nil, err
	case errors.As(err, &exitErr):
		return nil, fmt.Errorf("%s %s fails: the configuration does not load", name, flag)
	case err != nil:
		return nil, fmt.Errorf("%s: %w", name, err)
	}
	return out, nil
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

// The lines of apachectl -S (-t -D DUMP_VHOSTS -D DUMP_RUN_CFG) that name a virtual host, checked
// against httpd 2.4.68 (the form is not documented; it is dump_a_vhost of server/vhost.c): an address
// with one virtual host ("*:443                  secure.example.org (/etc/apache2/sites-enabled/a.conf:1)"),
// or below "*:80 is a NameVirtualHost" each of its virtual hosts ("port 80 namevhost www.example.org
// (…:4)") with its aliases ("alias example.org"). "default server" repeats a namevhost, "wild alias"
// is a wildcard; both are left out. "port *" (<VirtualHost *>) names no port and is left out too.
// ServerRoot is the directory relative Include paths are taken from.
var (
	apacheOneVhost   = regexp.MustCompile(`^\S+:([0-9]+)\s+(\S+) \((/.+):([0-9]+)\)$`)
	apacheNameVhost  = regexp.MustCompile(`^\s+port ([0-9]+) namevhost (\S+) \((/.+):([0-9]+)\)$`)
	apacheAlias      = regexp.MustCompile(`^\s+alias (\S+)$`)
	apacheServerRoot = regexp.MustCompile(`^ServerRoot: "(/.*)"$`)
)

// apacheVhost is a virtual host of apachectl -S: its names, its port and where it is defined.
type apacheVhost struct {
	names []string
	port  uint16
	file  string
	line  int
}

// apacheDirective is a directive of an Apache configuration file, its words and the line it starts at.
type apacheDirective struct {
	line int
	f    []string
}

// apacheConf reads the files of Apache's configuration for apacheVhosts, each at most once and no
// more than maxApacheFiles of them.
type apacheConf struct {
	root     string
	included map[string][]apacheDirective
	files    int
	unread   bool
	tooMany  bool
}

// read reads a file's directives; nil for one that cannot be read or is past the cap.
func (c *apacheConf) read(name string) []apacheDirective {
	if c.files == maxApacheFiles {
		c.tooMany = true
		return nil
	}
	c.files++
	text, err := readCapped(name, maxApacheFileBytes)
	if err != nil {
		c.unread = true
		return nil
	}
	return apacheDirectives(text)
}

// apacheVhosts reads the virtual hosts from the output of apachectl -S, and from the <VirtualHost>
// each is defined at what -S does not tell: SSLEngine on for TLS, the first SSLCertificateFile, the
// DocumentRoot and the ServerAlias (-S lists the aliases only of a name-based virtual host). A
// virtual host without a ServerName of its own is listed by -S under the name it inherits (the main
// server's, else the host name) and is left out under it. A file that cannot be read gives an error,
// its virtual hosts stay without TLS; past maxApacheFiles files the rest are left out, with an error.
func apacheVhosts(out []byte) ([]Vhost, error) {
	var list []*apacheVhost
	var last *apacheVhost
	conf := &apacheConf{included: map[string][]apacheDirective{}}
	for raw := range strings.Lines(string(out)) {
		line := strings.TrimRight(raw, "\r\n")
		if m := apacheServerRoot.FindStringSubmatch(line); m != nil {
			conf.root = m[1]
			continue
		}
		m := apacheOneVhost.FindStringSubmatch(line)
		if m == nil {
			m = apacheNameVhost.FindStringSubmatch(line)
		}
		if m != nil {
			last = nil
			port, err := strconv.ParseUint(m[1], 10, 16)
			n, lerr := strconv.Atoi(m[4])
			if err == nil && port > 0 && lerr == nil && safePath.MatchString(m[3]) {
				last = &apacheVhost{names: []string{m[2]}, port: uint16(port), file: m[3], line: n}
				list = append(list, last)
			}
			continue
		}
		if a := apacheAlias.FindStringSubmatch(line); a != nil && last != nil {
			last.names = append(last.names, a[1])
		}
	}
	// Each file is read once and dropped before the next, its virtual hosts found by their line.
	var files []string
	byFile := map[string][]int{}
	for k, a := range list {
		if _, seen := byFile[a.file]; !seen {
			files = append(files, a.file)
		}
		byFile[a.file] = append(byFile[a.file], k)
	}
	found := make([][]Vhost, len(list))
	for _, file := range files {
		dirs := conf.read(file)
		if conf.tooMany {
			break
		}
		at := map[int]int{}
		for j, d := range dirs {
			at[d.line] = j
		}
		for _, k := range byFile[file] {
			j, ok := at[list[k].line]
			if !ok {
				j = -1 // unread, or the file changed since apachectl -S read it
			}
			found[k] = apacheVhostsOf(list[k], conf.block(dirs, j))
		}
	}
	vhosts := slices.Concat(found...)
	switch {
	case conf.tooMany:
		return vhosts, fmt.Errorf("the configuration of Apache has more than %d files", maxApacheFiles)
	case conf.unread:
		return vhosts, errors.New("a file of the configuration of Apache cannot be read")
	}
	return vhosts, nil
}

// apacheVhostsOf are the vhosts of a virtual host of -S with what its block tells.
func apacheVhostsOf(a *apacheVhost, b apacheVhostBlock) []Vhost {
	names := a.names
	if b.found && !b.named {
		names = names[1:]
	}
	app := webApp(b.root)
	var vhosts []Vhost
	for _, n := range append(slices.Clone(names), b.aliases...) {
		name := vhostName(n)
		if name == "" {
			continue
		}
		v := Vhost{Server: "apache", Name: name, Port: a.port, TLS: b.tls, App: app, root: b.root}
		if v.TLS {
			v.cert = b.cert
		}
		vhosts = append(vhosts, v)
	}
	return vhosts
}

// apacheVhostBlock is what block keeps of a <VirtualHost>.
type apacheVhostBlock struct {
	found, named, tls bool
	root, cert        string
	aliases           []string
}

// block reads the <VirtualHost> that starts at directive i (nothing for none there), and the files it
// includes by a plain path (Include, IncludeOptional; relative to ServerRoot), one level deep: certbot's
// <VirtualHost> includes SSLEngine on from /etc/letsencrypt/options-ssl-apache.conf.
func (c *apacheConf) block(dirs []apacheDirective, i int) apacheVhostBlock {
	var b apacheVhostBlock
	if i < 0 || i >= len(dirs) || strings.ToLower(dirs[i].f[0]) != "<virtualhost" {
		return b
	}
	b.found = true
	for _, d := range dirs[i+1:] {
		key := strings.ToLower(d.f[0])
		if key == "</virtualhost>" {
			break
		}
		if (key == "include" || key == "includeoptional") && len(d.f) == 2 {
			for _, inc := range c.include(strings.Trim(d.f[1], `"`)) {
				b.set(inc.f)
			}
			continue
		}
		b.set(d.f)
	}
	return b
}

// include is the directives of an included file, read once per run; none for a pattern or a path
// that is no plain absolute one after ServerRoot. A file that is not there (IncludeOptional) and a
// directory, whose files Apache reads, add none without counting as unread: the configuration loaded.
func (c *apacheConf) include(name string) []apacheDirective {
	if !path.IsAbs(name) && c.root != "" {
		name = path.Join(c.root, name)
	}
	if !safePath.MatchString(name) {
		return nil
	}
	dirs, ok := c.included[name]
	if !ok {
		if fi, err := os.Stat(name); errors.Is(err, fs.ErrNotExist) || (err == nil && fi.IsDir()) {
			c.included[name] = nil
			return nil
		}
		dirs = c.read(name)
		c.included[name] = dirs
	}
	return dirs
}

// set takes a directive of a <VirtualHost> into the block.
func (b *apacheVhostBlock) set(f []string) {
	if len(f) < 2 {
		return
	}
	switch strings.ToLower(f[0]) {
	case "sslengine":
		b.tls = strings.EqualFold(f[1], "on")
	case "sslcertificatefile":
		if b.cert == "" {
			b.cert = strings.Trim(f[1], `"`) // the first of several (RSA beside ECDSA)
		}
	case "documentroot":
		b.root = strings.Trim(f[1], `"`)
	case "servername":
		b.named = true
	case "serveralias":
		b.aliases = append(b.aliases, f[1:]...)
	}
}

// apacheDirectives returns the directives of an Apache configuration file as apacheLines does
// (continuations joined, comments and empty lines dropped), each with the line it starts at.
func apacheDirectives(text []byte) []apacheDirective {
	var dirs []apacheDirective
	var cur strings.Builder
	n, start := 0, 0
	for raw := range strings.Lines(string(text)) {
		n++
		line := strings.TrimSpace(raw)
		if cur.Len() == 0 {
			start = n
		}
		if strings.HasSuffix(line, "\\") {
			cur.WriteString(strings.TrimSuffix(line, "\\") + " ")
			continue
		}
		cur.WriteString(line)
		full := strings.TrimSpace(cur.String())
		cur.Reset()
		if full != "" && !strings.HasPrefix(full, "#") {
			dirs = append(dirs, apacheDirective{line: start, f: strings.Fields(full)})
		}
	}
	return dirs
}
