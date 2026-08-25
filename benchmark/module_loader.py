"""module_loader.py - 动态加载章节模块（s08 等）的工具。

在临时 cwd 下加载模块，注入 fake_anthropic 与 fake_dotenv，
避免依赖真实 API Key 与项目根目录的 .env。

针对 Python 3.9 以下环境，加载时自动注入 `from __future__ import annotations`，
使 PEP 585 类型注解（如 list[dict]）延迟求值，无需修改原代码。
"""
import os
import sys
import tempfile
import types
from pathlib import Path

from benchmark.fake_anthropic import make_fake_anthropic_module, make_fake_dotenv_module

REPO_ROOT = Path(__file__).resolve().parents[1]


def _inject_future_annotations(source: str) -> str:
    """在源码顶部注入 `from __future__ import annotations`。

    处理顺序：shebang → 模块 docstring → 插入 future import。
    若源码已包含该 import，则原样返回。
    """
    if "from __future__ import annotations" in source:
        return source

    lines = source.split("\n")
    insert_idx = 0

    # 跳过 shebang
    if lines and lines[0].startswith("#!"):
        insert_idx = 1

    # 跳过模块 docstring
    if insert_idx < len(lines):
        stripped = lines[insert_idx].lstrip()
        for quote in ('"""', "'''"):
            if stripped.startswith(quote):
                if stripped.count(quote) >= 2:
                    # 单行 docstring
                    insert_idx += 1
                else:
                    # 多行 docstring：找到结束引号
                    insert_idx += 1
                    while insert_idx < len(lines):
                        if quote in lines[insert_idx]:
                            insert_idx += 1
                            break
                        insert_idx += 1
                break

    lines.insert(insert_idx, "from __future__ import annotations")
    return "\n".join(lines)


def load_chapter_module(chapter: str, temp_cwd: Path = None):
    """动态加载章节模块。

    Args:
        chapter: 章节标识，如 "s08"、"s09"、"s20"
        temp_cwd: 临时工作目录；为 None 时自动创建临时目录

    Returns:
        (module, temp_dir_or_None, fake_client) 三元组。
        temp_dir_or_None 为 None 表示调用方无需清理；
        否则调用方应在使用完毕后清理临时目录。
        fake_client 是注入到模块的 Anthropic 客户端实例。
    """
    path_map = {
        "s08": REPO_ROOT / "s08_context_compact" / "code.py",
        "s09": REPO_ROOT / "s09_memory" / "code.py",
        "s20": REPO_ROOT / "s20_comprehensive" / "code.py",
    }
    path = path_map.get(chapter)
    if path is None or not path.exists():
        raise FileNotFoundError(f"无法找到章节 {chapter} 的 code.py: {path}")

    owns_temp = temp_cwd is None
    if owns_temp:
        temp_cwd = Path(tempfile.mkdtemp(prefix=f"bench_{chapter}_"))

    # 保存环境快照
    previous_cwd = Path.cwd()
    previous_model = os.environ.get("MODEL_ID")
    previous_key = os.environ.get("ANTHROPIC_API_KEY")
    previous_base = os.environ.get("ANTHROPIC_BASE_URL")

    # 注入 fake 模块
    fake_anthropic_mod = make_fake_anthropic_module()
    fake_dotenv_mod = make_fake_dotenv_module()
    sys.modules["anthropic"] = fake_anthropic_mod
    sys.modules["dotenv"] = fake_dotenv_mod
    os.environ["MODEL_ID"] = "test-model"
    os.environ["ANTHROPIC_API_KEY"] = "test-key"
    os.environ.pop("ANTHROPIC_BASE_URL", None)

    # 读取源码并注入 future annotations，再用 compile + exec 加载
    source = path.read_text(encoding="utf-8")
    source = _inject_future_annotations(source)
    module = types.ModuleType(f"bench_{chapter}_module")
    module.__file__ = str(path)

    try:
        os.chdir(temp_cwd)
        code = compile(source, str(path), "exec")
        exec(code, module.__dict__)
    finally:
        os.chdir(previous_cwd)

    fake_client = module.client
    return module, temp_cwd, fake_client


def restore_environment():
    """恢复 sys.modules 中 anthropic/dotenv 的原始状态。

    在所有基准测试完成后调用，避免污染后续代码。
    """
    # 简化实现：直接清理 bench 注入的 fake 模块
    # （真实测试场景下不影响，因为 benchmark 进程退出后即清理）
    for k in ("anthropic", "dotenv"):
        sys.modules.pop(k, None)
