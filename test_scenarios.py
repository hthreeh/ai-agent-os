import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.agent_workflow import (
    _parse_intents,
    _extract_single_intent,
    _is_complex_input,
    _build_task_sequence,
    _compute_execution_order,
)
from src.state_manager import StateValidator


def test_intent_parsing():
    print("=" * 60)
    print("测试 1：意图解析")
    print("=" * 60)

    test_cases = [
        ("查询磁盘使用情况", "disk_usage"),
        ("查看进程", "process_status"),
        ("查看端口", "port_status"),
        ("系统信息", "os_info"),
        ("创建用户 testuser", "create_user"),
        ("删除用户 testuser", "delete_user"),
        ("搜索 /etc 下的 .conf 文件", "search_files"),
        ("查看内存", "memory_usage"),
        ("查看CPU", "cpu_usage"),
        ("安装 nginx", "install_software"),
        ("卸载 nginx", "uninstall_software"),
        ("启动 nginx 服务", "manage_service"),
        ("查看防火墙", "check_firewall"),
        ("清理日志", "cleanup_logs"),
        ("配置 dev1 的 sudo 权限", "configure_sudo"),
        ("部署工作目录", "deploy_workspace"),
        ("排查80端口问题", "diagnostic"),
    ]

    passed = 0
    failed = 0
    for text, expected_intent in test_cases:
        result = _extract_single_intent(text)
        if result["intent"] == expected_intent:
            passed += 1
            print(f"✓ '{text}' -> {result['intent']}")
        else:
            failed += 1
            print(f"✗ '{text}' -> {result['intent']} (期望: {expected_intent})")

    print(f"\n结果: {passed}/{len(test_cases)} 通过")
    print()
    return passed, failed


def test_complex_input_detection():
    print("=" * 60)
    print("测试 2：复杂输入检测")
    print("=" * 60)

    test_cases = [
        ("查看磁盘", False),
        ("先查看磁盘，然后查看进程", True),
        ("检查磁盘空间，如果不足就清理日志", True),
        ("创建用户，配置权限", True),
        ("排查80端口无法访问的原因", True),
    ]

    passed = 0
    failed = 0
    for text, expected_complex in test_cases:
        result = _is_complex_input(text)
        if result == expected_complex:
            passed += 1
            print(f"✓ '{text}' -> 复杂={result}")
        else:
            failed += 1
            print(f"✗ '{text}' -> 复杂={result} (期望: {expected_complex})")

    print(f"\n结果: {passed}/{len(test_cases)} 通过")
    print()
    return passed, failed


def test_task_sequence_building():
    print("=" * 60)
    print("测试 3：任务序列构建")
    print("=" * 60)

    user_inputs = [
        "先查看磁盘使用情况，然后查看进程状态",
        "检查磁盘空间，如果不足就清理日志，然后安装 nginx",
        "创建新用户 dev1，配置 sudo 权限，部署工作目录",
        "排查80端口无法访问的原因",
    ]

    for user_input in user_inputs:
        print(f"\n用户输入: {user_input}")
        intents = _parse_intents(user_input)
        print(f"  识别意图数: {len(intents)}")
        for i, intent in enumerate(intents):
            print(f"  [{i}] {intent['intent']} - 参数: {intent.get('parameters', {})}")

        task_sequence = _build_task_sequence(intents)
        print(f"  任务数: {len(task_sequence)}")
        for i, task in enumerate(task_sequence):
            print(f"  [{i}] {task['intent']} - ID: {task['task_id']}")

        order = _compute_execution_order(task_sequence)
        print(f"  执行顺序: {order}")

    print()


def test_scenario_one():
    print("=" * 60)
    print("测试 4：场景一 - 磁盘检查、清理、安装")
    print("=" * 60)

    user_input = "检查磁盘空间，如果不足就清理日志，然后安装 nginx"
    print(f"用户输入: {user_input}")

    intents = _parse_intents(user_input)
    print(f"识别意图: {[i['intent'] for i in intents]}")

    for intent in intents:
        print(f"  - {intent['intent']}: {intent.get('parameters', {})}")

    task_sequence = _build_task_sequence(intents)
    print(f"任务序列长度: {len(task_sequence)}")

    cycles = StateValidator.detect_circular_dependencies(task_sequence)
    print(f"循环依赖检测: {'无' if not cycles else cycles}")

    order = _compute_execution_order(task_sequence)
    print(f"执行顺序: {order}")

    print()


def test_scenario_two():
    print("=" * 60)
    print("测试 5：场景二 - 用户创建、权限、部署")
    print("=" * 60)

    user_input = "创建新用户 dev1，配置 sudo 权限，部署工作目录"
    print(f"用户输入: {user_input}")

    intents = _parse_intents(user_input)
    print(f"识别意图: {[i['intent'] for i in intents]}")

    for intent in intents:
        print(f"  - {intent['intent']}: {intent.get('parameters', {})}")

    task_sequence = _build_task_sequence(intents)
    print(f"任务序列长度: {len(task_sequence)}")

    for i, task in enumerate(task_sequence):
        print(f"  [{i}] {task['intent']}")
        print(f"      参数: {task.get('parameters', {})}")

    print()


def test_scenario_three():
    print("=" * 60)
    print("测试 6：场景三 - 端口排查")
    print("=" * 60)

    user_input = "排查80端口无法访问的原因"
    print(f"用户输入: {user_input}")

    is_complex = _is_complex_input(user_input)
    print(f"是否复杂输入: {is_complex}")

    intents = _parse_intents(user_input)
    print(f"识别意图: {[i['intent'] for i in intents]}")

    for intent in intents:
        print(f"  - {intent['intent']}: {intent.get('parameters', {})}")

    print()


if __name__ == "__main__":
    print("\n")
    print("╔" + "═" * 58 + "╗")
    print("║" + " " * 12 + "OS Agent 连续任务编排引擎测试" + " " * 12 + "║")
    print("╚" + "═" * 58 + "╝")
    print()

    p1, f1 = test_intent_parsing()
    p2, f2 = test_complex_input_detection()
    test_task_sequence_building()
    test_scenario_one()
    test_scenario_two()
    test_scenario_three()

    total_passed = p1 + p2
    total_failed = f1 + f2
    total = total_passed + total_failed

    print("╔" + "═" * 58 + "╗")
    print(f"║" + f" 总计: {total_passed}/{total} 通过, {total_failed} 失败 " + " " * (58 - 18 - len(str(total_passed)) - len(str(total)) - len(str(total_failed))) + "║")
    print("╚" + "═" * 58 + "╝")
