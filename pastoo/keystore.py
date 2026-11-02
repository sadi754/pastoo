"""The files.ir key in Windows Credential Manager ("Windows Credentials" ->
Pastoo/files.ir), through the Win32 API - no extra packages, so the
command line (backup.bat, system Python) can read it too.
"""
import ctypes
from ctypes import wintypes

TARGET = "Pastoo/files.ir"
_CRED_TYPE_GENERIC = 1
_CRED_PERSIST_LOCAL_MACHINE = 2
_ERROR_NOT_FOUND = 1168


class _CREDENTIAL(ctypes.Structure):
    _fields_ = [("Flags", wintypes.DWORD), ("Type", wintypes.DWORD), ("TargetName", wintypes.LPWSTR),
                ("Comment", wintypes.LPWSTR), ("LastWritten", wintypes.FILETIME),
                ("CredentialBlobSize", wintypes.DWORD), ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
                ("Persist", wintypes.DWORD), ("AttributeCount", wintypes.DWORD), ("Attributes", ctypes.c_void_p),
                ("TargetAlias", wintypes.LPWSTR), ("UserName", wintypes.LPWSTR)]


_advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
_advapi32.CredReadW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                ctypes.POINTER(ctypes.POINTER(_CREDENTIAL))]
_advapi32.CredWriteW.argtypes = [ctypes.POINTER(_CREDENTIAL), wintypes.DWORD]
_advapi32.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
_advapi32.CredFree.argtypes = [ctypes.c_void_p]


def read(target=TARGET):
    """The stored secret, or None."""
    pcred = ctypes.POINTER(_CREDENTIAL)()
    if not _advapi32.CredReadW(target, _CRED_TYPE_GENERIC, 0, ctypes.byref(pcred)):
        if ctypes.get_last_error() == _ERROR_NOT_FOUND:
            return None
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        cred = pcred.contents
        return bytes(cred.CredentialBlob[:cred.CredentialBlobSize]).decode("utf8")
    finally:
        _advapi32.CredFree(pcred)


def write(secret, target=TARGET, comment="Pastoo - files.ir developer API key"):
    blob = secret.encode("utf8")
    buffer = (ctypes.c_ubyte * len(blob)).from_buffer_copy(blob)
    cred = _CREDENTIAL(Type=_CRED_TYPE_GENERIC, TargetName=target, Comment=comment,
                       CredentialBlobSize=len(blob), CredentialBlob=ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)),
                       Persist=_CRED_PERSIST_LOCAL_MACHINE, UserName="Pastoo")
    if not _advapi32.CredWriteW(ctypes.byref(cred), 0):
        raise ctypes.WinError(ctypes.get_last_error())


def delete(target=TARGET):
    if not _advapi32.CredDeleteW(target, _CRED_TYPE_GENERIC, 0) and ctypes.get_last_error() != _ERROR_NOT_FOUND:
        raise ctypes.WinError(ctypes.get_last_error())


def files_ir_key():
    return read()

