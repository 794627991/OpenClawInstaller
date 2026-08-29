# -*- coding: utf-8 -*-
"""演练模式全流程走查：update() 泵事件驱动，异常可捕获"""
import os
os.environ["OPENCLAW_DRY_RUN"] = "1"
import sys, time
import importlib.util

spec = importlib.util.spec_from_file_location("installer",
    r"D:\AI_PROJECT\龙虾一键安装\src\installer.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

# 打桩：模拟已提权，弹窗默认「是/取消」
m._is_admin = lambda: True
m._ensure_admin = lambda: None
m.messagebox.askyesno = lambda *a, **k: True
m.messagebox.askretrycancel = lambda *a, **k: False
for name in ("showinfo", "showerror", "showwarning"):
    setattr(m.messagebox, name, lambda *a, **k: None)

app = m.OpenClawInstaller()
REPORT = []
ok = []
failed = None
phase = 0

def pump(sec=0.05):
    deadline = time.time() + sec
    while time.time() < deadline:
        app.update()
        time.sleep(0.01)

def step_one():
    """执行一个阶段的推进，返回 True 表示阶段完成"""
    global phase
    if phase == 0:
        app.next_step(); phase = 1
    elif phase == 1:
        if not app.prereq_done:
            return False
        status = {k: v.cget("text") for k, v in app.prereq_labels.items()}
        REPORT.append("检测结果: " + repr(status))
        if not (app.prereq_ok["node"] and app.prereq_ok["npm"] and app.prereq_ok["openclaw"]):
            return "FAIL: 本机已装却检测失败 %s" % app.prereq_ok
        ok.append("环境检测全绿")
        app.next_step(); phase = 2
    elif phase == 2:
        app.next_step(); phase = 3
    elif phase == 3:
        if app.is_installing:
            return False
        text = app.log_text.get("1.0", "end")
        if "安装完成" not in text and "成功" not in text:
            return "FAIL: 安装流程未走完 -> " + text[:300]
        ok.append("安装流程（跳过已装 + 演练模式）")
        app.next_step(); phase = 4
    elif phase == 4:
        app._on_provider_selected(m.PROVIDERS[1])
        app.api_key.set("sk-test-dry-run-key-12345")
        app.next_step(); phase = 5
    elif phase == 5:
        with open(r"C:\Users\79462\.claude\jobs\317ddaa1\tmp\tick.log", "a", encoding="utf-8") as f:
            f.write("[p5] enter\n")
        info = app.complete_info.cget("text")
        with open(r"C:\Users\79462\.claude\jobs\317ddaa1\tmp\tick.log", "a", encoding="utf-8") as f:
            f.write("[p5] got info len=%d\n" % len(info))
        REPORT.append("完成页: " + info.replace("\n", " | "))
        if "已配置" not in info:
            return "FAIL: 完成页应显示已配置 -> " + info
        ok.append("配置 5 步（演练模式）+ 完成页")
        return "DONE"
    return True

# mainloop 事件驱动（子线程 after 需要 mainloop）
import threading

def mainloop_driver():
    global failed
    deadline = time.time() + 90
    while time.time() < deadline:
        try:
            r = step_one()
        except Exception as e:
            failed = "phase %d 异常: %r" % (phase, e)
            app.quit()
            return
        if isinstance(r, str):
            if r == "DONE":
                app.quit()
                return
            failed = r
            app.quit()
            return
        time.sleep(0.1)
    failed = "整体超时"
    app.quit()

threading.Thread(target=mainloop_driver, daemon=True).start()
app.mainloop()

report_path = r"C:\Users\79462\.claude\jobs\317ddaa1\tmp\report.txt"
with open(report_path, "w", encoding="utf-8") as f:
    f.write("\n".join(REPORT) + "\n")
    if failed:
        f.write("\n===== FAILED =====\n" + failed + "\n")
    else:
        f.write("\n===== PASSED =====\n")
        for line in ok:
            f.write("  - " + line + "\n")
try:
    app.destroy()
except Exception:
    pass
sys.exit(1 if failed else 0)
