import time
import json
from typing import Any, Dict, List, Optional
from openai import OpenAI

from config.config import OPENAI_API_KEY, OPENAI_MODEL, OPENAI_BASE_URL

_explain_client = None
if OPENAI_API_KEY and OPENAI_API_KEY != "sk-your-api-key-here":
    try:
        _kwargs = {"api_key": OPENAI_API_KEY}
        if OPENAI_BASE_URL:
            _kwargs["base_url"] = OPENAI_BASE_URL
        _explain_client = OpenAI(**_kwargs)
    except Exception:
        pass

RISK_TEMPLATES = {
    "high": {
        "template": "该操作已被阻止。原因：触发了规则 {rule_id}（{rule_name}）。该命令包含高风险操作符 '{operator}'，可能导致{impact}。系统已拒绝执行以保护系统安全。",
        "rule_id": "R001",
        "rule_name": "高危命令拦截",
        "fallback": "该操作存在严重安全风险，已被系统阻止。"
    },
    "medium": {
        "template": "该操作需要您的确认。原因：命令包含'{operator}'，属于中等风险操作，可能{impact}。请确认您理解操作后果后再执行。",
        "rule_id": "R002",
        "rule_name": "中等风险确认",
        "fallback": "该操作需要确认，请评估后再执行。"
    },
    "low": {
        "template": "该操作属于低风险操作，命令为{command_type}，用于{impact}。系统已自动执行。",
        "rule_id": "R003",
        "rule_name": "低风险自动放行",
        "fallback": "该操作已安全执行。"
    }
}

OPERATION_TEMPLATES = {
    "disk_usage": {
        "purpose": "检查磁盘空间使用情况",
        "expected": "展示各挂载点的空间使用百分比和剩余容量",
        "command_desc": "df -h（以人类可读格式显示磁盘使用情况）"
    },
    "process_status": {
        "purpose": "查看当前运行的进程列表",
        "expected": "展示所有运行中进程的PID、CPU和内存占用",
        "command_desc": "ps aux（显示所有用户的详细进程信息）"
    },
    "port_status": {
        "purpose": "查看系统开放的网络端口",
        "expected": "展示所有监听中的TCP/UDP端口及对应进程",
        "command_desc": "ss -tuln（以数字格式显示TCP/UDP监听端口）"
    },
    "os_info": {
        "purpose": "获取操作系统版本和内核信息",
        "expected": "展示OS名称、版本号、内核版本和架构信息",
        "command_desc": "uname -a && cat /etc/os-release（显示系统和发行版信息）"
    },
    "memory_usage": {
        "purpose": "检查内存使用情况",
        "expected": "展示总内存、已用内存、空闲内存和缓存信息",
        "command_desc": "free -h（以人类可读格式显示内存使用情况）"
    },
    "cpu_usage": {
        "purpose": "检查CPU使用率",
        "expected": "展示CPU使用百分比和负载情况",
        "command_desc": "top -bn1（一次性输出CPU使用概况）"
    },
    "search_files": {
        "purpose": "在指定目录中搜索匹配模式的文件",
        "expected": "列出所有匹配的文件路径",
        "command_desc": "find <目录> -name <模式>（递归搜索匹配文件）"
    },
    "create_user": {
        "purpose": "创建新的系统用户账户",
        "expected": "创建用户并设置默认家目录",
        "command_desc": "useradd <用户名>（创建新用户账户）"
    },
    "delete_user": {
        "purpose": "删除系统用户账户",
        "expected": "移除用户账户和相关配置",
        "command_desc": "userdel <用户名>（删除指定用户）"
    },
    "install_software": {
        "purpose": "安装指定的软件包",
        "expected": "从软件源下载并安装目标软件及其依赖",
        "command_desc": "apt-get install -y <软件包>（自动确认安装软件）"
    },
    "uninstall_software": {
        "purpose": "卸载指定的软件包",
        "expected": "移除目标软件及相关配置文件",
        "command_desc": "apt-get remove -y <软件包>（自动确认卸载软件）"
    },
    "manage_service": {
        "purpose": "管理系统服务的运行状态",
        "expected": "启动/停止/重启服务或查看服务状态",
        "command_desc": "systemctl <操作> <服务名>（通过systemd管理服务）"
    },
    "check_firewall": {
        "purpose": "检查防火墙规则配置",
        "expected": "展示当前防火墙的允许/拒绝规则列表",
        "command_desc": "ufw status / iptables -L（查看防火墙规则）"
    },
    "cleanup_logs": {
        "purpose": "清理指定目录中的旧日志文件",
        "expected": "删除超过指定天数的日志文件以释放空间",
        "command_desc": "find <目录> -name '*.log' -mtime +30 -delete（删除30天前的日志）"
    },
    "configure_sudo": {
        "purpose": "为用户配置sudo管理员权限",
        "expected": "将用户加入sudo/wheel组，获得管理员权限",
        "command_desc": "usermod -aG sudo <用户名>（将用户加入sudo组）"
    },
    "deploy_workspace": {
        "purpose": "创建工作目录并设置所有权",
        "expected": "创建目录结构并设置正确的用户权限",
        "command_desc": "mkdir -p <路径> && chown <用户> <路径>（创建目录并设置所有者）"
    },
    "diagnostic": {
        "purpose": "诊断系统问题（如端口无法访问）",
        "expected": "通过多步检查定位问题原因并给出建议",
        "command_desc": "综合诊断命令（检查端口、服务和防火墙）"
    }
}

DECISION_EXPLANATIONS = {
    "task_decomposition": {
        "llm": "我理解您的需求包含{step_count}个步骤，已将其分解为可执行的任务序列：{task_list}。任务之间存在依赖关系，系统将按依赖顺序执行。",
        "rule": "我识别到您的请求包含多个操作，已按顺序分解为：{task_list}。",
        "condition": "我理解您的需求包含条件判断，将根据实际执行情况选择不同的操作路径。"
    },
    "risk_decision": {
        "blocked": "该操作已被安全策略阻止。触发的规则是：{rule_id}（{rule_name}）。建议：{suggestion}",
        "confirm": "该操作需要您的确认，因为：{reason}。请评估风险后再决定是否继续。",
        "passed": "该操作已通过安全检查，风险等级为{level}，已自动执行。"
    },
    "error_handling": {
        "retry": "命令执行未成功，正在自动重试（第{attempt}次）。",
        "skip": "任务执行失败，根据错误策略标记为跳过。该步骤不影响后续任务执行。",
        "rollback": "检测到操作失败，正在执行回滚操作：{action}。",
        "abort": "遇到不可恢复的错误，已中止任务链执行。"
    },
    "pre_check": {
        "passed": "执行前检查通过，前置条件已满足。",
        "failed": "执行前检查未通过，原因：{reason}。根据策略已{action}。"
    },
    "post_validation": {
        "passed": "执行后验证通过，操作结果符合预期。",
        "failed": "执行后验证未通过，操作结果与预期不符。根据策略已{action}。"
    },
    "branch_execution": {
        "taken": "条件检查结果为{result}，将执行{path}路径下的任务。",
        "skipped": "条件分支已完成，根据条件结果选择了合适的执行路径。"
    }
}


class ExplainabilityEngine:
    """行为可解释引擎：模板化生成 + LLM 润色"""

    def __init__(self, model: str = OPENAI_MODEL):
        self.model = model

    def explain_risk(self, risk_level: str, command: str = "", operator: str = "",
                     impact: str = "", context: str = "") -> str:
        """生成风险决策的自然语言解释"""
        tmpl = RISK_TEMPLATES.get(risk_level, RISK_TEMPLATES["low"])
        explanation = tmpl["template"].format(
            rule_id=tmpl["rule_id"],
            rule_name=tmpl["rule_name"],
            operator=operator or command[:50],
            impact=impact or "系统配置变更",
            command_type=command[:100] if command else "未知"
        )
        if context:
            explanation += f"\n\n当前上下文：{context}"
        return explanation

    def explain_operation(self, intent: str, status: str = "completed",
                          result: str = "", error: str = "") -> str:
        """生成操作目的、预期效果和实际结果的自然语言描述"""
        tmpl = OPERATION_TEMPLATES.get(intent, {
            "purpose": "执行系统操作",
            "expected": "完成指定的操作任务",
            "command_desc": intent
        })
        status_map = {
            "completed": "操作已成功完成",
            "failed": f"操作执行失败：{error}" if error else "操作执行失败",
            "skipped": "该操作已根据策略跳过",
            "cancelled": "该操作已被用户取消",
            "rolled_back": "该操作已执行回滚",
            "pending": "该操作等待执行",
            "in_progress": "该操作正在执行中"
        }
        status_desc = status_map.get(status, f"操作状态：{status}")
        parts = [
            f"**操作**：{tmpl['purpose']}",
            f"**命令**：{tmpl['command_desc']}",
            f"**预期效果**：{tmpl['expected']}",
            f"**实际结果**：{status_desc}"
        ]
        if result and status == "completed":
            lines = result.strip().split('\n')
            key_lines = [l for l in lines if l.strip() and not l.strip().startswith('Exit code') and not l.strip().startswith('STDERR')]
            preview = '\n'.join(key_lines[:5])
            if len(key_lines) > 5:
                preview += f"\n...（共{len(key_lines)}行输出）"
            parts.append(f"**输出摘要**：{preview}")
        return "\n".join(parts)

    def explain_decision(self, decision_type: str, context: Dict[str, Any] = None) -> str:
        if context is None:
            context = {}
        tmpl_dict = DECISION_EXPLANATIONS.get(decision_type, {})
        if not tmpl_dict:
            return f"决策类型：{decision_type}"

        selected_key = None
        for key in tmpl_dict:
            if key in context:
                selected_key = key
                break
        if selected_key is None:
            selected_key = next(iter(tmpl_dict))

        tmpl = tmpl_dict[selected_key]
        try:
            return tmpl.format(**context)
        except (KeyError, IndexError):
            return tmpl

    def explain_task_sequence(self, tasks: List[Dict[str, Any]]) -> str:
        """解释任务序列的分解逻辑和执行计划"""
        if not tasks:
            return "未识别到需要执行的任务。"
        llm_used = any(t.get("branch_type") != "sequential" for t in tasks)
        step_count = len(tasks)
        task_list = "、".join([t.get("description", t.get("intent", "")) for t in tasks[:5]])
        if len(tasks) > 5:
            task_list += f" 等{step_count}个任务"
        if llm_used:
            tmpl = DECISION_EXPLANATIONS["task_decomposition"]["llm"]
        elif any(t.get("branch_type") == "conditional" for t in tasks):
            tmpl = DECISION_EXPLANATIONS["task_decomposition"]["condition"]
        else:
            tmpl = DECISION_EXPLANATIONS["task_decomposition"]["rule"]
        return tmpl.format(step_count=step_count, task_list=task_list)

    def explain_context_change(self, old_intent: str, new_intent: str,
                               conversation_length: int) -> str:
        """解释上下文转换，保持语义连贯性"""
        if old_intent == new_intent:
            return f"继续执行{new_intent}相关操作。"
        transitions = {
            ("disk_usage", "process_status"): "已从磁盘检查切换到进程状态查看。",
            ("process_status", "port_status"): "已从进程查看切换到端口状态检查。",
            ("create_user", "configure_sudo"): "用户已创建，接下来配置其sudo权限。",
        }
        key = (old_intent, new_intent)
        if key in transitions:
            return transitions[key]
        return f"操作上下文已从「{old_intent}」切换到「{new_intent}」。"

    def polish_explanation(self, raw_explanation: str, context: Dict[str, Any] = None) -> str:
        """使用 LLM 润色解释文本，使其更符合当前对话语境"""
        if not _explain_client:
            return raw_explanation
        if context is None:
            context = {}
        user_input = context.get("user_input", "")
        os_type = context.get("os_type", "linux")
        history = context.get("history", [])
        history_context = ""
        if history:
            last_user = next((m.get("content", "") for m in reversed(history) if m.get("role") == "user"), "")
            last_assistant = next((m.get("content", "") for m in reversed(history) if m.get("role") == "assistant"), "")
            history_context = f"用户上轮请求：{last_user[:100]}\n助手上轮回复：{last_assistant[:100]}\n"
        prompt = f"""请将以下系统操作解释改写为更加自然、易懂的中文表达，适合普通运维人员阅读。
保持信息准确性，不要改变原始含义。
输出只需改写后的解释文本，不要添加额外说明。

原始解释：
{raw_explanation}

对话上下文：
{history_context}
当前环境：{os_type}
用户当前请求：{user_input}
"""
        try:
            resp = _explain_client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "你是一个技术写作助手。请将技术性解释改写为自然流畅的中文。"},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,
                max_tokens=500,
                timeout=15
            )
            return resp.choices[0].message.content.strip()
        except Exception:
            return raw_explanation

    def generate_full_explanation(self, intent: str, status: str = "",
                                  risk_level: str = "", command: str = "",
                                  result: str = "", error: str = "",
                                  context: Dict[str, Any] = None) -> str:
        """生成完整的可解释输出：决策原因 + 操作描述 + 结果说明"""
        parts = []
        if risk_level:
            risk_expl = self.explain_risk(risk_level, command)
            parts.append(f"🔒 **安全决策**：{risk_expl}")
        op_expl = self.explain_operation(intent, status, result, error)
        parts.append(f"⚙️ **操作说明**：{op_expl}")
        full = "\n\n".join(parts)
        polished = self.polish_explanation(full, context)
        return polished
