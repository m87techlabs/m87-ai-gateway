"""Private files on POSIX and Windows, without changing unrelated parent folders."""

import os
from pathlib import Path
import stat


def _unsafe(path: Path) -> bool:
    return path.is_symlink() or bool(
        getattr(path.stat(), "st_file_attributes", 0)
        & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 1024)
    )


def _windows_security(path: Path, *, protect=False):
    import ctypes as c
    from ctypes import wintypes as w

    adv = c.WinDLL("advapi32", use_last_error=True)
    kernel = c.WinDLL("kernel32", use_last_error=True)
    pointer = c.c_void_p
    adv.OpenProcessToken.argtypes = [w.HANDLE, w.DWORD, c.POINTER(w.HANDLE)]
    adv.GetTokenInformation.argtypes = [w.HANDLE, c.c_int, pointer, w.DWORD, c.POINTER(w.DWORD)]
    adv.ConvertSidToStringSidW.argtypes = [pointer, c.POINTER(w.LPWSTR)]
    adv.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [
        w.LPCWSTR,
        w.DWORD,
        c.POINTER(pointer),
        c.POINTER(w.DWORD),
    ]
    adv.SetFileSecurityW.argtypes = [w.LPCWSTR, w.DWORD, pointer]
    adv.GetFileSecurityW.argtypes = [w.LPCWSTR, w.DWORD, pointer, w.DWORD, c.POINTER(w.DWORD)]
    adv.GetSecurityDescriptorDacl.argtypes = [
        pointer,
        c.POINTER(w.BOOL),
        c.POINTER(pointer),
        c.POINTER(w.BOOL),
    ]
    adv.GetAce.argtypes = [pointer, w.DWORD, c.POINTER(pointer)]
    adv.EqualSid.argtypes = [pointer, pointer]
    kernel.GetCurrentProcess.restype = w.HANDLE
    kernel.CloseHandle.argtypes = [w.HANDLE]
    kernel.LocalFree.argtypes = [pointer]
    token = w.HANDLE()
    sid_text = w.LPWSTR()
    descriptor = pointer()

    def require(ok):
        if not ok:
            raise ValueError("Windows private storage ACL operation failed")

    try:
        require(adv.OpenProcessToken(kernel.GetCurrentProcess(), 8, c.byref(token)))
        needed = w.DWORD()
        adv.GetTokenInformation(token, 1, None, 0, c.byref(needed))
        info = c.create_string_buffer(needed.value)
        require(adv.GetTokenInformation(token, 1, info, needed, c.byref(needed)))
        sid = c.cast(info, c.POINTER(pointer))[0]
        if protect:
            require(adv.ConvertSidToStringSidW(sid, c.byref(sid_text)))
            inheritance = "OICI" if path.is_dir() else ""
            sddl = f"D:P(A;{inheritance};FA;;;{sid_text.value})"
            require(
                adv.ConvertStringSecurityDescriptorToSecurityDescriptorW(
                    sddl, 1, c.byref(descriptor), None
                )
            )
            require(adv.SetFileSecurityW(str(path), 0x80000004, descriptor))
        else:
            size = w.DWORD()
            adv.GetFileSecurityW(str(path), 4, None, 0, c.byref(size))
            security = c.create_string_buffer(size.value)
            require(adv.GetFileSecurityW(str(path), 4, security, size, c.byref(size)))
            present, defaulted, acl = w.BOOL(), w.BOOL(), pointer()
            require(
                adv.GetSecurityDescriptorDacl(
                    security, c.byref(present), c.byref(acl), c.byref(defaulted)
                )
            )
            if not present.value or not acl.value:
                raise ValueError("Private storage must be owner-only")
            # ACL header: revision, reserved, size (WORD), ACE count (WORD), reserved.
            count = c.c_ushort.from_address(acl.value + 4).value
            if count == 0:
                raise ValueError("Private storage must be owner-only")
            for index in range(count):
                ace = pointer()
                require(adv.GetAce(acl, index, c.byref(ace)))
                # Only an allowed ACE for this user is accepted. SID starts after header/mask.
                if c.c_ubyte.from_address(ace.value).value != 0 or not adv.EqualSid(
                    ace.value + 8, sid
                ):
                    raise ValueError("Private storage must be owner-only")
    finally:
        if descriptor.value:
            kernel.LocalFree(descriptor)
        if sid_text:
            kernel.LocalFree(c.cast(sid_text, pointer))
        if token:
            kernel.CloseHandle(token)


def check_private(path: Path):
    if _unsafe(path):
        raise ValueError("Private storage cannot be a symlink or reparse point")
    if os.name == "nt":
        _windows_security(path)
    elif stat.S_IMODE(path.stat().st_mode) & 0o077:
        raise ValueError("Private storage must be owner-only")


def protect(path: Path):
    if _unsafe(path):
        raise ValueError("Private storage cannot be a symlink or reparse point")
    if os.name == "nt":
        _windows_security(path, protect=True)
    else:
        path.chmod(0o700 if path.is_dir() else 0o600)


def prepare_directory(path: Path):
    if path.exists():
        if not path.is_dir():
            raise ValueError("Private storage directory is unsafe")
        check_private(path)
        return
    path.mkdir(parents=True, mode=0o700)
    protect(path)


def prepare_file(path: Path):
    prepare_directory(path.parent)
    if path.is_symlink():
        raise ValueError("Private storage file cannot be a symlink")
    if path.exists():
        if not path.is_file():
            raise ValueError("Private storage file is unsafe")
        check_private(path)
        return
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(descriptor)
    protect(path)
