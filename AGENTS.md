# AGENTS.md

## Project Overview

Learn Claude Code 是一个 0 到 1 的智能体（Agent）Harness 工程教学项目，通过 20 个渐进式章节，教授如何构建围绕大模型的智能体运行环境（Harness）——包括工具系统、上下文压缩、子智能体、任务系统、权限治理、团队协作等核心机制。

## Architecture

### 技术栈

- **后端（Python）**: Python 3.11+，Anthropic SDK（anthropic>=0.25.0），python-dotenv，pyyaml
- **前端（Web 平台）**: Next.js 16，React 19，TypeScript 5，Tailwind CSS 4，Framer Motion，lucide-react
- **文档/多语言**: 中文（源语言）、英文、日文三语 README 和文档

### 架构模式

项目采用**分层渐进式教学架构**，每个章节独立成章，共享统一的智能体核心循环：

```
Agent = Model (LLM) + Harness (工具 + 知识 + 上下文 + 权限)
```

- **s01-s04**: 核心能力（循环、工具、权限、Hooks）
- **s05-s08**: 复杂处理（Todo 计划、子智能体、技能加载、上下文压缩）
- **s09-s11**: 记忆与恢复（记忆系统、系统提示组装、错误恢复）
- **s12-s14**: 长任务（任务系统、后台任务、定时调度）
- **s15-s18**: 多智能体协作（智能体团队、团队协议、自主智能体、Worktree 隔离）
- **s19-s20**: 扩展与综合（MCP 插件、综合智能体）

### 核心模块关系

```
s01 (Agent Loop) ──→ s02 (Tool Use) ──→ s03 (Permission) ──→ s04 (Hooks)
                                                              │
                    ┌─────────────────────────────────────────┘
                    ▼
              s05 (TodoWrite) ──→ s06 (Subagent) ──→ s07 (Skill) ──→ s08 (Context Compact)
                                                                      │
                    ┌─────────────────────────────────────────────────┘
                    ▼
              s09 (Memory) ──→ s10 (System Prompt) ──→ s11 (Error Recovery)
                    │
                    ▼
              s12 (Task System) ──→ s13 (Background) ──→ s14 (Cron)
                    │
                    ▼
              s15-s18 (Agent Teams / Protocols / Autonomous / Worktree)
                    │
                    ▼
              s19 (MCP Plugin) ──→ s20 (Comprehensive Agent)
```

## Build & Commands

### Python 虚拟环境（必读）

项目根目录下已创建专用的 Conda 虚拟环境 `.venv/`，**必须使用该环境运行所有 Python 代码**，否则会因系统 Python（如 3.9）缺少 anthropic SDK 等依赖而报 `ModuleNotFoundError`。

| 项 | 值 |
|----|-----|
| 位置 | `.venv/` (项目根目录下，已加入 `.gitignore`) |
| 创建方式 | `conda create -p ./.venv python=3.11 -y` |
| Python 版本 | 3.11.15 |
| Python 解释器 | `.venv/python.exe` |
| 已装依赖 | anthropic 0.120.2, python-dotenv 1.2.2, PyYAML 6.0.3, httpx, jiter, pydantic |

**三种推荐运行方式**（任选其一）：

```bash
# 方式 1：直接使用 .venv 的 python.exe（最简单，推荐）
.venv/python.exe s20_comprehensive/code.py
.venv/python.exe test_models.py

# 方式 2：通过 conda 激活
conda activate ./.venv
python s20_comprehensive/code.py

# 方式 3：安装/补全依赖到 .venv
.venv/python.exe -m pip install -r requirements.txt
```

> ⚠️ **常见错误**：直接使用 `python xxx.py` 默认调用系统 Python（如 `C:\Program Files\python\python.exe` 是 3.9 版本），会因缺少 anthropic 等依赖而失败。

### Python 环境配置

```bash
# 配置环境变量（.env 已存在则跳过；模板见 .env.example）
cp .env.example .env
# 编辑 .env 设置 ANTHROPIC_API_KEY、MODEL_ID、MODEL_POOL、ANTHROPIC_BASE_URL

# 运行单章节代码（必须使用 .venv）
.venv/python.exe s01_agent_loop/code.py
.venv/python.exe s08_context_compact/code.py
.venv/python.exe s20_comprehensive/code.py

# 运行旧版代码
.venv/python.exe agents/s01_agent_loop.py
.venv/python.exe agents/s_full.py
```

### Web 前端

```bash
cd web

# 安装依赖
npm install

# 开发模式（带自动内容提取）
npm run dev
# 访问 http://localhost:3000

# 构建生产版本
npm run build

# 启动生产服务器
npm start
```

### 测试

```bash
# Python 测试（必须使用 .venv）
.venv/python.exe -m pytest tests -q

# Web 前端类型检查
cd web && npx tsc --noEmit

# Web 前端构建验证
cd web && npm run build

# 大模型可用性测试（验证 .env 中 MODEL_POOL 配置的所有模型）
.venv/python.exe test_models.py                      # 测试所有模型
.venv/python.exe test_models.py qwen3.7-plus qwen3.8-max  # 测试指定模型
.venv/python.exe test_models.py --verbose            # 显示详细错误信息
# 结果保存至 test_models_result.json，退出码 0=全部可用，1=部分失败
```

## Code Style

### Python

- 使用 Python 3.11+ 特性
- 每个类、方法上方添加中文注释说明功能
- 遵循 PEP 8 命名规范
- 使用类型提示（Type Hints）

### TypeScript/React

- 使用 TypeScript 严格模式
- 组件采用函数式组件 + Hooks 模式
- CSS 使用 Tailwind CSS 4 语法
- 文件命名：组件用 kebab-case，工具文件用 camelCase

### 通用

- 每个章节目录自包含：README（中/英/日三语）、code.py 独立实现、images/ 架构图
- 新增章节需同步三语翻译
- 保持章节间的渐进依赖关系

## Testing

### 测试框架

- **Python**: pytest（tests/ 目录）
- **前端**: TypeScript 类型检查 + Next.js 构建验证

### 测试约定

- `tests/test_agents_smoke.py`: 智能体核心烟雾测试
- `tests/test_compaction_tool_pairs.py`: 上下文压缩工具对测试
- `tests/test_s_full_background.py`: 综合智能体后台功能测试
- `tests/test_todo_write_string_input.py`: TodoWrite 输入格式测试

### CI/CD

- GitHub Actions 双流水线：
  - **Test 流水线**: Python 烟雾测试 + Web 构建验证
  - **CI 流水线**: TypeScript 类型检查 + Web 构建
- 在 push/PR 到 main 分支时自动触发

## Security

- **API 密钥管理**: 通过 `.env` 文件配置，`.env` 已加入 `.gitignore`
- **环境变量**: 使用 `python-dotenv` 加载，支持 ANTHROPIC_BASE_URL 等可选配置
- **权限治理**: 项目教学中包含权限系统设计（s03_permission），包含沙箱隔离、审批流程等
- **MCP 安全**: s19_mcp_plugin 涉及外部工具接入，需注意信任边界
- **Worktree 隔离**: s18_worktree_isolation 确保任务在独立目录中执行

## Configuration

### 环境变量（.env）

| 变量 | 必填 | 说明 |
|------|------|------|
| `ANTHROPIC_API_KEY` | 是 | Anthropic API 密钥（或阿里云百炼等兼容端点的 API Key） |
| `MODEL_ID` | 是 | 首选模型 ID，必须是 `MODEL_POOL` 中的一个 |
| `MODEL_POOL` | 是 | 模型池，逗号分隔；额度耗尽时按顺序自动切换到下一个 |
| `ANTHROPIC_BASE_URL` | 否 | 兼容 Anthropic 的第三方端点（不填则默认 Anthropic 官方） |
| `FALLBACK_MODEL_ID` | 否 | （遗留）单模型降级，已被 `MODEL_POOL` 取代，无需配置 |

### 当前实际配置（阿里云百炼）

项目 `.env` 当前已配置阿里云百炼端点，享有 14 个模型各 100 万 token 的免费额度（90 天有效）：

```bash
ANTHROPIC_API_KEY=sk-xxxx
MODEL_ID=qwen3.7-plus
MODEL_POOL=qwen3.7-plus,qwen3.7-plus-2026-05-26,qwen3.7-max,qwen3.7-max-2026-06-08,qwen3.7-max-2026-05-20,qwen3.7-max-2026-05-17,qwen3.7-max-preview,qwen3.8-max,deepseek-v4-flash-0731,glm-5.2,kimi-k2.7-code,qwen3.5-ocr,qwen3.7-flash,qwen3.7-flash-2026-07-15
ANTHROPIC_BASE_URL=https://dashscope.aliyuncs.com/apps/anthropic
```

### 模型池机制（s20_comprehensive/code.py）

项目在 `s20_comprehensive/code.py` 中实现了多模型池自动切换机制，主要组件：

| 组件 | 位置 | 作用 |
|------|------|------|
| `ModelPool` 类 | `s20_comprehensive/code.py` L1220-1255 | 维护可用模型列表，标记耗尽模型，切换下一个 |
| `AllModelsExhaustedError` | `s20_comprehensive/code.py` L1215-1217 | 所有模型额度耗尽时抛出，触发无 token 提示 |
| `is_quota_exhausted_error` | `s20_comprehensive/code.py` L1258-1282 | 识别配额耗尽错误（含阿里云专属错误码 `AllocationQuota.FreeTierOnly`） |
| `RecoveryState` | `s20_comprehensive/code.py` L1285-1295 | 错误恢复状态，集成 ModelPool |
| `with_retry` | `s20_comprehensive/code.py` L1293-1350 | 统一重试包装，处理 429/529/配额耗尽三类错误 |

**工作流程**：

```
启动 → 加载 MODEL_POOL（14 个模型）→ 用 MODEL_ID 调用
  ↓ 遇到 quota/欠费/AllocationQuota.FreeTierOnly 错误
标记当前模型为已耗尽 → 切换到下一个未耗尽模型 → 立即重试（不消耗重试次数）
  ↓ 持续切换直到找到可用模型
正常返回响应
  ↓ 所有 14 个模型都耗尽
抛出 AllModelsExhaustedError → agent_loop 捕获 → 打印红色 [无token] 提示 → 优雅退出
```

### 切换到其他提供商

修改 `.env` 中 `ANTHROPIC_BASE_URL` 和 `MODEL_ID` 即可。参考 `.env.example` 中的预置配置：

- **Anthropic 官方**：`MODEL_ID=claude-sonnet-4-6`，无需 `ANTHROPIC_BASE_URL`
- **MiniMax**：`ANTHROPIC_BASE_URL=https://api.minimax.io/anthropic`，`MODEL_ID=MiniMax-M2.5`
- **GLM（智谱）**：`ANTHROPIC_BASE_URL=https://api.z.ai/api/anthropic`，`MODEL_ID=glm-5`
- **Kimi（月之暗面）**：`ANTHROPIC_BASE_URL=https://api.moonshot.ai/anthropic`，`MODEL_ID=kimi-k2.5`
- **DeepSeek**：`ANTHROPIC_BASE_URL=https://api.deepseek.com/anthropic`，`MODEL_ID=deepseek-chat`

### 查询免费额度（阿里云百炼）

阿里云百炼未公开免费额度查询 API，需通过控制台查看：

- [免费额度页面](https://bailian.console.aliyun.com/?tab=costing-balance#/costing-balance/free-quota)：查看所有模型剩余量+过期时间（推荐）
- [模型用量页面](https://bailian.console.aliyun.com/?tab=costing-balance#/costing-balance/usage-statistics)：按时间维度查看历史消耗

**建议**：开启「免费额度用完即停」开关，额度耗尽时返回明确的 `403 AllocationQuota.FreeTierOnly` 错误码，便于项目精准识别并自动切换。

### 前端配置

- `web/next.config.ts`: Next.js 配置
- `web/tsconfig.json`: TypeScript 配置
- `web/tailwind.config.mjs`: Tailwind CSS 配置
- `web/postcss.config.mjs`: PostCSS 配置

## 关键目录与文件

| 路径 | 说明 |
|------|------|
| `s01_*/s20_*` | 20 个章节的独立实现（当前主线） |
| `agents/` | 旧版 12 章节代码（保留用于过渡） |
| `docs/` | 旧版 12 章节文档（保留用于过渡） |
| `web/` | Next.js 学习平台前端 |
| `skills/` | s07 技能系统定义 |
| `tests/` | 测试用例 |
| `.trae/` | Trae IDE 配置和文档 |
| `.venv/` | 项目专用 Python 3.11 虚拟环境（必用，已 gitignore） |
| `.env` | 实际生效的大模型配置（已 gitignore，含 API Key） |
| `.env.example` | 配置模板（提供 Anthropic/MiniMax/GLM/Kimi/DeepSeek 等多提供商示例） |
| `requirements.txt` | Python 依赖清单（anthropic>=0.25.0, python-dotenv, pyyaml） |
| `test_models.py` | 大模型可用性测试脚本（纯标准库实现，验证 MODEL_POOL 中所有模型） |
| `test_models_result.json` | 测试结果 JSON（运行 test_models.py 后生成，已 gitignore） |
| `AGENTS.md` | 本文件，Trae/Claude Code 等 Agent 工具的项目指引 |

## Trae IDE 配置建议

为确保 Trae 在该项目中正确使用 Python 环境，建议在 `.vscode/settings.json`（如不存在可创建）中指定解释器：

```json
{
  "python.defaultInterpreterPath": "${workspaceFolder}/.venv/python.exe",
  "python.terminal.activateEnvironment": true
}
```

这样 Trae 内置终端和代码跳转都会自动使用 `.venv`，避免误用系统 Python。