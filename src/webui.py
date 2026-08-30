#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🦞 OpenClaw 一键安装器 — Web UI 版（pywebview 前端套壳）
复用 installer.py 的全部业务逻辑，GUI 换成 HTML/CSS/JS
"""
import os
import sys
import json
import queue
import time
import urllib.request
import shutil
import threading
import subprocess
import webbrowser
from pathlib import Path

import installer as core

# webview 在模块级导入：Api 需要运行时创建窗口（内置 Control UI）
import webview

# ============================================================
# 运行日志：存到 claw 数据目录（~/.openclaw/workbench.log），滚动保留
# ============================================================
def _log_path():
    return os.path.expanduser("~/.openclaw/workbench.log")

_WRB_LOCK = threading.Lock()   # 日志写入/轮转互斥（多线程并发写安全）

def wrb_log(msg):
    """写运行日志（文件 + 控制台），文件超 1MB 轮转。
    加锁防轮转竞态；自动创建 ~/.openclaw（全新机目录不存在）"""
    try:
        import time as _t
        with _WRB_LOCK:
            p = _log_path()
            try:
                os.makedirs(os.path.dirname(p), exist_ok=True)
            except Exception:
                pass
            try:
                if os.path.exists(p) and os.path.getsize(p) > 1024 * 1024:
                    old = p + ".1"
                    if os.path.exists(old):
                        os.remove(old)
                    os.replace(p, old)
            except Exception:
                pass
            with open(p, "a", encoding="utf-8") as f:
                f.write("%s %s\n" % (_t.strftime("%Y-%m-%d %H:%M:%S"), msg))
    except Exception:
        pass
    try:
        print("[wrb]", msg, file=sys.stderr, flush=True)
    except Exception:
        pass

# ============================================================
# 前端 <-> 后端桥接
# ============================================================
class Api:
    # 注意：属性一律以下划线开头！pywebview 会用 dir() 遍历 js_api 对象
    # 生成 JS 函数表，公开属性（如 window/outbox）会被递归展开 —
    # window.native 是 WinForms .NET 控件树，展开一次耗时数十秒甚至无限递归，
    # 直接卡死 pywebviewready 事件导致前端 api 永远为空。
    def __init__(self):
        self._window = None
        self._panel_win = None         # 仪表盘面板窗口（运行时创建，复用）
        self._panel_max = False        # 面板是否最大化
        self._panel_accent = "#f38ba8" # 面板标题栏主色（前端主题传入）
        self._tray = None              # 系统托盘状态
        self._tray_icon = None         # pystray Icon 对象（必须持引用防 GC，否则托盘消失）
        self._port_cli = None          # CLI 端口查询结果缓存（避免每次启动 node）
        self._auto_starting = False    # 网关自动恢复中（防轮询重复触发）
        self._auto_last_try = 0.0      # 上次自动尝试时间（失败冷却用）
        self._auto_tries = 0           # 自动尝试次数（达到上限停止）
        self._auto_hint_shown = False  # 服务脚本缺失提示只弹一次
        self._gw_lock = threading.Lock()  # 网关命令全局互斥（launch/fix/auto 串行化）
        self._gui_actions = queue.Queue()  # 主窗口 UI 动作队列（pump 线程执行 evaluate_js——防自锁）
        self._home_url = ""            # 主窗口 http 地址（预留）
        self._outbox = queue.Queue()   # 主线程 -> JS 的事件
        self._dlgbox = queue.Queue()   # JS -> 主线程 的对话框请求

    # ---------- 事件推送（主线程 pump 消费） ----------
    def emit(self, msg):
        self._outbox.put(msg)

    def push_log(self, line):
        self.emit({"type": "log", "line": line})

    def push_progress(self, value, label):
        self.emit({"type": "progress", "value": value, "label": label})

    def push_env(self, results):
        self.emit({"type": "env", "results": results})

    def push_done(self, kind, ok, info=None, token=""):
        self.emit({"type": "done", "kind": kind, "ok": ok, "info": info, "token": token})

    def push_status(self, status):
        self.emit({"type": "status", "status": status})

    def _gui_exec(self, fn):
        """主窗口 UI 动作入队——由 pump 线程消费执行（evaluate_js 从 pump 线程调用安全；
        绝不在主窗口消息泵/WndProc 内同步 evaluate_js，否则自锁「未响应」）"""
        self._gui_actions.put(fn)

    def push_toast(self, text, ok=None):
        """轻提示：前端顶部浮动显示"""
        self.emit({"type": "toast", "text": text, "ok": ok})

    # ---------- JS 直接调用的 API ----------
    def get_logs(self):
        """获取调试日志内容（滚动保留最近 400 行）"""
        try:
            p = _log_path()
            if not os.path.exists(p):
                return "[日志] 暂无日志：%s" % p
            lines = open(p, encoding="utf-8", errors="replace").read().splitlines()
            return "\n".join(lines[-400:])
        except Exception as e:
            return "[日志] 读取失败: %s" % e

    def get_meta(self):
        """首页元数据：版本、默认目录、磁盘空间、安装状态、托盘位置"""
        spaces = {}
        for drive in ("C:", "D:"):
            try:
                spaces[drive] = round(shutil.disk_usage(drive + "\\").free / (1024**3), 1)
            except Exception:
                spaces[drive] = None
        # 版本只查一次（缓存命中时 CLI 兜底会拖慢；避免调用两次）
        claw_ver = core.get_openclaw_version()
        return {
            "version": core.APP_VERSION,
            "install_dir": core.default_install_dir(),
            "spaces": spaces,
            "data_dir": str(Path.home() / ".openclaw"),
            "dry_run": core.DRY_RUN,
            "installed": claw_ver is not None,
            "openclaw_version": claw_ver,
            "tray_path": self._find_tray(),
        }

    def _find_tray(self):
        """查找 OpenClaw 托盘程序（WinUI 独立 exe）"""
        candidates = [
            r"D:\AI\OpenClawTray\OpenClaw.Tray.WinUI.exe",
            r"C:\AI\OpenClawTray\OpenClaw.Tray.WinUI.exe",
        ]
        for c in candidates:
            if os.path.exists(c):
                return c
        return ""

    def get_models(self):
        """已配置模型列表 + 当前激活模型（只读 openclaw.json）"""
        try:
            cfg = json.load(open(os.path.expanduser("~/.openclaw/openclaw.json"),
                                 encoding="utf-8"))
            agents = cfg.get("agents") or {}
            defaults = agents.get("defaults") or {}
            model_cfg = defaults.get("model") or {}
            current = model_cfg.get("primary") or ""
            configured = defaults.get("models") or {}
            provs = (cfg.get("models") or {}).get("providers") or {}
            out = []
            for full_id in configured:
                pid, _, mid = full_id.partition("/")
                name = ""
                try:
                    for m in (provs.get(pid) or {}).get("models") or []:
                        if m.get("id") == mid:
                            name = m.get("name") or mid
                            break
                except Exception:
                    name = mid
                out.append({"id": full_id, "name": name or mid})
            return {"current": current, "models": out}
        except Exception as e:
            return {"current": "", "models": [], "error": str(e)}

    def switch_model(self, full_id):
        """切换激活模型（官方 models set，正式执行）"""
        def run():
            self.push_log("  正在切换模型: %s" % full_id)
            ret = core.run_cmd(claw_cmd() + ' models set "%s"' % full_id, callback=self.push_log)
            if ret == 0:
                self.push_toast("✅ 已切换到 %s" % full_id, True)
            else:
                self.push_toast("⚠️ 切换失败（返回码 %s）" % ret, False)
            self.push_done("launch", ret == 0, None)
        threading.Thread(target=run, daemon=True).start()

    def list_provider_models(self, provider_id):
        """列出某 provider 的全部可用模型（只读 models list）"""
        out = {"provider": provider_id, "models": [], "error": ""}
        cmd = claw_cmd() + " --no-color models list --provider %s" % provider_id
        r = core._run_quiet(cmd, timeout=30)   # 首跑扫描可能较慢，放宽到 30s
        if not r or r.returncode != 0:
            r = core._run_quiet(cmd, timeout=60)  # 仍失败重试一次（更长超时）
        if not r or r.returncode != 0:
            out["error"] = "无法获取模型列表（服务商可能不支持扫描）"
            return out
        for line in (r.stdout or "").splitlines():
            line = line.strip()
            if not line or "Model" in line and "Input" in line:
                continue  # 表头
            fields = line.split()
            if not fields:
                continue
            mid = fields[0]
            if "/" not in mid:
                continue  # 非 <provider>/<model> 格式跳过多余行
            tags = ""
            if "default" in line:
                tags = "default"
            if "configured" in line:
                tags = (tags + "," if tags else "") + "configured"
            out["models"].append({
                "id": mid,
                "input": fields[1] if len(fields) > 1 else "",
                "ctx": fields[2] if len(fields) > 2 else "",
                "tags": tags,
                "configured": "configured" in tags,
                "default": "default" in tags,
            })
        return out

    def _patch_models(self, patch_obj, action, full_id):
        """向 agents.defaults.models 打 config patch（merge；null=删除，正式执行）"""
        patch_str = json.dumps({"agents": {"defaults": {"models": patch_obj}}})
        # 通过 stdin 传 JSON5 patch（服务繁忙时可能超时：90s + 重试一次）
        for attempt in (1, 2):
            try:
                p = subprocess.run(claw_cmd() + " config patch --stdin", shell=True,
                                   input=patch_str, text=True,
                                   capture_output=True, timeout=90,
                                   env=os.environ,
                                   creationflags=subprocess.CREATE_NO_WINDOW
                                   if sys.platform == "win32" else 0)
                ret = p.returncode
            except Exception as e:
                ret = -1
                self.push_log("  执行失败: %s" % e)
            if ret == 0:
                break
            self.push_log("  尝试 %d/2 未成功（返回码 %s）..." % (attempt, ret))
        if ret == 0:
            self.push_toast("✅ 模型已%s" % ("添加" if action == "添加" else "移除"), True)
        else:
            self.push_toast("⚠️ 模型%s失败（返回码 %s），请重试" % (action, ret), False)
        self.push_done("launch", ret == 0, None)

    def add_model(self, full_id):
        """添加模型到可用列表"""
        self.push_log("  添加模型: %s" % full_id)
        self._patch_models({full_id: {}}, "添加", full_id)

    def remove_model(self, full_id):
        """从可用列表移除模型"""
        self.push_log("  移除模型: %s" % full_id)
        self._patch_models({full_id: None}, "移除", full_id)

    def get_status(self):
        """异步诊断：Gateway 运行状态 + 模型配置（只读，不修改任何东西）"""
        def run():
            status = {
                "gateway": {"running": False, "text": "未知"},
                "service": {"registered": False, "text": "未知"},
                "model": {"title": "未配置", "provider": "", "model": "", "has": False},
                "tray": self._find_tray() != "",
            }
            # 1) Gateway 状态分级（全部秒级判定，不跑 CLI）：
            #    HTTP 200=就绪"运行中"；TCP 活但 HTTP 未通="启动中…"；都不通="未运行"
            if self._health_ok():
                status["gateway"] = {"running": True, "text": "运行中"}
            elif self._ping_http():
                status["gateway"] = {"running": True, "text": "启动中…"}
            else:
                status["gateway"] = {"running": False, "text": "未运行"}
                # 自动恢复：服务已注册但没起来 → 后台自动 start（用户无需点修复）
                self._auto_start_gateway()
            status["service"] = {"registered": True, "text": ""}
            # 2) 模型配置（读配置文件，只读）：以激活模型 primary 为准
            try:
                cfg = json.load(open(os.path.expanduser("~/.openclaw/openclaw.json"),
                                     encoding="utf-8"))
                agents = cfg.get("agents") or {}
                defaults = agents.get("defaults") or {}
                primary = (defaults.get("model") or {}).get("primary") or ""
                configured_keys = list((defaults.get("models") or {}).keys())
                pid, _, mid = primary.partition("/")
                label = mid or pid or primary
                if primary:
                    # 从 providers 元数据里找友好名
                    try:
                        provs = (cfg.get("models") or {}).get("providers") or {}
                        for m in (provs.get(pid) or {}).get("models") or []:
                            if m.get("id") == mid:
                                label = m.get("name") or label
                                break
                    except Exception:
                        pass
                status["model"] = {"title": label, "provider": pid,
                                   "model": mid, "has": bool(primary),
                                   "count": len(configured_keys)}
            except Exception:
                pass
            self.push_status(status)
        threading.Thread(target=run, daemon=True).start()

    def _dashboard_url(self):
        """控制面板 URL：真实端口 + 上次对话会话 + 网关令牌（token 仅内存，不进入日志）。
        /chat?session=agent:main:main = main agent 主会话——打开即恢复上次对话（已验证）"""
        base = "http://127.0.0.1:%s/chat?session=agent%%3Amain%%3Amain" % self._gateway_port()
        try:
            cfg = json.load(open(os.path.expanduser("~/.openclaw/openclaw.json"),
                                 encoding="utf-8"))
            token = (cfg.get("gateway") or {}).get("auth", {}).get("token", "")
            if token:
                import urllib.parse
                base += "#token=" + urllib.parse.quote(token)
        except Exception:
            pass
        return base

    def _gateway_port(self):
        """网关真实端口，三重来源：CLI 查询 → 配置文件 → 环境变量 → 默认 18789
        （VM 上配置文件可能无 port 键，CLI 最准）"""
        # 1) 配置文件（秒回，纯文件 — 不跑 CLI，VM 冷启动 node 会拖 10s+）
        try:
            cfg = json.load(open(os.path.expanduser("~/.openclaw/openclaw.json"),
                                 encoding="utf-8"))
            port = (cfg.get("gateway") or {}).get("port")
            if port:
                return int(port)
        except Exception:
            pass
        # 2) 环境变量（schtasks 服务定义）
        envp = os.environ.get("OPENCLAW_GATEWAY_PORT")
        if envp and envp.isdigit():
            return int(envp)
        # 3) CLI 兜底（结果缓存——只查一次）
        if self._port_cli is None:
            try:
                import re as _re
                r = core._run_quiet(claw_cmd() + " config get gateway.port",
                                    timeout=15)
                if r and r.returncode == 0:
                    m = _re.search(r"(\d{4,5})", r.stdout or "")
                    self._port_cli = int(m.group(1)) if m else -1
                else:
                    self._port_cli = -1
            except Exception:
                self._port_cli = -1
        return self._port_cli if self._port_cli and self._port_cli > 0 else 18789

    def _health_ok(self):
        """健康检查：HTTP GET / 返回 200 = 就绪（秒级、不依赖 CLI/WS）。
        VM 上 CLI health 每次冷启动 node >10s，超时即误判；HTTP 层 2s 内出结果"""
        try:
            port = self._gateway_port()
            q = urllib.request.urlopen("http://127.0.0.1:%s/" % port, timeout=3)
            return q.status == 200
        except Exception:
            return False

    def _model_display(self):
        """当前激活模型（primary）友好名；未配置返回 '未配置'（只读配置，绝不修改）"""
        try:
            cfg = json.load(open(os.path.expanduser("~/.openclaw/openclaw.json"),
                                 encoding="utf-8"))
            agents = cfg.get("agents") or {}
            defaults = agents.get("defaults") or {}
            primary = (defaults.get("model") or {}).get("primary") or ""
            if not primary:
                return "未配置"
            pid, _, mid = primary.partition("/")
            label = mid or pid or primary
            try:
                provs = (cfg.get("models") or {}).get("providers") or {}
                for m in (provs.get(pid) or {}).get("models") or []:
                    if m.get("id") == mid:
                        label = m.get("name") or label
                        break
            except Exception:
                pass
            return label or pid or primary
        except Exception:
            return "未知"

    def _gw_http_ok(self):
        return self._health_ok()

    _AUTO_RETRY_SLEEP = 300      # 失败后冷却 5 分钟（代替无限每 45s 重试）
    _AUTO_MAX_TRIES = 2          # 最多自动尝试 2 次，之后仅提示（不轰炸）

    def _auto_start_gateway(self):
        """检测到网关未运行且服务已注册 → 后台自动 start。
        限流：失败冷却 5 分钟、最多 2 次；服务脚本缺失只提示一次（杜绝 80070002 弹窗/刷屏）"""
        now = time.time()
        if self._auto_starting:
            return
        if now - self._auto_last_try < self._AUTO_RETRY_SLEEP:
            return
        if self._auto_tries >= self._AUTO_MAX_TRIES:
            if not self._auto_hint_shown:
                self._auto_hint_shown = True
                self.push_log("  ℹ️ 网关未运行且自动启动未成功，可点「修复网关」手动处理")
                self.push_toast("⚠️ 网关未运行，请点「修复网关」", False)
            return
        self._auto_starting = True
        self._auto_last_try = now
        self._auto_tries += 1
        def run():
            try:
                cmd_path = os.path.expanduser("~/.openclaw/gateway.cmd")
                vbs_path = os.path.expanduser("~/.openclaw/gateway.vbs")
                if not os.path.exists(cmd_path) or not os.path.exists(vbs_path):
                    # 只提示一次（避免每 15s 轮询刷屏）
                    if not self._auto_hint_shown:
                        self._auto_hint_shown = True
                        self.push_log("  ⚠️ 网关服务脚本不完整（缺 gateway.cmd/vbs），"
                                      "跳过自动启动，建议使用「修复网关」重装服务")
                        self.push_toast("⚠️ 网关服务脚本缺失，请点「修复网关」", False)
                    return
                try:
                    vbs_txt = open(vbs_path, encoding="utf-8", errors="ignore").read()
                    if "gateway.cmd" not in vbs_txt:
                        if not self._auto_hint_shown:
                            self._auto_hint_shown = True
                            self.push_log("  ⚠️ gateway.vbs 未引用 gateway.cmd，跳过自动启动")
                        return
                except Exception:
                    pass
                self.push_log("  服务脚本完整，正在自动启动网关（第 %d 次尝试）..." % self._auto_tries)
                with self._gw_lock:   # 与 launch/fix 互斥（防 stop 杀 start 自相残杀）
                    core.run_cmd(claw_cmd() + " gateway start",
                                 callback=self.push_log, timeout=40)
                time.sleep(3)
            finally:
                self._auto_starting = False
        threading.Thread(target=run, daemon=True).start()

    def _ping_http(self):
        """网关探测：TCP 端口可达即"在运行"（秒回）。
        日志已证 pid 4220 在跑但 WS 1006/HTTP HEAD 可能挂——TCP connect 最可靠：
        端口活着 = 进程在跑，无论 WS 是否健康。"""
        try:
            import socket as _so
            port = self._gateway_port()
            with _so.create_connection(("127.0.0.1", port), timeout=2):
                return True
        except Exception:
            # TCP 不通 → 再试 HTTP（兼容只走 HTTP 的部署）
            try:
                port = self._gateway_port()
                q = urllib.request.urlopen(urllib.request.Request(
                    "http://127.0.0.1:%s/" % port, method="HEAD"), timeout=2)
                return q.status == 200
            except Exception:
                return False

    def _open_dashboard_window(self, url):
        """运行时创建窗口打开控制面板：系统原生标题栏（最大化/最小化/关闭齐全、风格天然统一），
        面板页面零注入——无遮挡、无底部截断、无风格冲突"""
        if self._panel_win is not None:
            # 已打开：直接复用
            self.push_toast("✅ 控制面板已打开", True)
            return True
        try:
            win2 = webview.create_window("OpenClaw 仪表盘", url,
                                         width=1100, height=780, min_size=(860, 620))
            self._panel_win = win2
            # 用户点系统 ✕ 关闭时窗口销毁 → 引用置空，下次可重新创建；主窗口恢复
            def _on_closed():
                self._panel_win = None
                try:
                    self._window.restore()
                    self._window.show()
                except Exception:
                    pass
            win2.events.closed += _on_closed
            self.push_toast("✅ 控制面板已打开", True)
            return True
        except Exception as e:
            self.push_log("  打开失败: %s" % e)
            self.push_toast("⚠️ 控制面板打开失败: %s" % e, False)
            return False

    def open_session(self, key):
        """打开指定会话的官方控制页 /chat?session=<key>#token=（后台线程，evaluate_js 不落 WndProc）"""
        def run():
            try:
                url = "http://127.0.0.1:%s/chat?session=%s" % (
                    self._gateway_port(),
                    urllib.request.quote(key, safe="") if hasattr(urllib.request, "quote")
                    else key.replace(":", "%3A").replace("@", "%40"))
                try:
                    cfg = json.load(open(os.path.expanduser("~/.openclaw/openclaw.json"),
                                         encoding="utf-8"))
                    tok = (cfg.get("gateway") or {}).get("auth", {}).get("token", "")
                    if tok:
                        import urllib.parse as _up
                        url += "#token=" + _up.quote(tok)
                except Exception:
                    pass
                self.push_log("  打开会话: %s" % url.split("#")[0].rsplit("session=", 1)[-1][:40])
                self._open_dashboard_window(url)
                self.push_done("launch", True, None)
            except Exception as e:
                self.push_log("  打开会话失败: %s" % e)
        threading.Thread(target=run, daemon=True).start()

    def close_panel(self):
        """关闭仪表盘面板窗口"""
        if self._panel_win is not None:
            try:
                self._panel_win.destroy()
            except Exception:
                pass
            self._panel_win = None
        try:
            self._window.restore()
            self._window.show()
        except Exception:
            pass

    def minimize_panel(self):
        """最小化仪表盘面板"""
        try:
            self._panel_win.minimize()
        except Exception:
            pass

    def maximize_panel(self):
        """最大化 / 还原仪表盘面板"""
        try:
            if self._panel_max:
                self._panel_win.restore()
            else:
                self._panel_win.maximize()
            self._panel_max = not self._panel_max
        except Exception:
            pass

    def launch_usage(self, accent=""):
        """开始使用：网关正常则秒开面板窗口（无边框自绘标题栏）；异常才启动服务
        accent：当前配色主色（面板标题栏/关闭按钮跟随主题）"""
        # 面板标题栏颜色：按前端传入的当前主题色（默认粉色兜底）
        self._panel_accent = accent or self._panel_accent
        def run():
            if not self._ping_http():
                self.push_log("  ⚠️ 网关未就绪（端口 %s），正在启动服务..." % self._gateway_port())
                # 网关命令全局互斥：防止与自动恢复/修复流程并发（stop 杀 start 等自相残杀）
                with self._gw_lock:
                    core.run_cmd(claw_cmd() + " gateway install --force", callback=self.push_log)
                    ret = core.run_cmd(claw_cmd() + " gateway start", callback=self.push_log)
                if ret != 0:
                    self.push_toast("⚠️ Gateway 启动失败（返回码 %s），可点「修复 Gateway」" % ret, False)
                    self.push_done("launch", False, str(ret))
                    return
                for _ in range(15):
                    if self._ping_http():
                        break
                    time.sleep(2)
            url = self._dashboard_url()
            self.push_log("  打开控制面板: %s" % url.split("#")[0])
            # 主窗口直接隐藏（退回托盘），面板接管；面板关闭后主窗口恢复
            try:
                self._window.hide()
            except Exception:
                pass
            self._open_dashboard_window(url)
            self.push_done("launch", True, None)
        threading.Thread(target=run, daemon=True).start()

    def fix_gateway(self):
        """修复 Gateway：探测 → install --force → start → 验证。
        验证优先 openclaw health（自带正确端口），失败写桌面报告"""
        _logbuf = []
        def _log(msg):
            self.push_log(msg)
            _logbuf.append(msg)

        def _gw_alive():
            """网关存活：health 命令优先（短超时）→ HTTP ping 兜底"""
            try:
                r = core._run_quiet(claw_cmd() + " --no-color gateway health", timeout=12)
                if r and r.returncode == 0 and "OK" in (r.stdout or ""):
                    return True
            except Exception:
                pass
            return self._ping_http()

        def run():
            # 分级：TCP 活+health OK=真运行；TCP 活+health 暂不 OK=慢启动（VM 常见，几分钟）
            try:
                if self._ping_http():
                    if self._health_ok():
                        _log("  ✅ 网关运行正常（端口 %s）" % self._gateway_port())
                        self.push_toast("✅ 网关运行中", True)
                        self.push_done("launch", True, None)
                        return
                    _log("  ℹ️ 网关进程已启动（端口 %s 可达），健康检查暂未就绪——"
                         "VM 上网关需 1-3 分钟预热（插件加载），正在等待..." % self._gateway_port())
                    self.push_toast("⏳ 网关启动中，正在等待就绪（约 1-3 分钟）…", False)
                    for i in range(20):
                        if self._health_ok():
                            _log("  ✅ 网关已就绪！")
                            self.push_toast("✅ Gateway 运行中", True)
                            self.push_done("launch", True, None)
                            return
                        time.sleep(10)
                    self._restart_gateway_flow(_log)
                    return   # done 推送由 _restart_gateway_flow 负责（避免重复/矛盾 done）
            except Exception as e:
                _log("  ❌ 慢启动路径异常: %r" % e)
                self.push_done("launch", False, str(e))
                return
            _log("  ⚠️ 网关端口无响应，开始修复...")
            self._restart_gateway_flow(_log)
        threading.Thread(target=run, daemon=True).start()

    def _gw_alive(self):
        """网关存活判定：HTTP 200（完全就绪）或 TCP 端口活（进程在）"""
        return self._health_ok() or self._ping_http()

    def _restart_gateway_flow(self, _log):
        """修复主流程：stop → install --force → start → 长轮询。
        每步实时 toast 反馈（不消失），结束自动写桌面报告（无论成败）"""
        self.push_toast("⏳ [0/4] 停止残留网关实例…", None)
        # 网关命令全局互斥（0-2 步 stop/install/start 串行化）
        with self._gw_lock:
            _log("  [0/4] 停止残留实例（gateway stop）...")
            ret = core.run_cmd(claw_cmd() + " gateway stop",
                               callback=lambda l: _log("      " + l), timeout=30)
            _log("      返回码: %s" % ret)
            time.sleep(2)
            self.push_toast("⏳ [1/4] 重新注册网关服务…", None)
            _log("  [1/4] 重新注册服务（install --force）...")
            ret = core.run_cmd(claw_cmd() + " gateway install --force",
                               callback=lambda l: _log("      " + l), timeout=60)
            _log("      返回码: %s" % ret)
            self.push_toast("⏳ [2/4] 启动网关（约 30 秒）…", None)
            _log("  [2/4] 启动网关（start）——该命令可能等待健康检查 30s 返回，属正常...")
            ret = core.run_cmd(claw_cmd() + " gateway start",
                               callback=lambda l: _log("      " + l), timeout=40)
            _log("      返回码: %s（-2=命令等待超时，网关可能仍在启动）" % ret)
        # 3) 耐心轮询：TCP 活=进程起（VM 慢启动，最多 5 分钟）
        _log("  [3/4] 等待网关进程起来（最多 5 分钟）...")
        for i in range(30):
            if self._ping_http():
                _log("  ✅ 网关进程已启动（端口 %s 可达）！" % self._gateway_port())
                self.push_toast("✅ 网关进程已启动，等待健康就绪…", True)
                break
            _log("      第 %d 次：端口未监听" % (i + 1))
            self.push_toast("⏳ 等待网关启动…（第 %d/30 次）" % (i + 1), None)
            time.sleep(10)
        else:
            _log("  ❌ 5 分钟内端口未监听，修复失败。")
            self._write_fix_report(_log, notify=True)
            self.push_toast("❌ 网关未能启动，报告已存桌面", False)
            self.push_done("launch", False, None)
            return
        # 4) 等健康就绪（预热阶段）
        _log("  [4/4] 等待健康检查就绪（插件预热，VM 约 1-3 分钟）...")
        for i in range(18):
            if self._health_ok():
                _log("  ✅ 网关已恢复健康！")
                self.push_toast("✅ Gateway 已恢复正常", True)
                self.push_done("launch", True, None)
                return
            _log("      健康检查暂未就绪（第 %d 次）..." % (i + 1))
            self.push_toast("⏳ 等待网关就绪…（第 %d/18 次）" % (i + 1), None)
            time.sleep(10)
        _log("  ⚠️ 端口已监听但健康检查未就绪——网关进程在预热，建议稍后查看，不视为失败")
        self.push_toast("✅ 网关进程已启动（健康预热中，稍后自动就绪）", True)
        self._write_fix_report(_log)
        self.push_done("launch", True, None)

    def _write_fix_report(self, _log, notify=False):
        """修复结束写报告到日志目录（不落桌面）；成功不写，仅失败留档"""
        try:
            report = os.path.expanduser("~/.openclaw/openclaw-fix-report.txt")
            if notify:
                # 后台线程不能直接弹 tkinter（非线程安全）——用系统默认程序打开报告
                try:
                    os.startfile(report)
                except Exception:
                    pass
        except Exception as e:
            _log("  报告写入失败: %s" % e)

    def launch_tray(self):
        """启动 OpenClaw 托盘程序（已安装时）"""
        tray = self._find_tray()
        if not tray:
            self.push_log("  ⚠️ 未检测到托盘程序，将改用控制面板")
            self.launch_usage()
            return
        if core.DRY_RUN:
            self.push_log("[演练模式] 跳过执行: 启动托盘: %s" % tray)
            self.push_done("launch", True, None)
            return
        try:
            subprocess.Popen([tray])
            self.push_log("  ✅ 托盘程序已启动")
            self.push_done("launch", True, None)
        except Exception as e:
            self.push_log("  ⚠️ 托盘启动失败: %s" % e)
            self.push_done("launch", False, str(e))

    def get_providers(self):
        """服务商列表（JS 做搜索分组渲染）；跳过项不提供——API Key 必须立刻配置"""
        out = []
        for p in core.PROVIDERS:
            if not p[0]:   # 过滤「⏭ 跳过，稍后配置」
                continue
            out.append({
                "id": p[0], "name": p[1], "group": p[2],
                "auth_choice": p[3], "key_param": p[4], "needs_key": p[5],
                "url": p[6], "steps": p[7], "key_format": p[8], "key_example": p[9],
            })
        return out

    def open_url(self, url):
        if url:
            webbrowser.open(url)

    def browse_dir(self):
        """请求主线程弹目录选择框（WinForms 对话框须在主线程）"""
        result = queue.Queue()
        self._dlgbox.put(result)
        try:
            return result.get(timeout=120)
        except Exception:
            return None

    # ---------- 异步流程 ----------
    def check_env(self):
        """环境检测（线程内执行，完成后推送）"""
        def run():
            net_ok = core.check_network()
            node_ver = core.get_node_version()
            npm_ver = core.get_npm_version()
            claw_ver = core.get_openclaw_version()
            self.push_env({
                "network": {"ok": net_ok,
                            "text": "✅ 可用" if net_ok else "❌ 无法连接"},
                "node": {"ok": node_ver[0] is not None,
                         "text": ("✅ v%s" % node_ver[1]) if node_ver[0]
                                 else "❌ 未安装（将自动安装）"},
                "npm": {"ok": npm_ver is not None,
                        "text": ("✅ v%s" % npm_ver) if npm_ver else "❌ 未安装（随 Node.js）"},
                "openclaw": {"ok": claw_ver is not None,
                             "text": ("✅ %s" % claw_ver) if claw_ver
                                     else "❌ 未安装（将自动安装）"},
            })
        threading.Thread(target=run, daemon=True).start()

    def start_install(self, install_dir):
        """安装流程（5 步，线程内执行）"""
        install_dir = (install_dir or core.default_install_dir()).strip()
        def run():
            self._install_thread(install_dir)
        threading.Thread(target=run, daemon=True).start()

    def _install_thread(self, install_dir):
        steps = [
            ("检查环境...", lambda: self._step_check_env()),
            ("配置 npm 镜像与目录...", lambda: self._step_config_npm(install_dir)),
            ("安装 Node.js...", lambda: self._step_install_node()),
            ("安装 OpenClaw...", lambda: self._step_install_openclaw(install_dir)),
            ("验证安装...", lambda: self._step_verify()),
        ]
        total = len(steps)
        try:
            for i, (desc, func) in enumerate(steps):
                self.push_progress(i / total * 100, desc)
                self.push_log("\n==========\n📌 %s\n==========" % desc)
                func()
                self.push_progress((i + 1) / total * 100, desc)
            self.push_log("\n🎉 所有组件安装成功！")
            self.push_done("install", True)
        except Exception as e:
            self.push_log("❌ 步骤失败: %s" % e)
            self.push_done("install", False, str(e))

    def _step_check_env(self):
        vt, vs = core.get_node_version()
        if vt and vt >= core.NODE_MIN_VERSION:
            self.push_log("  ✅ Node.js v%s 已就绪" % vs)
        else:
            self.push_log("  ⚠️ Node.js 需要安装")

    def _step_config_npm(self, install_dir):
        if core.DRY_RUN:
            # 演练模式：npm 全局配置属安装动作，仅记录
            self.push_log("  [演练模式] 跳过执行: 配置 npm 镜像与全局目录（%s\\npm）" % install_dir)
            return
        # 镜像
        r = core._run_quiet("npm config get registry")
        current = r.stdout.strip() if r and r.returncode == 0 else ""
        if current == core.MIRRORS["npm_registry"]:
            self.push_log("  ✅ npm 镜像已配置: %s" % current)
        else:
            self.push_log("  设置 npm 镜像: %s" % core.MIRRORS["npm_registry"])
            core.run_cmd('npm config set registry %s' % core.MIRRORS["npm_registry"], callback=self.push_log)
            core.run_cmd('npm config set disturl https://npmmirror.com/mirrors/node', callback=self.push_log)
            self.push_log("  ✅ npm 镜像配置完成")
        # prefix 重定向（程序装到用户选择目录）
        npm_dir = os.path.join(install_dir, "npm")
        try:
            os.makedirs(npm_dir, exist_ok=True)
        except Exception as e:
            self.push_log("  ⚠️ 无法创建目录 %s: %s" % (npm_dir, e))
        self.push_log("  设置 npm 全局目录: %s" % npm_dir)
        if core.run_cmd('npm config set prefix "%s"' % npm_dir, callback=self.push_log) == 0:
            os.environ["PATH"] = npm_dir + os.pathsep + os.environ.get("PATH", "")
            # npm 缓存也挪走，减少 C 盘占用
            cache_dir = os.path.join(install_dir, "npm-cache")
            try:
                os.makedirs(cache_dir, exist_ok=True)
            except Exception:
                pass
            if core.run_cmd('npm config set cache "%s"' % cache_dir, callback=self.push_log) == 0:
                self.push_log("  ✅ npm 下载缓存已移至安装目录")
        else:
            self.push_log("  ⚠️ npm 全局目录设置失败，将使用默认位置")

    def _step_install_node(self):
        if core.DRY_RUN:
            self.push_log("  [演练模式] 跳过执行: 下载安装 Node.js")
            return
        vt, vs = core.get_node_version()
        if vt and vt >= core.NODE_MIN_VERSION:
            self.push_log("  跳过 - Node.js v%s 已安装" % vs)
            return
        self.push_log("  正在下载 Node.js...")
        node_ver = core.NODE_RECOMMENDED
        node_url = "%s/v%s/node-v%s-x64.msi" % (core.MIRRORS["node_dist"], node_ver, node_ver)
        msi_path = os.path.join(core.tempfile.gettempdir(), "node-v%s-x64.msi" % node_ver)
        self.push_log("  下载: %s" % node_url)
        try:
            # 分块下载带超时（urlretrieve 无超时会永久挂起）
            core.download_file(node_url, msi_path)
        except Exception as e:
            raise Exception("Node.js 下载失败: %s\n请检查网络后重试" % e)
        self.push_log("  正在安装 Node.js（可能需要管理员权限）...")
        log_path = os.path.join(core.tempfile.gettempdir(), "openclaw-node-install.log")
        ret = core.run_cmd('msiexec /i "%s" /quiet /norestart /l*v "%s"' % (msi_path, log_path),
                           callback=self.push_log)
        if ret not in (0, 3010):
            self.push_log("  ⚠️ 静默安装失败（错误码 %s），改用带进度界面重试..." % ret)
            ret = core.run_cmd('msiexec /i "%s" /passive /norestart' % msi_path, callback=self.push_log)
        if ret not in (0, 3010):
            raise Exception(
                "Node.js 安装失败（错误码 %d）。\n\n"
                "请手动安装：\n"
                "  1. 用浏览器打开 %s\n"
                "  2. 下载 node-v%s-x64.msi 并双击安装\n"
                "  3. 安装完成后重新运行本安装器" % (ret, core.MIRRORS["node_dist"], node_ver))
        os.environ["PATH"] = r"C:\Program Files\nodejs" + os.pathsep + os.environ.get("PATH", "")
        try:
            os.remove(msi_path)
        except Exception:
            pass
        vt, vs = core.get_node_version()
        self.push_log("  ✅ Node.js v%s 安装成功" % vs if vt else "  ⚠️ 安装完成，可能需要重启电脑后生效")

    def _step_install_openclaw(self, install_dir):
        if core.DRY_RUN:
            self.push_log("  [演练模式] 跳过执行: npm install -g openclaw")
            return
        ov = core.get_openclaw_version()
        if ov:
            self.push_log("  跳过 - OpenClaw %s 已安装" % ov)
            return
        self.push_log("  正在安装 OpenClaw...")
        ret = core.run_cmd("npm install -g openclaw", callback=self.push_log)
        if ret != 0:
            raise Exception(
                "OpenClaw 安装失败（npm 返回码 %d）。\n\n"
                "可能原因与解决办法：\n"
                "  1. 网络不稳定 → 点击「重试」再试一次\n"
                "  2. 被安全软件拦截 → 在安全软件中允许本程序后重试\n"
                "  3. npm 源异常 → 上方日志中有 npm 的具体报错信息" % ret)
        npm_dir = os.path.join(install_dir, "npm")
        os.environ["PATH"] = npm_dir + os.pathsep + os.environ.get("PATH", "")
        if core.add_to_user_path(npm_dir):
            self.push_log("  ✅ 已写入环境变量 PATH: %s" % npm_dir)
            self.push_log("     （新开的终端窗口即可直接使用 openclaw 命令）")
        else:
            self.push_log("  ⚠️ 环境变量写入失败，请手动将以下目录加入系统 PATH：")
            self.push_log("     %s" % npm_dir)
        self.push_log("  ✅ OpenClaw 安装成功")

    def _step_verify(self):
        self.push_log("\n  验证安装...")
        vt, vs = core.get_node_version()
        self.push_log("  ✅ Node.js: v%s" % vs if vt else "  ⚠️ Node.js 未检测到")
        nv = core.get_npm_version()
        self.push_log("  ✅ npm: v%s" % nv if nv else "  ⚠️ npm 未检测到")
        ov = core.get_openclaw_version()
        self.push_log("  ✅ OpenClaw: %s" % ov if ov else "  ⚠️ OpenClaw 未检测到")

    # ---------- 配置 ----------
    # ---------- API Key 真实 HTTP 验证（只读、不写配置；覆盖服务商表全部 key 型 provider） ----------
    _VERIFY_ENDPOINTS = {
        # 国产
        "deepseek":  ("https://api.deepseek.com/models", "bearer", "GET"),
        "zai":       ("https://open.bigmodel.cn/api/paas/v4/models", "bearer", "GET"),
        "moonshot":  ("https://api.moonshot.cn/v1/models", "bearer", "GET"),
        "minimax":   ("https://api.minimaxi.com/v1/models", "bearer", "GET"),
        "qwen-oauth":("https://dashscope.aliyuncs.com/compatible-mode/v1/models", "bearer", "GET"),
        "volcengine-plan": ("https://ark.cn-beijing.volces.com/api/v3/models", "bearer", "GET"),
        "qianfan":   ("https://qianfan.baidubce.com/v2/models", "bearer", "GET"),
        "tencent-tokenhub": ("https://api.tencent.com/v1/models", "bearer", "GET"),
        "xiaomi":    ("https://api.xiaomi.com/v1/models", "bearer", "GET"),
        "stepfun":   ("https://api.stepfun.com/v1/models", "bearer", "GET"),
        # 聚合
        "opencode-go":   ("https://api.opencode.ai/v1/models", "bearer", "GET"),
        "opencode-zen":  ("https://api.opencode.ai/v1/models", "bearer", "GET"),
        "openrouter":("https://openrouter.ai/api/v1/models", "bearer", "GET"),
        "clawrouter":("https://api.clawrouter.ai/v1/models", "bearer", "GET"),
        "vercel-ai-gateway": ("https://ai-gateway.vercel.sh/v1/models", "bearer", "GET"),
        # 美国
        "openai":    ("https://api.openai.com/v1/models", "bearer", "GET"),
        "anthropic": ("https://api.anthropic.com/v1/messages", "anthropic", "POST"),
        "google":    ("https://generativelanguage.googleapis.com/v1beta/models", "google", "GET"),
        "xai":       ("https://api.x.ai/v1/models", "bearer", "GET"),
        "cohere":    ("https://api.cohere.com/v1/models", "bearer", "GET"),
        "groq":      ("https://api.groq.com/openai/v1/models", "bearer", "GET"),
        "mistral":   ("https://api.mistral.ai/v1/models", "bearer", "GET"),
        "nvidia":    ("https://integrate.api.nvidia.com/v1/models", "bearer", "GET"),
        # 其他
        "deepinfra": ("https://api.deepinfra.com/v1/openai/models", "bearer", "GET"),
        "together":  ("https://api.together.xyz/v1/models", "bearer", "GET"),
        "cerebras":  ("https://api.cerebras.ai/v1/models", "bearer", "GET"),
        "huggingface":("https://huggingface.co/api/models?limit=1", "bearer", "GET"),
        # 本地（无需 key）
        "ollama":    ("__local__", "", ""),
        "lmstudio":  ("__local__", "", ""),
    }

    def _verify_key_http(self, pid, key, token=""):
        """真实 HTTP 探测 API Key：请求成功=有效。只读、不写任何配置。
        token 透传回 push_done，前端据此丢弃过期结果"""
        def _done(ok, info):
            self.push_done("verify", ok, info, token)

        combo = self._VERIFY_ENDPOINTS.get(pid)
        if not combo:
            _done(False, "该服务商暂不支持自动验证，请自行确认后继续")
            return
        url, mode, method = combo
        if url == "__local__":
            _done(True, "本地运行模型，无需 API Key")
            return
        try:
            headers = {}
            if mode == "bearer":
                headers["Authorization"] = "Bearer %s" % key
            elif mode == "anthropic":
                headers["x-api-key"] = key
                headers["anthropic-version"] = "2023-06-01"
                headers["Content-Type"] = "application/json"
            elif mode == "google":
                # Gemini: key 走 query 参数
                url = url + "?key=" + urllib.parse.quote(key)
            def _req():
                q = urllib.request.Request(url, method=method, headers=headers)
                if method == "POST":
                    import json as _j
                    body = _j.dumps({"model": "gpt-4o-mini",
                                     "messages": [{"role": "user",
                                                   "content": "hi"}]}).encode()
                    q.data = body
                return urllib.request.urlopen(q, timeout=15)
            try:
                r = _req()
                # 成功：2xx = key 有效（models 列表/推理请求均此判断）
                _done(True, "Key 有效！可以继续安装")
                return
            except urllib.error.HTTPError as e:
                if e.code in (401, 403, 404):
                    _done(False, "Key 无效或已过期，请检查后重试")
                elif e.code == 429:
                    _done(False, "请求被限流，请稍后再试")
                else:
                    _done(False, "验证失败（HTTP %s），服务商可能需要额外配置" % e.code)
            except Exception as e:
                _done(False, "网络异常，无法验证：%s" % e)
        except Exception as e:
            _done(False, "无法验证，请确认 Key 是否正确")

    def verify_key(self, pid, key, token=""):
        """验证 Key（真实 HTTP 探测，只读）。
        token=前端请求指纹——结果带回 token，前端据此丢弃过期的验证结果（防竞态回填）"""
        threading.Thread(target=self._verify_key_http, args=(pid, key, token),
                         daemon=True).start()

    def apply_config(self, provider_id, key, mode="install"):
        """配置模型。mode=install: 全 5 步（新装）；mode=reconfig: 仅 onboard（更换模型，快）"""
        def run():
            if mode == "reconfig":
                self._reconfig(provider_id, key.strip() if key else "")
            else:
                self._apply_config(provider_id, key.strip() if key else "")
        threading.Thread(target=run, daemon=True).start()

    def _reconfig(self, pid, key):
        """更换/重配模型：只跑 onboard 一步，完成后回首页"""
        if not pid:
            self.push_log("\n⚠️ 未选择服务商，取消重新配置")
            self.push_done("config", False, None)
            return
        self.push_log("\n📌 正在重新配置 AI 模型 (%s)..." % pid)
        # 本地模型（Ollama/LM Studio）无需 API Key（与 _apply_config 的 needs_key 逻辑一致）
        needs_key = True
        for p in core.PROVIDERS:
            if p[0] == pid:
                needs_key = bool(p[5])
                break
        if not key and needs_key:
            self.push_log("\n⚠️ 未填入 API Key（配置未执行）")
            self.push_done("config", False, None)
            return
        cmd = self._build_onboard_cmd(pid, key)
        self.push_log("  %s..." % cmd[:80])
        ret = core.run_cmd(cmd, callback=self.push_log)
        if ret == 0:
            self.push_log("  ✅ AI 模型配置完成")
            self.push_toast("✅ AI 模型已更新为 %s" % pid, True)
        else:
            self.push_log("  ❌ 配置失败（返回码: %s），请检查 API Key" % ret)
            self.push_toast("⚠️ 配置失败，请检查 API Key", False)
        self.push_done("config", ret == 0, {"provider": pid, "key": "已配置" if ret == 0 else "配置失败"})

    def _build_onboard_cmd(self, pid, key):
        base = claw_cmd() + " onboard --non-interactive --accept-risk --mode local"
        for p in core.PROVIDERS:
            if p[0] == pid:
                auth_choice, key_param = p[3], p[4]
                # 普通 provider：auth-choice + key 参数（key 可空——本地模型）
                if auth_choice and key_param:
                    # shell 转义：双引号/反引号/美元符（防命令破坏/注入）
                    esc_key = key.replace('"', '\\"').replace('`', '\\`').replace('$', '\\$')
                    return '%s --auth-choice %s %s "%s" --gateway-bind loopback --install-daemon --daemon-runtime node' % (
                        base, auth_choice, key_param, esc_key)
                # 本地 provider（ollama/lmstudio）：仅 auth-choice（onboard 官方支持该值），无 key_param
                if auth_choice:
                    return '%s --auth-choice %s --gateway-bind loopback --install-daemon --daemon-runtime node' % (
                        base, auth_choice)
                break
        return "%s --auth-choice %s --gateway-bind loopback --install-daemon --daemon-runtime node" % (base, pid)

    def _apply_config(self, pid, key):
        if not pid:
            self.push_log("\n⏭ 跳过 AI 配置（稍后运行 openclaw configure）")
            self.push_done("config", True, {"provider": "未配置", "key": "未配置"})
            return
        # 本地模型（Ollama/LM Studio）无需 API Key——空 Key 也走 onboard（不报假成功）
        needs_key = True
        for p in core.PROVIDERS:
            if p[0] == pid:
                needs_key = bool(p[5])
                break
        if not key and needs_key:
            self.push_log("\n⚠️ 未填入 API Key（稍后运行 openclaw configure）")
            self.push_done("config", True, {"provider": pid, "key": "未配置"})
            return
        self.push_log("\n📌 Step 1/5: 配置 AI 模型 (%s)..." % pid)
        cmd = self._build_onboard_cmd(pid, key)
        self.push_log("  %s..." % cmd[:80])
        ret = core.run_cmd(cmd, callback=self.push_log)
        if ret == 0:
            self.push_log("  ✅ AI 模型配置完成")
        else:
            self.push_log("  ❌ AI 模型配置失败（返回码: %s）" % ret)
            self.push_log("     请检查 API Key 是否正确，或稍后运行: openclaw configure")
        results = [("配置 AI 模型", ret)]

        self.push_log("\n📌 Step 2/5: 安装 Gateway 守护进程...")
        if core.DRY_RUN:
            self.push_log("  [演练模式] 跳过执行: openclaw gateway install")
            ret = 0
        else:
            with self._gw_lock:   # 与 launch/fix/auto 互斥（审计：原绕过锁——网关命令自相残杀）
                ret = core.run_cmd(claw_cmd() + " gateway install", callback=self.push_log)
        self.push_log("  ✅ 守护进程已安装" if ret == 0 else "  ⚠️ 失败（返回码: %s），稍后可手动运行" % ret)
        results.append(("安装守护进程", ret))

        self.push_log("\n📌 Step 3/5: 启动 Gateway...")
        with self._gw_lock:
            ret = core.run_cmd(claw_cmd() + " gateway start", callback=self.push_log)
        self.push_log("  ✅ Gateway 已启动" if ret == 0 else "  ⚠️ 失败（返回码: %s）" % ret)
        results.append(("启动 Gateway", ret))

        self.push_log("\n📌 Step 4/5: 健康检查...")
        time.sleep(3)
        # 用 HTTP 探测（status 命令在部分环境会挂起）
        ok = False
        for _ in range(5):
            if self._ping_http():
                ok = True
                break
            time.sleep(2)
        ret = 0 if ok else 1
        self.push_log("  ✅ Gateway 运行正常！" if ok else "  ⚠️ 状态异常，可稍后手动检查")
        results.append(("健康检查", ret))

        self.push_log("\n📌 Step 5/5: 安装推荐 Skills...")
        if core.DRY_RUN:
            self.push_log("  [演练模式] 跳过执行: openclaw skills install --all")
            ret = 0
        else:
            ret = core.run_cmd(claw_cmd() + " skills install --all", callback=self.push_log)
        self.push_log("  ✅ Skills 安装完成" if ret == 0 else "  ⚠️ 可稍后运行: openclaw skills install --all")
        results.append(("安装 Skills", ret))

        failed = [n for n, r in results if r != 0]
        if failed:
            self.push_log("\n⚠️ 以下步骤未成功: %s" % "、".join(failed))
            self.push_done("config", True, {"provider": pid, "key": "部分步骤未成功（详见日志）"})
        else:
            self.push_done("config", True, {"provider": pid, "key": "已配置"})

    def start_openclaw(self):
        """启动控制面板"""
        try:
            os.system("start openclaw dashboard")
        except Exception:
            pass


# ============================================================
# 主线程事件泵：队列消息 -> JS
# ============================================================
def pump(api, win, stop_event):
    while not stop_event.is_set():
        # 后端 -> JS 事件
        try:
            msg = api._outbox.get(timeout=0.1)
            try:
                win.evaluate_js("window.__pyEvent(%s)" % json.dumps(msg, ensure_ascii=False))
            except Exception as e:
                # 静默吞掉会掩盖问题，写日志便于排查
                try:
                    os.write(2, ("[pump] evaluate_js 失败: %r\n" % e).encode("utf-8", "replace"))
                except Exception:
                    pass
        except queue.Empty:
            pass
        # 主窗口 UI 动作（托盘菜单等）——pump 线程执行（evaluate_js 安全）
        try:
            while True:
                _fn = api._gui_actions.get_nowait()
                try:
                    _fn()
                except Exception as e:
                    try:
                        os.write(2, ("[pump] gui_action 失败: %r\n" % e).encode("utf-8", "replace"))
                    except Exception:
                        pass
        except queue.Empty:
            pass
        # JS -> 主线程 对话框请求
        try:
            req = api._dlgbox.get_nowait()
            try:
                import webview
                result = win.create_file_dialog(webview.FOLDER_DIALOG)
                req.put(result[0] if result else None)
            except Exception as e:
                req.put(None)
        except queue.Empty:
            pass
        time.sleep(0.02)


def _web_dir():
    """前端资源目录：源码运行用 src/web，PyInstaller 打包后用 _MEIPASS/web"""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, "web")

_CLAW_CMD = None
def claw_cmd():
    """openclaw 命令：优先 PATH（_fix_path 已注入 npm prefix），找不到则探测绝对路径"""
    global _CLAW_CMD
    if _CLAW_CMD is None:
        # 探测常见安装位置的 openclaw.cmd（覆盖 prefix 重定向场景）
        cands = [
            os.path.expanduser("~/AppData/Roaming/npm/openclaw.cmd"),
            # 无 D 盘回退目录（default_install_dir 的 C 盘回退）
            os.path.expanduser("~/AppData/Local/OpenClaw/npm/openclaw.cmd"),
            r"D:\openclaw\npm\openclaw.cmd",
            r"C:\openclaw\npm\openclaw.cmd",
        ]
        found = ""
        for c in cands:
            if os.path.exists(c):
                found = c
                break
        if not found:
            # 终极兜底：npm config get prefix 拿真实全局目录（npm 必在 nodejs 目录）
            try:
                r = subprocess.run("npm config get prefix", shell=True,
                                   capture_output=True, text=True, timeout=10,
                                   encoding=core._console_encoding(), errors="replace",
                                   creationflags=subprocess.CREATE_NO_WINDOW
                                   if sys.platform == "win32" else 0)
                prefix = (r.stdout or "").strip().splitlines()
                prefix = prefix[-1].strip() if prefix else ""
                if prefix:
                    c = os.path.join(prefix, "openclaw.cmd")
                    if os.path.exists(c):
                        found = c
            except Exception:
                pass
        _CLAW_CMD = '"%s"' % found if found else "openclaw"
    return _CLAW_CMD

def _webview2_available():
    """检测 WebView2 Runtime 是否已安装（pywebview 用它在 Win 渲染 Chromium 页面）"""
    try:
        import winreg
        guids = [
            '{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}',  # Runtime
            '{2CD8A007-E189-409D-A2C8-9AF4EF3C72AA}',  # Beta
            '{0D50BFEC-CD6A-4F9A-964C-C7416E3ACB10}',  # Dev
            '{65C35B14-6C1D-4122-AC46-7148CC9D6497}',  # Canary
        ]
        for guid in guids:
            for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
                try:
                    with winreg.OpenKey(root, r'SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\%s' % guid) as k:
                        winreg.QueryValueEx(k, 'pv')
                        return True
                except FileNotFoundError:
                    continue
                except OSError:
                    continue
        return False
    except Exception:
        # 无法检测则乐观假设可用（多数现代系统已装）
        return True

def _ensure_webview2():
    """WebView2 缺失：精致进度窗 + 真实进度（下载字节级/安装阶段级）安装，装完直接进主体
    返回 True=可继续启动；False=安装失败/取消，应退出"""
    if sys.platform != "win32" or _webview2_available():
        return True
    try:
        import tkinter as _tk
        import tkinter.messagebox as _mb
        from tkinter import ttk as _ttk
        boot = os.path.join(core.tempfile.gettempdir(), "MicrosoftEdgeWebview2Setup.exe")

        ok = _mb.askyesno("需要 WebView2 Runtime",
            "本工具需要微软 WebView2 Runtime 才能显示界面。\n"
            "当前系统尚未安装，需要先安装它。\n\n"
            "说明：\n"
            "  · 将先下载微软官方安装器（约 2 MB）\n"
            "  · 安装器会在线获取并安装运行组件（安装后约占用数百 MB）\n"
            "  · 全程自动，安装完成后直接进入主界面\n\n"
            "现在开始吗？")
        if not ok:
            return False

        # ---------- 精致进度窗口（主题一致 + 龙虾图标 + 渐变进度条） ----------
        win = _tk.Tk()
        win.title("正在准备 WebView2 Runtime")
        win.geometry("440x220")
        win.resizable(False, False)
        win.configure(bg="#13131f")
        try:
            win.iconbitmap(_icon_path())
        except Exception:
            pass
        # 顶部图标：用 PIL 加载品牌龙虾图标（appicon.ico）→ PhotoImage 显示。
        # 注意：tkinter 渲染彩色 emoji 是黑白的，SVG 字符串会当文本显示——都不能用。
        _logo_photo = None
        try:
            from PIL import Image as _PImage, ImageTk as _PImageTk
            _logo = _PImage.open(_icon_path()).resize((52, 52), _PImage.LANCZOS)
            _logo_photo = _PImageTk.PhotoImage(_logo)
            _tk.Label(win, image=_logo_photo, bg="#13131f").pack(pady=(14, 0))
        except Exception:
            # PIL 不可用时纯文字标题兜底
            _tk.Label(win, text="OpenClaw 工作台", bg="#13131f", fg="#f38ba8",
                      font=("Microsoft YaHei UI", 13, "bold")).pack(pady=(16, 0))
        _tk.Label(win, text="正在准备 WebView2 Runtime", bg="#13131f", fg="#dfe3f5",
                  font=("Microsoft YaHei UI", 13, "bold")).pack(pady=(4, 2))
        _lbl = _tk.Label(win, text="准备中…", bg="#13131f", fg="#cdd6f4",
                         font=("Microsoft YaHei UI", 10), justify="left", anchor="w")
        _lbl.pack(fill="x", padx=36, pady=(4, 0))
        # 渐变进度条：标准 ttk.Progressbar（样式化主题色，平滑确定模式）
        _frame = _tk.Frame(win, bg="#13131f")
        _frame.pack(fill="x", padx=36, pady=(8, 0))
        _style = _ttk.Style(win)
        _style.theme_use("clam")
        _style.configure("WebV2.Horizontal.TProgressbar",
                         troughcolor="#313244", background="#f38ba8",
                         bordercolor="#313244", lightcolor="#f38ba8",
                         darkcolor="#d96a8a", thickness=14)
        _track = _ttk.Progressbar(_frame, style="WebV2.Horizontal.TProgressbar",
                                  length=360, mode="determinate", maximum=100)
        _track.pack(fill="x")
        _st = _tk.Label(win, text="", bg="#13131f", fg="#6c7086",
                        font=("Microsoft YaHei UI", 9), anchor="w")
        _st.pack(fill="x", padx=36, pady=(6, 0))
        _prog = {"v": 0}
        def _paint(pct):
            _track.config(value=pct)
        def _set(label, pct=None, sub=""):
            # 主线程内直接改（所有 _set 调用都在 UI 线程的 after 里）
            _lbl.config(text=label)
            if pct is not None:
                _prog["v"] = pct
                _paint(pct)
            _st.config(text=sub)

        # 后台线程：下载 + 安装（不阻塞 UI，避免 update() 高频重绘 CPU 100%）
        import threading as _th
        import queue as _q
        _qmsg = _q.Queue()
        _dlog = open(os.path.join(core.tempfile.gettempdir(), "openclaw-wv2.log"),
                     "a", encoding="utf-8")
        def _dbg(s):
            try:
                _dlog.write(time.strftime("%H:%M:%S") + " " + s + "\n")
                _dlog.flush()
            except Exception:
                pass
        _dbg("== ensure_webview2 start, avail=%s" % _webview2_available())
        def _worker():
            try:
                # 1) 下载官方引导器
                _qmsg.put(("set", "① 下载微软官方安装器…", 2, "下载地址：go.microsoft.com/fwlink/…"))
                if not os.path.exists(boot):
                    def _hook(b, bs, total):
                        if total > 0:
                            pct = 2 + b * bs * 80 // total
                            _qmsg.put(("set", "① 正在下载安装器…", pct,
                                       "已下载 %d / %d KB" % (b * bs // 1024, total // 1024)))
                        else:
                            _qmsg.put(("set", "① 正在下载安装器…", 2,
                                       "已下载 %d KB" % (b * bs // 1024)))
                    _dbg("downloading bootstrapper")
                    def _dl_progress(n, bs, total):
                        _hook(n, bs, total)
                    core.download_file(
                        "https://go.microsoft.com/fwlink/p/?LinkId=2124703",
                        boot, progress=_dl_progress, timeout=180)
                    _dbg("downloaded size=%d" % os.path.getsize(boot))
                _qmsg.put(("set", "① 下载完成 ✓", 85,
                           "安装器：%s" % os.path.basename(boot)))
                # 2) 安装（轮询注册表）
                _qmsg.put(("set", "② 正在安装 WebView2 Runtime…", 88,
                           "安装器在线获取并安装运行组件，需几分钟…"))
                _dbg("launching bootstrapper /silent")
                p = subprocess.Popen([boot, "/silent", "/install"],
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                deadline = time.time() + 300
                last = 88
                _dbg("polling max 300s")
                while time.time() < deadline and p.poll() is None:
                    time.sleep(1.5)
                    if _webview2_available():
                        _dbg("webview2 available!")
                        _qmsg.put(("set", "② 安装完成 ✓", 100, "WebView2 Runtime 已就绪"))
                        break
                    last = min(99, last + 0.5)
                    _qmsg.put(("set", "② 正在安装…（已用时 %d 秒）"
                               % int(time.time() - (deadline - 300)),
                               last, "完成后自动进入主界面"))
                if p.poll() is None:
                    p.terminate()
                time.sleep(0.5)
                _dbg("worker done, rc=%s avail=%s" % (p.poll(), _webview2_available()))
                _dlog.close()
                _qmsg.put(("done", _webview2_available()))
            except Exception as e:
                _dbg("worker error: %r" % e)
                _dlog.close()
                _qmsg.put(("done", False, str(e)))

        _th.Thread(target=_worker, daemon=True).start()
        # UI 线程 mainloop（轮询队列更新界面）
        _result = {}
        def _tick():
            try:
                while True:
                    m = _qmsg.get_nowait()
                    if m[0] == "set":
                        _set(m[1], m[2], m[3])
                    elif m[0] == "done":
                        _result["ok"] = m[1]
                        if len(m) > 2:
                            _result["err"] = m[2]
                        win.destroy()
                        return
            except _q.Empty:
                pass
            win.after(50, _tick)
        win.after(20, _tick)
        win.mainloop()

        if _result.get("ok"):
            _mb.showinfo("运行组件就绪", "WebView2 Runtime 已安装完成，即将进入主界面。")
            return True
        _mb.showwarning("安装未完成",
            ("WebView2 Runtime 安装未能在预期内完成。\n\n"
             "也可手动安装：https://developer.microsoft.com/microsoft-edge/webview2/")
            + (("\n\n错误：%s" % _result.get("err")) if _result.get("err") else ""))
        return False
    except Exception as e:
        try:
            import tkinter.messagebox as _mb
            _mb.showerror("无法自动安装",
                "未能自动下载/安装 WebView2 Runtime：%s\n\n"
                "请手动访问 https://developer.microsoft.com/microsoft-edge/webview2/ "
                "下载安装后重试。" % e)
        except Exception:
            pass
        return False

def _icon_path():
    """窗口图标路径：源码运行 src/appicon.ico，打包后 _MEIPASS/appicon.ico"""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    ico = os.path.join(base, "appicon.ico")
    return ico if os.path.exists(ico) else None


def diag_mode():
    """命令行诊断模式：在 VM 上直接跑全套诊断写桌面报告（每步带超时不卡死）"""
    report = os.path.expanduser("~/Desktop/openclaw-diag-report.txt")
    def w(s):
        try:
            with open(report, "a", encoding="utf-8") as f:
                f.write(s + "\n")
        except Exception:
            pass
    def timed(cmd, t=30):
        try:
            r = core._run_quiet(cmd, timeout=t)
            return "rc=%s | %s | %s" % (
                r.returncode if r else "?",
                (r.stdout or "").strip()[:600] if r else "无输出",
                (r.stderr or "").strip()[:300] if r else "")
        except Exception as e:
            return "异常: %s" % e
    try:
        open(report, "w", encoding="utf-8").write("OpenClaw 诊断 %s\n" % time.strftime("%Y-%m-%d %H:%M"))
    except Exception:
        pass
    w("== 环境 ==")
    w("node: " + str(timed("node --version", 15)))
    w("npm: " + str(timed("npm --version", 15)))
    w("npm prefix: " + str(timed("npm config get prefix", 15)))
    w("where openclaw: " + str(timed("where openclaw", 15)))
    w("claw_cmd 探测: " + claw_cmd())
    w("版本: " + str(core.get_openclaw_version()))
    w("端口(文件/配置): " + str(Api()._gateway_port()))
    w("HTTP ping: " + str(Api()._ping_http()))
    w("== gateway 系列（各 30s 超时，不会卡） ==")
    w("health: " + timed(claw_cmd() + " --no-color gateway health", 30))
    w("status: " + timed(claw_cmd() + " --no-color gateway status", 30))
    w("install: " + timed(claw_cmd() + " gateway install --force", 30))
    w("start: " + timed(claw_cmd() + " gateway start", 30))
    import time as _t; _t.sleep(8)
    w("health(重启前): " + timed(claw_cmd() + " --no-color gateway health", 30))
    w("HTTP ping(重启后): " + str(Api()._ping_http()))
    w("== 强制清场 + 重启（修复半死实例） ==")
    # 1) 杀残留 node 进程（gateway 半死实例锁端口/锁文件）
    w("taskkill node: " + str(timed("taskkill /F /IM node.exe /T", 20)))
    _t.sleep(3)
    w("netstat 18789: " + str(timed("netstat -ano | findstr 18789", 10)))
    w("gateway stop: " + timed(claw_cmd() + " gateway stop", 30))
    _t.sleep(2)
    # 2) 重新注册 + 启动
    w("install --force: " + timed(claw_cmd() + " gateway install --force", 30))
    w("start: " + timed(claw_cmd() + " gateway start", 30))
    _t.sleep(10)
    w("health(清场后): " + timed(claw_cmd() + " --no-color gateway health", 30))
    w("HTTP ping(清场后): " + str(Api()._ping_http()))
    w("== 完成 ==")
    try:
        os.startfile(report)
    except Exception:
        pass
    return 0


def main():
    wrb_log("========== 应用启动 ==========")
    wrb_log("[app] 版本 %s | frozen=%s | argv=%s" % (core.APP_VERSION, getattr(sys, "frozen", False), sys.argv))
    # 托盘独立测试模式（--traytest）：只建托盘，验证 pystray 在裸环境是否显示
    if len(sys.argv) > 1 and sys.argv[1] == "--traytest":
        wrb_log("[traytest] 开始独立托盘测试")
        try:
            import pystray
            from PIL import Image as _PILImg
            img = _PILImg.open(_icon_path())
            ico = pystray.Icon("ocwtraytest", img, "OpenClaw 托盘测试",
                               pystray.Menu(
                                   pystray.MenuItem("退出测试",
                                                    lambda i, it: (i.stop(),
                                                                   os._exit(0)),
                                                    default=True)))
            ico.visible = True
            ico.run_detached()
            wrb_log("[traytest] run_detached 完成 visible=%s" % ico.visible)
            import time as _t
            for _ in range(30):
                _t.sleep(1)
                wrb_log("[traytest] visible=%s" % ico.visible)
            ico.stop()
        except Exception as e:
            wrb_log("[traytest] 失败: %r" % e)
            import traceback
            wrb_log(traceback.format_exc())
        return
    # 命令行诊断模式（--diag / --diagnose）：VM 排障专用
    if len(sys.argv) > 1 and sys.argv[1] in ("--diag", "--diagnose"):
        diag_mode()
        return
    # 托盘独立探针模式（--trayprobe --hwnd）：验证 ctypes 自研托盘在宿主 hwnd 上能否成功
    if len(sys.argv) > 1 and sys.argv[1] == "--trayprobe":
        wrb_log("[trayprobe] 自研托盘探针启动")
        _tp_icon_path = _icon_path() or os.path.join(os.path.dirname(os.path.abspath(__file__)), "appicon.ico")
        _tp_hwnd = None
        try:
            import ctypes as _c
            user32 = _c.windll.user32
            # 找任意有效宿主窗口 hwnd（桌面窗口兜底）
            _tp_hwnd = user32.FindWindowW("Shell_TrayWnd", None) or user32.GetDesktopWindow()
            wrb_log("[trayprobe] 宿主 hwnd=%s" % _tp_hwnd)
        except Exception as e:
            wrb_log("[trayprobe] 找 hwnd 失败: %r" % e)
        import tray as _tray
        t, ok = _tray.create_tray(_tp_hwnd, _tp_icon_path, "OpenClaw 托盘探针")
        wrb_log("[trayprobe] create_tray ok=%s" % ok)
        import time as _t
        for _ in range(30):
            _t.sleep(1)
        t.destroy()
        wrb_log("[trayprobe] 探针结束")
        return
    # WebView2 缺失引导（Win10 无自带时关键；缺失则白屏）
    if not _ensure_webview2():
        return
    api = Api()
    web_dir = _web_dir()
    win = webview.create_window(
        "OpenClaw 工作台",
        os.path.join(web_dir, "index.html"),
        js_api=api, width=860, height=720, min_size=(700, 600))
    api._window = win
    # 主窗口实际 URL（加载完成后才有 http 地址），仪表盘返回按钮导航回这里
    api._home_url = ""
    _tray_started = {"v": False}
    def _on_home_loaded():
        api._home_url = win.real_url or ""
        try:
            win.evaluate_js("window.__pyEvent(%s)" %
                            json.dumps({"type": "home", "url": api._home_url},
                                       ensure_ascii=False))
        except Exception:
            pass
        # 窗口 native 就绪后才能建托盘（hwnd 有效）；防抖只初始化一次
        if not _tray_started["v"]:
            _tray_started["v"] = True
            time.sleep(1)
            threading.Thread(target=_setup_tray, daemon=True).start()
    win.events.loaded += _on_home_loaded

    # ---- 主窗口关闭 → 托盘（不退出程序，静默无弹窗） ----
    def _on_closing():
        try:
            win.hide()
        except Exception:
            pass
        return False   # 返回 False → 取消关闭，窗口隐藏到托盘
    win.events.closing += _on_closing

    # ---- 系统托盘：动态状态 + 全套快捷操作 + 左键单击弹菜单 ----
        # ---- 系统托盘（自研 ctypes 版：挂到主窗口 HWND，图标必然显示） ----
    def _setup_tray():
        wrb_log("[tray] 开始创建托盘（ctypes 自研, 宿主 hwnd=%s）" % win.native)
        try:
            import ctypes as _c
            # 主窗口 native = WinForms Form，取 Handle（64位）
            try:
                _form = win.native
                _hwnd = _form.Handle.ToInt64()
            except Exception as e:
                wrb_log("[tray] 取 hwnd 失败: %r" % e)
                return
            import tray as _tray
            ico_path = _icon_path()
            def _show_menu():
                """左键托盘 → 主窗口显示。
                restore+show 双保险：Win32 直调 SW_RESTORE/SW_SHOWNORMAL + 强制前台；
                并记录前后状态（wrb_log 留证——用户反馈过"任务栏有预览但不显示"）"""
                def _run():
                    try:
                        before = "?"
                        try:
                            n = win.native
                            before = "V=%s W=%s" % (n.Visible, n.WindowState)
                        except Exception:
                            pass
                        win.restore()
                        win.show()
                        try:
                            import ctypes as _c
                            u = _c.windll.user32
                            u.ShowWindow.restype = _c.c_int
                            h = win.native.Handle.ToInt64()
                            u.ShowWindow(h, 9)          # SW_RESTORE（最小化/隐藏态直还原）
                            u.ShowWindow(h, 1)          # SW_SHOWNORMAL（visible 兜底）
                            u.SetForegroundWindow(h)     # 强置前台（Win11 限制时无害）
                        except Exception:
                            pass
                        wrb_log("[tray] 左键显示主窗 (before=%s) OK" % before)
                    except Exception as e:
                        wrb_log("[tray] 左键显示主窗异常: %r" % e)
                api._gui_exec(_run)
            def _open_dash():
                try:
                    api.launch_usage()
                except Exception:
                    pass
            def _fix_gw():
                try:
                    api.fix_gateway()
                except Exception:
                    pass
            def _reconfig():
                # 关键：evaluate_js 必须在 pump 线程执行（主窗口 WndProc/消息线程内同步调用会自锁）
                api._gui_exec(lambda: (
                    win.restore(), win.show(),
                    win.evaluate_js("goConfig('reconfig')")))
            def _quit():
                try:
                    nonlocal _tray_obj
                    _tray_obj.destroy()
                except Exception:
                    pass
                # os._exit 会被 .NET/WebView2 的 DLL detach 钩子拖 2-3s（实测 2343ms）——
                # TerminateProcess 绕过一切卸载钩子（实测 294ms）——立即退出
                try:
                    import ctypes as _c
                    k = _c.windll.kernel32
                    k.GetCurrentProcess.restype = _c.c_void_p
                    k.TerminateProcess.argtypes = [_c.c_void_p, _c.c_uint]
                    k.TerminateProcess(k.GetCurrentProcess(), 0)
                except Exception:
                    os._exit(0)
            def _refresh():
                gw = api._ping_http()
                ver = core.get_openclaw_version() or "未安装"
                tip = "OpenClaw %s · 网关%s" % (ver, "运行中" if gw else "未运行")
                try:
                    _tray_obj.update_tip(tip)
                except Exception:
                    pass
            _sessions_cache = {"t": 0.0, "data": None, "loading": False}

            def _session_label(key):
                """会话 key → 中文标签（主会话/微信/QQ/定时/仪表盘/截断）"""
                label = key.split(":")
                if len(label) >= 2 and label[-1] == "main" and "main" in label:
                    return "主会话"
                for p in label:
                    if p in ("openclaw-weixin", "weixin", "wechat", "im-bot"):
                        return "微信"
                    if p == "qqbot":
                        return "QQ"
                    if p == "cron":
                        return "定时任务"
                    if p == "dashboard":
                        return "仪表盘"
                tail = key.split("@")[0].replace("direct:", "").replace("default:", "")
                tail = tail.strip(":").split(":")[-1][:14]
                return tail or "会话"

            def _hz(n):
                """token 数人类化：25456 → 25.5K"""
                if n is None:
                    return "?"
                n = float(n)
                if n >= 1e6:
                    return "%.1fM" % (n / 1e6)
                if n >= 1e3:
                    return "%.1fK" % (n / 1e3)
                return str(int(n))

            def _normalize_sessions(raw):
                """CLI sessions --json → 面板行数据（按更新时间倒序）"""
                out = []
                for s in raw:
                    try:
                        total = s.get("totalTokens") or 0
                        ctx = s.get("contextTokens") or 0
                        pct = (total / ctx) if ctx else 0.0
                        age = s.get("ageMs") or 0
                        if age < 3600e3:
                            age_t = "%d分钟前" % max(1, int(age / 60000))
                        elif age < 86400e3:
                            age_t = "%d小时前" % int(age / 3600e3)
                        else:
                            age_t = "%d天前" % int(age / 86400e3)
                        out.append({
                            "label": _session_label(s.get("key") or ""),
                            "age": age_t,
                            "model": s.get("model") or "",
                            "tokens_text": "%s/%s (%d%%)" % (_hz(total), _hz(ctx or 1), round(pct * 100)),
                            "pct": pct,
                            "active": bool((s.get("status") or "").lower() in
                                           ("active", "running", "working")) or False,
                            "key": s.get("key") or "",
                            "total": total, "ctx": ctx,
                        })
                    except Exception:
                        continue
                return out

            def _load_sessions(force=False):
                """CLI 读会话（60s 缓存；后台加载不阻塞）；返回 normalized list 或 None"""
                now = time.time()
                if not force and _sessions_cache["data"] is not None and now - _sessions_cache["t"] < 60:
                    return _sessions_cache["data"]
                if _sessions_cache["loading"]:
                    return _sessions_cache["data"]
                _sessions_cache["loading"] = True
                def run():
                    try:
                        r = core._run_quiet(claw_cmd() + " --no-color sessions --active 1440 --limit 30 --json",
                                            timeout=60)
                        if r and r.returncode == 0 and r.stdout:
                            j = json.loads(r.stdout)
                            _sessions_cache["data"] = _normalize_sessions(j.get("sessions") or [])
                            _sessions_cache["t"] = time.time()
                    except Exception:
                        pass
                    finally:
                        _sessions_cache["loading"] = False
                threading.Thread(target=run, daemon=True).start()
                return _sessions_cache["data"]

            def _sessions_summary():
                """面板 Sessions 行右侧摘要：数量 + 总 token"""
                data = _load_sessions()
                if data:
                    total = sum(int(d.get("total") or 0) for d in data)
                    act = sum(1 for d in data if d.get("active"))
                    return "%d 个 · %s token%s" % (len(data), _hz(total),
                                                   " · 活动" if act else "")
                return "正在加载…"

            def _panel_spec():
                """07 式面板内容：状态三色 + 版本 + 地址/模型 + Gateway 卡（打开时抓快照）"""
                if api._health_ok():
                    st, stt = "green", "网关运行中"
                elif api._ping_http():
                    st, stt = "yellow", "启动中…"
                else:
                    st, stt = "red", "未运行"
                    try:
                        api._auto_start_gateway()   # 与 get_status 同策略：后台自动恢复（限流）
                    except Exception:
                        pass
                return {"title": "OpenClaw 工作台",
                        "version": core.get_openclaw_version() or "未安装",
                        "status": st, "status_text": stt,
                        "addr": "127.0.0.1:%s" % api._gateway_port(),
                        "model": api._model_display(),
                        "sessions_right": _sessions_summary()}

            _tray_obj = None
            def _open_sessions_panel():
                """打开会话列表面板：行=会话（点开对应官方页），头部返回主面板。
                数据未就绪时先显示「正在获取会话…」，异步到达后经 WM_USER+1 通知列表重绘（
                ——修复 Sessions (0)：原来异步加载被当成空数据直接用，永不刷新）"""
                try:
                    data = _sessions_cache.get("data")
                    lst = data if data is not None else []
                    spec = {"title": "Sessions", "list": lst,
                            "loading": data is None,
                            "on_row": _pick_session}
                    _tray.open_session_panel(_hwnd, spec, [("main", "返回工作台", _panel_route)])
                    if data is None:
                        def run():
                            # 审计中-2：loading 守卫使 force 返回 None → 面板永久"正在获取会话…"。
                            # 修复：等已有加载完成（轮询 data），有数据才 post 刷新；失败也解除 loading
                            for _ in range(120):
                                rows = _sessions_cache.get("data")
                                if rows is not None:
                                    spec["list"] = rows
                                    spec["loading"] = False
                                    hm = _tray.menu_find("OcwPanelV2")
                                    if hm:
                                        try:
                                            import ctypes as _ct
                                            _ct.windll.user32.PostMessageW(hm, 0x401, 0, 0)
                                        except Exception:
                                            pass
                                    return
                                if not _sessions_cache.get("loading"):
                                    _load_sessions(force=True)
                                time.sleep(0.5)
                            spec["loading"] = False   # 超时兜底：解除永久加载态
                            hm = _tray.menu_find("OcwPanelV2")
                            if hm:
                                try:
                                    import ctypes as _ct
                                    _ct.windll.user32.PostMessageW(hm, 0x401, 0, 0)
                                except Exception:
                                    pass
                        threading.Thread(target=run, daemon=True).start()
                except Exception as e:
                    wrb_log("[tray] 会话面板异常，回退: %r" % e)
                    _panel_route()

            def _pick_session(i):
                try:
                    rows = _sessions_cache.get("data") or []
                    if 0 <= i < len(rows):
                        api.open_session(rows[i].get("key") or "")
                except Exception:
                    pass

            def _panel_route():
                """右键路由：默认 07 式卡片面板；OCW_PANEL=0 或面板异常 → 系统菜单"""
                if os.environ.get("OCW_PANEL", "1") != "0":
                    try:
                        _tray.open_panel(_hwnd, _panel_spec(), [
                            ("row", "Sessions", _open_sessions_panel),
                            ("main", "打开工作台", _show_menu),
                            ("btn", "控制面板", _open_dash),
                            ("btn", "重新配置", _reconfig),
                            ("btn", "修复网关", _fix_gw),
                            ("quit", "退出", _quit),
                        ])
                        return
                    except Exception as e:
                        wrb_log("[tray] 面板弹窗异常，回退系统菜单: %r" % e)
                # 回退系统菜单（临时解绑 _route 防递归）
                try:
                    _tray_obj._route = None
                    _tray_obj.show_menu()
                finally:
                    _tray_obj._route = _panel_route

            menu = [
                ("打开工作台", _show_menu),
                ("打开控制面板", _open_dash),
                ("更换 AI 模型", _reconfig),
                ("修复网关", _fix_gw),
                ("退出", _quit),
            ]

            _tray_obj, ok = _tray.create_tray(
                _hwnd, ico_path, "OpenClaw 工作台", on_click=_show_menu,
                menu_items=menu)
            if _tray_obj:
                _tray_obj._sep_after = [2, 4]   # 更换模型后 / 修复网关后分隔
                _tray_obj._route = _panel_route
            wrb_log("[tray] create_tray ok=%s (挂宿主窗口+WndProc钩子)" % ok)
            if not ok:
                wrb_log("[tray] 创建失败（Shell_NotifyIconW 返回假）")
            # 状态刷新线程（每 15s update tip）
            def _loop():
                while True:
                    try:
                        time.sleep(15); _refresh()
                    except Exception:
                        time.sleep(15)
            threading.Thread(target=_loop, daemon=True).start()
        except Exception as e:
            wrb_log("[tray] 异常: %r" % e)

    stop_event = threading.Event()
    webview.start(lambda: pump(api, win, stop_event), debug=False,
                  icon=_icon_path())
    stop_event.set()


if __name__ == "__main__":
    main()
