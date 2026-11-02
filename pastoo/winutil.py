"""Small Windows helpers (Win32 API via ctypes) - the ones NetMon's winutil has that this app needs."""
import ctypes
import os
from ctypes import wintypes

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

_WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
_user32.EnumWindows.argtypes = [_WNDENUMPROC, wintypes.LPARAM]
_user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
_user32.IsWindowVisible.argtypes = [wintypes.HWND]
_user32.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
_user32.GetWindow.restype = wintypes.HWND
_user32.IsIconic.argtypes = [wintypes.HWND]
_user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
_user32.SetForegroundWindow.argtypes = [wintypes.HWND]
_user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
_user32.SendMessageW.restype = wintypes.LPARAM
_user32.CreateIconFromResourceEx.argtypes = [
    ctypes.c_char_p, wintypes.DWORD, wintypes.BOOL, wintypes.DWORD, ctypes.c_int, ctypes.c_int, wintypes.UINT]
_user32.CreateIconFromResourceEx.restype = wintypes.HICON
_kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
_kernel32.CreateMutexW.restype = wintypes.HANDLE


class _PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("th32ProcessID", wintypes.DWORD),
                ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", wintypes.DWORD),
                ("cntThreads", wintypes.DWORD), ("th32ParentProcessID", wintypes.DWORD),
                ("pcPriClassBase", ctypes.c_long), ("dwFlags", wintypes.DWORD),
                ("szExeFile", wintypes.WCHAR * 260)]


_kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
_kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
_kernel32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(_PROCESSENTRY32W)]
_kernel32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(_PROCESSENTRY32W)]
_kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

_ERROR_ALREADY_EXISTS = 183
_TH32CS_SNAPPROCESS = 0x2
_INVALID_HANDLE = wintypes.HANDLE(-1).value
_GW_OWNER = 4
_WM_SYSCOMMAND = 0x0112
_SC_RESTORE = 0xF120
_WM_SETICON = 0x0080
_SM_CXICON = 11
_SM_CXSMICON = 49

_instance_mutex = None


def claim_single_instance(name="Local\\Pastoo"):
    """True if we are the only Pastoo app running; the claim lasts until we exit."""
    global _instance_mutex
    _instance_mutex = _kernel32.CreateMutexW(None, False, name + os.environ.get("PASTOO_INSTANCE", ""))
    return ctypes.get_last_error() != _ERROR_ALREADY_EXISTS


def enable_dpi_awareness():
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # per-monitor aware
    except OSError:
        pass


def set_app_id(app_id="Pastoo"):
    """Own taskbar button and notification name instead of Python's."""
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_id)


def allow_any_foreground():
    _user32.AllowSetForegroundWindow(-1)  # ASFW_ANY


def small_icon_size():
    return _user32.GetSystemMetrics(_SM_CXSMICON)


def big_icon_size():
    return _user32.GetSystemMetrics(_SM_CXICON)


def process_tree(pid):
    """pid and all its descendants. A venv's python.exe only starts the real Python as a child."""
    snapshot = _kernel32.CreateToolhelp32Snapshot(_TH32CS_SNAPPROCESS, 0)
    if snapshot == _INVALID_HANDLE:
        return {pid}
    children = {}
    try:
        entry = _PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(entry)
        ok = _kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
        while ok:
            children.setdefault(entry.th32ParentProcessID, []).append(entry.th32ProcessID)
            ok = _kernel32.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        _kernel32.CloseHandle(snapshot)
    tree, todo = set(), [pid]
    while todo:
        p = todo.pop()
        if p not in tree:
            tree.add(p)
            todo.extend(children.get(p, ()))
    return tree


def windows_of(pid):
    """Visible top-level windows that belong to a process or one of its children."""
    pids = process_tree(pid)
    found = []

    @_WNDENUMPROC
    def check(hwnd, _):
        owner = wintypes.DWORD()
        _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value in pids and _user32.IsWindowVisible(hwnd) and not _user32.GetWindow(hwnd, _GW_OWNER):
            found.append(hwnd)
        return True

    _user32.EnumWindows(check, 0)
    return found


def bring_to_front(hwnd):
    if _user32.IsIconic(hwnd):
        # what a taskbar click does; ShowWindow(SW_RESTORE) from another process often leaves WebView2 unpainted
        _user32.PostMessageW(hwnd, _WM_SYSCOMMAND, _SC_RESTORE, 0)
    _user32.SetForegroundWindow(hwnd)


def style_dark_window(hwnd, caption_rgb):
    """Dark title bar (Windows 10/11) and a caption colour matching the app (Windows 11)."""
    dwmapi = ctypes.windll.dwmapi
    dark = ctypes.c_int(1)
    dwmapi.DwmSetWindowAttribute(wintypes.HWND(hwnd), 20, ctypes.byref(dark), 4)
    r, g, b = caption_rgb
    colour = wintypes.DWORD(r | g << 8 | b << 16)  # COLORREF is 0x00BBGGRR
    dwmapi.DwmSetWindowAttribute(wintypes.HWND(hwnd), 35, ctypes.byref(colour), 4)


def icon_from_png(png, size):
    """PNG bytes -> a Windows icon handle (HICON), without touching the disk."""
    hicon = _user32.CreateIconFromResourceEx(png, len(png), True, 0x00030000, size, size, 0)
    if not hicon:
        raise ctypes.WinError(ctypes.get_last_error())
    return hicon


def set_window_icon(hwnd, small, big):
    _user32.SendMessageW(hwnd, _WM_SETICON, 0, small)  # title bar
    _user32.SendMessageW(hwnd, _WM_SETICON, 1, big)    # taskbar, Alt+Tab
