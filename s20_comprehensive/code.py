#!/usr/bin/env python3
"""
s20: Comprehensive Agent — all teaching components in one loop.

Run:  python s20_comprehensive/code.py
Need: pip install anthropic python-dotenv pyyaml + .env with ANTHROPIC_API_KEY

This final chapter intentionally puts the earlier teaching mechanisms back
together: dispatch, permission, hooks, todo, subagent, skills, compaction,
memory, prompt assembly, error recovery, task graph, background tasks, cron,
teams, protocols, autonomous agents, worktrees, and MCP.
"""

import ast, json, os, subprocess, time, random, threading, re, uuid, shutil
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass, asdict, field
import yaml

try:
    import readline
    readline.parse_and_bind('set bind-tty-special-chars off')
    READLINE_AVAILABLE = True
except ImportError:
    READLINE_AVAILABLE = False

from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv(override=True)
if os.getenv("ANTHROPIC_BASE_URL"):
    os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)

WORKDIR = Path.cwd()
client = Anthropic(base_url=os.getenv("ANTHROPIC_BASE_URL"))
MODEL = os.environ["MODEL_ID"]
PRIMARY_MODEL = MODEL
FALLBACK_MODEL = os.getenv("FALLBACK_MODEL_ID")

# 模型池：从环境变量 MODEL_POOL 加载所有可用模型（逗号分隔）
# 用途：当某模型免费额度耗尽时自动切换到池中下一个模型
_MODEL_POOL_STR = os.getenv("MODEL_POOL", "")
MODEL_POOL = [m.strip() for m in _MODEL_POOL_STR.split(",") if m.strip()] or [MODEL]
# 启动时打印模型池信息，方便排查配置
print(f"[model-pool] 可用模型 {len(MODEL_POOL)} 个：{', '.join(MODEL_POOL)}")

SKILLS_DIR = WORKDIR / "skills"
TRANSCRIPT_DIR = WORKDIR / ".transcripts"
TOOL_RESULTS_DIR = WORKDIR / ".task_outputs" / "tool-results"
FILE_TRACKER_PATH = WORKDIR / ".file_tracker.json"
DORMANT_GRACE_SECONDS = 3600  # 临时文件休眠宽限期（秒）
PERSISTENT_DIRS = {"src", "lib", "components", "docs", "config", "tests", "static", "assets"}
TMP_NAME_PATTERNS = [".tmp.", "_temp.", "_debug.", ".bak."]

DEFAULT_MAX_TOKENS = 8000
ESCALATED_MAX_TOKENS = 16000
MAX_RETRIES = 3
MAX_CONSECUTIVE_529 = 2
MAX_RECOVERY_RETRIES = 2
BASE_DELAY_MS = 500
CONTEXT_LIMIT = 50000
KEEP_RECENT_TOOL_RESULTS = 3
PERSIST_THRESHOLD = 30000
CONTINUATION_PROMPT = "Continue from the previous response. Do not repeat completed work."
PROMPT = "\033[36ms20 >> \033[0m"
CLI_ACTIVE = False
_current_session_id: str = ""  # 当前 agent_loop 的会话 ID，供工具 handler 读取


def terminal_print(text: str):
    if threading.current_thread() is threading.main_thread() or not CLI_ACTIVE:
        print(text)
        return
    line = ""
    if READLINE_AVAILABLE:
        try:
            line = readline.get_line_buffer()
        except Exception:
            line = ""
    print(f"\r\033[K{text}")
    print(PROMPT + line, end="", flush=True)

# ── Task System ──

# Tasks are tiny durable records. Later systems add ownership, dependencies,
# worktrees, and teammates on top of this same file-backed state.
TASKS_DIR = WORKDIR / ".tasks"
TASKS_DIR.mkdir(exist_ok=True)
CURRENT_TODOS: list[dict] = []


@dataclass
class Task:
    id: str
    subject: str
    description: str
    status: str
    owner: str | None
    blockedBy: list[str]
    worktree: str | None = None


def _task_path(task_id: str) -> Path:
    return TASKS_DIR / f"{task_id}.json"


def create_task(subject: str, description: str = "",
                blockedBy: list[str] | None = None) -> Task:
    task = Task(
        id=f"task_{int(time.time())}_{random.randint(0, 9999):04d}",
        subject=subject, description=description,
        status="pending", owner=None,
        blockedBy=blockedBy or [],
    )
    save_task(task)
    return task


def save_task(task: Task):
    _task_path(task.id).write_text(json.dumps(asdict(task), indent=2))


def load_task(task_id: str) -> Task:
    return Task(**json.loads(_task_path(task_id).read_text()))


def list_tasks() -> list[Task]:
    return [Task(**json.loads(p.read_text()))
            for p in sorted(TASKS_DIR.glob("task_*.json"))]


def get_task_json(task_id: str) -> str:
    return json.dumps(asdict(load_task(task_id)), indent=2)


def can_start(task_id: str) -> bool:
    # Dependencies are intentionally simple: every blocker must exist and be
    # completed before the task can be claimed.
    task = load_task(task_id)
    for dep_id in task.blockedBy:
        if not _task_path(dep_id).exists():
            return False
        if load_task(dep_id).status != "completed":
            return False
    return True


def claim_task(task_id: str, owner: str = "agent") -> str:
    task = load_task(task_id)
    if task.status != "pending":
        return f"Task {task_id} is {task.status}, cannot claim"
    if task.owner:
        return f"Task {task_id} already owned by {task.owner}"
    if not can_start(task_id):
        deps = [d for d in task.blockedBy
                if _task_path(d).exists() and load_task(d).status != "completed"]
        missing = [d for d in task.blockedBy if not _task_path(d).exists()]
        parts = []
        if deps: parts.append(f"blocked by: {deps}")
        if missing: parts.append(f"missing deps: {missing}")
        return "Cannot start — " + ", ".join(parts)
    task.owner = owner
    task.status = "in_progress"
    save_task(task)
    print(f"  \033[36m[claim] {task.subject} → in_progress\033[0m")
    return f"Claimed {task.id} ({task.subject})"


def complete_task(task_id: str) -> str:
    task = load_task(task_id)
    if task.status != "in_progress":
        return f"Task {task_id} is {task.status}, cannot complete"
    task.status = "completed"
    save_task(task)
    unblocked = [t.subject for t in list_tasks()
                 if t.status == "pending" and t.blockedBy and can_start(t.id)]
    print(f"  \033[32m[complete] {task.subject} ✓\033[0m")
    msg = f"Completed {task.id} ({task.subject})"
    if unblocked:
        msg += f"\nUnblocked: {', '.join(unblocked)}"
    return msg


# ── Worktree System ──

# Worktree names become filesystem paths, so the teaching version keeps the
# validation rules strict and reuses them for create/remove/keep.
WORKTREES_DIR = WORKDIR / ".worktrees"
WORKTREES_DIR.mkdir(exist_ok=True)

VALID_WT_NAME = re.compile(r'^[A-Za-z0-9._-]{1,64}$')


def validate_worktree_name(name: str) -> str | None:
    if not name:
        return "Worktree name cannot be empty"
    if name in (".", ".."):
        return f"'{name}' is not a valid worktree name"
    if not VALID_WT_NAME.match(name):
        return (f"Invalid worktree name '{name}': "
                "only letters, digits, dots, underscores, dashes (1-64 chars)")
    return None


def run_git(args: list[str]) -> tuple[bool, str]:
    try:
        r = subprocess.run(["git"] + args, cwd=WORKDIR,
                           capture_output=True, text=True, timeout=30)
        out = (r.stdout + r.stderr).strip()
        return r.returncode == 0, out[:5000] if out else "(no output)"
    except subprocess.TimeoutExpired:
        return False, "Error: git timeout"


def log_event(event_type: str, worktree_name: str, task_id: str = ""):
    event = {"type": event_type, "worktree": worktree_name,
             "task_id": task_id, "ts": time.time()}
    events_file = WORKTREES_DIR / "events.jsonl"
    with open(events_file, "a") as f:
        f.write(json.dumps(event) + "\n")


def create_worktree(name: str, task_id: str = "") -> str:
    # Tool-layer validation is part of the safety boundary; do it before git
    # sees the name, not only after git happens to reject something.
    err = validate_worktree_name(name)
    if err:
        return f"Error: {err}"
    if task_id:
        try:
            load_task(task_id)
        except FileNotFoundError:
            return f"Error: task {task_id} not found"
    path = WORKTREES_DIR / name
    if path.exists():
        return f"Worktree '{name}' already exists at {path}"
    ok, result = run_git(["worktree", "add", str(path), "-b", f"wt/{name}", "HEAD"])
    if not ok:
        return f"Git error: {result}"
    if task_id:
        bind_task_to_worktree(task_id, name)
    log_event("create", name, task_id)
    print(f"  \033[33m[worktree] created: {name} at {path}\033[0m")
    return f"Worktree '{name}' created at {path}"


def bind_task_to_worktree(task_id: str, worktree_name: str):
    task = load_task(task_id)
    task.worktree = worktree_name
    save_task(task)


def _count_worktree_changes(path: Path) -> tuple[int, int]:
    try:
        r1 = subprocess.run(["git", "status", "--porcelain"],
                            cwd=path, capture_output=True, text=True, timeout=10)
        files = len([l for l in r1.stdout.strip().splitlines() if l.strip()])
        r2 = subprocess.run(["git", "log", "@{push}..HEAD", "--oneline"],
                            cwd=path, capture_output=True, text=True, timeout=10)
        commits = len([l for l in r2.stdout.strip().splitlines() if l.strip()])
        return files, commits
    except Exception:
        return -1, -1


def remove_worktree(name: str, discard_changes: bool = False) -> str:
    err = validate_worktree_name(name)
    if err:
        return err
    path = WORKTREES_DIR / name
    if not path.exists():
        return f"Worktree '{name}' not found"
    if not discard_changes:
        files, commits = _count_worktree_changes(path)
        if files < 0:
            return "Cannot verify status. Use discard_changes=true to force."
        if files > 0 or commits > 0:
            return (f"Worktree '{name}' has {files} file(s), {commits} commit(s). "
                    "Use discard_changes=true or keep_worktree.")
    ok1, _ = run_git(["worktree", "remove", str(path), "--force"])
    if not ok1:
        return f"Failed to remove worktree '{name}'"
    run_git(["branch", "-D", f"wt/{name}"])
    log_event("remove", name)
    print(f"  \033[33m[worktree] removed: {name}\033[0m")
    return f"Worktree '{name}' removed"


def keep_worktree(name: str) -> str:
    err = validate_worktree_name(name)
    if err:
        return err
    log_event("keep", name)
    return f"Worktree '{name}' kept for review (branch: wt/{name})"


# ── Skill Loading ──

SKILL_REGISTRY: dict[str, dict] = {}


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    try:
        meta = yaml.safe_load(parts[1]) or {}
    except yaml.YAMLError:
        meta = {}
    return meta, parts[2].strip()


def scan_skills():
    SKILL_REGISTRY.clear()
    if not SKILLS_DIR.exists():
        return
    for directory in sorted(SKILLS_DIR.iterdir()):
        if not directory.is_dir():
            continue
        manifest = directory / "SKILL.md"
        if not manifest.exists():
            continue
        raw = manifest.read_text()
        meta, _ = _parse_frontmatter(raw)
        name = meta.get("name", directory.name)
        desc = meta.get("description", raw.split("\n")[0].lstrip("#").strip())
        SKILL_REGISTRY[name] = {
            "name": name,
            "description": desc,
            "content": raw,
        }


scan_skills()


def list_skills() -> str:
    if not SKILL_REGISTRY:
        return "(no skills found)"
    return "\n".join(
        f"- {skill['name']}: {skill['description']}"
        for skill in SKILL_REGISTRY.values())


def load_skill(name: str) -> str:
    skill = SKILL_REGISTRY.get(name)
    if not skill:
        available = ", ".join(SKILL_REGISTRY.keys()) or "(none)"
        return f"Skill not found: {name}. Available: {available}"
    return skill["content"]


# ── Prompt Assembly ──

PROMPT_SECTIONS = {
    "identity": "You are a coding agent. Act, don't explain.",
    "tools": "Available tools (categorized):\n"
             "- File ops: read_file, write_file, edit_file, delete_file, glob, ls\n"
             "- Content search: grep (regex over file contents)\n"
             "- Diagnostics: diagnostics (py syntax check)\n"
             "- Web: web_search, web_fetch (use only when user asks to go online)\n"
             "- Shell: bash (system commands only — git/npm/docker/python)\n"
             "- Planning: todo_write, compact\n"
             "- Delegation: task (subagent), load_skill\n"
             "- Task graph: create_task, list_tasks, get_task, claim_task, complete_task\n"
             "- Cron: schedule_cron, list_crons, cancel_cron\n"
             "- Team: spawn_teammate, send_message, check_inbox, "
             "request_shutdown, request_plan, review_plan\n"
             "- Worktree: create_worktree, remove_worktree, keep_worktree\n"
             "- MCP: connect_mcp. MCP tools are prefixed mcp__{server}__{tool}.",
    "principles": (
        "Tool-use principles (MUST follow):\n"
        "1. DEDICATED TOOLS FIRST: never use bash for what dedicated tools do. "
        "Use read_file (not `cat`), write_file (not `echo>`), edit_file (not `sed`), "
        "glob (not `find`), grep (not `grep`/`rg`), ls (not `ls`), delete_file (not `rm`).\n"
        "2. BASH IS LAST RESORT: bash is only for git/npm/docker/python/make/pip "
        "and other true shell commands. Never bash for file read/write/edit/search.\n"
        "3. PATH SAFETY: file tools reject paths escaping the workspace. "
        "Always pass relative paths, never absolute paths from outside.\n"
        "4. READ BEFORE OVERWRITE: before write_file overwrites an existing file, "
        "call read_file first to confirm current contents. Never blindly overwrite.\n"
        "5. EDIT UNIQUENESS: edit_file requires old_text to be unique in the file. "
        "If not unique, include more surrounding lines to disambiguate. "
        "Do not chain multiple edits on the same line.\n"
        "6. DELETE WITH CARE: delete_file refuses missing paths and directories. "
        "Confirm with the user before deleting files you did not create in this session.\n"
        "7. GREP OVER BASH: for content search use grep tool (with glob filter), "
        "never `bash grep` or `bash rg`.\n"
        "8. DIAGNOSTICS AFTER EDIT: after editing .py files, if unsure of syntax, "
        "call diagnostics to verify before declaring done.\n"
        "9. WEB TOOLS ARE OPT-IN: web_search/web_fetch only when the user explicitly "
        "asks to go online. Default is offline. Always cite sources after web_search.\n"
        "10. PARALLEL CALLS: independent tool calls in the same turn should be batched "
        "in one message (up to 5). Sequential only when one call's result feeds the next."
    ),
    "workspace": f"Working directory: {WORKDIR}",
    "memory": "Relevant memories are injected below when available.",
    "temp_file_policy": (
        "临时文件管理规范（MUST follow）：\n"
        "1. 临时文件定义：为验证思路、中间调试、一次性脚本、实验性代码而创建的文件，"
        "任务完成后无需保留。\n"
        "2. 标记规则：\n"
        "   - 临时文件：路径含 .tmp. 前缀或后缀，或文件名以 _temp.py / _debug.py 结尾，"
        "   或在 write_file 调用时显式设置 purpose='temporary'\n"
        "   - 持久文件：项目源码、配置文件、README 等需要长期保留的文件，"
        "   设置 purpose='persistent'\n"
        "3. 托管义务：每次创建临时文件后，harness 会自动注册到文件追踪表，"
        "   无需手动调用 file_tracker 工具（除非需要主动查询追踪状态）\n"
        "4. 清理时机：子任务完成后调用 cleanup_temp() 清理当前会话创建的临时文件；\n"
        "5. 禁止行为：不得将临时文件作为最终产物输出给用户的代码，除非明确标记为 persistent。\n"
        "6. 文件追踪工具：file_tracker（查询）、cleanup_temp（清理）、mark_persistent（升级）"
    ),
    "file_tracking_note": (
        "文件追踪规范：\n"
        "- write_file / edit_file 创建或修改文件后，自动由 harness 注册到文件追踪表\n"
        "- bash 中通过重定向创建的临时文件，会在 PostToolUse 中自动扫描并注册\n"
        "- 可在工具调用时通过 purpose 参数声明文件性质，harness 据此决定生命周期策略\n"
        "- 临时文件在会话切换时进入休眠（计时暂停），宽限期（1小时活跃时长）到期后自动清理\n"
        "- 清理前会写入 .filename.tracker 占位标记文件，保留完整溯源信息"
    ),
}


def assemble_system_prompt(context: dict) -> str:
    # The system prompt is rebuilt each turn from live context. This is where
    # memory, skill catalog, MCP state, and active teammates become visible.
    sections = [PROMPT_SECTIONS["identity"],
                PROMPT_SECTIONS["tools"],
                PROMPT_SECTIONS["principles"],
                PROMPT_SECTIONS["workspace"],
                PROMPT_SECTIONS["temp_file_policy"],
                PROMPT_SECTIONS["file_tracking_note"]]
    sections.append(f"Current time: {datetime.now().isoformat(timespec='seconds')}")
    sections.append("Skills catalog:\n" + list_skills() +
                    "\nUse load_skill(name) when a skill is relevant.")
    if context.get("memories"):
        sections.append(f"Relevant memories:\n{context['memories']}")
    mcp_names = list(mcp_clients.keys())
    if mcp_names:
        sections.append(f"Connected MCP servers: {', '.join(mcp_names)}")
    return "\n\n".join(sections)


# ── Basic Tools ──

def safe_path(p: str, cwd: Path = None) -> Path:
    # File tools stay inside the workspace or teammate worktree. Bash remains
    # powerful on purpose and is controlled by the permission hook instead.
    base = cwd or WORKDIR
    path = (base / p).resolve()
    if not path.is_relative_to(base):
        raise ValueError(f"Path escapes workspace: {p}")
    return path


def run_bash(command: str, cwd: Path = None,
             run_in_background: bool = False) -> str:
    # run_in_background is consumed by the dispatcher; direct execution ignores it.
    # 执行前后扫描文件集合，将新增文件自动注册到文件追踪器
    try:
        before_paths = _scan_workspace_files()
        r = subprocess.run(command, shell=True, cwd=cwd or WORKDIR,
                           capture_output=True, text=True, timeout=120)
        out = (r.stdout + r.stderr).strip()
        after_paths = _scan_workspace_files()
        new_files = after_paths - before_paths
        for fp in new_files:
            _FILE_TRACKER.track(path=fp, is_new=True, tool="bash",
                                session_id=_current_session_id)
        return out[:50000] if out else "(no output)"
    except subprocess.TimeoutExpired:
        return "Error: Timeout (120s)"


def run_read(path: str, limit: int | None = None,
             offset: int = 0, cwd: Path = None) -> str:
    # 检查是否为 ghost / deleted 文件（物理丢失但追踪表有记录），返回溯源提示
    entry = _FILE_TRACKER.get_entry(path)
    if entry and entry.get("status") in ("ghost", "deleted"):
        reason = entry.get("ghost_reason", "file_not_found")
        session = entry.get("session_id", "unknown")[:8]
        created = datetime.fromtimestamp(entry.get("created_at", 0)).isoformat()
        purpose = entry.get("purpose", "unknown")
        tool = entry.get("tool", "unknown")
        return (f"[TRACKED FILE - {entry.get('status','?').upper()}] {path} is no longer available.\n"
                f"  Reason: {reason}\n"
                f"  Created: {created}  Purpose: {purpose}  Tool: {tool}\n"
                f"  Session: {session}\n"
                f"  See .file_tracker.json for full record.")
    try:
        lines = safe_path(path, cwd).read_text().splitlines()
        offset = max(int(offset or 0), 0)
        limit = int(limit) if limit is not None else None
        lines = lines[offset:]
        if limit is not None and limit < len(lines):
            lines = lines[:limit] + [f"... ({len(lines) - limit} more lines)"]
        return "\n".join(lines)
    except Exception as e:
        return f"Error: {e}"


def run_write(path: str, content: str, cwd: Path = None,
              purpose: str = None) -> str:
    # 写入文件后自动注册到文件追踪器，purpose 参数用于显式标注文件性质
    try:
        fp = safe_path(path, cwd)
        is_new = not fp.exists()
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(content)
        # 自动追踪新创建的文件
        _FILE_TRACKER.track(path=path, is_new=is_new, tool="write_file",
                            purpose=purpose, session_id=_current_session_id,
                            content_preview=content[:200])
        return f"Wrote {len(content)} bytes to {path}"
    except Exception as e:
        return f"Error: {e}"


def run_edit(path: str, old_text: str, new_text: str,
             cwd: Path = None) -> str:
    # 编辑文件后更新追踪记录（is_new=False，保持原有 is_temporary 属性）
    try:
        fp = safe_path(path, cwd)
        text = fp.read_text()
        if old_text not in text:
            return f"Error: text not found in {path}"
        fp.write_text(text.replace(old_text, new_text, 1))
        _FILE_TRACKER.track(path=path, is_new=False, tool="edit_file",
                            session_id=_current_session_id,
                            content_preview=new_text[:200])
        return f"Edited {path}"
    except Exception as e:
        return f"Error: {e}"


def run_glob(pattern: str, cwd: Path = None) -> str:
    import glob as g
    try:
        base = cwd or WORKDIR
        results = []
        for match in g.glob(pattern, root_dir=base):
            if (base / match).resolve().is_relative_to(base):
                results.append(match)
        return "\n".join(results) if results else "(no matches)"
    except Exception as e:
        return f"Error: {e}"


def run_grep(pattern: str, path: str = ".", glob: str = "*",
             case_insensitive: bool = False, cwd: Path = None,
             max_matches: int = 100, context_lines: int = 0) -> str:
    """在文件内容中搜索正则表达式（对标 Trae Grep 工具）。

    Args:
        pattern: 正则表达式（re.search 语法）
        path: 相对路径（文件或目录），默认当前目录
        glob: 文件名 glob 过滤，默认 "*"（所有文件）
        case_insensitive: 是否大小写不敏感
        max_matches: 最多返回匹配数（防止输出爆炸）
        context_lines: 匹配行前后各显示的上下文行数

    Returns:
        匹配结果字符串，格式为 "file:line: content"
    """
    import fnmatch
    try:
        base = cwd or WORKDIR
        target = (base / path).resolve()
        if not target.is_relative_to(base):
            return f"Error: Path escapes workspace: {path}"
        flags = re.IGNORECASE if case_insensitive else 0
        regex = re.compile(pattern, flags)
        results = []
        files_to_search = []
        if target.is_file():
            files_to_search = [target]
        else:
            for fp in target.rglob(glob):
                if fp.is_file() and fp.resolve().is_relative_to(base):
                    # 跳过常见二进制/大文件目录
                    if any(part in {".venv", ".git", "node_modules", "__pycache__"}
                           for part in fp.parts):
                        continue
                    files_to_search.append(fp)
        for fp in files_to_search:
            try:
                lines = fp.read_text(encoding="utf-8", errors="ignore").splitlines()
            except Exception:
                continue
            for i, line in enumerate(lines):
                if regex.search(line):
                    rel = fp.relative_to(base).as_posix()
                    if context_lines > 0:
                        start = max(0, i - context_lines)
                        end = min(len(lines), i + context_lines + 1)
                        for j in range(start, end):
                            marker = ">" if j == i else " "
                            results.append(f"{rel}:{j+1}:{marker} {lines[j]}")
                        results.append("---")
                    else:
                        results.append(f"{rel}:{i+1}: {line}")
                    if len(results) >= max_matches:
                        results.append(f"... (truncated at {max_matches} matches)")
                        return "\n".join(results)
        return "\n".join(results) if results else "(no matches)"
    except re.error as e:
        return f"Error: invalid regex: {e}"
    except Exception as e:
        return f"Error: {e}"


def run_ls(path: str = ".", cwd: Path = None) -> str:
    """列出目录内容（对标 Trae LS 工具），强制路径安全校验。"""
    try:
        base = cwd or WORKDIR
        target = (base / path).resolve()
        if not target.is_relative_to(base):
            return f"Error: Path escapes workspace: {path}"
        if not target.exists():
            return f"Error: not found: {path}"
        if not target.is_dir():
            return f"Error: not a directory: {path}"
        entries = []
        for child in sorted(target.iterdir()):
            tag = "/" if child.is_dir() else ""
            entries.append(f"{child.name}{tag}")
        return "\n".join(entries) if entries else "(empty)"
    except Exception as e:
        return f"Error: {e}"


def run_delete_file(paths: list, cwd: Path = None) -> str:
    """删除文件（对标 Trae DeleteFile 工具），强制路径安全+存在性校验。

    Args:
        paths: 待删除文件的相对路径列表
    """
    try:
        base = cwd or WORKDIR
        if isinstance(paths, str):
            paths = [paths]
        deleted = []
        errors = []
        for p in paths:
            try:
                fp = (base / p).resolve()
                if not fp.is_relative_to(base):
                    errors.append(f"{p}: path escapes workspace")
                    continue
                if not fp.exists():
                    errors.append(f"{p}: not found")
                    continue
                if fp.is_dir():
                    errors.append(f"{p}: is a directory (use bash rm -r)")
                    continue
                fp.unlink()
                deleted.append(p)
            except Exception as e:
                errors.append(f"{p}: {e}")
        parts = []
        if deleted:
            parts.append(f"Deleted {len(deleted)} file(s): {', '.join(deleted)}")
        if errors:
            parts.append("Errors:\n  " + "\n  ".join(errors))
        return "\n".join(parts) if parts else "(nothing deleted)"
    except Exception as e:
        return f"Error: {e}"


def run_diagnostics(paths: list = None, cwd: Path = None) -> str:
    """Python 语法诊断（对标 Trae GetDiagnostics 工具）。

    使用 py_compile 检查指定 Python 文件的语法错误。
    未指定 paths 时，扫描工作区根目录下一层的 .py 文件。

    Args:
        paths: 待检查的 .py 文件相对路径列表；省略则扫描根目录
    """
    import py_compile
    try:
        base = cwd or WORKDIR
        if paths is None or paths == []:
            targets = [fp for fp in base.glob("*.py") if fp.is_file()]
        else:
            if isinstance(paths, str):
                paths = [paths]
            targets = []
            for p in paths:
                fp = (base / p).resolve()
                if not fp.is_relative_to(base):
                    return f"Error: path escapes workspace: {p}"
                if not fp.exists():
                    return f"Error: not found: {p}"
                targets.append(fp)
        if not targets:
            return "(no .py files to check)"
        results = []
        ok_count = 0
        for fp in targets:
            rel = fp.relative_to(base).as_posix()
            try:
                py_compile.compile(str(fp), doraise=True)
                ok_count += 1
            except py_compile.PyCompileError as e:
                # 提取关键错误信息，避免输出过长
                msg = str(e).split("\n")[:3]
                results.append(f"{rel}: SYNTAX ERROR\n  " + "\n  ".join(msg))
            except Exception as e:
                results.append(f"{rel}: ERROR {e}")
        if ok_count == len(targets):
            results.insert(0, f"All {ok_count} file(s) OK")
        else:
            results.insert(0, f"{ok_count}/{len(targets)} file(s) OK")
        return "\n".join(results)
    except Exception as e:
        return f"Error: {e}"


def run_web_search(query: str, num_results: int = 5) -> str:
    """网络搜索（对标 Trae WebSearch 工具），使用 DuckDuckGo HTML 端点。

    注意：本项目离线优先，web_search 仅在用户明确要求联网时使用。
    无 API Key 依赖，使用公共 HTML 端点，可能不稳定。
    """
    import urllib.request
    import urllib.parse
    try:
        q = urllib.parse.quote(query)
        url = f"https://html.duckduckgo.com/html/?q={q}"
        req = urllib.request.Request(
            url, headers={"User-Agent": "Mozilla/5.0 (compatible; s20-agent/1.0)"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
        # 提取结果链接和标题（简单正则）
        results = []
        for m in re.finditer(
                r'class="result__a"[^>]*href="([^"]+)"[^>]*>([^<]+)<', html):
            raw_url = m.group(1)
            title = m.group(2).strip()
            # DuckDuckGo 重定向 URL 解码
            if raw_url.startswith("//duckduckgo.com/l/?uddg="):
                actual = urllib.parse.unquote(
                    raw_url.split("uddg=", 1)[1].split("&", 1)[0])
            else:
                actual = raw_url
            results.append(f"- {title}\n  {actual}")
            if len(results) >= num_results:
                break
        return "\n".join(results) if results else "(no results)"
    except Exception as e:
        return f"Error: {e}"


def run_web_fetch(url: str, max_chars: int = 20000) -> str:
    """抓取 URL 内容并转为纯文本（对标 Trae WebFetch 工具）。

    仅支持 HTTP/HTTPS，自动跟随重定向，剥离 HTML 标签。
    私有/认证 URL 会失败。
    """
    import urllib.request
    import html as html_mod
    try:
        if not url.startswith(("http://", "https://")):
            return f"Error: URL must start with http:// or https://"
        req = urllib.request.Request(
            url, headers={"User-Agent": "Mozilla/5.0 (compatible; s20-agent/1.0)"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = resp.read().decode("utf-8", errors="ignore")
        # 简易 HTML 清洗：移除 script/style，剥离标签，反转义实体
        raw = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", raw,
                     flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<[^>]+>", "", raw)
        text = html_mod.unescape(text)
        # 压缩空白
        text = re.sub(r"\s+\n", "\n", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text[:max_chars] if len(text) > max_chars else text
    except Exception as e:
        return f"Error: {e}"


def call_tool_handler(handler, args: dict, name: str) -> str:
    if not handler:
        return f"Unknown: {name}"
    try:
        return handler(**(args or {}))
    except TypeError as e:
        return f"Error: {e}"


def _normalize_todos(todos):
    if isinstance(todos, str):
        try:
            todos = json.loads(todos)
        except json.JSONDecodeError:
            try:
                todos = ast.literal_eval(todos)
            except (SyntaxError, ValueError):
                return None, "Error: todos must be a list or JSON array string"
    if not isinstance(todos, list):
        return None, "Error: todos must be a list"
    for i, todo in enumerate(todos):
        if not isinstance(todo, dict):
            return None, f"Error: todos[{i}] must be an object"
        if "content" not in todo or "status" not in todo:
            return None, f"Error: todos[{i}] missing 'content' or 'status'"
        if todo["status"] not in ("pending", "in_progress", "completed"):
            return None, f"Error: todos[{i}] has invalid status '{todo['status']}'"
    return todos, None

def run_todo_write(todos: list) -> str:
    global CURRENT_TODOS
    todos, error = _normalize_todos(todos)
    if error:
        return error
    CURRENT_TODOS = todos
    print(f"  \033[33m[todo] updated {len(CURRENT_TODOS)} item(s)\033[0m")
    return f"Updated {len(CURRENT_TODOS)} todos"


# ── MessageBus ──

# Team communication is append-only JSONL mailboxes. This keeps the protocol
# inspectable on disk and lets background teammates send messages.
MAILBOX_DIR = WORKDIR / ".mailboxes"
MAILBOX_DIR.mkdir(exist_ok=True)


class MessageBus:
    def send(self, from_agent: str, to_agent: str, content: str,
             msg_type: str = "message", metadata: dict = None,
             session_id: str = ""):
        """发送消息到目标 agent 的邮箱，携带 session_id 用于会话隔离"""
        msg = {"from": from_agent, "to": to_agent,
               "content": content, "type": msg_type,
               "ts": time.time(), "metadata": metadata or {}}
        if session_id:
            msg["metadata"]["session_id"] = session_id
        inbox = MAILBOX_DIR / f"{to_agent}.jsonl"
        with open(inbox, "a", encoding="utf-8") as f:
            f.write(json.dumps(msg, ensure_ascii=False) + "\n")
        terminal_print(f"  \033[33m[bus] {from_agent} → {to_agent}: "
                       f"({msg_type}) {content[:50]}\033[0m")

    def read_inbox(self, agent: str) -> list[dict]:
        """读取目标 agent 的全部邮箱消息（不删除文件）"""
        inbox = MAILBOX_DIR / f"{agent}.jsonl"
        if not inbox.exists():
            return []
        msgs = [json.loads(line) for line in inbox.read_text(encoding="utf-8").splitlines()
                if line.strip()]
        return msgs

    def clear_inbox(self, agent: str):
        """清空目标 agent 的邮箱文件"""
        inbox = MAILBOX_DIR / f"{agent}.jsonl"
        if inbox.exists():
            inbox.unlink()

    def requeue_messages(self, agent: str, msgs: list[dict]):
        """将消息重新写回邮箱（用于会话隔离时保留其他会话的消息）"""
        if not msgs:
            return
        inbox = MAILBOX_DIR / f"{agent}.jsonl"
        with open(inbox, "a", encoding="utf-8") as f:
            for msg in msgs:
                f.write(json.dumps(msg, ensure_ascii=False) + "\n")


BUS = MessageBus()
active_teammates: dict[str, bool] = {}

# ── Protocol State ──

@dataclass
class ProtocolState:
    request_id: str
    type: str
    sender: str
    target: str
    status: str
    payload: str
    created_at: float = field(default_factory=time.time)


pending_requests: dict[str, ProtocolState] = {}


def new_request_id() -> str:
    return f"req_{random.randint(0, 999999):06d}"


def match_response(response_type: str, request_id: str, approve: bool):
    # Responses are matched by request_id so one protocol reply cannot approve
    # a different pending request.
    state = pending_requests.get(request_id)
    if not state:
        return
    if state.type == "shutdown" and response_type != "shutdown_response":
        return
    if state.type == "plan_approval" and response_type != "plan_approval_response":
        return
    state.status = "approved" if approve else "rejected"


def consume_lead_inbox(session_id: str = "", route_protocol=True) -> list[dict]:
    """读取 lead 邮箱，按 session_id 过滤。未匹配的消息 requeue 回邮箱，不丢失"""
    all_msgs = BUS.read_inbox("lead")
    if not all_msgs:
        return []

    if not session_id:
        # 无 session_id 时返回全部（兼容旧逻辑）
        BUS.clear_inbox("lead")
        if route_protocol:
            for msg in all_msgs:
                meta = msg.get("metadata", {})
                req_id = meta.get("request_id", "")
                msg_type = msg.get("type", "")
                if req_id and msg_type.endswith("_response"):
                    match_response(msg_type, req_id, meta.get("approve", False))
        return all_msgs

    # 按 session_id 过滤
    mine = []
    others = []
    for msg in all_msgs:
        msg_session = msg.get("metadata", {}).get("session_id", "")
        if msg_session == session_id or not msg_session:
            mine.append(msg)
        else:
            others.append(msg)

    # 清空邮箱，然后 requeue 其他会话的消息
    BUS.clear_inbox("lead")
    BUS.requeue_messages("lead", others)

    if route_protocol:
        for msg in mine:
            meta = msg.get("metadata", {})
            req_id = meta.get("request_id", "")
            msg_type = msg.get("type", "")
            if req_id and msg_type.endswith("_response"):
                match_response(msg_type, req_id, meta.get("approve", False))
    return mine


# ── Autonomous Agent ──

IDLE_POLL_INTERVAL = 5
IDLE_TIMEOUT = 60


def scan_unclaimed_tasks() -> list[dict]:
    unclaimed = []
    for f in sorted(TASKS_DIR.glob("task_*.json")):
        task = json.loads(f.read_text())
        if (task.get("status") == "pending"
                and not task.get("owner")
                and can_start(task["id"])):
            unclaimed.append(task)
    return unclaimed


def idle_poll(agent_name: str, messages: list,
              name: str, role: str,
              worktree_context: dict | None = None) -> str:
    # Autonomous teammates wake up for inbox messages first, then look for
    # unclaimed tasks. This keeps direct protocol messages higher priority.
    for _ in range(IDLE_TIMEOUT // IDLE_POLL_INTERVAL):
        time.sleep(IDLE_POLL_INTERVAL)
        inbox = BUS.read_inbox(agent_name)
        if inbox:
            for msg in inbox:
                if msg.get("type") == "shutdown_request":
                    req_id = msg.get("metadata", {}).get("request_id", "")
                    BUS.send(name, "lead", "Shutting down.",
                             "shutdown_response",
                             {"request_id": req_id, "approve": True})
                    return "shutdown"
            messages.append({"role": "user",
                "content": "<inbox>" + json.dumps(inbox) + "</inbox>"})
            return "work"
        unclaimed = scan_unclaimed_tasks()
        if unclaimed:
            task_data = unclaimed[0]
            result = claim_task(task_data["id"], agent_name)
            if "Claimed" in result:
                wt_info = ""
                if task_data.get("worktree"):
                    wt_path = WORKTREES_DIR / task_data["worktree"]
                    wt_info = f"\nWork directory: {wt_path}"
                    if worktree_context is not None:
                        worktree_context["path"] = str(wt_path)
                messages.append({"role": "user",
                    "content": f"<auto-claimed>Task {task_data['id']}: "
                               f"{task_data['subject']}{wt_info}</auto-claimed>"})
                return "work"
    return "timeout"


# ── Teammate Thread ──

def spawn_teammate_thread(name: str, role: str, prompt: str) -> str:
    if name in active_teammates:
        return f"Teammate '{name}' already exists"

    # Plan approval is a real gate: after submit_plan, the teammate stops
    # taking model/tool steps until lead sends plan_approval_response.
    protocol_ctx = {"waiting_plan": None}
    system = (f"You are '{name}', a {role}. "
              f"Use tools to complete tasks. "
              f"If a task has a worktree, work in that directory.")

    def handle_inbox_message(name: str, msg: dict, messages: list):
        msg_type = msg.get("type", "message")
        meta = msg.get("metadata", {})
        req_id = meta.get("request_id", "")
        if msg_type == "shutdown_request":
            BUS.send(name, "lead", "Shutting down.",
                     "shutdown_response",
                     {"request_id": req_id, "approve": True})
            return True
        if msg_type == "plan_approval_response":
            approve = meta.get("approve", False)
            if req_id == protocol_ctx["waiting_plan"]:
                protocol_ctx["waiting_plan"] = None
            messages.append({"role": "user",
                "content": "[Plan approved]" if approve
                           else f"[Plan rejected] {msg['content']}"})
        return False

    def run():
        wt_ctx = {"path": None}

        def _wt_cwd():
            # Once a task with a worktree is claimed, all teammate file tools
            # transparently run inside that isolated directory.
            p = wt_ctx["path"]
            return Path(p) if p else None

        def _run_bash(command: str) -> str:
            return run_bash(command, cwd=_wt_cwd())

        def _run_read(path: str) -> str:
            return run_read(path, cwd=_wt_cwd())

        def _run_write(path: str, content: str) -> str:
            return run_write(path, content, cwd=_wt_cwd())

        def _run_list_tasks():
            tasks = list_tasks()
            if not tasks:
                return "No tasks."
            return "\n".join(
                f"  {t.id}: {t.subject} [{t.status}]"
                + (f" (wt:{t.worktree})" if t.worktree else "")
                for t in tasks)

        def _run_claim_task(task_id: str):
            result = claim_task(task_id, owner=name)
            if "Claimed" in result:
                task = load_task(task_id)
                wt_ctx["path"] = (str(WORKTREES_DIR / task.worktree)
                                  if task.worktree else None)
            return result

        def _run_complete_task(task_id: str):
            result = complete_task(task_id)
            wt_ctx["path"] = None
            return result

        messages = [{"role": "user", "content": prompt}]
        sub_tools = [
            {"name": "bash", "description": "Run a shell command.",
             "input_schema": {"type": "object",
                              "properties": {"command": {"type": "string"}},
                              "required": ["command"]}},
            {"name": "read_file", "description": "Read file.",
             "input_schema": {"type": "object",
                              "properties": {"path": {"type": "string"},
                                             "limit": {"type": "integer"},
                                             "offset": {"type": "integer"}},
                              "required": ["path"]}},
            {"name": "write_file", "description": "Write file.",
             "input_schema": {"type": "object",
                              "properties": {"path": {"type": "string"},
                                             "content": {"type": "string"}},
                              "required": ["path", "content"]}},
            {"name": "send_message",
             "description": "Send message to another agent.",
             "input_schema": {"type": "object",
                              "properties": {"to": {"type": "string"},
                                             "content": {"type": "string"}},
                              "required": ["to", "content"]}},
            {"name": "submit_plan",
             "description": "Submit a plan for Lead approval.",
             "input_schema": {"type": "object",
                              "properties": {"plan": {"type": "string"}},
                              "required": ["plan"]}},
            {"name": "list_tasks",
             "description": "List all tasks.",
             "input_schema": {"type": "object", "properties": {},
                              "required": []}},
            {"name": "claim_task",
             "description": "Claim a pending task.",
             "input_schema": {"type": "object",
                              "properties": {"task_id": {"type": "string"}},
                              "required": ["task_id"]}},
            {"name": "complete_task",
             "description": "Mark an in-progress task as completed.",
             "input_schema": {"type": "object",
                              "properties": {"task_id": {"type": "string"}},
                              "required": ["task_id"]}},
        ]

        sub_handlers = {
            "bash": _run_bash, "read_file": _run_read,
            "write_file": _run_write,
            "send_message": lambda to, content: (BUS.send(name, to, content),
                                                  "Sent")[1],
            "list_tasks": _run_list_tasks,
            "claim_task": _run_claim_task,
            "complete_task": _run_complete_task,
        }

        while True:
            if len(messages) <= 3:
                messages.insert(0, {"role": "user",
                    "content": f"<identity>You are '{name}', role: {role}. "
                               f"Continue your work.</identity>"})
            should_shutdown = False
            for _ in range(10):
                inbox = BUS.read_inbox(name)
                for msg in inbox:
                    stopped = handle_inbox_message(name, msg, messages)
                    if stopped:
                        should_shutdown = True
                        break
                if should_shutdown:
                    break
                if protocol_ctx["waiting_plan"]:
                    # Poll only for protocol replies while the approval gate is
                    # closed; do not let the model continue with the task.
                    time.sleep(IDLE_POLL_INTERVAL)
                    continue
                if inbox and not should_shutdown:
                    non_protocol = [m for m in inbox
                                    if m.get("type") == "message"]
                    if non_protocol:
                        messages.append({"role": "user",
                            "content": "<inbox>" + json.dumps(non_protocol) + "</inbox>"})
                try:
                    response = client.messages.create(
                        model=MODEL, system=system, messages=messages[-20:],
                        tools=sub_tools, max_tokens=8000)
                except Exception:
                    break
                messages.append({"role": "assistant", "content": response.content})
                if not has_tool_use(response.content):
                    break
                results = []
                for block in response.content:
                    if block.type == "tool_use":
                        if block.name == "submit_plan":
                            output = _teammate_submit_plan(
                                name, block.input.get("plan", ""))
                            match = re.search(r"\((req_\d+)\)", output)
                            protocol_ctx["waiting_plan"] = (
                                match.group(1) if match else output)
                        else:
                            handler = sub_handlers.get(block.name)
                            output = call_tool_handler(handler, block.input,
                                                       block.name)
                        results.append({"type": "tool_result",
                                        "tool_use_id": block.id,
                                        "content": str(output)})
                        if protocol_ctx["waiting_plan"]:
                            # Ignore later tool_use blocks from the same model
                            # response; they belong after approval, not before.
                            break
                messages.append({"role": "user", "content": results})
                if protocol_ctx["waiting_plan"]:
                    break
            if should_shutdown:
                break
            if protocol_ctx["waiting_plan"]:
                continue
            idle_result = idle_poll(name, messages, name, role, wt_ctx)
            if idle_result in ("shutdown", "timeout"):
                break

        summary = "Done."
        for msg in reversed(messages):
            if msg["role"] == "assistant" and isinstance(msg["content"], list):
                for b in msg["content"]:
                    if getattr(b, "type", None) == "text":
                        summary = b.text
                        break
                else:
                    continue
                break
        BUS.send(name, "lead", summary, "result")
        active_teammates.pop(name, None)

    active_teammates[name] = True
    threading.Thread(target=run, daemon=True).start()
    return f"Teammate '{name}' spawned as {role}"


def _teammate_submit_plan(from_name: str, plan: str) -> str:
    req_id = new_request_id()
    pending_requests[req_id] = ProtocolState(
        request_id=req_id, type="plan_approval",
        sender=from_name, target="lead",
        status="pending", payload=plan)
    BUS.send(from_name, "lead", plan,
             "plan_approval_request",
             {"request_id": req_id})
    return f"Plan submitted ({req_id})"


# ── Lead Protocol Tools ──

def run_request_shutdown(teammate: str) -> str:
    req_id = new_request_id()
    pending_requests[req_id] = ProtocolState(
        request_id=req_id, type="shutdown",
        sender="lead", target=teammate,
        status="pending", payload="")
    BUS.send("lead", teammate, "Shut down.", "shutdown_request",
             {"request_id": req_id})
    return f"Shutdown request sent to {teammate}"


def run_request_plan(teammate: str, task: str) -> str:
    BUS.send("lead", teammate, f"Submit plan for: {task}", "message")
    return f"Asked {teammate} to submit a plan"


def run_review_plan(request_id: str, approve: bool,
                    feedback: str = "") -> str:
    state = pending_requests.get(request_id)
    if not state:
        return f"Request {request_id} not found"
    state.status = "approved" if approve else "rejected"
    BUS.send("lead", state.sender,
             feedback or ("Approved" if approve else "Rejected"),
             "plan_approval_response",
             {"request_id": request_id, "approve": approve})
    return f"Plan {'approved' if approve else 'rejected'}"


# ── File Tracker Module ──

# 文件追踪器：记录 Agent 创建/修改的所有文件，管理临时文件生命周期。
# 临时文件在会话切换时暂停计时，宽限期到期后自动清理，删除前保留可溯源占位符。


class FileTracker:
    """文件追踪器：内存 + 磁盘持久化，管理临时文件的全生命周期"""

    def __init__(self, tracker_path: Path):
        self._tracker_path = tracker_path
        self._entries: dict[str, dict] = {}
        self._lock = threading.Lock()
        self._load()

    # ── 公开接口 ──

    def track(self, path: str, is_new: bool, tool: str,
              purpose: str | None = None, session_id: str = "",
              task_id: str = "", content_preview: str = "") -> None:
        """注册或更新一个文件的追踪记录

        Args:
            path: 文件相对路径
            is_new: 是否为新创建的文件（True=新建，False=修改现有文件）
            tool: 创建/修改该文件的工具名（write_file / edit_file / bash）
            purpose: 显式指定的用途（temporary / persistent），None 则自动推断
            session_id: 创建该文件的会话 ID
            task_id: 关联的任务 ID
            content_preview: 文件内容预览（前 200 字符，用于审计）
        """
        with self._lock:
            if path in self._entries:
                # 修改现有文件：更新元信息，保持原有 is_temporary
                entry = self._entries[path]
                entry["updated_at"] = time.time()
                entry["tool"] = tool
                entry["session_id"] = session_id or entry.get("session_id", "")
                entry["task_id"] = task_id or entry.get("task_id", "")
                entry["status"] = "active"
                # 若原先是 dormant，恢复为 active 并继续计时
                if entry.get("status") == "dormant":
                    elapsed = time.time() - entry.get("last_active_at", time.time())
                    entry["accumulated_seconds"] = entry.get("accumulated_seconds", 0) + elapsed
                    entry["last_active_at"] = time.time()
            else:
                # 新文件：推断 purpose 并创建条目
                inferred = self._infer_purpose(path, is_new, tool, content_preview)
                actual_purpose = purpose if purpose else inferred
                self._entries[path] = {
                    "path": path,
                    "created_at": time.time(),
                    "updated_at": time.time(),
                    "tool": tool,
                    "purpose": actual_purpose,
                    "is_temporary": actual_purpose == "temporary",
                    "session_id": session_id,
                    "task_id": task_id,
                    "status": "active",
                    "accumulated_seconds": 0.0,
                    "last_active_at": time.time(),
                    "placeholder": None,
                    "ghost_reason": None,
                    "content_preview": content_preview[:200],
                }
            self._save()

    def get_entry(self, path: str) -> dict | None:
        """查询单个文件的追踪条目"""
        return self._entries.get(path)

    def query(self, purpose: str = "all", path_pattern: str = "",
              session_id: str = "", task_id: str = "") -> list[dict]:
        """按条件查询追踪条目，返回格式化结果列表"""
        with self._lock:
            results = []
            for entry in self._entries.values():
                if purpose != "all" and entry["purpose"] != purpose:
                    continue
                if path_pattern:
                    import fnmatch
                    if not fnmatch.fnmatch(entry["path"], path_pattern):
                        continue
                if session_id and entry.get("session_id") != session_id:
                    continue
                if task_id and entry.get("task_id") != task_id:
                    continue
                results.append(dict(entry))
            return results

    def on_session_activate(self, session_id: str) -> list[str]:
        """会话恢复时调用：将属于该会话的 dormant 临时文件恢复为 active，继续计时

        Returns:
            恢复成功的临时文件路径列表
        """
        restored = []
        with self._lock:
            for entry in self._entries.values():
                # 只恢复临时文件，持久文件不受会话切换影响
                if not entry.get("is_temporary"):
                    continue
                if (entry.get("session_id") == session_id
                        and entry.get("status") in ("dormant", "ghost")):
                    # 若物理文件仍存在，恢复为 active
                    fp = WORKDIR / entry["path"]
                    if entry["status"] == "ghost" and fp.exists():
                        entry["status"] = "active"
                        entry["ghost_reason"] = None
                        entry["accumulated_seconds"] = entry.get("accumulated_seconds", 0)
                        entry["last_active_at"] = time.time()
                    elif entry["status"] == "dormant" and fp.exists():
                        # 计算休眠期间积累的时长
                        paused_duration = time.time() - entry.get("last_active_at", time.time())
                        entry["accumulated_seconds"] = (
                            entry.get("accumulated_seconds", 0) + paused_duration)
                        entry["last_active_at"] = time.time()
                        entry["status"] = "active"
                        restored.append(entry["path"])
                    # ghost 且文件已丢失：保持 ghost 状态，不恢复
            self._save()
        return restored

    def on_session_deactivate(self, session_id: str) -> list[str]:
        """会话切换时调用：将属于该会话的 active 临时文件标记为 dormant，暂停计时

        Returns:
            进入 dormant 状态的临时文件路径列表
        """
        deactivated = []
        with self._lock:
            for entry in self._entries.values():
                # 只暂停临时文件，持久文件不受会话切换影响
                if not entry.get("is_temporary"):
                    continue
                if (entry.get("session_id") == session_id
                        and entry.get("status") == "active"):
                    entry["accumulated_seconds"] = entry.get("accumulated_seconds", 0)
                    entry["last_active_at"] = time.time()
                    entry["status"] = "dormant"
                    deactivated.append(entry["path"])
            self._save()
        return deactivated

    def cleanup(self, session_id: str = "", task_id: str = "",
                dry_run: bool = False) -> list[dict]:
        """清理指定范围的临时文件，写入占位符后删除

        清理 active（用户主动清理）和 dormant（宽限期到期）两种状态的临时文件。
        deleted / ghost 状态的条目跳过，避免重复清理。

        Returns:
            清理报告列表，每项包含 path / action / placeholder
        """
        report = []
        with self._lock:
            targets = [e for e in self._entries.values()
                       if e["is_temporary"]
                       and e["status"] in ("active", "dormant")
                       and (not session_id or e.get("session_id") == session_id)
                       and (not task_id or e.get("task_id") == task_id)]
            for entry in targets:
                entry["status"] = "deleted"
                entry["deleted_at"] = time.time()
                if dry_run:
                    report.append({"path": entry["path"], "action": "dry_run"})
                    continue
                placeholder_path = self._write_placeholder(entry)
                entry["placeholder"] = str(placeholder_path)
                fp = WORKDIR / entry["path"]
                if fp.exists():
                    fp.unlink(missing_ok=True)
                report.append({
                    "path": entry["path"],
                    "action": "deleted",
                    "placeholder": str(placeholder_path),
                })
            self._save()
        return report

    def check_cleanup_due(self) -> list[dict]:
        """检查哪些 dormant 文件的总活跃时长达到宽限期阈值，返回待清理条目"""
        due = []
        with self._lock:
            now = time.time()
            for entry in self._entries.values():
                if entry["status"] != "dormant" or not entry["is_temporary"]:
                    continue
                # 计算当前总消耗时长
                total_elapsed = (entry.get("accumulated_seconds", 0)
                                 + (now - entry.get("last_active_at", now)))
                if total_elapsed >= DORMANT_GRACE_SECONDS:
                    entry["ghost_reason"] = "cleaned_by_timeout"
                    due.append(entry)
        return due

    def upgrade_persistent(self, path: str) -> str:
        """将临时文件升级为持久文件，防止被自动清理"""
        with self._lock:
            entry = self._entries.get(path)
            if not entry:
                return f"Error: file '{path}' not found in tracker"
            entry["purpose"] = "persistent"
            entry["is_temporary"] = False
            entry["status"] = "active"
            self._save()
            return f"File '{path}' upgraded to persistent"

    # ── 内部方法 ──

    def _infer_purpose(self, path: str, is_new: bool, tool: str,
                       content_preview: str) -> str:
        """按优先级规则推断文件的 purpose

        规则优先级（从高到低）：
        1. 路径匹配临时文件名模式 → temporary
        2. bash 工具创建的新文件 → temporary（重定向写入通常为临时）
        3. 路径在已知持久目录 → persistent
        4. 默认 → persistent（保守策略）
        """
        name = Path(path).name
        # 规则 1：路径包含临时文件特征
        for pattern in TMP_NAME_PATTERNS:
            if pattern in name:
                return "temporary"
        # 规则 2：bash 创建的新文件默认临时
        if tool == "bash" and is_new:
            return "temporary"
        # 规则 3：已知持久目录
        parts = Path(path).parts
        for part in parts[:-1]:  # 不包含文件名本身
            if part in PERSISTENT_DIRS:
                return "persistent"
        # 规则 4：默认持久
        return "persistent"

    def _write_placeholder(self, entry: dict) -> Path:
        """在原文件同目录下写入 .tracker 占位标记文件，保留溯源信息"""
        original_fp = WORKDIR / entry["path"]
        placeholder_name = f".{original_fp.name}.tracker"
        placeholder_path = original_fp.parent / placeholder_name
        placeholder_text = (
            f"# [TRACKED FILE - CLEANED]\n"
            f"# Original path: {entry['path']}\n"
            f"# Created: {datetime.fromtimestamp(entry['created_at']).isoformat()}\n"
            f"# Tool: {entry['tool']}, Purpose: {entry['purpose']}\n"
            f"# Session: {entry.get('session_id', 'unknown')[:8]}\n"
            f"# Task: {entry.get('task_id', 'none')}\n"
        )
        if entry.get("ghost_reason"):
            placeholder_text += f"# Reason: {entry['ghost_reason']}\n"
        if entry.get("deleted_at"):
            placeholder_text += f"# Deleted: {datetime.fromtimestamp(entry['deleted_at']).isoformat()}\n"
        placeholder_text += "# Full record: .file_tracker.json\n"
        placeholder_path.write_text(placeholder_text, encoding="utf-8")
        return placeholder_path

    def _save(self) -> None:
        """将追踪表持久化到磁盘"""
        try:
            data = {"version": 1, "entries": list(self._entries.values())}
            self._tracker_path.write_text(
                json.dumps(data, indent=2, ensure_ascii=False),
                encoding="utf-8")
        except OSError as e:
            print(f"  \033[33m[file-tracker] save error: {e}\033[0m")

    def _load(self) -> None:
        """从磁盘加载追踪表，物理文件不存在的条目标记为 ghost"""
        if not self._tracker_path.exists():
            return
        try:
            data = json.loads(self._tracker_path.read_text(encoding="utf-8"))
            entries = data.get("entries", [])
            for raw in entries:
                path = raw.get("path", "")
                fp = WORKDIR / path
                status = raw.get("status", "active")
                # 若物理文件已不存在且状态为 active，降级为 ghost
                if not fp.exists() and status in ("active", "dormant"):
                    raw["status"] = "ghost"
                    raw["ghost_reason"] = raw.get("ghost_reason", "file_missing_on_load")
                elif not fp.exists() and status == "ghost":
                    raw["ghost_reason"] = raw.get("ghost_reason", "file_missing_on_load")
                self._entries[path] = raw
        except (json.JSONDecodeError, OSError) as e:
            print(f"  \033[33m[file-tracker] load error: {e}，使用空追踪表\033[0m")


# 全局文件追踪器实例
_FILE_TRACKER = FileTracker(FILE_TRACKER_PATH)


def _scan_workspace_files() -> set[str]:
    """扫描工作区所有文件路径（相对路径集合），用于 bash 前后差集对比"""
    try:
        return {p.relative_to(WORKDIR).as_posix()
                for p in WORKDIR.rglob("*") if p.is_file()
                and not p.name.startswith(".tracker")
                and not p.name.endswith(".pyc")}
    except OSError:
        return set()


def _cleanup_dormant_background():
    """后台线程：定期检查 dormant 文件是否超过宽限期，到期则自动清理"""
    while True:
        time.sleep(10)
        try:
            due = _FILE_TRACKER.check_cleanup_due()
            if due:
                print(f"  \033[33m[file-tracker] {len(due)} temp file(s) exceeded grace period, cleaning\033[0m")
                for entry in due:
                    _FILE_TRACKER._write_placeholder(entry)
                    fp = WORKDIR / entry["path"]
                    if fp.exists():
                        fp.unlink(missing_ok=True)
                    entry["status"] = "deleted"
                    entry["deleted_at"] = time.time()
                _FILE_TRACKER._save()
        except Exception as e:
            print(f"  \033[31m[file-tracker] background cleanup error: {e}\033[0m")


# 启动后台清理守护线程
threading.Thread(target=_cleanup_dormant_background, daemon=True).start()


# ── Hooks + Permission Pipeline ──

# Hooks are intentionally outside tool handlers. The loop can add permission,
# logging, and stop behavior without changing each individual tool.
HOOKS = {"UserPromptSubmit": [], "PreToolUse": [],
         "PostToolUse": [], "Stop": []}


def register_hook(event: str, callback):
    HOOKS[event].append(callback)


def trigger_hooks(event: str, *args):
    for callback in HOOKS[event]:
        result = callback(*args)
        if result is not None:
            return result
    return None


DENY_LIST = ["rm -rf /", "sudo", "shutdown", "reboot", "mkfs", "dd if="]
DESTRUCTIVE = ["rm ", "> /etc/", "chmod 777"]
# bash 命令中如果出现这些模式，提示改用专用工具（不阻断，仅警告）
REDIRECT_TO_TOOL = [
    ("cat ", "read_file"),
    ("grep ", "grep"),
    ("rg ", "grep"),
    ("find ", "glob"),
    ("ls ", "ls"),
    ("rm ", "delete_file"),
]


def permission_hook(block):
    # The permission layer sees the raw tool_use before dispatch. It can deny,
    # ask the user, or allow execution to continue.
    if block.name == "bash":
        command = block.input.get("command", "")
        for pattern in DENY_LIST:
            if pattern in command:
                return f"Permission denied: '{pattern}' is on the deny list"
        # 提示：bash 中出现 cat/grep/find/ls/rm 等应改用专用工具（原则 1/2/7）
        for token, better_tool in REDIRECT_TO_TOOL:
            if token in command:
                print(f"\n\033[33m[principle] bash 中检测到 '{token.strip()}'，"
                      f"建议改用专用工具 '{better_tool}'\033[0m")
                print(f"  command: {command}")
                break
        if any(token in command for token in DESTRUCTIVE):
            print(f"\n\033[33m[permission] destructive command\033[0m")
            print(f"  {command}")
            choice = input("  Allow? [y/N] ").strip().lower()
            if choice not in ("y", "yes"):
                return "Permission denied by user"
    # 路径安全校验：所有接收 path 参数的文件类工具都必须通过 safe_path
    if block.name in ("write_file", "edit_file", "read_file"):
        path = block.input.get("path", "")
        try:
            safe_path(path)
        except Exception:
            return f"Permission denied: path escapes workspace: {path}"
    # delete_file 接收 paths 列表，逐个校验
    if block.name == "delete_file":
        paths = block.input.get("paths", [])
        if isinstance(paths, str):
            paths = [paths]
        for p in paths:
            try:
                safe_path(p)
            except Exception:
                return f"Permission denied: path escapes workspace: {p}"
    # grep/ls/diagnostics 的 path/glob 参数校验（若提供）
    if block.name in ("grep", "ls"):
        path = block.input.get("path", ".")
        try:
            safe_path(path)
        except Exception:
            return f"Permission denied: path escapes workspace: {path}"
    if block.name == "diagnostics":
        paths = block.input.get("paths", [])
        if isinstance(paths, str):
            paths = [paths]
        for p in paths:
            try:
                safe_path(p)
            except Exception:
                return f"Permission denied: path escapes workspace: {p}"
    if block.name.startswith("mcp__") and "deploy" in block.name:
        print(f"\n\033[33m[permission] MCP destructive-looking tool: {block.name}\033[0m")
        choice = input("  Allow? [y/N] ").strip().lower()
        if choice not in ("y", "yes"):
            return "Permission denied by user"
    return None


def log_hook(block):
    print(f"\033[90m[HOOK] {block.name}\033[0m")
    return None


def large_output_hook(block, output):
    if len(str(output)) > 100000:
        print(f"\033[33m[HOOK] large output from {block.name}: "
              f"{len(str(output))} chars\033[0m")
    return None


def user_prompt_hook(query: str):
    print(f"\033[90m[HOOK] UserPromptSubmit: {WORKDIR}\033[0m")
    return None


def stop_hook(messages: list):
    tool_count = 0
    for msg in messages:
        content = msg.get("content")
        if isinstance(content, list):
            tool_count += sum(1 for item in content
                              if isinstance(item, dict)
                              and item.get("type") == "tool_result")
    print(f"\033[90m[HOOK] Stop: {tool_count} tool result(s)\033[0m")
    return None


register_hook("UserPromptSubmit", user_prompt_hook)
register_hook("PreToolUse", permission_hook)
register_hook("PreToolUse", log_hook)
register_hook("PostToolUse", large_output_hook)
register_hook("Stop", stop_hook)


# ── Subagent Tool ──

SUB_SYSTEM = (
    f"You are a coding subagent at {WORKDIR}. "
    "Complete the task, then return a concise final summary. "
    "Do not spawn more agents."
)


SUB_TOOLS = [
    {"name": "bash", "description": "Run a shell command.",
     "input_schema": {"type": "object",
                      "properties": {"command": {"type": "string"}},
                      "required": ["command"]}},
    {"name": "read_file", "description": "Read file contents.",
     "input_schema": {"type": "object",
                      "properties": {"path": {"type": "string"},
                                     "limit": {"type": "integer"},
                                     "offset": {"type": "integer"}},
                      "required": ["path"]}},
    {"name": "write_file", "description": "Write content to a file.",
     "input_schema": {"type": "object",
                      "properties": {"path": {"type": "string"},
                                     "content": {"type": "string"}},
                      "required": ["path", "content"]}},
    {"name": "edit_file", "description": "Replace exact text in a file once.",
     "input_schema": {"type": "object",
                      "properties": {"path": {"type": "string"},
                                     "old_text": {"type": "string"},
                                     "new_text": {"type": "string"}},
                      "required": ["path", "old_text", "new_text"]}},
    {"name": "glob", "description": "Find files matching a glob pattern.",
     "input_schema": {"type": "object",
                      "properties": {"pattern": {"type": "string"}},
                      "required": ["pattern"]}},
]


SUB_HANDLERS = {
    "bash": run_bash, "read_file": run_read,
    "write_file": run_write, "edit_file": run_edit,
    "glob": run_glob,
}


def extract_text(content) -> str:
    if not isinstance(content, list):
        return str(content)
    return "\n".join(
        getattr(block, "text", "")
        for block in content
        if getattr(block, "type", None) == "text").strip()


def has_tool_use(content) -> bool:
    # Do not rely on stop_reason alone; the concrete tool_use block is the
    # continuation signal used by the loop.
    return any(getattr(block, "type", None) == "tool_use"
               for block in content)


def spawn_subagent(description: str) -> str:
    messages = [{"role": "user", "content": description}]
    for _ in range(30):
        response = client.messages.create(
            model=MODEL, system=SUB_SYSTEM, messages=messages,
            tools=SUB_TOOLS, max_tokens=8000)
        messages.append({"role": "assistant", "content": response.content})
        if not has_tool_use(response.content):
            break
        results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            blocked = trigger_hooks("PreToolUse", block)
            if blocked:
                output = str(blocked)
            else:
                handler = SUB_HANDLERS.get(block.name)
                output = call_tool_handler(handler, block.input, block.name)
                trigger_hooks("PostToolUse", block, output)
            results.append({"type": "tool_result",
                            "tool_use_id": block.id,
                            "content": str(output)})
        messages.append({"role": "user", "content": results})
    for msg in reversed(messages):
        if msg["role"] == "assistant":
            text = extract_text(msg["content"])
            if text:
                return text
    return "Subagent finished without a text summary."


# ── Context Compaction ──

# Compaction is layered: first shrink oversized tool results, then trim old
# message ranges, and only call the model for a summary when the context is
# still too large or the model explicitly asks for compact.
def estimate_size(messages: list) -> int:
    return len(json.dumps(messages, default=str))

def block_type(block):
    return block.get("type") if isinstance(block, dict) else getattr(block, "type", None)


def message_has_tool_use(message: dict) -> bool:
    if message.get("role") != "assistant":
        return False
    content = message.get("content")
    if not isinstance(content, list):
        return False
    return any(block_type(block) == "tool_use" for block in content)


def is_tool_result_message(message: dict) -> bool:
    if message.get("role") != "user":
        return False
    content = message.get("content")
    if not isinstance(content, list):
        return False
    return any(isinstance(block, dict) and block.get("type") == "tool_result"
               for block in content)


def collect_tool_results(messages: list):
    found = []
    for mi, msg in enumerate(messages):
        content = msg.get("content")
        if msg.get("role") != "user" or not isinstance(content, list):
            continue
        for bi, block in enumerate(content):
            if isinstance(block, dict) and block.get("type") == "tool_result":
                found.append((mi, bi, block))
    return found


def persist_large_output(tool_use_id: str, output: str) -> str:
    if len(output) <= PERSIST_THRESHOLD:
        return output
    TOOL_RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    path = TOOL_RESULTS_DIR / f"{tool_use_id}.txt"
    if not path.exists():
        path.write_text(output)
    return (f"<persisted-output>\nFull output: {path}\n"
            f"Preview:\n{output[:2000]}\n</persisted-output>")


def tool_result_budget(messages: list, max_bytes: int = 200_000) -> list:
    if not messages:
        return messages
    last = messages[-1]
    content = last.get("content")
    if last.get("role") != "user" or not isinstance(content, list):
        return messages
    blocks = [(i, b) for i, b in enumerate(content)
              if isinstance(b, dict) and b.get("type") == "tool_result"]
    total = sum(len(str(b.get("content", ""))) for _, b in blocks)
    if total <= max_bytes:
        return messages
    for _, block in sorted(blocks,
                           key=lambda pair: len(str(pair[1].get("content", ""))),
                           reverse=True):
        if total <= max_bytes:
            break
        text = str(block.get("content", ""))
        block["content"] = persist_large_output(
            block.get("tool_use_id", "unknown"), text)
        total = sum(len(str(b.get("content", ""))) for _, b in blocks)
    return messages


def snip_compact(messages: list, max_messages: int = 50) -> list:
    if len(messages) <= max_messages:
        return messages
    head_end, tail_start = 3, len(messages) - (max_messages - 3)
    if head_end > 0 and message_has_tool_use(messages[head_end - 1]):
        while head_end < len(messages) and is_tool_result_message(messages[head_end]):
            head_end += 1
    if (tail_start > 0 and tail_start < len(messages)
            and is_tool_result_message(messages[tail_start])
            and message_has_tool_use(messages[tail_start - 1])):
        tail_start -= 1
    if head_end >= tail_start:
        return messages
    snipped = tail_start - head_end
    return (messages[:head_end]
            + [{"role": "user", "content": f"[snipped {snipped} messages]"}]
            + messages[tail_start:])


def micro_compact(messages: list) -> list:
    tool_results = collect_tool_results(messages)
    if len(tool_results) <= KEEP_RECENT_TOOL_RESULTS:
        return messages
    for _, _, block in tool_results[:-KEEP_RECENT_TOOL_RESULTS]:
        if len(str(block.get("content", ""))) > 120:
            block["content"] = "[Earlier tool result compacted. Re-run if needed.]"
    return messages


def write_transcript(messages: list) -> Path:
    TRANSCRIPT_DIR.mkdir(parents=True, exist_ok=True)
    path = TRANSCRIPT_DIR / f"transcript_{int(time.time())}.jsonl"
    with path.open("w") as f:
        for msg in messages:
            f.write(json.dumps(msg, default=str) + "\n")
    return path


def summarize_history(messages: list) -> str:
    conversation = json.dumps(messages, default=str)[:80000]
    prompt = ("Summarize this coding-agent conversation so work can continue. "
              "Preserve current goal, key findings, changed files, remaining work, "
              "and user constraints.\n\n" + conversation)
    response = client.messages.create(
        model=MODEL,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=2000)
    return extract_text(response.content) or "(empty summary)"


def compact_history(messages: list, session_id: str = "") -> list:
    """压缩历史消息，可选写入 compact_boundary 标记到 JSONL"""
    transcript = write_transcript(messages)
    print(f"  \033[36m[compact] transcript saved: {transcript}\033[0m")
    summary = summarize_history(messages)
    # 向 JSONL 追加压缩边界标记和摘要
    if session_id:
        timestamp = datetime.now().isoformat()
        append_to_jsonl(session_id, {
            "type": "system",
            "subtype": "compact_boundary",
            "timestamp": timestamp,
        })
        append_to_jsonl(session_id, {
            "type": "system",
            "subtype": "compact_summary",
            "content": summary,
            "timestamp": timestamp,
        })
        update_session_in_index(session_id, has_compact_boundary=True)
    return [{"role": "user", "content": f"[Compacted]\n\n{summary}"}]


def reactive_compact(messages: list) -> list:
    transcript = write_transcript(messages)
    print(f"  \033[31m[reactive compact] transcript saved: {transcript}\033[0m")
    try:
        summary = summarize_history(messages)
    except Exception:
        summary = "Earlier conversation was trimmed after a prompt-too-long error."
    tail_start = max(0, len(messages) - 5)
    if (tail_start > 0 and tail_start < len(messages)
            and is_tool_result_message(messages[tail_start])
            and message_has_tool_use(messages[tail_start - 1])):
        tail_start -= 1
    return [{"role": "user", "content": f"[Reactive compact]\n\n{summary}"},
            *messages[tail_start:]]


# ── Error Recovery ──

class AllModelsExhaustedError(RuntimeError):
    """所有模型免费额度均已耗尽的异常，用于触发无 token 提示"""
    pass


class ModelPool:
    """模型池管理器：维护可用模型列表，在配额耗尽时自动切换下一个模型"""

    def __init__(self, models: list[str]):
        # 拷贝一份避免外部修改影响内部状态
        self.models: list[str] = list(models)
        # 已耗尽免费额度的模型集合
        self.exhausted: set[str] = set()
        # 当前使用的模型在 models 列表中的索引
        self.current_index: int = 0

    @property
    def current(self) -> str:
        """获取当前正在使用的模型 ID"""
        if not self.models:
            return ""
        return self.models[self.current_index]

    def mark_exhausted(self, model: str) -> None:
        """将指定模型标记为免费额度已耗尽"""
        if model not in self.exhausted:
            self.exhausted.add(model)
            print(f"  \033[31m[quota] 模型 {model} 额度已耗尽，"
                  f"剩余可用 {len(self.models) - len(self.exhausted)} 个\033[0m")

    def next_model(self) -> str | None:
        """切换到下一个未耗尽的模型，若全部耗尽则返回 None"""
        for _ in range(len(self.models)):
            self.current_index = (self.current_index + 1) % len(self.models)
            if self.models[self.current_index] not in self.exhausted:
                return self.models[self.current_index]
        return None

    def all_exhausted(self) -> bool:
        """判断池中所有模型是否都已耗尽"""
        return all(m in self.exhausted for m in self.models)


def is_quota_exhausted_error(e: Exception) -> bool:
    """识别错误是否表示模型免费额度已耗尽（配额/欠费/余额不足）

    覆盖阿里云百炼的专属错误码：
    - AllocationQuota.FreeTierOnly：开启「免费额度用完即停」后，额度耗尽返回 403
    - FreeTierQuota.Exhausted：免费额度耗尽
    - Arrearage：欠费
    以及通用的 quota / 余额不足等关键词
    """
    msg = str(e).lower()
    quota_keywords = [
        "quota",                       # 通用配额关键词
        "free quota",                  # 免费额度
        "免费额度",                    # 中文
        "allocationquota.freetieronly", # 阿里云：免费额度用完即停触发的 403 错误码
        "freetierquota.exhausted",      # 阿里云：免费额度耗尽
        "arrears",                     # 欠费
        "arrearage",
        "insufficient_balance",        # 余额不足
        "balance is not enough",
        "余额不足",
        "exceeded your current",
        "no enough balance",
    ]
    return any(kw in msg for kw in quota_keywords)


class RecoveryState:
    def __init__(self, model_pool: ModelPool = None):
        self.has_escalated = False
        self.recovery_count = 0
        self.consecutive_529 = 0
        self.has_attempted_reactive_compact = False
        # 模型池：未传入时使用全局 MODEL_POOL 构造一个
        self.model_pool = model_pool or ModelPool(MODEL_POOL)
        # 当前使用的模型 ID，与 model_pool.current 保持同步
        self.current_model = self.model_pool.current


def retry_delay(attempt: int) -> float:
    base = min(BASE_DELAY_MS * (2 ** attempt), 32000) / 1000
    return base + random.uniform(0, base * 0.25)


def with_retry(fn, state: RecoveryState):
    """统一的重试包装：处理 429 限速、529 过载、配额耗尽三类错误

    - 配额耗尽：标记当前模型为已耗尽，立即切换到池中下一个模型重试
    - 429 限速：按指数退避延迟后重试
    - 529 过载：累计达到阈值时切换到池中下一个模型，再退避重试
    - 全部模型耗尽：抛出 AllModelsExhaustedError 由上层处理
    """
    attempt = 0
    while attempt < MAX_RETRIES:
        try:
            result = fn()
            state.consecutive_529 = 0
            return result
        except Exception as e:
            name = type(e).__name__.lower()
            msg = str(e).lower()

            # 1) 配额耗尽：切换模型，不增加 attempt 计数
            if is_quota_exhausted_error(e):
                state.model_pool.mark_exhausted(state.current_model)
                next_m = state.model_pool.next_model()
                if next_m:
                    state.current_model = next_m
                    print(f"  \033[33m[quota] 切换到模型 {next_m} 重试\033[0m")
                    continue  # 切换后重置重试计数
                raise AllModelsExhaustedError(
                    "所有模型免费额度均已耗尽，请前往阿里云百炼控制台充值"
                    "或更换 API Key 后重试")

            # 2) 限速错误：退避后重试
            if "ratelimit" in name or "429" in msg:
                delay = retry_delay(attempt)
                print(f"  \033[33m[429] retry {attempt + 1}/{MAX_RETRIES} "
                      f"after {delay:.1f}s\033[0m")
                time.sleep(delay)
                attempt += 1
                continue

            # 3) 过载错误：累计达阈值时切换模型，再退避重试
            if "overloaded" in name or "529" in msg or "overloaded" in msg:
                state.consecutive_529 += 1
                if state.consecutive_529 >= MAX_CONSECUTIVE_529:
                    next_m = state.model_pool.next_model()
                    if next_m and next_m != state.current_model:
                        state.current_model = next_m
                        state.consecutive_529 = 0
                        print(f"  \033[31m[529] switching to {next_m}\033[0m")
                delay = retry_delay(attempt)
                print(f"  \033[33m[529] retry {attempt + 1}/{MAX_RETRIES} "
                      f"after {delay:.1f}s\033[0m")
                time.sleep(delay)
                attempt += 1
                continue

            # 4) 其他异常：直接抛出，由上层处理
            raise
    raise RuntimeError(f"Max retries ({MAX_RETRIES}) exceeded")


def is_prompt_too_long_error(e: Exception) -> bool:
    msg = str(e).lower()
    return (("prompt" in msg and "long" in msg)
            or "context_length_exceeded" in msg
            or "max_context_window" in msg)


# ── Background Tasks ──

# Slow tools return a placeholder tool_result immediately. Their real output is
# later injected as a task_notification, so the main loop can keep moving.
_bg_counter = 0
background_tasks: dict[str, dict] = {}
background_results: dict[str, str] = {}
background_lock = threading.Lock()


def is_slow_operation(tool_name: str, tool_input: dict) -> bool:
    if tool_name != "bash":
        return False
    command = tool_input.get("command", "").lower()
    slow_keywords = ["install", "build", "test", "deploy", "compile",
                     "docker build", "pip install", "npm install",
                     "cargo build", "pytest", "make"]
    return any(keyword in command for keyword in slow_keywords)


def should_run_background(tool_name: str, tool_input: dict) -> bool:
    if tool_name != "bash":
        return False
    return bool(tool_input.get("run_in_background")) or is_slow_operation(tool_name, tool_input)


def start_background_task(block, handlers: dict, session_id: str = "") -> str:
    """启动后台任务，记录 session_id 用于结果路由"""
    global _bg_counter
    _bg_counter += 1
    bg_id = f"bg_{_bg_counter:04d}"
    command = block.input.get("command", block.name)

    def worker():
        handler = handlers.get(block.name)
        result = call_tool_handler(handler, block.input, block.name)
        trigger_hooks("PostToolUse", block, result)
        with background_lock:
            background_tasks[bg_id]["status"] = "completed"
            background_results[bg_id] = str(result)

    with background_lock:
        background_tasks[bg_id] = {
            "tool_use_id": block.id,
            "command": command,
            "status": "running",
            "session_id": session_id,
        }
    threading.Thread(target=worker, daemon=True).start()
    print(f"  \033[33m[background] {bg_id}: {str(command)[:60]}\033[0m")
    return bg_id


def collect_background_results(session_id: str = "") -> list[str]:
    """收集已完成的后台任务结果，按 session_id 过滤"""
    with background_lock:
        ready = [bg_id for bg_id, task in background_tasks.items()
                 if task["status"] == "completed"
                 and (not session_id or task.get("session_id", "") == session_id)]
    notifications = []
    for bg_id in ready:
        with background_lock:
            task = background_tasks.pop(bg_id)
            output = background_results.pop(bg_id, "")
        summary = output[:200] if len(output) > 200 else output
        notifications.append(
            f"<task_notification>\n"
            f"  <task_id>{bg_id}</task_id>\n"
            f"  <status>completed</status>\n"
            f"  <command>{task['command']}</command>\n"
            f"  <summary>{summary}</summary>\n"
            f"</task_notification>")
    return notifications


# ── Cron Scheduler ──

# Cron jobs are stored separately from conversation history. When a job fires,
# it becomes a scheduled prompt that is injected back into the same agent loop.
DURABLE_PATH = WORKDIR / ".scheduled_tasks.json"


@dataclass
class CronJob:
    id: str
    cron: str
    prompt: str
    recurring: bool
    durable: bool


scheduled_jobs: dict[str, CronJob] = {}
cron_queue: list[CronJob] = []
cron_lock = threading.Lock()
_last_fired: dict[str, str] = {}


def _cron_field_matches(field: str, value: int) -> bool:
    if field == "*":
        return True
    if field.startswith("*/"):
        step = int(field[2:])
        return step > 0 and value % step == 0
    if "," in field:
        return any(_cron_field_matches(part.strip(), value)
                   for part in field.split(","))
    if "-" in field:
        lo, hi = field.split("-", 1)
        return int(lo) <= value <= int(hi)
    return value == int(field)


def cron_matches(cron_expr: str, dt: datetime) -> bool:
    fields = cron_expr.strip().split()
    if len(fields) != 5:
        return False
    minute, hour, dom, month, dow = fields
    dow_val = (dt.weekday() + 1) % 7
    m = _cron_field_matches(minute, dt.minute)
    h = _cron_field_matches(hour, dt.hour)
    dom_ok = _cron_field_matches(dom, dt.day)
    month_ok = _cron_field_matches(month, dt.month)
    dow_ok = _cron_field_matches(dow, dow_val)
    if not (m and h and month_ok):
        return False
    if dom == "*" and dow == "*":
        return True
    if dom == "*":
        return dow_ok
    if dow == "*":
        return dom_ok
    return dom_ok or dow_ok


def _validate_cron_field(field: str, lo: int, hi: int) -> str | None:
    if field == "*":
        return None
    if field.startswith("*/"):
        step = field[2:]
        if not step.isdigit() or int(step) <= 0:
            return f"Invalid step: {field}"
        return None
    if "," in field:
        for part in field.split(","):
            err = _validate_cron_field(part.strip(), lo, hi)
            if err:
                return err
        return None
    if "-" in field:
        left, right = field.split("-", 1)
        if not left.isdigit() or not right.isdigit():
            return f"Invalid range: {field}"
        a, b = int(left), int(right)
        if a < lo or a > hi or b < lo or b > hi:
            return f"Range {field} out of bounds [{lo}-{hi}]"
        if a > b:
            return f"Range start > end: {field}"
        return None
    if not field.isdigit():
        return f"Invalid field: {field}"
    value = int(field)
    if value < lo or value > hi:
        return f"Value {value} out of bounds [{lo}-{hi}]"
    return None


def validate_cron(cron_expr: str) -> str | None:
    fields = cron_expr.strip().split()
    if len(fields) != 5:
        return f"Expected 5 fields, got {len(fields)}"
    bounds = [(0, 59), (0, 23), (1, 31), (1, 12), (0, 6)]
    names = ["minute", "hour", "day-of-month", "month", "day-of-week"]
    for field, (lo, hi), name in zip(fields, bounds, names):
        err = _validate_cron_field(field, lo, hi)
        if err:
            return f"{name}: {err}"
    return None


def save_durable_jobs():
    durable = [asdict(job) for job in scheduled_jobs.values() if job.durable]
    DURABLE_PATH.write_text(json.dumps(durable, indent=2))


def load_durable_jobs():
    if not DURABLE_PATH.exists():
        return
    try:
        for item in json.loads(DURABLE_PATH.read_text()):
            job = CronJob(**item)
            if not validate_cron(job.cron):
                scheduled_jobs[job.id] = job
    except Exception:
        pass


def schedule_job(cron: str, prompt: str,
                 recurring: bool = True, durable: bool = True) -> CronJob | str:
    err = validate_cron(cron)
    if err:
        return err
    job = CronJob(
        id=f"cron_{random.randint(0, 999999):06d}",
        cron=cron, prompt=prompt,
        recurring=recurring, durable=durable)
    with cron_lock:
        scheduled_jobs[job.id] = job
    if durable:
        save_durable_jobs()
    return job


def cancel_job(job_id: str) -> str:
    with cron_lock:
        job = scheduled_jobs.pop(job_id, None)
    if not job:
        return f"Job {job_id} not found"
    if job.durable:
        save_durable_jobs()
    return f"Cancelled {job_id}"


def cron_scheduler_loop():
    while True:
        time.sleep(1)
        now = datetime.now()
        marker = now.strftime("%Y-%m-%d %H:%M")
        with cron_lock:
            for job in list(scheduled_jobs.values()):
                try:
                    if cron_matches(job.cron, now) and _last_fired.get(job.id) != marker:
                        cron_queue.append(job)
                        _last_fired[job.id] = marker
                        if not job.recurring:
                            scheduled_jobs.pop(job.id, None)
                            if job.durable:
                                save_durable_jobs()
                except Exception as e:
                    print(f"  \033[31m[cron error] {job.id}: {e}\033[0m")


def consume_cron_queue() -> list[CronJob]:
    with cron_lock:
        fired = list(cron_queue)
        cron_queue.clear()
    return fired


def run_schedule_cron(cron: str, prompt: str,
                      recurring: bool = True, durable: bool = True) -> str:
    result = schedule_job(cron, prompt, recurring, durable)
    if isinstance(result, str):
        return f"Error: {result}"
    return f"Scheduled {result.id}: '{cron}' -> {prompt}"


def run_list_crons() -> str:
    with cron_lock:
        jobs = list(scheduled_jobs.values())
    if not jobs:
        return "No cron jobs."
    return "\n".join(
        f"  {job.id}: '{job.cron}' -> {job.prompt[:40]} "
        f"[{'recurring' if job.recurring else 'one-shot'}, "
        f"{'durable' if job.durable else 'session'}]"
        for job in jobs)


def run_cancel_cron(job_id: str) -> str:
    return cancel_job(job_id)


load_durable_jobs()
threading.Thread(target=cron_scheduler_loop, daemon=True).start()


# ── MCP System ──

# MCP is modeled as late-bound tools: connect first, then discovered server
# tools are merged into the normal tool pool with mcp__server__tool names.
class MCPClient:
    """Discovers and calls tools on an MCP server (mock for teaching)."""

    def __init__(self, name: str):
        self.name = name
        self.tools: list[dict] = []
        self._handlers: dict[str, callable] = {}

    def register(self, tool_defs: list[dict],
                 handlers: dict[str, callable]):
        self.tools = tool_defs
        self._handlers = handlers

    def call_tool(self, tool_name: str, args: dict) -> str:
        handler = self._handlers.get(tool_name)
        if not handler:
            return f"MCP error: unknown tool '{tool_name}'"
        try:
            return handler(**args)
        except Exception as e:
            return f"MCP error: {e}"


mcp_clients: dict[str, MCPClient] = {}

_DISALLOWED_CHARS = re.compile(r'[^a-zA-Z0-9_-]')


def normalize_mcp_name(name: str) -> str:
    """Replace non [a-zA-Z0-9_-] with underscore."""
    return _DISALLOWED_CHARS.sub('_', name)


def _mock_server_docs():
    client = MCPClient("docs")
    client.register(
        tool_defs=[
            {"name": "search", "description": "Search documentation. (readOnly)",
             "inputSchema": {"type": "object",
                             "properties": {"query": {"type": "string"}},
                             "required": ["query"]}},
            {"name": "get_version", "description": "Get API version. (readOnly)",
             "inputSchema": {"type": "object", "properties": {},
                             "required": []}},
        ],
        handlers={
            "search": lambda query: f"[docs] Found 3 results for '{query}'",
            "get_version": lambda: "[docs] API v2.1.0",
        })
    return client


def _mock_server_deploy():
    client = MCPClient("deploy")
    client.register(
        tool_defs=[
            {"name": "trigger",
             "description": "Trigger a deployment. (destructive — requires approval in real CC)",
             "inputSchema": {"type": "object",
                             "properties": {"service": {"type": "string"}},
                             "required": ["service"]}},
            {"name": "status", "description": "Check deployment status. (readOnly)",
             "inputSchema": {"type": "object",
                             "properties": {"service": {"type": "string"}},
                             "required": ["service"]}},
        ],
        handlers={
            "trigger": lambda service: f"[deploy] Triggered: {service}",
            "status": lambda service: f"[deploy] {service}: running (v1.4.2)",
        })
    return client


MOCK_SERVERS = {
    "docs": _mock_server_docs,
    "deploy": _mock_server_deploy,
}


def connect_mcp(name: str) -> str:
    if name in mcp_clients:
        return f"MCP server '{name}' already connected"
    factory = MOCK_SERVERS.get(name)
    if not factory:
        available = ", ".join(MOCK_SERVERS.keys())
        return f"Unknown server '{name}'. Available: {available}"
    mcp_client = factory()
    mcp_clients[name] = mcp_client
    tool_names = [t["name"] for t in mcp_client.tools]
    print(f"  \033[31m[mcp] connected: {name} → {tool_names}\033[0m")
    return (f"Connected to MCP server '{name}'. "
            f"Discovered {len(mcp_client.tools)} tools: {', '.join(tool_names)}")


def assemble_tool_pool() -> tuple[list[dict], dict]:
    """Merge builtin tools + all MCP tools into one pool."""
    tools = list(BUILTIN_TOOLS)
    handlers = dict(BUILTIN_HANDLERS)
    for server_name, mcp_client in mcp_clients.items():
        safe_server = normalize_mcp_name(server_name)
        for tool_def in mcp_client.tools:
            safe_tool = normalize_mcp_name(tool_def["name"])
            prefixed = f"mcp__{safe_server}__{safe_tool}"
            tools.append({
                "name": prefixed,
                "description": tool_def.get("description", ""),
                "input_schema": tool_def.get("inputSchema", {}),
            })
            handlers[prefixed] = (
                lambda *, c=mcp_client, t=tool_def["name"], **kw: c.call_tool(t, kw))
    return tools, handlers


# ── Lead Worktree Tools ──

def run_create_worktree(name: str, task_id: str = "") -> str:
    return create_worktree(name, task_id)

def run_remove_worktree(name: str, discard_changes: bool = False) -> str:
    return remove_worktree(name, discard_changes)

def run_keep_worktree(name: str) -> str:
    return keep_worktree(name)


# ── Basic tool handlers ──

def run_create_task(subject: str, description: str = "",
                    blockedBy: list[str] | None = None) -> str:
    task = create_task(subject, description, blockedBy)
    deps = f" (blockedBy: {', '.join(blockedBy)})" if blockedBy else ""
    print(f"  \033[34m[create] {task.subject}{deps}\033[0m")
    return f"Created {task.id}: {task.subject}{deps}"


def run_list_tasks() -> str:
    tasks = list_tasks()
    if not tasks:
        return "No tasks."
    return "\n".join(
        f"  {t.id}: {t.subject} [{t.status}]"
        + (f" (wt:{t.worktree})" if t.worktree else "")
        for t in tasks)


def run_get_task(task_id: str) -> str:
    try:
        return get_task_json(task_id)
    except FileNotFoundError:
        return f"Error: task {task_id} not found"

def run_claim_task(task_id: str) -> str:
    try:
        return claim_task(task_id, owner="agent")
    except FileNotFoundError:
        return f"Error: task {task_id} not found"

def run_complete_task(task_id: str) -> str:
    try:
        return complete_task(task_id)
    except FileNotFoundError:
        return f"Error: task {task_id} not found"

def run_spawn_teammate(name: str, role: str, prompt: str) -> str:
    return spawn_teammate_thread(name, role, prompt)

def run_send_message(to: str, content: str) -> str:
    BUS.send("lead", to, content)
    return f"Sent to {to}"

def run_check_inbox() -> str:
    msgs = consume_lead_inbox(route_protocol=True)
    if not msgs:
        return "(inbox empty)"
    lines = []
    for m in msgs:
        meta = m.get("metadata", {})
        req_id = meta.get("request_id", "")
        tag = f" [{m['type']} req:{req_id}]" if req_id else f" [{m['type']}]"
        lines.append(f"  [{m['from']}]{tag} {m['content'][:200]}")
    return "\n".join(lines)

def run_connect_mcp(name: str) -> str:
    return connect_mcp(name)


def run_file_tracker(purpose: str = "all", path_pattern: str = "",
                     session_id: str = "", task_id: str = "") -> str:
    """查询文件追踪表，按条件过滤并格式化输出"""
    entries = _FILE_TRACKER.query(purpose=purpose, path_pattern=path_pattern,
                                   session_id=session_id, task_id=task_id)
    if not entries:
        return "(no tracked files match the filter)"
    lines = []
    for e in sorted(entries, key=lambda x: x["path"]):
        sid = e.get("session_id", "")[:8] if e.get("session_id") else "-"
        tid = e.get("task_id", "")[:8] if e.get("task_id") else "-"
        ts = datetime.fromtimestamp(e.get("created_at", 0)).strftime("%m-%d %H:%M")
        status_icon = {"active": "●", "dormant": "○", "ghost": "◇", "deleted": "×"}.get(e.get("status"), "?")
        lines.append(f"  {status_icon} {e['path']}  purpose={e['purpose']:11s}  "
                     f"tool={e['tool']:12s}  session={sid}  task={tid}  created={ts}")
    return "\n".join(lines)


def run_cleanup_temp(session_id: str = "", task_id: str = "",
                     dry_run: bool = False) -> str:
    """清理临时文件，返回清理报告"""
    report = _FILE_TRACKER.cleanup(session_id=session_id, task_id=task_id, dry_run=dry_run)
    if not report:
        return "(no temporary files to clean)"
    deleted = [r for r in report if r["action"] == "deleted"]
    parts = []
    if dry_run:
        parts.append(f"[DRY RUN] Would delete {len(deleted)} temporary file(s):")
        for r in deleted:
            parts.append(f"  - {r['path']} -> {r.get('placeholder', '')}")
    else:
        parts.append(f"Cleaned {len(deleted)} temporary file(s):")
        for r in deleted:
            placeholder = Path(r.get("placeholder", ""))
            marker = f"  placeholder: {placeholder.name}" if placeholder.name else ""
            parts.append(f"  - {r['path']}{marker}")
    return "\n".join(parts)


def run_mark_persistent(path: str) -> str:
    """将临时文件升级为持久文件"""
    return _FILE_TRACKER.upgrade_persistent(path)


# ── Tool Definitions ──

# The model sees tool schemas; Python executes handlers. S20 keeps both tables
# explicit so every added capability is visible in one place.
BUILTIN_TOOLS = [
    {"name": "bash", "description": "Run a shell command.",
     "input_schema": {"type": "object",
                      "properties": {"command": {"type": "string"},
                                     "run_in_background": {"type": "boolean"}},
                      "required": ["command"]}},
    {"name": "read_file", "description": "Read file contents.",
     "input_schema": {"type": "object",
                      "properties": {"path": {"type": "string"},
                                     "limit": {"type": "integer"},
                                     "offset": {"type": "integer"}},
                      "required": ["path"]}},
    {"name": "write_file", "description": "Write content to a file.",
     "input_schema": {"type": "object",
                      "properties": {"path": {"type": "string"},
                                     "content": {"type": "string"}},
                      "required": ["path", "content"]}},
    {"name": "edit_file", "description": "Replace exact text in a file once.",
     "input_schema": {"type": "object",
                      "properties": {"path": {"type": "string"},
                                     "old_text": {"type": "string"},
                                     "new_text": {"type": "string"}},
                      "required": ["path", "old_text", "new_text"]}},
    {"name": "glob", "description": "Find files matching a glob pattern.",
     "input_schema": {"type": "object",
                      "properties": {"pattern": {"type": "string"}},
                      "required": ["pattern"]}},
    {"name": "grep",
     "description": "Search file contents by regex. Prefer over `bash grep`/`bash rg`. "
                    "Returns 'file:line: content' per match.",
     "input_schema": {"type": "object",
                      "properties": {
                          "pattern": {"type": "string",
                                      "description": "Regex pattern (re.search syntax)."},
                          "path": {"type": "string",
                                   "description": "Relative file or dir to search. Default '.'."},
                          "glob": {"type": "string",
                                   "description": "Filename glob filter, e.g. '*.py'. Default '*'."},
                          "case_insensitive": {"type": "boolean"},
                          "context_lines": {"type": "integer",
                                            "description": "Lines of context before/after match."},
                          "max_matches": {"type": "integer",
                                          "description": "Cap on result count. Default 100."}},
                      "required": ["pattern"]}},
    {"name": "ls",
     "description": "List directory contents. Prefer over `bash ls`. "
                    "Refuses paths outside the workspace.",
     "input_schema": {"type": "object",
                      "properties": {"path": {"type": "string",
                                              "description": "Relative dir path. Default '.'."}},
                      "required": []}},
    {"name": "delete_file",
     "description": "Delete one or more files. Prefer over `bash rm`. "
                    "Refuses missing paths, directories, and out-of-workspace paths.",
     "input_schema": {"type": "object",
                      "properties": {"paths": {"type": "array",
                                               "items": {"type": "string"},
                                               "description": "Relative file paths to delete."}},
                      "required": ["paths"]}},
    {"name": "diagnostics",
     "description": "Run Python syntax diagnostics on .py files via py_compile. "
                    "Use after editing Python to verify syntax before declaring done.",
     "input_schema": {"type": "object",
                      "properties": {"paths": {"type": "array",
                                               "items": {"type": "string"},
                                               "description": "Relative .py paths. "
                                                              "Omit to scan root *.py."}},
                      "required": []}},
    {"name": "web_search",
     "description": "Search the web (DuckDuckGo). OPT-IN: use only when user explicitly "
                    "asks to go online. Always cite sources in the response.",
     "input_schema": {"type": "object",
                      "properties": {"query": {"type": "string"},
                                     "num_results": {"type": "integer",
                                                     "description": "Max results. Default 5."}},
                      "required": ["query"]}},
    {"name": "web_fetch",
     "description": "Fetch a URL and return cleaned text (HTML stripped). OPT-IN: "
                    "use only when user explicitly asks to go online. "
                    "Fails on authenticated/private URLs.",
     "input_schema": {"type": "object",
                      "properties": {"url": {"type": "string",
                                              "description": "http:// or https:// URL."},
                                     "max_chars": {"type": "integer",
                                                   "description": "Truncate length. Default 20000."}},
                      "required": ["url"]}},
    {"name": "todo_write",
     "description": "Create and manage a task list for the current session.",
     "input_schema": {"type": "object",
                      "properties": {"todos": {"type": "array",
                          "items": {"type": "object",
                                    "properties": {
                                        "content": {"type": "string"},
                                        "status": {"type": "string",
                                                   "enum": ["pending", "in_progress", "completed"]}},
                                    "required": ["content", "status"]}}},
                      "required": ["todos"]}},
    {"name": "task",
     "description": "Launch a focused subagent. Returns only its final summary.",
     "input_schema": {"type": "object",
                      "properties": {"description": {"type": "string"}},
                      "required": ["description"]}},
    {"name": "load_skill",
     "description": "Load the full content of a skill by name.",
     "input_schema": {"type": "object",
                      "properties": {"name": {"type": "string"}},
                      "required": ["name"]}},
    {"name": "compact",
     "description": "Summarize earlier conversation and continue with compacted context.",
     "input_schema": {"type": "object",
                      "properties": {"focus": {"type": "string"}},
                      "required": []}},
    {"name": "create_task", "description": "Create a task.",
     "input_schema": {"type": "object",
                      "properties": {"subject": {"type": "string"},
                                     "description": {"type": "string"},
                                     "blockedBy": {"type": "array",
                                                   "items": {"type": "string"}}},
                      "required": ["subject"]}},
    {"name": "list_tasks", "description": "List all tasks.",
     "input_schema": {"type": "object", "properties": {}, "required": []}},
    {"name": "get_task", "description": "Get full task details.",
     "input_schema": {"type": "object",
                      "properties": {"task_id": {"type": "string"}},
                      "required": ["task_id"]}},
    {"name": "claim_task", "description": "Claim a pending task.",
     "input_schema": {"type": "object",
                      "properties": {"task_id": {"type": "string"}},
                      "required": ["task_id"]}},
    {"name": "complete_task", "description": "Complete an in-progress task.",
     "input_schema": {"type": "object",
                      "properties": {"task_id": {"type": "string"}},
                      "required": ["task_id"]}},
    {"name": "schedule_cron",
     "description": ("Schedule a cron job. cron is 5-field: min hour dom "
                     "month dow. For one-shot reminders, compute the target "
                     "minute and set recurring=false."),
     "input_schema": {"type": "object",
                      "properties": {"cron": {"type": "string"},
                                     "prompt": {"type": "string"},
                                     "recurring": {"type": "boolean"},
                                     "durable": {"type": "boolean"}},
                      "required": ["cron", "prompt"]}},
    {"name": "list_crons", "description": "List registered cron jobs.",
     "input_schema": {"type": "object", "properties": {}, "required": []}},
    {"name": "cancel_cron", "description": "Cancel a cron job by ID.",
     "input_schema": {"type": "object",
                      "properties": {"job_id": {"type": "string"}},
                      "required": ["job_id"]}},
    {"name": "spawn_teammate", "description": "Spawn an autonomous teammate.",
     "input_schema": {"type": "object",
                      "properties": {"name": {"type": "string"},
                                     "role": {"type": "string"},
                                     "prompt": {"type": "string"}},
                      "required": ["name", "role", "prompt"]}},
    {"name": "send_message", "description": "Send message to a teammate.",
     "input_schema": {"type": "object",
                      "properties": {"to": {"type": "string"},
                                     "content": {"type": "string"}},
                      "required": ["to", "content"]}},
    {"name": "check_inbox",
     "description": "Check inbox for messages and protocol responses.",
     "input_schema": {"type": "object", "properties": {}, "required": []}},
    {"name": "request_shutdown",
     "description": "Request a teammate to shut down.",
     "input_schema": {"type": "object",
                      "properties": {"teammate": {"type": "string"}},
                      "required": ["teammate"]}},
    {"name": "request_plan",
     "description": "Ask a teammate to submit a plan.",
     "input_schema": {"type": "object",
                      "properties": {"teammate": {"type": "string"},
                                     "task": {"type": "string"}},
                      "required": ["teammate", "task"]}},
    {"name": "review_plan",
     "description": "Approve or reject a submitted plan.",
     "input_schema": {"type": "object",
                      "properties": {"request_id": {"type": "string"},
                                     "approve": {"type": "boolean"},
                                     "feedback": {"type": "string"}},
                      "required": ["request_id", "approve"]}},
    {"name": "create_worktree",
     "description": "Create an isolated git worktree.",
     "input_schema": {"type": "object",
                      "properties": {"name": {"type": "string"},
                                     "task_id": {"type": "string"}},
                      "required": ["name"]}},
    {"name": "remove_worktree",
     "description": "Remove a worktree. Refuses if changes exist.",
     "input_schema": {"type": "object",
                      "properties": {"name": {"type": "string"},
                                     "discard_changes": {"type": "boolean"}},
                      "required": ["name"]}},
    {"name": "keep_worktree",
     "description": "Keep a worktree for manual review.",
     "input_schema": {"type": "object",
                      "properties": {"name": {"type": "string"}},
                      "required": ["name"]}},
    {"name": "connect_mcp",
     "description": "Connect to an MCP server (docs, deploy) and discover tools.",
     "input_schema": {"type": "object",
                      "properties": {"name": {"type": "string"}},
                      "required": ["name"]}},
]

BUILTIN_HANDLERS = {
    "bash": run_bash, "read_file": run_read, "write_file": run_write,
    "edit_file": run_edit, "glob": run_glob,
    "grep": run_grep, "ls": run_ls, "delete_file": run_delete_file,
    "diagnostics": run_diagnostics,
    "web_search": run_web_search, "web_fetch": run_web_fetch,
    "todo_write": run_todo_write, "task": spawn_subagent,
    "load_skill": load_skill,
    "create_task": run_create_task, "list_tasks": run_list_tasks,
    "get_task": run_get_task,
    "claim_task": run_claim_task, "complete_task": run_complete_task,
    "schedule_cron": run_schedule_cron,
    "list_crons": run_list_crons,
    "cancel_cron": run_cancel_cron,
    "spawn_teammate": run_spawn_teammate,
    "send_message": run_send_message, "check_inbox": run_check_inbox,
    "request_shutdown": run_request_shutdown,
    "request_plan": run_request_plan, "review_plan": run_review_plan,
    "create_worktree": run_create_worktree,
    "remove_worktree": run_remove_worktree,
    "keep_worktree": run_keep_worktree,
    "connect_mcp": run_connect_mcp,
    "file_tracker": run_file_tracker,
    "cleanup_temp": run_cleanup_temp,
    "mark_persistent": run_mark_persistent,
}


# ── Context ──

MEMORY_DIR = WORKDIR / ".memory"
MEMORY_INDEX = MEMORY_DIR / "MEMORY.md"


def update_context(context: dict, messages: list) -> dict:
    memories = ""
    if MEMORY_INDEX.exists():
        memories = MEMORY_INDEX.read_text()[:2000]
    return {
        "memories": memories,
        "connected_mcp": list(mcp_clients.keys()),
        "active_teammates": list(active_teammates.keys()),
    }


# ── Session Storage ──

# 会话存储根目录：所有会话 JSONL 文件与索引均存放于此
SESSIONS_DIR = WORKDIR / ".sessions"
SESSIONS_DIR.mkdir(exist_ok=True)


# 根据会话 ID 拼接对应的 JSONL 文件路径
def session_file_path(session_id: str) -> Path:
    """返回指定会话的 JSONL 文件路径"""
    return SESSIONS_DIR / f"{session_id}.jsonl"


# 向会话 JSONL 追加一条消息，保证实时落盘以便崩溃恢复
def append_to_jsonl(session_id: str, message: dict):
    """向指定会话的 JSONL 文件追加写入一条消息（实时落盘）"""
    path = session_file_path(session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(message, default=str, ensure_ascii=False) + "\n")


# 将内存中的消息转换为 JSONL 格式并追加写入文件
def log_message_to_jsonl(session_id: str, msg: dict, model: str = ""):
    """将内存中的消息转换为 JSONL 格式并追加写入文件

    内存格式：{"role": "user"/"assistant", "content": ...}
    JSONL格式：{"type": "user"/"assistant"/"tool_result", "content": ..., "timestamp": ..., "model": ...}
    """
    timestamp = datetime.now().isoformat()
    role = msg.get("role", "unknown")
    content = msg.get("content")

    if role == "user" and isinstance(content, list):
        # user 消息的 content 是 list 时，可能包含 tool_result 块
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_result":
                # tool_result 独立成行
                jsonl_msg = {
                    "type": "tool_result",
                    "tool_use_id": block.get("tool_use_id", ""),
                    "content": str(block.get("content", "")),
                    "timestamp": timestamp,
                }
                append_to_jsonl(session_id, jsonl_msg)
            elif isinstance(block, dict) and block.get("type") == "text":
                jsonl_msg = {
                    "type": "user",
                    "content": block.get("text", ""),
                    "timestamp": timestamp,
                }
                append_to_jsonl(session_id, jsonl_msg)
        # 同时记录整个 user 消息（用于恢复时重建完整结构）
        append_to_jsonl(session_id, {
            "type": "user",
            "content": str(content)[:200] if isinstance(content, list) else str(content),
            "timestamp": timestamp,
        })
    elif role == "assistant":
        jsonl_msg = {
            "type": "assistant",
            "content": content,
            "timestamp": timestamp,
            "model": model,
        }
        append_to_jsonl(session_id, jsonl_msg)
    else:
        jsonl_msg = {
            "type": role,
            "content": content,
            "timestamp": timestamp,
        }
        append_to_jsonl(session_id, jsonl_msg)


# 从 JSONL 文件逐行读取并还原为 history 消息列表
def load_session_jsonl(session_id: str) -> list:
    """读取指定会话的 JSONL 文件，恢复为 history 列表"""
    path = session_file_path(session_id)
    if not path.exists():
        return []
    history = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
                history.append(msg)
            except json.JSONDecodeError:
                continue
    return history


# 读取会话索引文件，缺失或损坏时返回空索引骨架
def load_index() -> dict:
    """读取 .sessions/index.json 索引文件"""
    index_path = SESSIONS_DIR / "index.json"
    if not index_path.exists():
        return {"version": 1, "sessions": []}
    try:
        return json.loads(index_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"version": 1, "sessions": []}


# 将索引字典序列化写入 index.json 文件
def save_index(index: dict):
    """写入 .sessions/index.json 索引文件"""
    index_path = SESSIONS_DIR / "index.json"
    index_path.write_text(
        json.dumps(index, indent=2, ensure_ascii=False),
        encoding="utf-8")


# 在索引中新增一条会话记录，包含 fork 关系等元数据
def add_session_to_index(session_id: str, title: str, created_at: str,
                         forked_from: str = None, forked_at_message: int = None):
    """向索引中添加一条新会话记录"""
    index = load_index()
    entry = {
        "id": session_id,
        "title": title,
        "created_at": created_at,
        "updated_at": created_at,
        "message_count": 0,
        "file_size": 0,
        "has_compact_boundary": False,
        "forked_from": forked_from,
        "forked_at_message": forked_at_message,
    }
    index["sessions"].append(entry)
    save_index(index)


# 按字段更新索引中某条会话记录（如消息数、文件大小、更新时间等）
def update_session_in_index(session_id: str, **fields):
    """更新索引中指定会话的字段"""
    index = load_index()
    for entry in index["sessions"]:
        if entry["id"] == session_id:
            entry.update(fields)
            break
    save_index(index)


# 从索引中删除指定会话记录（配合 JSONL 文件清理使用）
def remove_session_from_index(session_id: str):
    """从索引中移除指定会话记录"""
    index = load_index()
    index["sessions"] = [s for s in index["sessions"] if s["id"] != session_id]
    save_index(index)


# 列出全部会话，按最近更新时间降序排列
def list_sessions() -> list:
    """返回所有会话列表（按 updated_at 降序）"""
    index = load_index()
    sessions = sorted(index["sessions"],
                      key=lambda s: s.get("updated_at", ""),
                      reverse=True)
    return sessions


# 取最近更新的会话 ID，便于启动时自动恢复上次会话
def get_latest_session_id() -> str | None:
    """返回最近更新的会话 ID（排除当前会话）"""
    sessions = list_sessions()
    return sessions[0]["id"] if sessions else None


# 会话管理器：以间接引用层持有当前活动会话的 history/context/session_id，
# 使 cron 守护线程能在会话切换后读取到最新引用
class SessionManager:
    """会话管理器：维护当前活动会话的 history/context/session_id，
    提供间接引用层，使 cron 守护线程能感知会话切换"""

    def __init__(self):
        # 当前会话的消息列表（直接持有引用，切换时整体替换）
        self._history: list = []          # 当前会话的消息列表
        # 当前会话的上下文字典（记忆、MCP、队友等聚合信息）
        self._context: dict = {}          # 当前会话的上下文
        # 当前活动会话的唯一标识
        self._session_id: str = ""        # 当前会话 ID
        # 标题是否已生成标记：新会话为 False，首轮对话后触发；加载/切换的会话为 True
        self._title_generated: bool = False

    # 通过 property 暴露 history，确保每次访问都读取最新引用
    @property
    def history(self) -> list:
        """读取当前会话的 history（每次调用都读最新引用）"""
        return self._history

    # 通过 property 暴露 context，确保 cron 线程读到切换后的上下文
    @property
    def context(self) -> dict:
        """读取当前会话的 context（每次调用都读最新引用）"""
        return self._context

    # 通过 property 暴露 session_id，供日志和索引查询使用
    @property
    def session_id(self) -> str:
        """读取当前会话 ID"""
        return self._session_id

    # 开启全新会话：重置 history 并基于空消息重建 context
    def start_new(self, session_id: str):
        """创建新会话：初始化空的 history 和 context"""
        self._session_id = session_id
        self._history = []
        self._context = update_context({}, [])
        self._title_generated = False  # 新会话需要首轮对话后生成标题

    # 从已落盘的 history 恢复会话状态（重启后继续对话）
    def load(self, session_id: str, history: list, context: dict):
        """加载已有会话：从 JSONL 恢复 history，重建 context"""
        self._session_id = session_id
        self._history = history
        self._context = context
        self._title_generated = True  # 已加载的会话不需要再生成标题

    # 切换到另一个会话：整体替换内部引用，必须在 agent_lock 内调用以保证线程安全
    def switch_to(self, session_id: str, history: list, context: dict):
        """切换会话：替换内部引用（必须在 agent_lock 内调用）"""
        self._session_id = session_id
        self._history = history
        self._context = context
        self._title_generated = True  # 切换到的会话不需要再生成标题


# ── Agent Loop ──

rounds_since_todo = 0
agent_lock = threading.Lock()


def prepare_context(messages: list, session_id: str = "") -> list:
    """上下文预算管线：每轮 LLM 调用前压缩历史，session_id 用于写入压缩边界"""
    # Every LLM turn enters through the same context budget pipeline.
    messages[:] = tool_result_budget(messages)
    messages[:] = snip_compact(messages)
    messages[:] = micro_compact(messages)
    if estimate_size(messages) > CONTEXT_LIMIT:
        messages[:] = compact_history(messages, session_id)
    return messages


def build_user_content(results: list[dict], session_id: str = "") -> list[dict]:
    # Tool results and completed background notifications are both returned to
    # the model as user-side content, matching the tool_result feedback loop.
    content = list(results)
    for note in collect_background_results(session_id):
        content.append({"type": "text", "text": note})
    return content


def inject_background_notifications(messages: list, session_id: str = ""):
    """注入已完成的后台任务通知到消息列表，按 session_id 过滤"""
    notes = collect_background_results(session_id)
    if notes:
        messages.append({"role": "user", "content": [
            {"type": "text", "text": note} for note in notes]})


def call_llm(messages: list, context: dict, tools: list,
             state: RecoveryState, max_tokens: int):
    system = assemble_system_prompt(context)
    return with_retry(
        lambda: client.messages.create(
            model=state.current_model,
            system=system,
            messages=messages,
            tools=tools,
            max_tokens=max_tokens),
        state)


def agent_loop(messages: list, context: dict, session_id: str = ""):
    global rounds_since_todo, _current_session_id
    _current_session_id = session_id
    tools, handlers = assemble_tool_pool()
    state = RecoveryState()
    max_tokens = DEFAULT_MAX_TOKENS

    while True:
        # One cycle: inject scheduled/background work, prepare context, call
        # the model, execute tool_use blocks, append tool_results, repeat.
        fired = consume_cron_queue()
        for job in fired:
            messages.append({"role": "user",
                             "content": f"[Scheduled] {job.prompt}"})
            if session_id:
                log_message_to_jsonl(session_id, messages[-1])
            print(f"  \033[35m[cron inject] {job.prompt[:60]}\033[0m")

        inject_background_notifications(messages, session_id)

        if rounds_since_todo >= 3:
            messages.append({"role": "user",
                             "content": "<reminder>Update your todos.</reminder>"})
            if session_id:
                log_message_to_jsonl(session_id, messages[-1])
            rounds_since_todo = 0

        prepare_context(messages, session_id)
        context = update_context(context, messages)
        tools, handlers = assemble_tool_pool()

        try:
            response = call_llm(messages, context, tools, state, max_tokens)
        except AllModelsExhaustedError as e:
            # 所有模型免费额度都已耗尽：给出明确的"无 token"提示并优雅退出
            notice = ("[无可用模型] 所有模型的免费额度均已耗尽，"
                      "无法继续调用。请前往阿里云百炼控制台 "
                      "(https://bailian.console.aliyun.com/) 充值或更换 API Key 后重试。")
            messages.append({"role": "assistant", "content": [
                {"type": "text", "text": notice}]})
            if session_id:
                log_message_to_jsonl(session_id, messages[-1])
            print(f"\033[31m[无token] {e}\033[0m")
            print(f"\033[31m[无token] 已耗尽模型："
                  f"{', '.join(state.model_pool.exhausted)}\033[0m")
            return
        except Exception as e:
            if is_prompt_too_long_error(e) and not state.has_attempted_reactive_compact:
                messages[:] = reactive_compact(messages)
                state.has_attempted_reactive_compact = True
                continue
            messages.append({"role": "assistant", "content": [
                {"type": "text", "text": f"[Error] {type(e).__name__}: {e}"}]})
            if session_id:
                log_message_to_jsonl(session_id, messages[-1])
            return

        if response.stop_reason == "max_tokens":
            if not state.has_escalated:
                max_tokens = ESCALATED_MAX_TOKENS
                state.has_escalated = True
                print(f"  \033[33m[max_tokens] retry with {max_tokens}\033[0m")
                continue
            messages.append({"role": "assistant", "content": response.content})
            if session_id:
                log_message_to_jsonl(session_id, messages[-1], state.current_model)
            if state.recovery_count < MAX_RECOVERY_RETRIES:
                messages.append({"role": "user", "content": CONTINUATION_PROMPT})
                if session_id:
                    log_message_to_jsonl(session_id, messages[-1])
                state.recovery_count += 1
                continue
            return

        max_tokens = DEFAULT_MAX_TOKENS
        state.has_escalated = False
        messages.append({"role": "assistant", "content": response.content})
        if session_id:
            log_message_to_jsonl(session_id, messages[-1], state.current_model)
        if not has_tool_use(response.content):
            trigger_hooks("Stop", messages)
            return

        results = []
        compacted_now = False
        for block in response.content:
            if block.type != "tool_use":
                continue
            print(f"\033[36m> {block.name}\033[0m")

            if block.name == "compact":
                messages[:] = compact_history(messages, session_id)
                messages.append({"role": "user",
                                 "content": "[Compacted. Continue with summarized context.]"})
                if session_id:
                    log_message_to_jsonl(session_id, messages[-1])
                compacted_now = True
                break

            blocked = trigger_hooks("PreToolUse", block)
            if blocked:
                results.append({"type": "tool_result",
                                "tool_use_id": block.id,
                                "content": str(blocked)})
                continue

            if should_run_background(block.name, block.input):
                bg_id = start_background_task(block, handlers, session_id)
                output = (f"[Background task {bg_id} started] "
                          "Result will arrive as a task_notification.")
                results.append({"type": "tool_result",
                                "tool_use_id": block.id,
                                "content": output})
                continue

            handler = handlers.get(block.name)
            output = call_tool_handler(handler, block.input, block.name)
            trigger_hooks("PostToolUse", block, output)
            print(str(output)[:300])

            if block.name == "todo_write":
                rounds_since_todo = 0
            else:
                rounds_since_todo += 1

            results.append({"type": "tool_result",
                            "tool_use_id": block.id, "content": output})

        if compacted_now:
            continue

        messages.append({"role": "user", "content": build_user_content(results, session_id)})
        if session_id:
            log_message_to_jsonl(session_id, messages[-1])


def print_turn_assistants(messages: list, turn_start: int):
    for msg in messages[turn_start:]:
        if msg.get("role") != "assistant":
            continue
        for block in msg.get("content", []):
            if getattr(block, "type", None) == "text":
                terminal_print(block.text)


def cron_autorun_loop(sm: SessionManager):
    """cron 守护线程：通过 SessionManager 访问当前会话的 history/context"""
    while True:
        time.sleep(1)
        fired = consume_cron_queue()
        if not fired:
            continue
        with agent_lock:
            turn_start = len(sm.history)
            for job in fired:
                msg = {"role": "user", "content": f"[Scheduled] {job.prompt}"}
                sm.history.append(msg)
                if sm.session_id:
                    log_message_to_jsonl(sm.session_id, msg)
                terminal_print(
                    f"  \033[35m[cron auto] {job.prompt[:60]}\033[0m")
            agent_loop(sm.history, sm.context, sm.session_id)
            sm._context = update_context(sm.context, sm.history)
            print_turn_assistants(sm.history, turn_start)


# 异步调用 LLM 生成会话标题，失败时回退到首条用户消息前 30 字符
def generate_title(session_id: str, first_user_msg: str, first_assistant_msg: str):
    """异步调用 LLM 生成会话标题，失败时回退到首条用户消息前 30 字符

    在后台线程中执行，不阻塞主循环。生成成功后更新 index.json。
    """
    try:
        prompt = (
            "根据以下对话生成一个简短的会话标题（不超过20个字，不要标点符号，只输出标题文字）：\n\n"
            f"用户: {first_user_msg[:200]}\n"
            f"助手: {first_assistant_msg[:200]}\n\n"
            "标题："
        )
        response = client.messages.create(
            model=MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=50)
        title = extract_text(response.content).strip()
        if title:
            title = title[:30]
            update_session_in_index(session_id, title=title)
            terminal_print(f"\033[36m[session] 会话标题已生成: {title}\033[0m")
        else:
            # 空返回，回退
            fallback = first_user_msg[:30]
            update_session_in_index(session_id, title=fallback)
    except Exception as e:
        # LLM 调用失败，回退到首条用户消息前 30 字符
        fallback = first_user_msg[:30]
        update_session_in_index(session_id, title=fallback)
        terminal_print(f"\033[33m[session] 标题生成失败，使用回退标题: {fallback}\033[0m")


# 处理 CLI 会话管理命令（/new /sessions /resume /rename /branch /help），返回 True 表示已处理
def handle_cli_command(query: str, sm: SessionManager) -> bool:
    """处理 CLI 会话管理命令，返回 True 表示已处理（主循环应 continue）"""
    parts = query.strip().split(maxsplit=1)
    cmd = parts[0].lower()
    arg = parts[1] if len(parts) > 1 else ""

    if cmd == "/new":
        # 保存当前会话，创建新会话，并暂停当前会话临时文件的计时
        with agent_lock:
            if len(sm.history) > 0:
                update_session_in_index(
                    sm.session_id,
                    updated_at=datetime.now().isoformat(),
                    message_count=len(sm.history),
                    file_size=session_file_path(sm.session_id).stat().st_size if session_file_path(sm.session_id).exists() else 0)
            # 暂停当前会话的临时文件计时
            deactivated = _FILE_TRACKER.on_session_deactivate(sm.session_id)
            if deactivated:
                print(f"  \033[33m[file-tracker] {len(deactivated)} temp file(s) paused for session {sm.session_id[:8]}\033[0m")
            new_id = str(uuid.uuid4())
            sm.start_new(new_id)
            now = datetime.now().isoformat()
            add_session_to_index(new_id, "新会话", now)
        print(f"\033[36m[session] 新会话已创建: {new_id[:8]}\033[0m")
        return True

    elif cmd == "/sessions":
        # 列出所有历史会话
        sessions = list_sessions()
        if not sessions:
            print("\033[33m[session] 暂无历史会话\033[0m")
            return True
        print(f"\033[36m[session] 共 {len(sessions)} 个会话:\033[0m")
        for i, s in enumerate(sessions, 1):
            sid = s["id"][:8]
            title = s.get("title", "无标题")[:30]
            count = s.get("message_count", 0)
            updated = s.get("updated_at", "")[:19]
            fork = ""
            if s.get("forked_from"):
                fork = f" (fork from {s['forked_from'][:8]})"
            current = " ← 当前" if s["id"] == sm.session_id else ""
            print(f"  {i}. [{sid}] {title} ({count} msgs, {updated}){fork}{current}")
        return True

    elif cmd == "/resume":
        # 恢复指定会话或最近会话
        target_id = arg.strip() if arg.strip() else None
        with agent_lock:
            # 保存当前会话
            if len(sm.history) > 0:
                update_session_in_index(
                    sm.session_id,
                    updated_at=datetime.now().isoformat(),
                    message_count=len(sm.history),
                    file_size=session_file_path(sm.session_id).stat().st_size if session_file_path(sm.session_id).exists() else 0)

            if target_id:
                # 尝试匹配完整 ID 或前缀
                sessions = list_sessions()
                matched = None
                for s in sessions:
                    if s["id"] == target_id or s["id"].startswith(target_id):
                        matched = s["id"]
                        break
                if not matched:
                    print(f"\033[31m[session] 未找到会话: {target_id}\033[0m")
                    return True
                target_id = matched
            else:
                # 恢复最近的会话（排除当前会话）
                sessions = list_sessions()
                target_id = None
                for s in sessions:
                    if s["id"] != sm.session_id:
                        target_id = s["id"]
                        break
                if not target_id:
                    print("\033[33m[session] 没有可恢复的历史会话\033[0m")
                    return True

            # 加载目标会话
            history = load_session_jsonl(target_id)
            context = update_context({}, history)
            sm.switch_to(target_id, history, context)
            # 恢复该会话临时文件的计时
            restored = _FILE_TRACKER.on_session_activate(target_id)
            ghost_entries = [e for e in _FILE_TRACKER.query(session_id=target_id)
                             if e.get("status") == "ghost"]
            print(f"\033[36m[session] 已恢复会话: {target_id[:8]} ({len(history)} 条消息)\033[0m")
            if restored:
                print(f"  \033[32m[file-tracker] {len(restored)} temp file(s) resumed for session {target_id[:8]}\033[0m")
            if ghost_entries:
                print(f"  \033[33m[file-tracker] {len(ghost_entries)} temp file(s) missing (ghost) for session {target_id[:8]}\033[0m")
                for g in ghost_entries:
                    print(f"    ◇ {g['path']}  reason={g.get('ghost_reason', '?')}")
        return True

    elif cmd == "/rename":
        # 重命名当前会话
        if not arg.strip():
            print("\033[33m[session] 用法: /rename <新标题>\033[0m")
            return True
        new_title = arg.strip()
        update_session_in_index(sm.session_id, title=new_title)
        print(f"\033[36m[session] 会话已重命名为: {new_title}\033[0m")
        return True

    elif cmd == "/branch":
        # 分支当前会话
        with agent_lock:
            if len(sm.history) == 0:
                print("\033[33m[session] 当前会话为空，无法分支\033[0m")
                return True

            # 确保当前 JSONL 完整（flush 已由实时追加写保证）
            src_path = session_file_path(sm.session_id)
            if not src_path.exists():
                print("\033[31m[session] 当前会话 JSONL 文件不存在\033[0m")
                return True

            # 记录原会话 ID（切换后 sm.session_id 会变）
            original_session_id = sm.session_id

            # 生成新会话 ID
            new_id = str(uuid.uuid4())
            dst_path = session_file_path(new_id)

            # 物理复制 JSONL 文件
            shutil.copyfile(src_path, dst_path)

            # 在内存中复制 history（浅拷贝）
            new_history = list(sm.history)
            new_context = update_context({}, new_history)

            # 记录分支信息
            fork_msg_count = len(sm.history)
            now = datetime.now().isoformat()
            branch_title = arg.strip() if arg.strip() else f"分支({sm.session_id[:8]})"
            add_session_to_index(new_id, branch_title, now,
                                 forked_from=sm.session_id,
                                 forked_at_message=fork_msg_count)
            update_session_in_index(new_id,
                                    message_count=fork_msg_count,
                                    file_size=dst_path.stat().st_size)

            # 切换到新会话
            sm.switch_to(new_id, new_history, new_context)

        print(f"\033[36m[session] 已创建分支: {new_id[:8]} ({branch_title})")
        print(f"[session] 来源: {original_session_id[:8]}, 复制 {fork_msg_count} 条消息\033[0m")
        return True

    elif cmd in ("/help", "/h", "/?"):
        # 显示帮助
        print("\033[36m[session] 可用命令:")
        print("  /new              创建新会话")
        print("  /sessions         列出所有历史会话")
        print("  /resume [id]      恢复指定会话（无参数则恢复最近的）")
        print("  /rename <title>   重命名当前会话")
        print("  /branch [title]   分支当前会话")
        print("  /help             显示此帮助\033[0m")
        return True

    else:
        print(f"\033[33m[session] 未知命令: {cmd}。输入 /help 查看可用命令\033[0m")
        return True


if __name__ == "__main__":
    CLI_ACTIVE = True
    print("s20: comprehensive agent")
    print("Enter a question, press Enter to send. Type q to quit.")
    print("Commands: /new /sessions /resume /rename /branch\n")

    # 初始化会话管理器
    sm = SessionManager()
    new_session_id = str(uuid.uuid4())
    sm.start_new(new_session_id)
    now = datetime.now().isoformat()
    add_session_to_index(new_session_id, "新会话", now)
    print(f"[session] 新会话已创建: {new_session_id[:8]}")

    # 启动 cron 守护线程（传入 SessionManager）
    threading.Thread(target=cron_autorun_loop,
                     args=(sm,), daemon=True).start()

    while True:
        try:
            query = input(PROMPT)
        except (EOFError, KeyboardInterrupt):
            break
        if query.strip().lower() in ("q", "exit", ""):
            # 退出前清理当前会话临时文件并更新索引
            if len(sm.history) > 0:
                update_session_in_index(sm.session_id,
                                        updated_at=datetime.now().isoformat(),
                                        message_count=len(sm.history),
                                        file_size=session_file_path(sm.session_id).stat().st_size if session_file_path(sm.session_id).exists() else 0)
            # 清理当前会话的临时文件
            cleanup_report = _FILE_TRACKER.cleanup(session_id=sm.session_id)
            if cleanup_report:
                print(f"\033[33m[file-tracker] 退出时清理了 {len(cleanup_report)} 个临时文件\033[0m")
                for r in cleanup_report:
                    ph = Path(r.get("placeholder", ""))
                    marker = f" → {ph.name}" if ph.name else ""
                    print(f"  - {r['path']}{marker}")
            else:
                print(f"\033[33m[file-tracker] 退出时无需清理临时文件\033[0m")
            if len(sm.history) == 0:
                # 空会话：删除文件和索引记录
                path = session_file_path(sm.session_id)
                if path.exists():
                    path.unlink()
                remove_session_from_index(sm.session_id)
            break

        # CLI 命令处理
        if query.strip().startswith("/"):
            handle_cli_command(query, sm)
            continue

        trigger_hooks("UserPromptSubmit", query)
        turn_start = len(sm.history)
        user_msg = {"role": "user", "content": query}
        sm.history.append(user_msg)
        if sm.session_id:
            log_message_to_jsonl(sm.session_id, user_msg)

        with agent_lock:
            agent_loop(sm.history, sm.context, sm.session_id)
            sm._context = update_context(sm.context, sm.history)
            print_turn_assistants(sm.history, turn_start)

        # 首轮对话结束后异步生成标题
        if len(sm.history) >= 2 and not sm._title_generated:
            sm._title_generated = True
            # 提取首条用户消息和首条助手消息
            first_user = ""
            first_assistant = ""
            for msg in sm.history:
                if msg.get("role") == "user" and not first_user:
                    content = msg.get("content", "")
                    first_user = str(content)[:200] if not isinstance(content, list) else str(content[0])[:200] if content else ""
                elif msg.get("role") == "assistant" and not first_assistant:
                    first_assistant = extract_text(msg.get("content", ""))[:200]
                if first_user and first_assistant:
                    break
            if first_user:
                # 在后台线程中异步生成标题
                threading.Thread(
                    target=generate_title,
                    args=(sm.session_id, first_user, first_assistant),
                    daemon=True
                ).start()

        inbox = consume_lead_inbox(sm.session_id, route_protocol=True)
        if inbox:
            def inbox_label(msg):
                req_id = msg.get("metadata", {}).get("request_id", "")
                suffix = f" req:{req_id}" if req_id else ""
                return f"{msg.get('type', 'message')}{suffix}"

            inbox_text = "\n".join(
                f"From {m['from']} [{inbox_label(m)}]: "
                f"{m['content'][:200]}" for m in inbox)
            inbox_msg = {"role": "user", "content": f"[Inbox]\n{inbox_text}"}
            sm.history.append(inbox_msg)
            if sm.session_id:
                log_message_to_jsonl(sm.session_id, inbox_msg)
        print()
