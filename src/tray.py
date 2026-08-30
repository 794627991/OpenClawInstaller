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
import threading
import time
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
WM_CLOSE = 0x0010


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

_DBG_PATH = os.path.expanduser("~/.openclaw/tray-debug.log")
def _dbg(s):
    try:
        with open(_DBG_PATH, "a", encoding="utf-8") as f:
            f.write("%s %s\n" % (time.time(), s))
    except Exception:
        pass

MSG_ACTION_FROM_MENU = 0x401 + 101   # 毛玻璃菜单动作（与 AcrylicMenu.MSG_ACTION 一致）
_MENU_ITEMS = []                     # 毛玻璃菜单项（主线程按索引提取动作）


MSG_ACTION_EXEC = 0x401 + 102   # 延迟执行（务必离开 WndProc 栈再跑 fn——同步 evaluate_js 自锁）


def _hook_proc(hwnd, msg, wparam, lparam):
    """宿主 WndProc：托盘 WM_USER+100 分发；菜单动作 WM_USER+101 先缓存，PostMessage 延迟执行"""
    if msg == MSG_ACTION_FROM_MENU and _ACTIVE:
        _dbg("hook 收到 MSG_ACTION wparam=%s lparam=%s" % (wparam, int(lparam)))
        # lparam=面板 hwnd：EXEC 按实例表分发（双面板并存动作不错位）；0=旧菜单/回退全局表
        user32.PostMessageW(hwnd, MSG_ACTION_EXEC, wparam, lparam)
        return 0
    if msg == MSG_ACTION_EXEC and _ACTIVE:
        try:
            idx = int(wparam)
            # 动作表独立于实例表：面板自毁 pop 后仍正确分发（竞态根治）
            entry = _MENU_ACTION_MAP.get(int(lparam))
            fn = None
            if entry is not None:
                actions, spec = entry
                if idx >= 1000 and spec is not None and callable(spec.get("on_row")):
                    spec["on_row"](idx - 1000)
                    _dbg("hook on_row(p%d) i=%s" % (int(lparam) & 0xFFFF, idx - 1000))
                    return 0
                if 0 <= idx < len(actions):
                    fn = actions[idx][2]
                    _dbg("hook EXEC(p%d) idx=%s" % (int(lparam) & 0xFFFF, idx))
            elif 0 <= idx < len(_MENU_ITEMS):
                fn = _MENU_ITEMS[idx][1]
            if callable(fn):
                fn()
        except Exception:
            pass
        return 0
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
        # 面板路由：外部（webui）注入 _route → 右键弹 07 式卡片面板（默认）
        if getattr(self, "_route", None) is not None:
            try:
                self._route()
                return
            except Exception as e:
                _dbg("面板路由异常，回退系统菜单: %r" % e)
        # 回退链：OCW_ACRYLIC_MENU=1 → 毛玻璃自绘菜单；默认原生系统菜单
        _dbg("show_menu items=%d acrylic=%s" % (len(self.menu_items),
             os.environ.get("OCW_ACRYLIC_MENU", "0")))
        if os.environ.get("OCW_ACRYLIC_MENU", "0") != "0":
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
            except Exception as e:
                _dbg("AcrylicMenu 弹窗异常 %r" % e)
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
        _dbg("原生菜单 sel=%s items=%d" % (sel, len(self.menu_items)))
        if sel > 0 and sel - 1 < len(self.menu_items):
            item = self.menu_items[sel - 1]
            if callable(item[1]):
                item[1]()   # 动作已是 gui_exec 入队（pump 消费）→ 永不卡死


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


def enable_acrylic(hwnd, color=0x880A141E):
    """系统毛玻璃 backdrop。Win11：DwmSetWindowAttribute SYSTEMBACKDROP（成功即主路径，
    不再叠加老 API——Win11 上 SetWindowCompositionAttribute 会覆盖系统 backdrop）；
    Win10：才走 SetWindowCompositionAttribute Acrylic。"""
    # ① Win11：系统 backdrop + 圆角
    try:
        dwm = ctypes.windll.dwmapi
        dwm.DwmSetWindowAttribute.restype = ctypes.c_long
        DWMWA_SYSTEMBACKDROP_TYPE = 38
        DWMSBT_ACRYLIC = 3
        val = ctypes.c_int(DWMSBT_ACRYLIC)
        r = dwm.DwmSetWindowAttribute(hwnd, DWMWA_SYSTEMBACKDROP_TYPE,
                                      ctypes.byref(val), ctypes.sizeof(val))
        if r == 0:
            try:
                DWMWA_WINDOW_CORNER_PREFERENCE = 33
                DWMWCP_ROUND = 2
                r2 = ctypes.c_int(DWMWCP_ROUND)
                dwm.DwmSetWindowAttribute(hwnd, DWMWA_WINDOW_CORNER_PREFERENCE,
                                          ctypes.byref(r2), ctypes.sizeof(r2))
            except Exception:
                pass
            return True
    except Exception:
        pass
    # ② Win10：accent acrylic
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
        pass
    return False





"""毛玻璃菜单：真 Acrylic 弹窗菜单
- 真毛玻璃：Win11 DwmSetWindowAttribute(SYSTEMBACKDROP) / Win10 SetWindowCompositionAttribute
- 类全局只注册一次 + 静态 WndProc（带实例表分发）→ 多次右键不悬空、不叠加、不崩
- 动作执行：点击 → PostMessage 宿主(MSG_ACTION) → 主窗口钩子 PostMessage 延迟执行
  （不在 WndProc 栈内同步 evaluate_js → 不卡死）
"""


# ---- GDI 函数必须声明参数/返回类型：无 argtypes 时中文 str 传 TextOutW 会 TypeError ----
user32.BeginPaint.restype = ctypes.c_void_p
gdi32.SetBkMode.argtypes = [ctypes.c_void_p, ctypes.c_int]
gdi32.SetBkMode.restype = ctypes.c_int
gdi32.SetTextColor.argtypes = [ctypes.c_void_p, wintypes.DWORD]
gdi32.SetTextColor.restype = wintypes.DWORD
gdi32.TextOutW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int,
                           wintypes.LPCWSTR, ctypes.c_int]
gdi32.TextOutW.restype = wintypes.BOOL
gdi32.RoundRect.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int,
                            ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int]
gdi32.RoundRect.restype = wintypes.BOOL
gdi32.SelectObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
gdi32.DeleteObject.argtypes = [ctypes.c_void_p]

WS_EX_NOACTIVATE = 0x08000000

# ctypes.wintypes 没有 PAINTSTRUCT（Python 3.14 确认），必须自定义——否则 _paint 整体失败
class _PAINTSTRUCT(ctypes.Structure):
    _fields_ = [("hdc", ctypes.c_void_p),
                ("fErase", wintypes.BOOL),
                ("rcPaint", wintypes.RECT),
                ("fRestore", wintypes.BOOL),
                ("fIncUpdate", wintypes.BOOL),
                ("rgbReserved", ctypes.c_byte * 32)]

# ---- 菜单/面板窗口：全局唯一注册 + 静态 WndProc（防止多次弹窗时回调对象被 GC 悬空） ----
_MENU_CLASS_CACHE = {}      # 类名 -> True（进程内只注册一次）
_MENU_INSTANCES = {}        # int(hwnd) -> 实例
# 面板动作表：int(hwnd) -> (actions, spec)。独立于 _MENU_INSTANCES——
# 面板点击自毁（WM_DESTROY pop）后 EXEC 仍可正确分发（对抗审计高-1 竞态根治）
_MENU_ACTION_MAP = {}


def _menu_static_wndproc(hwnd, msg, wparam, lparam):
    """类注册的唯一窗口过程：按 hwnd 分发到实例；无实例交给系统默认。"""
    inst = _MENU_INSTANCES.get(int(hwnd))
    if inst is None:
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)
    return inst._wndproc(hwnd, msg, wparam, lparam)


# 模块加载时一次性创建（对抗审计中-3：lazy check-then-set 竞态会释放已注册 thunk → AV）
_MENU_STATIC_PROC = ctypes.WINFUNCTYPE(
    ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT,
    ctypes.c_ssize_t, ctypes.c_ssize_t)(_menu_static_wndproc)


def _menu_reg_class(cls_name="OcwGlassMenuV3"):
    """注册弹窗类（每个类名只注册一次；已存在(1410)视为成功）。
    菜单用 OcwGlassMenuV3、面板用 OcwPanelV1——共用静态 proc 分发"""
    if _MENU_CLASS_CACHE.get(cls_name):
        return True
    try:

        class WNDCLASSW(ctypes.Structure):
            _fields_ = [("style", wintypes.UINT), ("lpfnWndProc", ctypes.c_void_p),
                        ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
                        ("hInstance", wintypes.HINSTANCE), ("hIcon", wintypes.HANDLE),
                        ("hCursor", ctypes.c_void_p), ("hbrBackground", ctypes.c_void_p),
                        ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR)]
        wc = WNDCLASSW()
        wc.hInstance = kernel32.GetModuleHandleW(None)
        wc.lpfnWndProc = ctypes.cast(_MENU_STATIC_PROC, ctypes.c_void_p).value
        wc.lpszClassName = cls_name
        wc.hCursor = user32.LoadCursorW(None, ctypes.c_void_p(32649))
        cls = user32.RegisterClassW(ctypes.byref(wc))
        if cls or user32.GetLastError() == 1410:
            _MENU_CLASS_CACHE[cls_name] = True
            return True
        _dbg("菜单类注册失败 %s last=%s" % (cls_name, user32.GetLastError()))
        return False
    except Exception as e:
        _dbg("菜单类注册异常 %r" % e)
        return False


class AcrylicMenu:
    FONT_NAME = "Microsoft YaHei UI"
    MARGIN = 12
    ITEM_H = 34
    WIDTH = 250
    RADIUS = 12

    def __init__(self, owner_hwnd, items):
        self.owner = int(owner_hwnd)
        self.items = items
        self._hfont = None
        self._hwnd = None
        self._hover = -1
        self._hits = []

    def _size(self):
        h = self.MARGIN * 2
        for _l, _f, sep in self.items:
            h += self.ITEM_H
            if sep:
                h += 9
        return self.WIDTH, h

    def _precompute_hits(self):
        """命中区域预计算（不依赖 WM_PAINT——只要窗口弹出来就能点）"""
        self._hits = []
        y = self.MARGIN
        for _l, _f, sep in self.items:
            self._hits.append((y, y + self.ITEM_H))
            y += self.ITEM_H + (9 if sep else 0)

    def _wndproc(self, hwnd, msg, wparam, lparam):
        try:
            if msg == WM_MOUSEMOVE:
                y = (int(lparam) >> 16) & 0xFFFF
                h = self._hit(y)
                if h != self._hover:
                    self._hover = h
                    user32.InvalidateRect(hwnd, None, True)
            elif msg == WM_LBUTTONUP:
                y = (int(lparam) >> 16) & 0xFFFF
                h = self._hit(y)
                _dbg("菜单 WM_LBUTTONUP y=%s hit=%d items=%d" % (y, h, len(self.items)))
                if 0 <= h < len(self.items):
                    try:
                        user32.PostMessageW(self.owner, MSG_ACTION_FROM_MENU, h, 0)
                        _dbg("已 post owner msg_action h=%s" % h)
                    except Exception as e:
                        _dbg("post 失败 %r" % e)
                user32.DestroyWindow(hwnd)
            elif msg == WM_PAINT:
                self._paint(hwnd)
                return 0
            elif msg == WM_KEYDOWN and wparam == 27:
                user32.DestroyWindow(hwnd)
            elif msg == WM_CLOSE:
                try:
                    user32.DestroyWindow(hwnd)
                except Exception:
                    pass
            elif msg == WM_KILLFOCUS:
                try:
                    user32.DestroyWindow(hwnd)
                except Exception:
                    pass
            elif msg == WM_DESTROY:
                _MENU_INSTANCES.pop(int(hwnd), None)
                try:
                    if self._hfont:
                        gdi32.DeleteObject(self._hfont)
                        self._hfont = None
                except Exception:
                    pass
                try:
                    user32.PostQuitMessage(0)   # 结束本面板线程消息泵（防线程泄漏）
                except Exception:
                    pass
        except Exception as e:
            _dbg("菜单 _wndproc 异常 msg=0x%04x %r" % (int(msg), e))
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def _hit(self, y):
        for idx, (top, bottom) in enumerate(self._hits):
            if top <= y <= bottom:
                return idx
        return -1

    def _paint(self, hwnd):
        """只画内容（文字/高亮/分隔线），背景交给 DWM blur——GDI 全走 gdi32 且声明 LPCWSTR"""
        try:
            ps = _PAINTSTRUCT()
            hdc = user32.BeginPaint(hwnd, ctypes.byref(ps))
            if not hdc:
                _dbg("菜单 BeginPaint 返回空")
            w, _h = self._size()
            gdi32.SelectObject(hdc, self._hfont)
            gdi32.SetBkMode(hdc, 1)   # TRANSPARENT
            y = self.MARGIN
            for idx, (label, fn, sep) in enumerate(self.items):
                if self._hover == idx:
                    pen = gdi32.CreatePen(0, 1, 0x004A57A0)
                    gdi32.SelectObject(hdc, pen)
                    gdi32.RoundRect(hdc, self.MARGIN, y, w - self.MARGIN,
                                    y + self.ITEM_H, 9, 9)
                    gdi32.DeleteObject(pen)
                    gdi32.SetTextColor(hdc, 0x00A8B7F3)   # 高亮文字（浅蓝）
                else:
                    gdi32.SetTextColor(hdc, 0xF0E8E4)
                gdi32.TextOutW(hdc, self.MARGIN + 14,
                               y + (self.ITEM_H - 16) // 2, label, len(label))
                y += self.ITEM_H
                if sep:
                    pen = gdi32.CreatePen(0, 1, 0xA89897F5)
                    gdi32.SelectObject(hdc, pen)
                    gdi32.MoveToEx(hdc, self.MARGIN + 10, y + 4, None)
                    gdi32.LineTo(hdc, w - self.MARGIN - 10, y + 4)
                    gdi32.DeleteObject(pen)
                    y += 9
            user32.EndPaint(hwnd, ctypes.byref(ps))
            _dbg("菜单 WM_PAINT 完成 items=%d hover=%d" % (len(self.items), self._hover))
        except Exception as e:
            _dbg("菜单 _paint 异常: %r" % e)

    def _thread_show(self):
        try:
            if not _menu_reg_class():
                return
            w, h = self._size()
            self._hfont = gdi32.CreateFontW(-13, 0, 0, 0, 400, 0, 0, 0, 1, 0, 0, 0,
                                             0, self.FONT_NAME)
            pt = wintypes.POINT()
            user32.GetCursorPos(ctypes.byref(pt))
            x = max(8, pt.x - w + 8)
            y = max(8, pt.y - h - 12)
            hwnd = user32.CreateWindowExW(
                0x8 | 0x80 | WS_EX_NOACTIVATE,   # TOPMOST | TOOLWINDOW | NOACTIVATE（非 Layered，与 DWM blur 共存）
                "OcwGlassMenuV3", "OpenClaw", 0x80000000,   # WS_POPUP
                x, y, w, h, None, None, kernel32.GetModuleHandleW(None), None)
            if not hwnd:
                _dbg("菜单 CreateWindowExW 失败")
                return
            self._hwnd = hwnd
            _MENU_INSTANCES[int(hwnd)] = self   # 先入表再显示（ShowWindow 派发的消息也能分发）
            self._precompute_hits()
            _dbg("菜单窗口创建 hwnd=%s items=%d" % (int(hwnd), len(self.items)))
            # 真 Acrylic：Win11 DWM backdrop / Win10 accent（深蓝黑 tint）
            enable_acrylic(hwnd, color=0x880A141E)
            user32.ShowWindow(hwnd, 4)   # SW_SHOWNOACTIVATE
            msg = wintypes.MSG()
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
            _dbg("菜单消息泵退出")
        except Exception as e:
            _dbg("菜单线程异常 %r" % e)

    def show(self):
        """非阻塞弹菜单；先关掉残留旧菜单（连点右键不叠加）"""
        for h in list(_MENU_INSTANCES.keys()):
            try:
                user32.PostMessageW(h, WM_CLOSE, 0, 0)
            except Exception:
                pass
        import threading as _th
        _th.Thread(target=self._thread_show, daemon=True).start()
        return None


def open_acrylic_menu(owner_hwnd, items):
    return AcrylicMenu(owner_hwnd, items).show()


# ============================================================
# 07 式卡片面板：状态点 + 标题 + 键值行 + 按钮网格（GDI 自绘深色圆角卡）
# 动作链：按钮点击 → PostMessage 宿主(MSG_ACTION) → 主窗口钩子 MSG_ACTION_EXEC → fn
# 关闭：点击空白/按钮、ESC、失焦（点面板外自动关——面板本身激活）
# ============================================================
gdi32.SetTextAlign.argtypes = [ctypes.c_void_p, wintypes.UINT]
gdi32.SetTextAlign.restype = wintypes.UINT
gdi32.Ellipse.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int,
                          ctypes.c_int, ctypes.c_int]
gdi32.Ellipse.restype = wintypes.BOOL
gdi32.GetTextExtentPoint32W.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR,
                                        ctypes.c_int, ctypes.c_void_p]
gdi32.GetTextExtentPoint32W.restype = wintypes.BOOL
gdi32.MoveToEx.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_void_p]
gdi32.MoveToEx.restype = wintypes.BOOL
gdi32.LineTo.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
gdi32.LineTo.restype = wintypes.BOOL
gdi32.CreatePen.argtypes = [ctypes.c_int, ctypes.c_int, wintypes.DWORD]
gdi32.CreateSolidBrush.argtypes = [wintypes.DWORD]
user32.BeginPaint.argtypes = [wintypes.HWND, ctypes.c_void_p]
user32.EndPaint.argtypes = [wintypes.HWND, ctypes.c_void_p]
user32.InvalidateRect.argtypes = [wintypes.HWND, ctypes.c_void_p, wintypes.BOOL]
user32.SetForegroundWindow.argtypes = [wintypes.HWND]

TA_LEFT = 0
TA_RIGHT = 2


class _SIZEX(ctypes.Structure):
    _fields_ = [("cx", ctypes.c_int), ("cy", ctypes.c_int)]


# ============================================================
# 全局鼠标监听（pynput）：点击面板外部任意位置 → 关闭全部面板
# 自研 WH_MOUSE_LL 在 pywebview 进程内回调从未被调度（diag 实测 0 回调，
# mini 复刻却正常——同进程组合下有系统性差异，不再深挖）；
# pynput 的 win32 实现已在同一进程实测（diag12 端到端关面板成功）。
# ============================================================
_pynput_listener = None


def _mouse_listen_start():
    """幂等：首次弹面板时启动；Listener daemon 常驻，点击非面板区域 post WM_CLOSE"""
    global _pynput_listener
    if _pynput_listener is not None:
        return
    try:
        from pynput import mouse

        # WindowFromPoint 需要 POINT 按值（x64 用 byref 指针会返回 NULL）
        user32.WindowFromPoint.argtypes = [wintypes.POINT]
        user32.WindowFromPoint.restype = wintypes.HWND

        def on_click(x, y, button, pressed):
            try:
                if not pressed:
                    return
                # DPI 差异：pynput 报物理坐标、面板窗口坐标/WindowFromPoint 可能按逻辑或物理
                # （进程 awareness 不同）；两种坐标都试——命中面板即算面板内
                hw = None
                try:
                    dpi = user32.GetDpiForSystem() or 96
                    hw = user32.WindowFromPoint(wintypes.POINT(
                        int(int(x) * 96 / dpi), int(int(y) * 96 / dpi)))
                except Exception:
                    pass
                if not hw or (hw and int(hw) not in _MENU_INSTANCES):
                    try:
                        hw2 = user32.WindowFromPoint(wintypes.POINT(int(x), int(y)))
                        if hw2 and int(hw2) in _MENU_INSTANCES:
                            hw = hw2
                    except Exception:
                        pass
                is_panel = bool(hw) and int(hw) in _MENU_INSTANCES
                _dbg("pynput click (%s,%s) hw=%s panel=%s items=%d"
                     % (int(x), int(y), int(hw) if hw else "-", is_panel, len(_MENU_INSTANCES)))
                if is_panel:
                    return
                for h in list(_MENU_INSTANCES.keys()):
                    try:
                        user32.PostMessageW(h, WM_CLOSE, 0, 0)
                    except Exception:
                        pass
            except Exception:
                pass

        _pynput_listener = mouse.Listener(on_click=on_click)
        _pynput_listener.daemon = True
        _pynput_listener.start()
        _dbg("pynput 鼠标监听已启动")
    except Exception as e:
        _dbg("pynput 监听启动失败 %r" % e)


def menu_find(cls_name):
    """按类名返回当前打开的菜单/面板 hwnd（遍历实例表）；无则 0"""
    for h, inst in list(_MENU_INSTANCES.items()):
        try:
            if getattr(inst, "_cls_name", "") == cls_name:
                return h
        except Exception:
            pass
    return 0


class AcrylicPanel:
    """07 式托盘卡片面板 v2：原版配色（近黑深底+浅灰文字+绿/黄/红状态点+蓝 Toggle+分段卡）
    行结构：标题(白,右侧版本小字) / 状态行(点+文字+addr) / 模型行 / 分隔 / Gateway 卡头+badge /
            卡体行 / 分隔 / 按钮组
    spec = {"title","version","status","status_text","addr","model","badge","node"}
    actions = [(kind, label, fn)]：
        kind= "main" 通栏主按钮 | "btn" 双列 | "quit" 通栏（每种都计入 _MENU_ITEMS 动作链）"""
    WIDTH = 320
    MARGIN = 16
    RADIUS = 14
    BTN_H = 38
    BTN_GAP = 8

    _DOT = {"green": 0x7EC935, "yellow": 0x43C0F0, "red": 0x4E56E5}
    _TCLR = {"green": 0xB4DD8F, "yellow": 0x88D2F0, "red": 0x8CA2F2}

    C_BG = 0x1C1615
    C_EDGE = 0x362C2A
    C_TXT = 0xF6F2F2
    C_SUB = 0xA89C9A
    C_WEAK = 0x6F6563
    C_SEP = 0x2E2523
    C_BTN = 0x2B2220
    C_BTN_HOVER = 0x3A2E2C
    C_MAIN = 0xDB6B2E
    C_MAIN_HOVER = 0xEB7C3E
    C_BADGE_BG = 0x2E2423
    C_GOOD = 0x7EC935

    def __init__(self, owner_hwnd, spec, actions):
        self.owner = int(owner_hwnd)
        self.spec = spec
        self.actions = actions
        self._hwnd = None
        self._hover = -1
        self._btn_rows = []         # [(x0,y0,x1,y1,kind,action_idx)]
        self._hdr_y = self._st_y = self._md_y = self._gwhd_y = self._gwbd_y = 0
        self._sep1 = self._sep2 = 0
        self._w = self.WIDTH
        self._h = 0
        self._hfont = None
        self._hfont_b = None
        self._hfont_s = None

    def _size(self):
        return self.WIDTH, self._h

    def _calc(self):
        m = self.MARGIN
        y = m
        self._hdr_y = y; y += 32
        self._st_y = y; y += 27
        self._md_y = y; y += 25
        self._sep1 = y - 2; y += 13
        self._btn_rows = []
        # 按钮网格：main/quit 通栏；btn 双列（落单自动双宽）
        i = 0
        while i < len(self.actions):
            kind, label, fn = self.actions[i]
            if kind in ("main", "quit", "row"):
                hh = self.BTN_H if kind != "row" else 36
                self._btn_rows.append((m, y, self.WIDTH - m, y + hh, kind, i))
                y += hh + self.BTN_GAP
                i += 1
            else:
                row = [(kind, i)]
                if i + 1 < len(self.actions) and self.actions[i + 1][0] == "btn":
                    row.append((self.actions[i + 1][0], i + 1))
                    i += 2
                else:
                    i += 1
                half = int((self.WIDTH - 2 * m - self.BTN_GAP) / 2)
                if len(row) == 2:
                    self._btn_rows.append((m, y, m + half, y + self.BTN_H, "btn", row[0][1]))
                    self._btn_rows.append((m + half + self.BTN_GAP, y, self.WIDTH - m,
                                          y + self.BTN_H, "btn", row[1][1]))
                    y += self.BTN_H + self.BTN_GAP
                else:
                    self._btn_rows.append((m, y, self.WIDTH - m, y + self.BTN_H, "btn", row[0][1]))
                    y += self.BTN_H + self.BTN_GAP
        self._h = y + 16

    def _font(self):
        self._hfont = gdi32.CreateFontW(-13, 0, 0, 0, 400, 0, 0, 0, 1, 0, 0, 0, 0,
                                        "Microsoft YaHei UI")
        self._hfont_b = gdi32.CreateFontW(-16, 0, 0, 0, 600, 0, 0, 0, 1, 0, 0, 0, 0,
                                          "Microsoft YaHei UI")
        self._hfont_s = gdi32.CreateFontW(-11, 0, 0, 0, 400, 0, 0, 0, 1, 0, 0, 0, 0,
                                          "Microsoft YaHei UI")

    def _hit(self, x, y):
        for idx, (x0, y0, x1, y1, _k, ai) in enumerate(self._btn_rows):
            if x0 <= x <= x1 and y0 <= y <= y1:
                return ai
        return -1

    def _wndproc(self, hwnd, msg, wparam, lparam):
        try:
            if msg == WM_MOUSEMOVE:
                x, y = int(lparam) & 0xFFFF, (int(lparam) >> 16) & 0xFFFF
                h = self._hit(x, y)
                if h != self._hover:
                    self._hover = h
                    user32.InvalidateRect(hwnd, None, True)
            elif msg == WM_LBUTTONUP:
                x, y = int(lparam) & 0xFFFF, (int(lparam) >> 16) & 0xFFFF
                h = self._hit(x, y)
                _dbg("面板 v2 WM_LBUTTONUP x=%d y=%d hit=%d" % (x, y, h))
                if 0 <= h < len(self.actions):
                    try:
                        user32.PostMessageW(self.owner, MSG_ACTION_FROM_MENU, h, int(hwnd))
                        _dbg("面板 v2 已 post owner msg_action h=%s (带面板 hwnd)" % h)
                    except Exception as e:
                        _dbg("面板 v2 post 失败 %r" % e)
                    # row（Sessions）点击：保留主面板——列表在旁边新开（并排）
                    if self.actions[h][0] == "row":
                        return 0
                user32.DestroyWindow(hwnd)
            elif msg == WM_PAINT:
                self._paint(hwnd)
                return 0
            elif msg == WM_KEYDOWN and wparam == 27:
                user32.DestroyWindow(hwnd)
            elif msg == WM_CLOSE:
                user32.DestroyWindow(hwnd)
            elif msg == WM_DESTROY:
                _MENU_INSTANCES.pop(int(hwnd), None)
                # 动作表保留（EXEC 可能晚到——面板自毁后动作仍需正确分发）
                for f in (self._hfont, self._hfont_b, self._hfont_s):
                    try:
                        if f:
                            gdi32.DeleteObject(f)
                    except Exception:
                        pass
                try:
                    user32.PostQuitMessage(0)   # 结束本面板线程消息泵（防线程泄漏）
                except Exception:
                    pass
        except Exception as e:
            _dbg("面板 v2 _wndproc 异常 msg=0x%04x %r" % (int(msg), e))
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def _fill_rect(self, hdc, x0, y0, x1, y1, color, rad=0):
        """绘制圆角/矩形。brush/pen 先换出 DC 再删除（MSDN：选中对象 DeleteObject 必然失败→泄漏）"""
        brush = gdi32.CreateSolidBrush(color)
        pen = gdi32.CreatePen(0, 1, color)
        old_b = gdi32.SelectObject(hdc, brush)
        old_p = gdi32.SelectObject(hdc, pen)
        try:
            if rad:
                gdi32.RoundRect(hdc, x0, y0, x1, y1, rad, rad)
            else:
                gdi32.Rectangle(hdc, x0, y0, x1, y1)
        finally:
            gdi32.SelectObject(hdc, old_p)
            gdi32.SelectObject(hdc, old_b)
            gdi32.DeleteObject(pen)
            gdi32.DeleteObject(brush)

    def _paint(self, hwnd):
        ps = _PAINTSTRUCT()
        hdc = user32.BeginPaint(hwnd, ctypes.byref(ps))
        if not hdc:
            return
        try:
            self._paint_impl(hdc)
        except Exception:
            import traceback as _tb
            _dbg("面板 v2 _paint 异常:\n%s" % _tb.format_exc())
        finally:
            user32.EndPaint(hwnd, ctypes.byref(ps))
        return

    def _paint_impl(self, hdc):
        try:
            w, h = self._w, self._h
            m = self.MARGIN
            gdi32.SetBkMode(hdc, 1)   # TRANSPARENT
            # 背景圆角卡 + 1px 边框（先换出再删——防 GDI 泄漏）
            brush = gdi32.CreateSolidBrush(self.C_BG)
            pen = gdi32.CreatePen(0, 1, self.C_EDGE)
            old_b = gdi32.SelectObject(hdc, brush)
            old_p = gdi32.SelectObject(hdc, pen)
            gdi32.RoundRect(hdc, 0, 0, w, h, self.RADIUS * 2, self.RADIUS * 2)
            gdi32.SelectObject(hdc, old_p)
            gdi32.SelectObject(hdc, old_b)
            gdi32.DeleteObject(pen)
            gdi32.DeleteObject(brush)
            # ① 标题（粗白）
            gdi32.SelectObject(hdc, self._hfont_b)
            gdi32.SetTextColor(hdc, self.C_TXT)
            t = self.spec.get("title", "OpenClaw")
            gdi32.TextOutW(hdc, m, self._hdr_y, t, len(t))
            # ② 版本号（标题行右，避免与状态行地址重叠）
            gdi32.SelectObject(hdc, self._hfont_s)
            gdi32.SetTextColor(hdc, self.C_WEAK)
            gdi32.SetTextAlign(hdc, TA_RIGHT)
            v = self.spec.get("version") or ""
            if v:
                gdi32.TextOutW(hdc, w - m, self._hdr_y + 8, v, len(v))
            gdi32.SetTextAlign(hdc, TA_LEFT)
            # ③ 状态行：点 + 状态文字 + addr，右侧版本
            gdi32.SelectObject(hdc, self._hfont)
            st = self.spec.get("status", "red")
            b3 = gdi32.CreateSolidBrush(self._DOT.get(st, self._DOT["red"]))
            old_s = gdi32.SelectObject(hdc, b3)
            gdi32.Ellipse(hdc, m, self._st_y + 5, m + 10, self._st_y + 15)
            gdi32.SelectObject(hdc, old_s)
            gdi32.DeleteObject(b3)
            gdi32.SetTextColor(hdc, self._TCLR.get(st, self._TCLR["red"]))
            stt = self.spec.get("status_text", "")
            gdi32.TextOutW(hdc, m + 18, self._st_y, stt, len(stt))
            addr = self.spec.get("addr", "")
            if addr:
                szs = _SIZEX()
                gdi32.GetTextExtentPoint32W(hdc, stt, len(stt), ctypes.byref(szs))
                gdi32.SetTextColor(hdc, self.C_SUB)
                txt = " · " + addr
                gdi32.TextOutW(hdc, m + 18 + szs.cx + 8, self._st_y, txt, len(txt))
            # ④ 模型行（弱灰）
            gdi32.SetTextColor(hdc, self.C_WEAK)
            md = self.spec.get("model", "")
            if md:
                mtxt = "使用模型  ·  " + md
                gdi32.TextOutW(hdc, m, self._md_y, mtxt, len(mtxt))
            # ⑤ 分隔线
            pen = gdi32.CreatePen(0, 1, self.C_SEP)
            old_pp = gdi32.SelectObject(hdc, pen)
            gdi32.MoveToEx(hdc, m, self._sep1, None)
            gdi32.LineTo(hdc, w - m, self._sep1)
            gdi32.SelectObject(hdc, old_pp)
            gdi32.DeleteObject(pen)
            # ⑧ 按钮
            gdi32.SelectObject(hdc, self._hfont)
            for (x0, y0, x1, y1, kind, ai) in self._btn_rows:
                label = self.actions[ai][1]
                hv = self._hover == ai
                if kind == "row":
                    bg = self.C_BTN_HOVER if hv else self.C_BTN
                    self._fill_rect(hdc, x0, y0, x1, y1, bg, 18)
                    gdi32.SelectObject(hdc, self._hfont)
                    gdi32.SetTextColor(hdc, 0xF0F1F5)
                    gdi32.TextOutW(hdc, x0 + 14, y0 + 8, label, len(label))
                    right = self.spec.get("sessions_right", "") or ""
                    if right:
                        gdi32.SelectObject(hdc, self._hfont_s)
                        gdi32.SetTextColor(hdc, self.C_SUB)
                        gdi32.TextOutW(hdc, x0 + 18, y0 + 11, right, len(right))
                    gdi32.SetTextColor(hdc, self.C_SUB)
                    gdi32.SelectObject(hdc, self._hfont)
                    gdi32.TextOutW(hdc, x1 - 26, y0 + 8, ">", 1)
                    continue
                if kind == "main":
                    bg = self.C_MAIN_HOVER if hv else self.C_MAIN
                    tc = 0xFFFFFF
                else:
                    bg = self.C_BTN_HOVER if hv else self.C_BTN
                    tc = 0xE0D8D6
                self._fill_rect(hdc, x0, y0, x1, y1, bg, 18)
                sz = _SIZEX()
                gdi32.GetTextExtentPoint32W(hdc, label, len(label), ctypes.byref(sz))
                gdi32.SetTextColor(hdc, tc)
                gdi32.TextOutW(hdc, (x0 + x1 - sz.cx) // 2,
                               y0 + (self.BTN_H - sz.cy) // 2, label, len(label))
        except Exception:
            pass

    def _thread_show(self):
        try:
            if not _menu_reg_class("OcwPanelV1"):
                return
            self._calc()
            self._font()
            pt = wintypes.POINT()
            user32.GetCursorPos(ctypes.byref(pt))
            w, h = self._w, self._h
            x = max(8, pt.x - w + 8)
            y = max(8, pt.y - h - 12)
            hwnd = user32.CreateWindowExW(
                0x8 | 0x80 | WS_EX_NOACTIVATE,   # TOPMOST | TOOLWINDOW | NOACTIVATE（不抢焦点，与列表面板并存）
                "OcwPanelV1", "OpenClaw", 0x80000000,   # WS_POPUP
                x, y, w, h, None, None, kernel32.GetModuleHandleW(None), None)
            if not hwnd:
                _dbg("面板 v2 CreateWindowExW 失败")
                return
            self._hwnd = hwnd
            self._cls_name = "OcwPanelV1"
            _MENU_INSTANCES[int(hwnd)] = self
            _MENU_ACTION_MAP[int(hwnd)] = (self.actions, self.spec)
            _dbg("面板 v2 创建 hwnd=%s btns=%d h=%d" % (int(hwnd), len(self._btn_rows), self._h))
            user32.ShowWindow(hwnd, 4)   # SW_SHOWNOACTIVATE
            _mouse_listen_start()
            msg = wintypes.MSG()
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
            _dbg("面板消息泵退出")
        except Exception as e:
            _dbg("面板 v2 线程异常 %r" % e)

    def show(self):
        """非阻塞弹面板；先关残留面板/菜单（连点右键不叠加）"""
        for h in list(_MENU_INSTANCES.keys()):
            try:
                user32.PostMessageW(h, WM_CLOSE, 0, 0)
            except Exception:
                pass
        import threading as _th
        _th.Thread(target=self._thread_show, daemon=True).start()
        return None


def open_session_panel(owner_hwnd, spec, actions):
    """会话列表面板：spec={"title","list"} + actions（点击走 MSG_ACTION 链同 open_panel）"""
    global _MENU_ITEMS
    _MENU_ITEMS = [(l, f, False) for (_k, l, f) in actions]
    return AcrylicSessionList(owner_hwnd, spec, actions).show()


def open_panel(owner_hwnd, spec, actions):
    """弹 07 式卡片面板。actions=[(kind,label,fn)]，写入 _MENU_ITEMS（主窗口钩子按索引执行）"""
    global _MENU_ITEMS
    _MENU_ITEMS = [(l, f, False) for (_k, l, f) in actions]
    return AcrylicPanel(owner_hwnd, spec, actions).show()


class AcrylicSessionList:
    """会话列表面板 v2（行数据 spec['list'] 可变——异步加载完成经 WM_USER+1 刷新重绘）：
    头部/返回/会话行(标题+时间/模型+token/进度条)/底部提示。
    命中：返回=actions[0]；行 N → on_row(N)（MSG_ACTION idx=1000+N）；WM_USER+1=数据到达刷新。"""
    WIDTH = 360
    MARGIN = 16
    RADIUS = 14
    ROW_H = 64
    BTN_H = 38
    BTN_GAP = 8
    MAX_ROWS = 7

    C_BG = 0x1C1615
    C_EDGE = 0x362C2A
    C_TXT = 0xF6F2F2
    C_SUB = 0xA89C9A
    C_WEAK = 0x6F6563
    C_SEP = 0x2E2523
    C_ROWHOVER = 0x242124
    C_BAR_BG = 0x33312F
    C_BAR_G = 0x37A462
    C_BAR_Y = 0xB0813C
    C_BAR_R = 0xB05243
    C_BTN = 0x2B2220
    C_BTN_HOVER = 0x3A2E2C

    def __init__(self, owner_hwnd, spec, actions):
        self.owner = int(owner_hwnd)
        self.spec = spec
        self.actions = actions
        self._hwnd = None
        self._hover = -1        # 命中索引：0=返回，N=行(N-1)；-1 无
        self._rows = []         # [(x0,y0,x1,y1,kind,val)] kind: back|row
        self._w = self.WIDTH
        self._h = 0
        self._hdr_y = 0
        self._sep1 = 0
        self._hfont = None
        self._hfont_b = None
        self._hfont_s = None

    def _list(self):
        return self.spec.get("list") or []

    def _calc(self):
        m = self.MARGIN
        y = m
        self._hdr_y = y; y += 30
        self._sep1 = y - 2; y += 11
        self._rows = []
        n = min(len(self._list()), self.MAX_ROWS)
        for i in range(n):
            self._rows.append((m, y, self.WIDTH - m, y + self.ROW_H, "row", 1000 + i))
            y += self.ROW_H + 4
        if not n:
            y += 40      # 空/加载中提示区
        self._h = y + 16

    def _font(self):
        self._hfont = gdi32.CreateFontW(-13, 0, 0, 0, 400, 0, 0, 0, 1, 0, 0, 0, 0,
                                        "Microsoft YaHei UI")
        self._hfont_b = gdi32.CreateFontW(-15, 0, 0, 0, 600, 0, 0, 0, 1, 0, 0, 0, 0,
                                          "Microsoft YaHei UI")
        self._hfont_s = gdi32.CreateFontW(-11, 0, 0, 0, 400, 0, 0, 0, 1, 0, 0, 0, 0,
                                          "Microsoft YaHei UI")

    def _hit(self, x, y):
        for (x0, y0, x1, y1, kind, val) in self._rows:
            if x0 <= x <= x1 and y0 <= y <= y1:
                return val
        return -1

    def _wndproc(self, hwnd, msg, wparam, lparam):
        try:
            if msg == WM_MOUSEMOVE:
                x, y = int(lparam) & 0xFFFF, (int(lparam) >> 16) & 0xFFFF
                h = self._hit(x, y)
                if h != self._hover:
                    self._hover = h
                    user32.InvalidateRect(hwnd, None, True)
            elif msg == WM_LBUTTONUP:
                x, y = int(lparam) & 0xFFFF, (int(lparam) >> 16) & 0xFFFF
                h = self._hit(x, y)
                _dbg("会话栏 WM_LBUTTONUP x=%d y=%d hit=%d" % (x, y, h))
                if h >= 1000:
                    # 会话行 → on_row(i)（EXEC 处理器分发）
                    try:
                        user32.PostMessageW(self.owner, MSG_ACTION_FROM_MENU, h, int(hwnd))
                        _dbg("会话栏已 post row h=%s" % h)
                    except Exception as e:
                        _dbg("会话栏 row post 失败 %r" % e)
                    user32.DestroyWindow(hwnd)
                    return 0
                user32.DestroyWindow(hwnd)   # 空白点击关闭
            elif msg == 0x401:   # WM_USER+1：异步数据到达 → 重算+重绘
                self._calc()
                user32.InvalidateRect(hwnd, None, True)
                return 0
            elif msg == WM_PAINT:
                self._paint(hwnd)
                return 0
            elif msg == WM_KEYDOWN and wparam == 27:
                user32.DestroyWindow(hwnd)
            elif msg == WM_CLOSE:
                user32.DestroyWindow(hwnd)
            elif msg == WM_DESTROY:
                _MENU_INSTANCES.pop(int(hwnd), None)
                # 动作表保留（EXEC 可能晚到）
                for f in (self._hfont, self._hfont_b, self._hfont_s):
                    try:
                        if f:
                            gdi32.DeleteObject(f)
                    except Exception:
                        pass
                try:
                    user32.PostQuitMessage(0)   # 结束本面板线程消息泵（防线程泄漏）
                except Exception:
                    pass
        except Exception as e:
            _dbg("会话栏 _wndproc 异常 msg=0x%04x %r" % (int(msg), e))
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def _paint(self, hwnd):
        ps = _PAINTSTRUCT()
        hdc = user32.BeginPaint(hwnd, ctypes.byref(ps))
        if not hdc:
            return
        try:
            self._paint_impl(hdc)
        except Exception:
            import traceback as _tb
            _dbg("会话栏 _paint 异常:\n%s" % _tb.format_exc())
        finally:
            user32.EndPaint(hwnd, ctypes.byref(ps))
        return

    def _paint_impl(self, hdc):
        try:
            w, h = self._w, self._h
            m = self.MARGIN
            gdi32.SetBkMode(hdc, 1)
            brush = gdi32.CreateSolidBrush(self.C_BG)
            pen = gdi32.CreatePen(0, 1, self.C_EDGE)
            old_b = gdi32.SelectObject(hdc, brush)
            old_p = gdi32.SelectObject(hdc, pen)
            gdi32.RoundRect(hdc, 0, 0, w, h, self.RADIUS * 2, self.RADIUS * 2)
            gdi32.SelectObject(hdc, old_p)
            gdi32.SelectObject(hdc, old_b)
            gdi32.DeleteObject(pen)
            gdi32.DeleteObject(brush)
            lst = self._list()
            # 头部
            gdi32.SelectObject(hdc, self._hfont_b)
            gdi32.SetTextColor(hdc, self.C_TXT)
            t = "%s (%d)" % (self.spec.get("title", "Sessions"), len(lst))
            gdi32.TextOutW(hdc, m, self._hdr_y, t, len(t))
            gdi32.SelectObject(hdc, self._hfont_s)
            gdi32.SetTextColor(hdc, self.C_WEAK)
            gdi32.SetTextAlign(hdc, TA_RIGHT)
            gdi32.TextOutW(hdc, w - m, self._hdr_y + 6, "点会话打开", len("点会话打开"))
            gdi32.SetTextAlign(hdc, TA_LEFT)
            # 分隔线
            pen = gdi32.CreatePen(0, 1, self.C_SEP)
            old_pp = gdi32.SelectObject(hdc, pen)
            gdi32.MoveToEx(hdc, m, self._sep1, None)
            gdi32.LineTo(hdc, w - m, self._sep1)
            gdi32.SelectObject(hdc, old_pp)
            gdi32.DeleteObject(pen)
            # 行
            idx = 0
            for (x0, y0, x1, y1, kind, val) in self._rows:
                if kind == "row" and idx < len(lst):
                    d = lst[idx]
                    idx += 1
                    if self._hover == val:
                        brush = gdi32.CreateSolidBrush(self.C_ROWHOVER)
                        old_hv = gdi32.SelectObject(hdc, brush)
                        gdi32.RoundRect(hdc, x0, y0, x1, y1, 10, 10)
                        gdi32.SelectObject(hdc, old_hv)
                        gdi32.DeleteObject(brush)
                    gdi32.SelectObject(hdc, self._hfont)
                    gdi32.SetTextColor(hdc, self.C_TXT)
                    lb = d.get("label") or "未命名会话"
                    gdi32.TextOutW(hdc, x0 + 12, y0 + 14, lb, len(lb))
                    gdi32.SelectObject(hdc, self._hfont_s)
                    gdi32.SetTextColor(hdc, self.C_WEAK)
                    aged = d.get("age") or ""
                    gdi32.SetTextAlign(hdc, TA_RIGHT)
                    gdi32.TextOutW(hdc, x1 - 12, y0 + 15, aged, len(aged))
                    gdi32.SetTextAlign(hdc, TA_LEFT)
                    gdi32.SetTextColor(hdc, self.C_SUB)
                    md = d.get("model") or ""
                    gdi32.TextOutW(hdc, x0 + 12, y0 + 34, md, len(md))
                    tkx = d.get("tokens_text") or ""
                    gdi32.SetTextColor(hdc, self.C_TXT)
                    gdi32.SetTextAlign(hdc, TA_RIGHT)
                    gdi32.TextOutW(hdc, x1 - 12, y0 + 34, tkx, len(tkx))
                    gdi32.SetTextAlign(hdc, TA_LEFT)
                    bx0, bx1 = x0 + 12, x1 - 12
                    by = y0 + 54
                    brush = gdi32.CreateSolidBrush(self.C_BAR_BG)
                    old_bg = gdi32.SelectObject(hdc, brush)
                    gdi32.RoundRect(hdc, bx0, by, bx1, by + 5, 4, 4)
                    gdi32.SelectObject(hdc, old_bg)
                    gdi32.DeleteObject(brush)
                    pct = float(d.get("pct") or 0.0)
                    if pct > 0:
                        fill = int((bx1 - bx0) * min(pct, 1.0))
                        if pct >= 0.95:
                            cbar = self.C_BAR_R
                        elif pct >= 0.80:
                            cbar = self.C_BAR_Y
                        else:
                            cbar = self.C_BAR_G
                        brush = gdi32.CreateSolidBrush(cbar)
                        old_fl = gdi32.SelectObject(hdc, brush)
                        gdi32.RoundRect(hdc, bx0, by, bx0 + fill, by + 5, 4, 4)
                        gdi32.SelectObject(hdc, old_fl)
                        gdi32.DeleteObject(brush)
            # 空态/加载中
            if not lst:
                gdi32.SelectObject(hdc, self._hfont)
                gdi32.SetTextColor(hdc, self.C_WEAK)
                msg_txt = "正在获取会话…" if self.spec.get("loading") else "暂无会话（过去 24 小时）"
                gdi32.TextOutW(hdc, m, self._hdr_y + 56, msg_txt, len(msg_txt))
        except Exception:
            pass

    def _thread_show(self):
        try:
            if not _menu_reg_class("OcwPanelV2"):
                return
            self._calc()
            self._font()
            w, h = self._w, self._h
            class _RECT(ctypes.Structure):
                _fields_ = [("l", ctypes.c_long), ("t", ctypes.c_long),
                            ("r", ctypes.c_long), ("b", ctypes.c_long)]
            x = y = None
            try:
                user32.GetWindowRect.restype = wintypes.BOOL
                main_hwnd = user32.FindWindowW("OcwPanelV1", None)
                if main_hwnd:
                    rc = _RECT()
                    if user32.GetWindowRect(main_hwnd, ctypes.byref(rc)):
                        x = rc.l - w - 8
                        y = rc.t
                        if x < 8:
                            x = rc.r + 8
            except Exception:
                pass
            if x is None:
                pt = wintypes.POINT()
                user32.GetCursorPos(ctypes.byref(pt))
                x = max(8, pt.x - w + 8)
                y = max(8, pt.y - h - 12)
            hwnd = user32.CreateWindowExW(
                0x8 | 0x80 | WS_EX_NOACTIVATE, "OcwPanelV2", "OpenClaw", 0x80000000,
                x, y, w, h, None, None, kernel32.GetModuleHandleW(None), None)
            if not hwnd:
                _dbg("会话栏 CreateWindowExW 失败")
                return
            self._hwnd = hwnd
            self._cls_name = "OcwPanelV2"
            _MENU_INSTANCES[int(hwnd)] = self
            _MENU_ACTION_MAP[int(hwnd)] = (self.actions, self.spec)
            _dbg("会话栏创建 hwnd=%s rows=%d h=%d" % (int(hwnd), len(self._rows), self._h))
            user32.ShowWindow(hwnd, 4)   # SW_SHOWNOACTIVATE
            _mouse_listen_start()
            msg = wintypes.MSG()
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
            _dbg("会话栏消息泵退出")
        except Exception as e:
            _dbg("会话栏线程异常 %r" % e)

    def show(self):
        """并排模式：保留主面板 OcwPanelV1，只清理旧列表面板"""
        try:
            user32.GetClassNameW.restype = ctypes.c_int
            user32.GetClassNameW.argtypes = [wintypes.HWND, ctypes.c_void_p, ctypes.c_int]
        except Exception:
            pass
        for h in list(_MENU_INSTANCES.keys()):
            try:
                buf = ctypes.create_unicode_buffer(64)
                if user32.GetClassNameW(h, buf, 64) and "OcwPanelV2" in buf.value:
                    user32.PostMessageW(h, WM_CLOSE, 0, 0)
            except Exception:
                pass
        import threading as _th
        _th.Thread(target=self._thread_show, daemon=True).start()
        return None


