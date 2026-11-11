// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build windows

package credentials

import (
	"fmt"
	"io"
	"os"
	"unsafe"

	"golang.org/x/sys/windows"
)

// The well-known SIDs of LocalSystem and of the built-in Administrators group.
const (
	systemSID         = "S-1-5-18"
	administratorsSID = "S-1-5-32-544"
)

// readPrivate reads the file at path if SYSTEM or the Administrators own it and its DACL grants
// access to them alone; a deny entry is fine, it only takes rights away. It opens the file without
// following a reparse point and checks the open handle, so a swap between the check and the read
// does not count.
func readPrivate(path string) ([]byte, error) {
	name, err := windows.UTF16PtrFromString(path)
	if err != nil {
		return nil, err
	}
	h, err := windows.CreateFile(name, windows.GENERIC_READ|windows.READ_CONTROL,
		windows.FILE_SHARE_READ, nil, windows.OPEN_EXISTING, windows.FILE_FLAG_OPEN_REPARSE_POINT, 0)
	if err != nil {
		// A PathError keeps errors.Is(err, fs.ErrNotExist) working for a missing file.
		return nil, &os.PathError{Op: "open", Path: path, Err: err}
	}
	f := os.NewFile(uintptr(h), path)
	defer f.Close()
	var info windows.ByHandleFileInformation
	if err := windows.GetFileInformationByHandle(h, &info); err != nil {
		return nil, &os.PathError{Op: "stat", Path: path, Err: err}
	}
	if info.FileAttributes&(windows.FILE_ATTRIBUTE_REPARSE_POINT|windows.FILE_ATTRIBUTE_DIRECTORY) != 0 {
		return nil, fmt.Errorf("%s is no regular file", path)
	}
	if err := checkPrivate(h, path); err != nil {
		return nil, err
	}
	data, err := io.ReadAll(io.LimitReader(f, maxFileBytes+1))
	if err != nil {
		return nil, &os.PathError{Op: "read", Path: path, Err: err}
	}
	if len(data) > maxFileBytes {
		return nil, fmt.Errorf("%s is larger than %d bytes", path, maxFileBytes)
	}
	return data, nil
}

// checkPrivate returns an error unless SYSTEM or the Administrators own the file h and its DACL
// allows access to them alone.
func checkPrivate(h windows.Handle, path string) error {
	sd, err := windows.GetSecurityInfo(h, windows.SE_FILE_OBJECT,
		windows.OWNER_SECURITY_INFORMATION|windows.DACL_SECURITY_INFORMATION)
	if err != nil {
		return fmt.Errorf("read the security of %s: %w", path, err)
	}
	owner, _, err := sd.Owner()
	if err != nil {
		return fmt.Errorf("read the owner of %s: %w", path, err)
	}
	if sid := owner.String(); sid != systemSID && sid != administratorsSID {
		return fmt.Errorf("%s is owned by %q, not by SYSTEM or the Administrators", path, sid)
	}
	dacl, _, err := sd.DACL()
	if err != nil || !daclPrivate(dacl) {
		return fmt.Errorf("%s is open to other accounts; the agent uses no credential from it until only SYSTEM and the Administrators have access", path)
	}
	return nil
}

// daclPrivate reports whether dacl allows access to SYSTEM and the Administrators alone. No DACL
// (a null DACL grants everyone everything) and an ACE type it cannot read as a plain allow or deny
// count as open.
func daclPrivate(dacl *windows.ACL) bool {
	if dacl == nil {
		return false
	}
	for i := range uint32(dacl.AceCount) {
		var ace *windows.ACCESS_ALLOWED_ACE
		if err := windows.GetAce(dacl, i, &ace); err != nil {
			return false
		}
		switch ace.Header.AceType {
		case windows.ACCESS_ALLOWED_ACE_TYPE:
			sid := (*windows.SID)(unsafe.Pointer(&ace.SidStart)).String()
			if sid != systemSID && sid != administratorsSID {
				return false
			}
		case windows.ACCESS_DENIED_ACE_TYPE:
		default:
			return false
		}
	}
	return true
}
