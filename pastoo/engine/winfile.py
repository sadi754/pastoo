"""What the backup needs from Windows beyond os (ctypes only, like the rest of the engine):

usn(path)        the file's number in the NTFS change journal. It moves on every change to the
                 file - also when a program puts the file's date back afterwards, as VeraCrypt
                 does with its containers - and reading the file leaves it alone. None where
                 there is no journal (FAT, exFAT, network drives).
open_read(path)  the file, opened for reading only while no other program is writing to it (a
                 mounted VeraCrypt container, an open Outlook .pst ...); raises InUse otherwise.
                 While it is open, nobody else can start writing to it either.
"""
import ctypes
import msvcrt
import os
from ctypes import wintypes

_k32 = ctypes.WinDLL("kernel32", use_last_error=True)
_k32.CreateFileW.restype = wintypes.HANDLE
_k32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
                             wintypes.DWORD, wintypes.HANDLE]
_k32.DeviceIoControl.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p,
                                 wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
_k32.CloseHandle.argtypes = [wintypes.HANDLE]

_INVALID = wintypes.HANDLE(-1).value
_GENERIC_READ, _FILE_READ_ATTRIBUTES = 0x80000000, 0x80
_SHARE_READ, _SHARE_WRITE, _SHARE_DELETE = 1, 2, 4
_OPEN_EXISTING = 3
_FLAG_BACKUP_SEMANTICS, _FLAG_SEQUENTIAL_SCAN = 0x02000000, 0x08000000
_FSCTL_READ_FILE_USN_DATA = 0x000900EB
_SHARING_VIOLATION, _LOCK_VIOLATION = 32, 33


class InUse(OSError):
    """Another program has the file open for writing (or has locked it)."""


class _UsnRecord(ctypes.Structure):     # USN_RECORD_V2, up to the fields we read
    _fields_ = [("RecordLength", wintypes.DWORD), ("MajorVersion", wintypes.WORD), ("MinorVersion", wintypes.WORD),
                ("FileReferenceNumber", ctypes.c_ulonglong), ("ParentFileReferenceNumber", ctypes.c_ulonglong),
                ("Usn", ctypes.c_longlong)]


def _long(path):
    """Paths past MAX_PATH need the \\\\?\\ prefix for CreateFileW."""
    path = os.path.abspath(path)
    return "\\\\?\\" + path if len(path) >= 248 and not path.startswith("\\\\") else path


def usn(path):
    h = _k32.CreateFileW(_long(path), _FILE_READ_ATTRIBUTES, _SHARE_READ | _SHARE_WRITE | _SHARE_DELETE, None,
                         _OPEN_EXISTING, _FLAG_BACKUP_SEMANTICS, None)
    if h == _INVALID:
        return None
    try:
        buf = ctypes.create_string_buffer(1024)
        got = wintypes.DWORD()
        if not _k32.DeviceIoControl(h, _FSCTL_READ_FILE_USN_DATA, None, 0, buf, len(buf), ctypes.byref(got), None):
            return None         # no change journal on this drive
        number = _UsnRecord.from_buffer_copy(buf).Usn
        return number or None   # 0: the journal has never seen the file
    finally:
        _k32.CloseHandle(h)


def readable(path):
    """Can open_read() have the file right now? (Opens and closes it, nothing more.)"""
    try:
        open_read(path).close()
        return True
    except FileNotFoundError:
        return True         # gone: the bundle is planned again next time, nothing to hold back
    except OSError:
        return False


def open_read(path):
    h = _k32.CreateFileW(_long(path), _GENERIC_READ, _SHARE_READ | _SHARE_DELETE, None, _OPEN_EXISTING,
                         _FLAG_SEQUENTIAL_SCAN, None)
    if h == _INVALID:
        err = ctypes.get_last_error()
        if err in (_SHARING_VIOLATION, _LOCK_VIOLATION):
            raise InUse(err, "in use by another program", path)
        raise ctypes.WinError(err, f"{ctypes.FormatError(err)}: {path}")
    try:
        fd = msvcrt.open_osfhandle(h, os.O_RDONLY | os.O_BINARY)
    except OSError:
        _k32.CloseHandle(h)
        raise
    return os.fdopen(fd, "rb")
