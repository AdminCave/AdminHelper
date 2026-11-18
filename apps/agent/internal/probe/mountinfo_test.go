// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package probe

import (
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
)

// A mount table as a Proxmox host writes it: the root, a tmpfs, two NFS stores, an SMB share with a
// space in its mount point, and the same NFS store mounted twice.
const mountinfoFixture = `22 1 253:1 / / rw,relatime shared:1 - ext4 /dev/mapper/pve-root rw,errors=remount-ro
25 22 0:22 / /run rw,nosuid,nodev shared:5 - tmpfs tmpfs rw,size=1636180k,mode=755
120 22 0:52 / /mnt/pve/backup rw,relatime shared:60 - nfs4 nas-a.example.org:/export/backup rw,vers=4.2
121 22 0:53 / /mnt/pve/iso rw,relatime shared:61 master:3 - nfs 192.0.2.10:/volume1/iso rw,vers=3
122 22 0:54 / /srv/team\040share rw,relatime - cifs //nas-b.example.org/team rw,vers=3.1.1
123 22 0:55 / /mnt/smb3 rw,relatime - smb3 //198.51.100.7/data rw
124 22 0:52 / /mnt/pve/backup rw,relatime shared:62 - nfs4 nas-a.example.org:/export/backup rw,vers=4.2
broken line
`

func TestShareMountsAreTheNetworkMountsWithoutTheirSource(t *testing.T) {
	got := ParseNetMounts([]byte(mountinfoFixture))
	want := []NetMount{
		{"/mnt/pve/backup", "nfs4"}, {"/mnt/pve/iso", "nfs"}, {"/srv/team share", "cifs"}, {"/mnt/smb3", "smb3"},
	}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("mounts = %+v, want %+v", got, want)
	}
	for _, m := range got {
		for _, source := range []string{"nas-a", "nas-b", "192.0.2.10", "198.51.100.7", "export", "volume1"} {
			if strings.Contains(m.Mountpoint+m.FSType, source) {
				t.Errorf("mount %+v carries its source %q", m, source)
			}
		}
	}
}

func TestShareMountsAreReadFromTheMountTable(t *testing.T) {
	old := mountinfoPath
	t.Cleanup(func() { mountinfoPath = old })
	mountinfoPath = filepath.Join(t.TempDir(), "mountinfo")
	if _, err := NetMounts(); err == nil {
		t.Error("a missing mount table read without error")
	}
	if err := os.WriteFile(mountinfoPath, []byte(mountinfoFixture), 0o600); err != nil {
		t.Fatal(err)
	}
	got, err := NetMounts()
	if err != nil || len(got) != 4 {
		t.Errorf("mounts %+v, err %v: want the four shares", got, err)
	}
}
