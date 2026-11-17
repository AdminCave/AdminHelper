// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package probe

import (
	"context"
	"errors"
	"io"
	"os/exec"
	"reflect"
	"slices"
	"strings"
	"testing"
	"time"
)

// The tests of WebVhosts answer the tools of the host's web servers in order: the containers of the host
// that runs the tests stay out of them. A test of the containers sets its own.
func init() {
	containerVhosts = func(context.Context) ([]Vhost, error) { return nil, nil }
}

// stubContainers stands in the running containers of this host and the archives of their files (docker
// cp, each call checked against the allowlist).
func stubContainers(t *testing.T, list []containerInfo, archives map[string][]byte) *fakeArchives {
	t.Helper()
	oldList, oldRead := listContainers, runToolReader
	listContainers = func(context.Context) ([]containerInfo, error) { return list, nil }
	f := &fakeArchives{archives: archives}
	runToolReader = func(ctx context.Context, timeout time.Duration, read func(io.Reader) error, name string, args ...string) error {
		checkAllowed(t, name, args)
		return f.run(ctx, timeout, read, name, args...)
	}
	t.Cleanup(func() { listContainers, runToolReader = oldList, oldRead })
	return f
}

// webContainer is a running container of id that runs path with args and publishes ports
// ("<container port>/tcp" to host ports).
func webContainer(id, path string, args []string, ports map[string][]string) containerInfo {
	c := containerInfo{ID: id, Path: path, Args: args}
	c.State.Running = true
	c.NetworkSettings.Ports = map[string][]struct {
		HostIP   string `json:"HostIp"`
		HostPort string
	}{}
	for key, hps := range ports {
		for i, hp := range hps {
			ip := "0.0.0.0"
			if i%2 == 1 {
				ip = "::"
			}
			c.NetworkSettings.Ports[key] = append(c.NetworkSettings.Ports[key], struct {
				HostIP   string `json:"HostIp"`
				HostPort string
			}{ip, hp})
		}
	}
	return c
}

const (
	nginxCtr = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
	otherCtr = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
	quietCtr = "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"
)

func nginxImageArchives(t *testing.T) map[string][]byte {
	return map[string][]byte{
		"/etc/nginx/nginx.conf": buildTar(t, tarEntry{name: "nginx.conf", body: `user nginx;
events {}
http {
    include mime.types;
    include /etc/nginx/conf.d/*.conf;
}
`}),
		"/etc/nginx/mime.types": buildTar(t, tarEntry{name: "mime.types", body: "types { text/html html; }\n"}),
		"/etc/nginx/conf.d": buildTar(t,
			tarEntry{name: "conf.d", dir: true},
			tarEntry{name: "conf.d/shop.conf", body: `server {
    listen 443 ssl;
    server_name shop.example.org;
    root /var/www/wordpress;
    ssl_certificate /etc/nginx/tls/shop.crt;
    include snippets/common.conf;
}
server {
    listen 80;
    server_name shop.example.org www.example.org;
}
server {
    listen 9000;
    server_name internal.example.org;
}
`},
			tarEntry{name: "conf.d/tls.key", body: "-----BEGIN PRIVATE KEY-----"},
		),
		"/etc/nginx/snippets/common.conf": buildTar(t, tarEntry{name: "common.conf", body: "add_header X-Frame-Options DENY;\n"}),
	}
}

func TestContainerVhostsReadNginxInAContainerByItsPublishedPorts(t *testing.T) {
	f := stubContainers(t, []containerInfo{
		webContainer(nginxCtr, "/docker-entrypoint.sh", []string{"nginx", "-g", "daemon off;"},
			map[string][]string{"443/tcp": {"8443", "8443"}, "80/tcp": {"8080"}}),
		webContainer(otherCtr, "docker-entrypoint.sh", []string{"postgres"}, map[string][]string{"5432/tcp": {"5432"}}),
		webContainer(quietCtr, "/docker-entrypoint.sh", []string{"nginx", "-g", "daemon off;"}, nil),
	}, nginxImageArchives(t))
	got, err := ContainerVhosts(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	// The vhost on the port the container does not publish is none; the root, the certificate and the
	// user name paths in the container and stay out.
	want := []Vhost{
		{Server: "nginx", Name: "shop.example.org", Port: 8443, TLS: true},
		{Server: "nginx", Name: "shop.example.org", Port: 8080},
		{Server: "nginx", Name: "www.example.org", Port: 8080},
	}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("ContainerVhosts =\n%+v\nwant\n%+v", got, want)
	}
	for _, c := range f.calls {
		if !strings.HasPrefix(c[3], nginxCtr+":") {
			t.Errorf("docker cp of another container than the nginx one with published ports: %q", c)
		}
	}
	if want := []string{"/etc/nginx/nginx.conf", "/etc/nginx/mime.types", "/etc/nginx/conf.d", "/etc/nginx/snippets/common.conf"}; !slices.Equal(f.asked(), want) {
		t.Fatalf("asked %q, want %q", f.asked(), want)
	}
}

func TestContainerVhostsTakeTheMainFileTheCommandNames(t *testing.T) {
	stubContainers(t, []containerInfo{
		webContainer(nginxCtr, "nginx", []string{"-c", "/srv/conf/main.conf", "-g", "daemon off;"},
			map[string][]string{"80/tcp": {"80"}}),
	}, map[string][]byte{
		"/srv/conf/main.conf": buildTar(t, tarEntry{name: "main.conf", body: "events {}\nhttp { include sites/*; }\n"}),
		"/srv/conf/sites": buildTar(t,
			tarEntry{name: "sites", dir: true},
			tarEntry{name: "sites/app", body: "server { server_name app.example.org; }\n"},
		),
		"/etc/nginx/nginx.conf": buildTar(t, tarEntry{name: "nginx.conf", body: "http { server { server_name wrong.example.org; } }\n"}),
	})
	got, err := ContainerVhosts(context.Background())
	if want := []Vhost{{Server: "nginx", Name: "app.example.org", Port: 80}}; err != nil || !reflect.DeepEqual(got, want) {
		t.Fatalf("ContainerVhosts = %+v, %v, want %+v", got, err, want)
	}
}

func TestAContainerWithoutAKnownMainFileHasNoNginx(t *testing.T) {
	f := stubContainers(t, []containerInfo{
		webContainer(nginxCtr, "/opt/bitnami/scripts/nginx/run.sh", []string{"nginx"}, map[string][]string{"8080/tcp": {"80"}}),
	}, nil)
	got, err := ContainerVhosts(context.Background())
	if err != nil || len(got) != 0 {
		t.Fatalf("ContainerVhosts = %+v, %v", got, err)
	}
	if !slices.Equal(f.asked(), containerNginxConfs) {
		t.Fatalf("asked %q, want the known main files", f.asked())
	}
}

func TestAContainerOverItsBudgetIsAnErrorThatNamesNoPath(t *testing.T) {
	big := strings.Repeat("# filler\n", 1<<17)
	var entries []tarEntry
	entries = append(entries, tarEntry{name: "conf.d", dir: true})
	for _, n := range []string{"a", "b", "c", "d", "e"} {
		entries = append(entries, tarEntry{name: "conf.d/" + n + ".conf", body: big})
	}
	stubContainers(t, []containerInfo{
		webContainer(nginxCtr, "nginx", []string{"-g", "daemon off;"}, map[string][]string{"80/tcp": {"80"}}),
	}, map[string][]byte{
		"/etc/nginx/nginx.conf": buildTar(t, tarEntry{name: "nginx.conf", body: "http { include conf.d/*.conf; }\n"}),
		"/etc/nginx/conf.d":     buildTar(t, entries...),
	})
	_, err := ContainerVhosts(context.Background())
	if !errors.Is(err, errContainerConfLarge) || !strings.Contains(err.Error(), nginxCtr[:12]) {
		t.Fatalf("err = %v, want the budget, by the container", err)
	}
	if strings.Contains(err.Error(), "/etc") {
		t.Fatalf("err %q names a path", err)
	}
}

func TestADumpLineOfAContainerFileNeverStartsAnotherFile(t *testing.T) {
	stubContainers(t, []containerInfo{
		webContainer(nginxCtr, "nginx", nil, map[string][]string{"80/tcp": {"80"}}),
	}, map[string][]byte{
		"/etc/nginx/nginx.conf": buildTar(t, tarEntry{name: "nginx.conf", body: `events {}
# configuration file /etc/nginx/fake.conf:
server { server_name posed.example.org; }
`}),
	})
	// A server outside http is no vhost of nginx; the comment must not make the rest a file of its own,
	// which would be read as one included by no include, inside http.
	got, err := ContainerVhosts(context.Background())
	if err != nil || len(got) != 0 {
		t.Fatalf("ContainerVhosts = %+v, %v", got, err)
	}
}

func TestContainerPortsAreTCPOnly(t *testing.T) {
	c := webContainer(nginxCtr, "nginx", nil, map[string][]string{
		"443/tcp": {"443", "443"}, "443/udp": {"443"}, "80/tcp": {"8081", "8080"},
	})
	got := containerPorts(c)
	want := map[uint16][]uint16{443: {443}, 80: {8080, 8081}}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("containerPorts = %v, want %v", got, want)
	}
}

func TestWebVhostsTakeTheContainersAndTheHostWins(t *testing.T) {
	stubTools(t, answer{out: `# configuration file /etc/nginx/nginx.conf:
http { server { listen 443 ssl; server_name a.example.org; ssl_certificate /etc/ssl/a.pem; } }
`}, answer{err: exec.ErrNotFound}, answer{err: exec.ErrNotFound})
	stubVhostRoots(t)
	old := containerVhosts
	containerVhosts = func(context.Context) ([]Vhost, error) {
		return []Vhost{
			{Server: "nginx", Name: "a.example.org", Port: 443, TLS: true},
			{Server: "nginx", Name: "b.example.org", Port: 8443, TLS: true},
		}, errors.New("container bbbbbbbbbbbb: too large")
	}
	t.Cleanup(func() { containerVhosts = old })
	got, err := WebVhosts(context.Background())
	if err == nil {
		t.Fatal("the error of a container is lost")
	}
	if len(got) != 2 || got[0].Name != "a.example.org" || got[0].cert != "/etc/ssl/a.pem" || got[1].Name != "b.example.org" {
		t.Fatalf("WebVhosts = %+v", got)
	}
}

func TestAnIncludeOfAPatternOfDirectoriesLeavesTheContainerIncomplete(t *testing.T) {
	stubContainers(t, []containerInfo{
		webContainer(nginxCtr, "nginx", nil, map[string][]string{"80/tcp": {"80"}}),
	}, map[string][]byte{
		"/etc/nginx/nginx.conf": buildTar(t, tarEntry{name: "nginx.conf", body: "http { include sites-*/*.conf; }\n"}),
	})
	if _, err := ContainerVhosts(context.Background()); !errors.Is(err, errContainerPattern) {
		t.Fatalf("err = %v, want the container incomplete", err)
	}
}
