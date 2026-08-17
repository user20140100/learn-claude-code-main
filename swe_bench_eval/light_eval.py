#!/usr/bin/env python3
"""
SWE-bench 轻量评估器：不依赖 git clone，通过 patch 格式验证 + 与 gold patch 对比来评估质量。
包含三项指标：
  - patch_format_ok: 补丁格式是否合法（有 diff header + hunk）
  - file_match: 模型预测的文件是否与 gold 文件相同
  - line_match: 模型预测的行号与 gold 行号的偏差
  - hunk_overlap: 补丁内容与 gold patch 的文本重叠率
"""
import json
import re
import sys
from pathlib import Path

# ── Gold Patch 解析 ─────────────────────────────────────────────────
def parse_gold(gold_patch: str) -> dict:
    """解析 gold patch，提取文件列表和行号信息。"""
    result = {"files": [], "hunks": [], "raw": gold_patch}
    for m in re.finditer(r"--- a/(.+)", gold_patch):
        result["files"].append(m.group(1).strip())
    for m in re.finditer(r"@@ -(\d+),?(\d*) \+(\d+),?(\d*) @@", gold_patch):
        result["hunks"].append({
            "gold_start": int(m.group(1)),
            "gold_len": int(m.group(2)) if m.group(2) else 1,
            "pred_start": int(m.group(3)),
            "pred_len": int(m.group(4)) if m.group(4) else 1,
        })
    return result


def parse_pred(pred_patch: str) -> dict:
    """解析模型预测的 patch。"""
    result = {"files": [], "hunks": [], "raw": pred_patch}
    for m in re.finditer(r"--- a/(.+)", pred_patch):
        result["files"].append(m.group(1).strip())
    for m in re.finditer(r"@@ -(\d+),?(\d*) \+(\d+),?(\d*) @@", pred_patch):
        result["hunks"].append({
            "gold_start": int(m.group(1)),
            "gold_len": int(m.group(2)) if m.group(2) else 1,
            "pred_start": int(m.group(3)),
            "pred_len": int(m.group(4)) if m.group(4) else 1,
        })
    return result


def patch_format_ok(patch: str) -> bool:
    """检查 patch 是否具有合法的 diff 格式。"""
    if not patch or len(patch) < 10:
        return False
    has_diff_header = bool(re.search(r"^diff --git", patch, re.MULTILINE))
    has_git_header = bool(re.search(r"^--- a/", patch, re.MULTILINE))
    has_hunk = bool(re.search(r"^@@ ", patch, re.MULTILINE))
    # 至少要有 --- a/ 和 @@ 格式
    return has_git_header and has_hunk


def compute_line_error(pred_hunks, gold_hunks):
    """计算预测行号与 gold 行号的平均偏差。"""
    if not pred_hunks or not gold_hunks:
        return None
    errors = []
    for ph in pred_hunks[:3]:  # 只比较前 3 个 hunk
        for gh in gold_hunks[:3]:
            err = abs(ph["pred_start"] - gh["gold_start"])
            errors.append(err)
            break  # 每个 pred hunk 只对比第一个 gold hunk
    return sum(errors) / len(errors) if errors else None


def compute_file_match(pred_files, gold_files):
    """检查预测文件是否与 gold 文件匹配。"""
    if not pred_files or not gold_files:
        return False
    return pred_files[0].strip() == gold_files[0].strip()


def compute_hunk_overlap(pred_patch, gold_patch):
    """计算预测 patch 与 gold patch 的行级重叠率（Jaccard）。"""
    if not pred_patch or not gold_patch:
        return 0.0
    # 提取所有非空行
    pred_lines = set(l.strip() for l in pred_patch.splitlines() if l.strip() and not l.startswith("diff ") and not l.startswith("---") and not l.startswith("+++") and not l.startswith("@@"))
    gold_lines = set(l.strip() for l in gold_patch.splitlines() if l.strip() and not l.startswith("diff ") and not l.startswith("---") and not l.startswith("+++") and not l.startswith("@@"))
    if not pred_lines and not gold_lines:
        return 0.0
    intersection = pred_lines & gold_lines
    union = pred_lines | gold_lines
    return len(intersection) / len(union) if union else 0.0


# ── 评估主函数 ────────────────────────────────────────────────────────
def evaluate(predictions_path: str, dataset_path: str = None):
    """评估 predictions.jsonl，输出详细结果。"""
    # 加载 predictions
    preds = []
    with open(predictions_path) as f:
        for line in f:
            if line.strip():
                preds.append(json.loads(line))

    print(f"[*] Loaded {len(preds)} predictions from {predictions_path}")

    # 加载 dataset（用于获取 gold patch）
    local_jsonl = Path("swe_bench_eval/data/test.jsonl")
    if local_jsonl.exists():
        with open(local_jsonl) as f:
            ds_list = [json.loads(line) for line in f if line.strip()]
        gold_map = {inst["instance_id"]: inst["patch"] for inst in ds_list}
    else:
        import os; os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
        try:
            from datasets import load_dataset
            ds = load_dataset("princeton-nlp/SWE-bench_Lite", split="test")
            gold_map = {inst["instance_id"]: inst["patch"] for inst in ds}
        except ImportError:
            gold_map = {}

    results = []
    for p in preds:
        iid = p["instance_id"]
        gold = gold_map.get(iid, "")
        pred_patch = p.get("model_patch", "")
        gp = parse_gold(gold)
        pp = parse_pred(pred_patch)

        fmt_ok = patch_format_ok(pred_patch)
        file_match = compute_file_match(pp["files"], gp["files"])
        line_err = compute_line_error(pp["hunks"], gp["hunks"])
        hunk_overlap = compute_hunk_overlap(pred_patch, gold)

        results.append({
            "instance_id": iid,
            "status": p.get("status", "?"),
            "patch_format_ok": fmt_ok,
            "file_match": file_match,
            "line_error": round(line_err, 1) if line_err is not None else None,
            "hunk_overlap": round(hunk_overlap, 3),
            "pred_patch_len": len(pred_patch),
            "gold_patch_len": len(gold),
            "context_fetched": p.get("context_fetched", False),
        })

    return results, preds


def print_report(results, preds):
    total = len(results)
    ok = sum(1 for r in results if r["status"] == "ok")
    fmt_ok = sum(1 for r in results if r["patch_format_ok"])
    file_match = sum(1 for r in results if r["file_match"])
    ctx_used = sum(1 for r in results if r["context_fetched"])

    line_errors = [r["line_error"] for r in results if r["line_error"] is not None]
    avg_line_err = sum(line_errors) / len(line_errors) if line_errors else None
    overlaps = [r["hunk_overlap"] for r in results]
    avg_overlap = sum(overlaps) / len(overlaps) if overlaps else 0

    print("\n" + "=" * 65)
    print(f"{'SWE-bench Lite Evaluation Report':^65}")
    print("=" * 65)
    print(f"{'Metric':<30} {'Value':>10} {'Description':>25}")
    print("-" * 65)
    print(f"{'Total instances':<30} {total:>10}")
    print(f"{'Model output status=ok':<30} {ok:>10} ({ok/total*100:.1f}%)")
    print(f"{'Context fetched (API)':<30} {ctx_used:>10} ({ctx_used/total*100:.1f}%)")
    print(f"{'Patch format valid':<30} {fmt_ok:>10} ({fmt_ok/total*100:.1f}%)")
    print(f"{'File path matches gold':<30} {file_match:>10} ({file_match/total*100:.1f}%)")
    if avg_line_err is not None:
        print(f"{'Avg line number error':<30} {avg_line_err:>10.1f} lines")
    print(f"{'Avg hunk overlap (Jaccard)':<30} {avg_overlap:>10.3f}")
    print("=" * 65)

    # 按状态分组统计
    by_status = {}
    for r in results:
        s = r["status"]
        by_status.setdefault(s, []).append(r)
    print("\nBreakdown by status:")
    for s, items in sorted(by_status.items(), key=lambda x: -len(x[1])):
        fmt_ok_cnt = sum(1 for i in items if i["patch_format_ok"])
        print(f"  {s}: {len(items)} instances, {fmt_ok_cnt} have valid patch format")

    # 详细实例列表
    print("\nDetailed results:")
    print(f"  {'instance_id':<30} {'status':<12} {'fmt':>4} {'file':>4} {'line_err':>8} {'overlap':>7}")
    for r in results:
        le = f"{r['line_error']:.0f}" if r['line_error'] is not None else "N/A"
        print(f"  {r['instance_id']:<30} {r['status']:<12} {'Y' if r['patch_format_ok'] else 'N':>4} "
              f"{'Y' if r['file_match'] else 'N':>4} {le:>8} {r['hunk_overlap']:>7.3f}")


def save_results(results, output_path):
    with open(output_path, "w") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"\nResults saved to {output_path}")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--predictions", default="swe_bench_eval/predictions_v4.jsonl")
    parser.add_argument("--output", default="swe_bench_eval/eval_results_v4.json")
    args = parser.parse_args()

    results, preds = evaluate(args.predictions)
    print_report(results, preds)
    save_results(results, args.output)
