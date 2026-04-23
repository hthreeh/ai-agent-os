"""
安全控制工具 —— 基于命令结构解析的风险分析

核心改进：
1. 不再使用固定模板，而是解析命令结构（动作+目标+参数）动态生成风险说明。
2. analyze_command_impact 提取命令中的具体对象（用户名、服务名、路径等）。
3. 支持外部注册自定义风险分析器（便于扩展新意图）。
"""

import os
import re
from typing import Any, Dict, List, Callable

# 保留原有的 HIGH_RISK_COMMANDS 导入
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
        "linux": [
            "rm --no-preserve-root",
            "wipefs",
            ":() { :|:& };:",   # fork 炸弹
            "mv /* /dev/null",
        ],
    }

    # ── 外部可扩展的风险分析器注册表 ──────────────────────────────────────────
    _risk_analyzers: List[Callable[[str, str, str], Dict[str, Any]]] = []

    @classmethod
    def register_risk_analyzer(cls, analyzer: Callable[[str, str, str], Dict[str, Any]]):
        """注册一个自定义风险分析器。签名: (command, command_lower, os_type) -> dict 或 None"""
        cls._risk_analyzers.append(analyzer)

    # ── 基础判断 ──────────────────────────────────────────────────────────────
    @staticmethod
    def is_high_risk_command(command, os_type="linux"):
        """判断命令是否触发高危规则"""
        command_lower = (command or "").lower().strip()

        for risk_cmd in HIGH_RISK_COMMANDS:
            if risk_cmd in command_lower:
                return True

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
        if "sed -i" in command_lower:
            return "medium"
        if any(
            keyword in command_lower
            for keyword in [
                "ls", "df", "ps", "netstat", "ss", "find", "useradd",
                "dir", "wmic", "tasklist", "free", "top", "uptime",
                "cat", "grep", "tail", "head", "who", "uname", "ip",
                "systemctl status", "docker ps", "ping", "echo",
            ]
        ):
            return "low"
        return "unknown"

    # ── 针对性风险说明（核心改进）─────────────────────────────────────────────
    @staticmethod
    def get_risk_explanation(command, os_type="linux"):
        """生成风险说明文本。优先使用命令结构解析生成针对性说明。"""
        command_lower = (command or "").lower().strip()

        # 高危：直接拦截
        if SecurityTools.is_high_risk_command(command, os_type):
            triggered = None
            for risk_cmd in HIGH_RISK_COMMANDS:
                if risk_cmd in command_lower:
                    triggered = risk_cmd
                    break
            if not triggered:
                for risk_cmd in SecurityTools.OS_SPECIFIC_RISK_COMMANDS.get(os_type, []):
                    if risk_cmd in command_lower:
                        triggered = risk_cmd
                        break
            return (
                f"命令包含高危操作符 '{triggered or '未知'}'，可能导致严重系统损坏或数据丢失。\n\n"
                "风险评估依据：\n"
                "- 操作类型：系统级修改\n"
                "- 潜在影响：关键系统资源受损\n"
                "- 恢复难度：高\n"
                "- 安全等级：不允许自动执行"
            )

        # 尝试外部注册的分析器
        for analyzer in SecurityTools._risk_analyzers:
            try:
                result = analyzer(command, command_lower, os_type)
                if result and result.get("explanation"):
                    return result["explanation"]
            except Exception:
                pass

        # 内置针对性分析
        specific = SecurityTools._analyze_specific_risk(command, command_lower)
        if specific:
            return specific

        # fallback 到通用模板
        if SecurityTools.assess_risk_level(command, os_type) == "medium":
            return (
                "命令包含可能影响系统安全或数据完整性的修改类操作。\n\n"
                "风险评估依据：\n"
                "- 操作类型：系统修改\n"
                "- 潜在影响：中等系统影响\n"
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
    def _analyze_specific_risk(command: str, command_lower: str) -> str:
        """基于命令结构解析生成针对性风险说明。返回空字符串表示无法解析。"""
        import re

        # userdel
        m = re.search(r'userdel\s+([a-zA-Z_][a-zA-Z0-9_-]*)', command)
        if m:
            user = m.group(1)
            return (
                f"将删除系统用户 '{user}'。\n\n"
                "风险评估依据：\n"
                "- 操作类型：用户账户删除\n"
                f"- 潜在影响：用户 {user} 将无法登录，其家目录和邮件池可能被删除\n"
                "- 恢复难度：中等（需重新创建用户并恢复权限）\n"
                "- 安全等级：需要确认"
            )

        # useradd / adduser
        m = re.search(r'(?:useradd|adduser)\s+([a-zA-Z_][a-zA-Z0-9_-]*)', command)
        if m and "delete" not in command_lower:
            user = m.group(1)
            return (
                f"将创建新的系统用户 '{user}'。\n\n"
                "风险评估依据：\n"
                "- 操作类型：用户账户创建\n"
                f"- 潜在影响：新增系统账户 {user}，可能被用于未授权访问\n"
                "- 恢复难度：低（可删除该用户）\n"
                "- 安全等级：需要确认"
            )

        # usermod
        m = re.search(r'usermod\s+.*\s+([a-zA-Z_][a-zA-Z0-9_-]*)\s*$', command)
        if m:
            user = m.group(1)
            return (
                f"将修改用户 '{user}' 的权限或组属性。\n\n"
                "风险评估依据：\n"
                "- 操作类型：权限变更\n"
                f"- 潜在影响：用户 {user} 的权限范围可能扩大或缩小\n"
                "- 恢复难度：中等\n"
                "- 安全等级：需要确认"
            )

        # systemctl restart/start/stop/reload
        m = re.search(r'systemctl\s+(restart|start|stop|reload)\s+([a-zA-Z0-9_\-\.@]+)', command)
        if m:
            action, svc = m.groups()
            action_cn = {"restart": "重启", "start": "启动", "stop": "停止", "reload": "重载"}.get(action, action)
            return (
                f"将{action_cn}系统服务 '{svc}'。\n\n"
                "风险评估依据：\n"
                f"- 操作类型：服务{action_cn}\n"
                f"- 潜在影响：服务 {svc} 可能短暂中断或状态变更，影响依赖该服务的业务\n"
                "- 恢复难度：低（可手动恢复服务状态）\n"
                "- 安全等级：需要确认"
            )

        # apt-get / apt / yum install/remove
        m = re.search(r'(?:apt-get|apt|yum)\s+(?:\S+\s+)*(install|remove)\s+([a-zA-Z0-9_\-\.+]+)', command)
        if m:
            action, pkg = m.groups()
            action_cn = {"install": "安装", "remove": "卸载"}.get(action, action)
            return (
                f"将{action_cn}软件包 '{pkg}'。\n\n"
                "风险评估依据：\n"
                f"- 操作类型：软件包{action_cn}\n"
                "- 潜在影响：系统软件环境变更，可能引入依赖冲突或删除关键组件\n"
                "- 恢复难度：中等\n"
                "- 安全等级：需要确认"
            )

        # chmod
        m = re.search(r'chmod\s+([0-7]{3,4})\s+([\S]+)', command)
        if m:
            mode, path = m.groups()
            return (
                f"将修改 '{path}' 的权限为 {mode}。\n\n"
                "风险评估依据：\n"
                "- 操作类型：文件权限变更\n"
                f"- 潜在影响：路径 {path} 的访问控制策略变更，可能导致未授权访问或功能异常\n"
                "- 恢复难度：中等\n"
                "- 安全等级：需要确认"
            )

        # chown
        m = re.search(r'chown\s+([a-zA-Z_][a-zA-Z0-9_-]*(?::[a-zA-Z_][a-zA-Z0-9_-]*)?)\s+([\S]+)', command)
        if m:
            owner, path = m.groups()
            return (
                f"将变更 '{path}' 的所有者为 {owner}。\n\n"
                "风险评估依据：\n"
                "- 操作类型：文件所有权变更\n"
                f"- 潜在影响：路径 {path} 的归属变更，可能影响服务运行或访问权限\n"
                "- 恢复难度：中等\n"
                "- 安全等级：需要确认"
            )

        # sed -i (配置文件修改)
        if "sed -i" in command_lower:
            return (
                "将使用 sed 就地修改配置文件。\n\n"
                "风险评估依据：\n"
                "- 操作类型：配置文件变更\n"
                "- 潜在影响：配置语法错误可能导致相关服务无法启动\n"
                "- 恢复难度：中等（需手动恢复备份或修正配置）\n"
                "- 安全等级：需要确认"
            )

        # rm
        m = re.search(r'rm\s+(?:-[a-zA-Z]*\s+)?([\S]+)', command)
        if m:
            target = m.group(1)
            return (
                f"将删除文件/目录 '{target}'。\n\n"
                "风险评估依据：\n"
                "- 操作类型：文件删除\n"
                f"- 潜在影响：{target} 将被永久移除（若无备份则不可恢复）\n"
                "- 恢复难度：中高\n"
                "- 安全等级：需要确认"
            )

        return ""

    # ── 风险缓解建议 ──────────────────────────────────────────────────────────
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

    # ── 命令影响分析（核心改进：提取具体对象）──────────────────────────────────
    @staticmethod
    def analyze_command_impact(command, os_type="linux"):
        command_lower = (command or "").lower()
        impacts = []
        import re

        # userdel
        m = re.search(r'userdel\s+([a-zA-Z_][a-zA-Z0-9_-]*)', command)
        if m:
            impacts.append(f"删除系统用户 {m.group(1)}")

        # useradd
        m = re.search(r'(?:useradd|adduser)\s+([a-zA-Z_][a-zA-Z0-9_-]*)', command)
        if m and "delete" not in command_lower:
            impacts.append(f"创建系统用户 {m.group(1)}")

        # usermod
        m = re.search(r'usermod\s+.*\s+([a-zA-Z_][a-zA-Z0-9_-]*)\s*$', command)
        if m:
            impacts.append(f"修改用户 {m.group(1)} 权限")

        # systemctl
        m = re.search(r'systemctl\s+(restart|start|stop|reload)\s+([a-zA-Z0-9_\-\.@]+)', command)
        if m:
            action, svc = m.groups()
            impacts.append(f"{action}服务 {svc}")

        # apt/yum install/remove
        m = re.search(r'(?:apt-get|apt|yum)\s+(?:\S+\s+)*(install|remove)\s+([a-zA-Z0-9_\-\.+]+)', command)
        if m:
            action, pkg = m.groups()
            impacts.append(f"{action}软件包 {pkg}")

        # chmod
        m = re.search(r'chmod\s+([0-7]{3,4})\s+([\S]+)', command)
        if m:
            impacts.append(f"修改 {m.group(2)} 权限为 {m.group(1)}")

        # chown
        m = re.search(r'chown\s+([a-zA-Z_][a-zA-Z0-9_-]*(?::[a-zA-Z_][a-zA-Z0-9_-]*)?)\s+([\S]+)', command)
        if m:
            impacts.append(f"变更 {m.group(2)} 所有权为 {m.group(1)}")

        # rm
        m = re.search(r'rm\s+(?:-[a-zA-Z]*\s+)?([\S]+)', command)
        if m:
            impacts.append(f"删除 {m.group(1)}")

        # sed -i
        if "sed -i" in command_lower:
            impacts.append("修改配置文件")

        if not impacts:
            impacts.append("信息查询")

        return impacts

    # ── 环境特定风险 ──────────────────────────────────────────────────────────
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
