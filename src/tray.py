#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🦞 自研托盘组件（ctypes + Shell_NotifyIconW）
图标挂到宿主窗口 HWND（pywebview 主窗口，显示可靠——已实测）；
交互用 SetWindowLongPtrW 钩住宿主窗口 WndProc（捕获 WM_USER+100 回调消息）：
  左键 → on_click；右键 → show_menu（CreatePopupMenu）。
不依赖 pystray（3.14/Win 的 CreateWindow 失败），不用独立消息窗口（消息泵线程绑定问题）。
"""
import ctypes
import os
from ctypes import wintypes

user32 = ctypes.windll.user32
shell32 = ctypes.windll.shell32
kernel32 = ctypes.windll.kernel32

# ---- 64 位句柄/参数必须设置类型，否则默认 int32 截断 ----
user32.SetForegroundWindow.restype = wintypes.BOOL
shell32.Shell_NotifyIconW.restype = wintypes.BOOL
shell32.Shell_NotifyIconW.argtypes = [wintypes.DWORD, ctypes.c_void_p]
user32.DestroyIcon.restype = wintypes.BOOL
user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
user32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
user32.CallWindowProcW.restype = ctypes.c_ssize_t
user32.CallWindowProcW.argtypes = [ctypes.c_void_p, wintypes.HWND, wintypes.UINT,
                                   ctypes.c_ssize_t, ctypes.c_ssize_t]
user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
user32.TrackPopupMenu.restype = ctypes.c_int
user32.TrackPopupMenu.argtypes = [ctypes.c_void_p, wintypes.UINT, ctypes.c_int,
                                  ctypes.c_int, ctypes.c_int, ctypes.c_void_p,
                                  ctypes.c_void_p]
user32.CreatePopupMenu.restype = ctypes.c_void_p
user32.AppendMenuW.restype = wintypes.BOOL
user32.AppendMenuW.argtypes = [ctypes.c_void_p, wintypes.UINT, ctypes.c_void_p,
                               wintypes.LPCWSTR]
user32.GetCursorPos.restype = wintypes.BOOL

GWL_WNDPROC = -4
NIF_MESSAGE = 0x1
NIF_ICON = 0x2
NIF_TIP = 0x4
NIM_ADD = 0x0
NIM_MODIFY = 0x1
NIM_DELETE = 0x2
NIM_SETVERSION = 0x4
WM_USER = 0x400
NOTIFYICON_VERSION_4 = 4
TPM_RIGHTALIGN = 0x0008
TPM_BOTTOMALIGN = 0x0020
TPM_RETURNCMD = 0x0100
WM_LBUTTONUP = 0x0202
WM_RBUTTONUP = 0x0205


class NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("hWnd", wintypes.HWND),
        ("uID", wintypes.UINT),
        ("uFlags", wintypes.UINT),
        ("uCallbackMessage", wintypes.UINT),
        ("hIcon", wintypes.HANDLE),
        ("szTip", wintypes.WCHAR * 128),
        ("dwState", wintypes.DWORD),
        ("dwStateMask", wintypes.DWORD),
        ("szInfo", wintypes.WCHAR * 256),
        ("uTimeoutOrVersion", wintypes.UINT),
        ("szInfoTitle", wintypes.WCHAR * 64),
        ("dwInfoFlags", wintypes.DWORD),
        ("guidItem", ctypes.c_byte * 16),
        ("hBalloonIcon", wintypes.HANDLE),
    ]


_OLD_PROC = None
_PROC_FN = None
_ACTIVE = None   # 活跃 TrayIcon 实例（回调需要）

MSG_ACTION_FROM_MENU = 0x401 + 101   # 毛玻璃菜单动作（与 AcrylicMenu.MSG_ACTION 一致）
_MENU_ITEMS = []                     # 毛玻璃菜单项（主线程按索引提取动作）


def _hook_proc(hwnd, msg, wparam, lparam):
    """宿主窗口替换后的 WndProc：托盘 WM_USER → 执行回调；菜单动作（主线程）→ 执行 fn；其它转发"""
    if msg == MSG_ACTION_FROM_MENU and _ACTIVE:
        # 菜单项点击：在主窗口线程执行（evaluate_js 等安全）
        try:
            idx = int(wparam)
            if 0 <= idx < len(_MENU_ITEMS):
                fn = _MENU_ITEMS[idx][1]
                if callable(fn):
                    fn()
        except Exception:
            pass
    if msg == WM_USER + 100 and _ACTIVE:
        try:
            _ACTIVE._on_lparam(lparam)
        except Exception:
            pass
    if _OLD_PROC:
        return user32.CallWindowProcW(_OLD_PROC, hwnd, msg, wparam, lparam)
    return 0


class TrayIcon:
    def __init__(self, hwnd, icon_path, tip, on_click=None, menu_items=None):
        self.hwnd = int(hwnd)
        self.icon_path = icon_path
        self.tip = tip
        self.on_click = on_click
        self.menu_items = menu_items or []
        self._icon_handle = None
        self._nid = None
        self.UMSG = WM_USER + 100
        self._ok = False
        self._hooked = False
        self._old_proc = None      # 本实例捕获的原 WndProc（destroy 时恢复自己的）

    def _load_icon(self, path):
        hicon = user32.LoadImageW(None, path, 1, 64, 64, 0x10)
        if not hicon:
            hicon = user32.LoadIconW(None, ctypes.c_void_p(32512))
        return hicon

    def _on_lparam(self, lparam):
        """托盘消息回调：版本4时 lparam=鼠标坐标；用 wparam? 简化：直接判断低字事件"""
        try:
            # 用 Shell_NotifyIcon 的 uCallbackMessage 是 WM_USER+100，lparam=事件类型
            # 版本4：lparam 高位=点击坐标，低位=事件代码
            lp = int(lparam)
            ev = lp & 0xFFFF
            if ev in (0x0202, 0x0301):   # WM_LBUTTONUP / NIN_SELECT
                if self.on_click:
                    self.on_click()
            elif ev == 0x0205:           # WM_RBUTTONUP
                self.show_menu()
        except Exception:
            pass

    def _hook(self):
        """替换宿主 WndProc（保存原 proc，转发保持 WinForms 事件流）。
        实例保存自己捕获的旧 proc——多实例/重复创建时各自恢复，不覆盖全局链"""
        global _OLD_PROC, _PROC_FN, _ACTIVE
        if self._hooked:
            return True
        try:
            self._old_proc = user32.GetWindowLongPtrW(self.hwnd, GWL_WNDPROC)
            if not self._old_proc:
                return False
            _PROC_FN = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wintypes.HWND,
                                          wintypes.UINT, ctypes.c_ssize_t,
                                          ctypes.c_ssize_t)(_hook_proc)
            _ACTIVE = self
            _OLD_PROC = self._old_proc
            user32.SetWindowLongPtrW(self.hwnd, GWL_WNDPROC,
                                     ctypes.cast(_PROC_FN, ctypes.c_void_p).value)
            self._hooked = True
            return True
        except Exception:
            return False

    def add(self):
        self._icon_handle = self._load_icon(self.icon_path)
        nid = NOTIFYICONDATAW()
        ctypes.memset(ctypes.byref(nid), 0, ctypes.sizeof(nid))
        nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        nid.hWnd = self.hwnd
        nid.uID = 1
        nid.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
        nid.uCallbackMessage = self.UMSG
        nid.hIcon = self._icon_handle
        nid.szTip = self.tip
        self._nid = nid
        # 先钩 WndProc（消息通道），再添加图标
        self._hook()
        ok = shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(nid))
        self._ok = bool(ok)
        if not ok:
            # NIM_ADD 失败：立即恢复 WndProc（避免悬空钩子泄漏/转发链断裂）
            if self._hooked and self._old_proc:
                try:
                    user32.SetWindowLongPtrW(self.hwnd, GWL_WNDPROC, self._old_proc)
                except Exception:
                    pass
                self._hooked = False
            return False
        if ok:
            nid4 = NOTIFYICONDATAW()
            ctypes.memset(ctypes.byref(nid4), 0, ctypes.sizeof(nid4))
            nid4.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
            nid4.hWnd = self.hwnd
            nid4.uID = 1
            nid4.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
            nid4.uCallbackMessage = self.UMSG
            nid4.hIcon = self._icon_handle
            nid4.szTip = self.tip
            nid4.uTimeoutOrVersion = NOTIFYICON_VERSION_4
            shell32.Shell_NotifyIconW(NIM_SETVERSION, ctypes.byref(nid4))
        return self._ok

    def update_tip(self, tip):
        if not self._ok:
            return
        self.tip = tip
        nid = NOTIFYICONDATAW()
        ctypes.memset(ctypes.byref(nid), 0, ctypes.sizeof(nid))
        nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        nid.hWnd = self.hwnd
        nid.uID = 1
        nid.uFlags = NIF_TIP
        nid.szTip = tip
        shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(nid))

    def destroy(self):
        if self._nid:
            shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(self._nid))
            self._nid = None
        if self._icon_handle:
            user32.DestroyIcon(self._icon_handle)
            self._icon_handle = None
        # 还原自己的原 WndProc（全局 _OLD_PROC 可能已被别的实例覆盖）
        if self._hooked and self._old_proc:
            try:
                user32.SetWindowLongPtrW(self.hwnd, GWL_WNDPROC, self._old_proc)
            except Exception:
                pass
            self._hooked = False
        self._ok = False

    def show_menu(self):
        if not self.menu_items:
            if self.on_click:
                self.on_click()
            return
        # 毛玻璃自绘菜单（默认关闭——右键稳定性优先；OCW_ACRYLIC_MENU=1 启用，供排错）
        if os.environ.get("OCW_ACRYLIC_MENU") == "1":
            try:
                items = []
                for idx, (label, fn) in enumerate(self.menu_items):
                    sep = idx in getattr(self, "_sep_after", [])
                    items.append((label, fn, sep))
                # 寄存菜单项（主窗口钩子按索引执行）——点击动作 PostMessage 回主线程
                global _MENU_ITEMS
                _MENU_ITEMS = items
                # 非阻塞：菜单在子线程弹，动作经主窗口钩子执行
                AcrylicMenu(self.hwnd, items).show()
                return
            except Exception:
                pass
        # ---- 回退：原生菜单 ----
        hmenu = user32.CreatePopupMenu()
        user32.SetForegroundWindow(self.hwnd)
        MF_STRING = 0x0
        MF_ENABLED = 0x0
        MF_SEPARATOR = 0x800
        for idx, (label, fn) in enumerate(self.menu_items):
            if idx in getattr(self, "_sep_after", []):
                user32.AppendMenuW(hmenu, MF_SEPARATOR, ctypes.c_void_p(0), None)
            user32.AppendMenuW(hmenu, MF_STRING | MF_ENABLED,
                               ctypes.c_void_p(idx + 1), label)
        pt = wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(pt))
        sel = user32.TrackPopupMenu(hmenu,
            TPM_RIGHTALIGN | TPM_BOTTOMALIGN | TPM_RETURNCMD,
            pt.x, pt.y, 0, self.hwnd, None)
        user32.DestroyMenu(hmenu)
        if sel > 0 and sel - 1 < len(self.menu_items):
            item = self.menu_items[sel - 1]
            if callable(item[1]):
                item[1]()


def create_tray(hwnd, icon_path, tip, on_click=None, menu_items=None):
    """创建托盘（挂宿主窗口 + WndProc 钩子）；返回 (TrayIcon, ok)"""
    t = TrayIcon(hwnd, icon_path, tip, on_click=on_click, menu_items=menu_items)
    ok = t.add()
    return (t, ok)



"""毛玻璃弹出菜单（自绘，Win10/11 Acrylic 模糊）——作为 tray.py 的追加模块"""
import ctypes
from ctypes import wintypes

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
gdi32 = ctypes.windll.gdi32

user32.CreateWindowExW.restype = ctypes.c_void_p
user32.DefWindowProcW.restype = ctypes.c_ssize_t
user32.DefWindowProcW.argtypes = [ctypes.c_void_p, wintypes.UINT,
                                  ctypes.c_ssize_t, ctypes.c_ssize_t]
user32.RegisterClassW.restype = ctypes.c_ushort
user32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR,
                                   wintypes.DWORD, ctypes.c_int, ctypes.c_int,
                                   ctypes.c_int, ctypes.c_int, wintypes.HWND,
                                   wintypes.HWND, wintypes.HINSTANCE, ctypes.c_void_p]
kernel32.GetModuleHandleW.restype = wintypes.HINSTANCE
user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
gdi32.CreateFontW.restype = ctypes.c_void_p
gdi32.CreateSolidBrush.restype = ctypes.c_void_p
gdi32.CreatePen.restype = ctypes.c_void_p
user32.GetDC.restype = ctypes.c_void_p
user32.SendMessageW.restype = ctypes.c_ssize_t
user32.DispatchMessageW.restype = ctypes.c_ssize_t
user32.GetMessageW.restype = ctypes.c_ssize_t

WS_EX_TOPMOST = 0x8
WS_EX_TOOLWINDOW = 0x80
WS_POPUP = 0x80000000
WS_BORDER = 0x00800000
WM_MOUSEMOVE = 0x0200
WM_LBUTTONUP = 0x0202
WM_KEYDOWN = 0x0100
WM_KILLFOCUS = 0x0008
WM_PAINT = 0x000F
WM_DESTROY = 0x0002
PS_SOLID = 0
CLR_INVALID = 0xFFFFFFFF

ACCENT_ENABLE_BLURBEHIND = 3
ACCENT_ENABLE_ACRYLICBLURBEHIND = 4
WCA_ACCENT_POLICY = 19


class _ACCENTPOLICY(ctypes.Structure):
    _fields_ = [("AccentState", ctypes.c_uint),
                ("AccentFlags", ctypes.c_uint),
                ("GradientColor", ctypes.c_uint),
                ("AnimationId", ctypes.c_uint)]


class _WINDOWCOMPOSITIONATTRIBDATA(ctypes.Structure):
    _fields_ = [("Attribute", ctypes.c_int),
                ("Data", ctypes.c_void_p),
                ("SizeOfData", ctypes.c_size_t)]


try:
    user32.SetWindowCompositionAttribute
except Exception:
    pass


def enable_acrylic(hwnd, color=0x992E2E45):
    """Acrylic 模糊（Win10 1803+ / Win11）；失败回退普通窗口"""
    try:
        accent = _ACCENTPOLICY(AccentState=ACCENT_ENABLE_ACRYLICBLURBEHIND,
                               AccentFlags=2,
                               GradientColor=color)
        data = _WINDOWCOMPOSITIONATTRIBDATA(Attribute=WCA_ACCENT_POLICY,
                                            Data=ctypes.cast(ctypes.pointer(accent),
                                                             ctypes.c_void_p),
                                            SizeOfData=ctypes.sizeof(accent))
        user32.SetWindowCompositionAttribute(hwnd, ctypes.byref(data))
        return True
    except Exception:
        return False


"""毛玻璃菜单 v2：宿主消息调度（不卡死）+ Layered 半透明绘制（真玻璃质感）"""


class AcrylicMenu:
    """自绘半透明菜单。
    - 动作执行：点击时 PostMessage 宿主主窗口（WM_USER+101）→ 主窗口钩子执行（主窗口线程，evaluate_js 安全）
    - 渲染：UpdateLayeredWindow + 32 位 alpha DIB（真半透明，跨 Win10/11；DWM 模糊与 Layered 互斥，
      但半透明+圆角+光影已是玻璃质感，且兼容所有环境）
    items: [(label, fn, sep_after_bool)]
    """
    FONT_NAME = "Microsoft YaHei UI"
    MARGIN = 12
    ITEM_H = 34
    WIDTH = 250
    RADIUS = 12
    MSG_ACTION = 0x401 + 101   # WM_USER+101（与宿主钩子约定）

    def __init__(self, owner_hwnd, items):
        self.owner = int(owner_hwnd)
        self.items = items
        self._proc = None
        self._hfont = None
        self._hwnd = None
        self._dib = None
        self._dibdc = None
        self._old_dib = None
        self._hover = -1

    def _size(self):
        h = self.MARGIN * 2
        for _l, _f, sep in self.items:
            h += self.ITEM_H
            if sep:
                h += 9
        return self.WIDTH, h

    def _reg_class(self):
        class WNDCLASSW(ctypes.Structure):
            _fields_ = [("style", wintypes.UINT), ("lpfnWndProc", ctypes.c_void_p),
                        ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
                        ("hInstance", wintypes.HINSTANCE), ("hIcon", wintypes.HANDLE),
                        ("hCursor", ctypes.c_void_p), ("hbrBackground", ctypes.c_void_p),
                        ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR)]
        self._proc = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT,
                                        ctypes.c_ssize_t, ctypes.c_ssize_t)(self._wndproc)
        wc = WNDCLASSW()
        wc.hInstance = kernel32.GetModuleHandleW(None)
        wc.lpfnWndProc = ctypes.cast(self._proc, ctypes.c_void_p).value
        wc.lpszClassName = "OcwGlassMenu"
        wc.hCursor = user32.LoadCursorW(None, ctypes.c_void_p(32649))
        cls = user32.RegisterClassW(ctypes.byref(wc))
        if cls:
            return True
        try:
            return user32.GetLastError() == 1410
        except Exception:
            return False

    def _wndproc(self, hwnd, msg, wparam, lparam):
        if msg == WM_MOUSEMOVE:
            y = (int(lparam) >> 16) & 0xFFFF
            h = self._hit(y)
            if h != self._hover:
                self._hover = h
                self._render()
        elif msg == WM_LBUTTONUP:
            y = (int(lparam) >> 16) & 0xFFFF
            h = self._hit(y)
            if 0 <= h < len(self.items):
                # 关键：不直接执行 fn——PostMessage 宿主主窗口，由主窗口钩子（主线程）执行
                try:
                    user32.PostMessageW(self.owner, self.MSG_ACTION, h, 0)
                except Exception:
                    pass
            user32.DestroyWindow(hwnd)
        elif msg == WM_KEYDOWN and wparam == 27:
            user32.DestroyWindow(hwnd)
        elif msg in (WM_KILLFOCUS,):
            try:
                user32.DestroyWindow(hwnd)
            except Exception:
                pass
        elif msg == WM_DESTROY:
            self._cleanup()
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def _hit(self, y):
        for idx, (top, bottom) in enumerate(self._hits):
            if top <= y <= bottom:
                return idx
        return -1

    def _cleanup(self):
        try:
            if self._dibdc and self._old_dib:
                gdi32.SelectObject(self._dibdc, self._old_dib)
            if self._dibdc:
                gdi32.DeleteDC(self._dibdc)
            if self._dib:
                gdi32.DeleteObject(self._dib)
            if self._hfont:
                gdi32.DeleteObject(self._hfont)
        except Exception:
            pass
        self._dib = self._dibdc = self._old_dib = self._hfont = None

    def _render(self):
        """绘制到 32 位 DIB，再用 UpdateLayeredWindow 显示（真半透明）"""
        try:
            w, h = self._size()
            # 创建 32 位 DIB section
            class BITMAPINFOHEADER(ctypes.Structure):
                _fields_ = [("biSize", ctypes.c_uint32), ("biWidth", ctypes.c_int32),
                            ("biHeight", ctypes.c_int32), ("biPlanes", ctypes.c_uint16),
                            ("biBitCount", ctypes.c_uint16), ("biCompression", ctypes.c_uint32),
                            ("biSizeImage", ctypes.c_uint32), ("biXPelsPerMeter", ctypes.c_int32),
                            ("biYPelsPerMeter", ctypes.c_int32), ("biClrUsed", ctypes.c_uint32),
                            ("biClrImportant", ctypes.c_uint32)]
            bmih = BITMAPINFOHEADER()
            bmih.biSize = ctypes.sizeof(BITMAPINFOHEADER)
            bmih.biWidth = w
            bmih.biHeight = -h    # 负值：顶部向下（正内存布局）
            bmih.biPlanes = 1
            bmih.biBitCount = 32
            bmih.biCompression = 0  # BI_RGB
            bits = ctypes.c_void_p()
            self._dib = gdi32.CreateDIBSection(0, ctypes.byref(bmih), 0,
                                               ctypes.byref(bits), None, 0)
            self._dibdc = gdi32.CreateCompatibleDC(0)
            self._old_dib = gdi32.SelectObject(self._dibdc, self._dib)

            def px(x, y, a, r, g, b):
                # BGRA 直接写内存
                off = (y * w + x) * 4
                ctypes.memset(ctypes.c_void_p(bits.value + off), 0, 0)  # 占位
                ctypes.cast(bits.value + off, ctypes.POINTER(ctypes.c_byte))[0] = b
                ctypes.cast(bits.value + off, ctypes.POINTER(ctypes.c_byte))[1] = g
                ctypes.cast(bits.value + off, ctypes.POINTER(ctypes.c_byte))[2] = r
                ctypes.cast(bits.value + off, ctypes.POINTER(ctypes.c_byte))[3] = a

            # 背景：半透明深色 + 圆角 + 边框
            BG_A, BG = 215, (0x2E, 0x2E, 0x45)
            EDGE = (0x45, 0x47, 0x5A)
            for yy in range(h):
                for xx in range(w):
                    # 圆角判定
                    inside = True
                    if xx < self.RADIUS and yy < self.RADIUS:
                        dx, dy = xx - self.RADIUS, yy - self.RADIUS
                        if dx * dx + dy * dy > self.RADIUS * self.RADIUS:
                            inside = False
                    elif xx >= w - self.RADIUS and yy < self.RADIUS:
                        dx, dy = xx - (w - self.RADIUS), yy - self.RADIUS
                        if dx * dx + dy * dy > self.RADIUS * self.RADIUS:
                            inside = False
                    elif xx < self.RADIUS and yy >= h - self.RADIUS:
                        dx, dy = xx - self.RADIUS, yy - (h - self.RADIUS)
                        if dx * dx + dy * dy > self.RADIUS * self.RADIUS:
                            inside = False
                    elif xx >= w - self.RADIUS and yy >= h - self.RADIUS:
                        dx, dy = xx - (w - self.RADIUS), yy - (h - self.RADIUS)
                        if dx * dx + dy * dy > self.RADIUS * self.RADIUS:
                            inside = False
                    if not inside:
                        continue  # 透明
                    a = BG_A
                    # 边框（外沿 1px 亮一点）
                    if (yy < 1 or yy >= h - 1 or xx < 1 or xx >= w - 1):
                        px(xx, yy, 230, EDGE[0], EDGE[1], EDGE[2])
                    else:
                        px(xx, yy, a, BG[0], BG[1], BG[2])

            # 悬停高亮 + 文字
            gdi32.SelectObject(self._dibdc, self._hfont)
            user32.SetBkMode(self._dibdc, 1)   # TRANSPARENT
            self._hits = []
            y = self.MARGIN
            for idx, (label, fn, sep) in enumerate(self.items):
                if self._hover == idx:
                    # 浅色高亮块（圆角近似）
                    for yy in range(y + 2, y + self.ITEM_H - 2):
                        for xx in range(self.MARGIN + 2, w - self.MARGIN - 2):
                            px(xx, yy, 150, 0x60, 0x5E, 0x8A)
                # 文字（白色）
                user32.SetTextColor(self._dibdc, 0xE5E0DC)
                user32.TextOutW(self._dibdc, self.MARGIN + 14,
                                y + (self.ITEM_H - 16) // 2, label, len(label))
                self._hits.append((y, y + self.ITEM_H))
                y += self.ITEM_H
                if sep:
                    # 分隔线（半透明）
                    ly = y + 4
                    for xx in range(self.MARGIN + 10, w - self.MARGIN - 10):
                        px(xx, ly, 120, 0x50, 0x55, 0x77)
                    y += 9

            # UpdateLayeredWindow
            class POINTX(ctypes.Structure):
                _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]
            class SIZE_T(ctypes.Structure):
                _fields_ = [("cx", ctypes.c_long), ("cy", ctypes.c_long)]
            class BLENDFUNCTION(ctypes.Structure):
                _fields_ = [("BlendOp", ctypes.c_byte), ("BlendFlags", ctypes.c_byte),
                            ("SourceConstantAlpha", ctypes.c_byte),
                            ("AlphaFormat", ctypes.c_byte)]
            dst = POINTX(0, 0)
            src = POINTX(0, 0)
            size = SIZE_T(w, h)
            bf = BLENDFUNCTION(0, 0, 255, 1)   # AC_SRC_ALPHA
            user32.UpdateLayeredWindow(self._hwnd, user32.GetDC(None), None,
                                       ctypes.byref(size), self._dibdc,
                                       ctypes.byref(src), 0, ctypes.byref(bf), 2)
        except Exception:
            pass

    def _thread_show(self):
        if not self._reg_class():
            return
        w, h = self._size()
        try:
            self._hfont = gdi32.CreateFontW(-13, 0, 0, 0, 400, 0, 0, 0, 1, 0, 0, 0,
                                             0, self.FONT_NAME)
        except Exception:
            self._hfont = None
        pt = wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(pt))
        x = max(8, pt.x - w + 8)
        y = max(8, pt.y - h - 12)
        hwnd = user32.CreateWindowExW(
            0x80000 | 0x8 | 0x80,   # WS_EX_LAYERED | TOPMOST | TOOLWINDOW
            "OcwGlassMenu", "OpenClaw", 0x80000000,   # WS_POPUP
            x, y, w, h, self.owner, None, kernel32.GetModuleHandleW(None), None)
        if not hwnd:
            return
        self._hwnd = hwnd
        self._render()
        user32.ShowWindow(hwnd, 4)   # SW_SHOWNOACTIVATE
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

    def show(self):
        """非阻塞弹菜单：独立线程（窗口与消息泵同线程）；动作经宿主 PostMessage 回主线程执行"""
        import threading as _th
        _th.Thread(target=self._thread_show, daemon=True).start()
        return None


def open_acrylic_menu(owner_hwnd, items):
    return AcrylicMenu(owner_hwnd, items).show()
