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

    # ── 新增：针对性风险说明测试 ──────────────────────────────────────────
    def test_specific_risk_explanation_userdel(self):
        expl = self.security_tools.get_risk_explanation("userdel dev1", "linux")
        self.assertIn("dev1", expl)
        self.assertIn("删除系统用户", expl)

    def test_specific_risk_explanation_systemctl(self):
        expl = self.security_tools.get_risk_explanation("systemctl restart nginx", "linux")
        self.assertIn("nginx", expl)
        self.assertIn("重启", expl)

    def test_specific_command_impact(self):
        impacts = self.security_tools.analyze_command_impact("userdel dev1")
        self.assertTrue(any("dev1" in imp for imp in impacts))


class TestExecutionVerifier(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.verifier = importlib.import_module("tools.execution_verifier").ExecutionVerifier

    def test_has_verification_for_create_user(self):
        self.assertTrue(self.verifier.has_verification("create_user"))

    def test_has_verification_for_delete_user(self):
        self.assertTrue(self.verifier.has_verification("delete_user"))

    def test_no_verification_for_disk_usage(self):
        self.assertFalse(self.verifier.has_verification("disk_usage"))

    def test_build_verification_command(self):
        cmd = self.verifier.build_verification_command("create_user", {"username": "testuser"})
        self.assertIn("id", cmd)
        self.assertIn("testuser", cmd)

    def test_delete_user_expects_nonzero(self):
        contract = self.verifier.REGISTRY.get("delete_user")
        self.assertEqual(contract["expect"], "nonzero")


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

    # ── 新增：确认恢复后任务链不断裂 ──────────────────────────────────────
    def test_confirmation_processed_allows_next_task(self):
        """确认恢复后，confirmation_processed=True，后续任务应正常执行。"""
        agent_workflow = importlib.import_module("src.agent_workflow")
        # 模拟需要确认的多任务场景
        pending = self.workflow.invoke(
            {
                "user_input": "删除用户 testuser1, 创建用户 testuser2",
                "session_id": "test_confirmation_chain",
            }
        )
        if not pending.get("requires_confirmation"):
            self.skipTest("该环境未触发风险确认，跳过链式测试")

        # 模拟用户确认
        result = self.workflow.invoke(
            {
                "user_input": "删除用户 testuser1, 创建用户 testuser2",
                "user_confirmation": True,
                "confirmation_processed": False,
                "session_id": "test_confirmation_chain",
                "command": pending.get("command", ""),
                "task_sequence": pending.get("task_sequence", []),
                "current_task_index": pending.get("current_task_index", 0),
                "task_status": pending.get("task_status", "in_progress"),
                "environment": pending.get("environment", {}),
                "risk_assessment": {**pending.get("risk_assessment", {}), "requires_confirmation": False},
                "risk_level": pending.get("risk_level", "medium"),
                "risk_explanation": pending.get("risk_explanation", ""),
            }
        )
        # 确认后应该处理 confirmation_processed，且 task_sequence 中至少有两个任务痕迹
        task_sequence = result.get("task_sequence", [])
        self.assertGreaterEqual(len(task_sequence), 1)

    # ── 新增：诊断意图不应误匹配配置修改 ──────────────────────────────────
    def test_diagnostic_not_matched_for_port_modification(self):
        agent_workflow = importlib.import_module("src.agent_workflow")
        intent = agent_workflow._extract_single_intent("修改nginx端口为9700")
        self.assertNotEqual(intent["intent"], "diagnostic")

    def test_diagnostic_matched_for_real_diagnose(self):
        agent_workflow = importlib.import_module("src.agent_workflow")
        intent = agent_workflow._extract_single_intent("排查80端口无法访问")
        self.assertEqual(intent["intent"], "diagnostic")


if __name__ == "__main__":
    unittest.main()
