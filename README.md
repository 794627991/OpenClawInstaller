# 🦞 OpenClaw 一键安装器

为电脑小白打造的 OpenClaw 图形化一键安装工具。

## ✨ 特性

- 🖱️ **全程 GUI** — 点点鼠标就能装好，不需要任何命令行知识
- 🪞 **国内镜像** — 所有下载走淘宝镜像，不需要梯子/VPN
- 📦 **自动安装** — Node.js、npm、OpenClaw 全自动处理
- 🔑 **配置向导** — 图形化选择 AI 服务商、填入 API Key
- 🎨 **深色主题** — 龙虾红色调的现代界面

## 🚀 快速开始

### 方法一：直接运行（开发模式）

```bash
# 1. 安装依赖
pip install pyinstaller

# 2. 打包
pyinstaller --clean --noconfirm --noconsole --onefile src/installer.py --name "OpenClaw一键安装器"

# 3. 运行
dist\OpenClaw一键安装器.exe
```

### 方法二：使用构建脚本

```bash
# 双击运行
build.bat
```

## 📁 项目结构

```
龙虾一键安装/
├── src/
│   └── installer.py          # 🎯 主程序（Python + tkinter GUI）
├── config/
│   └── mirrors.json          # 镜像配置
├── installer/
│   └── setup.iss             # Inno Setup 脚本（生成 .exe 安装器）
├── resources/                # 图片资源（可选）
├── build.bat                 # 一键构建脚本
├── installer.spec            # PyInstaller 配置
└── README.md
```

## 🛠️ 构建步骤

### 前置要求

| 工具 | 用途 | 必需？ |
|------|------|--------|
| Python 3.8+ | 运行 GUI 程序 | ✅ 是 |
| PyInstaller | 打包成 exe | ✅ 是 |
| Inno Setup 6+ | 生成安装器 | ⬜ 可选 |

### 完整构建流程

```bash
# 1. 安装 Python 依赖
pip install pyinstaller

# 2. PyInstaller 打包（生成绿色版）
pyinstaller --clean --noconfirm installer.spec

# 3. 测试
dist\OpenClaw一键安装器\OpenClaw一键安装器.exe

# 4. （可选）用 Inno Setup 生成安装器
#    打开 installer\setup.iss → 编译 → 生成 .exe
```

## 🔧 工作原理

```
用户双击安装器
    ↓
[欢迎页] → [环境检测] → [选择目录] → [安装进度] → [配置API Key] → [完成]
    │              │              │              │              │
    │         检测 Node.js    自动下载       npm install    填入 Key
    │         检测 npm       安装 Node.js   openclaw       onboard
    │         检测网络       配置镜像       -g openclaw    验证
    │
    └── 所有下载走 npmmirror.com（淘宝镜像）
```

## 🌐 镜像说明

| 资源 | 镜像地址 | 说明 |
|------|----------|------|
| npm 包 | registry.npmmirror.com | npm 包下载加速 |
| Node.js | npmmirror.com/mirrors/node | Node.js 安装包下载 |
| OpenClaw | 通过 npm 镜像安装 | 无需额外配置 |

## 📝 用户使用流程

1. 双击 `OpenClaw一键安装器.exe`
2. 点击「开始检测」
3. 看到环境检测结果，点击「下一步」
4. 确认安装目录（默认即可），点击「下一步」
5. 等待自动安装（约 3-5 分钟）
6. 选择 AI 服务商，填入 API Key
7. 点击「完成」，OpenClaw 自动启动

## ❓ 常见问题

**Q: 需要管理员权限吗？**
A: 安装 Node.js 时可能需要，安装器会自动请求 UAC 提权。

**Q: 安装后找不到 openclaw 命令？**
A: 可能需要重启终端或重启电脑，让 PATH 环境变量生效。

**Q: 国内网络能用吗？**
A: 可以，所有下载都走国内镜像（npmmirror），不需要代理。

**Q: 可以修改 AI 模型配置吗？**
A: 可以，安装后运行 `openclaw configure` 重新配置。

## 📜 许可证

MIT License
