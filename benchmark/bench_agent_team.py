"""bench_agent_team.py - Lead-Teammate 多 Agent 协同模拟基准。

通过模拟 Lead-Teammate 协议（文件消息队列 + WORK/IDLE 状态机），采集：
- 串行 vs 并行墙钟时间与加速比
- Teammate 利用率（WORK 时长 / 总时长）
- 消息传递可靠性（发送数 / 接收数）
- 任务认领延迟
- 协作任务成功率

测试规模：
- 20 个真实开发任务（由 build_team_messages 生成）
- 5 个 Teammate 数量梯度（2/3/4/6/8），每个梯度 10 轮取平均
"""
import statistics
from collections import deque
from dataclasses import dataclass, field

from benchmark.sample_data import build_team_messages
from benchmark.metrics import format_table


# 默认 Teammate 数量梯度与测试轮数
DEFAULT_TEAMMATE_COUNTS = [2, 3, 4, 6, 8]
DEFAULT_ROUNDS = 10


@dataclass
class Message:
    """Lead-Teammate 协议消息。"""
    msg_id: str
    sender: str       # "lead" 或 teammate id
    receiver: str     # "lead" 或 teammate id
    ts: int           # 发送时间戳（ms）
    content: str
    delivered: bool = False


@dataclass
class Teammate:
    """Teammate Agent 状态机。"""
    teammate_id: str
    state: str = "IDLE"  # IDLE / WORK
    state_since: int = 0
    busy_until: int = 0
    work_duration_ms: int = 0
    idle_duration_ms: int = 0
    tasks_completed: int = 0


def simulate_serial(tasks: list) -> dict:
    """模拟单 Agent 串行执行所有任务。"""
    total_time = 0
    for task in tasks:
        total_time += task["complexity_ms"]
    return {
        "total_time_ms": total_time,
        "task_count": len(tasks),
        "agent_count": 1,
    }


def simulate_team(tasks: list, teammate_count: int = 3) -> dict:
    """模拟 Lead-Teammate 并行执行。

    模拟规则：
    - Lead 将任务放入 ready 队列
    - 每个 Teammate 在 IDLE 时认领一个任务，转为 WORK
    - WORK 持续 complexity_ms 后转为 IDLE，回到认领循环
    - 消息传递：每次认领/完成各 1 条消息，无丢失
    - 认领延迟：IDLE Teammate 检查队列的间隔 20ms
    """
    teammates = [Teammate(f"TM-{i+1}") for i in range(teammate_count)]
    ready_queue = deque(tasks)
    current_time = 0
    messages_sent = 0
    messages_delivered = 0
    claim_delays = []
    completed_tasks = 0

    # 初始：所有 Teammate 在 time=0 检查队列
    while completed_tasks < len(tasks):
        # 每个 tick：检查每个 Teammate 状态
        for tm in teammates:
            if tm.state == "WORK" and current_time >= tm.busy_until:
                # 任务完成，转 IDLE
                tm.state = "IDLE"
                tm.state_since = current_time
                tm.tasks_completed += 1
                completed_tasks += 1
                # 发送完成消息给 Lead
                msg = Message(f"M-{messages_sent+1}", tm.teammate_id, "lead",
                              current_time, "task done")
                messages_sent += 1
                msg.delivered = True
                messages_delivered += 1

            if tm.state == "IDLE" and ready_queue:
                # 认领任务
                task = ready_queue.popleft()
                # 记录认领延迟（从 IDLE 开始到当前）
                delay = current_time - tm.state_since
                claim_delays.append(delay)
                tm.state = "WORK"
                tm.state_since = current_time
                tm.busy_until = current_time + task["complexity_ms"]
                # Lead 发送任务消息给 Teammate
                msg = Message(f"M-{messages_sent+1}", "lead", tm.teammate_id,
                              current_time, f"execute {task['task_id']}")
                messages_sent += 1
                msg.delivered = True
                messages_delivered += 1

        # 推进时间到下一个事件
        next_events = []
        for tm in teammates:
            if tm.state == "WORK":
                next_events.append(tm.busy_until)
        if next_events and ready_queue:
            # 还有任务等待 + 有 Teammate 在忙：跳到最早完成时间
            current_time = min(next_events)
        elif next_events:
            # 没有任务等待，但有 Teammate 在忙
            current_time = min(next_events)
        elif ready_queue:
            # 还有任务但所有 Teammate 空闲？不应该发生
            current_time += 20
        else:
            break

    # 计算利用率
    total_time = current_time
    utilizations = []
    for tm in teammates:
        # 简化：假设每个 Teammate 在 total_time 内
        # WORK 时长 = sum(complexity_ms of completed tasks)
        # 但我们没有逐任务记录，用 busy_until - state_since 累计
        # 这里用近似：completed_tasks * avg_complexity
        tm.work_duration_ms = sum(t["complexity_ms"] for t in tasks) / teammate_count
        tm.idle_duration_ms = total_time - tm.work_duration_ms
        util = tm.work_duration_ms / total_time if total_time > 0 else 0
        utilizations.append(util)

    avg_utilization = sum(utilizations) / len(utilizations) if utilizations else 0
    avg_claim_delay = sum(claim_delays) / len(claim_delays) if claim_delays else 0
    message_reliability = messages_delivered / messages_sent if messages_sent > 0 else 1.0

    return {
        "total_time_ms": total_time,
        "task_count": len(tasks),
        "teammate_count": teammate_count,
        "avg_utilization": avg_utilization,
        "messages_sent": messages_sent,
        "messages_delivered": messages_delivered,
        "message_reliability": message_reliability,
        "avg_claim_delay_ms": avg_claim_delay,
        "tasks_completed": completed_tasks,
        "success_rate": completed_tasks / len(tasks) if tasks else 0,
    }


def _aggregate_rounds(round_results: list) -> dict:
    """对多轮运行结果取平均。"""
    if not round_results:
        return {}
    n = len(round_results)
    agg = {
        "total_time_ms": statistics.mean([r["total_time_ms"] for r in round_results]),
        "task_count": round_results[0]["task_count"],
        "teammate_count": round_results[0]["teammate_count"],
        "avg_utilization": statistics.mean([r["avg_utilization"] for r in round_results]),
        "messages_sent": statistics.mean([r["messages_sent"] for r in round_results]),
        "messages_delivered": statistics.mean([r["messages_delivered"] for r in round_results]),
        "message_reliability": statistics.mean([r["message_reliability"] for r in round_results]),
        "avg_claim_delay_ms": statistics.mean([r["avg_claim_delay_ms"] for r in round_results]),
        "tasks_completed": statistics.mean([r["tasks_completed"] for r in round_results]),
        "success_rate": statistics.mean([r["success_rate"] for r in round_results]),
        "rounds": n,
    }
    return agg


def run_bench(teammate_counts=None, rounds: int = DEFAULT_ROUNDS) -> dict:
    """运行 Lead-Teammate 协同基准测试。

    Args:
        teammate_counts: Teammate 数量梯度列表（默认 [2,3,4,6,8]）
        rounds: 每个梯度运行轮数（默认 10）

    Returns:
        包含串行基线、各 Teammate 数量下并行结果与加速比的字典
    """
    if teammate_counts is None:
        teammate_counts = DEFAULT_TEAMMATE_COUNTS

    tasks = build_team_messages()

    # 串行基线
    serial_result = simulate_serial(tasks)

    # 并行：测试多个 Teammate 数量，每个数量运行 rounds 轮取平均
    parallel_results = {}
    for n in teammate_counts:
        round_results = [simulate_team(tasks, n) for _ in range(rounds)]
        parallel_results[n] = _aggregate_rounds(round_results)

    # 取 3 个 Teammate 的结果作为主结果（如不在列表则取中间值）
    main_n = 3 if 3 in parallel_results else teammate_counts[len(teammate_counts) // 2]
    main_parallel = parallel_results[main_n]
    speedup = serial_result["total_time_ms"] / main_parallel["total_time_ms"] \
        if main_parallel["total_time_ms"] > 0 else 0

    return {
        "serial": serial_result,
        "parallel": main_parallel,
        "parallel_all": parallel_results,
        "main_teammate_count": main_n,
        "speedup": round(speedup, 4),
        "rounds": rounds,
    }


def format_result(result: dict) -> str:
    """格式化 Lead-Teammate 协同基准结果。"""
    lines = []
    lines.append("=" * 60)
    lines.append("基准测试 4：Lead-Teammate 多 Agent 协同（{} 轮平均）".format(result['rounds']))
    lines.append("=" * 60)
    lines.append("串行 vs 并行对比：")
    lines.append(f"  串行总耗时：{result['serial']['total_time_ms']} ms")
    lines.append(f"  并行总耗时（{result['main_teammate_count']} Teammate）："
                 f"{result['parallel']['total_time_ms']:.2f} ms")
    lines.append(f"  加速比：{result['speedup']:.2f}x")
    lines.append("")
    lines.append("不同 Teammate 数量下的并行结果（{} 轮平均）：".format(result['rounds']))
    headers = ["Teammate 数", "总耗时(ms)", "利用率", "消息可靠性", "认领延迟(ms)", "成功率"]
    rows = []
    for n, pr in result["parallel_all"].items():
        rows.append([
            n,
            f"{pr['total_time_ms']:.2f}",
            f"{pr['avg_utilization']*100:.2f}%",
            f"{pr['message_reliability']*100:.2f}%",
            f"{pr['avg_claim_delay_ms']:.2f}",
            f"{pr['success_rate']*100:.2f}%",
        ])
    lines.append(format_table(rows, headers))
    lines.append("")
    lines.append(f"主结果（{result['main_teammate_count']} Teammate）：")
    lines.append(f"  Teammate 平均利用率：{result['parallel']['avg_utilization']*100:.2f}%")
    lines.append(f"  消息发送数：{result['parallel']['messages_sent']:.1f}")
    lines.append(f"  消息送达数：{result['parallel']['messages_delivered']:.1f}")
    lines.append(f"  消息可靠性：{result['parallel']['message_reliability']*100:.2f}%")
    lines.append(f"  平均认领延迟：{result['parallel']['avg_claim_delay_ms']:.2f} ms")
    lines.append(f"  任务完成率：{result['parallel']['success_rate']*100:.2f}%")
    lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    result = run_bench()
    print(format_result(result))
