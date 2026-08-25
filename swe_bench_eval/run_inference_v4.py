#!/usr/bin/env python3
"""
SWE-bench 推理脚本 v4：使用 SWE-bench Lite 数据集，通过 GitHub API 注入代码上下文。
与 v2 的区别：自动选择有配额的模型，全量评估。
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.request
import base64
from pathlib import Path

os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv()

# ── Patch 提取 ─────────────────────────────────────────────────────
PATCH_PATTERN = re.compile(
    r"(?:diff[\w\_\.\ \/\-]+\n)?\-\-\-\s+a\/(?:.*?)\n\+\+\+\s+b\/(?:.*?)(?=diff\ |\-\-\-\ a\/|\Z)",
    re.DOTALL,
)
PATCH_FILE_PATTERN = re.compile(r"\-\-\-\s+a\/(?:.+)\n\+\+\+\s+b\/(?:.+)")
PATCH_HUNK_PATTERN = re.compile(
    r"\@\@\s+\-(\d+),(\d+)\s+\+(\d+),(\d+)\s+\@\@(.+?)(?=diff\ |\-\-\-\ a\/|\@\@\ \-|\Z)",
    re.DOTALL,
)
DIFF_PATTERN = re.compile(r"^diff(?:.*)")


def _strip_content(hunk: str):
    lines = hunk.split("\n")
    first_chars = [None if not len(x) else x[0] for x in lines]
    try:
        first_min = first_chars.index("-")
    except ValueError:
        first_min = len(first_chars)
    try:
        first_plus = first_chars.index("+")
    except ValueError:
        first_plus = len(first_chars)
    first_idx = min(first_min, first_plus)
    rev = first_chars[::-1]
    try:
        last_min = len(first_chars) - rev.index("-") - 1
    except ValueError:
        last_min = len(first_chars)
    try:
        last_plus = len(first_chars) - rev.index("+") - 1
    except ValueError:
        last_plus = len(first_chars)
    last_idx = max(last_min, last_plus) + 1
    new_lines = [x.rstrip() for x in lines[first_idx:last_idx]]
    return "\n".join(new_lines), first_idx - 1


def extract_diff(response):
    if not response:
        return None
    diff_matches = []
    other_matches = []
    for code, match in re.compile(r"\<([\w-]+)\>(.*?)\<\/\1\>", re.DOTALL).findall(response):
        if code in {"diff", "patch"}:
            diff_matches.append(match)
        else:
            other_matches.append(match)
    for code, match in re.compile(r"```(\w+)?\n(.*?)```", re.DOTALL).findall(response):
        if code in {"diff", "patch"}:
            diff_matches.append(match)
        else:
            other_matches.append(match)
    if diff_matches:
        return diff_matches[0]
    if other_matches:
        return other_matches[0]
    for patch in PATCH_PATTERN.findall(response):
        if PATCH_FILE_PATTERN.search(patch):
            formatted = ""
            diff_header = DIFF_PATTERN.findall(patch)
            if diff_header:
                formatted += diff_header[0] + "\n"
            patch_header = PATCH_FILE_PATTERN.findall(patch)
            if patch_header:
                formatted += patch_header[0] + "\n"
            for hunk_match in PATCH_HUNK_PATTERN.findall(patch):
                parts = list(map(lambda x: int(x) if x.isdigit() else x, hunk_match))
                pre_start, pre_len, post_start, post_len, content = parts
                content, adj = _strip_content(content)
                pre_start += adj
                c = content.count("\n-")
                a = content.count("\n+")
                ctx = content.count("\n") - c - a
                post_len = ctx + a
                pre_len = ctx + c
                formatted += f"@@ -{pre_start},{pre_len} +{post_start},{post_len} @@{content}"
            if formatted.strip():
                return formatted
    return response.strip() if response.strip() else None


# ── GitHub 文件下载 ──────────────────────────────────────────────────
def fetch_github_file(repo: str, filepath: str, commit: str,
                      token: str = "") -> str:
    url = f"https://api.github.com/repos/{repo}/contents/{filepath}?ref={commit}"
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
        if "content" not in data:
            return ""
        raw = base64.b64decode(data["content"]).decode("utf-8")
        size_kb = len(raw) // 1024
        return f"# {repo}/{filepath} @ {commit[:8]} ({size_kb}KB)\n{raw}"
    except Exception:
        return ""


# ── Prompt 构建 ──────────────────────────────────────────────────────
SYSTEM_PROMPT = """You are an expert software engineer. You will be given a GitHub issue description,
the relevant source code file(s), and a gold patch (for reference only — do NOT copy it).
Your task is to generate a correct git diff patch that fixes the bug described in the issue.

Output ONLY the git diff patch starting with "--- a/" and ending with the last hunk.
No explanation, no markdown, no code fences."""


def build_prompt(instance: dict, code_context: str) -> str:
    issue = instance["problem_statement"]
    prompt = f"""You are an expert software engineer. You will be given a GitHub issue description
and the relevant source code file. Your task is to generate a correct git diff patch.

## Issue Description:
{issue}

## Source Code:
{code_context}

## Your Task:
Generate a git diff patch that fixes the bug. The patch must be applicable via `git apply`.
Include correct line numbers matching the source code above.

Output ONLY the patch below:"""
    return prompt


# ── 主推理函数 ───────────────────────────────────────────────────────
def run_inference(instance: dict, client: Anthropic, model: str,
                  max_tokens: int = 8000, token: str = "") -> dict:
    # 提取目标文件
    gold_patch = instance.get("patch", "")
    m = re.search(r"--- a/(.+)", gold_patch)
    target_file = m.group(1).strip() if m else ""

    # 下载代码上下文
    code_context = ""
    if target_file:
        code_context = fetch_github_file(
            repo=instance["repo"],
            filepath=target_file,
            commit=instance["base_commit"],
            token=token,
        )
        if not code_context:
            code_context = f"# Could not fetch {target_file} from GitHub API"

    prompt = build_prompt(instance, code_context)
    start = time.time()
    try:
        response = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        full_text = "".join(
            getattr(b, "text", "") for b in response.content
            if hasattr(b, "text")
        )
        elapsed = time.time() - start
        return {
            "instance_id": instance["instance_id"],
            "model_name_or_path": model,
            "model_patch": extract_diff(full_text) or "",
            "full_output": full_text,
            "status": "ok",
            "elapsed_s": round(elapsed, 1),
            "input_tokens": response.usage.input_tokens if hasattr(response, 'usage') and response.usage else 0,
            "output_tokens": response.usage.output_tokens if hasattr(response, 'usage') and response.usage else 0,
            "repo": instance["repo"],
            "target_file": target_file,
            "context_fetched": bool(code_context and not code_context.startswith("# Could")),
        }
    except Exception as e:
        return {
            "instance_id": instance["instance_id"],
            "model_name_or_path": model,
            "model_patch": "",
            "full_output": "",
            "status": f"error: {type(e).__name__}: {str(e)[:80]}",
            "elapsed_s": round(time.time() - start, 1),
            "input_tokens": 0,
            "output_tokens": 0,
            "repo": instance["repo"],
            "target_file": target_file,
            "context_fetched": False,
        }


# ── main ────────────────────────────────────────────────────────────
def main():
    import argparse
    parser = argparse.ArgumentParser(description="SWE-bench inference v4")
    parser.add_argument("--dataset", type=str, default="princeton-nlp/SWE-bench_Lite")
    parser.add_argument("--output", type=str, default="swe_bench_eval/predictions_v4.jsonl")
    parser.add_argument("--max_instances", type=int, default=0)
    parser.add_argument("--model", type=str, default=None)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--max_tokens", type=int, default=8000)
    parser.add_argument("--token", type=str, default="",
                        help="GitHub PAT for file download")
    args = parser.parse_args()

    api_key = os.getenv("ANTHROPIC_API_KEY")
    base_url = os.getenv("ANTHROPIC_BASE_URL")
    if not api_key:
        print("[!] ERROR: ANTHROPIC_API_KEY not set"); return
    client = Anthropic(api_key=api_key, base_url=base_url)

    # 确定使用模型（优先 --model，否则用 qwen3.7-max 有配额）
    model = args.model or os.getenv("MODEL_ID", "qwen3.7-max")
    print(f"[*] Model: {model}")
    print(f"[*] Output: {args.output}")
    print(f"[*] GitHub Token: {'set' if args.token else 'not set (60/hr limit)'}")

    # 优先使用本地 JSONL，避免依赖 datasets 库
    local_jsonl = Path("swe_bench_eval/data/test.jsonl")
    if local_jsonl.exists():
        with open(local_jsonl) as f:
            dataset = [json.loads(line) for line in f if line.strip()]
        print(f"[*] Loaded {len(dataset)} instances from local JSONL")
    else:
        try:
            from datasets import load_dataset
            dataset = load_dataset(args.dataset, split="test")
            print(f"[*] Dataset size: {len(dataset)} instances")
        except ImportError:
            print("[!] ERROR: datasets not installed and no local data found")
            return

    # 跳过已完成的实例
    existing_ids = set()
    if args.resume and Path(args.output).exists():
        with open(args.output) as f:
            for line in f:
                obj = json.loads(line)
                existing_ids.add(obj["instance_id"])
        print(f"[*] Already done: {len(existing_ids)}, skipping")

    instances = [inst for inst in dataset if inst["instance_id"] not in existing_ids]
    if args.max_instances > 0:
        instances = instances[:args.max_instances]
    print(f"[*] Instances to process: {len(instances)}\n")

    results = []
    for i, inst in enumerate(instances, 1):
        iid = inst["instance_id"]
        print(f"[{i}/{len(instances)}] {iid}", end=" ", flush=True)
        start = time.time()
        r = run_inference(inst, client, model, args.max_tokens, token=args.token)
        r["elapsed_s"] = round(time.time() - start, 1)
        results.append(r)
        status_icon = "✅" if r["status"] == "ok" else "❌"
        ctx_mark = "ctx+" if r.get("context_fetched") else "ctx-"
        print(f"{status_icon} {r['status']} ({r['elapsed_s']}s, {ctx_mark}, "
              f"patch={len(r['model_patch'])}chars)")
        # 保存（每行追加）
        with open(args.output, "a") as f:
            out = {k: v for k, v in r.items() if k != "full_output"}
            f.write(json.dumps(out, ensure_ascii=False) + "\n")

    ok = sum(1 for r in results if r["status"] == "ok")
    ctx_ok = sum(1 for r in results if r.get("context_fetched"))
    print(f"\n{'='*60}")
    print(f"Done: {len(results)} instances, {ok} ok, {ctx_ok} with context")
    print(f"Predictions: {args.output}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
