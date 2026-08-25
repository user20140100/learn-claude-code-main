#!/usr/bin/env python3
"""
SWE-bench 完整评测器：克隆仓库 → 应用 patch → 运行测试 → 判定 resolve。

评估标准（SWE-bench 官方定义）：
  - FAIL_TO_PASS: 修复前失败、修复后应通过的测试（Bug 修复验证）
  - PASS_TO_PASS: 修复前后均应通过的测试（回归保护）
  - resolve = FAIL_TO_PASS全通过 AND PASS_TO_PASS全通过
"""
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

# ── 配置 ────────────────────────────────────────────────────────────
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
SCRIPT_DIR = Path(__file__).parent
DATA_DIR = SCRIPT_DIR / "data"
CACHE_DIR = Path("/tmp/swebench_cache")
CACHE_DIR.mkdir(parents=True, exist_ok=True)

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
PYTHON = "/home/hongchang/anaconda3/envs/s20/bin/python"


# ── 工具函数 ────────────────────────────────────────────────────────
def get_repo_path(repo: str, commit: str) -> Path:
    """获取（或创建）仓库缓存路径。优先用 cache，否则从 GitHub 下载。"""
    safe_name = repo.replace("/", "__") + "__" + commit[:8]
    repo_path = CACHE_DIR / safe_name
    if repo_path.exists() and (repo_path / ".git").exists():
        return repo_path

    # 尝试 git clone（可能因 TLS 失败）
    clone_url = f"https://github.com/{repo}.git"
    if GITHUB_TOKEN:
        clone_url = clone_url.replace("https://", f"https://{GITHUB_TOKEN}@")
    r = subprocess.run(
        ["git", "clone", "--depth", "1", clone_url, str(repo_path)],
        capture_output=True, text=True, timeout=120,
    )
    if r.returncode == 0:
        r2 = subprocess.run(["git", "-C", str(repo_path), "checkout", commit],
                           capture_output=True, text=True, timeout=30)
        if r2.returncode == 0:
            print(f"  [clone] {repo} @ {commit[:8]}")
            return repo_path

    # git clone 失败 → 记录并返回 None
    print(f"  [warn] git clone failed for {repo}@{commit[:8]}: {r.stderr[:100]}")
    return None


def apply_patch(repo_path: Path, patch_text: str) -> tuple[bool, str]:
    """将 patch 应用到仓库。返回 (success, error_msg)。"""
    patch_file = repo_path / "_temp_patch.diff"
    patch_file.write_text(patch_text)
    try:
        r = subprocess.run(
            ["git", "apply", "--check", str(patch_file)],
            capture_output=True, text=True, timeout=30,
        )
        if r.returncode != 0:
            return False, r.stderr[:200]
        r2 = subprocess.run(
            ["git", "apply", str(patch_file)],
            capture_output=True, text=True, timeout=30,
        )
        if r2.returncode != 0:
            return False, r2.stderr[:200]
        return True, ""
    finally:
        patch_file.unlink(missing_ok=True)


def run_tests(repo_path: Path, test_specs: str, description: str = "") -> tuple[bool, str]:
    """运行指定测试，返回 (all_passed, summary)。"""
    if not test_specs or test_specs.strip() == "[]" or test_specs.strip() == "null":
        return True, "No tests to run"
    try:
        tests = json.loads(test_specs)
    except json.JSONDecodeError:
        # 尝试清理字符串
        tests = re.findall(r'"([^"]+)"', test_specs)
    if not tests:
        return True, "Empty test list"

    # 运行 pytest
    r = subprocess.run(
        [PYTHON, "-m", "pytest", *tests, "-v", "--tb=short", "-q"],
        cwd=str(repo_path), capture_output=True, text=True, timeout=300,
        env={**os.environ, "PYTHONUNBUFFERED": "1"},
    )
    output = r.stdout[-3000:]
    # 解析结果
    passed = len(re.findall(r" passed", output))
    failed = len(re.findall(r" failed", output))
    errors = len(re.findall(r" error", output))
    total = passed + failed + errors
    if total == 0:
        total = len(tests)
    all_pass = failed == 0 and errors == 0
    summary = f"{passed}/{total} passed"
    if failed or errors:
        summary += f" ({failed} failed, {errors} errors)"
    return all_pass, summary


def parse_json_field(value: str):
    """安全解析 JSON 字段（可能是字符串化的 JSON）。"""
    if not value or value.strip() in ("null", ""):
        return []
    try:
        result = json.loads(value)
        if isinstance(result, list):
            return result
        if isinstance(result, str):
            return json.loads(result)
        return [result]
    except (json.JSONDecodeError, TypeError):
        # 尝试从字符串中提取测试路径
        return re.findall(r'"([^"]+)"', value)


# ── 主评测函数 ────────────────────────────────────────────────────────
def evaluate_instance(inst: dict, pred_patch: str) -> dict:
    """对单个实例进行完整评测。"""
    iid = inst["instance_id"]
    repo = inst["repo"]
    commit = inst["base_commit"]
    setup_commit = inst.get("environment_setup_commit", "")

    result = {
        "instance_id": iid,
        "status": "pending",
        "resolved": False,
        "fail_to_pass_result": None,
        "pass_to_pass_result": None,
        "apply_status": None,
        "error": "",
        "elapsed_s": 0,
    }

    start = time.time()
    try:
        # Step 1: 获取/创建仓库
        repo_path = get_repo_path(repo, commit)
        if repo_path is None:
            result["status"] = "no_repo"
            result["error"] = f"无法获取仓库 {repo}@{commit[:8]}"
            result["elapsed_s"] = round(time.time() - start, 1)
            return result

        # Step 2: 检查并安装依赖
        requirements = []
        setup_script = repo_path / "setup.py"
        setup_cfg = repo_path / "setup.cfg"
        pyproject = repo_path / "pyproject.toml"
        if setup_py.exists() or pyproject.exists():
            requirements.append("install_deps")
        if (repo_path / "requirements.txt").exists():
            requirements.append("requirements")

        # Step 3: 应用预测 patch
        patch_ok, patch_err = apply_patch(repo_path, pred_patch)
        if not patch_ok:
            result["status"] = "patch_apply_failed"
            result["error"] = f"Patch apply failed: {patch_err[:200]}"
            result["elapsed_s"] = round(time.time() - start, 1)
            return result
        result["apply_status"] = "ok"

        # Step 4: 运行 FAIL_TO_PASS 测试
        ftp_tests = parse_json_field(inst.get("FAIL_TO_PASS", "[]"))
        if ftp_tests:
            ftp_pass, ftp_summary = run_tests(repo_path, ftp_tests, "FAIL_TO_PASS")
            result["fail_to_pass_result"] = ftp_summary
            result["fail_to_pass_pass"] = ftp_pass
        else:
            result["fail_to_pass_result"] = "N/A"
            result["fail_to_pass_pass"] = True  # 无测试视为通过

        # Step 5: 运行 PASS_TO_PASS 测试（回归检查）
        ptp_tests = parse_json_field(inst.get("PASS_TO_PASS", "[]"))
        if ptp_tests:
            ptp_pass, ptp_summary = run_tests(repo_path, ptp_tests, "PASS_TO_PASS")
            result["pass_to_pass_result"] = ptp_summary
            result["pass_to_pass_pass"] = ptp_pass
        else:
            result["pass_to_pass_result"] = "N/A"
            result["pass_to_pass_pass"] = True

        # Step 6: 判定是否 resolve
        result["resolved"] = result.get("fail_to_pass_pass", True) and result.get("pass_to_pass_pass", True)
        result["status"] = "resolved" if result["resolved"] else "unresolved"

    except Exception as e:
        result["status"] = "error"
        result["error"] = f"{type(e).__name__}: {str(e)[:200]}"

    result["elapsed_s"] = round(time.time() - start, 1)
    return result


# ── main ────────────────────────────────────────────────────────────
def main():
    import argparse
    parser = argparse.ArgumentParser(description="SWE-bench 完整评测")
    parser.add_argument("--predictions", default="swe_bench_eval/predictions_v4.jsonl")
    parser.add_argument("--dataset", default="swe_bench_eval/data/test.jsonl")
    parser.add_argument("--output", default="swe_bench_eval/full_eval_results.json")
    parser.add_argument("--max_instances", type=int, default=0)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()

    # 加载 predictions
    preds = {}
    with open(args.predictions) as f:
        for line in f:
            if line.strip():
                d = json.loads(line)
                preds[d["instance_id"]] = d

    # 加载 dataset
    with open(args.dataset) as f:
        dataset = [json.loads(line) for line in f if line.strip()]

    print(f"[*] Dataset: {len(dataset)} instances")
    print(f"[*] Predictions: {len(preds)} instances")
    print(f"[*] To evaluate: {min(len(dataset), len(preds))} matching instances")

    # 跳过已完成的
    existing_ids = set()
    if args.resume and Path(args.output).exists():
        with open(args.output) as f:
            for line in f:
                if line.strip():
                    existing_ids.add(json.loads(line)["instance_id"])
        print(f"[*] Already done: {len(existing_ids)}")

    instances = [inst for inst in dataset
                 if inst["instance_id"] in preds
                 and inst["instance_id"] not in existing_ids]
    if args.max_instances > 0:
        instances = instances[:args.max_instances]
    print(f"[*] Evaluating: {len(instances)} instances\n")

    results = []
    for i, inst in enumerate(instances, 1):
        iid = inst["instance_id"]
        pred = preds[iid]
        patch = pred.get("model_patch", "")
        print(f"[{i}/{len(instances)}] {iid} ...", end=" ", flush=True)
        r = evaluate_instance(inst, patch)
        results.append(r)
        icon = "✅" if r["resolved"] else ("❌" if r["status"] != "error" else "⚠️")
        print(f"{icon} {r['status']} ({r['elapsed_s']}s)")
        if r["error"]:
            print(f"       err: {r['error'][:80]}")
        if r.get("fail_to_pass_result"):
            print(f"       FAIL_TO_PASS: {r['fail_to_pass_result']}")
        if r.get("pass_to_pass_result"):
            print(f"       PASS_TO_PASS: {r['pass_to_pass_result']}")
        # 保存进度
        with open(args.output, "a") as f:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    # 汇总
    total = len(results)
    resolved = sum(1 for r in results if r["resolved"])
    errors = sum(1 for r in results if r["status"] == "error")
    no_repo = sum(1 for r in results if r["status"] == "no_repo")
    patch_fail = sum(1 for r in results if r["status"] == "patch_apply_failed")
    unresolved = total - resolved - errors - no_repo - patch_fail

    print(f"\n{'='*60}")
    print(f"  SWE-bench Full Evaluation Results")
    print(f"{'='*60}")
    print(f"  Total instances evaluated:  {total}")
    print(f"  ✅ Resolved (patch correct): {resolved} ({resolved/total*100:.1f}%)")
    print(f"  ❌ Unresolved (patch wrong): {unresolved}")
    print(f"  ⚠️  Patch apply failed:      {patch_fail}")
    print(f"  📦 No repo available:        {no_repo}")
    print(f"  💥 Errors:                   {errors}")
    print(f"{'='*60}")

    # 详细结果
    print("\nDetailed results:")
    print(f"  {'instance_id':<30} {'resolved':>8} {'ftp':>12} {'ptp':>12} {'time':>6}")
    print("  " + "-"*72)
    for r in results:
        ftp = r.get("fail_to_pass_result") or "?"
        ptp = r.get("pass_to_pass_result") or "?"
        if len(ftp) > 10: ftp = ftp[:10] + "..."
        if len(ptp) > 10: ptp = ptp[:10] + "..."
        print(f"  {r['instance_id']:<30} {str(r['resolved']):>8} {ftp:>12} {ptp:>12} {r['elapsed_s']:>5.0f}s")

    # 保存
    with open(args.output, "w") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"\nResults saved to {args.output}")


if __name__ == "__main__":
    main()
