"""bench_skill_loading.py - 渐进式 Skill 加载基准测试。

通过动态加载 s08 模块（已扫描 skills/ 目录），采集：
- Skill 总数
- 全量加载 vs 按需加载的 system prompt token 估算
- token 节省率
- 各 Skill 加载耗时（多轮平均）
- 命中率与复用频次 Top3

测试规模：
- 50 个真实代码开发任务（由 build_skill_tasks 生成）
- 每轮模拟全部 50 个任务，共运行 10 轮取平均
"""
import statistics
from pathlib import Path

from benchmark.module_loader import load_chapter_module
from benchmark.sample_data import build_skill_tasks
from benchmark.metrics import estimate_tokens, format_table, timed


# 默认测试轮数：每轮模拟 50 个任务，多轮取平均以稳定加载耗时
DEFAULT_ROUNDS = 10


def run_bench(rounds: int = DEFAULT_ROUNDS) -> dict:
    """运行 Skill 加载基准测试。

    Args:
        rounds: 测试轮数，每轮模拟全部任务集，多轮取平均

    Returns:
        包含 Skill 总数、token 节省率、加载耗时、复用频次等指标的字典
    """
    # 加载 s08 模块（会自动扫描 skills/ 目录）
    repo_root = Path(__file__).resolve().parents[1]
    module, temp_dir, _ = load_chapter_module("s08", temp_cwd=repo_root)

    # 获取 Skill 注册表
    registry = module.SKILL_REGISTRY
    skill_names = list(registry.keys())
    skill_count = len(skill_names)

    # === 1. 全量加载 token 估算 ===
    # 全量：所有 SKILL.md 内容拼接到 system prompt
    full_load_content = ""
    for name in skill_names:
        full_load_content += registry[name]["content"] + "\n\n"
    full_load_tokens = estimate_tokens(full_load_content)

    # === 2. 按需加载 token 估算 ===
    # 按需：仅 catalog（名称+描述）+ 命中 Skill 全文
    catalog_content = module.list_skills()
    catalog_tokens = estimate_tokens(catalog_content)

    # 模拟任务集（50 个），统计命中与复用
    tasks = build_skill_tasks()
    usage_counter = {name: 0 for name in skill_names}
    total_needed = 0
    total_loaded = 0
    on_demand_tokens_total = 0
    load_times = {name: [] for name in skill_names}

    # 多轮运行，每轮重置 usage_counter 但累计 load_times
    usage_per_round = []

    for _round in range(rounds):
        round_loaded = 0
        round_needed = 0
        round_tokens = 0
        for task_name, needed_skills in tasks:
            round_needed += len(needed_skills)
            # 每个任务都支付 catalog 成本
            task_tokens = catalog_tokens
            for skill_name in needed_skills:
                if skill_name in registry:
                    # 测量 load_skill 耗时
                    content, dur = timed(module.load_skill, skill_name)
                    load_times[skill_name].append(dur)
                    if _round == 0:  # 仅第一轮累计 usage_counter
                        usage_counter[skill_name] += 1
                    round_loaded += 1
                    task_tokens += estimate_tokens(content)
            round_tokens += task_tokens

        total_needed = round_needed  # 每轮相同
        total_loaded += round_loaded
        on_demand_tokens_total += round_tokens
        usage_per_round.append((round_loaded, round_needed, round_tokens))

    # 平均每轮的指标
    avg_on_demand_tokens_per_task = on_demand_tokens_total / (rounds * len(tasks)) if tasks else 0
    avg_loaded_per_round = total_loaded / rounds

    # === 3. token 节省率 ===
    # 对比：全量加载（每个任务都支付 full_load_tokens）
    #      vs 按需加载（每个任务支付 avg_on_demand_tokens_per_task）
    saving_ratio = 1 - (avg_on_demand_tokens_per_task / full_load_tokens) if full_load_tokens > 0 else 0

    # === 4. 命中率（按全部轮次平均） ===
    total_needed_all = total_needed * rounds
    hit_rate = total_loaded / total_needed_all if total_needed_all > 0 else 0

    # === 5. 复用频次 Top3（基于第一轮的 usage_counter） ===
    top3 = sorted(usage_counter.items(), key=lambda x: x[1], reverse=True)[:3]

    # === 6. 各 Skill 加载耗时（多轮平均） ===
    avg_load_times = {}
    for name in skill_names:
        if load_times[name]:
            avg_load_times[name] = statistics.mean(load_times[name])
        else:
            # 未被任务使用，单独测一次
            _, dur = timed(module.load_skill, name)
            avg_load_times[name] = dur

    return {
        "skill_count": skill_count,
        "skill_names": skill_names,
        "full_load_tokens": full_load_tokens,
        "catalog_tokens": catalog_tokens,
        "avg_on_demand_tokens_per_task": int(avg_on_demand_tokens_per_task),
        "saving_ratio": round(saving_ratio, 4),
        "hit_rate": round(hit_rate, 4),
        "total_tasks": len(tasks),
        "rounds": rounds,
        "total_needed": total_needed_all,
        "total_loaded": total_loaded,
        "top3_usage": top3,
        "usage_counter": dict(usage_counter),
        "avg_load_times_ms": {k: round(v, 4) for k, v in avg_load_times.items()},
    }


def format_result(result: dict) -> str:
    """格式化 Skill 加载基准结果。"""
    lines = []
    lines.append("=" * 60)
    lines.append("基准测试 2：渐进式 Skill 加载（{} 任务 × {} 轮）".format(
        result['total_tasks'], result['rounds']))
    lines.append("=" * 60)
    lines.append(f"Skill 总数：{result['skill_count']}")
    lines.append(f"Skill 列表：{', '.join(result['skill_names'])}")
    lines.append(f"全量加载 token 估算：{result['full_load_tokens']}")
    lines.append(f"Catalog 索引 token：{result['catalog_tokens']}")
    lines.append(f"按需加载平均 token/任务：{result['avg_on_demand_tokens_per_task']}")
    lines.append(f"token 节省率：{result['saving_ratio']*100:.2f}%")
    lines.append(f"任务数：{result['total_tasks']}（每轮），共 {result['rounds']} 轮")
    lines.append(f"命中率：{result['hit_rate']*100:.2f}% "
                 f"({result['total_loaded']}/{result['total_needed']})")
    lines.append("")
    lines.append("各 Skill 加载耗时（多轮平均）：")
    headers = ["Skill 名", "平均耗时(ms)", "复用次数", "总加载次数"]
    rows = []
    for name in result['skill_names']:
        # 总加载次数 = 复用次数 × 轮数（仅当复用次数>0）
        reuse = result['usage_counter'].get(name, 0)
        total_loads = reuse * result['rounds'] if reuse > 0 else result['rounds']
        rows.append([
            name,
            f"{result['avg_load_times_ms'][name]:.4f}",
            reuse,
            total_loads,
        ])
    lines.append(format_table(rows, headers))
    lines.append("")
    lines.append("复用频次 Top3（单轮内）：")
    for i, (name, cnt) in enumerate(result['top3_usage'], 1):
        lines.append(f"  {i}. {name}：{cnt} 次/轮 × {result['rounds']} 轮 = {cnt * result['rounds']} 次")
    lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    result = run_bench()
    print(format_result(result))
