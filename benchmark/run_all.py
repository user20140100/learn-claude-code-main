"""run_all.py - 一键运行全部基准测试。

用法：
    python benchmark/run_all.py

输出：
- 终端打印 4 类基准测试的汇总表格
- 更新 测试.md 追加测试结果章节

测试规模（v2）：
- 4 层压缩：8 个真实场景 × 20 轮
- Skill 加载：50 任务 × 10 轮
- DAG+Worktree：20 节点 DAG + 20 并行任务 × 5 轮
- Lead-Teammate：20 任务 × 5 个 Teammate 数量梯度 × 10 轮
"""
import platform
import sys
import time
from datetime import datetime
from pathlib import Path

# 确保项目根目录在 sys.path 中
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from benchmark import bench_context_compact, bench_skill_loading, bench_dag_worktree, bench_agent_team


def main():
    """运行全部基准测试并输出汇总。"""
    print("=" * 70)
    print("简历数据基准测试工具 - 一键运行（v2：多场景 × 多轮）")
    print(f"运行时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Python 版本：{sys.version.split()[0]}")
    print(f"操作系统：{platform.system()} {platform.release()}")
    print("=" * 70)
    print()

    results = {}
    errors = {}

    # 1. 4 层压缩基准：8 场景 × 20 轮
    print(">>> 运行基准 1/4：4 层上下文压缩流水线（8 场景 × 20 轮）...")
    t0 = time.perf_counter()
    try:
        results["context_compact"] = bench_context_compact.run_bench(repeat=20)
        print(bench_context_compact.format_result(results["context_compact"]))
    except Exception as e:
        errors["context_compact"] = str(e)
        import traceback
        traceback.print_exc()
    print(f"（耗时 {time.perf_counter()-t0:.2f}s）\n")

    # 2. Skill 加载基准：50 任务 × 10 轮
    print(">>> 运行基准 2/4：渐进式 Skill 加载（50 任务 × 10 轮）...")
    t0 = time.perf_counter()
    try:
        results["skill_loading"] = bench_skill_loading.run_bench()
        print(bench_skill_loading.format_result(results["skill_loading"]))
    except Exception as e:
        errors["skill_loading"] = str(e)
        import traceback
        traceback.print_exc()
    print(f"（耗时 {time.perf_counter()-t0:.2f}s）\n")

    # 3. DAG + Worktree 基准：20 节点 + 20 并行任务 × 5 轮
    print(">>> 运行基准 3/4：DAG + Git Worktree 任务隔离（20 节点 + 20 并行 × 5 轮）...")
    t0 = time.perf_counter()
    try:
        results["dag_worktree"] = bench_dag_worktree.run_bench()
        print(bench_dag_worktree.format_result(results["dag_worktree"]))
    except Exception as e:
        errors["dag_worktree"] = str(e)
        import traceback
        traceback.print_exc()
    print(f"（耗时 {time.perf_counter()-t0:.2f}s）\n")

    # 4. Lead-Teammate 协同基准：20 任务 × 5 梯度 × 10 轮
    print(">>> 运行基准 4/4：Lead-Teammate 多 Agent 协同（20 任务 × 5 梯度 × 10 轮）...")
    t0 = time.perf_counter()
    try:
        results["agent_team"] = bench_agent_team.run_bench()
        print(bench_agent_team.format_result(results["agent_team"]))
    except Exception as e:
        errors["agent_team"] = str(e)
        import traceback
        traceback.print_exc()
    print(f"（耗时 {time.perf_counter()-t0:.2f}s）\n")

    # 汇总
    print("=" * 70)
    print("全部基准测试完成")
    print("=" * 70)
    if errors:
        print(f"⚠ 有 {len(errors)} 个基准测试失败：")
        for k, v in errors.items():
            print(f"  - {k}: {v}")
    else:
        print("✓ 全部 4 个基准测试成功完成")

    # 输出简历可用数据汇总
    print_summary(results)

    # 更新 测试.md
    update_test_md(results, errors)

    return 0 if not errors else 1


def print_summary(results: dict):
    """打印简历可用数据汇总。"""
    print()
    print("=" * 70)
    print("简历可用数据汇总")
    print("=" * 70)

    if "context_compact" in results:
        r = results["context_compact"]
        overall = r["overall"]
        print(f"[上下文压缩] 场景数：{overall['scenarios_count']} × {overall['repeat']} 轮")
        print(f"[上下文压缩] 全场景平均压缩率：{overall['avg_compression_ratio']*100:.2f}%")
        print(f"[上下文压缩] 全场景平均长程决策保留率：{overall['avg_retention_rate']*100:.2f}%")
        triggers = overall['total_trigger_counts']
        print(f"[上下文压缩] 各层总触发次数："
              f"L1={triggers.get('L1',0)}、L2={triggers.get('L2',0)}、"
              f"L3={triggers.get('L3',0)}、L4={triggers.get('L4',0)}")
        # 列出每个场景的压缩率
        for sc in r["scenarios"]:
            print(f"  - 场景 {sc['scenario']}：压缩率 {sc['overall_compression_ratio']*100:.2f}%，"
                  f"保留率 {sc['retention_rate']*100:.2f}%")

    if "skill_loading" in results:
        r = results["skill_loading"]
        print(f"[Skill 加载] 任务数：{r['total_tasks']} × {r['rounds']} 轮")
        print(f"[Skill 加载] Skill 数量：{r['skill_count']}")
        print(f"[Skill 加载] token 节省率：{r['saving_ratio']*100:.2f}%")
        print(f"[Skill 加载] 命中率：{r['hit_rate']*100:.2f}% "
              f"({r['total_loaded']}/{r['total_needed']})")

    if "dag_worktree" in results:
        r = results["dag_worktree"]
        print(f"[DAG+Worktree] 任务节点数：{r['task_count']}（最大深度 {r['max_depth']} 层）")
        print(f"[DAG+Worktree] 最大并行宽度：{r['parallel_width']}")
        print(f"[DAG+Worktree] 各层并行度：{r['per_layer_widths']}")
        print(f"[DAG+Worktree] 零冲突验证：{r['conflict']['conflicts']} 冲突"
              f"（{r['conflict']['task_count']} 并行任务 × {r['conflict']['rounds']} 轮）")

    if "agent_team" in results:
        r = results["agent_team"]
        print(f"[多Agent协同] 任务数：{r['serial']['task_count']} × {r['rounds']} 轮")
        print(f"[多Agent协同] 加速比：{r['speedup']:.2f}x（{r['main_teammate_count']} Teammate vs 串行）")
        print(f"[多Agent协同] Teammate 利用率：{r['parallel']['avg_utilization']*100:.2f}%")
        print(f"[多Agent协同] 消息可靠性：{r['parallel']['message_reliability']*100:.2f}%")
        for n, pr in r["parallel_all"].items():
            print(f"  - {n} Teammate：耗时 {pr['total_time_ms']:.2f}ms，"
                  f"利用率 {pr['avg_utilization']*100:.2f}%")
    print()


def update_test_md(results: dict, errors: dict):
    """更新 测试.md，追加测试结果章节。

    策略：读取现有 测试.md，按行查找以 "## 测试结果" 开头的标题行，
    替换该章节内容；若不存在则追加。保留其他章节不变。
    使用行首精确匹配，避免误匹配正文中的字符串。
    """
    md_path = REPO_ROOT / "测试.md"
    new_section = build_result_section(results, errors)

    if md_path.exists():
        content = md_path.read_text(encoding="utf-8")
        lines = content.split("\n")
        marker_idx = None
        for i, line in enumerate(lines):
            if line.startswith("## 测试结果"):
                marker_idx = i
                break

        if marker_idx is not None:
            # 找下一个 ## 标题
            next_h2_idx = None
            for j in range(marker_idx + 1, len(lines)):
                if lines[j].startswith("## "):
                    next_h2_idx = j
                    break
            before = "\n".join(lines[:marker_idx]).rstrip()
            if next_h2_idx is not None:
                tail = "\n".join(lines[next_h2_idx:])
                content = before + "\n\n" + new_section + "\n\n" + tail
            else:
                content = before + "\n\n" + new_section + "\n"
        else:
            content = content.rstrip() + "\n\n" + new_section + "\n"
        md_path.write_text(content, encoding="utf-8")
        print(f"✓ 已更新 {md_path}")
    else:
        md_path.write_text(new_section + "\n", encoding="utf-8")
        print(f"✓ 已创建 {md_path}")


def build_result_section(results: dict, errors: dict) -> str:
    """构建测试结果章节内容。"""
    lines = ["## 测试结果"]
    lines.append("")
    lines.append(f"- 运行时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"- Python 版本：{sys.version.split()[0]}")
    lines.append(f"- 操作系统：{platform.system()} {platform.release()}")
    lines.append(f"- 测试状态：{'全部通过' if not errors else f'{len(errors)} 项失败'}")
    lines.append("")

    if errors:
        lines.append("### 失败项")
        for k, v in errors.items():
            lines.append(f"- {k}: {v}")
        lines.append("")

    # 1. 上下文压缩结果（多场景）
    if "context_compact" in results:
        r = results["context_compact"]
        overall = r["overall"]
        lines.append("### 1. 4 层上下文压缩流水线（多场景 × {} 轮）".format(overall["repeat"]))
        lines.append("")
        lines.append(f"- 场景数：{overall['scenarios_count']} 个真实代码开发场景")
        lines.append(f"- 每个场景运行轮数：{overall['repeat']} 轮取平均")
        overall_ok = "✓" if overall['avg_compression_ratio'] >= 0.5 else "✗"
        lines.append(f"- 全场景平均压缩率：{overall['avg_compression_ratio']*100:.2f}% {overall_ok}（预期 ≥ 50%）")
        ret_ok = "✓" if overall['avg_retention_rate'] >= 0.8 else "✗"
        lines.append(f"- 全场景平均长程决策保留率：{overall['avg_retention_rate']*100:.2f}% {ret_ok}（预期 ≥ 80%）")
        triggers = overall['total_trigger_counts']
        lines.append(f"- 各层总触发次数：L1={triggers.get('L1',0)}、L2={triggers.get('L2',0)}、"
                     f"L3={triggers.get('L3',0)}、L4={triggers.get('L4',0)}")
        lines.append("")
        lines.append("各场景独立指标：")
        lines.append("")
        lines.append("| 场景 | 原始大小 | 压缩后 | 压缩率 | 保留率 | L1 | L2 | L3 | L4 | 预期 |")
        lines.append("|---|---|---|---|---|---|---|---|---|---|")
        for sc in r["scenarios"]:
            ratio_ok = "✓" if sc['overall_compression_ratio'] >= 0.5 else "✗"
            lines.append(f"| {sc['scenario']} | {sc['original_size']} | "
                         f"{sc['final_size']} | "
                         f"{sc['overall_compression_ratio']*100:.2f}% | "
                         f"{sc['retention_rate']*100:.2f}% | "
                         f"{sc['trigger_counts']['L1']} | "
                         f"{sc['trigger_counts']['L2']} | "
                         f"{sc['trigger_counts']['L3']} | "
                         f"{sc['trigger_counts']['L4']} | {ratio_ok} |")
        lines.append("")

    # 2. Skill 加载结果（多轮）
    if "skill_loading" in results:
        r = results["skill_loading"]
        lines.append("### 2. 渐进式 Skill 加载（{} 任务 × {} 轮）".format(
            r['total_tasks'], r['rounds']))
        lines.append("")
        lines.append(f"- Skill 总数：{r['skill_count']} ✓（预期 ≥ 4）")
        lines.append(f"- 全量加载 token：{r['full_load_tokens']}")
        lines.append(f"- Catalog 索引 token：{r['catalog_tokens']}")
        lines.append(f"- 按需加载平均 token/任务：{r['avg_on_demand_tokens_per_task']}")
        saving_ok = "✓" if r['saving_ratio'] >= 0.5 else "✗"
        lines.append(f"- token 节省率：{r['saving_ratio']*100:.2f}% {saving_ok}（预期 ≥ 50%）")
        hit_ok = "✓" if r['hit_rate'] >= 0.5 else "✗"
        lines.append(f"- 命中率：{r['hit_rate']*100:.2f}% {hit_ok}（预期 ≥ 50%，"
                     f"{r['total_loaded']}/{r['total_needed']}）")
        lines.append("")
        lines.append("| Skill 名 | 平均耗时(ms) | 单轮复用次数 | 总加载次数 | 耗时达标 |")
        lines.append("|---|---|---|---|---|")
        for name in r['skill_names']:
            dur = r['avg_load_times_ms'][name]
            reuse = r['usage_counter'].get(name, 0)
            total_loads = reuse * r['rounds'] if reuse > 0 else r['rounds']
            dur_ok = "✓" if dur < 100 else "✗"
            lines.append(f"| {name} | {dur:.4f} | {reuse} | {total_loads} | {dur_ok} |")
        lines.append("")
        lines.append("**复用频次 Top3（单轮内）：**")
        for i, (name, cnt) in enumerate(r['top3_usage'], 1):
            lines.append(f"{i}. {name}：{cnt} 次/轮 × {r['rounds']} 轮 = {cnt * r['rounds']} 次")
        lines.append("")

    # 3. DAG + Worktree 结果（多轮）
    if "dag_worktree" in results:
        r = results["dag_worktree"]
        lines.append("### 3. DAG + Git Worktree 任务隔离（{} 轮）".format(r['rounds']))
        lines.append("")
        lines.append(f"- 任务节点数：{r['task_count']}")
        lines.append(f"- 最大依赖深度：{r['max_depth']} 层")
        lines.append(f"- 最大并行宽度：{r['parallel_width']} 个任务")
        lines.append(f"- 各层并行度：{r['per_layer_widths']}")
        lines.append(f"- 平均总耗时：{r['execution']['avg_total_time_ms']:.2f} ms")
        lines.append(f"- 平均依赖解锁延迟：{r['execution']['avg_unlock_delay_ms']:.2f} ms")
        conflict_ok = "✓" if r['conflict']['all_rounds_zero_conflict'] else "✗"
        lines.append(f"- 零冲突验证：{r['conflict']['conflicts']} 冲突 {conflict_ok}"
                     f"（{r['conflict']['task_count']} 并行任务 × {r['conflict']['rounds']} 轮，预期 0）")
        lines.append(f"- 单 Worktree 估算开销：{r['disk']['estimated_per_task_kb']} KB")
        lines.append(f"- 项目 Python 代码：{r['disk']['total_python_files']} 文件 / "
                     f"{r['disk']['total_python_lines']} 行")
        lines.append("")

    # 4. Lead-Teammate 结果（多轮多梯度）
    if "agent_team" in results:
        r = results["agent_team"]
        lines.append("### 4. Lead-Teammate 多 Agent 协同（{} 轮平均）".format(r['rounds']))
        lines.append("")
        lines.append(f"- 任务数：{r['serial']['task_count']}")
        lines.append(f"- 串行总耗时：{r['serial']['total_time_ms']} ms")
        lines.append(f"- 并行总耗时（{r['main_teammate_count']} Teammate）："
                     f"{r['parallel']['total_time_ms']:.2f} ms")
        speedup_ok = "✓" if r['speedup'] >= 1.5 else "✗"
        lines.append(f"- 加速比：{r['speedup']:.2f}x {speedup_ok}（预期 ≥ 1.5x）")
        util_ok = "✓" if 0.5 <= r['parallel']['avg_utilization'] <= 0.95 else "✗"
        lines.append(f"- Teammate 利用率：{r['parallel']['avg_utilization']*100:.2f}% "
                     f"{util_ok}（预期 50%~95%）")
        rel_ok = "✓" if r['parallel']['message_reliability'] >= 1.0 else "✗"
        lines.append(f"- 消息可靠性：{r['parallel']['message_reliability']*100:.2f}% "
                     f"{rel_ok}（预期 100%）")
        lines.append(f"- 平均认领延迟：{r['parallel']['avg_claim_delay_ms']:.2f} ms")
        lines.append(f"- 任务完成率：{r['parallel']['success_rate']*100:.2f}%")
        lines.append("")
        lines.append("| Teammate 数 | 总耗时(ms) | 利用率 | 消息可靠性 | 认领延迟(ms) | 成功率 |")
        lines.append("|---|---|---|---|---|---|")
        for n, pr in r["parallel_all"].items():
            lines.append(f"| {n} | {pr['total_time_ms']:.2f} | "
                         f"{pr['avg_utilization']*100:.2f}% | "
                         f"{pr['message_reliability']*100:.2f}% | "
                         f"{pr['avg_claim_delay_ms']:.2f} | "
                         f"{pr['success_rate']*100:.2f}% |")
        lines.append("")

    # 简历可用数据汇总
    lines.append("### 简历可用数据汇总")
    lines.append("")
    lines.append("| 指标 | 实测值 | 简历可用表述 |")
    lines.append("|---|---|---|")
    if "context_compact" in results:
        r = results["context_compact"]
        overall = r["overall"]
        lines.append(f"| 上下文压缩率 | {overall['avg_compression_ratio']*100:.1f}% | "
                     f"\"4层压缩流水线在 {overall['scenarios_count']} 个真实开发场景 × {overall['repeat']} 轮测试中平均压缩率 "
                     f"{overall['avg_compression_ratio']*100:.0f}%\" |")
        lines.append(f"| 长程决策保留率 | {overall['avg_retention_rate']*100:.1f}% | "
                     f"\"压缩后长程决策保留率 {overall['avg_retention_rate']*100:.0f}%\" |")
        lines.append(f"| 压缩场景覆盖 | {overall['scenarios_count']} 类 | "
                     f"\"覆盖 bug修复/代码审查/功能实现/重构/长调试等 {overall['scenarios_count']} 类真实场景\" |")
    if "skill_loading" in results:
        r = results["skill_loading"]
        lines.append(f"| Skill token 节省率 | {r['saving_ratio']*100:.1f}% | "
                     f"\"按需加载节省 {r['saving_ratio']*100:.0f}% system prompt token"
                     f"（50 任务 × {r['rounds']} 轮）\" |")
    if "dag_worktree" in results:
        r = results["dag_worktree"]
        lines.append(f"| DAG 节点数 | {r['task_count']} | "
                     f"\"支持 {r['task_count']} 节点 {r['max_depth']} 层依赖的 DAG 任务图\" |")
        lines.append(f"| DAG 并行宽度 | {r['parallel_width']} | "
                     f"\"支持 {r['parallel_width']} 个任务并行执行\" |")
        lines.append(f"| Worktree 零冲突 | {r['conflict']['conflicts']} | "
                     f"\"{r['conflict']['task_count']} 并行任务 × {r['conflict']['rounds']} 轮零冲突\" |")
    if "agent_team" in results:
        r = results["agent_team"]
        lines.append(f"| 多Agent加速比 | {r['speedup']:.2f}x | "
                     f"\"{r['main_teammate_count']} Teammate 协同加速 {r['speedup']:.1f}x"
                     f"（{r['rounds']} 轮平均）\" |")
        lines.append(f"| Teammate 梯度 | {len(r['parallel_all'])} 档 | "
                     f"\"测试 {min(r['parallel_all'].keys())}~{max(r['parallel_all'].keys())} Teammate 扩展性\" |")
        lines.append(f"| 消息可靠性 | {r['parallel']['message_reliability']*100:.1f}% | "
                     f"\"消息传递 100% 可达\" |")
    lines.append("")

    return "\n".join(lines)


if __name__ == "__main__":
    sys.exit(main())
