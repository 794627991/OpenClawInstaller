# 🦞 OpenClaw 一键安装器 - 待办事项

## 🔴 明日首要（2026-09-01 用户实测反馈，需修复）

### 问题1：左键点击托盘，主窗口无法显示（✅ 2026-09-01 已修复+防御加固）

- 修复：`_show_menu` 双保险——pywebview restore/show + Win32 直调 SW_RESTORE(9)/SW_SHOWNORMAL(1) + SetForegroundWindow；前后状态写 wrb_log（再失败可拿日志定位）
- diag8 实测：正常/hide/最小化三场景 restore+show 均恢复（模拟环境未复现原 bug，故按防御性修复）

### 问题2：Sessions 面板并排新开（✅ 2026-09-01 已修复）

- 实现：row 点击保留主面板；列表面板锚定主面板左侧 -8px 并排（放不下自动右侧）；两面板均 WS_EX_NOACTIVATE + SW_SHOWNOACTIVATE（无焦点互抢/无 KILLFOCUS 误关）；列表行点击=自关+保留主面板
- **动作按实例分发**：MSG_ACTION 消息 lparam 携带面板 hwnd → EXEC 查 `_MENU_INSTANCES` 实例表（转发时曾丢 lparam 导致动作串台——已修）；0=旧菜单/全局表兼容
- diag9/10 实测：并排双窗口✓ row 点击保留✓ 列表行点击后主面板仍在✓ 实例分发不串✓ 退出自关✓

## 🔴 明日首要：打包验证（沙盒）

- [X] **PyInstaller 打包**（webui.py 版，单 exe）：
  - [X] spec 更新：webui.py 入口 + src/web 静态资源（datas）+ appicon.ico + uac_admin=True
  - [X] pywebview/WebView2 运行时依赖验证（Win10 无 WebView2 时提示/引导安装）
- [X] **沙盒/隔离环境验证**（不动本机）：
  - [X] 方案 A：Hyper-V/VMware 干净 Win11 虚拟机（推荐，最真实）
  - [X] 方案 B：Windows Sandbox（Win11 家庭版含，一键原生沙盒，关闭即销毁）
  - [X] 方案 C：无沙盒时先 PyInstaller 单目录模式 + 本机双环境（--onedir 可测试打包产物，不会污染系统配置——工具本身对系统无安装行为）
  - [X] 沙盒内验证项：exe 启动 ✓ / 检测页全绿 / 演练模式安装链路 / 仪表盘面板（自动认证+关闭） / 模型切换+增删 / 主题 121 组合 / 无崩溃
- [ ] 打包后的 exe 大小、杀软误报检查（常见：PyInstaller 裸包易报毒，考虑 UPX 关闭/版本信息/加壳）

## 🟠 正式安装器（Inno Setup，正规分发形态）

- [ ] Inno Setup 生成官方安装器（`installer/setup.iss` 已有旧版，需按 Web 版重构）：
  - [ ] 打包 PyInstaller 产物 + 图标/版本信息/许可协议页（同意后才装）
  - [ ] 安装目录支持（默认 Program Files 或用户选择）、开始菜单 + 桌面快捷方式
  - [ ] 可选：安装时预检（VC++/WebView2 运行时依赖，缺失提示引导）
  - [ ] 卸载器（Inno 自动生成，含注册表清理：开机自启/PATH 如需留则注释说明）
  - [ ] 集成商业激活：激活入口放安装前/首次启动，未授权提示→预览模式
- [ ] Inno Setup 官网下载：https://jrsoftware.org/isdl.php（`build.bat` 里已有检测 iscc）

## 🟠 商业保护（后续给别人用，收费授权）

- [ ] **授权激活机制**（主方案）：
  - [ ] 首次启动生成机器码（主板 UUID + 硬盘序列指纹，不泄露隐私）
  - [ ] 离线激活码（机器码→签名，RSA/Ed25519 授权文件），未激活仅开放预览/演练，激活后才能执行安装
  - [ ] 激活状态本地加密存储 + 防重放（时间同步容忍）
- [ ] **防复制加固**（尽力而为层）：
  - [ ] PyInstaller `--key` 字节码加密（防小白直接解包改代码）
  - [ ] 关键逻辑（授权校验/激活/密钥）下沉 native（C 扩展或 openssl 签名校验）提高门槛
  - [ ] 完整性校验（hash + 自校验，防改 exe）
- [ ] ⚠️ 技术边界（如实）：本地安装的程序无法做到绝对防破解（有能力的攻击者总能找到绕过），上述措施目标是：
  - [ ] 防止「直接拷贝给他人使用」（激活码机器绑定使然）
  - [ ] 抬高小白/中低水平盗用门槛；配合定期版本更新追缴
- [ ] 商业化配套：使用协议/免责声明页面、激活失败自助指引、服务器端发放工具（预留 API）

## 🟡 其余遗留

- [X] **WebView2 内嵌自动安装（2026-08-28，按你的思路重做）**：检测缺失 → 弹窗确认 → 下载官方 Evergreen Bootstrapper → **`/silent /install` 静默安装**（~2MB 无打扰）→ 装完**直接进主界面**（无需重启/重开）。非管理员走用户级安装同样有效
- [ ] webui.py 入口 UAC 提权（真实安装需管理员，打包 uac_admin 之外还建议 exe-level）
- [ ] 安装失败回滚机制 / 日志归档（安装日志保存到 %LOCALAPPDATA%\OpenClaw\logs）
- [ ] index.html  同步改为「OpenClaw 工作台」
- [ ] 自动检查升级（可选：版本号对比 release 地址）
- [ ] Node.js 静默安装 msiexec 日志排查脚本
- [ ] 仪表盘「Default model: Off」现象跟踪（openclaw 前端显示逻辑，待确认是否需要在工具内补偿）

## 🔷 竞品调研 + 托盘卡片面板（2026-08-30）

**竞品库**：`D:\AI_PROJECT\openclaw-competitors\`（9 仓库 clone 完成）

- 直接同类：01 agentkernel/openclaw-desktop（Electron，打包期预装 Node，黑屏事故复盘）、02 easyclaw（WSL 路线，对小白不友好）、03 daxiondi（Tauri+离线载荷+Codex 复用）、04 ChatClaw（Go/Wails 悬浮球+托盘）、05 standalone（Inno 零依赖）、06 offline-package（bat 编号入口）、07 openclaw-windows-node（官方 C# 托盘卡片面板——对标对象）、08 openclaw-guide（中文文档站）、09 portable（npmmirror+token 自动复制）
- 结论：内置便携 Node 是竞品最优解（预装 node.exe ~93MB + openclaw ~371MB）；**用户已决定 Node 维持现状（检测/装系统 Node）**
- 用户点名对标 07 的面板：配色（近黑+浅灰+绿/黄/红点+蓝 Toggle）、功能（连接开关、状态行、Gateway 卡、会话/用量行）、"直接配置 claw"入口

### ✅ 面板 v2 已完成（2026-08-30，默认启用，OCW_PANEL=0 回退系统菜单）

- [X] 原版 07 配色：深底 #15161C、浅灰文字、绿/黄/红状态点、蓝色 Toggle、分段卡+badge"Local"
- [X] 标题行 + 右侧连接 Toggle（点击 = gateway start/stop，全局互斥）
- [X] 状态行（点+状态文字+addr+右侧版本）、"使用模型"行
- [X] Gateway 卡（卡头+badge、"127.0.0.1:18789 · 本机 1 节点"）
- [X] 按钮组：打开工作台（主色通栏）/ 控制面板 / 重新配置 / 修复网关 / 退出
- [X] 删除「复制诊断」（用户要求不出现在面板）；新配色直接照原版截图

### ⏳ 待办：面板剩余功能（记自 07 原版截图/红圈）

- [X] **会话列表栏**（09-01 完成）：`openclaw sessions --json` 数据源（实测字段 totalTokens/contextTokens/model/ageMs）；会话列表面板（标题+时间/模型+token/上下文进度条 >80%黄 >95%红），点击行打开对应会话官方页；主面板 Sessions 行入口+摘要
- [X] **上下文进度条**（同上实现；主会话那条也走 CLI 数据）
- [ ] 面板实时刷新（Updated 2s ago）——现在每次右键重新抓快照；可后续靠 15s tip 轮询线程带出
- [ ] Usage 成本行（$13.84 · 304.1M tokens）——WS `usage.cost`/`usage.status` 才有（需要 connect 签名：07 的 DeviceIdentity 体系）；CLI 侧无等价命令 → 成本行后置
- [ ] **权限开关**（Permissions 直接开关能力）——需网关能力清单接口；07 `perm-toggle|*` 参考
- [ ] 卡片 hover 悬浮层（版本/在线客户端/待审批计数）——07 GatewayCard 展开细节
- [ ] WS 实时推送（可选）：07 用 connect.challenge+device 签名（C# DeviceIdentityConnectEnvelopeSigner）；本地 SDK 需复刻签名算法——价值比 CLI 轮询低，暂不做
- [ ] 菜单入口项：Chat/Canvas（官方页可用性确认后加直达按钮）

### 研究结论（WS 协议，留档）

- 网关 WS：ws://127.0.0.1:<port></port>/ → connect.challenge(nonce/ts) → connect(params: role/auth.token/client/minProtocol:4/maxProtocol:4)
- 服务器对纯 token 连接的拒绝原因未完全确认（可能要求 device identity——枚举见 AUTH_*_MISMATCH）
- sessions.list / usage / usage.cost / sessions.patch / sessions.delete 等 RPC 方法；payload tryGetProperty("sessions")
- **最终决定：CLI 方案（--json）代替 WS**——免签名、稳定、本机实测 2-3s

### ⏳ Node 路线（用户已拍板维持现状，记录备选）

- [ ] 备选 1：打包期抠 node.exe（93MB）进包（01 的 download-node.ts 做法），openclaw 走 npmmirror 在线装（1-3 分钟）
- [ ] 备选 2：全程联网下载便携 Node + npmmirror 装 openclaw（09 的 start-online.bat 配方；token 自动复制+`?token=` 自动开浏览器也是 09 的）
- [ ] 端口占用自动 +1 回退（09 start.bat：18789→18790）

---

## ✅ 已完成的里程碑（2026-08-24 ~ 08-26）

- [X] tkinter 版核心安装器（环境检测/PATH 修复/提权/40+ 服务商/5 步配置）
- [X] Web UI 重构：pywebview + HTML/CSS/JS（深色玻璃拟态）
- [X] 安装器 + 启动器一体：首页双态（未安装引导/已安装状态+使用入口）
- [X] API Key 强制填写（无跳过）；已配置模型下拉切换 + 模型增删管理（config patch）
- [X] 控制面板内嵌窗口（token 自动认证、系统原生标题栏、底部完整、零遮挡）
- [X] 网关修复带真实 ping 轮询；主页状态 15s 轮询
- [X] 演练模式语义：仅安装动作不执行，模型/服务功能真实（可当正式启动器用）
- [X] 主题系统：11 配色 × 11 风格 = 121 组合（图标随风格、面板按钮随配色、localStorage 记忆）
- [X] 鼠标跟随毛玻璃波纹；SVG 图标系统
- [X] 全套自动化审计/Fix（桥接竞态、js_api 递归爆炸、config patch 参数冲突、注入脚本顺序、js_api 漏传、100vh 截断等）
