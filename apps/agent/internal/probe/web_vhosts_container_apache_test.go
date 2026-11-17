// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package probe

import (
	"context"
	"errors"
	"reflect"
	"slices"
	"strconv"
	"testing"
)

const apacheCtr = "dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd"

func TestContainerVhostsReadApacheInAContainer(t *testing.T) {
	f := stubContainers(t, []containerInfo{
		webContainer(apacheCtr, "docker-php-entrypoint", []string{"apache2-foreground"},
			map[string][]string{"80/tcp": {"8080"}, "443/tcp": {"8443", "8443"}}),
	}, map[string][]byte{
		"/etc/apache2/apache2.conf": buildTar(t, tarEntry{name: "apache2.conf", body: `# ServerRoot "/etc/apache2"
Include ports.conf
IncludeOptional mods-enabled/*.load
IncludeOptional conf-enabled/*.conf
IncludeOptional sites-enabled/*.conf
`}),
		"/etc/apache2/ports.conf": buildTar(t, tarEntry{name: "ports.conf", body: "Listen 80\nListen 443\n"}),
		"/etc/apache2/sites-enabled": buildTar(t,
			tarEntry{name: "sites-enabled", dir: true},
			tarEntry{name: "sites-enabled/000-default.conf", body: `<VirtualHost *:80>
	ServerName http://shop.example.org:80
	ServerAlias www.example.org \
	    static.example.org
	DocumentRoot /var/www/html
</VirtualHost>
`},
			tarEntry{name: "sites-enabled/default-ssl.conf", link: "../sites-available/default-ssl.conf"},
			tarEntry{name: "sites-enabled/.old.conf", body: "<VirtualHost *:80>\nServerName old.example.org\n</VirtualHost>\n"},
		),
		"/etc/apache2/sites-available/default-ssl.conf": buildTar(t, tarEntry{name: "default-ssl.conf", body: `<VirtualHost _default_:443 [::]:443>
	ServerName shop.example.org
	Include /etc/apache2/tls
	SSLCertificateFile /etc/ssl/certs/shop.pem
	SSLCertificateKeyFile /etc/ssl/private/shop.key
</VirtualHost>
<VirtualHost *:9000>
	ServerName internal.example.org
</VirtualHost>
<VirtualHost *>
	ServerName noport.example.org
</VirtualHost>
<VirtualHost *:80>
	ServerAlias alias-only.example.org
</VirtualHost>
`}),
		"/etc/apache2/tls": buildTar(t,
			tarEntry{name: "tls", dir: true},
			tarEntry{name: "tls/engine.conf", body: "SSLEngine on\n"},
			tarEntry{name: "tls/site.key", body: "-----BEGIN PRIVATE KEY-----"},
		),
	})
	got, err := ContainerVhosts(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	want := []Vhost{
		{Server: "apache", Name: "shop.example.org", Port: 8080},
		{Server: "apache", Name: "www.example.org", Port: 8080},
		{Server: "apache", Name: "static.example.org", Port: 8080},
		{Server: "apache", Name: "shop.example.org", Port: 8443, TLS: true},
		{Server: "apache", Name: "alias-only.example.org", Port: 8080},
	}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("ContainerVhosts =\n%+v\nwant\n%+v", got, want)
	}
	for _, p := range f.asked() {
		if keyPath(p) {
			t.Errorf("asked docker cp for %s, a path that looks like a key", p)
		}
	}
	if !slices.Contains(f.asked(), "/usr/local/apache2/conf/httpd.conf") {
		t.Fatalf("asked %q: the main file of the httpd image comes first", f.asked())
	}
}

func TestContainerApacheTakesServerRootForTheIncludesAfterIt(t *testing.T) {
	stubContainers(t, []containerInfo{
		webContainer(apacheCtr, "httpd-foreground", nil, map[string][]string{"80/tcp": {"80"}}),
	}, map[string][]byte{
		"/usr/local/apache2/conf/httpd.conf": buildTar(t, tarEntry{name: "httpd.conf", body: `ServerRoot "/srv/apache"
Include conf/extra/vhosts.conf
`}),
		"/srv/apache/conf/extra/vhosts.conf": buildTar(t, tarEntry{name: "vhosts.conf",
			body: "<VirtualHost *:80>\nServerName app.example.org\n</VirtualHost>\n"}),
		"/usr/local/apache2/conf/extra/vhosts.conf": buildTar(t, tarEntry{name: "vhosts.conf",
			body: "<VirtualHost *:80>\nServerName wrong.example.org\n</VirtualHost>\n"}),
	})
	got, err := ContainerVhosts(context.Background())
	if want := []Vhost{{Server: "apache", Name: "app.example.org", Port: 80}}; err != nil || !reflect.DeepEqual(got, want) {
		t.Fatalf("ContainerVhosts = %+v, %v, want %+v", got, err, want)
	}
}

func TestContainerApacheReadsAFileOnceAndStopsAtTheCap(t *testing.T) {
	// A file that includes itself is read once: its vhost once, no error.
	stubContainers(t, []containerInfo{
		webContainer(apacheCtr, "/usr/sbin/httpd", []string{"-DFOREGROUND"}, map[string][]string{"80/tcp": {"80"}}),
	}, map[string][]byte{
		"/etc/httpd/conf/httpd.conf": buildTar(t, tarEntry{name: "httpd.conf",
			body: "Include conf/httpd.conf\n<VirtualHost *:80>\nServerName a.example.org\n</VirtualHost>\n"}),
	})
	got, err := ContainerVhosts(context.Background())
	if want := []Vhost{{Server: "apache", Name: "a.example.org", Port: 80}}; err != nil || !reflect.DeepEqual(got, want) {
		t.Fatalf("ContainerVhosts = %+v, %v, want %+v", got, err, want)
	}
	// A chain longer than maxApacheFiles is an error.
	archives := map[string][]byte{
		"/etc/httpd/conf/httpd.conf": buildTar(t, tarEntry{name: "httpd.conf", body: "Include conf.d/f0.conf\n"}),
	}
	for i := range maxApacheFiles + 1 {
		name := "f" + strconv.Itoa(i) + ".conf"
		archives["/etc/httpd/conf.d/"+name] = buildTar(t, tarEntry{name: name, body: "Include conf.d/f" + strconv.Itoa(i+1) + ".conf\n"})
	}
	stubContainers(t, []containerInfo{
		webContainer(apacheCtr, "/usr/sbin/httpd", []string{"-DFOREGROUND"}, map[string][]string{"80/tcp": {"80"}}),
	}, archives)
	if _, err := ContainerVhosts(context.Background()); !errors.Is(err, errContainerConfLarge) {
		t.Fatalf("err = %v, want the cap of files", err)
	}
}

func TestApacheServerName(t *testing.T) {
	for in, want := range map[string]string{
		"a.example.org":             "a.example.org",
		"a.example.org:8443":        "a.example.org",
		"https://a.example.org:443": "a.example.org",
		"http://a.example.org":      "a.example.org",
		"a.example.org:notaport":    "a.example.org:notaport",
	} {
		if got := apacheServerName(in); got != want {
			t.Errorf("apacheServerName(%q) = %q, want %q", in, got, want)
		}
	}
}
