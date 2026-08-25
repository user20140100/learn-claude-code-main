"""批量应用 SWE-bench GitHub 工具链修改到 s20_comprehensive/code.py"""
PATH = "s20_comprehensive/code.py"
with open(PATH) as f:
    content = f.read()

# 1. 添加 import
if "import urllib.request" not in content:
    content = content.replace(
        "import ast, json, os, subprocess, time, random, threading, re, uuid, shutil\n",
        "import ast, json, os, subprocess, time, random, threading, re, uuid, shutil\nimport urllib.request\nimport base64\n"
    )

# 2. 添加 GITHUB_TOKEN
if "GITHUB_TOKEN = os.getenv" not in content:
    content = content.replace(
        'if os.getenv("ANTHROPIC_BASE_URL"):\n    os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)\n',
        'if os.getenv("ANTHROPIC_BASE_URL"):\n    os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)\n\nGITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")\nif GITHUB_TOKEN:\n    print(f"[config] GITHUB_TOKEN loaded, limit: 5000/hr")\nelse:\n    print("[config] GITHUB_TOKEN not set (60/hr limit for public repos)")\n'
    )

# 3. 添加工具函数（在 VALID_WT_NAME 之后）
if "_github_api_get" not in content:
    new_funcs = """

# --- GitHub Sandbox Tools ---
SANDBOXES_DIR = WORKDIR / ".sandboxes"
SANDBOXES_DIR.mkdir(exist_ok=True)
_active_sandboxes: dict[str, str] = {}


def _github_api_get(path, token="", timeout=15):
    url = "https://api.github.com" + path
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None


def run_github_fetch(repo, filepath, commit, token=""):
    data = _github_api_get("/repos/" + repo + "/contents/" + filepath + "?ref=" + commit, token)
    if not data or "content" not in data:
        return "Error: cannot fetch " + repo + "/" + filepath + "@" + commit[:8]
    try:
        raw = base64.b64decode(data["content"]).decode("utf-8")
        size_kb = len(raw) // 1024
        return "# " + repo + "/" + filepath + " @ " + commit[:8] + " (" + str(size_kb) + "KB)\\n" + raw
    except Exception as e:
        return "Error: Base64 decode failed: " + str(e)


def run_github_clone(repo, commit, sandbox_name="", token=""):
    import urllib.parse
    if not sandbox_name:
        safe_name = repo.replace("/", "__") + "__" + commit[:8]
    else:
        safe_name = re.sub(r'[^A-Za-z0-9._-]', '_', sandbox_name)
    sandbox_path = SANDBOXES_DIR / safe_name
    if sandbox_path.exists() and (sandbox_path / ".git").exists():
        r = subprocess.run(["git", "-C", str(sandbox_path), "fetch",
                            "https://github.com/" + repo + ".git", commit],
                           capture_output=True, timeout=60)
        if r.returncode != 0:
            return "Error: fetch failed: " + r.stderr.decode()[:200]
        r2 = subprocess.run(["git", "-C", str(sandbox_path), "reset", "--hard", "FETCH_HEAD"],
                            capture_output=True, timeout=30)
        if r2.returncode != 0:
            return "Error: reset failed: " + r2.stderr.decode()[:200]
        _active_sandboxes[safe_name] = str(sandbox_path)
        return "Reused sandbox: " + str(sandbox_path)
    clone_url = "https://github.com/" + repo + ".git"
    if token:
        clone_url = clone_url.replace("https://", "https://" + token + "@")
    r = subprocess.run(["git", "clone", "--depth", "1", "--single-branch",
                        clone_url, str(sandbox_path)],
                       capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        return "Error: clone failed: " + r.stderr[:300]
    r2 = subprocess.run(["git", "-C", str(sandbox_path), "checkout", commit],
                        capture_output=True, text=True, timeout=30)
    if r2.returncode != 0:
        return "Warning: checkout " + commit[:8] + " failed; using HEAD"
    _active_sandboxes[safe_name] = str(sandbox_path)
    total_files = sum(1 for _ in sandbox_path.rglob("*") if _.is_file())
    return "Cloned " + repo + "@" + commit[:8] + " to " + str(sandbox_path) + " (" + str(total_files) + " files)"


def run_sandbox_cleanup(names=None):
    targets = names if names is not None else list(_active_sandboxes.keys())
    cleaned = 0
    errors = []
    for name in targets:
        path = Path(_active_sandboxes.pop(name, ""))
        if not path or not path.exists():
            errors.append(name + ": not found")
            continue
        try:
            shutil.rmtree(path, ignore_errors=True)
            cleaned += 1
        except Exception as e:
            errors.append(name + ": " + str(e))
    if names is None:
        for child in SANDBOXES_DIR.iterdir():
            if child.is_dir():
                try:
                    shutil.rmtree(child, ignore_errors=True)
                except Exception:
                    pass
    msg = "Cleaned " + str(cleaned) + "/" + str(len(targets)) + " sandboxes"
    if errors:
        msg += "; errors: " + ", ".join(errors[:3])
    return msg


def run_list_sandboxes():
    if not _active_sandboxes:
        return "No active sandboxes."
    lines = []
    for name, path in _active_sandboxes.items():
        p = Path(path)
        size = sum(f.stat().st_size for f in p.rglob("*") if f.is_file()) if p.exists() else 0
        size_mb = size / (1024 * 1024)
        files = sum(1 for _ in p.rglob("*") if _.is_file()) if p.exists() else 0
        lines.append("  " + name + ": " + str(path) + "  (" + str(files) + " files, " + str(round(size_mb, 1)) + "MB)")
    return "\\n".join(lines)
"""
    content = content.replace(
        "VALID_WT_NAME = re.compile(r'^[A-Za-z0-9._-]{1,64}$')",
        "VALID_WT_NAME = re.compile(r'^[A-Za-z0-9._-]{1,64}$')" + new_funcs
    )

# 4. 更新 tools 列表
if "github_fetch" not in content.split("principles")[0]:
    content = content.replace(
        "- MCP: connect_mcp. MCP tools are prefixed mcp__{server}__{tool}.",
        "- GitHub: github_fetch (download single file), github_clone (clone repo to sandbox), sandbox_cleanup (clean up), list_sandboxes (list sandboxes)\\n             - MCP: connect_mcp. MCP tools are prefixed mcp__{server}__{tool}."
    )

# 5. 添加规则 11
if "11. GITHUB TOOLS" not in content:
    content = content.replace(
        '"in one message (up to 5). Sequential only when one call\'s result feeds the next."',
        '"in one message (up to 5). Sequential only when one call\'s result feeds the next.\\n"\\n        "11. GITHUB TOOLS: for SWE-bench / GitHub issue tasks, use github_fetch(repo, filepath, commit) to read a single file, or github_clone(repo, commit) to clone the full repo. After finishing, always call sandbox_cleanup() to reclaim disk space."'
    )

# 6. 更新 assemble_system_prompt
if "Active sandboxes" not in content:
    content = content.replace(
        '    mcp_names = list(mcp_clients.keys())\n    if mcp_names:\n        sections.append(f"Connected MCP servers: {\', \'.join(mcp_names)}")\n    return "\\n\\n".join(sections)',
        '''    mcp_names = list(mcp_clients.keys())
    if mcp_names:
        sections.append(f"Connected MCP servers: {', '.join(mcp_names)}")
    if GITHUB_TOKEN:
        sections.append(f"GitHub PAT is configured (token: {GITHUB_TOKEN[:8]}...). Use github_fetch/github_clone tools for SWE-bench tasks.")
    if _active_sandboxes:
        sections.append(f"Active sandboxes: {', '.join(_active_sandboxes.keys())}. Call sandbox_cleanup() when done.")
    return "\\n\\n".join(sections)'''
    )

# 7. 注册工具到 BUILTIN_TOOLS（web_fetch 之后插入）
if '"github_fetch"' not in content:
    github_tools_json = '''    {"name": "github_fetch",
     "description": "Download a single file from a GitHub repository via the Contents API.",
     "input_schema": {"type": "object",
                      "properties": {
                          "repo": {"type": "string", "description": "owner/repo"},
                          "filepath": {"type": "string", "description": "path inside repo"},
                          "commit": {"type": "string", "description": "base_commit hash"},
                          "token": {"type": "string", "description": "GitHub PAT (optional)"}
                      },
                      "required": ["repo", "filepath", "commit"]}},
    {"name": "github_clone",
     "description": "Clone a GitHub repo at a specific commit into a local sandbox.",
     "input_schema": {"type": "object",
                      "properties": {
                          "repo": {"type": "string", "description": "owner/repo"},
                          "commit": {"type": "string", "description": "base_commit hash"},
                          "sandbox_name": {"type": "string", "description": "optional name"},
                          "token": {"type": "string", "description": "GitHub PAT (optional)"}
                      },
                      "required": ["repo", "commit"]}},
    {"name": "sandbox_cleanup",
     "description": "Delete sandbox directories to reclaim disk space. Call after finishing.",
     "input_schema": {"type": "object",
                      "properties": {"names": {"type": "array", "items": {"type": "string"}}},
                      "required": []}},
    {"name": "list_sandboxes",
     "description": "List all active sandbox directories with their paths and sizes.",
     "input_schema": {"type": "object", "properties": {}, "required": []}},'''
    # 插入到 web_fetch 定义之前
    content = content.replace(
        '    {"name": "web_fetch",',
        github_tools_json + '\n    {"name": "web_fetch",'
    )

# 8. 注册 handlers
if '"github_fetch": run_github_fetch' not in content:
    content = content.replace(
        '    "web_search": run_web_search, "web_fetch": run_web_fetch,',
        '    "web_search": run_web_search, "web_fetch": run_web_fetch,\n    "github_fetch": run_github_fetch, "github_clone": run_github_clone,\n    "sandbox_cleanup": run_sandbox_cleanup, "list_sandboxes": run_list_sandboxes,'
    )

with open(PATH, "w") as f:
    f.write(content)

print("OK: all changes applied")
import ast
ast.parse(content)
print("syntax OK")
for c in ["_github_api_get", "run_github_fetch", "run_github_clone", "run_sandbox_cleanup",
          "run_list_sandboxes", "SANDBOXES_DIR", "_active_sandboxes", "GITHUB_TOKEN"]:
    print(f"  {c}: {'OK' if c in content else 'MISSING'}")
gf_count = content.count('"github_fetch"')
print(f"  github_fetch registrations: {gf_count}")
