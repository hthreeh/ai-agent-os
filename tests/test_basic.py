import importlib
import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestSecurityTools(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            security_module = importlib.import_module("tools.security_tools")
        except ModuleNotFoundError as exc:
            if exc.name in {"dotenv"}:
                raise unittest.SkipTest(f"security tool dependencies not installed: {exc.name}")
            raise
        cls.security_tools = security_module.SecurityTools

    def test_high_risk_command_blocked(self):
        self.assertTrue(self.security_tools.should_block_command("rm -rf /", "linux"))

    def test_low_risk_command_allowed(self):
        self.assertFalse(self.security_tools.should_block_command("df -h", "linux"))

    def test_delete_operation_requires_confirmation(self):
        risk_level = self.security_tools.assess_risk_level(
            "find /var/log -name '*.log' -delete", "linux"
        )
        self.assertEqual(risk_level, "medium")

    def test_usermod_requires_confirmation(self):
        self.assertEqual(
            self.security_tools.assess_risk_level("usermod -aG sudo dev1", "linux"),
            "medium",
        )

    def test_raw_shell_fallback_rejects_compound_commands(self):
        self.assertFalse(self.security_tools.is_safe_raw_shell_fallback("ls && whoami"))
        self.assertTrue(self.security_tools.is_safe_raw_shell_fallback("df -h"))


class TestWorkflow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            agent_workflow = importlib.import_module("src.agent_workflow")
        except ModuleNotFoundError as exc:
            if exc.name in {"langgraph", "openai"}:
                raise unittest.SkipTest(f"workflow dependencies not installed: {exc.name}")
            raise
        cls.workflow = agent_workflow.build_workflow()

    def test_multistep_planning(self):
        result = self.workflow.invoke(
            {
                "user_input": "先查看磁盘使用情况，然后查看进程状态",
                "session_id": "test_multistep",
            }
        )
        self.assertFalse(result.get("requires_confirmation", False))

    def test_risk_confirmation_required(self):
        result = self.workflow.invoke(
            {"user_input": "删除用户 testuser", "session_id": "test_risk"}
        )
        self.assertTrue(result["requires_confirmation"])

    def test_risk_confirmation_cancel(self):
        pending = self.workflow.invoke(
            {"user_input": "删除用户 testuser", "session_id": "test_risk_cancel"}
        )
        result = self.workflow.invoke(
            {
                "user_input": "删除用户 testuser",
                "user_confirmation": False,
                "session_id": "test_risk_cancel",
                "command": pending.get("command", ""),
                "task_sequence": pending.get("task_sequence", []),
                "current_task_index": pending.get("current_task_index", 0),
                "task_status": pending.get("task_status", "in_progress"),
                "environment": pending.get("environment", {}),
                "risk_assessment": pending.get("risk_assessment", {}),
                "risk_level": pending.get("risk_level", "medium"),
                "risk_explanation": pending.get("risk_explanation", ""),
            }
        )
        self.assertIn("取消", result["response"])

    def test_session_continuity(self):
        sid = "test_session_continuity"
        first = self.workflow.invoke({"user_input": "查看系统信息", "session_id": sid})
        result = self.workflow.invoke(
            {
                "user_input": "再查看进程",
                "session_id": sid,
                "conversation_history": first.get("conversation_history", []),
                "environment": first.get("environment", {}),
            }
        )
        self.assertGreaterEqual(len(result.get("conversation_history", [])), 4)


if __name__ == "__main__":
    unittest.main()
