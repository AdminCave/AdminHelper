// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package probe

import (
	"context"
	"crypto/x509"
	"encoding/json"
	"encoding/pem"
	"errors"
	"fmt"
	"io"
	"io/fs"
	"math"
	"net/http"
	"net/netip"
	"net/url"
	"os"
	"path"
	"strings"
	"time"
)

// caddyAdminPort is the port of Caddy's admin API by default (localhost:2019, caddyserver.com/docs/api).
const caddyAdminPort = 2019

// caddyEndpoint finds where the unit of Caddy listens; tests point it at their server.
var caddyEndpoint = resolve

// caddyUpstreams counts the upstreams of Caddy's reverse proxies and those with failed requests, from
// GET /reverse_proxy/upstreams of Caddy's admin API on loopback. It never asks /config/, which holds
// the secrets of the configuration, and keeps no address of an upstream.
func caddyUpstreams(ctx context.Context, t Target) (map[string]any, error) {
	port := caddyAdminPort
	if t.PortHint > 0 {
		port = t.PortHint
	}
	t.PortHint = port
	ep, err := caddyEndpoint(ctx, t)
	if err != nil {
		return nil, err
	}
	// Without its admin port the unit's one other port would be a site's: never ask a site.
	if int(ep.port) != port {
		return nil, fmt.Errorf("%w: unit %s does not listen on the admin port %d", ErrUnsupported, t.Name, port)
	}
	if !ep.addr.IsLoopback() {
		return nil, fmt.Errorf("unit %s has its admin API beyond loopback; the view asks it on loopback alone", t.Name)
	}
	u := url.URL{Scheme: "http", Host: netip.AddrPortFrom(ep.addr, ep.port).String(), Path: "/reverse_proxy/upstreams"}
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, u.String(), nil)
	if err != nil {
		return nil, errors.New("the request to Caddy cannot be built")
	}
	resp, err := NewGuard(ep.extra...).HTTPClient(nil).Do(req)
	if err != nil {
		return nil, netErr(ctx, err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("Caddy answers /reverse_proxy/upstreams with HTTP %d", resp.StatusCode)
	}
	var ups []struct {
		Fails *int `json:"fails"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&ups); err != nil {
		return nil, netErr(ctx, errors.New("Caddy answers /reverse_proxy/upstreams with no list of upstreams"))
	}
	failing := 0
	for _, u := range ups {
		if u.Fails == nil {
			return nil, errors.New("Caddy answers /reverse_proxy/upstreams with an upstream without fails")
		}
		if *u.Fails > 0 {
			failing++
		}
	}
	return map[string]any{"upstreams": len(ups), "failing": failing}, nil
}

const (
	// maxACMEStoreBytes caps Traefik's acme.json, which holds every certificate it manages.
	maxACMEStoreBytes = 16 << 20
	// maxProxyCerts caps the entries a certificates view reads.
	maxProxyCerts = 10_000
)

var (
	// caddyDataDirs are where Caddy keeps its data, relative to the root of its process: the official
	// image's XDG_DATA_HOME, the home of the user caddy of the packages, and that of root
	// (caddyserver.com/docs/conventions#data-directory).
	caddyDataDirs = []string{"data/caddy", "var/lib/caddy/.local/share/caddy", "root/.local/share/caddy"}

	// traefikStores are where Traefik's ACME store (option storage) is put in its documentation and the
	// usual setups, relative to the root of its process.
	traefikStores = []string{
		"acme.json", "data/acme.json", "letsencrypt/acme.json",
		"etc/traefik/acme.json", "etc/traefik/acme/acme.json", "var/lib/traefik/acme.json",
	}

	// npmCertDirs hold one directory npm-<id> per certificate of Nginx Proxy Manager: certbot's live
	// directory for Let's Encrypt and the uploaded ones (backend/internal/certificate.js).
	npmCertDirs = []string{"etc/letsencrypt/live", "data/custom_ssl"}

	// hostRoot opens the root of this host, where a proxy installed as a unit keeps its files.
	hostRoot = func() (*os.Root, error) { return os.OpenRoot("/") }
)

// errNoProxyFiles: the root holds none of the places a proxy keeps its certificates.
var errNoProxyFiles = errors.New("no certificate store")

// certCount adds up the certificates a view read.
type certCount struct {
	certs, expired int
	minLeft        float64
}

func (c *certCount) add(notAfter time.Time) {
	left := notAfter.Sub(now()).Hours() / 24
	if c.certs == 0 || left < c.minLeft {
		c.minLeft = left
	}
	c.certs++
	if left < 0 {
		c.expired++
	}
}

func (c certCount) values() map[string]any {
	v := map[string]any{"certs": c.certs, "expired": c.expired}
	if c.certs > 0 {
		v["min_days_left"] = int(math.Floor(c.minLeft))
	}
	return v
}

// caddyCerts reads when the certificates in Caddy's data directory expire. Of the certificates of its
// own CA (issuer local), which live 12 hours and renew themselves, it reads none; it opens no .key
// file.
func caddyCerts(ctx context.Context, t Target) (map[string]any, error) {
	return proxyCerts(ctx, t, "Caddy", func(root *os.Root, c *certCount) error {
		found := false
		for _, dir := range caddyDataDirs {
			issuers, err := readDirNames(root, dir+"/certificates")
			if errors.Is(err, fs.ErrNotExist) {
				continue
			}
			if err != nil {
				return err
			}
			found = true
			for _, issuer := range issuers {
				if issuer == "local" {
					continue
				}
				sites, err := readDirNames(root, dir+"/certificates/"+issuer)
				if err != nil {
					return err
				}
				for _, site := range sites {
					// The name of a site is a domain: errors name its issuer's directory alone.
					shown := "a certificate in /" + dir + "/certificates/" + issuer
					err := addCertFile(root, dir+"/certificates/"+issuer+"/"+site+"/"+site+".crt", shown, c)
					if err != nil && !errors.Is(err, fs.ErrNotExist) {
						return err
					}
				}
			}
		}
		if !found {
			return errNoProxyFiles
		}
		return nil
	})
}

// traefikCerts reads when the certificates in Traefik's ACME store expire: of each one the field
// certificate, never key, and of the account nothing.
func traefikCerts(ctx context.Context, t Target) (map[string]any, error) {
	return proxyCerts(ctx, t, "Traefik", func(root *os.Root, c *certCount) error {
		found := false
		for _, name := range traefikStores {
			data, err := readRootFile(root, name, "/"+name, maxACMEStoreBytes)
			if errors.Is(err, fs.ErrNotExist) {
				continue
			}
			if err != nil {
				return err
			}
			found = true
			// Traefik creates the store empty at its start and writes it with the first account.
			if strings.TrimSpace(string(data)) == "" {
				continue
			}
			// pkg/provider/acme: a map of resolvers, each with its certificates, whose PEM json carries
			// in base64 ([]byte).
			var store map[string]struct {
				Certificates []struct {
					Certificate []byte `json:"certificate"`
				}
			}
			if json.Unmarshal(data, &store) != nil {
				return fmt.Errorf("/%s is no ACME store of Traefik", name)
			}
			for _, r := range store {
				for _, cert := range r.Certificates {
					if c.certs >= maxProxyCerts {
						return fmt.Errorf("more than %d certificates", maxProxyCerts)
					}
					notAfter, err := leafNotAfter(cert.Certificate)
					if err != nil {
						return fmt.Errorf("a certificate in /%s %w", name, err)
					}
					c.add(notAfter)
				}
			}
		}
		if !found {
			return errNoProxyFiles
		}
		return nil
	})
}

// npmCerts reads when the certificates of Nginx Proxy Manager expire: fullchain.pem of each directory
// npm-<id>, never privkey.pem. In certbot's live directory fullchain.pem is a link into the archive;
// it is followed inside the container alone.
func npmCerts(ctx context.Context, t Target) (map[string]any, error) {
	return proxyCerts(ctx, t, "Nginx Proxy Manager", func(root *os.Root, c *certCount) error {
		found := false
		for _, dir := range npmCertDirs {
			names, err := readDirNames(root, dir)
			if errors.Is(err, fs.ErrNotExist) {
				continue
			}
			if err != nil {
				return err
			}
			found = true
			for _, n := range names {
				if !strings.HasPrefix(n, "npm-") {
					continue
				}
				name, err := resolveInRoot(root, dir+"/"+n+"/fullchain.pem", path.Dir(dir))
				if err == nil {
					err = addCertFile(root, name, "/"+name, c)
				}
				if err != nil && !errors.Is(err, fs.ErrNotExist) {
					return err
				}
			}
		}
		if !found {
			return errNoProxyFiles
		}
		return nil
	})
}

// proxyCerts opens the root of t's process, the host's for a unit, and counts what read finds below
// it. Its errors name places of the proxy, never a certificate's subject or what a file holds.
func proxyCerts(ctx context.Context, t Target, proxy string, read func(*os.Root, *certCount) error) (map[string]any, error) {
	open := hostRoot
	if t.Kind == kindContainer {
		c, err := inspectContainer(ctx, t.Name)
		if err != nil {
			return nil, err
		}
		if !c.State.Running || c.State.Pid <= 0 {
			return nil, fmt.Errorf("container %s is not running", t.Name)
		}
		open = func() (*os.Root, error) { return containerRoot(c.State.Pid) }
	}
	return untilDone(ctx, func() (map[string]any, error) {
		root, err := open()
		if errors.Is(err, ErrUnsupported) {
			return nil, err
		}
		if err != nil {
			return nil, fmt.Errorf("the root of %s %s cannot be opened: %v", t.Kind, t.Name, cause(err))
		}
		defer root.Close()
		var c certCount
		err = read(root, &c)
		if errors.Is(err, errNoProxyFiles) {
			return nil, fmt.Errorf("%w: %s %s holds no certificates of %s", ErrUnsupported, t.Kind, t.Name, proxy)
		}
		if err != nil {
			return nil, fmt.Errorf("the certificates of %s: %w", proxy, err)
		}
		return c.values(), nil
	})
}

// readDirNames returns the names of the directories in the directory dir below root, at most
// maxProxyCerts of them.
func readDirNames(root *os.Root, dir string) ([]string, error) {
	f, err := root.OpenFile(dir, dirFlags, 0)
	if errors.Is(err, fs.ErrNotExist) {
		return nil, fs.ErrNotExist
	}
	if errors.Is(notDir(err), errNotDir) {
		return nil, fmt.Errorf("/%s is no directory", dir)
	}
	if err != nil {
		return nil, fmt.Errorf("/%s cannot be read: %v", dir, cause(err))
	}
	defer f.Close()
	if fi, err := f.Stat(); err != nil || !fi.IsDir() {
		return nil, fmt.Errorf("/%s is no directory", dir)
	}
	entries, err := f.ReadDir(maxProxyCerts + 1)
	if err != nil && !errors.Is(err, io.EOF) {
		return nil, fmt.Errorf("/%s cannot be read: %v", dir, cause(err))
	}
	if len(entries) > maxProxyCerts {
		return nil, fmt.Errorf("/%s holds more than %d entries", dir, maxProxyCerts)
	}
	var names []string
	for _, e := range entries {
		if e.IsDir() {
			names = append(names, e.Name())
		}
	}
	return names, nil
}

// resolveInRoot returns name, or where the link at name leads if it is one: a relative link, as
// certbot puts in its live directory, that stays below the directory within. Another link is an
// error.
func resolveInRoot(root *os.Root, name, within string) (string, error) {
	fi, err := root.Lstat(name)
	if err != nil {
		return "", err
	}
	if fi.Mode()&fs.ModeSymlink == 0 {
		return name, nil
	}
	dest, err := root.Readlink(name)
	if err != nil {
		return "", fmt.Errorf("/%s cannot be read: %v", name, cause(err))
	}
	target := path.Join(path.Dir(name), dest)
	if path.IsAbs(dest) || !strings.HasPrefix(target, within+"/") {
		return "", fmt.Errorf("/%s is a link out of the directories of certificates", name)
	}
	return target, nil
}

// addCertFile counts the certificate of the PEM file name below root; its errors call the file shown.
func addCertFile(root *os.Root, name, shown string, c *certCount) error {
	if c.certs >= maxProxyCerts {
		return fmt.Errorf("more than %d certificates", maxProxyCerts)
	}
	data, err := readRootFile(root, name, shown, maxCertFileBytes)
	if err != nil {
		return err
	}
	notAfter, err := leafNotAfter(data)
	if err != nil {
		return fmt.Errorf("%s %w", shown, err)
	}
	c.add(notAfter)
	return nil
}

// readRootFile reads the regular file name below root, at most limit bytes, through openRegular: no
// link at name, no FIFO, no device. Its errors call the file shown; a file that is not there is
// fs.ErrNotExist.
func readRootFile(root *os.Root, name, shown string, limit int64) ([]byte, error) {
	if _, err := root.Lstat(name); errors.Is(err, fs.ErrNotExist) {
		return nil, fs.ErrNotExist
	}
	f, err := openRegular(root, name, shown)
	if err != nil {
		return nil, err
	}
	defer f.Close()
	data, err := io.ReadAll(io.LimitReader(f, limit+1))
	if err != nil {
		return nil, fmt.Errorf("%s cannot be read: %v", shown, cause(err))
	}
	if int64(len(data)) > limit {
		return nil, fmt.Errorf("%s is larger than %d bytes", shown, limit)
	}
	return data, nil
}

// leafNotAfter returns the end of validity of the first certificate in the PEM data, the leaf of a
// chain. Any other block, a private key among them, it skips and never quotes.
func leafNotAfter(data []byte) (time.Time, error) {
	for {
		var b *pem.Block
		b, data = pem.Decode(data)
		if b == nil {
			return time.Time{}, errors.New("holds no PEM certificate")
		}
		if b.Type != "CERTIFICATE" {
			continue
		}
		cert, err := x509.ParseCertificate(b.Bytes)
		if err != nil {
			return time.Time{}, errors.New("holds a certificate that cannot be parsed")
		}
		return cert.NotAfter, nil
	}
}
