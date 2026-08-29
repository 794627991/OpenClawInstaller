# -*- mode: python ; coding: utf-8 -*-
# OpenClaw 一键安装器 - PyInstaller 打包配置（Web UI 版）

import os

# 项目根目录（PyInstaller exec 时用 SPECPATH 定位 spec 所在目录）
root = os.path.abspath(SPECPATH)
src_dir = os.path.join(root, "src")
web_dir = os.path.join(src_dir, "web")

# webui.py 需要同目录的 installer.py（业务核心），一起打包
a = Analysis(
    [os.path.join(src_dir, "webui.py")],
    pathex=[src_dir],               # 让 webui.py 能 import installer.py
    binaries=[],
    datas=[
        # 前端静态资源（HTML/CSS/JS）
        (web_dir, "web"),
        # 窗口图标
        (os.path.join(src_dir, "appicon.ico"), "."),
    ],
    hiddenimports=["webview", "bottle", "proxy_tools", "PIL.Image", "PIL.ImageTk",
                   "tray", "psutil", "clr", "pythonnet",
                   "tkinter", "tkinter.filedialog", "tkinter.messagebox",
                   "tkinter.scrolledtext", "tkinter.ttk"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=1,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='OpenClaw一键安装器',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,                      # 关 UPX，减少杀软误报
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=os.path.join(src_dir, "appicon.ico"),   # exe 图标
    uac_admin=True,                 # 双击直接提权（安装需管理员）
)
