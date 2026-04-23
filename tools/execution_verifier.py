"""
执行验证框架 (Execution Verifier)

每个意图(Intent)可以注册一个"验证契约"，在主命令执行成功后，
系统会自动运行验证命令，确认操作真正生效，而不是只看 exit_code。

验证契约包含：
- verification_cmd: 验证命令模板（支持 {param} 占位符）
- expect: "zero" 或 "nonzero" —— 验证命令的期望返回码
- on_mismatch: "warn" 或 "fail" —— 验证不通过时如何处理
"""

import re
import shlex
from typing import Any, Dict, List, Optional


class VerificationResult:
    def __init__(self, passed: bool, command: str, stdout: str, stderr: str,
                 exit_code: int, message: str = ""):
        self.passed = passed
        self.command = command
        self.stdout = stdout
        self.stderr = stderr
        self.exit_code = exit_code
        self.message = message

    def to_dict(self) -> Dict[str, Any]:
        return {
            "passed": self.passed,
            "command": self.command,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "exit_code": self.exit_code,
            "message": self.message,
        }


class ExecutionVerifier:
    """执行验证器：基于意图注册表进行执行后验证。"""

    # 意图 → 验证契约
    # 每个契约是一个 dict，包含 verification_cmd / expect / on_mismatch
    REGISTRY: Dict[str, Dict[str, Any]] = {
        "create_user": {
            "verification_cmd": "id {username}",
            "expect": "zero",
            "on_mismatch": "fail",
            "description": "验证用户是否已存在于系统",
        },
        "delete_user": {
            "verification_cmd": "id {username}",
            "expect": "nonzero",
            "on_mismatch": "fail",
            "description": "验证用户是否已从系统移除",
        },
        "install_software": {
            "verification_cmd": "dpkg -l | grep -w '^{package}' || rpm -q {package}",
            "expect": "zero",
            "on_mismatch": "warn",
            "description": "验证软件包是否已安装",
        },
        "uninstall_software": {
            "verification_cmd": "dpkg -l | grep -w '^{package}' || rpm -q {package}",
            "expect": "nonzero",
            "on_mismatch": "warn",
            "description": "验证软件包是否已移除",
        },
        "manage_service": {
            "verification_cmd": "systemctl is-active {service}",
            "expect": "zero",
            "on_mismatch": "warn",
            "description": "验证服务是否处于 active 状态",
            # 注意：仅对 start/restart 操作有效；stop 需要反向验证
        },
    }

    @classmethod
    def register(cls, intent: str, verification_cmd: str, expect: str = "zero",
                 on_mismatch: str = "warn", description: str = ""):
        """动态注册验证契约（也支持运行时扩展）。"""
        cls.REGISTRY[intent] = {
            "verification_cmd": verification_cmd,
            "expect": expect,
            "on_mismatch": on_mismatch,
            "description": description,
        }

    @classmethod
    def has_verification(cls, intent: str) -> bool:
        return intent in cls.REGISTRY

    @classmethod
    def build_verification_command(cls, intent: str, params: Dict[str, Any]) -> Optional[str]:
        """根据意图和参数构建验证命令。"""
        contract = cls.REGISTRY.get(intent)
        if not contract:
            return None
        tmpl = contract["verification_cmd"]
        try:
            # 只使用 params 中存在的键进行填充，避免 KeyError
            used_keys = {k for k in re.findall(r"\{(\w+)\}", tmpl)}
            available = {k: shlex.quote(str(v)) for k, v in params.items() if k in used_keys}
            # 如果模板中有占位符但参数缺失，返回 None（跳过验证）
            if used_keys - set(available.keys()):
                return None
            return tmpl.format(**available)
        except Exception:
            return None

    @classmethod
    def verify(cls, intent: str, params: Dict[str, Any],
               system_runner, os_type: str = "linux") -> Optional[VerificationResult]:
        """
        执行验证。

        Args:
            intent: 任务意图
            params: 任务参数
            system_runner: 一个可调用对象，接收 (command, timeout) 返回 dict
            os_type: 操作系统类型

        Returns:
            VerificationResult 或 None（该意图无验证契约）
        """
        contract = cls.REGISTRY.get(intent)
        if not contract:
            return None

        # manage_service 特殊处理：只对 start/restart 验证 active，stop 验证 inactive
        if intent == "manage_service":
            action = params.get("action", "")
            if action in ("stop", "disable"):
                # 临时改写期望：服务应该是 inactive
                cmd = cls.build_verification_command(intent, params)
                if cmd:
                    result = system_runner(cmd, timeout=10)
                    stdout = result.get("stdout", "")
                    stderr = result.get("stderr", "")
                    exit_code = result.get("exit_code", -1)
                    passed = exit_code != 0  # inactive 是非零
                    return VerificationResult(
                        passed=passed,
                        command=cmd,
                        stdout=stdout,
                        stderr=stderr,
                        exit_code=exit_code,
                        message="验证通过：服务已停止" if passed else "验证警告：服务可能仍在运行",
                    )
            elif action == "status":
                return None  # status 本身不需要验证

        cmd = cls.build_verification_command(intent, params)
        if not cmd:
            return None

        result = system_runner(cmd, timeout=10)
        stdout = result.get("stdout", "")
        stderr = result.get("stderr", "")
        exit_code = result.get("exit_code", -1)

        expect = contract.get("expect", "zero")
        if expect == "zero":
            passed = exit_code == 0
        elif expect == "nonzero":
            passed = exit_code != 0
        else:
            passed = exit_code == 0

        if passed:
            message = f"执行后验证通过：{contract.get('description', '')}"
        else:
            level = contract.get("on_mismatch", "warn")
            if level == "fail":
                message = f"执行后验证未通过（视为失败）：{contract.get('description', '')}"
            else:
                message = f"执行后验证未通过（仅警告）：{contract.get('description', '')}"

        return VerificationResult(
            passed=passed,
            command=cmd,
            stdout=stdout,
            stderr=stderr,
            exit_code=exit_code,
            message=message,
        )

    @classmethod
    def get_verification_summary(cls, intent: str, params: Dict[str, Any]) -> str:
        """获取验证说明（用于前端展示或日志）。"""
        contract = cls.REGISTRY.get(intent)
        if not contract:
            return ""
        cmd = cls.build_verification_command(intent, params)
        if not cmd:
            return ""
        return f"执行后验证命令: {cmd} (期望: {contract.get('expect', 'zero')})"
