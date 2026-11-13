// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package probe

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

// proxySecret stands for the private keys next to the certificates: no value and no error may carry it.
const proxySecret = "s3cr3t-pr1vate-key"

var proxyKey = "-----BEGIN PRIVATE KEY-----\n" + proxySecret + "\n-----END PRIVATE KEY-----\n"

// certPEM is a PEM file of a leaf certificate valid until notAfter.
func certPEM(t *testing.T, notAfter time.Time) []byte {
	t.Helper()
	data, err := os.ReadFile(writeCert(t, notAfter))
	if err != nil {
		t.Fatal(err)
	}
	return data
}

// put writes data to the file rel below root.
func put(t *testing.T, root, rel string, data []byte) {
	t.Helper()
	path := filepath.Join(root, filepath.FromSlash(rel))
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, data, 0o600); err != nil {
		t.Fatal(err)
	}
}

func link(t *testing.T, root, rel, dest string) {
	t.Helper()
	path := filepath.Join(root, filepath.FromSlash(rel))
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(dest, path); err != nil {
		t.Fatal(err)
	}
}

// stubHostRoot makes dir the root of this host for the views of a unit.
func stubHostRoot(t *testing.T, dir string) {
	t.Helper()
	old := hostRoot
	hostRoot = func() (*os.Root, error) { return os.OpenRoot(dir) }
	t.Cleanup(func() { hostRoot = old })
}

// proxyContainer is the root of a running container web; it stubs docker and containerRoot.
func proxyContainer(t *testing.T) (string, *[]int) {
	t.Helper()
	root := t.TempDir()
	stubTool(t, inspectJSON(t, "running", "", "bridge"), nil)
	return root, stubContainerRoot(t, func(int) (*os.Root, error) { return os.OpenRoot(root) })
}

func proxyUnit(name string) Target { return Target{Kind: kindUnit, Name: name} }

func wantCerts(t *testing.T, got map[string]any, err error, certs, expired, minLeft int) {
	t.Helper()
	want := map[string]any{"certs": certs, "expired": expired, "min_days_left": minLeft}
	if err != nil || fmt.Sprint(got) != fmt.Sprint(want) {
		t.Fatalf("view = %v, %v; want %v", got, err, want)
	}
	noneOf(t, got, proxySecret, "example.org")
}

// caddySite puts a certificate of site from issuer into Caddy's data directory dir below root, with
// its key and metadata next to it as certmagic keeps them.
func caddySite(t *testing.T, root, dir, issuer, site string, notAfter time.Time) {
	t.Helper()
	base := dir + "/certificates/" + issuer + "/" + site + "/" + site
	put(t, root, base+".crt", certPEM(t, notAfter))
	put(t, root, base+".key", []byte(proxyKey))
	put(t, root, base+".json", []byte(`{"sans":["`+site+`"],"issuer_data":{"url":"https://acme.example/cert/`+proxySecret+`"}}`))
}

const letsEncrypt = "acme-v02.api.letsencrypt.org-directory"

func TestCaddyCertsReadsTheCertificatesOfTheUnit(t *testing.T) {
	stubNow(t, start)
	root := t.TempDir()
	stubHostRoot(t, root)
	dir := "var/lib/caddy/.local/share/caddy"
	caddySite(t, root, dir, letsEncrypt, "example.org", start.Add(60*24*time.Hour))
	caddySite(t, root, dir, letsEncrypt, "www.example.org", start.Add(20*24*time.Hour+time.Hour))
	caddySite(t, root, dir, "acme.zerossl.com-v2-dv90", "shop.example.org", start.Add(-2*time.Hour))
	// Of its own CA Caddy keeps certificates of 12 hours that renew themselves: never counted.
	caddySite(t, root, dir, "local", "intranet.example.org", start.Add(-time.Hour))
	caddySite(t, root, dir, "local", "printer.example.org", start.Add(6*time.Hour))
	put(t, root, dir+"/certificates/"+letsEncrypt+"/README", []byte("not a site"))
	got, err := caddyCerts(context.Background(), proxyUnit("caddy.service"))
	wantCerts(t, got, err, 3, 1, -1)
}

func TestCaddyCertsReadsTheDataDirectoryOfTheImage(t *testing.T) {
	stubNow(t, start)
	root, pids := proxyContainer(t)
	caddySite(t, root, "data/caddy", letsEncrypt, "example.org", start.Add(30*24*time.Hour))
	got, err := caddyCerts(context.Background(), Target{Kind: kindContainer, Name: "web"})
	wantCerts(t, got, err, 1, 0, 30)
	if len(*pids) != 1 || (*pids)[0] != 4242 {
		t.Errorf("opened the roots of %v, want the container's process 4242", *pids)
	}
}

func TestCaddyCertsWithoutADataDirectory(t *testing.T) {
	root := t.TempDir()
	stubHostRoot(t, root)
	put(t, root, "etc/caddy/Caddyfile", []byte("example.org\n"))
	if _, err := caddyCerts(context.Background(), proxyUnit("caddy.service")); !errors.Is(err, ErrUnsupported) {
		t.Errorf("no data directory = %v, want ErrUnsupported", err)
	}
	// A data directory without certificates yet: none, no error.
	if err := os.MkdirAll(filepath.Join(root, "root/.local/share/caddy/certificates"), 0o755); err != nil {
		t.Fatal(err)
	}
	got, err := caddyCerts(context.Background(), proxyUnit("caddy.service"))
	if err != nil || fmt.Sprint(got) != fmt.Sprint(map[string]any{"certs": 0, "expired": 0}) {
		t.Errorf("an empty data directory = %v, %v", got, err)
	}
}

func TestCaddyCertsFollowsNoLink(t *testing.T) {
	root := t.TempDir()
	stubHostRoot(t, root)
	dir := "data/caddy/certificates/" + letsEncrypt + "/example.org"
	put(t, root, "secret.pem", []byte(proxyKey))
	link(t, root, dir+"/example.org.crt", "../../../../../secret.pem")
	_, err := caddyCerts(context.Background(), proxyUnit("caddy.service"))
	if err == nil || !strings.Contains(err.Error(), "is no regular file") {
		t.Fatalf("a link = %v, want it refused", err)
	}
	if strings.Contains(err.Error(), "example.org") || strings.Contains(err.Error(), proxySecret) {
		t.Errorf("error %q names the site or the key", err)
	}
}

func TestCaddyCertsErrorsNameNoSite(t *testing.T) {
	root := t.TempDir()
	stubHostRoot(t, root)
	put(t, root, "data/caddy/certificates/"+letsEncrypt+"/example.org/example.org.crt", []byte(proxyKey))
	_, err := caddyCerts(context.Background(), proxyUnit("caddy.service"))
	if err == nil || !strings.Contains(err.Error(), "holds no PEM certificate") {
		t.Fatalf("a key for a certificate = %v", err)
	}
	if strings.Contains(err.Error(), "example.org") || strings.Contains(err.Error(), proxySecret) {
		t.Errorf("error %q names the site or the key", err)
	}
}

// acmeStore is Traefik's acme.json (pkg/provider/acme/local_store.go): per resolver its account with
// the account's private key and its certificates, each with domain, certificate and key, PEM in base64.
func acmeStore(t *testing.T, resolvers map[string][]time.Time) []byte {
	t.Helper()
	store := map[string]any{}
	for name, ends := range resolvers {
		var certs []map[string]any
		for i, end := range ends {
			certs = append(certs, map[string]any{
				"domain":      map[string]any{"main": fmt.Sprintf("site%d.example.org", i)},
				"certificate": certPEM(t, end),
				"key":         []byte(proxyKey),
				"Store":       "default",
			})
		}
		store[name] = map[string]any{
			"Account": map[string]any{
				"Email": "admin@example.org", "PrivateKey": proxySecret, "KeyType": "4096",
				"Registration": map[string]any{"uri": "https://acme.example/acct/1"},
			},
			"Certificates": certs,
		}
	}
	data, err := json.Marshal(store)
	if err != nil {
		t.Fatal(err)
	}
	return data
}

func TestTraefikCertsReadsTheACMEStore(t *testing.T) {
	stubNow(t, start)
	root, _ := proxyContainer(t)
	put(t, root, "letsencrypt/acme.json", acmeStore(t, map[string][]time.Time{
		"letsencrypt": {start.Add(70 * 24 * time.Hour), start.Add(13*24*time.Hour + time.Hour)},
		"staging":     {start.Add(-24*time.Hour - time.Minute)},
	}))
	got, err := traefikCerts(context.Background(), Target{Kind: kindContainer, Name: "web"})
	wantCerts(t, got, err, 3, 1, -2)
}

func TestTraefikCertsReadsTheStoreOfTheUnit(t *testing.T) {
	stubNow(t, start)
	root := t.TempDir()
	stubHostRoot(t, root)
	put(t, root, "etc/traefik/acme.json", acmeStore(t, map[string][]time.Time{"le": {start.Add(50 * 24 * time.Hour)}}))
	got, err := traefikCerts(context.Background(), proxyUnit("traefik.service"))
	wantCerts(t, got, err, 1, 0, 50)
}

func TestTraefikCertsTakesAnEmptyStoreForNoCertificates(t *testing.T) {
	stubNow(t, start)
	root := t.TempDir()
	stubHostRoot(t, root)
	for _, store := range []string{"", " \n"} {
		put(t, root, "acme.json", []byte(store))
		got, err := traefikCerts(context.Background(), proxyUnit("traefik.service"))
		if err != nil || got["certs"] != 0 || got["expired"] != 0 || len(got) != 2 {
			t.Errorf("store %q = %v, %v; want no certificates", store, got, err)
		}
	}
}

func TestTraefikCertsErrorsNameNothingOfTheStore(t *testing.T) {
	root := t.TempDir()
	stubHostRoot(t, root)
	if _, err := traefikCerts(context.Background(), proxyUnit("traefik.service")); !errors.Is(err, ErrUnsupported) {
		t.Errorf("no store = %v, want ErrUnsupported", err)
	}
	cases := map[string]string{
		"no JSON":          proxySecret,
		"no map":           `["` + proxySecret + `"]`,
		"a broken base64":  `{"le":{"Certificates":[{"certificate":"` + proxySecret + `!"}]}}`,
		"a key as cert":    `{"le":{"Certificates":[{"certificate":"` + base64Of(proxyKey) + `"}]}}`,
		"no certificate":   `{"le":{"Certificates":[{"key":"` + base64Of(proxyKey) + `"}]}}`,
		"a broken PEM DER": `{"le":{"Certificates":[{"certificate":"` + base64Of("-----BEGIN CERTIFICATE-----\nczNjcjN0\n-----END CERTIFICATE-----\n") + `"}]}}`,
	}
	for name, store := range cases {
		t.Run(name, func(t *testing.T) {
			put(t, root, "acme.json", []byte(store))
			_, err := traefikCerts(context.Background(), proxyUnit("traefik.service"))
			if err == nil || strings.Contains(err.Error(), proxySecret) || strings.Contains(err.Error(), "czNj") {
				t.Fatalf("error %v, want one naming nothing of the store", err)
			}
		})
	}
}

func TestTraefikCertsRefusesAStoreTooLarge(t *testing.T) {
	root := t.TempDir()
	stubHostRoot(t, root)
	put(t, root, "acme.json", nil)
	if err := os.Truncate(filepath.Join(root, "acme.json"), maxACMEStoreBytes+1); err != nil {
		t.Fatal(err)
	}
	_, err := traefikCerts(context.Background(), proxyUnit("traefik.service"))
	if err == nil || !strings.Contains(err.Error(), "is larger than") {
		t.Errorf("a store too large = %v", err)
	}
}

func base64Of(s string) string {
	data, _ := json.Marshal([]byte(s))
	return strings.Trim(string(data), `"`)
}

func TestNpmCertsReadsLetsEncryptAndUploadedCertificates(t *testing.T) {
	stubNow(t, start)
	root, _ := proxyContainer(t)
	// certbot: live/<name>/fullchain.pem links into archive/<name>/fullchainN.pem.
	put(t, root, "etc/letsencrypt/archive/npm-1/fullchain3.pem", certPEM(t, start.Add(40*24*time.Hour)))
	put(t, root, "etc/letsencrypt/archive/npm-1/privkey3.pem", []byte(proxyKey))
	link(t, root, "etc/letsencrypt/live/npm-1/fullchain.pem", "../../archive/npm-1/fullchain3.pem")
	link(t, root, "etc/letsencrypt/live/npm-1/privkey.pem", "../../archive/npm-1/privkey3.pem")
	put(t, root, "etc/letsencrypt/live/README", []byte("This directory contains your keys and certificates."))
	put(t, root, "etc/letsencrypt/live/example.org/fullchain.pem", certPEM(t, start.Add(-time.Hour)))
	put(t, root, "data/custom_ssl/npm-7/fullchain.pem", certPEM(t, start.Add(8*24*time.Hour+time.Hour)))
	put(t, root, "data/custom_ssl/npm-7/privkey.pem", []byte(proxyKey))
	// A certificate whose renewal failed long ago may have lost its live link: not counted.
	if err := os.MkdirAll(filepath.Join(root, "etc/letsencrypt/live/npm-9"), 0o755); err != nil {
		t.Fatal(err)
	}
	got, err := npmCerts(context.Background(), Target{Kind: kindContainer, Name: "web"})
	wantCerts(t, got, err, 2, 0, 8)
}

func TestNpmCertsFollowsNoLinkOutOfItsDirectories(t *testing.T) {
	cases := map[string]string{
		"absolute": "/etc/shadow",
		"upward":   "../../../../etc/shadow",
	}
	for name, dest := range cases {
		t.Run(name, func(t *testing.T) {
			root, _ := proxyContainer(t)
			put(t, root, "etc/shadow", []byte(proxyKey))
			link(t, root, "etc/letsencrypt/live/npm-1/fullchain.pem", dest)
			_, err := npmCerts(context.Background(), Target{Kind: kindContainer, Name: "web"})
			if err == nil || !strings.Contains(err.Error(), "is a link out of") || strings.Contains(err.Error(), proxySecret) {
				t.Fatalf("a link to %s = %v, want it refused", dest, err)
			}
		})
	}
	// A link within the root that points to another link is not followed further.
	root, _ := proxyContainer(t)
	put(t, root, "etc/shadow", []byte(proxyKey))
	link(t, root, "etc/letsencrypt/archive/npm-1/fullchain1.pem", "/etc/shadow")
	link(t, root, "etc/letsencrypt/live/npm-1/fullchain.pem", "../../archive/npm-1/fullchain1.pem")
	_, err := npmCerts(context.Background(), Target{Kind: kindContainer, Name: "web"})
	if err == nil || !strings.Contains(err.Error(), "is no regular file") || strings.Contains(err.Error(), proxySecret) {
		t.Fatalf("a link to a link = %v, want it refused", err)
	}
}

func TestNpmCertsWithoutItsDirectories(t *testing.T) {
	root, _ := proxyContainer(t)
	put(t, root, "etc/nginx/nginx.conf", []byte("events {}\n"))
	if _, err := npmCerts(context.Background(), Target{Kind: kindContainer, Name: "web"}); !errors.Is(err, ErrUnsupported) {
		t.Errorf("no certificate directories = %v, want ErrUnsupported", err)
	}
}

func TestTheProxyCertViewsAskARunningContainer(t *testing.T) {
	_, pids := proxyContainer(t)
	stubTool(t, inspectJSON(t, "exited", "", "bridge"), nil)
	for name, read := range map[string]func(context.Context, Target) (map[string]any, error){
		"caddy": caddyCerts, "traefik": traefikCerts, "npm": npmCerts,
	} {
		if _, err := read(context.Background(), Target{Kind: kindContainer, Name: "web"}); err == nil || err.Error() != "container web is not running" {
			t.Errorf("%s of a stopped container = %v", name, err)
		}
	}
	if len(*pids) != 0 {
		t.Errorf("opened the roots of %v, want none", *pids)
	}
	stubContainerRoot(t, func(int) (*os.Root, error) { return nil, errors.New("gone") })
	stubTool(t, inspectJSON(t, "running", "", "bridge"), nil)
	_, err := caddyCerts(context.Background(), Target{Kind: kindContainer, Name: "web"})
	if err == nil || err.Error() != "the root of container web cannot be opened: gone" {
		t.Errorf("a root that cannot be opened = %v", err)
	}
}
