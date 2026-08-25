"""metrics.py - 轻量指标采集器。

提供：
- MetricsCollector: 记录各层压缩的触发次数、前后 token、耗时
- estimate_tokens: token 估算（与 s08 estimate_size 一致，用字符数 // 4）
- format_table: 输出 Markdown 表格
- estimate_size: 与 s08 的 estimate_size 一致（len(str(msgs))）
"""
import time
from collections import defaultdict
from statistics import mean


def estimate_size(msgs) -> int:
    """与 s08.estimate_size 一致：返回 len(str(msgs))。"""
    return len(str(msgs))


def estimate_tokens(text) -> int:
    """粗略 token 估算：字符数 // 4。

    适用于中英文混合文本，与 OpenAI/Anthropic 经验值接近。
    """
    return len(str(text)) // 4


class MetricsCollector:
    """指标采集器，记录多次测量的数据并汇总。

    用法：
        mc = MetricsCollector()
        mc.record("L1", before=10000, after=8000, duration_ms=0.5, triggered=True)
        summary = mc.summary()
    """

    def __init__(self):
        # 每层一个记录列表
        self._records = defaultdict(list)

    def record(self, layer: str, before: int, after: int,
               duration_ms: float, triggered: bool = True):
        """记录一次压缩层的执行。

        Args:
            layer: 层名（L1/L2/L3/L4）
            before: 压缩前 token/字符数
            after: 压缩后 token/字符数
            duration_ms: 本次执行耗时（毫秒）
            triggered: 是否实际触发（False 表示该层未触发，仅记录耗时为 0）
        """
        self._records[layer].append({
            "before": before,
            "after": after,
            "duration_ms": duration_ms,
            "triggered": triggered,
        })

    def summary(self) -> dict:
        """返回各层汇总指标。

        返回字典结构：
        {
            "L1": {
                "trigger_count": int,        # 触发次数
                "trigger_ratio": float,      # 触发占比（该层触发数 / 总触发数）
                "avg_before": float,
                "avg_after": float,
                "avg_compression_ratio": float,  # 1 - after/before
                "avg_duration_ms": float,
                "duration_ratio": float,     # 耗时占比（该层耗时 / 总耗时）
            },
            ...
            "overall": {
                "total_triggers": int,
                "total_duration_ms": float,
                "avg_compression_ratio": float,  # 整体平均压缩率
            }
        }
        """
        result = {}
        total_triggers = 0
        total_duration = 0.0
        layer_durations = {}
        layer_triggers = {}

        for layer, records in self._records.items():
            triggered_records = [r for r in records if r["triggered"]]
            trig_count = len(triggered_records)
            layer_triggers[layer] = trig_count
            total_triggers += trig_count

            dur_sum = sum(r["duration_ms"] for r in records)
            layer_durations[layer] = dur_sum
            total_duration += dur_sum

            if triggered_records:
                avg_before = mean(r["before"] for r in triggered_records)
                avg_after = mean(r["after"] for r in triggered_records)
                # 单次压缩率 = 1 - after/before
                ratios = [1 - (r["after"] / r["before"]) if r["before"] > 0 else 0
                          for r in triggered_records]
                avg_ratio = mean(ratios)
            else:
                avg_before = avg_after = avg_ratio = 0.0

            result[layer] = {
                "trigger_count": trig_count,
                "avg_before": round(avg_before, 2),
                "avg_after": round(avg_after, 2),
                "avg_compression_ratio": round(avg_ratio, 4),
                "avg_duration_ms": round(dur_sum / len(records) if records else 0, 4),
                "duration_sum_ms": round(dur_sum, 4),
            }

        # 计算占比
        for layer in result:
            result[layer]["trigger_ratio"] = round(
                layer_triggers[layer] / total_triggers, 4) if total_triggers > 0 else 0
            result[layer]["duration_ratio"] = round(
                layer_durations[layer] / total_duration, 4) if total_duration > 0 else 0

        # 整体平均压缩率：所有触发层的平均
        all_ratios = []
        for layer, recs in self._records.items():
            for r in recs:
                if r["triggered"] and r["before"] > 0:
                    all_ratios.append(1 - r["after"] / r["before"])
        overall_ratio = mean(all_ratios) if all_ratios else 0

        result["overall"] = {
            "total_triggers": total_triggers,
            "total_duration_ms": round(total_duration, 4),
            "avg_compression_ratio": round(overall_ratio, 4),
        }
        return result


def format_table(rows: list, headers: list) -> str:
    """生成 Markdown 表格。

    Args:
        rows: 行数据列表，每行为 list/tuple
        headers: 表头列表

    Returns:
        Markdown 表格字符串
    """
    lines = []
    lines.append("| " + " | ".join(str(h) for h in headers) + " |")
    lines.append("|" + "|".join("---" for _ in headers) + "|")
    for row in rows:
        lines.append("| " + " | ".join(str(c) for c in row) + " |")
    return "\n".join(lines)


def timed(fn, *args, **kwargs):
    """执行函数并返回 (result, duration_ms)。"""
    start = time.perf_counter()
    result = fn(*args, **kwargs)
    duration_ms = (time.perf_counter() - start) * 1000
    return result, duration_ms
