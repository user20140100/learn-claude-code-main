#!/usr/bin/env python3
"""
test_models.py - 测试 .env 中 MODEL_POOL 配置的所有模型是否可直接调用

测试方式：
  对每个模型发送一个最简短的请求（max_tokens=10），消耗约 10-20 token
  捕获各类异常（配额耗尽/模型不存在/权限错误/网络错误等）
  输出表格化的测试报告

特点：
  - 纯 Python 标准库实现，无需安装 anthropic SDK
  - 直接调用阿里云百炼 Anthropic 兼容端点

用法：
  python test_models.py            # 测试所有模型
  python test_models.py qwen3.7-plus qwen3.7-max  # 测试指定模型
  python test_models.py --verbose  # 显示详细错误信息
"""
from __future__ import annotations
import os
import sys
import time
import json
import urllib.request
import urllib.error
from pathlib import Path

# ── 加载 .env 文件（不依赖 python-dotenv）──
ENV_PATH = Path(__file__).parent / ".env"
if ENV_PATH.exists():
    with open(ENV_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())

# ── 配置 ──
API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
BASE_URL = os.environ.get("ANTHROPIC_BASE_URL", "").rstrip("/")
MODEL_POOL_STR = os.environ.get("MODEL_POOL", "")
MODEL_POOL = [m.strip() for m in MODEL_POOL_STR.split(",") if m.strip()]

# 测试请求参数
TEST_MESSAGE = "Hi"
TEST_MAX_TOKENS = 10  # 仅请求 10 个输出 token
REQUEST_TIMEOUT = 30  # 单模型超时 30 秒


def classify_error(status_code: int, body: str) -> tuple[str, str]:
    """对 HTTP 错误进行分类，返回 (状态标签, 简短说明)"""
    body_lower = body.lower()

    # 配额/额度类
    if any(kw in body_lower for kw in [
        "allocationquota.freetieronly", "freetierquota.exhausted",
        "quota", "免费额度", "arrears", "余额不足",
        "insufficient_balance", "balance is not enough",
    ]):
        return "QUOTA_EXHAUSTED", "免费额度已耗尽或欠费"

    # 模型不存在/不可用
    if any(kw in body_lower for kw in [
        "model not found", "does not exist", "not supported",
        "invalid model", "unknown model", "no such model",
        "model_not_found",
    ]):
        return "MODEL_NOT_FOUND", "模型不存在或不支持"

    # 权限/认证类
    if status_code in (401, 403) or any(kw in body_lower for kw in [
        "unauthorized", "invalid api key", "authentication",
        "forbidden", "permission", "access denied",
    ]):
        # 403 但未命中配额关键词，可能是权限问题
        if "quota" not in body_lower and "arrears" not in body_lower:
            return "AUTH_ERROR", "API Key 无效或无权限"

    # 限速
    if status_code == 429 or "ratelimit" in body_lower:
        return "RATE_LIMITED", "触发限速，稍后重试"

    # 过载
    if status_code == 529 or "overloaded" in body_lower:
        return "OVERLOADED", "服务过载，稍后重试"

    # 其他
    snippet = body[:80].replace("\n", " ").strip()
    return f"HTTP_{status_code}", snippet or f"HTTP {status_code}"


def test_single_model(model: str, verbose: bool = False) -> dict:
    """测试单个模型，返回测试结果字典"""
    result = {
        "model": model,
        "status": "",
        "label": "",
        "detail": "",
        "latency_ms": 0,
        "input_tokens": 0,
        "output_tokens": 0,
    }

    # 构造请求
    url = f"{BASE_URL}/v1/messages"
    payload = {
        "model": model,
        "max_tokens": TEST_MAX_TOKENS,
        "messages": [{"role": "user", "content": TEST_MESSAGE}],
    }
    headers = {
        "Content-Type": "application/json",
        "x-api-key": API_KEY,
        "anthropic-version": "2023-06-01",
    }
    data = json.dumps(payload).encode("utf-8")

    start = time.time()
    try:
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            elapsed = (time.time() - start) * 1000
            body = resp.read().decode("utf-8")
            data_resp = json.loads(body)

            result["status"] = "OK"
            result["label"] = "可用"
            result["latency_ms"] = elapsed

            # 提取 token 使用情况
            usage = data_resp.get("usage", {})
            result["input_tokens"] = usage.get("input_tokens", 0)
            result["output_tokens"] = usage.get("output_tokens", 0)
            result["detail"] = (
                f"in={result['input_tokens']} out={result['output_tokens']}")

            if verbose:
                content = data_resp.get("content", [])
                if content and isinstance(content, list):
                    text = content[0].get("text", "")[:50]
                    result["detail"] += f" | reply: {text!r}"

    except urllib.error.HTTPError as e:
        elapsed = (time.time() - start) * 1000
        result["latency_ms"] = elapsed
        body = ""
        try:
            body = e.read().decode("utf-8")
        except Exception:
            pass
        label, detail = classify_error(e.code, body)
        result["status"] = label
        result["label"] = detail
        # 提取 API 错误消息
        try:
            err_json = json.loads(body)
            api_msg = err_json.get("error", {}).get("message", body[:120])
        except Exception:
            api_msg = body[:120] if body else f"HTTP {e.code}"
        result["detail"] = api_msg if verbose else detail

    except urllib.error.URLError as e:
        elapsed = (time.time() - start) * 1000
        result["latency_ms"] = elapsed
        result["status"] = "NETWORK_ERROR"
        result["label"] = "网络连接失败"
        result["detail"] = str(e.reason)[:120]

    except Exception as e:
        elapsed = (time.time() - start) * 1000
        result["latency_ms"] = elapsed
        result["status"] = "UNKNOWN_ERROR"
        result["label"] = type(e).__name__
        result["detail"] = str(e)[:120]

    return result


def print_report(results: list[dict]):
    """打印表格化的测试报告"""
    print("\n" + "=" * 100)
    print(f"{'模型 ID':<35} {'状态':<22} {'耗时':>8} {'详情'}")
    print("-" * 100)

    ok_count = 0
    for r in results:
        # 状态符号 + 颜色
        if r["status"] == "OK":
            status_display = f"\033[32m✓ OK\033[0m"
            ok_count += 1
        elif r["status"] == "QUOTA_EXHAUSTED":
            status_display = f"\033[31m✗ QUOTA_EXHAUSTED\033[0m"
        elif r["status"] == "MODEL_NOT_FOUND":
            status_display = f"\033[33m✗ MODEL_NOT_FOUND\033[0m"
        elif r["status"] in ("RATE_LIMITED", "OVERLOADED"):
            status_display = f"\033[33m⚠ {r['status']}\033[0m"
        else:
            status_display = f"\033[31m✗ {r['status']}\033[0m"

        latency = f"{r['latency_ms']:.0f}ms"
        # 截断详情避免破坏表格
        detail = r["detail"][:50]
        print(f"{r['model']:<35} {status_display:<30} {latency:>8} {detail}")

    print("=" * 100)
    total = len(results)
    print(f"汇总：\033[32m{ok_count} 可用\033[0m / {total - ok_count} 不可用 / 共 {total} 个")

    # 给出后续建议
    if ok_count < total:
        print("\n建议：")
        failed = [r for r in results if r["status"] != "OK"]
        quota_failed = [r for r in failed if r["status"] == "QUOTA_EXHAUSTED"]
        not_found = [r for r in failed if r["status"] == "MODEL_NOT_FOUND"]
        auth_err = [r for r in failed if r["status"] == "AUTH_ERROR"]
        if quota_failed:
            print(f"  - {len(quota_failed)} 个模型额度已耗尽，"
                  f"项目运行时会自动切换到其他可用模型")
            print(f"    已耗尽：{', '.join(r['model'] for r in quota_failed)}")
        if not_found:
            print(f"  - {len(not_found)} 个模型 ID 不存在，建议从 MODEL_POOL 中移除：")
            for r in not_found:
                print(f"      {r['model']}")
        if auth_err:
            print(f"  - {len(auth_err)} 个模型因权限问题失败，请检查 API Key 权限")
        other = [r for r in failed if r["status"] not in
                 ("QUOTA_EXHAUSTED", "MODEL_NOT_FOUND", "AUTH_ERROR",
                  "RATE_LIMITED", "OVERLOADED")]
        if other:
            print(f"  - {len(other)} 个模型因其他原因失败，使用 --verbose 查看详情")
    print()


def main():
    verbose = "--verbose" in sys.argv or "-v" in sys.argv
    # 解析要测试的模型列表
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    models_to_test = args if args else MODEL_POOL

    if not models_to_test:
        print("\033[31m错误：未找到 MODEL_POOL 配置，且未指定要测试的模型\033[0m")
        print(f"请检查 .env 文件：{ENV_PATH}")
        sys.exit(1)

    if not API_KEY:
        print("\033[31m错误：未找到 ANTHROPIC_API_KEY\033[0m")
        sys.exit(1)

    if not BASE_URL:
        print("\033[31m错误：未找到 ANTHROPIC_BASE_URL\033[0m")
        sys.exit(1)

    # 打印测试环境
    print(f"\n测试环境：")
    print(f"  Base URL: {BASE_URL}")
    print(f"  API Key:  {API_KEY[:8]}...{API_KEY[-4:] if len(API_KEY) > 12 else '***'}")
    print(f"  请求路径: {BASE_URL}/v1/messages")
    print(f"  测试请求: messages=[{{'role':'user','content':'{TEST_MESSAGE}'}}], "
          f"max_tokens={TEST_MAX_TOKENS}")
    print(f"  待测试模型数: {len(models_to_test)}")
    print(f"  预计消耗: ~{len(models_to_test) * 20} token（每模型约 10-20 token）")
    print()

    # 逐个测试
    results = []
    for i, model in enumerate(models_to_test, 1):
        print(f"[{i}/{len(models_to_test)}] 测试 {model} ...", end="", flush=True)
        r = test_single_model(model, verbose)
        results.append(r)
        # 同行打印结果
        if r["status"] == "OK":
            print(f" \033[32m✓\033[0m {r['latency_ms']:.0f}ms "
                  f"(in={r['input_tokens']}, out={r['output_tokens']})")
        else:
            print(f" \033[31m✗ {r['status']}\033[0m - {r['label']}")

    # 打印汇总报告
    print_report(results)

    # 保存结果到 JSON（便于后续分析）
    out_path = Path(__file__).parent / "test_models_result.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"详细结果已保存至：{out_path}")

    # 退出码：全部可用为 0，否则为 1
    sys.exit(0 if all(r["status"] == "OK" for r in results) else 1)


if __name__ == "__main__":
    main()
