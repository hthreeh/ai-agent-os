import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.agent_workflow import build_workflow, _save_session, _load_session
from tools.audit_logger import AuditLogger

audit_logger = AuditLogger()


class CLI:
    def __init__(self):
        self.workflow = build_workflow()
        self.conversation_history = []
        self.session_id = f"session_{int(time.time())}"
        self.pending_input = None

    def run(self):
        print("=" * 50)
        print("  操作系统智能代理")
        print("=" * 50)
        print("输入 'exit' 退出")
        print("输入 'history' 查看对话历史")
        print("输入 'clear' 清除对话历史")
        print("输入 'stats' 查看会话统计")
        print("示例命令:")
        print("- 查询磁盘使用情况")
        print("- 搜索文件: *.txt")
        print("- 查看进程状态")
        print("- 查看端口状态")
        print("- 创建用户 testuser")
        print("- 删除用户 testuser")
        print("- 查看系统信息")
        print("- 先查看磁盘，然后查看进程")
        print("=" * 50)

        while True:
            try:
                user_input = input("\n请输入命令: ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\n再见!")
                break

            if not user_input:
                continue
            if user_input.lower() == 'exit':
                print("再见!")
                break
            elif user_input.lower() == 'history':
                self.show_history()
                continue
            elif user_input.lower() == 'clear':
                self.clear_history()
                continue
            elif user_input.lower() == 'stats':
                self.show_stats()
                continue

            try:
                initial_state = {
                    "session_id": self.session_id,
                    "user_input": user_input,
                    "conversation_history": list(self.conversation_history),
                }

                result = self.workflow.invoke(initial_state)

                if result.get("requires_confirmation") or result.get("risk_assessment", {}).get("requires_confirmation"):
                    _save_session(self.session_id, result)
                    self._handle_confirmation(user_input, result)
                    continue

                response = result.get("response", "")
                self.conversation_history = result.get("conversation_history", self.conversation_history)

                print("\n" + "=" * 50)
                print(response)
                print("=" * 50)

                _save_session(self.session_id, result)

            except Exception as e:
                print(f"\n错误: {str(e)}")

    def _handle_confirmation(self, user_input, result):
        risk_info = result.get("risk_assessment", {})
        print("\n" + "!" * 50)
        print("  风险警告")
        print("!" * 50)
        print(f"风险等级: {risk_info.get('risk_level', 'unknown')}")
        print(f"风险解释: {risk_info.get('risk_explanation', '')}")
        print(f"缓解建议: {risk_info.get('risk_mitigation', '')}")

        impacts = risk_info.get('command_impact', [])
        if impacts:
            print("影响范围:")
            for imp in impacts:
                print(f"  - {imp}")

        env_risks = risk_info.get('environmental_risk', {}).get('environment_specific_risks', [])
        if env_risks:
            print("环境特定风险:")
            for risk in env_risks:
                print(f"  - {risk}")

        confirmation = input("\n是否确认执行此操作? (y/n): ").strip().lower()

        if confirmation == 'y':
            result = self.workflow.invoke({
                "session_id": self.session_id,
                "user_input": user_input,
                "conversation_history": list(self.conversation_history),
                "user_confirmation": True,
                "command": result.get("command", ""),
                "task_sequence": result.get("task_sequence", []),
                "current_task_index": result.get("current_task_index", 0),
                "task_status": result.get("task_status", "in_progress"),
                "environment": result.get("environment", {}),
                "risk_assessment": {**risk_info, "requires_confirmation": False},
                "risk_level": risk_info.get("risk_level", "medium"),
                "risk_explanation": risk_info.get("risk_explanation", ""),
            })
        else:
            result = self.workflow.invoke({
                "session_id": self.session_id,
                "user_input": user_input,
                "conversation_history": list(self.conversation_history),
                "user_confirmation": False,
                "command": result.get("command", ""),
                "task_sequence": result.get("task_sequence", []),
                "current_task_index": result.get("current_task_index", 0),
                "task_status": result.get("task_status", "in_progress"),
                "environment": result.get("environment", {}),
                "risk_assessment": risk_info,
                "risk_level": risk_info.get("risk_level", "medium"),
                "risk_explanation": risk_info.get("risk_explanation", ""),
            })

        self.conversation_history = result.get("conversation_history", self.conversation_history)

        print("\n" + "=" * 50)
        print(result.get("response", result.get("execution_result", "")))
        print("=" * 50)

        _save_session(self.session_id, result)

    def show_history(self):
        sessions = audit_logger.get_session_history(self.session_id)
        if not sessions:
            print("当前会话无历史记录")
            return
        print("\n对话历史:")
        print("=" * 50)
        for s in sessions:
            print(f"[{s['intent']}] 输入: {s['user_input'][:60]}")
            print(f"    响应: {s['response'][:80]}...")
            print("-" * 50)

    def clear_history(self):
        self.conversation_history = []
        print("对话历史已清除\n")

    def show_stats(self):
        stats = audit_logger.get_session_statistics(self.session_id)
        print("\n会话统计:")
        print("=" * 50)
        print(f"总交互次数: {stats.get('total_interactions', 0)}")
        print(f"高风险操作: {stats.get('high_risk_count', 0)}")
        print(f"中风险操作: {stats.get('medium_risk_count', 0)}")
        print(f"低风险操作: {stats.get('low_risk_count', 0)}")
        print(f"完成任务: {stats.get('completed_tasks', 0)}")
        print(f"失败任务: {stats.get('failed_tasks', 0)}")
        print("=" * 50 + "\n")


if __name__ == "__main__":
    cli = CLI()
    cli.run()
