#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🦞 OpenClaw 一键安装器
为电脑小白打造的图形化安装工具
"""

import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import subprocess
import threading
import os
import sys
import json
import urllib.request
import tempfile
import shutil
import webbrowser
import ctypes
import platform
from pathlib import Path

# ============================================================
# 常量
# ============================================================
APP_NAME = "🦞 OpenClaw 一键安装器"
APP_VERSION = "1.2.0"
NODE_MIN_VERSION = (22, 22, 3)
NODE_RECOMMENDED = "24.15.0"

# ============================================================
# 启动时修复 PATH（PyInstaller exe 启动时 PATH 不完整）
# ============================================================
def _fix_path():
    """从 Windows 注册表读取用户 PATH，注入当前进程"""
    if sys.platform != "win32":
        return
    user_path = ""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                r"Environment") as key:
            user_path, _ = winreg.QueryValueEx(key, "Path")
    except Exception:
        pass
    # npm 全局目录：优先读 ~/.npmrc 的 prefix（安装时可重定向到 D:\openclaw\npm）
    npm_dirs = []
    try:
        rc = Path.home() / ".npmrc"
        if rc.exists():
            for line in rc.read_text(encoding="utf-8", errors="ignore").splitlines():
                s = line.strip()
                if s.lower().startswith("prefix="):
                    d = s.split("=", 1)[1].strip().strip('"').strip("'")
                    if d and os.path.isdir(d):
                        npm_dirs.append(d)
    except Exception:
        pass
    # 合并：用户 PATH + npm 真实 prefix + 常见路径（PyInstaller exe 启动时 PATH 不完整）
    extra_dirs = npm_dirs + [
        str(Path.home() / "AppData" / "Roaming" / "npm"),
        str(Path.home() / "AppData" / "Local" / "OpenClaw" / "npm"),  # 无 D 盘回退目录
        r"D:\openclaw\npm",
        r"C:\openclaw\npm",
        str(Path.home() / ".openclaw" / "npm"),
        r"C:\Program Files\nodejs",
        r"C:\Program Files (x86)\nodejs",
    ]
    cur = os.environ.get("PATH", "")
    merged = user_path + os.pathsep + os.pathsep.join(extra_dirs) + os.pathsep + cur
    os.environ["PATH"] = merged

_fix_path()

# ============================================================
# 默认安装目录（优先 D 盘，无 D 盘回退 C 盘）
# ============================================================
def default_install_dir():
    """OpenClaw 程序安装目录：D:\\openclaw 优先，无 D 盘则回退用户目录"""
    if os.path.exists("D:\\"):
        return r"D:\openclaw"
    return str(Path.home() / "AppData" / "Local" / "OpenClaw")

def add_to_user_path(directory):
    """把目录写入用户 PATH（注册表 + 广播刷新），持久生效"""
    if DRY_RUN:
        return False  # 演练模式不写注册表
    if sys.platform != "win32" or not directory:
        return False
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0,
                             winreg.KEY_QUERY_VALUE | winreg.KEY_SET_VALUE)
        try:
            cur, _ = winreg.QueryValueEx(key, "Path")
        except FileNotFoundError:
            cur = ""
        norm = lambda s: os.path.normcase(s.rstrip("\\"))
        if any(norm(directory) == norm(x) for x in cur.split(";")):
            winreg.CloseKey(key)
            return True  # 已在 PATH 中
        new = (cur.rstrip(";") + ";" + directory) if cur else directory
        winreg.SetValueEx(key, "Path", 0, winreg.REG_EXPAND_SZ, new)
        winreg.CloseKey(key)
        # 广播 WM_SETTINGCHANGE，让已打开的终端/资源管理器立即感知
        ctypes.windll.user32.SendMessageW(0xFFFF, 0x001A, 0, None)
        return True
    except Exception:
        return False

# ============================================================
# 管理员权限（npm 全局安装 / Node.js MSI / 守护进程都需要提权）
# ============================================================
def _is_admin():
    """当前进程是否以管理员权限运行"""
    if sys.platform != "win32":
        return True
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return True

def _ensure_admin():
    """非管理员时弹 UAC 重新以管理员启动（用户只需点「是」）"""
    if sys.platform != "win32" or _is_admin():
        return
    if getattr(sys, "frozen", False):
        params = None  # PyInstaller exe：无额外参数
    else:
        params = subprocess.list2cmdline(sys.argv)  # 开发模式：带上脚本路径
    try:
        ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable,
            params, None, 1)
    except Exception:
        return  # 用户取消 UAC：继续以普通权限运行，安装前会再次提示
    sys.exit(0)

MIRRORS = {
    "npm_registry": "https://registry.npmmirror.com",
    "node_dist": "https://npmmirror.com/mirrors/node",
}

# ============================================================
# 全部 AI 服务商（带获取 Key 指引）
# ============================================================
# 格式: (id, 名称, 分组, auth_choice, key_param, 需要key?,
#         官网URL, 注册步骤列表, Key格式提示, Key示例)
PROVIDERS = [
    # --- 跳过 ---
    ("", "⏭ 跳过，稍后配置", "操作", "", "", False,
     "", [], "", ""),

    # --- 🇨🇳 国产 ---
    ("deepseek", "DeepSeek", "🇨🇳 国产", "deepseek-api-key", "--deepseek-api-key", True,
     "https://platform.deepseek.com",
     ["1. 打开 platform.deepseek.com",
      "2. 点击右上角「注册」",
      "3. 用手机号注册并登录",
      "4. 左侧菜单点击「API Keys」",
      "5. 点击「创建 API Key」",
      "6. 复制生成的 Key（sk-开头）"],
     "sk- 开头的一串字符", "sk-xxxxxxxxxxxxxxxxxxxxxxxx"),

    ("zai", "Z.AI / 智谱 GLM", "🇨🇳 国产", "zai-api-key", "--zai-api-key", True,
     "https://open.bigmodel.cn",
     ["1. 打开 open.bigmodel.cn",
      "2. 点击右上角「注册」",
      "3. 用手机号注册并登录",
      "4. 点击头像进入「API密钥」",
      "5. 点击「创建新的API密钥」",
      "6. 复制生成的 Key"],
     "一串字符", "xxxxxxxxxxxxxxxxxxxxxxxx"),

    ("moonshot", "Moonshot (Kimi)", "🇨🇳 国产", "moonshot-api-key", "--moonshot-api-key", True,
     "https://platform.moonshot.cn",
     ["1. 打开 platform.moonshot.cn",
      "2. 点击右上角「注册」",
      "3. 用手机号注册并登录",
      "4. 左侧菜单点击「API Key 管理」",
      "5. 点击「新建 API Key」",
      "6. 复制生成的 Key（sk-开头）"],
     "sk- 开头的一串字符", "sk-xxxxxxxxxxxxxxxxxxxxxxxx"),

    ("minimax", "MiniMax", "🇨🇳 国产", "minimax-global-api", "--minimax-global-api-key", True,
     "https://platform.minimaxi.com",
     ["1. 打开 platform.minimaxi.com",
      "2. 点击右上角「注册」",
      "3. 用手机号注册并登录",
      "4. 左侧菜单点击「接口密钥」",
      "5. 点击「创建新密钥」",
      "6. 复制生成的 Key"],
     "一串字符", "eyJhbGciOiJSUz..."),

    ("qwen-oauth", "通义千问 Qwen", "🇨🇳 国产", "qwen-oauth", "--qwen-oauth-api-key", True,
     "https://dashscope.aliyun.com",
     ["1. 打开 dashscope.aliyun.com",
      "2. 用支付宝/淘宝账号登录",
      "3. 进入控制台",
      "4. 左侧菜单点击「API-KEY管理」",
      "5. 点击「创建」",
      "6. 复制生成的 Key（sk-开头）"],
     "sk- 开头的一串字符", "sk-xxxxxxxxxxxxxxxxxxxxxxxx"),

    ("volcengine-plan", "火山引擎 (豆包)", "🇨🇳 国产", "volcengine-api-key", "--volcengine-api-key", True,
     "https://console.volcengine.com",
     ["1. 打开 console.volcengine.com",
      "2. 注册/登录火山引擎账号",
      "3. 开通「方舟」大模型服务",
      "4. 进入方舟控制台",
      "5. 左侧点击「API Key 管理」",
      "6. 创建并复制 Key"],
     "一串字符", "xxxxxxxxxxxxxxxxxxxxxxxx"),

    ("qianfan", "百度千帆", "🇨🇳 国产", "qianfan-api-key", "--qianfan-api-key", True,
     "https://qianfan.baidubce.com",
     ["1. 打开 qianfan.baidubce.com",
      "2. 用百度账号登录",
      "3. 进入控制台",
      "4. 左侧点击「API Key」",
      "5. 创建并复制 Key"],
     "一串字符", "xxxxxxxxxxxxxxxxxxxxxxxx"),

    ("tencent-tokenhub", "腾讯 TokenHub", "🇨🇳 国产", "tencent-tokenhub-api-key", "--tencent-tokenhub-api-key", True,
     "https://console.cloud.tencent.com",
     ["1. 打开 console.cloud.tencent.com",
      "2. 注册/登录腾讯云账号",
      "3. 开通「TokenHub」服务",
      "4. 进入控制台获取 API Key"],
     "一串字符", "xxxxxxxxxxxxxxxxxxxxxxxx"),

    ("xiaomi", "小米 MiMo", "🇨🇳 国产", "xiaomi-api-key", "--xiaomi-api-key", True,
     "https://open.mi.com",
     ["1. 打开 open.mi.com",
      "2. 注册/登录小米开放平台账号",
      "3. 开通 MiMo 模型服务",
      "4. 获取 API Key"],
     "一串字符", "xxxxxxxxxxxxxxxxxxxxxxxx"),

    ("stepfun", "阶跃星辰", "🇨🇳 国产", "stepfun-api-key", "--stepfun-api-key", True,
     "https://platform.stepfun.com",
     ["1. 打开 platform.stepfun.com",
      "2. 注册并登录",
      "3. 进入控制台",
      "4. 获取 API Key"],
     "一串字符", "xxxxxxxxxxxxxxxxxxxxxxxx"),

    # --- 🌐 聚合平台 ---
    ("opencode-go", "OpenCode Go", "🌐 聚合平台", "opencode-go", "--opencode-go-api-key", True,
     "https://opencode.ai",
     ["1. 打开 opencode.ai",
      "2. 注册账号并登录",
      "3. 进入 Dashboard",
      "4. 点击「API Keys」",
      "5. 创建并复制 Key（sk-开头）"],
     "sk- 开头的一串字符", "sk-xxxxxxxxxxxxxxxxxxxxxxxx"),

    ("opencode-zen", "OpenCode Zen", "🌐 聚合平台", "opencode-zen", "--opencode-zen-api-key", True,
     "https://opencode.ai",
     ["1. 打开 opencode.ai",
      "2. 注册账号并登录",
      "3. 进入 Dashboard",
      "4. 点击「API Keys」",
      "5. 创建并复制 Key（sk-开头）"],
     "sk- 开头的一串字符", "sk-xxxxxxxxxxxxxxxxxxxxxxxx"),

    ("openrouter", "OpenRouter", "🌐 聚合平台", "openrouter-api-key", "--openrouter-api-key", True,
     "https://openrouter.ai",
     ["1. 打开 openrouter.ai",
      "2. 用 Google/GitHub 账号登录",
      "3. 进入 Settings → Keys",
      "4. 创建并复制 API Key"],
     "sk-or- 开头", "sk-or-xxxxxxxxxxxxxxxxxxxxxxxx"),

    ("clawrouter", "ClawRouter", "🌐 聚合平台", "clawrouter-api-key", "--clawrouter-api-key", True,
     "https://clawrouter.ai",
     ["1. 打开 clawrouter.ai",
      "2. 注册并登录",
      "3. 进入 Dashboard 获取 API Key"],
     "一串字符", "xxxxxxxxxxxxxxxxxxxxxxxx"),

    ("vercel-ai-gateway", "Vercel AI Gateway", "🌐 聚合平台", "ai-gateway-api-key", "--ai-gateway-api-key", True,
     "https://vercel.com",
     ["1. 打开 vercel.com",
      "2. 用 GitHub/GitLab 账号登录",
      "3. 创建项目并开启 AI Gateway",
      "4. 获取 API Key"],
     "一串字符", "xxxxxxxxxxxxxxxxxxxxxxxx"),

    # --- 🇺🇸 美国 ---
    ("openai", "OpenAI (ChatGPT)", "🇺🇸 美国", "openai-api-key", "--openai-api-key", True,
     "https://platform.openai.com",
     ["1. 打开 platform.openai.com",
      "2. 注册/登录 OpenAI 账号",
      "3. 需要绑定国际信用卡",
      "4. 左侧点击「API Keys」",
      "5. 点击「Create new secret key」",
      "6. 复制 Key（sk-开头，只显示一次！）"],
     "sk- 开头（注意：只显示一次，务必保存！）", "sk-xxxxxxxxxxxxxxxxxxxxxxxx"),

    ("anthropic", "Anthropic (Claude)", "🇺🇸 美国", "apiKey", "--anthropic-api-key", True,
     "https://console.anthropic.com",
     ["1. 打开 console.anthropic.com",
      "2. 注册/登录 Anthropic 账号",
      "3. 需要绑定国际信用卡",
      "4. 左侧点击「API Keys」",
      "5. 点击「Create Key」",
      "6. 复制 Key（sk-ant-开头）"],
     "sk-ant- 开头的一串字符", "sk-ant-xxxxxxxxxxxxxxxxxxxxxxxx"),

    ("google", "Google Gemini", "🇺🇸 美国", "gemini-api-key", "--gemini-api-key", True,
     "https://aistudio.google.com",
     ["1. 打开 aistudio.google.com",
      "2. 用 Google 账号登录",
      "3. 点击「Get API key」",
      "4. 创建并复制 Key（AIza 开头）"],
     "AIza 开头的一串字符", "AIzaSyxxxxxxxxxxxxxxxxxxxxxxxx"),

    ("xai", "xAI (Grok)", "🇺🇸 美国", "xai-api-key", "--xai-api-key", True,
     "https://console.x.ai",
     ["1. 打开 console.x.ai",
      "2. 注册/登录 xAI 账号",
      "3. 进入 API Keys 页面",
      "4. 创建并复制 Key"],
     "一串字符", "xai-xxxxxxxxxxxxxxxxxxxxxxxx"),

    ("cohere", "Cohere", "🇺🇸 美国", "cohere-api-key", "--cohere-api-key", True,
     "https://dashboard.cohere.com",
     ["1. 打开 dashboard.cohere.com",
      "2. 注册/登录",
      "3. 进入 API Keys 页面",
      "4. 创建并复制 Key"],
     "一串字符", "xxxxxxxxxxxxxxxxxxxxxxxx"),

    ("groq", "Groq", "🇺🇸 美国", "groq-api-key", "--groq-api-key", True,
     "https://console.groq.com",
     ["1. 打开 console.groq.com",
      "2. 用 Google/GitHub 账号登录",
      "3. 进入 API Keys 页面",
      "4. 创建并复制 Key（gsk_开头）"],
     "gsk_ 开头的一串字符", "gsk_xxxxxxxxxxxxxxxxxxxxxxxx"),

    ("mistral", "Mistral AI", "🇺🇸 美国", "mistral-api-key", "--mistral-api-key", True,
     "https://console.mistral.ai",
     ["1. 打开 console.mistral.ai",
      "2. 注册/登录",
      "3. 进入 API Keys 页面",
      "4. 创建并复制 Key"],
     "一串字符", "xxxxxxxxxxxxxxxxxxxxxxxx"),

    ("nvidia", "NVIDIA NIM", "🇺🇸 美国", "nvidia-api-key", "--nvidia-api-key", True,
     "https://build.nvidia.com",
     ["1. 打开 build.nvidia.com",
      "2. 注册/登录 NVIDIA 账号",
      "3. 选择模型点击「Get API Key」",
      "4. 复制 Key（nvapi-开头）"],
     "nvapi- 开头的一串字符", "nvapi-xxxxxxxxxxxxxxxxxxxxxxxx"),

    # --- 🌍 其他 ---
    ("deepinfra", "DeepInfra", "🌍 其他", "deepinfra-api-key", "--deepinfra-api-key", True,
     "https://deepinfra.com",
     ["1. 打开 deepinfra.com",
      "2. 用 Google/GitHub 账号登录",
      "3. 进入 API Keys 页面",
      "4. 创建并复制 Key"],
     "一串字符", "xxxxxxxxxxxxxxxxxxxxxxxx"),

    ("together", "Together AI", "🌍 其他", "together-api-key", "--together-api-key", True,
     "https://api.together.xyz",
     ["1. 打开 api.together.xyz",
      "2. 用 Google/GitHub 账号登录",
      "3. 进入 Settings → API Keys",
      "4. 创建并复制 Key"],
     "一串字符", "xxxxxxxxxxxxxxxxxxxxxxxx"),

    ("cerebras", "Cerebras", "🌍 其他", "cerebras-api-key", "--cerebras-api-key", True,
     "https://cloud.cerebras.ai",
     ["1. 打开 cloud.cerebras.ai",
      "2. 注册/登录",
      "3. 进入 API Keys 页面",
      "4. 创建并复制 Key"],
     "一串字符", "xxxxxxxxxxxxxxxxxxxxxxxx"),

    ("huggingface", "Hugging Face", "🌍 其他", "huggingface-api-key", "--huggingface-api-key", True,
     "https://huggingface.co",
     ["1. 打开 huggingface.co",
      "2. 注册/登录",
      "3. 点击头像 → Settings → Access Tokens",
      "4. 创建并复制 Token"],
     "hf_ 开头的一串字符", "hf_xxxxxxxxxxxxxxxxxxxxxxxx"),

    ("ollama", "Ollama (本地运行)", "🏠 本地", "", "", False,
     "https://ollama.com",
     ["1. 打开 ollama.com/download",
      "2. 下载 Windows 版本",
      "3. 安装后运行 ollama pull 拉取模型",
      "4. 无需 API Key，本地运行"],
     "无需 Key", ""),

    ("lmstudio", "LM Studio (本地运行)", "🏠 本地", "", "", False,
     "https://lmstudio.ai",
     ["1. 打开 lmstudio.ai",
      "2. 下载 Windows 版本",
      "3. 安装后搜索并下载模型",
      "4. 无需 API Key，本地运行"],
     "无需 Key", ""),
]


# ============================================================
# 颜色主题
# ============================================================
COLORS = {
    "bg": "#1e1e2e",
    "card": "#2d2d44",
    "accent": "#f38ba8",
    "accent_hover": "#f5a0bc",
    "text": "#cdd6f4",
    "text_dim": "#6c7086",
    "success": "#a6e3a1",
    "error": "#f38ba8",
    "warning": "#f9e2af",
    "input_bg": "#313244",
    "border": "#45475a",
    "link": "#89b4fa",
}


# ============================================================
# 工具函数
# ============================================================
def _run_quiet(cmd, timeout=10):
    """静默运行命令并返回结果（shell=True 以支持 npm.cmd / openclaw.cmd）"""
    try:
        return subprocess.run(cmd, shell=True, capture_output=True, text=True,
            timeout=timeout, env=os.environ, encoding=_console_encoding(),
            errors="replace",
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)
    except Exception:
        return None

def get_node_version():
    r = _run_quiet("node --version")
    if r and r.returncode == 0:
        ver = r.stdout.strip().lstrip("v")
        return tuple(int(x) for x in ver.split(".")[:3]), ver
    return None, None

def get_npm_version():
    r = _run_quiet("npm --version")
    if r and r.returncode == 0:
        return r.stdout.strip()
    return None

def get_openclaw_version():
    """OpenClaw 版本：优先读 package.json（秒回），CLI 兜底（缓存）"""
    if "_claw_ver_cache" in globals() and globals()["_claw_ver_cache"]:
        return globals()["_claw_ver_cache"]
    # 1) 读 npm 全局目录的 package.json（不启动 node）
    for d in _candidate_npm_dirs():
        pkg = os.path.join(d, "node_modules", "openclaw", "package.json")
        try:
            if os.path.exists(pkg):
                ver = json.load(open(pkg, encoding="utf-8")).get("version")
                if ver:
                    globals()["_claw_ver_cache"] = "OpenClaw " + ver
                    return globals()["_claw_ver_cache"]
        except Exception:
            pass
    # 2) CLI 兜底
    r = _run_quiet("openclaw --version", timeout=20)
    if r and r.returncode == 0:
        v = r.stdout.strip().splitlines()
        v = "\n".join(v) if v else ""
        # 从末行提取 "OpenClaw X (y)"
        import re as _re
        m = _re.search(r"OpenClaw\s+([\d.\-a-zA-Z\(\) ]+)", v)
        ver = "OpenClaw " + m.group(1).strip() if m else v
        globals()["_claw_ver_cache"] = ver
        return ver
    return None

def _candidate_npm_dirs():
    """可能存在的 npm 全局目录（prefix 重定向后位置不定）"""
    dirs = [
        str(Path.home() / "AppData" / "Roaming" / "npm"),
        str(Path.home() / "AppData" / "Local" / "OpenClaw" / "npm"),
        r"D:\openclaw\npm",
        r"C:\openclaw\npm",
    ]
    # 读 ~/.npmrc prefix
    try:
        rc = Path.home() / ".npmrc"
        if rc.exists():
            for line in rc.read_text(encoding="utf-8", errors="ignore").splitlines():
                s = line.strip()
                if s.lower().startswith("prefix="):
                    dirs.insert(0, s.split("=", 1)[1].strip().strip('"').strip("'"))
    except Exception:
        pass
    return dirs

def check_network():
    try:
        r = urllib.request.urlopen(urllib.request.Request(MIRRORS["npm_registry"], method="HEAD"), timeout=5)
        return r.status == 200
    except Exception:
        return False

def download_file(url, path, progress=None, timeout=120):
    """分块下载（每次读写带超时，避免 urlretrieve 挂死）；
    progress(块数, 块大小, 总大小)；超时抛异常"""
    try:
        r = urllib.request.urlopen(url, timeout=timeout)
    except Exception as e:
        raise Exception("下载连接失败: %s" % e)
    total = int(r.headers.get("Content-Length") or 0)
    n = 0
    buf = 1024 * 256
    import time as _t
    last = _t.time()
    with open(path, "wb") as f:
        while True:
            if _t.time() - last > 60:
                raise Exception("下载超时（60 秒无数据），已中止")
            try:
                chunk = r.read(buf)
            except Exception as e:
                raise Exception("下载中断: %s" % e)
            if not chunk:
                break
            f.write(chunk)
            n += len(chunk)
            last = _t.time()
            if progress:
                progress(n, buf, total)
    return n

# 演练模式：OPENCLAW_DRY_RUN=1 时仅「安装动作」不执行（Node 安装 / npm -g / 写全局配置），
# 其余功能（模型切换/增删/Gateway 修复/控制面板）与正式版一致——工具可当正常启动器使用
DRY_RUN = os.environ.get("OPENCLAW_DRY_RUN") == "1"

def _console_encoding():
    """Windows 中文控制台常见 GBK；npm/msiexec 输出编码跟随系统代码页。
    自动探测（chcp 输出或直接回退 gbk）"""
    if sys.platform != "win32":
        return "utf-8"
    try:
        r = subprocess.run(["chcp"], capture_output=True,
                           text=True, encoding="utf-8", errors="replace", timeout=5)
        import re as _re
        m = _re.search(r"(\d+)", r.stdout or "")
        if m:
            cpd = int(m.group(1))
            if cpd == 65001:
                return "utf-8"
            if cpd == 936:
                return "gbk"
    except Exception:
        pass
    return "gbk" if sys.platform == "win32" else "utf-8"

def run_cmd(cmd, callback=None, timeout=90):
    """执行命令并实时回传输出；超时强制终止（VM 上 openclaw 命令可能挂起，必须有兜底）"""
    try:
        si = None
        if sys.platform == "win32":
            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            si.wShowWindow = subprocess.SW_HIDE
        enc = _console_encoding()
        p = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding=enc, errors="replace", startupinfo=si,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)
        # 读取输出 + 超时控制。
        # 注意：gateway start/stop 等经 cmd.exe → node 守护进程会继承 stdout 管道，
        # cmd 退出后管道不关闭，reader 里 for 循环会永久阻塞（线程泄漏）——
        # 用 readline + 总超时轮询代替 for 循环
        import queue as _q
        def _reader():
            import time as _t
            deadline = _t.time() + max(10, timeout) + 10
            try:
                while _t.time() < deadline:
                    line = p.stdout.readline()
                    if not line:
                        break
                    if callback:
                        callback(line.rstrip("\n"))
            finally:
                try:
                    p.stdout.close()
                except Exception:
                    pass
        _th = threading.Thread(target=_reader, daemon=True)
        _th.start()
        try:
            p.wait(timeout=max(10, timeout))
        except subprocess.TimeoutExpired:
            p.kill()
            p.wait(timeout=5)
            if callback:
                callback(f"⚠️ 命令超时（>{timeout}s）已强制终止")
            return -2
        _th.join(timeout=5)
        return p.returncode
    except Exception as e:
        if callback:
            callback(f"❌ 执行失败: {e}")
        return -1


# ============================================================
# 搜索下拉框
# ============================================================
class SearchableCombobox(tk.Frame):
    def __init__(self, parent, items, callback=None):
        super().__init__(parent, bg=COLORS["bg"])
        self.items = items
        self.callback = callback

        self.search_entry = tk.Entry(self,
            font=("Microsoft YaHei UI", 10), bg=COLORS["input_bg"], fg=COLORS["text_dim"],
            insertbackground=COLORS["text"], relief=tk.FLAT, bd=5)
        self.search_entry.pack(fill=tk.X)
        self.search_entry.insert(0, "🔍 输入关键词搜索服务商（如：deep、claude、kimi）")
        self.search_entry.bind("<FocusIn>", self._focus_in)
        self.search_entry.bind("<FocusOut>", self._focus_out)
        self.search_entry.bind("<KeyRelease>", self._filter)

        lf = tk.Frame(self, bg=COLORS["card"])
        lf.pack(fill=tk.BOTH, expand=True, pady=(2, 0))
        self.listbox = tk.Listbox(lf, font=("Microsoft YaHei UI", 10),
            bg=COLORS["card"], fg=COLORS["text"], selectbackground=COLORS["accent"],
            selectforeground="white", relief=tk.FLAT, bd=0, highlightthickness=0)
        self.listbox.pack(fill=tk.BOTH, expand=True)
        self.listbox.bind("<<ListboxSelect>>", self._on_select)
        self._populate(items)

    def _focus_in(self, e):
        if self.search_entry.get().startswith("🔍"):
            self.search_entry.delete(0, tk.END)
            self.search_entry.config(fg=COLORS["text"])

    def _focus_out(self, e):
        if not self.search_entry.get():
            self.search_entry.config(fg=COLORS["text_dim"])
            self.search_entry.insert(0, "🔍 输入关键词搜索服务商（如：deep、claude、kimi）")

    def _populate(self, items):
        self.listbox.delete(0, tk.END)
        self._visible = []
        cur_group = ""
        for p in items:
            pid, name, group = p[0], p[1], p[2]
            if group != cur_group:
                self.listbox.insert(tk.END, f"── {group} ──")
                self.listbox.itemconfig(tk.END, fg=COLORS["text_dim"])
                cur_group = group
            self.listbox.insert(tk.END, f"  {name}")
            self._visible.append(p)

    def _filter(self, *args):
        q = self.search_entry.get().lower()
        if q.startswith("🔍"):
            q = ""
        filtered = [p for p in self.items if q in p[1].lower() or q in p[0].lower() or q in p[2].lower()]
        self._populate(filtered)

    def _on_select(self, e):
        sel = self.listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        text = self.listbox.get(idx)
        if text.startswith("──"):
            return
        # 计算真实索引
        real = 0
        for i, t in enumerate(self.listbox.get(0, tk.END)):
            if i == idx:
                break
            if not t.startswith("──"):
                real += 1
        if real < len(self._visible):
            p = self._visible[real]
            self.search_entry.delete(0, tk.END)
            self.search_entry.insert(0, p[1])
            self.search_entry.config(fg=COLORS["text"])
            if self.callback:
                self.callback(p)


# ============================================================
# 主程序
# ============================================================
class OpenClawInstaller(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_NAME)
        self.geometry("750x650")
        self.resizable(False, False)
        self.configure(bg=COLORS["bg"])

        # 仅支持 64 位系统（Node.js MSI 为 x64 版本）
        if sys.platform == "win32" and platform.machine().lower() not in ("amd64", "x86_64"):
            messagebox.showwarning("系统不支持",
                "本安装器仅支持 64 位 Windows 系统。\n\n"
                "您的系统为 32 位，无法安装，请使用 64 位电脑。")
            self.destroy()
            sys.exit(0)

        self.prereq_done = False      # 环境检测是否完成
        self.prereq_ok = {}           # 检测结果 {"network": bool, "node": bool, ...}
        self._disk_warned = False     # 磁盘空间警告只提示一次（重试时不再弹）

        self.update_idletasks()
        x = (self.winfo_screenwidth() - 750) // 2
        y = (self.winfo_screenheight() - 650) // 2
        self.geometry(f"+{x}+{y}")

        self.current_step = 0
        # OpenClaw 程序安装目录（npm prefix 重定向，优先 D 盘）
        self.install_dir = default_install_dir()
        self.selected_provider = None  # 完整 provider tuple
        self.api_key = tk.StringVar()
        self.is_installing = False

        self.style = ttk.Style()
        self.style.theme_use("clam")
        self._configure_styles()

        self.main_frame = tk.Frame(self, bg=COLORS["bg"])
        self.main_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)

        self.pages = {}
        self._create_pages()
        self._create_bottom_bar()
        self.show_page("welcome")

    def _configure_styles(self):
        self.style.configure("TButton", background=COLORS["accent"], foreground="white",
            font=("Microsoft YaHei UI", 10, "bold"), padding=(20, 8))
        self.style.map("TButton", background=[("active", COLORS["accent_hover"])])
        self.style.configure("TSecondary.TButton", background=COLORS["border"],
            foreground=COLORS["text"], font=("Microsoft YaHei UI", 9), padding=(15, 6))
        self.style.configure("TLabel", background=COLORS["bg"], foreground=COLORS["text"],
            font=("Microsoft YaHei UI", 10))
        self.style.configure("Title.TLabel", font=("Microsoft YaHei UI", 18, "bold"),
            foreground=COLORS["accent"])
        self.style.configure("TProgressbar", background=COLORS["accent"],
            troughcolor=COLORS["border"])

    def _create_bottom_bar(self):
        bottom = tk.Frame(self, bg=COLORS["bg"], height=50)
        bottom.pack(fill=tk.X, side=tk.BOTTOM, padx=20, pady=(0, 10))
        self.btn_prev = ttk.Button(bottom, text="◀ 上一步", style="TSecondary.TButton",
            command=self.prev_step)
        self.btn_next = ttk.Button(bottom, text="下一步 ▶", command=self.next_step)
        self.btn_next.pack(side=tk.RIGHT)

    def _create_pages(self):
        self._create_welcome_page()
        self._create_prereq_page()
        self._create_dir_page()
        self._create_install_page()
        self._create_config_page()
        self._create_complete_page()

    # ---- 欢迎页 ----
    def _create_welcome_page(self):
        page = tk.Frame(self.main_frame, bg=COLORS["bg"])
        self.pages["welcome"] = page
        tk.Label(page, text="🦞", font=("Segoe UI Emoji", 60), bg=COLORS["bg"],
                 fg=COLORS["accent"]).pack(pady=(30, 10))
        ttk.Label(page, text="OpenClaw 一键安装器", style="Title.TLabel",
                 background=COLORS["bg"]).pack()
        tk.Label(page, text=f"v{APP_VERSION}", font=("Microsoft YaHei UI", 9),
                 bg=COLORS["bg"], fg=COLORS["text_dim"]).pack(pady=(5, 15))

        info = tk.Frame(page, bg=COLORS["card"], padx=20, pady=15)
        info.pack(fill=tk.X, padx=30)
        tk.Label(info, text="📋 安装步骤：", bg=COLORS["card"], fg=COLORS["text"],
                 font=("Microsoft YaHei UI", 10, "bold")).pack(anchor="w")
        for t in ["  1️⃣  检测并安装 Node.js 运行环境",
                  "  2️⃣  安装 OpenClaw 主程序",
                  "  3️⃣  选择 AI 服务商 + 填入 API Key",
                  "  4️⃣  自动配置 Gateway + 安装技能"]:
            tk.Label(info, text=t, bg=COLORS["card"], fg=COLORS["text"],
                     font=("Microsoft YaHei UI", 10)).pack(anchor="w", pady=3)
        tk.Label(info, text="⏱️ 全程约 3-5 分钟 | 🖱️ 只需点击几下 | 🇨🇳 国内镜像加速",
                 bg=COLORS["card"], fg=COLORS["warning"],
                 font=("Microsoft YaHei UI", 9)).pack(anchor="w", pady=(10, 0))

    # ---- 环境检测 ----
    def _create_prereq_page(self):
        page = tk.Frame(self.main_frame, bg=COLORS["bg"])
        self.pages["prereq"] = page
        ttk.Label(page, text="🔍 环境检测", style="Title.TLabel",
                 background=COLORS["bg"]).pack(pady=(15, 10))
        pf = tk.Frame(page, bg=COLORS["card"], padx=20, pady=15)
        pf.pack(fill=tk.X, padx=30, pady=10)
        self.prereq_labels = {}
        for key, icon, label in [("network","🌐","网络连接"),("node","📦","Node.js"),
                                  ("npm","📋","npm"),("openclaw","🦞","OpenClaw")]:
            f = tk.Frame(pf, bg=COLORS["card"])
            f.pack(fill=tk.X, pady=5)
            tk.Label(f, text=f"{icon} {label}", bg=COLORS["card"], fg=COLORS["text"],
                     font=("Microsoft YaHei UI", 10)).pack(side=tk.LEFT)
            self.prereq_labels[key] = tk.Label(f, text="检测中...", bg=COLORS["card"],
                     fg=COLORS["warning"], font=("Microsoft YaHei UI", 10))
            self.prereq_labels[key].pack(side=tk.RIGHT)
        tk.Label(page, text="💡 未安装的组件将自动安装，无需手动操作",
                 bg=COLORS["bg"], fg=COLORS["text_dim"],
                 font=("Microsoft YaHei UI", 9)).pack(pady=10)

    # ---- 安装位置（默认 D 盘，可修改；小白可直接跳过） ----
    def _create_dir_page(self):
        page = tk.Frame(self.main_frame, bg=COLORS["bg"])
        self.pages["dir"] = page
        ttk.Label(page, text="📦 安装位置", style="Title.TLabel",
                 background=COLORS["bg"]).pack(pady=(15, 10))
        tk.Label(page, text="默认安装到 D 盘（避免占用 C 盘空间），可自行修改",
                 bg=COLORS["bg"], fg=COLORS["text_dim"],
                 font=("Microsoft YaHei UI", 9)).pack()

        df = tk.Frame(page, bg=COLORS["card"], padx=15, pady=15)
        df.pack(fill=tk.X, padx=30, pady=15)
        self.dir_var = tk.StringVar(value=self.install_dir)
        tk.Entry(df, textvariable=self.dir_var, font=("Consolas", 10),
            bg=COLORS["input_bg"], fg=COLORS["text"], insertbackground=COLORS["text"],
            relief=tk.FLAT, bd=5, width=45).pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(df, text="浏览...", style="TSecondary.TButton",
            command=self._browse_dir).pack(side=tk.RIGHT, padx=(10, 0))

        info_f = tk.Frame(page, bg=COLORS["card"], padx=20, pady=10)
        info_f.pack(fill=tk.X, padx=30, pady=(0, 5))
        for icon, name, detail in [
            ("📦", "Node.js", "自动检测，缺失时自动安装"),
            ("🦞", "OpenClaw 主程序", "安装到上方目录的 npm 子目录，自动写入环境变量"),
            ("📁", "数据/配置", str(Path.home() / ".openclaw")),
        ]:
            f = tk.Frame(info_f, bg=COLORS["card"])
            f.pack(fill=tk.X, pady=3)
            tk.Label(f, text=f"{icon} {name}：", bg=COLORS["card"],
                     fg=COLORS["text"], font=("Microsoft YaHei UI", 10, "bold"),
                     anchor="w").pack(side=tk.LEFT)
            tk.Label(f, text=detail, bg=COLORS["card"], fg=COLORS["text_dim"],
                     font=("Microsoft YaHei UI", 9), anchor="w",
                     wraplength=440, justify=tk.LEFT).pack(side=tk.LEFT, padx=(6, 0))

        # C/D 盘剩余空间实时展示
        space_f = tk.Frame(page, bg=COLORS["card"], padx=20, pady=8)
        space_f.pack(fill=tk.X, padx=30, pady=(0, 5))
        tk.Label(space_f, text="💾 磁盘剩余空间：", bg=COLORS["card"],
                 fg=COLORS["text"], font=("Microsoft YaHei UI", 9, "bold")).pack(side=tk.LEFT)
        for drive, label in [("C:", "C 盘"), ("D:", "D 盘")]:
            try:
                free_gb = shutil.disk_usage(drive + "\\").free / (1024**3)
                color = COLORS["error"] if free_gb < 1 else COLORS["success"]
            except Exception:
                free_gb, color = None, COLORS["text_dim"]
            txt = f"{label}: {free_gb:.1f} GB" if free_gb is not None else f"{label}: 无"
            tk.Label(space_f, text=txt, bg=COLORS["card"], fg=color,
                     font=("Microsoft YaHei UI", 9)).pack(side=tk.LEFT, padx=(8, 0))

        tk.Label(page, text="💡 保持默认即可，直接点击右下角「开始安装」",
                 bg=COLORS["bg"], fg=COLORS["warning"],
                 font=("Microsoft YaHei UI", 9)).pack(pady=5)

    def _browse_dir(self):
        from tkinter import filedialog
        d = filedialog.askdirectory(initialdir=self.install_dir)
        if d:
            self.dir_var.set(d)

    # ---- 安装进度 ----
    def _create_install_page(self):
        page = tk.Frame(self.main_frame, bg=COLORS["bg"])
        self.pages["install"] = page
        ttk.Label(page, text="⚙️ 正在安装", style="Title.TLabel",
                 background=COLORS["bg"]).pack(pady=(15, 10))
        self.progress = ttk.Progressbar(page, length=550, mode="determinate",
            style="TProgressbar")
        self.progress.pack(pady=10)
        self.progress_label = tk.Label(page, text="准备中...", bg=COLORS["bg"],
            fg=COLORS["text"], font=("Microsoft YaHei UI", 10))
        self.progress_label.pack(pady=5)
        lf = tk.Frame(page, bg=COLORS["input_bg"], padx=5, pady=5)
        lf.pack(fill=tk.BOTH, expand=True, padx=30, pady=10)
        self.log_text = scrolledtext.ScrolledText(lf, font=("Consolas", 9),
            bg=COLORS["input_bg"], fg=COLORS["text"], insertbackground=COLORS["text"],
            relief=tk.FLAT, state=tk.DISABLED, height=12)
        self.log_text.pack(fill=tk.BOTH, expand=True)

    # ============================================================
    # 配置页（重点：手把手拿 Key 指引）
    # ============================================================
    def _create_config_page(self):
        page = tk.Frame(self.main_frame, bg=COLORS["bg"])
        self.pages["config"] = page
        ttk.Label(page, text="🔑 配置 AI 模型", style="Title.TLabel",
                 background=COLORS["bg"]).pack(pady=(8, 3))
        tk.Label(page, text="选择服务商 → 获取 API Key → 填入下方",
                 bg=COLORS["bg"], fg=COLORS["text"]).pack()

        # 左右分栏：左边选择+填Key，右边指引
        body = tk.Frame(page, bg=COLORS["bg"])
        body.pack(fill=tk.BOTH, expand=True, padx=15, pady=5)

        # ---- 左栏：选择 + Key 输入 ----
        left = tk.Frame(body, bg=COLORS["bg"], width=340)
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        left.pack_propagate(False)

        sf = tk.Frame(left, bg=COLORS["card"], padx=10, pady=8)
        sf.pack(fill=tk.X)
        tk.Label(sf, text="① 选择服务商：", bg=COLORS["card"], fg=COLORS["text"],
                 font=("Microsoft YaHei UI", 10, "bold")).pack(anchor="w")
        self.provider_selector = SearchableCombobox(sf, PROVIDERS,
            callback=self._on_provider_selected)
        self.provider_selector.pack(fill=tk.X, pady=(3, 0))

        kf = tk.Frame(left, bg=COLORS["card"], padx=10, pady=8)
        kf.pack(fill=tk.X, pady=(3, 0))
        self.key_label = tk.Label(kf, text="② 填入 API Key：", bg=COLORS["card"],
                 fg=COLORS["text"], font=("Microsoft YaHei UI", 10, "bold"))
        self.key_label.pack(anchor="w")
        self.key_entry = tk.Entry(kf, textvariable=self.api_key, font=("Consolas", 11),
            bg=COLORS["input_bg"], fg=COLORS["text"], insertbackground=COLORS["text"],
            relief=tk.FLAT, bd=5, show="*")
        self.key_entry.pack(fill=tk.X, pady=3)
        kf2 = tk.Frame(kf, bg=COLORS["card"])
        kf2.pack(fill=tk.X)
        self.show_key = False
        self.toggle_btn = tk.Button(kf2, text="👁 显示", bg=COLORS["border"], fg=COLORS["text"],
            font=("Microsoft YaHei UI", 8), relief=tk.FLAT, command=self._toggle_key)
        self.toggle_btn.pack(side=tk.LEFT)
        self.key_format_label = tk.Label(kf2, text="", bg=COLORS["card"],
            fg=COLORS["text_dim"], font=("Microsoft YaHei UI", 8))
        self.key_format_label.pack(side=tk.RIGHT)

        # 验证按钮
        self.btn_verify = tk.Button(left, text="🔍 验证 Key 是否正确", bg=COLORS["border"],
            fg=COLORS["text"], font=("Microsoft YaHei UI", 9, "bold"), relief=tk.FLAT,
            padx=15, pady=5, command=self._verify_key)
        self.btn_verify.pack(pady=8)
        self.verify_result = tk.Label(left, text="", bg=COLORS["bg"],
            font=("Microsoft YaHei UI", 9))
        self.verify_result.pack()

        # ---- 右栏：获取 Key 指引 ----
        right = tk.Frame(body, bg=COLORS["card"], padx=10, pady=8, width=360)
        right.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=(3, 0))
        right.pack_propagate(False)

        self.guide_title = tk.Label(right, text="📖 如何获取 API Key", bg=COLORS["card"],
            fg=COLORS["accent"], font=("Microsoft YaHei UI", 11, "bold"))
        self.guide_title.pack(anchor="w")

        self.guide_url = tk.Label(right, text="请先选择一个服务商", bg=COLORS["card"],
            fg=COLORS["link"], font=("Microsoft YaHei UI", 9, "underline"))
        self.guide_url.pack(anchor="w", pady=(3, 5))
        self.guide_url.bind("<Button-1>", self._open_guide_url)

        guide_scroll = tk.Frame(right, bg=COLORS["card"])
        guide_scroll.pack(fill=tk.BOTH, expand=True)
        self.guide_text = tk.Text(guide_scroll, font=("Microsoft YaHei UI", 9),
            bg=COLORS["card"], fg=COLORS["text"], relief=tk.FLAT, wrap=tk.WORD,
            state=tk.DISABLED, cursor="arrow")
        self.guide_text.pack(fill=tk.BOTH, expand=True)

    def _on_provider_selected(self, provider):
        """选中服务商后更新右侧指引"""
        self.selected_provider = provider
        pid, name, group, auth_choice, key_param, needs_key = provider[:6]
        url = provider[6] if len(provider) > 6 else ""
        steps = provider[7] if len(provider) > 7 else []
        fmt = provider[8] if len(provider) > 8 else ""

        # 更新 Key 输入区
        if not needs_key or not pid:
            self.key_entry.pack_forget()
            self.toggle_btn.pack_forget()
            self.key_format_label.config(text="⏭ 已选择跳过" if not pid else "ℹ️ 本地运行，无需 Key")
            self.btn_verify.pack_forget()
        else:
            self.key_entry.pack(fill=tk.X, pady=3)
            self.toggle_btn.pack(side=tk.LEFT)
            self.key_format_label.config(text=f"格式：{fmt}" if fmt else "")
            self.btn_verify.pack(pady=8)

        # 更新右侧指引
        self.guide_title.config(text=f"📖 {name} — 获取 API Key 步骤")
        if url:
            self.guide_url.config(text=f"🔗 {url}")
            self._current_guide_url = url
        else:
            self.guide_url.config(text="")
            self._current_guide_url = ""

        self.guide_text.config(state=tk.NORMAL)
        self.guide_text.delete("1.0", tk.END)
        if steps:
            self.guide_text.insert("1.0", "\n".join(steps))
        elif not pid:
            self.guide_text.insert("1.0",
                "⏭ 跳过配置\n\n"
                "您可以跳过此步骤，稍后运行以下命令配置：\n\n"
                "  openclaw configure\n\n"
                "但建议现在就配置好，否则安装完成后无法使用 AI 对话功能。")
        else:
            self.guide_text.insert("1.0", "ℹ️ 此服务商无需 API Key\n\n本地运行的模型服务，\n安装后即可直接使用。")
        self.guide_text.config(state=tk.DISABLED)
        self.verify_result.config(text="")

    def _open_guide_url(self, event):
        if hasattr(self, "_current_guide_url") and self._current_guide_url:
            webbrowser.open(self._current_guide_url)

    def _toggle_key(self):
        self.show_key = not self.show_key
        self.key_entry.config(show="" if self.show_key else "*")
        self.toggle_btn.config(text="🙈 隐藏" if self.show_key else "👁 显示")

    def _verify_key(self):
        """验证 API Key 是否有效"""
        key = self.api_key.get().strip()
        if not key:
            self.verify_result.config(text="❌ 请先填入 API Key", fg=COLORS["error"])
            return
        if not self.selected_provider:
            self.verify_result.config(text="❌ 请先选择服务商", fg=COLORS["error"])
            return

        self.verify_result.config(text="⏳ 验证中...", fg=COLORS["warning"])
        self.update()

        # 后台验证
        def do_verify():
            pid = self.selected_provider[0]
            # 尝试运行 openclaw 来验证（--accept-risk 需要管理员/用户确认时静默跳过）
            result = _run_quiet(f'openclaw models list --provider {pid}')
            if result is None:
                self.after(0, lambda: self.verify_result.config(
                    text="⚠️ 无法验证，请确认 Key 是否正确", fg=COLORS["warning"]))
            elif result.returncode == 0 and "error" not in result.stdout.lower():
                self.after(0, lambda: self.verify_result.config(
                    text="✅ Key 格式正确！可以继续安装", fg=COLORS["success"]))
            else:
                self.after(0, lambda: self.verify_result.config(
                    text="⚠️ Key 可能无效，请检查后重试", fg=COLORS["warning"]))

        threading.Thread(target=do_verify, daemon=True).start()

    # ---- 完成页 ----
    def _create_complete_page(self):
        page = tk.Frame(self.main_frame, bg=COLORS["bg"])
        self.pages["complete"] = page
        tk.Label(page, text="🎉", font=("Segoe UI Emoji", 50),
                 bg=COLORS["bg"]).pack(pady=(25, 10))
        ttk.Label(page, text="安装完成！", style="Title.TLabel",
                 background=COLORS["bg"]).pack()
        info_f = tk.Frame(page, bg=COLORS["card"], padx=20, pady=15)
        info_f.pack(fill=tk.X, padx=30, pady=15)
        self.complete_info = tk.Label(info_f, text="", bg=COLORS["card"],
            fg=COLORS["text"], font=("Microsoft YaHei UI", 10), justify=tk.LEFT)
        self.complete_info.pack(anchor="w")
        self.auto_start = tk.BooleanVar(value=True)
        tk.Checkbutton(page, text="立即启动 OpenClaw", variable=self.auto_start,
            bg=COLORS["bg"], fg=COLORS["text"], selectcolor=COLORS["input_bg"],
            activebackground=COLORS["bg"], font=("Microsoft YaHei UI", 10)).pack(pady=5)
        tk.Label(page, text="💡 常用命令：\n"
                 "  openclaw dashboard        打开控制面板\n"
                 "  openclaw gateway status   查看运行状态\n"
                 "  openclaw configure        重新配置",
                 bg=COLORS["bg"], fg=COLORS["text_dim"],
                 font=("Consolas", 9), justify=tk.LEFT).pack(pady=8)

    # ============================================================
    # 页面切换
    # ============================================================
    def show_page(self, name):
        for p in self.pages.values():
            p.pack_forget()
        self.pages[name].pack(fill=tk.BOTH, expand=True)
        steps = ["welcome","prereq","dir","install","config","complete"]
        self.current_step = steps.index(name)
        if name == "welcome":
            self.btn_prev.pack_forget()
            self.btn_next.config(text="开始检测 ▶")
        elif name == "complete":
            self.btn_prev.pack_forget()
            self.btn_next.config(text="完成 ✓")
        elif name == "install":
            self.btn_prev.pack_forget()
            self.btn_next.pack_forget()
        else:
            self.btn_prev.pack(side=tk.LEFT)
            self.btn_next.config(text="开始安装 ▶" if name == "config" else "下一步 ▶")

    def prev_step(self):
        steps = ["welcome","prereq","dir","install","config","complete"]
        if self.current_step > 0:
            self.show_page(steps[self.current_step - 1])

    def next_step(self):
        steps = ["welcome","prereq","dir","install","config","complete"]
        if self.current_step == 0:
            self.show_page("prereq")
            self._run_prereq_check()
        elif self.current_step == 1:
            # 检测未完成则等待
            if not self.prereq_done:
                messagebox.showinfo("正在检测", "环境检测中，请稍等几秒再点「下一步」")
                return
            # 网络不通 → 警告，防止安装必失败
            if not self.prereq_ok.get("network"):
                if not messagebox.askyesno("网络不可用",
                    "网络连接失败，将无法下载安装包，安装几乎必然失败。\n\n"
                    "请检查网络（如使用代理/VPN，请先关闭或放行本程序）。\n\n"
                    "仍然继续吗？"):
                    return
            self.show_page("dir")
        elif self.current_step == 2:
            self.install_dir = self.dir_var.get().strip() or default_install_dir()
            self.show_page("install")
            self._start_install()
        elif self.current_step == 4:
            # 检查是否需要 Key 但没填
            if self.selected_provider and self.selected_provider[5] and not self.api_key.get().strip():
                if not messagebox.askyesno("提示",
                    "您选择了需要 API Key 的服务商，但还没有填入 Key。\n\n"
                    "没有正确的 API Key，安装完成后将无法使用 AI 对话。\n\n"
                    "确定要跳过吗？"):
                    return
            self._apply_config()
            self.show_page("complete")
        elif self.current_step == 5:
            if self.auto_start.get():
                self._start_openclaw()
            self.destroy()

    # ============================================================
    # 环境检测
    # ============================================================
    def _run_prereq_check(self):
        def check():
            for key in ["network", "node", "npm", "openclaw"]:
                self.after(0, lambda k=key: self.prereq_labels[k].config(text="检测中...", fg=COLORS["warning"]))
            # 每个组件只检测一次，避免重复运行命令
            net_ok = check_network()
            node_ver = get_node_version()
            npm_ver = get_npm_version()
            claw_ver = get_openclaw_version()

            def show(key, text, color):
                self.after(0, lambda k=key, t=text, c=color:
                           self.prereq_labels[k].config(text=t, fg=c))

            show("network", "✅ 可用" if net_ok else "❌ 无法连接",
                 COLORS["success"] if net_ok else COLORS["error"])
            vt, vs = node_ver
            if vt:
                show("node", f"✅ v{vs}", COLORS["success"] if vt >= NODE_MIN_VERSION else COLORS["warning"])
            else:
                show("node", "❌ 未安装（将自动安装）", COLORS["error"])
            if npm_ver:
                show("npm", f"✅ v{npm_ver}", COLORS["success"])
            else:
                show("npm", "❌ 未安装（随 Node.js）", COLORS["warning"])
            if claw_ver:
                show("openclaw", f"✅ {claw_ver}", COLORS["success"])
            else:
                show("openclaw", "❌ 未安装（将自动安装）", COLORS["error"])
            # 记录结果供「下一步」时校验
            self.prereq_ok = {"network": net_ok, "node": vt is not None,
                              "npm": npm_ver is not None, "openclaw": claw_ver is not None}
            self.prereq_done = True
        threading.Thread(target=check, daemon=True).start()

    # ============================================================
    # 安装流程
    # ============================================================
    def _start_install(self):
        if self.is_installing:
            return
        # 安装前确认管理员权限（启动时 UAC 可能被取消）
        if not _is_admin():
            if not messagebox.askyesno("需要管理员权限",
                "安装 Node.js / OpenClaw 需要管理员权限。\n\n"
                "是否以管理员身份重新启动安装器？"):
                return
            _ensure_admin()  # 重启；若用户取消 UAC 则继续往下走
            if not _is_admin():
                messagebox.showerror("权限不足",
                    "未获得管理员权限，无法继续安装。\n\n"
                    "请关闭本程序，然后右键图标 →「以管理员身份运行」。")
                return
        # C 盘空间检测（Node.js + npm 缓存占用 C 盘，需留足 1GB）
        if not self._disk_warned:
            try:
                sys_drive = os.environ.get("SystemDrive", "C:") + "\\"
                free_mb = shutil.disk_usage(sys_drive).free // (1024 * 1024)
                if free_mb < 1024:
                    self._disk_warned = True
                    if not messagebox.askyesno("C 盘空间不足",
                        f"系统盘 {sys_drive} 可用空间仅 {free_mb} MB。\n\n"
                        "Node.js 与 npm 缓存需要占用 C 盘约 500 MB 空间，\n"
                        "空间不足可能导致安装失败。\n\n"
                        "仍然继续吗？"):
                        return
            except Exception:
                pass
        self.is_installing = True
        threading.Thread(target=self._install_thread, daemon=True).start()

    def _install_thread(self):
        steps = [
            ("检查环境...", self._step_check_env),
            ("配置 npm 镜像...", self._step_config_npm),
            ("安装 Node.js...", self._step_install_node),
            ("安装 OpenClaw...", self._step_install_openclaw),
            ("验证安装...", self._step_verify),
        ]
        total = len(steps)
        for i, (desc, func) in enumerate(steps):
            self.after(0, lambda d=desc: self.progress_label.config(text=d))
            self.after(0, lambda v=i/total*100: self.progress.config(value=v))
            self._log(f"\n{'='*50}\n📌 {desc}\n{'='*50}")
            try:
                func()
            except Exception as e:
                self._log(f"❌ 步骤失败: {e}")
                self.after(0, lambda: self._prompt_retry(e))
                return
        self.after(0, lambda: self.progress.config(value=100))
        self.after(0, lambda: self.progress_label.config(text="✅ 安装完成！"))
        self._log("\n🎉 所有组件安装成功！")
        self.after(0, self._enable_next)

    def _prompt_retry(self, err):
        """安装失败：提供重试（已完成的步骤会自动跳过）"""
        retry = messagebox.askretrycancel("安装失败",
            f"安装过程中出错：\n\n{err}\n\n"
            "点击「重试」将重新执行失败的步骤。\n"
            "点击「取消」将跳过安装，直接进入配置页。")
        if retry:
            self.is_installing = False
            self._start_install()
        else:
            self.is_installing = False
            self.btn_next.pack(side=tk.RIGHT)
            self.show_page("config")

    def _enable_next(self):
        self.is_installing = False
        self.btn_next.pack(side=tk.RIGHT)
        self.show_page("config")

    def _log(self, msg):
        self.after(0, lambda: self._append_log(msg))

    def _append_log(self, msg):
        self.log_text.config(state=tk.NORMAL)
        self.log_text.insert(tk.END, msg + "\n")
        self.log_text.see(tk.END)
        self.log_text.config(state=tk.DISABLED)

    def _step_check_env(self):
        vt, vs = get_node_version()
        self._log(f"  ✅ Node.js v{vs} 已就绪" if vt and vt >= NODE_MIN_VERSION else "  ⚠️ Node.js 需要安装")

    def _step_config_npm(self):
        # 已是镜像则跳过（避免覆盖用户已有配置）
        r = _run_quiet("npm config get registry")
        current = r.stdout.strip() if r and r.returncode == 0 else ""
        if current == MIRRORS["npm_registry"]:
            self._log(f"  ✅ npm 镜像已配置: {current}")
        else:
            self._log(f"  设置 npm 镜像: {MIRRORS['npm_registry']}")
            self._log(f"  （原 registry: {current or '未知'}，仅下载加速，不影响使用）")
            ret1 = run_cmd(f'npm config set registry {MIRRORS["npm_registry"]}', callback=self._log)
            ret2 = run_cmd('npm config set disturl https://npmmirror.com/mirrors/node', callback=self._log)
            if ret1 != 0 or ret2 != 0:
                self._log("  ⚠️ npm 镜像配置未生效（不影响安装，仅影响下载速度）")
            else:
                self._log("  ✅ npm 镜像配置完成")

        # 全局安装目录（prefix）重定向到用户选择的目录，OpenClaw 程序装到 D 盘
        npm_dir = os.path.join(self.install_dir, "npm")
        try:
            os.makedirs(npm_dir, exist_ok=True)
        except Exception as e:
            self._log(f"  ⚠️ 无法创建目录 {npm_dir}: {e}")
        self._log(f"  设置 npm 全局目录: {npm_dir}")
        ret = run_cmd(f'npm config set prefix "{npm_dir}"', callback=self._log)
        if ret != 0:
            self._log("  ⚠️ npm 全局目录设置失败，将使用默认位置")
        else:
            # 立即注入当前进程 PATH，供本会话后续命令使用
            os.environ["PATH"] = npm_dir + os.pathsep + os.environ.get("PATH", "")
            # npm 下载缓存也挪到 D 盘，减少 C 盘占用
            cache_dir = os.path.join(self.install_dir, "npm-cache")
            try:
                os.makedirs(cache_dir, exist_ok=True)
            except Exception:
                pass
            ret = run_cmd(f'npm config set cache "{cache_dir}"', callback=self._log)
            self._log("  ✅ npm 下载缓存已移至 D 盘" if ret == 0
                      else "  ⚠️ npm 缓存目录设置失败（不影响安装）")

    def _step_install_node(self):
        vt, vs = get_node_version()
        if vt and vt >= NODE_MIN_VERSION:
            self._log(f"  跳过 - Node.js v{vs} 已安装")
            return
        self._log("  正在下载 Node.js...")
        node_ver = NODE_RECOMMENDED
        node_url = f"{MIRRORS['node_dist']}/v{node_ver}/node-v{node_ver}-x64.msi"
        msi_path = os.path.join(tempfile.gettempdir(), f"node-v{node_ver}-x64.msi")
        self._log(f"  下载: {node_url}")
        def dl_progress(block_num, block_size, total_size):
            if total_size > 0:
                pct = min(100, block_num * block_size * 100 // total_size)
                self.after(0, lambda p=pct: self.progress_label.config(text=f"下载 Node.js... {p}%"))
        try:
            urllib.request.urlretrieve(node_url, msi_path, dl_progress)
        except Exception as e:
            self._log(f"  ❌ 下载失败: {e}")
            raise
        self._log("  正在安装 Node.js（可能需要管理员权限）...")
        log_path = os.path.join(tempfile.gettempdir(), "openclaw-node-install.log")
        ret = run_cmd(f'msiexec /i "{msi_path}" /quiet /norestart /l*v "{log_path}"',
                      callback=self._log)
        if ret not in (0, 3010):  # 3010 = 安装成功但需要重启
            # 静默失败 → 改用带界面方式重试，让小白能看到安装过程
            self._log("  ⚠️ 静默安装失败，正在改用带进度界面重试...")
            self._log(f"     错误码: {ret} | 日志: {log_path}")
            ret = run_cmd(f'msiexec /i "{msi_path}" /passive /norestart',
                          callback=self._log)
        if ret not in (0, 3010):
            raise Exception(
                "Node.js 安装失败（错误码 %d）。\n\n"
                "请手动安装：\n"
                "  1. 用浏览器打开 %s\n"
                "  2. 下载 node-v%s-x64.msi 并双击安装\n"
                "  3. 安装完成后重新运行本安装器" % (ret, MIRRORS["node_dist"], node_ver))
        os.environ["PATH"] = r"C:\Program Files\nodejs" + os.pathsep + os.environ.get("PATH", "")
        try:
            os.remove(msi_path)
        except Exception:
            pass
        vt, vs = get_node_version()
        self._log(f"  ✅ Node.js v{vs} 安装成功" if vt else "  ⚠️ 安装完成，可能需要重启电脑后生效")

    def _step_install_openclaw(self):
        ov = get_openclaw_version()
        if ov:
            self._log(f"  跳过 - OpenClaw {ov} 已安装")
            return
        self._log("  正在安装 OpenClaw...")
        ret = run_cmd("npm install -g openclaw", callback=self._log)
        if ret != 0:
            raise Exception(
                "OpenClaw 安装失败（npm 返回码 %d）。\n\n"
                "可能原因与解决办法：\n"
                "  1. 网络不稳定 → 点击「重试」再试一次\n"
                "  2. 被安全软件拦截 → 在安全软件中允许本程序后重试\n"
                "  3. npm 源异常 → 上方日志中有 npm 的具体报错信息\n\n"
                "如多次重试仍失败，请截图日志联系技术支持。" % ret)
        # 写入用户 PATH 环境变量（持久生效），否则重启后找不到 openclaw 命令
        npm_dir = os.path.join(self.install_dir, "npm")
        os.environ["PATH"] = npm_dir + os.pathsep + os.environ.get("PATH", "")
        if add_to_user_path(npm_dir):
            self._log(f"  ✅ 已写入环境变量 PATH: {npm_dir}")
            self._log("     （新开的终端窗口即可直接使用 openclaw 命令）")
        else:
            self._log("  ⚠️ 环境变量写入失败，请手动将以下目录加入系统 PATH：")
            self._log(f"     {npm_dir}")
        self._log("  ✅ OpenClaw 安装成功")

    def _step_verify(self):
        self._log("\n  验证安装...")
        vt, vs = get_node_version()
        self._log(f"  {'✅' if vt else '⚠️'} Node.js: v{vs}" if vt else "  ⚠️ Node.js 未检测到")
        nv = get_npm_version()
        self._log(f"  {'✅' if nv else '⚠️'} npm: v{nv}" if nv else "  ⚠️ npm 未检测到")
        ov = get_openclaw_version()
        self._log(f"  {'✅' if ov else '⚠️'} OpenClaw: {ov}" if ov else "  ⚠️ OpenClaw 未检测到")

    # ============================================================
    # 配置（5 步全自动）
    # ============================================================
    def _apply_config(self):
        if not self.selected_provider or not self.selected_provider[0]:
            self._log("\n⏭ 跳过 AI 配置（稍后运行 openclaw configure）")
            self._update_complete_info("未配置", "未配置")
            return
        key = self.api_key.get().strip()
        pid = self.selected_provider[0]
        if not key and self.selected_provider[5]:
            self._log("\n⚠️ 未填入 API Key（稍后运行 openclaw configure）")
            self._update_complete_info(pid, "未配置")
            return

        self._log(f"\n📌 Step 1/5: 配置 AI 模型 ({pid})...")
        cmd = self._build_onboard_cmd(pid, key)
        self._log(f"  {cmd[:80]}...")
        ret = run_cmd(cmd, callback=self._log)
        if ret == 0:
            self._log("  ✅ AI 模型配置完成")
        else:
            self._log(f"  ❌ AI 模型配置失败（返回码: {ret}）")
            self._log("     请检查 API Key 是否正确，或稍后运行: openclaw configure")
        results = [("配置 AI 模型", ret)]

        self._log("\n📌 Step 2/5: 安装 Gateway 守护进程...")
        ret = run_cmd("openclaw gateway install", callback=self._log)
        self._log("  ✅ 守护进程已安装" if ret == 0 else f"  ⚠️ 失败（返回码: {ret}），稍后可手动运行")
        results.append(("安装守护进程", ret))

        self._log("\n📌 Step 3/5: 启动 Gateway...")
        ret = run_cmd("openclaw gateway start", callback=self._log)
        self._log("  ✅ Gateway 已启动" if ret == 0 else f"  ⚠️ 失败（返回码: {ret}）")
        results.append(("启动 Gateway", ret))

        self._log("\n📌 Step 4/5: 健康检查...")
        import time; time.sleep(3)
        ret = run_cmd("openclaw gateway status", callback=self._log)
        self._log("  ✅ Gateway 运行正常！" if ret == 0 else "  ⚠️ 状态异常，可稍后手动检查")
        results.append(("健康检查", ret))

        self._log("\n📌 Step 5/5: 安装推荐 Skills...")
        ret = run_cmd("openclaw skills install --all", callback=self._log)
        self._log("  ✅ Skills 安装完成" if ret == 0 else "  ⚠️ 可稍后运行: openclaw skills install --all")
        results.append(("安装 Skills", ret))

        failed = [name for name, r in results if r != 0]
        if failed:
            self._log(f"\n⚠️ 以下步骤未成功: {'、'.join(failed)}")
            self._log("   可在命令行手动运行对应 openclaw 命令修复")
            self._update_complete_info(pid, "部分步骤未成功（详见日志）")
        else:
            self._update_complete_info(pid, "已配置")

    def _build_onboard_cmd(self, pid, key):
        base = 'openclaw onboard --non-interactive --accept-risk --mode local'
        for p in PROVIDERS:
            if p[0] == pid:
                auth_choice, key_param = p[3], p[4]
                if auth_choice and key_param:
                    return f'{base} --auth-choice {auth_choice} {key_param} "{key}" --gateway-bind loopback --install-daemon --daemon-runtime node'
                break
        return f'{base} --auth-choice {pid} --gateway-bind loopback --install-daemon --daemon-runtime node'

    def _update_complete_info(self, provider, key):
        _, node_ver = get_node_version()
        info = f"📦 Node.js: v{node_ver if node_ver else '未检测到'}\n"
        ov = get_openclaw_version()
        if ov:
            info += f"🦞 OpenClaw: {ov}\n"
        info += f"📁 程序位置: {self.install_dir}\n"
        info += f"📁 数据位置: {Path.home() / '.openclaw'}\n"
        info += f"🤖 AI 模型: {provider}\n"
        info += f"🔑 API Key: {key}"
        self.complete_info.config(text=info)

    def _start_openclaw(self):
        """启动 OpenClaw 控制面板"""
        try:
            subprocess.Popen("start openclaw dashboard", shell=True)
        except Exception:
            pass


# ============================================================
# 入口
# ============================================================
if __name__ == "__main__":
    _ensure_admin()  # 启动即提权（双击 exe → UAC → 点「是」→ 全程管理员）
    app = OpenClawInstaller()
    app.mainloop()
