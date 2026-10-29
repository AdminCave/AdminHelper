// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build windows

package config

import (
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"runtime"
	"unsafe"

	"golang.org/x/sys/windows"
)

// protectedSDDL is the descriptor of a directory EnsureSecureDir creates, or locks if
// it was closed: owned by the Administrators, full control for SYSTEM and the
// Administrators, passed on to everything below, and protected (P), so that nothing is
// inherited.
const protectedSDDL = "O:BAD:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)"

// removalSDDL is the descriptor a directory or file gets while the agent removes it,
// and a kept directory that was open while the agent cleans it: owned by the
// Administrators, full control for SYSTEM and the Administrators, not passed on (no
// OICI). If the removal or the cleaning stops halfway, what is left does not carry the
// inheritable form, so the next run does not take it for a closed directory.
const removalSDDL = "O:BAD:P(A;;FA;;;SY)(A;;FA;;;BA)"

// The inherited form of the protected DACL, as it looks on an entry below a protected
// directory: not protected, auto-inherited (AI), one inherited (ID) ACE each for
// SYSTEM and the Administrators. A kept entry is set to this form the moment it is
// unlocked, never to an empty DACL, so that a run cut short between two steps leaves
// no entry the next run cannot open. A directory carries the inheritance on (OICI); a
// file does not.
const (
	inheritedDirSDDL  = "D:AI(A;OICIID;FA;;;SY)(A;OICIID;FA;;;BA)"
	inheritedFileSDDL = "D:AI(A;ID;FA;;;SY)(A;ID;FA;;;BA)"
)

// The access EnsureSecureDir asks for: on a directory it keeps and enumerates, on a
// file it removes, and on a directory it removes. Backup and restore intent
// (FILE_OPEN_FOR_BACKUP_INTENT with the two privileges) grant these regardless of the
// entry's DACL, so an Owner-Rights ACE or an empty DACL cannot keep the agent out.
const (
	keepAccess = windows.READ_CONTROL | windows.WRITE_DAC | windows.WRITE_OWNER |
		windows.FILE_LIST_DIRECTORY | windows.FILE_READ_ATTRIBUTES | windows.SYNCHRONIZE
	fileRemoveAccess = windows.DELETE | windows.FILE_WRITE_ATTRIBUTES | windows.FILE_READ_ATTRIBUTES
	dirRemoveAccess  = windows.FILE_LIST_DIRECTORY | windows.FILE_READ_ATTRIBUTES |
		windows.FILE_WRITE_ATTRIBUTES | windows.DELETE | windows.SYNCHRONIZE
)

// writeOrCreateMask is the set of rights that let a principal add to or change a
// directory or a file. A directory is "closed" only if it already belonged to SYSTEM
// or the Administrators, its DACL grants none of these to anyone else, and it carries
// the inheritable (OICI) entries for both, as the agent and the former SecureDir set
// them.
const writeOrCreateMask = windows.FILE_WRITE_DATA | windows.FILE_APPEND_DATA | windows.FILE_WRITE_EA |
	windows.FILE_WRITE_ATTRIBUTES | windows.DELETE | windows.WRITE_DAC | windows.WRITE_OWNER |
	windows.GENERIC_WRITE | windows.GENERIC_ALL

// privileges is the set EnsureSecureDir enables in the thread token before it touches
// an existing tree: take ownership (to become the owner of a foreign entry), and
// backup and restore (to read and write an entry's security and to delete it
// regardless of its DACL). LocalSystem holds all three, disabled by default.
var privileges = []string{"SeTakeOwnershipPrivilege", "SeBackupPrivilege", "SeRestorePrivilege"}

// ownerLookup returns the owner, as a SID string, of the entry open as h at path.
type ownerLookup func(h windows.Handle, path string) (string, error)

// descriptors holds the fixed descriptors EnsureSecureDir reuses across a run.
type descriptors struct {
	protected     *windows.SECURITY_DESCRIPTOR
	removal       *windows.SECURITY_DESCRIPTOR
	inheritedDir  *windows.SECURITY_DESCRIPTOR
	inheritedFile *windows.SECURITY_DESCRIPTOR
}

// fileBasicInfo mirrors the Win32 FILE_BASIC_INFO, for clearing the read-only
// attribute through SetFileInformationByHandle on the delete fall-back path.
type fileBasicInfo struct {
	CreationTime   int64
	LastAccessTime int64
	LastWriteTime  int64
	ChangeTime     int64
	FileAttributes uint32
	_              uint32
}

// EnsureSecureDir creates dir, and every missing parent, in one step with the
// descriptor protectedSDDL. Mode bits mean nothing to Windows ACLs, and a directory
// created without a descriptor inherits the %ProgramData% ACL, which lets any local
// user read it.
//
// An existing dir is handled through handles that never follow a reparse point: dir
// and each of its entries are opened, as often as a step needs, relative to a handle
// of their parent, never by path. If dir is gone by then, it is created anew; if it
// is back when that is tried, EnsureSecureDir fails. It is kept if it is a directory that SYSTEM or the Administrators own and not a reparse
// point. It is locked first (owner Administrators, protected DACL, no propagation; the
// DACL is in the inheritable form only if dir was closed, so that a run cut short
// leaves an open directory open), then its tree is cleaned: a reparse point, a file
// with a second name and, unless the directory was closed, an entry that neither
// SYSTEM nor the Administrators own are removed; a kept directory that another account
// owns is taken over (owner Administrators) and, because its former owner could set
// its DACL, cleaned as an open directory. A kept entry is unlocked into the inherited form of the protected DACL at
// once. Last, dir's DACL is set once more, with propagation. Any other existing dir is
// removed and created anew; every level to be removed is taken over first (owner
// Administrators, a DACL for SYSTEM and the Administrators that is not passed on, no
// propagation, for itself only), then enumerated,
// and deleted with POSIX semantics, the read-only attribute ignored, like Go's
// internal/syscall/windows.Deleteat, with a fall back to the plain disposition. If a
// step fails, EnsureSecureDir returns the error (fail closed), except where a step on
// an entry below dir no longer finds that entry (isGone): that entry counts as removed.
//
// The directories above dir are not checked: a caller secures the data root before a
// directory in it (EnsureDataDir).
func EnsureSecureDir(dir string) error {
	return ensureSecureDir(dir, handleOwner)
}

// EnsureDataDir is EnsureSecureDir for a directory of the agent's data. EnsureSecureDir
// opens the directory above dir by path, so a dir below the data root (MonitorDir,
// which holds frp, logs and identity) is secured only after the root, in the same run:
// the root's tree is clean then, and only SYSTEM and the Administrators can add to it.
// A dir outside the root (an ADMINHELPER_*_DIR override) is secured alone.
func EnsureDataDir(dir string) error {
	root := MonitorDir()
	if rel, err := filepath.Rel(root, dir); err == nil && rel != "." && filepath.IsLocal(rel) {
		if err := EnsureSecureDir(root); err != nil {
			return err
		}
	}
	return EnsureSecureDir(dir)
}

// EnsureLogDir creates the log directory with EnsureDataDir before the logger opens
// it: the logger would create it, and the data root above it, with the inherited
// %ProgramData% ACL.
func EnsureLogDir() error {
	return EnsureDataDir(LogDir())
}

// ensureSecureDir is EnsureSecureDir with the owner lookup as a parameter, so that a
// test can name an owner the test account cannot set.
func ensureSecureDir(dir string, ownerOf ownerLookup) error {
	dir = filepath.Clean(dir)
	d, err := newDescriptors()
	if err != nil {
		return err
	}
	err = createSecureDir(dir, d.protected)
	if !errors.Is(err, windows.ERROR_ALREADY_EXISTS) {
		return err
	}
	var recreate bool
	err = withPrivileges(func() error {
		var err error
		recreate, err = secureExisting(dir, d, ownerOf)
		return err
	})
	if err != nil || !recreate {
		return err
	}
	// ERROR_ALREADY_EXISTS here means dir came back in the meantime: an error.
	return createSecureDir(dir, d.protected)
}

// newDescriptors parses the fixed descriptors once.
func newDescriptors() (descriptors, error) {
	var d descriptors
	for _, p := range []struct {
		sddl string
		dst  **windows.SECURITY_DESCRIPTOR
	}{
		{protectedSDDL, &d.protected},
		{removalSDDL, &d.removal},
		{inheritedDirSDDL, &d.inheritedDir},
		{inheritedFileSDDL, &d.inheritedFile},
	} {
		sd, err := windows.SecurityDescriptorFromString(p.sddl)
		if err != nil {
			return d, err
		}
		*p.dst = sd
	}
	return d, nil
}

// secureExisting keeps and secures the existing dir, or removes it and reports that
// it has to be created anew.
func secureExisting(dir string, d descriptors, ownerOf ownerLookup) (bool, error) {
	parent, err := openDir(filepath.Dir(dir))
	if err != nil {
		return false, err
	}
	defer windows.CloseHandle(parent)
	name := filepath.Base(dir)

	e, err := classifyAt(parent, name, dir, ownerOf)
	if err != nil {
		return false, err
	}
	if e.gone {
		// Nothing to keep: create dir anew rather than report a directory that is
		// not there.
		return true, nil
	}
	if e.reparse || !e.trusted {
		return true, removeEntry(parent, name, dir, d)
	}
	if !e.isDir {
		return false, fmt.Errorf("%s is not a directory", dir)
	}
	// Lock before opening with keepAccess, so that the open does not depend on the
	// DACL the directory had; the density was read from that DACL before the lock.
	if err := lockEntry(parent, name, dir, windows.FILE_DIRECTORY_FILE, d.lockFor(e.closed)); err != nil {
		return false, err
	}
	h, err := openAt(parent, name, dir, keepAccess, windows.FILE_DIRECTORY_FILE)
	if err != nil {
		return false, err
	}
	defer windows.CloseHandle(h)
	if err := cleanChildren(h, dir, e.closed, d, ownerOf); err != nil {
		return false, err
	}
	admins, _, err := d.protected.Owner()
	if err != nil {
		return false, err
	}
	dacl, _, err := d.protected.DACL()
	if err != nil {
		return false, err
	}
	// Last, after the tree is clean: set the DACL with propagation. No reparse point
	// is left in the tree, so this does not reach beyond it.
	if err := windows.SetSecurityInfo(h, windows.SE_FILE_OBJECT,
		windows.OWNER_SECURITY_INFORMATION|windows.DACL_SECURITY_INFORMATION|windows.PROTECTED_DACL_SECURITY_INFORMATION,
		admins, nil, dacl, nil); err != nil {
		return false, fmt.Errorf("set the owner and the ACL of %s: %w", dir, err)
	}
	return false, nil
}

// cleanChildren cleans every entry of the kept directory open as h, which is already
// locked. closed says whether h, before any change, already belonged to SYSTEM or the
// Administrators and granted the rights to add or write only to them.
func cleanChildren(h windows.Handle, path string, closed bool, d descriptors, ownerOf ownerLookup) error {
	names, err := readNames(h, path)
	if err != nil {
		return err
	}
	for _, n := range names {
		if err := cleanChild(h, n, filepath.Join(path, n), closed, d, ownerOf); err != nil {
			return err
		}
	}
	return nil
}

// cleanChild handles the entry name of the kept directory parent, cleaned on the
// strength of parent's state before any change: parentClosed is true if parent
// already belonged to SYSTEM or the Administrators and granted the rights to add or
// write only to them. A reparse point and a file with a second name are removed. An
// entry another account owns is removed unless parent was closed, in which case it is
// taken over (owner Administrators) and kept. A kept directory is cleaned the same
// way, but as an open one if it was only just taken over, since its former owner
// could set its DACL. A kept entry ends with the inherited form of the DACL. An entry
// that a step no longer finds counts as removed (isGone); an entry below it that a
// step no longer finds has already been handled at its own level, so such an error
// that reaches the end here concerns name itself.
func cleanChild(parent windows.Handle, name, path string, parentClosed bool, d descriptors, ownerOf ownerLookup) (err error) {
	defer func() {
		if isGone(err) {
			err = nil
		}
	}()
	e, err := classifyAt(parent, name, path, ownerOf)
	if err != nil {
		return err
	}
	if e.gone {
		return nil
	}
	if e.reparse || e.secondName || (!e.trusted && !parentClosed) {
		return removeEntry(parent, name, path, d)
	}
	options := uint32(windows.FILE_NON_DIRECTORY_FILE)
	if e.isDir {
		options = windows.FILE_DIRECTORY_FILE
	}
	if !e.trusted {
		if err := takeOwner(parent, name, path, options, d.protected); err != nil {
			return err
		}
	}
	if !e.isDir {
		return resetDACL(parent, name, path, windows.FILE_NON_DIRECTORY_FILE, d.inheritedFile)
	}
	// A directory only just taken over is treated as open: its former owner could
	// have set a DACL that looks closed.
	closed := e.trusted && e.closed
	if err := lockEntry(parent, name, path, windows.FILE_DIRECTORY_FILE, d.lockFor(closed)); err != nil {
		return err
	}
	dh, err := openAt(parent, name, path, keepAccess, windows.FILE_DIRECTORY_FILE)
	if err != nil {
		return err
	}
	defer windows.CloseHandle(dh)
	if err := cleanChildren(dh, path, closed, d, ownerOf); err != nil {
		return err
	}
	// Unlock into the inherited form at once; parent's final propagation then makes
	// the inheritance real.
	if err := windows.SetKernelObjectSecurity(dh,
		windows.DACL_SECURITY_INFORMATION|windows.UNPROTECTED_DACL_SECURITY_INFORMATION, d.inheritedDir); err != nil {
		return fmt.Errorf("reset the ACL of %s: %w", path, err)
	}
	return nil
}

// takeOwner makes the Administrators the owner of the entry name of parent, through a
// handle that asks for WRITE_OWNER only (granted by SeTakeOwnershipPrivilege).
func takeOwner(parent windows.Handle, name, path string, options uint32, protected *windows.SECURITY_DESCRIPTOR) error {
	h, err := openAt(parent, name, path, windows.WRITE_OWNER, options)
	if err != nil {
		return err
	}
	defer windows.CloseHandle(h)
	if err := windows.SetKernelObjectSecurity(h, windows.OWNER_SECURITY_INFORMATION, protected); err != nil {
		return fmt.Errorf("make the Administrators own %s: %w", path, err)
	}
	return nil
}

// resetDACL gives the entry name of parent the descriptor sd's DACL, unprotected, so
// that it keeps only what it inherits. Its content stays.
func resetDACL(parent windows.Handle, name, path string, options uint32, sd *windows.SECURITY_DESCRIPTOR) error {
	h, err := openAt(parent, name, path, windows.WRITE_DAC, options)
	if err != nil {
		return err
	}
	defer windows.CloseHandle(h)
	if err := windows.SetKernelObjectSecurity(h,
		windows.DACL_SECURITY_INFORMATION|windows.UNPROTECTED_DACL_SECURITY_INFORMATION, sd); err != nil {
		return fmt.Errorf("reset the ACL of %s: %w", path, err)
	}
	return nil
}

// lockFor returns the descriptor a kept directory is locked with while its entries are
// cleaned: the protected one if it was closed, the removal one if it was open. A run
// cut short after the lock so leaves the directory as closed or as open as it was.
func (d descriptors) lockFor(closed bool) *windows.SECURITY_DESCRIPTOR {
	if closed {
		return d.protected
	}
	return d.removal
}

// lockEntry makes the Administrators the owner of the entry name of parent and gives
// it sd's DACL, protected, each through its own handle, without propagation. sd is the
// descriptor from lockFor for a directory the agent keeps and the removal descriptor
// for one it removes.
func lockEntry(parent windows.Handle, name, path string, options uint32, sd *windows.SECURITY_DESCRIPTOR) error {
	if err := takeOwner(parent, name, path, options, sd); err != nil {
		return err
	}
	h, err := openAt(parent, name, path, windows.WRITE_DAC, options)
	if err != nil {
		return err
	}
	defer windows.CloseHandle(h)
	if err := windows.SetKernelObjectSecurity(h,
		windows.DACL_SECURITY_INFORMATION|windows.PROTECTED_DACL_SECURITY_INFORMATION, sd); err != nil {
		return fmt.Errorf("lock the ACL of %s: %w", path, err)
	}
	return nil
}

// removeEntry removes the entry name of the directory parent and everything below it.
// It never follows a reparse point; it removes the reparse point itself.
func removeEntry(parent windows.Handle, name, path string, d descriptors) error {
	h, err := openAt(parent, name, path, fileRemoveAccess, windows.FILE_NON_DIRECTORY_FILE)
	if errors.Is(err, windows.STATUS_ACCESS_DENIED) {
		// A read-only file whose own DACL denies the write-attributes the delete
		// needs: take it over, unless it has a second name (whose descriptor would
		// change with it).
		info, e := statAt(parent, name, path)
		if e != nil {
			return e
		}
		if info.NumberOfLinks != 1 {
			return fmt.Errorf("remove %s: a read-only file with more than one name", path)
		}
		if err := lockEntry(parent, name, path, windows.FILE_NON_DIRECTORY_FILE, d.removal); err != nil {
			return err
		}
		h, err = openAt(parent, name, path, fileRemoveAccess, windows.FILE_NON_DIRECTORY_FILE)
	}
	if err == nil {
		defer windows.CloseHandle(h)
		return markDeleted(h, path)
	}
	if !errors.Is(err, windows.STATUS_FILE_IS_A_DIRECTORY) {
		return err
	}
	return removeDir(parent, name, path, d)
}

// removeDir removes the directory name of parent and everything below it. It takes
// the directory over first, without a condition (owner Administrators, the removal
// DACL, which is not passed on, no propagation, for itself only), so that its own
// DACL can no longer keep the agent from deleting its entries; then it enumerates and
// deletes, from the top down. A reparse point is deleted without being entered. An
// entry that its removal no longer finds counts as removed (isGone).
func removeDir(parent windows.Handle, name, path string, d descriptors) error {
	if err := lockEntry(parent, name, path, windows.FILE_DIRECTORY_FILE, d.removal); err != nil {
		return err
	}
	h, err := openAt(parent, name, path, dirRemoveAccess, windows.FILE_DIRECTORY_FILE)
	if err != nil {
		return err
	}
	defer windows.CloseHandle(h)
	var info windows.ByHandleFileInformation
	if err := windows.GetFileInformationByHandle(h, &info); err != nil {
		return &os.PathError{Op: "stat", Path: path, Err: err}
	}
	if info.FileAttributes&windows.FILE_ATTRIBUTE_REPARSE_POINT == 0 {
		names, err := readNames(h, path)
		if err != nil {
			return err
		}
		for _, n := range names {
			if err := removeEntry(h, n, filepath.Join(path, n), d); err != nil && !isGone(err) {
				return err
			}
		}
	}
	return markDeleted(h, path)
}

// isGone reports whether err says that the entry a step works on is no longer there,
// by name or by path. Such an entry below dir counts as removed. An entry about to be
// deleted (STATUS_DELETE_PENDING) does not: it stays until its last handle is closed,
// so the run fails like on an entry held open, and the next run cleans up.
func isGone(err error) bool {
	return errors.Is(err, windows.STATUS_OBJECT_NAME_NOT_FOUND) || errors.Is(err, windows.STATUS_OBJECT_PATH_NOT_FOUND) ||
		errors.Is(err, windows.ERROR_FILE_NOT_FOUND) || errors.Is(err, windows.ERROR_PATH_NOT_FOUND)
}

// markDeleted deletes the entry open as h once h is closed. It asks for POSIX
// semantics first, under which the name goes at once even if another handle to the
// entry is still open, and ignores a read-only attribute. Where Windows or the file
// system has no extended disposition, it falls back to the plain one, clearing a
// read-only attribute first (only on a file with a single name, whose attributes it
// may change).
func markDeleted(h windows.Handle, path string) error {
	flags := uint32(windows.FILE_DISPOSITION_DELETE | windows.FILE_DISPOSITION_FORCE_IMAGE_SECTION_CHECK |
		windows.FILE_DISPOSITION_POSIX_SEMANTICS | windows.FILE_DISPOSITION_IGNORE_READONLY_ATTRIBUTE)
	err := windows.NtSetInformationFile(h, &windows.IO_STATUS_BLOCK{}, (*byte)(unsafe.Pointer(&flags)),
		uint32(unsafe.Sizeof(flags)), windows.FileDispositionInformationEx)
	if errors.Is(err, windows.STATUS_INVALID_INFO_CLASS) || errors.Is(err, windows.STATUS_INVALID_PARAMETER) ||
		errors.Is(err, windows.STATUS_NOT_SUPPORTED) {
		var info windows.ByHandleFileInformation
		if e := windows.GetFileInformationByHandle(h, &info); e == nil &&
			info.FileAttributes&windows.FILE_ATTRIBUTE_READONLY != 0 && info.NumberOfLinks == 1 {
			clearReadOnly(h, info.FileAttributes)
		}
		deleteFile := uint8(1)
		err = windows.NtSetInformationFile(h, &windows.IO_STATUS_BLOCK{}, &deleteFile,
			uint32(unsafe.Sizeof(deleteFile)), windows.FileDispositionInformation)
	}
	if err != nil {
		return &os.PathError{Op: "remove", Path: path, Err: err}
	}
	return nil
}

// clearReadOnly drops the read-only attribute of the entry open as h (best effort, on
// the pre-1809 fall-back path).
func clearReadOnly(h windows.Handle, attrs uint32) {
	attrs &^= windows.FILE_ATTRIBUTE_READONLY
	if attrs == 0 {
		// Zero means "leave the attributes as they are" to FILE_BASIC_INFO.
		attrs = windows.FILE_ATTRIBUTE_NORMAL
	}
	info := fileBasicInfo{FileAttributes: attrs}
	_ = windows.SetFileInformationByHandle(h, windows.FileBasicInfo, (*byte)(unsafe.Pointer(&info)),
		uint32(unsafe.Sizeof(info)))
}

// entry is what classifyAt reports about one directory entry.
type entry struct {
	gone       bool // the name was not there
	reparse    bool
	isDir      bool
	secondName bool // a file with more than one name
	trusted    bool // SYSTEM or the Administrators own it
	closed     bool // trusted directory whose DACL grants add/write only to them
}

// classifyAt opens the entry name of parent for reading, without following a reparse
// point, and reports what the agent needs to decide. A file with a second name shares
// its descriptor with that name, so the agent does not change it. An owner it cannot
// read counts as another account's.
func classifyAt(parent windows.Handle, name, path string, ownerOf ownerLookup) (entry, error) {
	h, hasReadControl, err := openForRead(parent, name, path)
	if errors.Is(err, windows.STATUS_OBJECT_NAME_NOT_FOUND) {
		return entry{gone: true}, nil
	}
	if err != nil {
		return entry{}, err
	}
	defer windows.CloseHandle(h)
	var info windows.ByHandleFileInformation
	if err := windows.GetFileInformationByHandle(h, &info); err != nil {
		return entry{}, &os.PathError{Op: "stat", Path: path, Err: err}
	}
	e := entry{
		reparse:    info.FileAttributes&windows.FILE_ATTRIBUTE_REPARSE_POINT != 0,
		isDir:      info.FileAttributes&windows.FILE_ATTRIBUTE_DIRECTORY != 0,
		secondName: info.FileAttributes&windows.FILE_ATTRIBUTE_DIRECTORY == 0 && info.NumberOfLinks != 1,
	}
	if e.reparse {
		return e, nil
	}
	sid, err := ownerOf(h, path)
	if err != nil {
		// The owner is unreadable, so this is not an entry the agent made.
		return e, nil
	}
	e.trusted = trustedOwner(sid)
	if e.trusted && e.isDir && hasReadControl {
		if dacl, err := handleDACL(h); err == nil {
			e.closed = aclClosed(dacl)
		}
	}
	return e, nil
}

// statAt returns the file information of the entry name of parent, without following a
// reparse point.
func statAt(parent windows.Handle, name, path string) (windows.ByHandleFileInformation, error) {
	var info windows.ByHandleFileInformation
	h, _, err := openForRead(parent, name, path)
	if err != nil {
		return info, err
	}
	defer windows.CloseHandle(h)
	if err := windows.GetFileInformationByHandle(h, &info); err != nil {
		return info, &os.PathError{Op: "stat", Path: path, Err: err}
	}
	return info, nil
}

// aclClosed reports whether the DACL dacl grants the rights to add or write only to
// SYSTEM and the Administrators and carries, for both, an allow ACE in the
// inheritable form (OICI) the agent and the former SecureDir set. It errs towards
// open: a directory with no DACL, one without both inheritable entries (such as the
// removal DACL a stopped removal leaves behind), an allow ACE that grants a write
// right to another SID, and any ACE type it cannot read as a plain allow or deny all
// count as open.
func aclClosed(dacl *windows.ACL) bool {
	if dacl == nil {
		return false
	}
	const inheritable = windows.OBJECT_INHERIT_ACE | windows.CONTAINER_INHERIT_ACE
	var system, admins bool
	for i := range uint32(dacl.AceCount) {
		var ace *windows.ACCESS_ALLOWED_ACE
		if err := windows.GetAce(dacl, i, &ace); err != nil {
			return false
		}
		switch ace.Header.AceType {
		case windows.ACCESS_ALLOWED_ACE_TYPE:
			sid := (*windows.SID)(unsafe.Pointer(&ace.SidStart)).String()
			if sid == systemSID || sid == administratorsSID {
				form := ace.Header.AceFlags&(inheritable|windows.INHERIT_ONLY_ACE) == inheritable
				system = system || (form && sid == systemSID)
				admins = admins || (form && sid == administratorsSID)
				continue
			}
			if uint32(ace.Mask)&writeOrCreateMask != 0 {
				return false
			}
		case windows.ACCESS_DENIED_ACE_TYPE:
			// A deny only takes rights away; it cannot open the directory.
		default:
			// A callback, object or unknown ACE: the layout above may not hold, so
			// do not read it, and do not vouch for the directory.
			return false
		}
	}
	return system && admins
}

// handleDACL returns the DACL of the entry open as h.
func handleDACL(h windows.Handle) (*windows.ACL, error) {
	sd, err := windows.GetSecurityInfo(h, windows.SE_FILE_OBJECT, windows.DACL_SECURITY_INFORMATION)
	if err != nil {
		return nil, err
	}
	dacl, _, err := sd.DACL()
	return dacl, err
}

// handleOwner returns the owner of the entry open as h as a SID string.
func handleOwner(h windows.Handle, _ string) (string, error) {
	sd, err := windows.GetSecurityInfo(h, windows.SE_FILE_OBJECT, windows.OWNER_SECURITY_INFORMATION)
	if err != nil {
		return "", err
	}
	owner, _, err := sd.Owner()
	if err != nil {
		return "", err
	}
	return owner.String(), nil
}

// openForRead opens the entry name of parent to read its attributes, owner and DACL,
// without following a reparse point. It reports whether the handle has READ_CONTROL;
// where the entry's DACL denies it and the privileges do not override it, it falls
// back to the attributes alone.
func openForRead(parent windows.Handle, name, path string) (windows.Handle, bool, error) {
	h, err := openAt(parent, name, path, windows.READ_CONTROL|windows.FILE_READ_ATTRIBUTES, 0)
	if err == nil {
		return h, true, nil
	}
	if !errors.Is(err, windows.STATUS_ACCESS_DENIED) {
		return 0, false, err
	}
	h, err = openAt(parent, name, path, windows.FILE_READ_ATTRIBUTES, 0)
	return h, false, err
}

// openAt opens the entry name of the directory parent with access, plus the create
// options in options. It does not follow a reparse point: if name is one, the handle
// is to the reparse point itself. Backup intent lets the privileges override the
// entry's DACL. A handle with SYNCHRONIZE does synchronous I/O.
func openAt(parent windows.Handle, name, path string, access, options uint32) (windows.Handle, error) {
	objectName, err := windows.NewNTUnicodeString(name)
	if err != nil {
		return 0, err
	}
	oa := windows.OBJECT_ATTRIBUTES{RootDirectory: parent, ObjectName: objectName, Attributes: windows.OBJ_CASE_INSENSITIVE}
	oa.Length = uint32(unsafe.Sizeof(oa))
	if access&windows.SYNCHRONIZE != 0 {
		options |= windows.FILE_SYNCHRONOUS_IO_NONALERT
	}
	var h windows.Handle
	err = windows.NtCreateFile(&h, access, &oa, &windows.IO_STATUS_BLOCK{}, nil, 0,
		windows.FILE_SHARE_READ|windows.FILE_SHARE_WRITE|windows.FILE_SHARE_DELETE, windows.FILE_OPEN,
		windows.FILE_OPEN_REPARSE_POINT|windows.FILE_OPEN_FOR_BACKUP_INTENT|options, 0, 0)
	if err != nil {
		return 0, &os.PathError{Op: "open", Path: path, Err: err}
	}
	return h, nil
}

// openDir opens the directory path, so that its entries can be opened relative to it.
func openDir(path string) (windows.Handle, error) {
	name, err := windows.UTF16PtrFromString(path)
	if err != nil {
		return 0, err
	}
	h, err := windows.CreateFile(name, windows.FILE_LIST_DIRECTORY|windows.SYNCHRONIZE,
		windows.FILE_SHARE_READ|windows.FILE_SHARE_WRITE|windows.FILE_SHARE_DELETE, nil, windows.OPEN_EXISTING,
		windows.FILE_FLAG_BACKUP_SEMANTICS, 0)
	if err != nil {
		return 0, &os.PathError{Op: "open", Path: path, Err: err}
	}
	return h, nil
}

// readNames returns the names of the entries of the directory open as h. It reads
// through a duplicate handle, so that the *os.File it needs can be closed without
// closing h, which the caller keeps using.
func readNames(h windows.Handle, path string) ([]string, error) {
	proc := windows.CurrentProcess()
	var dup windows.Handle
	if err := windows.DuplicateHandle(proc, h, proc, &dup, 0, false, windows.DUPLICATE_SAME_ACCESS); err != nil {
		return nil, &os.PathError{Op: "readdir", Path: path, Err: err}
	}
	f := os.NewFile(uintptr(dup), path)
	defer f.Close()
	return f.Readdirnames(-1)
}

// withPrivileges runs f on a locked OS thread whose token has the take-ownership,
// backup and restore privileges enabled, so that f can read, take over and remove an
// entry whatever its DACL. A token without a privilege still runs f; an access it
// would have granted then fails with access denied.
func withPrivileges(f func() error) error {
	runtime.LockOSThread()
	if err := windows.ImpersonateSelf(windows.SecurityImpersonation); err != nil {
		runtime.UnlockOSThread()
		return fmt.Errorf("impersonate the process token: %w", err)
	}
	defer func() {
		// A thread that still impersonates stays locked, so that it ends with the
		// goroutine and no other goroutine runs with its token.
		if windows.RevertToSelf() == nil {
			runtime.UnlockOSThread()
		}
	}()
	var token windows.Token
	if err := windows.OpenThreadToken(windows.CurrentThread(), windows.TOKEN_ADJUST_PRIVILEGES|windows.TOKEN_QUERY,
		false, &token); err != nil {
		return fmt.Errorf("open the thread token: %w", err)
	}
	defer token.Close()
	for _, name := range privileges {
		enablePrivilege(token, name)
	}
	return f()
}

// enablePrivilege enables the named privilege in token, best effort: a token that does
// not hold it is left as it is, and the caller's access check fails later if it is
// truly needed.
func enablePrivilege(token windows.Token, name string) {
	value, err := windows.UTF16PtrFromString(name)
	if err != nil {
		return
	}
	var tp windows.Tokenprivileges
	tp.PrivilegeCount = 1
	tp.Privileges[0].Attributes = windows.SE_PRIVILEGE_ENABLED
	if err := windows.LookupPrivilegeValue(nil, value, &tp.Privileges[0].Luid); err != nil {
		return
	}
	_ = windows.AdjustTokenPrivileges(token, false, &tp, 0, nil, nil)
}

// createSecureDir creates dir with the descriptor sd, and every missing parent with
// it as well. It fails with ERROR_ALREADY_EXISTS if dir exists.
func createSecureDir(dir string, sd *windows.SECURITY_DESCRIPTOR) error {
	err := mkdirWithDescriptor(dir, sd)
	if !errors.Is(err, windows.ERROR_PATH_NOT_FOUND) {
		return err
	}
	parent := filepath.Dir(dir)
	if parent == dir {
		return err
	}
	if err := createSecureDir(parent, sd); err != nil && !errors.Is(err, windows.ERROR_ALREADY_EXISTS) {
		return err
	}
	return mkdirWithDescriptor(dir, sd)
}

// mkdirWithDescriptor creates the directory dir with the descriptor sd. Its parent
// has to exist.
func mkdirWithDescriptor(dir string, sd *windows.SECURITY_DESCRIPTOR) error {
	name, err := windows.UTF16PtrFromString(dir)
	if err != nil {
		return err
	}
	sa := windows.SecurityAttributes{SecurityDescriptor: sd}
	sa.Length = uint32(unsafe.Sizeof(sa))
	if err := windows.CreateDirectory(name, &sa); err != nil {
		return &os.PathError{Op: "mkdir", Path: dir, Err: err}
	}
	return nil
}

// OwnByAdministrators makes the Administrators the owner of path, a file or directory
// the agent wrote. Who owns a new file depends on the account and on local policy: a
// file an elevated administrator writes can belong to that user, and EnsureSecureDir
// removes a child with such an owner. It does not follow a reparse point: it works on
// a handle opened with FILE_FLAG_OPEN_REPARSE_POINT and returns an error if path is
// one. It runs with the thread privileges EnsureSecureDir uses (withPrivileges): the
// restore privilege lets it set the owner whatever the attributes of the
// Administrators group in the token.
func OwnByAdministrators(path string) error {
	return withPrivileges(func() error { return ownByAdministrators(path) })
}

// ownByAdministrators is OwnByAdministrators without the privileges.
func ownByAdministrators(path string) error {
	name, err := windows.UTF16PtrFromString(path)
	if err != nil {
		return err
	}
	h, err := windows.CreateFile(name, windows.READ_CONTROL|windows.WRITE_OWNER|windows.FILE_READ_ATTRIBUTES,
		windows.FILE_SHARE_READ|windows.FILE_SHARE_WRITE|windows.FILE_SHARE_DELETE, nil, windows.OPEN_EXISTING,
		windows.FILE_FLAG_OPEN_REPARSE_POINT|windows.FILE_FLAG_BACKUP_SEMANTICS, 0)
	if err != nil {
		return &os.PathError{Op: "open", Path: path, Err: err}
	}
	defer windows.CloseHandle(h)
	var info windows.ByHandleFileInformation
	if err := windows.GetFileInformationByHandle(h, &info); err != nil {
		return &os.PathError{Op: "stat", Path: path, Err: err}
	}
	if info.FileAttributes&windows.FILE_ATTRIBUTE_REPARSE_POINT != 0 {
		return fmt.Errorf("%s is a reparse point", path)
	}
	admins, err := windows.CreateWellKnownSid(windows.WinBuiltinAdministratorsSid)
	if err != nil {
		return err
	}
	if err := windows.SetSecurityInfo(h, windows.SE_FILE_OBJECT, windows.OWNER_SECURITY_INFORMATION,
		admins, nil, nil, nil); err != nil {
		return fmt.Errorf("make the Administrators own %s: %w", path, err)
	}
	return nil
}
