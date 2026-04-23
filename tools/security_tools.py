import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from config.config import HIGH_RISK_COMMANDS


class SecurityTools:
    # 原始 Shell 控制令牌（用于判断是否安全的兜底命令）
    RAW_SHELL_CONTROL_TOKENS = (";", "&&", "||", "|", "`", "$(", "\n", "\r")

    # OS 特定高危命令（补充 config.HIGH_RISK_COMMANDS 未涵盖的部分）
    OS_SPECIFIC_RISK_COMMANDS = {
        "windows": [
            "format",
            "diskpart",
            "del /f /s /q",
            "rd /s /q",
            "reg delete",
            "net user /delete",
            "shutdown /s /t 0",
            "taskkill /f /im",
        ],
        # Linux 部分：config.HIGH_RISK_COMMANDS 已全面覆盖，此处仅补充额外场景
        "linux": [
            "rm --no-preserve-root",
            "wipefs",
            ":() { :|:& };:",   # fork 炸弹
            "mv /* /dev/null",
        ],
    }

    @staticmethod
    def is_high_risk_command(command, os_type="linux"):
        """判断命令是否触发高危规则"""
        command_lower = (command or "").lower().strip()

        # 检查全局高危列表（config.py 中定义）
        for risk_cmd in HIGH_RISK_COMMANDS:
            if risk_cmd in command_lower:
                return True

        # 检查 OS 特定高危列表
        os_risk_commands = SecurityTools.OS_SPECIFIC_RISK_COMMANDS.get(os_type, [])
        for risk_cmd in os_risk_commands:
            if risk_cmd in command_lower:
                return True

        return False

    @staticmethod
    def is_safe_raw_shell_fallback(command: str) -> bool:
        """判断原始 Shell 命令兜底是否安全（不含控制令牌）"""
        candidate = (command or "").strip()
        if not candidate:
            return False
        return not any(token in candidate for token in SecurityTools.RAW_SHELL_CONTROL_TOKENS)

    @staticmethod
    def assess_risk_level(command, os_type="linux"):
        """三级风险评估：high / medium / low / unknown"""
        command_lower = (command or "").lower()
        if SecurityTools.is_high_risk_command(command, os_type):
            return "high"
        if any(
            keyword in command_lower
            for keyword in [
                "rm", "chmod", "chown", "userdel", "groupdel",
                "passwd", "su", "sudo", "del", "rd", "reg",
                "taskkill", "-delete", "usermod",
            ]
        ):
            return "medium"
        if any(
            keyword in command_lower
            for keyword in [
                "ls", "df", "ps", "netstat", "ss", "find", "useradd",
                "dir", "wmic", "tasklist", "free", "top", "uptime",
                "cat", "grep", "tail", "head", "who", "uname", "ip",
                "systemctl status", "docker ps", "ping",
            ]
        ):
            return "low"
        return "unknown"

    @staticmethod
    def get_risk_explanation(command, os_type="linux"):
        """生成风险说明文本"""
        command_lower = (command or "").lower()
        if SecurityTools.is_high_risk_command(command, os_type):
            # 找到第一个触发的规则
            for risk_cmd in HIGH_RISK_COMMANDS:
                if risk_cmd in command_lower:
                    return (
                        f"命令包含高危操作符 '{risk_cmd}'，可能导致严重系统损坏或数据丢失。\n\n"
                        "风险评估依据：\n"
                        "- 操作类型：系统级修改\n"
                        "- 潜在影响：关键系统资源受损\n"
                        "- 恢复难度：高\n"
                        "- 安全等级：不允许自动执行"
                    )
            for risk_cmd in SecurityTools.OS_SPECIFIC_RISK_COMMANDS.get(os_type, []):
                if risk_cmd in command_lower:
                    return (
                        f"命令包含 {os_type} 环境下的高危操作 '{risk_cmd}'，可能导致严重系统风险。\n\n"
                        "风险评估依据：\n"
                        "- 操作类型：系统级修改\n"
                        "- 潜在影响：关键系统资源受损\n"
                        "- 恢复难度：高\n"
                        "- 安全等级：不允许自动执行"
                    )
        if any(keyword in command_lower for keyword in
               ["rm", "chmod", "chown", "userdel", "groupdel", "del", "rd", "reg", "-delete", "usermod"]):
            return (
                "命令包含可能影响系统安全或数据完整性的修改类操作。\n\n"
                "风险评估依据：\n"
                "- 操作类型：系统修改\n"
                "- 潜在影响：中等系统影响\n"
                "- 恢复难度：中等\n"
                "- 安全等级：需要确认"
            )
        if any(keyword in command_lower for keyword in ["passwd", "su", "sudo"]):
            return (
                "命令涉及权限提升或密码管理，需要谨慎处理。\n\n"
                "风险评估依据：\n"
                "- 操作类型：权限管理\n"
                "- 潜在影响：权限风险\n"
                "- 恢复难度：中等\n"
                "- 安全等级：需要确认"
            )
        return (
            "命令属于系统信息查询或低风险操作。\n\n"
            "风险评估依据：\n"
            "- 操作类型：信息查询或安全操作\n"
            "- 潜在影响：很小\n"
            "- 恢复难度：无需恢复\n"
            "- 安全等级：可自动执行"
        )

    @staticmethod
    def get_risk_mitigation_suggestion(command, os_type="linux"):
        risk_level = SecurityTools.assess_risk_level(command, os_type)
        if risk_level == "high":
            return (
                "该命令已被安全策略阻止。建议改用更小范围、更可回滚的安全操作，"
                "并在测试环境验证后再执行。"
            )
        if risk_level == "medium":
            return "该命令需要人工确认。请先检查目标范围、权限前提、影响面和回滚方案。"
        return "该命令无特殊限制，但仍建议保留日志并遵循最小权限原则。"

    @staticmethod
    def should_block_command(command, os_type="linux"):
        return SecurityTools.assess_risk_level(command, os_type) == "high"

    @staticmethod
    def analyze_command_impact(command, os_type="linux"):
        command_lower = (command or "").lower()
        impacts = []

        if "rm" in command_lower or "del" in command_lower:
            impacts.append("文件系统修改")
        if "-delete" in command_lower:
            impacts.append("文件删除")
        if "chmod" in command_lower or "chown" in command_lower:
            impacts.append("权限变更")
        if "usermod" in command_lower:
            impacts.append("用户权限变更")
        if "userdel" in command_lower or "groupdel" in command_lower or "net user /delete" in command_lower:
            impacts.append("用户/组管理")
        if "passwd" in command_lower:
            impacts.append("密码修改")
        if "su" in command_lower or "sudo" in command_lower:
            impacts.append("权限提升")
        if "format" in command_lower or "dd" in command_lower or "diskpart" in command_lower:
            impacts.append("磁盘修改")
        if "reg" in command_lower:
            impacts.append("注册表修改")
        if "shutdown" in command_lower or "reboot" in command_lower or "halt" in command_lower:
            impacts.append("系统关机/重启")

        if not impacts:
            impacts.append("信息查询")

        return impacts

    @staticmethod
    def get_environment_specific_risks(os_type):
        environment_risks = {
            "windows": [
                "注册表修改可能导致系统不稳定",
                "磁盘操作可能导致数据丢失",
                "强制终止进程可能影响关键系统服务",
            ],
            "linux": [
                "root 权限操作可能导致系统级损坏",
                "文件权限变更可能影响系统安全",
                "系统关机/重启可能中断服务",
                "网络配置变更可能影响连通性",
            ],
        }
        return environment_risks.get(os_type, [])

    @staticmethod
    def assess_environmental_risk(command, environment_info):
        os_type = environment_info.get("os_type", "linux")
        risk_level = SecurityTools.assess_risk_level(command, os_type)
        environment_risks = SecurityTools.get_environment_specific_risks(os_type)

        command_lower = (command or "").lower()
        if os_type == "windows" and "reg" in command_lower:
            risk_level = "high" if risk_level != "high" else risk_level
        elif os_type == "linux" and "sudo" in command_lower:
            risk_level = "medium" if risk_level == "low" else risk_level

        return {
            "risk_level": risk_level,
            "environment_specific_risks": environment_risks,
            "os_type": os_type,
        }
