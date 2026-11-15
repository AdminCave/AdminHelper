// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package probe

// The tests of Apache that write its configuration files: -S names them by an absolute Unix path,
// and the discovery reads vhosts on Linux only.

import (
	"context"
	"os"
	"os/exec"
	"reflect"
	"strings"
	"testing"
)

// apacheConfText is the configuration apacheS was the output of (httpd 2.4.68, Docker image httpd:2.4,
// the file included from httpd.conf as conf/extra/v.conf).
const apacheConfText = `Listen 443
Listen 8080
LoadModule ssl_module modules/mod_ssl.so
<VirtualHost *:80>
    ServerName www.example.org
    ServerAlias example.org alt.example.org
    DocumentRoot /usr/local/apache2/htdocs
</VirtualHost>
<VirtualHost *:80>
    ServerName second.example.org
    DocumentRoot "/srv/second"
</VirtualHost>
<VirtualHost *:443>
    ServerName secure.example.org
    SSLEngine on
    SSLCertificateFile /usr/local/apache2/conf/server.crt
    SSLCertificateKeyFile /usr/local/apache2/conf/server.key
    DocumentRoot /srv/secure
</VirtualHost>
<VirtualHost 127.0.0.1:8080 [::1]:8080>
    ServerName local.example.org
</VirtualHost>
<VirtualHost *:443>
    ServerName other.example.org
    ServerAlias *.wild.example.org
    SSLEngine on
    SSLCertificateFile /usr/local/apache2/conf/server.crt
    SSLCertificateKeyFile /usr/local/apache2/conf/server.key
</VirtualHost>
<VirtualHost *:443>
    ServerName third.example.org
    SSLEngine on
    SSLCertificateFile /usr/local/apache2/conf/server.crt
    SSLCertificateKeyFile /usr/local/apache2/conf/server.key
</VirtualHost>
`

// apacheS is the standard output of httpd -S for apacheConfText (httpd 2.4.68), CONF where it named the
// file.
const apacheS = `VirtualHost configuration:
[::1]:8080             local.example.org (CONF:20)
127.0.0.1:8080         local.example.org (CONF:20)
*:80                   is a NameVirtualHost
         default server www.example.org (CONF:4)
         port 80 namevhost www.example.org (CONF:4)
                 alias example.org
                 alias alt.example.org
         port 80 namevhost second.example.org (CONF:9)
*:443                  is a NameVirtualHost
         default server secure.example.org (CONF:13)
         port 443 namevhost secure.example.org (CONF:13)
         port 443 namevhost other.example.org (CONF:23)
                 wild alias *.wild.example.org
         port 443 namevhost third.example.org (CONF:30)
ServerRoot: "/usr/local/apache2"
Main DocumentRoot: "/usr/local/apache2/htdocs"
Main ErrorLog: "/proc/self/fd/2"
Mutex ssl-stapling-refresh: using_defaults
Mutex ssl-stapling: using_defaults
Mutex ssl-cache: using_defaults
Mutex default: dir="/usr/local/apache2/logs/" mechanism=default 
PidFile: "/usr/local/apache2/logs/httpd.pid"
Define: DUMP_VHOSTS
Define: DUMP_RUN_CFG
User: name="www-data" id=33
Group: name="www-data" id=33
`

// writeApacheConf writes text as a file of Apache's configuration and returns the output of -S with
// out's CONF set to it.
func writeApacheConf(t *testing.T, text, out string) string {
	t.Helper()
	conf := t.TempDir() + "/v.conf"
	if err := os.WriteFile(conf, []byte(text), 0o600); err != nil {
		t.Fatal(err)
	}
	return strings.ReplaceAll(out, "CONF", conf)
}

func TestTheVhostsOfApacheAreReadFromItsListAndTheirBlocks(t *testing.T) {
	out := writeApacheConf(t, apacheConfText, apacheS)
	stubVhostRoots(t, "/srv/secure/wp-login.php", "/srv/secure/wp-includes/version.php")
	calls := stubTools(t, answer{err: exec.ErrNotFound}, answer{err: exec.ErrNotFound}, answer{out: out})

	got, err := WebVhosts(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	cert := "/usr/local/apache2/conf/server.crt"
	want := []Vhost{
		{Server: "apache", Name: "local.example.org", Port: 8080},
		{Server: "apache", Name: "www.example.org", Port: 80, root: "/usr/local/apache2/htdocs"},
		{Server: "apache", Name: "example.org", Port: 80, root: "/usr/local/apache2/htdocs"},
		{Server: "apache", Name: "alt.example.org", Port: 80, root: "/usr/local/apache2/htdocs"},
		{Server: "apache", Name: "second.example.org", Port: 80, root: "/srv/second"},
		{Server: "apache", Name: "secure.example.org", Port: 443, TLS: true, App: "wordpress", root: "/srv/secure", cert: cert},
		{Server: "apache", Name: "other.example.org", Port: 443, TLS: true, cert: cert},
		{Server: "apache", Name: "third.example.org", Port: 443, TLS: true, cert: cert},
	}
	if !reflect.DeepEqual(got, want) {
		t.Errorf("vhosts =\n%+v\nwant\n%+v", got, want)
	}
	if last := (*calls)[2]; !reflect.DeepEqual(last, []string{"apachectl", "-S"}) {
		t.Errorf("Apache asked by %q, want apachectl -S after apache2ctl", last)
	}
}

func TestABlockOfApacheGivesTheAliasesOfAVhostAloneAtItsAddress(t *testing.T) {
	conf := "<VirtualHost *:443>\n  ServerName a.example.org\n  ServerAlias \\\n    b.example.org\n" +
		"  <IfModule ssl_module>\n    SSLEngine On\n  </IfModule>\n</VirtualHost>\n"
	out := writeApacheConf(t, conf, "*:443                  a.example.org (CONF:1)\n"+
		"*:*                    is a NameVirtualHost\n"+
		"         port * namevhost c.example.org (CONF:1)\n")
	stubVhostRoots(t)
	got, err := apacheVhosts([]byte(out))
	if err != nil {
		t.Fatal(err)
	}
	want := []Vhost{
		{Server: "apache", Name: "a.example.org", Port: 443, TLS: true},
		{Server: "apache", Name: "b.example.org", Port: 443, TLS: true},
	}
	if !reflect.DeepEqual(got, want) {
		t.Errorf("vhosts = %+v, want %+v", got, want)
	}
}

func TestAVhostOfApacheWhoseBlockIsGoneOrUnreadableStaysWithoutTLS(t *testing.T) {
	stubVhostRoots(t)
	moved := writeApacheConf(t, "# a comment now\n<VirtualHost *:443>\nSSLEngine on\n</VirtualHost>\n",
		"*:443                  a.example.org (CONF:1)\n")
	got, err := apacheVhosts([]byte(moved))
	if want := []Vhost{{Server: "apache", Name: "a.example.org", Port: 443}}; err != nil || !reflect.DeepEqual(got, want) {
		t.Errorf("moved block: %+v, %v; want %+v", got, err, want)
	}
	got, err = apacheVhosts([]byte("*:443                  a.example.org (/nonexistent/v.conf:1)\n"))
	if want := []Vhost{{Server: "apache", Name: "a.example.org", Port: 443}}; !reflect.DeepEqual(got, want) ||
		err == nil || strings.Contains(err.Error(), "nonexistent") {
		t.Errorf("unreadable file: %+v, %v; want %+v and an error without the path", got, err, want)
	}
}

func TestTheAliasesOfANameVhostComeFromTheListOfApache(t *testing.T) {
	stubVhostRoots(t)
	out := writeApacheConf(t, "<VirtualHost *:80>\n  ServerName ${SITE}\n  ServerAlias ${ALIAS}\n</VirtualHost>\n",
		"*:80                   is a NameVirtualHost\n"+
			"         port 80 namevhost a.example.org (CONF:1)\n"+
			"                 alias b.example.org\n")
	got, err := apacheVhosts([]byte(out))
	want := []Vhost{{Server: "apache", Name: "a.example.org", Port: 80}, {Server: "apache", Name: "b.example.org", Port: 80}}
	if err != nil || !reflect.DeepEqual(got, want) {
		t.Errorf("vhosts = %+v, %v; want %+v", got, err, want)
	}
}

func TestTheBlockOfApacheReadsTheFilesItIncludes(t *testing.T) {
	stubVhostRoots(t)
	dir := t.TempDir()
	if err := os.WriteFile(dir+"/options-ssl-apache.conf", []byte("SSLEngine on\nSSLProtocol all -SSLv2\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(dir+"/alias.conf", []byte("ServerAlias c.example.org\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	// certbot's -le-ssl.conf: SSLEngine on only in the file it includes.
	conf := "<IfModule mod_ssl.c>\n<VirtualHost *:443>\n  ServerName a.example.org\n" +
		"  SSLCertificateFile /etc/letsencrypt/live/a/fullchain.pem\n" +
		"  Include " + dir + "/options-ssl-apache.conf\n</VirtualHost>\n" +
		"<VirtualHost *:443>\n  ServerName b.example.org\n  IncludeOptional alias.conf\n" +
		"  Include *.conf\n</VirtualHost>\n</IfModule>\n"
	out := writeApacheConf(t, conf, "ServerRoot: \""+dir+"\"\n"+
		"*:443                  is a NameVirtualHost\n"+
		"         port 443 namevhost a.example.org (CONF:2)\n"+
		"         port 443 namevhost b.example.org (CONF:7)\n")
	got, err := apacheVhosts([]byte(out))
	want := []Vhost{
		{Server: "apache", Name: "a.example.org", Port: 443, TLS: true, cert: "/etc/letsencrypt/live/a/fullchain.pem"},
		{Server: "apache", Name: "b.example.org", Port: 443},
		{Server: "apache", Name: "c.example.org", Port: 443},
	}
	if err != nil || !reflect.DeepEqual(got, want) {
		t.Errorf("vhosts = %+v, %v; want %+v", got, err, want)
	}
}

func TestAVhostOfApacheWithoutAServerNameIsNotReportedUnderTheInheritedOne(t *testing.T) {
	stubVhostRoots(t)
	conf := "<VirtualHost *:80>\n  DocumentRoot /var/www/html\n</VirtualHost>\n" +
		"<VirtualHost *:8080>\n  ServerAlias own.example.org\n</VirtualHost>\n"
	out := writeApacheConf(t, conf, "*:80                   box.example.net (CONF:1)\n"+
		"*:8080                 box.example.net (CONF:4)\n")
	got, err := apacheVhosts([]byte(out))
	want := []Vhost{{Server: "apache", Name: "own.example.org", Port: 8080}}
	if err != nil || !reflect.DeepEqual(got, want) {
		t.Errorf("vhosts = %+v, %v; want %+v", got, err, want)
	}
}
