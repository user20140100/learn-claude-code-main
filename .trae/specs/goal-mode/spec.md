# Goal Mode 需求文档

## 1. 背景与目标

### 1.1 背景

当前 s20_comprehensive 的 agent_loop 采用"一问一答"模式：用户输入 → agent 执行一轮或多轮工具调用 → 输出结果 → 等待下一条用户输入。这种模式适合短任务，但不适合需要多步骤自主执行的长任务。

Codex 的 Goal Mode 提供了一个更好的范式：用户设定目标 → agent 自主执行直到完成 → 用户可以随时暂停、追加指令、继续执行。

### 1.2 目标

在 s20_comprehensive 的基础上实现 Goal Mode，核心特征：
- 用户通过 `/goal` 命令设定目标，agent 持续执行直到模型判断目标达成
- 执行过程中用户可随时暂停（手动或权限审批触发），暂停期间可追加指令
- agent 可通过工具发起权限审批，审批时暂停整个 goal 等待用户选择
- 支持跨会话的暂停/恢复——进程重启后仍可继续之前的 goal

### 1.3 非目标

- 不改变现有普通对话模式（s20 默认行为保持不变）
- 不引入新的 LLM 调用方式或模型体系
- 不改 s01~s19 各章节的代码（本需求仅描述在 s20 层面新增的功能）

---

## 2. 核心概念定义

| 概念 | 定义 |
|------|------|
| `Goal` | 用户通过 `/goal` 命令设定的一个执行目标，包含目标描述、上下文、状态等 |
| `Goal Context` | 每个 goal 独立维护的上下文副本，包含该 goal 执行过程中的 messages、工具调用历史、todo 列表等 |
| `Goal Run` | goal 从启动到完成/终止/暂停的一次执行实例 |
| `Goal State` | goal 的当前状态，见 4.1 状态机 |

---

## 3. 整体架构

```
用户 CLI
    │
    ▼
┌─────────────────────────────────────────────┐
│           SessionManager (现有)               │
│  ┌───────────────────────────────────────┐  │
│  │           GoalManager (新增)           │  │
│  │  管理当前 session 内的 goal 状态       │  │
│  │  - 暂停/恢复 goal                     │  │
│  │  - goal 上下文持久化与加载            │  │
│  │  - goal 生命周期回调                  │  │
│  └───────────────────────────────────────┘  │
│  ┌───────────────────────────────────────┐  │
│  │         agent_loop (修改)             │  │
│  │  - 支持 goal 模式入口                 │  │
│  │  - goal 级暂停与恢复                  │  │
│  │  - 与 GoalManager 协作                │  │
│  └───────────────────────────────────────┘  │
└─────────────────────────────────────────────┘
    │                    │
    ▼                    ▼
┌─────────┐      ┌──────────────────┐
│ 普通对话 │      │  Goal Mode       │
│ 模式    │      │  /goal <描述>    │
│ (不变)  │      │  agent_loop 自主 │
│         │      │  执行直到完成     │
│         │      │  用户可暂停/继续  │
└─────────┘      └──────────────────┘
```

---

## 4. Goal 状态机

### 4.1 五状态机

```
                        ┌──────────────────┐
                        │  GOAL_RUNNING    │
                        │  (goal 正在执行)  │
                        └────────┬─────────┘
                                 │
              ┌──────────────────┼──────────────────┐
              ▼                  ▼                  ▼
    ┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐
    │  GOAL_PAUSED    │ │  GOAL_COMPLETED │ │ GOAL_TERMINATED │
    │  (goal 已暂停)   │ │  (goal 已完成)   │ │ (goal 被终止)    │
    └────────┬────────┘ └─────────────────┘ └─────────────────┘
             │
             │ 用户继续
             ▼
    ┌─────────────────┐
    │  GOAL_AWAITING  │
    │   PERMISSION    │
    │  (等待用户审批)   │
    └─────────────────┘
```

### 4.2 状态定义

| 状态 | 说明 | 触发条件 | 可转移至 |
|------|------|----------|----------|
| `GOAL_RUNNING` | goal 正在执行中 | `/goal` 命令启动，或从 PAUSED 恢复 | PAUSED, COMPLETED, TERMINATED |
| `GOAL_PAUSED` | goal 被用户手动暂停 | 用户输入 `/pause` 或 Ctrl+C | RUNNING（用户输入 `continue`） |
| `GOAL_AWAITING_PERMISSION` | 等待用户对工具权限审批做出选择 | 工具执行前权限检查要求用户确认 | RUNNING（批准后），TERMINATED（拒绝后取消当前 goal） |
| `GOAL_COMPLETED` | goal 正常完成 | 模型判断目标达成，或达到步数上限 | —（终态） |
| `GOAL_TERMINATED` | goal 被终止 | 用户主动终止，或权限被拒绝且用户确认取消 | —（终态） |

### 4.3 状态转换事件

| 事件 | 从 → 到 | 说明 |
|------|---------|------|
| `START_GOAL` | — | `GOAL_RUNNING` |
| `USER_PAUSE` | `RUNNING` | → `GOAL_PAUSED` |
| `USER_RESUME` | `GOAL_PAUSED` | → `GOAL_RUNNING` |
| `PERMISSION_REQUIRED` | `RUNNING` | → `GOAL_AWAITING_PERMISSION` |
| `PERMISSION_GRANTED` | `GOAL_AWAITING_PERMISSION` | → `GOAL_RUNNING` |
| `PERMISSION_DENIED` | `GOAL_AWAITING_PERMISSION` | → `GOAL_TERMINATED`（当前 goal） |
| `GOAL_DONE` | `RUNNING` | → `GOAL_COMPLETED` |
| `STEP_LIMIT_REACHED` | `RUNNING` | → `GOAL_COMPLETED`（超时报错） |
| `USER_TERMINATE` | `RUNNING\|PAUSED` | → `GOAL_TERMINATED` |

---

## 5. Goal Mode 核心机制

### 5.1 进入 Goal Mode

```
用户输入: /goal <目标描述>
    │
    ▼
触发 UserPromptSubmit hook（goal 模式）
    │
    ▼
GoalManager 创建新 Goal 对象
    │
    ▼
从当前 Session 的 context 复制一份 Goal Context
    │
    ▼
agent_loop 以 goal_context 为输入开始执行
```

**CLI 命令规范：**
- `/goal <描述>` — 启动新 goal
- `/goal <N> <描述>` — 启动 goal 并指定最大轮数 N（可选，默认使用全局上限）
- `/pause` — 手动暂停当前 goal
- `/continue` — 恢复当前暂停的 goal
- `/status` — 查看当前 goal 的状态和执行进度
- `/goal list` — 列出当前 session 的所有 goal（含历史）

### 5.2 Goal Context（goal 独立上下文）

**设计原则：** 每个 goal 维护独立的上下文副本，执行期间与主 session 上下文隔离。

**Goal Context 包含：**
- `messages`: 该 goal 执行过程中的完整消息历史
- `todo_list`: 该 goal 执行期间管理的 todo 列表
- `task_state`: 该 goal 执行期间创建的任务状态
- `round_count`: 已执行轮数
- `start_time`: goal 启动时间
- `last_resume_time`: 最近一次恢复时间

**上下文管理策略：**
1. Goal 启动时：从当前 Session Context 浅拷贝一份作为 Goal Context
2. Goal 执行期间：所有 messages 写入 Goal Context，不写入 Session Context
3. 每执行 N 轮（如 N=10）：对 Goal Context 执行一次上下文压缩（复用 s08 的 compact 逻辑）
4. Goal 完成后：将 Goal Context 中的关键信息（目标、完成情况、关键决策）总结后追加到 Session Context
5. Goal 暂停时：将 Goal Context 完整序列化到磁盘文件

### 5.3 Goal 停止条件

**双条件判断（模型判断 + 步数兜底）：**

1. **模型自主判断**：沿用现有 `stop_reason != "tool_use"` 逻辑。当模型认为目标已完成，输出总结性文本后退出工具调用循环。
2. **步数上限兜底**：
   - 全局配置 `MAX_GOAL_ROUNDS`（如 100）
   - 每个 goal 独立计数，每执行一轮 LLM 调用 +1
   - 达到上限时触发 `STEP_LIMIT_REACHED` 事件，goal 以超时报错状态完成

### 5.4 暂停与恢复机制

#### 5.4.1 暂停触发条件

以下情况触发 goal 级暂停（而非工具级暂停）：
1. 用户手动输入 `/pause` 或 Ctrl+C
2. 工具权限检查要求用户确认（`permission_hook` 返回需要用户选择的信号）
3. 大模型调用失败（如网络错误、模型超时、配额耗尽）

**不触发暂停的情况：**
- 单个工具执行报错：将错误信息作为 `tool_result` 返回给模型，由模型自行决定下一步
- 后台任务完成通知：正常注入，不暂停

#### 5.4.2 暂停时的状态保存

goal 暂停时，GoalManager 序列化以下内容到磁盘：

```json
{
  "goal_id": "uuid",
  "session_id": "uuid",
  "state": "PAUSED",
  "goal_context": {
    "messages": [...],
    "todo_list": [...],
    "task_state": {...},
    "round_count": 42,
    "start_time": "2026-09-03T10:00:00",
    "last_resume_time": "2026-09-03T10:05:00"
  },
  "pending_permission": {
    "tool_name": "bash",
    "tool_input": {"command": "rm -rf /tmp/test"},
    "reason": "Potentially destructive command",
    "options": ["allow", "deny"]
  },
  "paused_at": "2026-09-03T10:05:00"
}
```

持久化文件路径：`.goals/<goal_id>.json`

#### 5.4.3 恢复执行

用户输入 `/continue` 后：
1. GoalManager 从磁盘加载 goal 状态
2. 将 Goal Context 中的 messages 恢复到 agent_loop
3. 如果是权限暂停，将 pending_permission 信息展示给用户，等待用户选择
4. agent_loop 从暂停位置继续执行

#### 5.4.4 暂停期间用户追加输入

goal 暂停时，CLI 重新变为可交互状态。用户可以：
- 输入普通文本（追加为新的 user message 到 goal context）
- 输入 `/continue`（恢复 goal）
- 输入 `/status`（查看 goal 状态）
- 输入 `/goal list`（查看 goal 列表）

追加的输入内容会被追加到 Goal Context 的 messages 末尾，恢复执行时由模型看到。

#### 5.4.5 并发 tool_use 处理

当一次 LLM 响应中包含多个 tool_use block，其中任何一个需要权限审批时：
- **整轮取消**：该轮所有未执行的 tool_use block 全部标记为 blocked
- 已执行的 tool_use block 结果保留在 messages 中
- 暂停 goal，等待用户审批决策
- 恢复时，模型重新调用 LLM（不重用上一轮的 tool_use 结果），基于当前 messages 重新决策

### 5.5 Goal 完成行为

goal 完成（无论正常完成还是超时报错）后的行为：
1. 输出 goal 执行总结
2. **沉淀到 Session Context**：调用模型生成执行过程与结果摘要，附带 goal 启动时的完整用户输入，以 structured message 追加到 session context，包含 `goal_description`、`goal_summary`、`goal_rounds`、`goal_status`
3. Goal 状态设为 COMPLETED，持久化到磁盘（`.goals/<goal_id>.json`）
4. 写入执行日志（`.goals/<goal_id>.log`）
5. 返回 CLI 输入状态，等待下一条命令

---

## 6. Goal 专用 Hooks

在 s04/s20 的 hooks 体系基础上新增三个 goal 生命周期 hook：

### 6.1 新增 Hook 事件

| Hook 事件 | 触发时机 | 参数 | 用途 |
|-----------|----------|------|------|
| `GoalStart` | goal 启动时 | `goal_id`, `goal_description` | 记录 goal 开始日志、初始化 goal 上下文 |
| `GoalPause` | goal 暂停时 | `goal_id`, `pause_reason` | 持久化 goal 状态、发送通知 |
| `GoalResume` | goal 恢复时 | `goal_id`, `resume_source` | 加载 goal 状态、恢复执行环境 |
| `GoalComplete` | goal 完成时 | `goal_id`, `success`, `summary` | 输出总结、沉淀 memory、清理临时资源 |
| `GoalTerminate` | goal 终止时 | `goal_id`, `reason` | 终止时清理、记录终止原因 |

### 6.2 Hook 注册示例

```python
# 新增 goal hooks
HOOKS = {
    "UserPromptSubmit": [],
    "PreToolUse": [],
    "PostToolUse": [],
    "Stop": [],
    # 新增 goal 生命周期 hooks
    "GoalStart": [],
    "GoalPause": [],
    "GoalResume": [],
    "GoalComplete": [],
    "GoalTerminate": [],
}
```

---

## 7. 与现有系统的交互

### 7.1 Session 管理交互

**关系原则：** Goal 在 Session 内运行，Session 是 Goal 的容器。

**Session 切换行为：**
- 用户切换到另一个 session（`/resume` 或 `/new`）时：
  1. 暂停当前 session 中正在执行的 goal
  2. 持久化当前 goal 的完整状态
  3. 切换到目标 session
  4. 如果目标 session 中存在已暂停的 goal，自动恢复其状态

**Session 持久化与 Goal 持久化的关系：**
- Session 持久化文件：`.sessions/<session_id>.json`（现有）
- Goal 持久化文件：`.goals/<goal_id>.json`（新增）
- Session 索引文件中记录该 session 下所有 goal 的 ID 列表
- 通过 session 文件可以定位到该 session 下所有 goal 的持久化文件

### 7.2 Hooks 交互

**现有 hooks 不受影响：**
- `UserPromptSubmit`：goal 模式下的用户输入也触发此 hook
- `PreToolUse`：工具执行前的权限检查仍然生效，当需要用户确认时触发 goal 暂停
- `PostToolUse`：工具执行后的后处理仍然生效
- `Stop`：普通对话结束时触发；goal 完成时通过 `GoalComplete` hook 替代

**新增 goal hooks 与现有 hooks 的关系：**
- `GoalPause` 与 `PreToolUse` 的关系：`PreToolUse` 的 permission_hook 检测到需要用户确认时，返回特殊信号（如 `"AWAITING_PERMISSION"`），由 agent_loop 层捕获并触发 `GoalPause` hook，而非直接在 permission_hook 中阻塞
- 这保持了 hooks 的纯粹性——permission_hook 只负责返回决策信号，不负责暂停控制流

### 7.3 后台任务（s13）交互

- goal 暂停时，已启动的后台任务（daemon thread）**继续运行**
- goal 恢复时，通过 `inject_background_notifications()` 将累积的通知注入 messages
- 后台任务的结果通过 `<task_notification>` 格式返回，不影响 goal 的暂停状态

### 7.4 Cron 调度（s14）交互

- goal 暂停时，cron 调度器**继续运行**
- goal 恢复时，cron 触发的 prompt 按正常流程注入 messages（与后台任务通知类似）

### 7.5 Subagent（s06）交互

- 子智能体的执行完全独立于主 goal
- 主 goal 暂停时，已启动的子智能体**继续运行**
- 子智能体的结果通过 tool_result 返回给主 agent，不影响 goal 的暂停/恢复状态
- 子智能体的执行不消耗主 goal 的轮数计数

### 7.6 上下文压缩（s08）交互

- 复用现有的上下文压缩逻辑，不做特殊调整
- 但 goal context 有自己的压缩计数（独立于 session context）
- goal 每执行 N 轮（如 N=10）触发一次压缩，或当 goal context token 量接近 CONTEXT_LIMIT 时触发

### 7.7 记忆系统（s09）交互

**设计原则：** Goal 执行期间读写独立的 goal memory，goal 完成后将关键信息沉淀到 session memory。

- Goal 执行期间：读写 goal 专属的 memory（`.memory/goal_<goal_id>.md`）
- Goal 完成后：将 goal memory 中的关键信息（目标、方案、关键决策、结果）总结后追加到 session 主 memory（`.memory/MEMORY.md`）
- Goal 暂停/恢复期间：不触发 memory 读写

### 7.8 错误恢复（s11）交互

**错误分类处理：**
1. **工具执行错误**（tool_result 包含错误信息）：
   - 将完整错误信息追加到 messages，让模型自行尝试解决
   - 不暂停 goal
   - 模型可以尝试其他思路实现目标

2. **大模型调用错误**（LLM API 失败、网络超时等）：
   - 触发 goal 暂停
   - 暂停状态中记录错误信息
   - 用户恢复 goal 时可以看到错误上下文

3. **配额耗尽（AllModelsExhaustedError）**：
   - 触发 goal 暂停
   - 输出明确的无 token 提示
   - goal 状态记为 COMPLETED（以失败告终）

### 7.9 任务系统（s12）交互

- goal 执行期间创建的任务归属于当前 goal
- goal 暂停/恢复时，任务状态随 goal context 一起持久化
- goal 完成后，未完成的任务保持 pending 状态，不自动清理
- 切换 session 时，原 session 中的任务不受影响

### 7.10 MCP 插件（s19）交互

- MCP 工具执行前经过现有 `permission_hook` 检查
- 如果 MCP 工具的权限检查要求用户确认，触发 goal 级暂停
- MCP 工具不拥有独立的权限体系，统一由 s20 的 permission 层管理

---

## 8. 影响分析：s01~s20 各章与 Goal Mode 的关系

### 8.1 存在影响（需要适配或确认）的章节

| 章节 | 功能 | 影响描述 | 影响程度 |
|------|------|----------|----------|
| **s01** | Agent Loop | 核心循环需要增加 goal 模式入口和暂停/恢复逻辑 | **高** |
| **s03** | Permission | 权限检查从"阻塞 input()"改为"返回信号"，由 loop 层统一处理暂停 | **高** |
| **s04** | Hooks | 新增 GoalStart/GoalPause/GoalResume/GoalComplete/GoalTerminate 五个 hook | **中** |
| **s05** | TodoWrite | goal 模式下的 todo 列表独立于 session 级别，需要 per-goal 管理 | **中** |
| **s06** | Subagent | 子智能体独立于 goal 暂停状态，需要明确生命周期管理 | **低** |
| **s08** | Context Compact | goal context 独立压缩策略，需要扩展 compaction 支持 per-context | **中** |
| **s09** | Memory | goal 专属 memory + goal 完成后沉淀到 session memory，需要扩展 memory 路径 | **中** |
| **s11** | Error Recovery | 错误分类处理：工具错误继续、LLM 错误暂停，需要扩展 RecoveryState | **中** |
| **s12** | Task System | 任务归属 goal，需要扩展 Task 的 owner 语义（goal_id 而非 agent name） | **低** |
| **s13** | Background Tasks | 暂停时后台任务继续运行，恢复时重新注入通知，需确认 notification 队列的暂停/恢复行为 | **低** |
| **s14** | Cron Scheduler | cron 不受 goal 暂停影响，需确认 cron 注入的 prompt 是否在 goal 暂停时被缓冲 | **低** |
| **s16** | Team Protocols | 团队协议在 goal 模式下是否适用？团队内部 goal 与 session goal 的关系需明确 | **中** |
| **s17** | Autonomous Agents | 自治认领机制与 goal 模式可能存在冲突，需明确优先级 | **低** |
| **s18** | Worktree Isolation | goal 模式下的工作目录隔离是否需要与 worktree 结合？ | **低** |
| **s19** | MCP Plugin | MCP 工具权限走统一 permission_hook，需确认 MCP 工具的暂停信号传递 | **低** |
| **s20** | Comprehensive | 所有机制的集成层，新增 GoalManager 和 Goal Context 管理 | **高** |

### 8.2 不存在影响的章节

| 章节 | 说明 |
|------|------|
| **s02** | Tool Use — goal 模式复用现有工具系统，无需修改 |
| **s07** | Skill Loading — skill 加载与 goal 模式无关 |
| **s10** | System Prompt — goal 模式复用现有 system prompt 组装逻辑 |
| **s15** | Agent Teams — 团队功能在 goal 模式下为可选启用 |

---

## 9. 需求细化决策（已决议）

以下问题已在 grill 过程中确认，决策结果如下：

### 9.1 Goal 上下文与 Session 上下文的同步边界 ✅

- **决策**：goal 完成后，调用模型生成执行过程与结果摘要，同时附带 goal 启动时完整的用户输入内容
- **实现方式**：`GoalComplete` hook 中触发一次 LLM 调用，输入为 goal context 的历史 messages，输出自然语言摘要 + 原始用户输入原文
- **沉淀格式**：一条 structured message 追加到 session context，包含：
  - `goal_description`: 原始用户输入（完整内容）
  - `goal_summary`: 模型生成的执行过程与结果摘要
  - `goal_rounds`: 执行轮数
  - `goal_status`: 完成/超时/终止

### 9.2 权限审批的用户交互界面 ✅

- **决策**：结构化展示 + 多选项
- **展示格式**：
  ```
  ⚠  权限审批 [goal: <goal_id>]
  ─────────────────────────────
  工具: bash
  原因: Potentially destructive command
  命令: rm -rf /tmp/test
  ─────────────────────────────
  1. allow   - 批准执行
  2. deny    - 拒绝，终止当前 goal
  3. edit    - 编辑命令后批准（进入编辑模式）
  ─────────────────────────────
  请输入选择 [1/2/3]:
  ```
- **edit 模式**：用户选择 3 后进入命令行编辑，输入新命令后返回选项列表再次确认

### 9.3 Goal 超时的明确定义 ✅

- **决策**：仅轮数上限，不设时间上限
- **轮数定义**：1 轮 = 1 次 LLM 调用 + 该轮所有 tool_use 块执行完毕
- **计数器位置**：`agent_loop` 每完成一个完整循环（LLM → 工具执行 → messages 追加）后 round_count +1
- **配置项**：`MAX_GOAL_ROUNDS`（建议默认值 100）

### 9.4 多 Goal 并发支持 ✅

- **决策**：单 goal 并发，支持暂停队列
- **规则**：同一 session 中最多一个 RUNNING goal；用户可在 goal 暂停时启动新 goal（暂停的 goal 保持 PAUSED 状态），但不能同时运行多个 RUNNING goal
- **队列语义**：`/goal` 命令检测到已有 RUNNING goal 时返回错误提示；检测到 PAUSED goal 时询问是否替换或加入队列

### 9.5 Goal 恢复时的上下文一致性 ✅

- **决策**：goal context 完全独立于 session context
- **规则**：
  - goal 暂停期间，用户追加的输入写入 goal context，不影响 session context
  - session context 中的新增消息不会影响正在执行或暂停的 goal
  - **重要约束**：goal 处于 RUNNING 状态时，用户无法绕过 goal 直接向 session 添加消息——所有输入进入 goal context
- **恢复行为**：goal 恢复时只加载 goal context，不检测 session context 变化

### 9.6 Goal 与 /branch 命令的交互 ✅

- **决策**：goal 归属创建它的 session，不迁移
- **规则**：
  - 在 branch session 中创建的 goal 归属于该 branch，切回根 session 时该 goal 保持 PAUSED 状态
  - 切换回包含 goal 的 branch 时自动恢复该 goal
  - SessionManager 需在 session 索引中记录该 session 下的 goal_id 列表

### 9.7 Goal 执行日志 ✅

- **决策**：完整日志 + 时间戳结构化
- **日志文件**：`.goals/<goal_id>.log`
- **日志内容**：每轮 LLM 调用（时间戳、模型、token 用量）、每个工具执行（名称、参数、结果摘要）、暂停/恢复事件、权限审批事件
- **日志格式**：
  ```
  [2026-09-03T10:00:01] GOAL_START  goal_id=abc123  description="修复login bug"
  [2026-09-03T10:00:02] LLM_CALL    model=qwen3.7-plus  tokens=1200  round=1
  [2026-09-03T10:00:05] TOOL_EXEC   name=bash  args={"command":"cat file.py"}  result="(truncated)"
  [2026-09-03T10:00:10] PERMISSION  tool=bash  command="rm -rf /tmp/test"  action=AWAITING
  [2026-09-03T10:00:15] GOAL_PAUSE  reason=permission  goal_id=abc123
  ```
- **保留策略**：goal 完成后日志文件保留，可通过 `/goal cleanup` 手动清理或定期清理

### 9.8 Goal 模式下的 System Prompt 适配 ✅

- **决策**：动态追加 goal 指示
- **注入方式**：goal 启动时，在现有 system prompt 末尾追加一行 goal 描述，格式：
  ```
  [GOAL MODE] Current goal: <用户输入的目标描述>
  ```
- **移除时机**：goal 完成/终止/暂停时移除该指示行
- **注入位置**：不修改原始 system prompt 内容，通过 dynamic_system_prefix 机制在每次 LLM 调用时动态附加

---

## 10. 数据模型

### 10.1 Goal 数据类

```python
@dataclass
class Goal:
    id: str                              # UUID
    session_id: str                      # 所属 session
    description: str                     # 用户描述的目标（goal 启动时完整输入）
    state: str                           # GOAL_RUNNING / PAUSED / GOAL_AWAITING_PERMISSION / COMPLETED / TERMINATED
    context: dict                        # Goal Context（messages、todo、task_state 等）
    round_count: int                     # 已执行轮数
    max_rounds: int                      # 最大轮数上限
    start_time: str                      # ISO 格式
    last_resume_time: str | None         # 最近恢复时间
    paused_at: str | None                # 暂停时间
    completed_at: str | None             # 完成时间
    pause_reason: str | None             # 暂停原因（permission / user / error / step_limit）
    pending_permission: dict | None      # 待审批的权限请求（含 tool_name、tool_input、reason、options）
    summary: str | None                  # 完成后的模型生成摘要
    log_path: str | None                 # 执行日志文件路径
```

### 10.2 持久化路径

```
.project_root/
├── .sessions/
│   └── <session_id>.json          # 现有：session 状态
├── .goals/
│   └── <goal_id>.json             # 新增：goal 完整状态（含 context）
│   └── <goal_id>.log              # 新增：goal 执行日志
└── .memory/
    ├── MEMORY.md                  # 现有：session 级 memory
    └── goal_<goal_id>.md          # 新增：goal 级 memory
```

---

## 11. CLI 命令规范

### 11.1 新增命令

| 命令 | 说明 | 示例 |
|------|------|------|
| `/goal <描述>` | 启动新 goal | `/goal 修复 login 页面的验证 bug` |
| `/goal <N> <描述>` | 启动 goal 并指定最大轮数 | `/goal 50 重构用户模块` |
| `/pause` | 暂停当前 goal | `/pause` |
| `/continue` | 恢复当前暂停的 goal | `/continue` |
| `/status` | 查看当前 goal 状态 | `/status` |
| `/goal list` | 列出当前 session 的所有 goal | `/goal list` |
| `/goal show <id>` | 查看指定 goal 的详细信息 | `/goal show abc123` |
| `/goal cancel <id>` | 取消指定 goal | `/goal cancel abc123` |

### 11.2 现有命令的兼容

| 现有命令 | 在 goal 模式下的行为 |
|----------|---------------------|
| `/new` | 暂停当前 goal，创建新 session |
| `/sessions` | 列出所有 session（含 goal 状态信息） |
| `/resume` | 切换到目标 session，暂停当前 session 的 goal |
| `/rename` | 重命名当前 session（不影响其中的 goal） |
| `/branch` | 创建分支 session，暂停当前 session 的 goal |
| `q` / `exit` | 暂停当前 goal 后退出（goal 状态保持 PAUSED） |

---

## 12. 实施优先级建议

### Phase 1：核心功能
- Goal 状态机（5 状态）
- Goal Manager（创建、暂停、恢复、完成）
- Goal Context 管理（独立上下文、持久化、加载）
- `/goal` 命令入口
- `/pause` / `/continue` 交互
- Goal 专用 Hooks

### Phase 2：权限与错误
- permission_hook 改造（返回信号而非阻塞）
- 权限审批触发的 goal 暂停
- 错误分类处理（工具错误 vs LLM 错误）
- 并发 tool_use 的整轮取消逻辑

### Phase 3：集成与完善
- Goal 完成后 context 沉淀到 Session
- Goal 级 memory（`.memory/goal_<id>.md`）
- Goal 执行日志
- Goal 列表与详情查询
- 与后台任务、cron 的协调

### Phase 4：增强功能（可选）
- 多 goal 并发支持（当前单 goal 并发，后续可扩展队列）
- Goal 与 worktree 的结合
- Goal 模板（预设常用 goal 类型）

---

## 13. 关键设计决策总结

| 决策点 | 选择 | 理由 |
|--------|------|------|
| 停止条件 | 模型判断 + 全局步数上限兜底 | 兼顾灵活性和安全性 |
| 用户输入注入 | 追加到 goal context 的 messages | 简单、与现有结构兼容 |
| 权限暂停粒度 | **Goal 级**——任一工具需审批则暂停整个 goal | 统一控制点，用户体验一致 |
| 暂停持久化 | 完整状态序列化到磁盘 | 支持跨会话恢复 |
| Goal 完成后行为 | 输出总结，沉淀摘要到 session context，返回 CLI | 符合 Codex 体验 |
| 新增 Hooks | 是，5 个 goal 专用 hook | 保持扩展性 |
| 进入方式 | `/goal` CLI 命令 | 不破坏现有模式 |
| 并发 tool_use | 整轮取消，恢复后重算 | 简化一致性 |
| 后台任务/Cron | 不停止，恢复后重新注入通知 | 避免中断耗时操作 |
| 上下文压缩 | 复用现有逻辑 | 最小改动 |
| 记忆系统 | goal 独立 context，完成后沉淀 | 隔离 + 传承 |
| 子智能体 | 独立于 goal 暂停 | 职责分离 |
| MCP 权限 | 走现有 permission_hook | 统一管理 |
| 步数上限 | 全局固定值，不设时间上限 | 简单可控 |
| 错误处理 | 工具错误给模型自解，LLM 错误暂停 | 分层处理 |
| 状态机 | 5 状态（含 GOAL_AWAITING_PERMISSION） | 平衡简洁与表达能力 |
| Session 关系 | goal 在 session 内，切换时暂停/恢复 | 与现有 session 管理兼容 |
| **沉淀内容** | **模型生成摘要 + 原始用户输入** | 保留完整上下文 |
| **权限交互** | **结构化展示 + 多选项（allow/deny/edit）** | 灵活且安全 |
| **轮数定义** | **1 轮 = LLM 调用 + 所有 tool_use 执行完毕** | 语义清晰 |
| **多 Goal 并发** | **单 goal 并发，支持暂停队列** | 避免上下文冲突 |
| **上下文隔离** | **goal context 完全独立，RUNNING 时无法绕过** | 保证执行连贯性 |
| **Branch 归属** | **goal 归属创建 session，不迁移** | 符合直觉 |
| **执行日志** | **完整日志 + 时间戳结构化，文件独立持久化** | 便于审计调试 |
| **System Prompt** | **动态追加 `[GOAL MODE]` 指示，不修改原始 prompt** | 最小侵入 |
