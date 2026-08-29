# 🦞 OpenClaw 一键安装工具 - 开发计划

## 项目概述

为电脑小白打造的 OpenClaw 一键安装工具，Windows 平台，点击几下即可完成从零到可用的全部流程。

**目标用户：** 不会命令行、不懂技术的普通用户  
**目标平台：** Windows 10/11  
**最终交付：** 一个 `.exe` 双击即可运行的安装器

---

## GUI 风格要求 ⭐

**简约卡通风格**：
- 配色：深色背景（#1e1e2e）+ 龙虾红主题色（#f38ba8）
- 图标：emoji 图标（🦞🔍📦⚙️🔑🎉），后续可替换为卡通图标
- 卡片：圆角卡片布局，间距宽松
- 按钮：圆角按钮，hover 变色
- 进度条：彩色渐变进度条
- 整体感觉：简洁、可爱、不吓人

---

## 完整安装链路

### 阶段一：软件安装（全自动）

| 步骤 | 操作 | 说明 |
|------|------|------|
| 1 | 检测环境 | 网络、Node.js、npm、OpenClaw |
| 2 | 配置 npm 镜像 | `npm config set registry https://registry.npmmirror.com` |
| 3 | 安装 Node.js | 从 npmmirror 下载 MSI，静默安装 |
| 4 | 安装 OpenClaw | `npm install -g openclaw` |
| 5 | 验证安装 | 检查版本号 |

### 阶段二：AI 模型配置（核心步骤）⭐

| 步骤 | 操作 | 说明 |
|------|------|------|
| 1 | 选择服务商 | 搜索下拉框，40+ 服务商可选 |
| 2 | 获取 API Key | 右侧显示手把手指引，含官网链接 |
| 3 | 填入 API Key | 输入框 + 显示/隐藏 + 格式提示 |
| 4 | 验证 Key | 点击按钮验证 Key 是否有效 |

### 阶段三：服务配置（全自动）

| 步骤 | 命令 | 说明 |
|------|------|------|
| Step 1/5 | `openclaw onboard --non-interactive --accept-risk` | 配置 AI 模型 |
| Step 2/5 | `openclaw gateway install` | 安装守护进程（开机自启） |
| Step 3/5 | `openclaw gateway start` | 启动 Gateway 服务 |
| Step 4/5 | `openclaw gateway status` | 健康检查 |
| Step 5/5 | `openclaw skills install --all` | 安装推荐 Skills |

---

## 配置页设计（重中之重）⭐

### 左右分栏布局

```
┌─────────────────────────────────┬─────────────────────────────────┐
│  ① 选择服务商：                  │  📖 DeepSeek — 获取 API Key     │
│  ┌─────────────────────────────┐│  🔗 platform.deepseek.com       │
│  │ 🔍 输入关键词搜索...        ││                                 │
│  ├─────────────────────────────┤│  1. 打开 platform.deepseek.com  │
│  │ ── 🇨🇳 国产 ──              ││  2. 点击右上角「注册」           │
│  │   DeepSeek                  ││  3. 用手机号注册并登录           │
│  │   Z.AI / 智谱 GLM           ││  4. 左侧菜单点击「API Keys」    │
│  │   Moonshot (Kimi)           ││  5. 点击「创建 API Key」        │
│  │   ...                       ││  6. 复制生成的 Key（sk-开头）   │
│  │ ── 🌐 聚合平台 ──           ││                                 │
│  │   OpenCode Go               ││  格式：sk- 开头的一串字符       │
│  │   OpenRouter                ││  示例：sk-xxxxxxxxxxxxxxxx      │
│  │ ── 🇺🇸 美国 ──              ││                                 │
│  │   OpenAI (ChatGPT)          ││  [🔗 点击打开官网获取 Key]      │
│  │   Anthropic (Claude)        ││                                 │
│  └─────────────────────────────┘│                                 │
│                                 │                                 │
│  ② 填入 API Key：               │                                 │
│  ┌─────────────────────────────┐│                                 │
│  │ sk-xxxxxxxxxxxx    [👁显示] ││                                 │
│  └─────────────────────────────┘│                                 │
│  格式：sk- 开头的一串字符       │                                 │
│                                 │                                 │
│  [🔍 验证 Key 是否正确]         │                                 │
│  ✅ Key 格式正确！可以继续安装   │                                 │
└─────────────────────────────────┴─────────────────────────────────┘
```

### 每个服务商的指引数据

每个 provider 包含：
- `id` — 内部标识
- `name` — 显示名称
- `group` — 分组（国产/聚合/美国/其他/本地）
- `auth_choice` — onboard 命令参数
- `key_param` — API Key 参数名
- `needs_key` — 是否需要 Key
- `url` — 官网地址（可点击跳转）
- `steps` — 获取 Key 的步骤列表（123456 步）
- `key_format` — Key 格式说明
- `key_example` — Key 示例

### 安全机制

- 选了需要 Key 的服务商但没填 Key → 弹窗提醒「没有 Key 将无法使用」
- 可以选择跳过，但会明确提示后果
- Key 输入框默认隐藏（show="*"），可切换显示

---

## 支持的 AI 服务商（40+）

### 🇨🇳 国产
| ID | 名称 | 官网 | Key 格式 |
|----|------|------|----------|
| `deepseek` | DeepSeek | platform.deepseek.com | sk-xxx |
| `zai` | Z.AI / 智谱 GLM | open.bigmodel.cn | xxx |
| `moonshot` | Moonshot (Kimi) | platform.moonshot.cn | sk-xxx |
| `minimax` | MiniMax | platform.minimaxi.com | eyJxxx |
| `qwen-oauth` | 通义千问 Qwen | dashscope.aliyun.com | sk-xxx |
| `volcengine-plan` | 火山引擎 (豆包) | console.volcengine.com | xxx |
| `qianfan` | 百度千帆 | qianfan.baidubce.com | xxx |
| `tencent-tokenhub` | 腾讯 TokenHub | console.cloud.tencent.com | xxx |
| `xiaomi` | 小米 MiMo | open.mi.com | xxx |
| `stepfun` | 阶跃星辰 | platform.stepfun.com | xxx |

### 🌐 聚合平台
| ID | 名称 | 官网 | Key 格式 |
|----|------|------|----------|
| `opencode-go` | OpenCode Go | opencode.ai | sk-xxx |
| `opencode-zen` | OpenCode Zen | opencode.ai | sk-xxx |
| `openrouter` | OpenRouter | openrouter.ai | sk-or-xxx |
| `clawrouter` | ClawRouter | clawrouter.ai | xxx |
| `vercel-ai-gateway` | Vercel AI Gateway | vercel.com | xxx |

### 🇺🇸 美国
| ID | 名称 | 官网 | Key 格式 |
|----|------|------|----------|
| `openai` | OpenAI (ChatGPT) | platform.openai.com | sk-xxx |
| `anthropic` | Anthropic (Claude) | console.anthropic.com | sk-ant-xxx |
| `google` | Google Gemini | aistudio.google.com | AIza-xxx |
| `xai` | xAI (Grok) | console.x.ai | xai-xxx |
| `cohere` | Cohere | dashboard.cohere.com | xxx |
| `groq` | Groq | console.groq.com | gsk_xxx |
| `mistral` | Mistral AI | console.mistral.ai | xxx |
| `nvidia` | NVIDIA NIM | build.nvidia.com | nvapi-xxx |

### 🌍 其他
| ID | 名称 | 官网 | Key 格式 |
|----|------|------|----------|
| `deepinfra` | DeepInfra | deepinfra.com | xxx |
| `together` | Together AI | api.together.xyz | xxx |
| `cerebras` | Cerebras | cloud.cerebras.ai | xxx |
| `huggingface` | Hugging Face | huggingface.co | hf_xxx |

### 🏠 本地（无需 Key）
| ID | 名称 | 官网 |
|----|------|------|
| `ollama` | Ollama | ollama.com |
| `lmstudio` | LM Studio | lmstudio.ai |

---

## 技术架构

| 组件 | 技术 | 说明 |
|------|------|------|
| GUI | Python + tkinter | 简约卡通风格 |
| 打包 | PyInstaller | 单个 exe，~12MB |
| 镜像 | npmmirror | 国内加速 |
| 配置 | openclaw onboard --non-interactive | 全自动 |

---

## 进度追踪

| 阶段 | 状态 | 说明 |
|------|------|------|
| Phase 1: 核心安装器 | ✅ 完成 | GUI + Node.js 自动安装 |
| Phase 2: OpenClaw 安装 | ✅ 完成 | npm install -g openclaw（可指定目录，默认 D 盘） |
| Phase 3: 配置向导 | ✅ 完成 | 40+ Provider + 搜索 + 手把手指引 |
| Phase 4: 服务配置 | ✅ 完成 | onboard + gateway + daemon + skills |
| Phase 5: 增强体验 | ⬜ 未开始 | 图标、快捷方式、卸载等 |
| Phase 6: Web UI 重构 | 🚧 进行中 | pywebview 前端套壳完成，待打包验证 |

---

*Created: 2026-08-24*
*Updated: 2026-08-24 23:20 — 添加配置页设计、手把手指引、安全机制*
