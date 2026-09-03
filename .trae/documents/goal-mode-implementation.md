# Goal Mode 实现计划

## 概述

在 `s20_comprehensive/code.py`（约 3758 行）基础上新增 Goal Mode 功能，不修改其他章节代码。所有改动集中在一处：`s20_comprehensive/code.py`。

---

## 任务列表

### Phase 1：核心骨架（Goal 状态机 + GoalManager + Goal Context）

#### T1.1 新增 Goal 相关常量
**位置**: `code.py` L40 附近（全局配置区）
**内容**:
- `MAX_GOAL_ROUNDS = 100` — 全局最大轮数配置
- `GOAL_COMPACT_EVERY = 10` — 每 N 轮触发 goal context 压缩
- `GOALS_DIR = WORKDIR / ".goals"` — goal 持久化目录
- `GOAL_STATE_RUNNING = "GOAL_RUNNING"`
- `GOAL_STATE_PAUSED = "GOAL_PAUSED"`
- `GOAL_STATE_AWAITING_PERMISSION = "GOAL_AWAITING_PERMISSION"`
- `GOAL_STATE_COMPLETED = "GOAL_COMPLETED"`
- `GOAL_STATE_TERMINATED = "GOAL_TERMINATED"`

#### T1.2 新增 Goal 数据类
**位置**: `code.py` L97 附近（Task dataclass 之后）
**内容**:
```python
@dataclass
class Goal:
    id: str                              # UUID
    session_id: str                      # 所属 session
    description: str                     # 用户描述的目标（启动时完整输入）
    state: str                           # 状态常量
    context: dict                        # Goal Context（messages、todo、task_state 等）
    round_count: int                     # 已执行轮数
    max_rounds: int                      # 最大轮数上限
    start_time: str                      # ISO 格式
    last_resume_time: str | None         # 最近恢复时间
    paused_at: str | None                # 暂停时间
    completed_at: str | None             # 完成时间
    pause_reason: str | None             # 暂停原因
    pending_permission: dict | None      # 待审批的权限请求
    summary: str | None                  # 完成后的模型生成摘要
    log_path: str | None                 # 执行日志文件路径
    original_messages_snapshot: list     # 启动时保存的 messages 快照（用于创建 goal context）
```

#### T1.3 新增 GoalLogger 类
**位置**: `code.py` L1690 附近（FileTracker 之后）
**内容**:
- `GoalLogger(goal_id, log_path)` — 初始化日志文件
- `log(event_type, **fields)` — 写入结构化日志行，格式：`[timestamp] EVENT_TYPE key=value ...`
- `close()` — 关闭文件句柄

#### T1.4 新增 GoalManager 类
**位置**: `code.py` L3170 附近（SessionManager 之前）
**内容**:
- `__init__(sm: SessionManager)` — 接收 SessionManager 引用
- `create_goal(description: str, max_rounds: int) -> Goal` — 创建新 goal
  - 从 `sm.history` 浅拷贝 messages 作为 goal context 初始值
  - 保存 `original_messages_snapshot`（启动时的用户输入）
  - 初始化 GoalLogger
  - 触发 `GoalStart` hook
  - 返回 Goal 对象
- `pause_goal(goal: Goal, reason: str, pending_perm: dict = None) -> None` — 暂停 goal
  - 序列化到 `.goals/<goal_id>.json`
  - 写日志记录暂停事件
  - 触发 `GoalPause` hook
- `resume_goal(goal_id: str) -> Goal | None` — 从磁盘加载并恢复 goal
  - 反序列化 goal 状态
  - 将 goal context 的 messages 恢复到 `sm.history`
  - 触发 `GoalResume` hook
  - 返回恢复后的 Goal
- `complete_goal(goal: Goal, success: bool, summary: str) -> None` — 完成 goal
  - 写入 summary 字段
  - 持久化 goal 状态
  - 写日志记录完成事件
  - 触发 `GoalComplete` hook
- `terminate_goal(goal: Goal, reason: str) -> None` — 终止 goal
  - 触发 `GoalTerminate` hook
  - 持久化 goal 状态
- `list_goals(session_id: str) -> list[Goal]` — 列出 session 下所有 goal
- `get_goal(goal_id: str) -> Goal | None` — 查询单个 goal
- `get_active_goal(session_id: str) -> Goal | None` — 获取当前 session 正在运行的 goal
- `_save_goal(goal: Goal)` / `_load_goal(goal_id: str) -> Goal` — 序列化/反序列化
- `_goal_log_path(goal_id) -> Path` — 计算日志路径

#### T1.5 新增 Goal 生命周期 Hooks 注册
**位置**: `code.py` L1700（HOOKS 字典定义）
**内容**:
- 在 `HOOKS` 字典中新增 `"GoalStart"`, `"GoalPause"`, `"GoalResume"`, `"GoalComplete"`, `"GoalTerminate"` 五个事件
- 在 `register_hook` 调用区（L1821-1825）注册默认 hook 实现：
  - `goal_start_hook(goal_id, description)` → 写日志
  - `goal_pause_hook(goal_id, reason)` → 无额外操作（由 GoalManager 处理持久化）
  - `goal_resume_hook(goal_id, source)` → 无额外操作
  - `goal_complete_hook(goal_id, success, summary)` → 无额外操作
  - `goal_terminate_hook(goal_id, reason)` → 无额外操作

---

### Phase 2：Agent Loop 改造（Goal 模式入口 + 暂停/恢复）

#### T2.1 改造 agent_loop 支持 goal_context 参数
**位置**: `code.py` L3288（agent_loop 函数定义）
**内容**:
- 新增参数 `goal: Goal = None`
- goal 为 None 时行为完全不变（普通对话模式）
- goal 不为 None 时：
  - 使用 `goal.context["messages"]` 作为 messages（而不是 sm.history）
  - 轮数计数器 `round_count` 从 goal 对象读取和递增
  - 每轮结束后检查 `round_count >= goal.max_rounds`，触发步骤限制
  - 每 `GOAL_COMPACT_EVERY` 轮对 goal context 执行压缩
  - tool_use block 结果追加到 goal.context["messages"]（不追加到 sm.history）
  - 当 `stop_reason != "tool_use"` 时：
    - 输出工具调用的文本结果
    - 触发 `GoalComplete` hook（成功完成）
    - 返回（不追加到 sm.history）
- 新增 `dynamic_goal_system_prefix`：goal 启动时在 system prompt 前追加 `[GOAL MODE] Current goal: <description>`

#### T2.2 在 agent_loop 中集成 goal 轮数检查
**位置**: `code.py` L3362 附近（max_tokens 重置处）
**内容**:
- 每轮 LLM 调用后，如果 goal 不为 None：`goal.round_count += 1`
- 检查 `goal.round_count >= goal.max_rounds`：
  - 若达到上限，将 `{"type": "text", "text": "[Goal 完成] 达到最大轮数上限，goal 自动终止。"}` 追加到 messages
  - 触发 `GoalComplete` hook（success=False）
  - return

#### T2.3 goal 完成后沉淀到 Session Context
**位置**: `code.py` T2.1 中 goal 完成分支
**内容**:
- 在 `GoalComplete` hook 触发前，调用 `generate_goal_summary(goal)`：
  - 构造 prompt：将 goal.original_messages_snapshot + goal.context["messages"] 中关键内容作为上下文
  - 调用 LLM 生成摘要
  - 返回结构化文本
- 将摘要以 structured message 追加到 `sm.history`：
  ```python
  sm.history.append({
      "role": "system",
      "content": f"[GOAL COMPLETE] {summary_text}"
  })
  ```
- 同时追加到 `MEMORY_DIR / "MEMORY.md"`（调用 memory 追加逻辑）

#### T2.4 CLI 层接入 goal 模式
**位置**: `code.py` L3675（main while True 循环）
**内容**:
- 在 CLI 输入处理后（`handle_cli_command` 之后），检测是否有活跃 goal：
  ```python
  active_goal = goal_manager.get_active_goal(sm.session_id)
  if active_goal:
      # goal 模式：所有输入进入 goal context
      # 不触发 handle_cli_command（除了 /continue /status /pause 等 goal 命令）
      ...
  else:
      # 普通模式：原有逻辑
      ...
  ```
- goal 运行中时，`/pause`、`/status`、`/continue` 不被 `handle_cli_command` 处理，而是在 goal 检测分支中直接处理

---

### Phase 3：权限改造（Permission Hook → Goal 级暂停）

#### T3.1 改造 permission_hook 返回信号而非阻塞
**位置**: `code.py` L1729-1789（permission_hook 函数）
**内容**:
- **破坏性 bash 命令**：将 `input("Allow? [y/N]")` 替换为返回特殊信号：
  ```python
  return {
      "type": "AWAITING_PERMISSION",
      "tool_name": "bash",
      "tool_input": {"command": command},
      "reason": "Potentially destructive command",
  }
  ```
- **MCP 危险工具**：同上，返回 AWAITING_PERMISSION 信号
- **硬拒绝（deny list）**：保持原有行为（返回字符串被 blocked 处理）
- **路径安全校验**：保持原有行为
- 新增 `show_permission_dialog(goal_id, perm_request) -> str` 函数：
  - 格式化展示权限审批界面（按 spec 9.2 的格式）
  - 等待用户输入 1/2/3
  - 返回 `"allow"` / `"deny"` / `"edit:<new_command>"`
- 新增 `apply_permission_choice(choice, perm_request) -> tuple[str | None, str | None]`:
  - `"allow"` → `(None, None)` 表示允许，继续执行
  - `"deny"` → `("Permission denied by user", None)` 表示拒绝
  - `"edit:<cmd>"` → `(None, {"command": cmd})` 表示用新命令继续

#### T3.2 在 agent_loop 中处理 permission 信号
**位置**: `code.py` L3387（PreToolUse hook 触发处）
**内容**:
- 现有逻辑：
  ```python
  blocked = trigger_hooks("PreToolUse", block)
  if blocked:
      results.append({"type": "tool_result", ...})
      continue
  ```
- 改造后：
  ```python
  hook_result = trigger_hooks("PreToolUse", block)
  if hook_result is not None:
      if isinstance(hook_result, dict) and hook_result.get("type") == "AWAITING_PERMISSION":
          # 权限审批信号：暂停 goal
          if goal:
              goal_manager.pause_goal(goal, "permission", pending_permission=hook_result)
              # 展示审批界面，等待用户选择
              choice = show_permission_dialog(goal.id, hook_result)
              apply_result, new_input = apply_permission_choice(choice, hook_result)
              if apply_result:
                  # 拒绝：记录 tool_result 并 continue
                  results.append({"type": "tool_result", ...})
                  continue
              else:
                  # 批准或编辑：用 new_input 或原 input 执行工具
                  # 恢复 goal 后重新调用 LLM
                  goal_manager.resume_goal(goal.id)
                  # 注意：这里需要把当前的 tool_use block 标记为已处理
                  # 策略：将其结果记为 blocked，下一轮 LLM 重新决策
                  results.append({"type": "tool_result", "tool_use_id": block.id,
                                   "content": "Permission was pending, please re-issue this action."})
                  break  # 整轮取消，让模型重新决策
      else:
          # 原有硬拒绝逻辑
          results.append({"type": "tool_result", ...})
          continue
  ```

#### T3.3 LLM 调用错误处理 → goal 暂停
**位置**: `code.py` L3334-3343（异常处理分支）
**内容**:
- 在现有的 `except Exception as e` 分支中，区分错误类型：
  - 工具执行错误（不在 LLM 调用层捕获，已由工具 handler 返回）
  - LLM API 错误：若 goal 不为 None，触发 `goal_manager.pause_goal(goal, "error", pending_error=str(e))`，然后 return
  - `AllModelsExhaustedError`：原有行为不变（打印红色提示，return）

---

### Phase 4：集成与完善

#### T4.1 Goal Manager 与 SessionManager 集成
**位置**: `code.py` L3184（SessionManager 类）+ T1.4（GoalManager）
**内容**:
- SessionManager 新增 `goal_manager: GoalManager | None` 属性
- `SessionManager.start_new()` 和 `SessionManager.switch_to()` 时：
  - 调用 `goal_manager.pause_all_running_goals(sm.session_id)` 暂停当前 session 的所有 running goal
  - 加载目标 session 下的 goal（如有），自动恢复
- Session 索引中新增 `goal_ids: list[str]` 字段，记录该 session 下的 goal ID

#### T4.2 Goal 列表与详情 CLI 命令
**位置**: `code.py` L3488（handle_cli_command）
**内容**:
- 新增命令处理：
  - `/goal <description>` — 启动 goal
  - `/goal <N> <description>` — 启动 goal 指定轮数
  - `/goal list` — 列出当前 session 所有 goal
  - `/goal show <id>` — 显示 goal 详情
  - `/goal cancel <id>` — 取消 goal
  - `/pause` — 暂停当前 goal
  - `/continue` — 恢复当前 goal
  - `/status` — 查看当前 goal 状态
- 这些命令在 main loop 的 goal 检测分支中直接处理（不进入 handle_cli_command）

#### T4.3 Goal 级 Memory
**位置**: `code.py` T2.3（goal 完成沉淀逻辑中）
**内容**:
- goal 执行期间，memory 读写指向 `.memory/goal_<goal_id>.md`
- goal 完成后，将关键信息追加到 `.memory/MEMORY.md`
- 复用现有的 memory 写入逻辑，仅修改目标路径

#### T4.4 Goal 执行日志写入 agent_loop
**位置**: `code.py` L3288（agent_loop 函数内）
**内容**:
- LLM 调用前：`goal_logger.log("LLM_CALL", model=MODEL, round=goal.round_count)`
- 每个工具执行后：`goal_logger.log("TOOL_EXEC", name=block.name, args=block.input)`
- 暂停时：`goal_logger.log("GOAL_PAUSE", reason=reason)`
- 恢复时：`goal_logger.log("GOAL_RESUME")`
- 完成时：`goal_logger.log("GOAL_COMPLETE", success=success)`

---

## 关键修改点汇总

| 修改点 | 文件 | 行号范围 | 改动类型 |
|--------|------|----------|----------|
| 新增常量 | code.py | ~L40 | 新增 |
| 新增 Goal 数据类 | code.py | ~L97 | 新增 |
| 新增 GoalLogger 类 | code.py | ~L1690 | 新增 |
| 新增 GoalManager 类 | code.py | ~L3170 | 新增 |
| HOOKS 字典扩展 | code.py | L1700 | 修改 |
| permission_hook 改造 | code.py | L1729-1789 | 修改 |
| register_hook 调用 | code.py | L1821-1825 | 修改 |
| SessionManager 扩展 | code.py | L3184 | 修改 |
| agent_loop 改造 | code.py | L3288 | 修改（核心） |
| CLI 命令处理 | code.py | L3488-L3675 | 修改 |
| main loop 改造 | code.py | L3675+ | 修改 |

---

## 不变的部分

- `s01~s19` 各章节代码：完全不修改
- `client`、`MODEL`、`SYSTEM` 等全局变量：不修改
- `assemble_tool_pool()`、`call_llm()`、`prepare_context()` 等工具函数：不修改签名，只修改调用方传入的 messages 来源
- 后台任务、cron、subagent、MCP 等机制：行为不变，仅通过 goal 暂停/恢复机制间接影响

---

## 验证步骤

### V1. 基本功能验证
1. 启动 s20，输入 `/goal 创建一个 hello.py 文件并打印 Hello World`
2. 验证 goal 启动后 agent 自主执行工具调用
3. 验证 goal 完成后输出总结并返回 CLI
4. 验证 session context 中出现了 goal 沉淀信息

### V2. 暂停/恢复验证
1. 启动 goal，执行过程中输入 `/pause`
2. 验证 goal 状态变为 PAUSED，磁盘写入 `.goals/<id>.json`
3. 验证输入 `/continue` 后 goal 继续执行
4. 验证输入追加文本后 goal 能看到新输入并调整行为

### V3. 权限暂停验证
1. 启动 goal，触发破坏性命令（如 `rm /tmp/test`）
2. 验证 goal 暂停，显示结构化权限审批界面
3. 选择 1 (allow) → goal 继续，工具被执行
4. 选择 2 (deny) → goal 终止
5. 选择 3 (edit) → 进入编辑模式，输入新命令后批准执行

### V4. 错误处理验证
1. 启动 goal，模拟 LLM 调用失败（断网或换无效 API key）
2. 验证 goal 暂停，错误信息写入 pending_error
3. 验证 `/continue` 后 goal 可以恢复

### V5. 轮数上限验证
1. 设置 `MAX_GOAL_ROUNDS=3`，启动 goal
2. 验证执行到第 3 轮后 goal 自动终止，输出超时报错

### V6. 跨会话恢复验证
1. 启动 goal，执行几轮后 `/pause`
2. 退出程序
3. 重新启动，`/resume` 到之前的 session
4. 验证 goal 状态恢复，可以 `/continue`

### V7. 回归测试
1. 不启动 goal，验证原有普通对话模式行为完全不变
2. 验证 `/new`、`/sessions`、`/branch` 等命令在 goal 模式下的正确行为
3. 验证 cron 和后台任务在 goal 暂停时仍正常运行
