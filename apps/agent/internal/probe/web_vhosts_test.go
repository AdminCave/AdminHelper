// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package probe

import (
	"context"
	"errors"
	"fmt"
	"io/fs"
	"os"
	"os/exec"
	"reflect"
	"strings"
	"testing"
)

// stubVhostRoots stands in a document root that holds exactly files.
func stubVhostRoots(t *testing.T, files ...string) {
	t.Helper()
	old := vhostStat
	vhostStat = func(p string) (os.FileInfo, error) {
		for _, f := range files {
			if f == p {
				return nil, nil
			}
		}
		return nil, fs.ErrNotExist
	}
	t.Cleanup(func() { vhostStat = old })
}

// nginxSitesDump is the dump of nginx -T of a host with a main file and the sites it includes.
const nginxSitesDump = `nginx: the configuration file /etc/nginx/nginx.conf syntax is ok
nginx: configuration file /etc/nginx/nginx.conf test is successful
# configuration file /etc/nginx/nginx.conf:
user www-data;
events {}
http {
    include /etc/nginx/conf.d/*.conf;
    include /etc/nginx/sites-enabled/*;
    upstream php { server unix:/run/php/php-fpm.sock; }
}

# configuration file /etc/nginx/conf.d/ssl.conf:
ssl_certificate /etc/ssl/default.pem;

# configuration file /etc/nginx/sites-enabled/cloud:
server {
    listen 80;
    listen [::]:80;
    server_name cloud.example.org Cloud.Example.org.;
    return 301 https://$host$request_uri;
}
server {
    listen 443 ssl;
    listen [::]:443 ssl;
    listen 443 quic reuseport;
    server_name cloud.example.org;
    root /var/www/nextcloud;
    ssl_certificate /etc/letsencrypt/live/cloud/fullchain.pem;
    ssl_certificate /etc/letsencrypt/live/cloud/ecdsa.pem;
    ssl_certificate_key /etc/letsencrypt/live/cloud/privkey.pem;
    location / { root /elsewhere; }
}

# configuration file /etc/nginx/sites-enabled/rest:
server {
    listen 127.0.0.1:8443 ssl;
    server_name "learn.example.org" *.example.org ~^www\d+\.example\.org$ _ localhost 192.0.2.10 "";
    root /srv/moodle;
}
server {
    server_name blog.example.org;
    root $document_root_by_map;
}
server {
    listen 8080;
    ssl on;
    server_name legacy.example.org;
}
server {
    listen unix:/run/nginx.sock;
    server_name sock.example.org;
}
`

func TestTheVhostsOfNginxAreReadFromItsDump(t *testing.T) {
	stubTools(t, answer{out: nginxSitesDump}, answer{err: exec.ErrNotFound}, answer{err: exec.ErrNotFound})
	stubVhostRoots(t, "/var/www/nextcloud/occ", "/var/www/nextcloud/status.php",
		"/srv/moodle/admin/cli/checks.php", "/srv/moodle/lib/moodlelib.php")

	got, err := WebVhosts(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	want := []Vhost{
		{Server: "nginx", Name: "cloud.example.org", Port: 443, TLS: true, App: "nextcloud",
			root: "/var/www/nextcloud", cert: "/etc/letsencrypt/live/cloud/fullchain.pem"},
		{Server: "nginx", Name: "learn.example.org", Port: 8443, TLS: true, App: "moodle",
			root: "/srv/moodle", cert: "/etc/ssl/default.pem"},
		{Server: "nginx", Name: "blog.example.org", Port: 80, root: "$document_root_by_map"},
		{Server: "nginx", Name: "legacy.example.org", Port: 8080, TLS: true, cert: "/etc/ssl/default.pem"},
	}
	if !reflect.DeepEqual(got, want) {
		t.Errorf("vhosts =\n%+v\nwant\n%+v", got, want)
	}
}

func TestTheApplicationOfARootIsKnownByAllItsFiles(t *testing.T) {
	for _, c := range []struct {
		root  string
		files []string
		want  string
	}{
		{"/var/www/wp", []string{"/var/www/wp/wp-login.php", "/var/www/wp/wp-includes/version.php"}, "wordpress"},
		{"/var/www/bookstack/public", []string{"/var/www/bookstack/artisan", "/var/www/bookstack/app/Entities/Models/Bookshelf.php"}, "bookstack"},
		// one file of two is not enough: a Laravel app has artisan, too.
		{"/var/www/laravel/public", []string{"/var/www/laravel/artisan"}, ""},
		{"/var/www/wp", []string{"/var/www/wp/wp-login.php"}, ""},
		{"relative/root", []string{"relative/root/occ", "relative/root/status.php"}, ""},
		{"", nil, ""},
	} {
		stubVhostRoots(t, c.files...)
		if got := webApp(c.root); got != c.want {
			t.Errorf("webApp(%q) = %q, want %q", c.root, got, c.want)
		}
	}
}

func TestAVhostNameNamesOneHost(t *testing.T) {
	for name, want := range map[string]string{
		"Example.ORG.":                  "example.org",
		"a-b.example.org":               "a-b.example.org",
		"*.example.org":                 "",
		"example.*":                     "",
		"~^www":                         "",
		"_":                             "",
		"localhost":                     "",
		"192.0.2.1":                     "",
		"[2001:db8::1]":                 "",
		"-bad.example.org":              "",
		"bad-.example.org":              "",
		"under_score.example.org":       "",
		strings.Repeat("a.", 127) + "b": "",
		strings.Repeat("a.", 59) + "bc": strings.Repeat("a.", 59) + "bc", // 120 characters
		strings.Repeat("a.", 60) + "b":  "",                              // 121
	} {
		if got := vhostName(name); got != want {
			t.Errorf("vhostName(%q) = %q, want %q", name, got, want)
		}
	}
}

func TestANameIsKeptOnceWithTheTLSPortFirst(t *testing.T) {
	got := uniqueVhosts([]Vhost{
		{Server: "nginx", Name: "a", Port: 80},
		{Server: "nginx", Name: "a", Port: 8443, TLS: true},
		{Server: "nginx", Name: "a", Port: 443, TLS: true},
		{Server: "nginx", Name: "a", Port: 8080},
		{Server: "apache", Name: "a", Port: 4443, TLS: true},
		{Server: "nginx", Name: "b", Port: 8080},
		{Server: "nginx", Name: "b", Port: 80},
	})
	want := []Vhost{{Server: "nginx", Name: "a", Port: 443, TLS: true}, {Server: "nginx", Name: "b", Port: 80}}
	if !reflect.DeepEqual(got, want) {
		t.Errorf("vhosts = %+v, want %+v", got, want)
	}
}

func TestAWebServerThatIsNotThereOrDoesNotLoad(t *testing.T) {
	stubVhostRoots(t)
	none := answer{err: exec.ErrNotFound}
	calls := stubTools(t, none, none, none)
	if got, err := WebVhosts(context.Background()); err != nil || len(got) != 0 {
		t.Errorf("without a web server: %+v, %v; want none and no error", got, err)
	}
	want := [][]string{{"nginx", "-T"}, {"apache2ctl", "-S"}, {"apachectl", "-S"}}
	if !reflect.DeepEqual(*calls, want) {
		t.Errorf("calls = %q, want %q", *calls, want)
	}
	stubTools(t, answer{err: &exec.ExitError{}}, none, none)
	if _, err := WebVhosts(context.Background()); err == nil || !strings.Contains(err.Error(), "nginx -T fails: the configuration does not load") {
		t.Errorf("broken nginx: err = %v, want the configuration that does not load", err)
	}
	stubTools(t, none, answer{err: &exec.ExitError{}})
	if _, err := WebVhosts(context.Background()); err == nil || !strings.Contains(err.Error(), "apache2ctl -S fails: the configuration does not load") {
		t.Errorf("broken Apache: err = %v, want the configuration that does not load", err)
	}
	stubTools(t, answer{err: errors.New("timeout")}, none, none)
	if _, err := WebVhosts(context.Background()); err == nil {
		t.Error("a failed nginx -T gave no error")
	}
	stubTools(t, none, none, answer{err: errors.New("timeout")})
	if _, err := WebVhosts(context.Background()); err == nil {
		t.Error("a failed apachectl -S gave no error")
	}
}

func TestTheFilesOfApacheVhostsAreCapped(t *testing.T) {
	stubVhostRoots(t)
	var out strings.Builder
	for i := range maxApacheFiles + 1 {
		fmt.Fprintf(&out, "*:80                   h%d.example.org (/nonexistent/%d.conf:1)\n", i, i)
	}
	got, err := apacheVhosts([]byte(out.String()))
	if len(got) != maxApacheFiles || err == nil || !strings.Contains(err.Error(), "more than") {
		t.Errorf("%d vhosts, err %v; want %d and the cap", len(got), err, maxApacheFiles)
	}
}

func TestServersOfUpstreamStreamAndMailAreNoVhosts(t *testing.T) {
	stubVhostRoots(t)
	got := nginxVhosts([]byte("# configuration file /etc/nginx/nginx.conf:\n" +
		"stream { server { listen 3306; server_name db.example.org; } include streams/*.conf; }\n" +
		"mail { server { listen 25; server_name mail.example.org; } }\n" +
		"http { upstream up { server a.example.org:80; } server { server_name web.example.org; } }\n" +
		"# configuration file /etc/nginx/streams/pg.conf:\n" +
		"server { listen 5432; server_name pg.example.org; }\n"))
	if len(got) != 1 || got[0].Name != "web.example.org" {
		t.Errorf("vhosts = %+v, want web.example.org alone", got)
	}
}

// A snippet is read inside the server that includes it, in each that does: its certificate and its
// listen are that server's, not the http block's.
func TestASnippetBelongsToEachServerThatIncludesIt(t *testing.T) {
	stubVhostRoots(t)
	got := nginxVhosts([]byte(`# configuration file /etc/nginx/nginx.conf:
http {
    ssl_certificate /etc/ssl/http.pem;
    include sites/*;
}
# configuration file /etc/nginx/sites/a:
server { server_name a.example.org; include snippets/tls.conf; include snippets/snakeoil.conf; }
server { server_name b.example.org; listen 443 ssl; }
server { server_name c.example.org; include /etc/nginx/snippets/tls.conf; }
# configuration file /etc/nginx/snippets/tls.conf:
listen 8443 ssl;
# configuration file /etc/nginx/snippets/snakeoil.conf:
ssl_certificate /etc/ssl/snakeoil.pem;
# configuration file /etc/nginx/orphan.conf:
ssl_certificate /etc/ssl/orphan.pem;
listen 9999;
server { server_name d.example.org; }
`))
	want := []Vhost{
		{Server: "nginx", Name: "a.example.org", Port: 8443, TLS: true, cert: "/etc/ssl/snakeoil.pem"},
		{Server: "nginx", Name: "b.example.org", Port: 443, TLS: true, cert: "/etc/ssl/http.pem"},
		{Server: "nginx", Name: "c.example.org", Port: 8443, TLS: true, cert: "/etc/ssl/http.pem"},
		{Server: "nginx", Name: "d.example.org", Port: 80},
	}
	if !reflect.DeepEqual(got, want) {
		t.Errorf("vhosts =\n%+v\nwant\n%+v", got, want)
	}
}
