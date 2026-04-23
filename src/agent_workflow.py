import re
import time
import os
import json
import shlex
from typing import Any, Dict, List, Optional

from langgraph.graph import StateGraph, END
from openai import OpenAI


def _safe_arg(value: str, os_type: str = "linux") -> str:
    if not value:
        return "''"
    if os_type == "windows":
        escaped = value.replace('"', '""')
        return f'"{escaped}"'
    return shlex.quote(str(value))

from config.config import (
    OPENAI_API_KEY,
    OPENAI_MODEL,
    OPENAI_BASE_URL,
    DEFAULT_TIMEOUT,
    MAX_RETRIES,
    ALLOW_RAW_SHELL_FALLBACK,
)
from tools.environment_tools import EnvironmentTools
from tools.system_tools import SystemTools
from tools.security_tools import SecurityTools
from tools.audit_logger import AuditLogger
from tools.task_decomposer import LLMTaskDecomposer
from tools.explainability import ExplainabilityEngine
from src.state_manager import (
    AgentState,
    StateValidator,
    EnvironmentContext,
    RiskAssessment,
    TaskItem,
)

os.environ["OPENAI_API_KEY"] = OPENAI_API_KEY

_api_initialized = bool(OPENAI_API_KEY and OPENAI_API_KEY != "sk-your-api-key-here")
if _api_initialized:
    _client_kwargs = {"api_key": OPENAI_API_KEY}
    if OPENAI_BASE_URL:
        _client_kwargs["base_url"] = OPENAI_BASE_URL
    client = OpenAI(**_client_kwargs)
    task_decomposer = LLMTaskDecomposer(OPENAI_API_KEY, OPENAI_MODEL, OPENAI_BASE_URL)
else:
    client = None
    task_decomposer = None

audit_logger = AuditLogger()
explainer = ExplainabilityEngine()


def _get_next_task_index(state: Dict[str, Any], current_idx: int) -> int:
    task_sequence = state.get("task_sequence", [])
    execution_order = state.get("task_execution_order", [])
    if not task_sequence:
        return current_idx
    if execution_order:
        current_task = task_sequence[current_idx] if current_idx < len(task_sequence) else {}
        current_task_id = current_task.get("task_id", "")
        try:
            order_idx = execution_order.index(current_task_id)
            if order_idx + 1 < len(execution_order):
                next_task_id = execution_order[order_idx + 1]
                for i, t in enumerate(task_sequence):
                    if t.get("task_id") == next_task_id:
                        return i
        except ValueError:
            pass
    return current_idx + 1 if current_idx + 1 < len(task_sequence) else len(task_sequence)

SESSION_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "sessions")
os.makedirs(SESSION_DIR, exist_ok=True)

COMPLEX_KEYWORDS = [
    "如果", "就", "否则", "然后", "并且", "接着", "最后",
    "先", "再", "后", "检查", "排查", "诊断",
    "创建", "配置", "部署", "安装", "卸载",
    "用户", "权限", "服务", "防火墙", "日志"
]


# ─────────────────────────────────────────────────────────────────────────────
# Intent → Goal-based Planning
# 新的架构：用户目标 → 命令推导，而不是 keyword → 硬编码命令
# ─────────────────────────────────────────────────────────────────────────────

GOAL_COMMAND_MAPPING = {
    # 磁盘相关
    "disk_usage": {
        "default": "df -h",
        "top_n": "df -h | sort -k5 -h | tail -10",
        "inodes": "df -i",
    },
    "file_size_largest": {
        "default": 'find . -type f -exec du -h {} + 2>/dev/null | sort -rh | head -20',
        "directory": 'du -h --max-depth=1 2>/dev/null | sort -rh | head -10',
    },
    # 内存相关
    "memory_usage": {
        "default": "free -h",
    },
    "memory_top_processes": {
        "default": "ps aux --sort=-%mem | head -20",
        "top5": "ps aux --sort=-%mem | awk 'NR<=6'",
    },
    "swap_usage": {
        "default": "free -h | grep Swap",
    },
    # CPU相关
    "cpu_usage": {
        "default": "top -bn1 | grep 'Cpu(s)'",
        "per_core": "mpstat",
        "load_average": "uptime",
    },
    "cpu_top_processes": {
        "default": "ps aux --sort=-%cpu | head -20",
        "top5": "ps aux --sort=-%cpu | awk 'NR<=6'",
    },
    # 进程相关
    "process_status": {
        "default": "ps aux",
        "tree": "pstree",
        "threads": "ps -eLf",
    },
    "process_by_name": {
        "default": 'ps aux | grep -v grep | grep',
    },
    "process_tree": {
        "default": "pstree -p",
    },
    # 端口相关
    "port_status": {
        "default": "ss -tuln",
        "listening": "ss -tlnp",
    },
    "port_by_service": {
        "default": "ss -tlnp",
    },
    # 文件搜索
    "search_files": {
        "default": 'find . -name',
        "recent": 'find . -type f -mtime -7',
        "large": 'find . -type f -size +100M',
    },
    "file_content_search": {
        "default": 'grep -r',
    },
    # 系统信息
    "os_info": {
        "default": "uname -a && cat /etc/os-release",
        "full": "hostnamectl && cat /etc/os-release",
    },
    "system_uptime": {
        "default": "uptime",
    },
    # 用户相关
    "list_users": {
        "default": "cat /etc/passwd | grep -v nologin",
    },
    "logged_in_users": {
        "default": "who",
    },
    # 服务相关
    "manage_service": {
        "status": "systemctl status",
        "start": "systemctl start",
        "stop": "systemctl stop",
        "restart": "systemctl restart",
        "enable": "systemctl enable",
        "disable": "systemctl disable",
    },
    # 网络相关
    "network_connections": {
        "default": "ss -tan",
    },
    "dns_lookup": {
        "default": "nslookup",
    },
    "ping_check": {
        "default": "ping -c 4",
    },
    # 防火墙
    "check_firewall": {
        "default": "ufw status",
        "iptables": "iptables -L -n",
    },
    # 日志
    "view_logs": {
        "default": "tail -100",
        "journalctl": "journalctl -n 50",
        "syslog": "tail -f /var/log/syslog",
    },
    "cleanup_logs": {
        "default": "find /var/log -name '*.log' -mtime +30",
    },
    # 软件管理
    "install_software": {
        "default": "apt-get update && apt-get install -y",
    },
    "uninstall_software": {
        "default": "apt-get remove -y",
    },
    "list_packages": {
        "default": "dpkg -l",
    },
    # Docker
    "docker_ps": {
        "default": "docker ps",
        "all": "docker ps -a",
    },
    "docker_stats": {
        "default": "docker stats --no-stream",
    },
    "docker_logs": {
        "default": "docker logs --tail 100",
    },
    # 诊断
    "diagnostic": {
        "port": "ss -tuln | grep",
        "process": "ps aux | grep",
        "memory": "free -h",
        "disk": "df -h",
    },
}


def _derive_best_command(intent: str, params: Dict[str, Any], os_type: str = "linux") -> str:
    """根据意图和参数推导出最佳命令"""
    mapping = GOAL_COMMAND_MAPPING.get(intent, {})
    if not mapping:
        return ""

    # 如果有明确的 sub-intent 或参数，选择对应命令
    sub_key = params.get("sub_intent", "default")
    if sub_key in mapping:
        cmd = mapping[sub_key]
    elif "default" in mapping:
        cmd = mapping["default"]
    else:
        cmd = ""

    # 参数替换
    if cmd and params:
        cmd = cmd.format(**{k: v for k, v in params.items() if k not in ("sub_intent",)})

    return cmd


MAX_SESSION_HISTORY = 50


def _load_session(session_id: str) -> Dict[str, Any]:
    path = os.path.join(SESSION_DIR, f"{session_id}.json")
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def _save_session(session_id: str, state: Dict[str, Any]):
    """原子写入：先写临时文件，再 os.replace 重命名，避免并发写入损坏 JSON"""
    path = os.path.join(SESSION_DIR, f"{session_id}.json")
    tmp_path = path + ".tmp"
    try:
        serializable = {}
        for k, v in state.items():
            if k == "conversation_history" and isinstance(v, list):
                serializable[k] = v[-MAX_SESSION_HISTORY:]
            else:
                serializable[k] = v
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(serializable, f, ensure_ascii=False, indent=2, default=str)
        os.replace(tmp_path, path)  # 原子替换
    except Exception:
        # 清理残留临时文件
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass


def _validate_and_fix_state(state: Dict[str, Any]) -> Dict[str, Any]:
    return StateValidator.validate_state(state)


def _is_confirmation_resume(state: Dict[str, Any]) -> bool:
    return (
        state.get("user_confirmation") is not None
        and bool(state.get("task_sequence"))
        and bool(state.get("command"))
    )



def _parse_intents(user_input: str) -> List[Dict[str, Any]]:
    separators = r"(?:然后|并且|接着|最后|，|,|再|后|，再|，然后)"
    parts = re.split(separators, user_input)
    parts = [p.strip() for p in parts if p.strip()]

    if len(parts) <= 1:
        parts = [user_input.strip()]

    return [_extract_single_intent(p) for p in parts if p]


def _extract_single_intent(text: str) -> Dict[str, Any]:
    """新的 goal-oriented 意图识别：理解用户目标，推导最佳命令"""
    text_lower = text.lower()

    # ── 内存相关目标 ──────────────────────────────────────────────────────────
    if "内存" in text_lower or "memory" in text_lower:
        # 区分"查看内存概况"和"找出占用最多的"
        if any(kw in text_lower for kw in ["哪个", "哪个进程", "什么进程", "最多", "最大", "占用最多", "占用最大", "top", "排名"]):
            return {"intent": "memory_top_processes", "parameters": {"sub_intent": "default"}}
        if "swap" in text_lower:
            return {"intent": "swap_usage", "parameters": {"sub_intent": "default"}}
        return {"intent": "memory_usage", "parameters": {"sub_intent": "default"}}

    # ── CPU相关目标 ───────────────────────────────────────────────────────────
    if "cpu" in text_lower or "处理器" in text_lower:
        if any(kw in text_lower for kw in ["哪个", "哪个进程", "什么进程", "最多", "最大", "占用最多", "top", "排名"]):
            return {"intent": "cpu_top_processes", "parameters": {"sub_intent": "default"}}
        return {"intent": "cpu_usage", "parameters": {"sub_intent": "default"}}

    # ── 磁盘相关目标 ─────────────────────────────────────────────────────────
    if "磁盘" in text_lower or "disk" in text_lower or "df" in text_lower or "空间" in text_lower:
        if any(kw in text_lower for kw in ["哪个", "哪个目录", "最大", "最多", "占用最大", "占用最多"]):
            return {"intent": "file_size_largest", "parameters": {"sub_intent": "directory"}}
        if "inodes" in text_lower:
            return {"intent": "disk_usage", "parameters": {"sub_intent": "inodes"}}
        return {"intent": "disk_usage", "parameters": {"sub_intent": "default"}}

    # ── 文件/目录大小相关目标 ─────────────────────────────────────────────────
    if any(kw in text_lower for kw in ["文件大小", "目录大小", "占用空间", "哪个文件", "哪个目录", "最大文件", "最大目录"]):
        if "目录" in text_lower or "folder" in text_lower:
            return {"intent": "file_size_largest", "parameters": {"sub_intent": "directory"}}
        return {"intent": "file_size_largest", "parameters": {"sub_intent": "default"}}

    # ── 进程相关目标 ─────────────────────────────────────────────────────────
    if "进程" in text_lower or "process" in text_lower or "ps" in text_lower:
        if any(kw in text_lower for kw in ["哪个", "最多", "最大", "占用最多", "top", "排名"]):
            # 如果同时提到内存，优先 memory_top_processes
            if any(kw in text_lower for kw in ["内存", "memory"]):
                return {"intent": "memory_top_processes", "parameters": {"sub_intent": "default"}}
            return {"intent": "cpu_top_processes", "parameters": {"sub_intent": "default"}}
        if "树" in text_lower or "tree" in text_lower:
            return {"intent": "process_tree", "parameters": {"sub_intent": "default"}}
        if "线程" in text_lower or "thread" in text_lower:
            return {"intent": "process_status", "parameters": {"sub_intent": "threads"}}
        return {"intent": "process_status", "parameters": {"sub_intent": "default"}}

    # ── 端口相关目标 ─────────────────────────────────────────────────────────
    if "端口" in text_lower or "port" in text_lower or "netstat" in text_lower or "ss " in text_lower:
        # 提取具体端口号（如"查看9600端口"、"80端口"、"port 443"）
        port_match = re.search(r'(\d{2,5})\s*端口|端口\s*(\d{2,5})|port\s*(\d{2,5})', text_lower)
        if port_match:
            port_num = port_match.group(1) or port_match.group(2) or port_match.group(3)
            return {"intent": "port_status", "parameters": {"sub_intent": "specific", "port": port_num}}
        return {"intent": "port_status", "parameters": {"sub_intent": "default"}}

    # ── 系统信息 ─────────────────────────────────────────────────────────────
    if "系统信息" in text_lower or re.search(r'\bos\b', text_lower) or "系统版本" in text_lower or "uname" in text_lower:
        return {"intent": "os_info", "parameters": {"sub_intent": "default"}}
    if "运行时间" in text_lower or "uptime" in text_lower:
        return {"intent": "system_uptime", "parameters": {"sub_intent": "default"}}

    # ── 用户相关目标 ─────────────────────────────────────────────────────────
    if any(kw in text_lower for kw in ["用户", "user"]) and any(kw in text_lower for kw in ["创建", "新建", "add", "create"]):
        m = re.search(r"(?:用户|user|名为?)\s*['\"]?([\w]+)['\"]?", text)
        if m:
            return {"intent": "create_user", "parameters": {"username": m.group(1)}}
        return {"intent": "create_user", "parameters": {}}
    if any(kw in text_lower for kw in ["用户", "user"]) and any(kw in text_lower for kw in ["删除", "delete", "移除"]):
        m = re.search(r"(?:用户|user|名为?)\s*['\"]?([\w]+)['\"]?", text)
        if m:
            return {"intent": "delete_user", "parameters": {"username": m.group(1)}}
        return {"intent": "delete_user", "parameters": {}}
    if "当前用户" in text_lower or "登录用户" in text_lower or "who" in text_lower:
        return {"intent": "logged_in_users", "parameters": {"sub_intent": "default"}}

    # ── 文件搜索 ──────────────────────────────────────────────────────────────
    if "搜索" in text_lower or "查找" in text_lower or "find" in text_lower or "search" in text_lower:
        params = {}
        dm = re.search(r"[/\\][\w/\\]+", text)
        if dm:
            params["directory"] = dm.group(0)
        pm = re.search(r"\*[\w]*\.\w+|[\w]+\.(\*|[\w]+)", text)
        if pm:
            params["pattern"] = pm.group(0)
        if "最近" in text_lower or "recent" in text_lower:
            params["sub_intent"] = "recent"
        elif "大文件" in text_lower or "large" in text_lower:
            params["sub_intent"] = "large"
        return {"intent": "search_files", "parameters": params}

    # ── 软件安装/卸载 ───────────────────────────────────────────────────────
    if "安装" in text_lower or "install" in text_lower or "apt-get" in text_lower or "yum" in text_lower or "pip" in text_lower:
        m = re.search(r"(?:安装|install)\s+['\"]?([\w\-\.\+]+)['\"]?", text)
        pkg = m.group(1) if m else ""
        return {"intent": "install_software", "parameters": {"package": pkg, "sub_intent": "default"}}
    if "卸载" in text_lower or "uninstall" in text_lower or "remove" in text_lower or "apt-get remove" in text_lower:
        m = re.search(r"(?:卸载|uninstall|remove)\s+['\"]?([\w\-\.\+]+)['\"]?", text)
        pkg = m.group(1) if m else ""
        return {"intent": "uninstall_software", "parameters": {"package": pkg, "sub_intent": "default"}}

    # ── 服务管理 ──────────────────────────────────────────────────────────────
    if "启动" in text_lower or "停止" in text_lower or "重启" in text_lower or "restart" in text_lower or "systemctl" in text_lower or "service" in text_lower:
        action = "status"
        if "启动" in text_lower or "start" in text_lower:
            action = "start"
        elif "停止" in text_lower or "stop" in text_lower:
            action = "stop"
        elif "重启" in text_lower or "restart" in text_lower:
            action = "restart"
        elif "启用" in text_lower or "enable" in text_lower:
            action = "enable"
        elif "禁用" in text_lower or "disable" in text_lower:
            action = "disable"
        m = re.search(r"(?:服务|service)\s+['\"]?([\w\-\.\+]+)['\"]?", text)
        svc = m.group(1) if m else ""
        return {"intent": "manage_service", "parameters": {"service": svc, "action": action, "sub_intent": action}}

    # ── 防火墙 ────────────────────────────────────────────────────────────────
    if "防火墙" in text_lower or "firewall" in text_lower or "iptables" in text_lower or "ufw" in text_lower:
        if "iptables" in text_lower:
            return {"intent": "check_firewall", "parameters": {"sub_intent": "iptables"}}
        return {"intent": "check_firewall", "parameters": {"sub_intent": "default"}}

    # ── 日志查看/清理 ────────────────────────────────────────────────────────
    if "日志" in text_lower and any(kw in text_lower for kw in ["查看", "tail", "view", "最近"]):
        return {"intent": "view_logs", "parameters": {"sub_intent": "default"}}
    if any(kw in text_lower for kw in ["清理", "cleanup", "清除日志", "删除日志"]):
        m = re.search(r"[/\\][\w/\\]+", text)
        path = m.group(0) if m else "/var/log"
        return {"intent": "cleanup_logs", "parameters": {"path": path, "sub_intent": "default"}}

    # ── Sudo/权限配置 ─────────────────────────────────────────────────────────
    if "sudo" in text_lower or "权限" in text_lower or "配置sudo" in text_lower or "管理员" in text_lower:
        m = re.search(r"(?:用户|user)\s+['\"]?([\w]+)['\"]?", text)
        user = m.group(1) if m else ""
        return {"intent": "configure_sudo", "parameters": {"username": user}}

    # ── 工作目录/部署 ─────────────────────────────────────────────────────────
    if "部署" in text_lower or "deploy" in text_lower or "工作目录" in text_lower or "workspace" in text_lower:
        m = re.search(r"[/\\][\w/\\]+", text)
        path = m.group(0) if m else ""
        m2 = re.search(r"(?:用户|user)\s+['\"]?([\w]+)['\"]?", text)
        user = m2.group(1) if m2 else ""
        return {"intent": "deploy_workspace", "parameters": {"path": path, "username": user}}

    # ── Docker ─────────────────────────────────────────────────────────────────
    if "docker" in text_lower:
        if "容器" in text_lower or "ps" in text_lower:
            if "-a" in text_lower or "所有" in text_lower or "all" in text_lower:
                return {"intent": "docker_ps", "parameters": {"sub_intent": "all"}}
            return {"intent": "docker_ps", "parameters": {"sub_intent": "default"}}
        if "统计" in text_lower or "stats" in text_lower:
            return {"intent": "docker_stats", "parameters": {"sub_intent": "default"}}
        if "日志" in text_lower:
            return {"intent": "docker_logs", "parameters": {"sub_intent": "default"}}

    # ── 诊断 ──────────────────────────────────────────────────────────────────
    if "排查" in text_lower or "诊断" in text_lower or "diagnose" in text_lower or "diagnostic" in text_lower or "无法访问" in text_lower or "不能访问" in text_lower:
        params = {"description": text}
        if "80" in text_lower or "端口" in text_lower:
            params["sub_intent"] = "port"
        elif "进程" in text_lower:
            params["sub_intent"] = "process"
        elif "内存" in text_lower:
            params["sub_intent"] = "memory"
        elif "磁盘" in text_lower:
            params["sub_intent"] = "disk"
        return {"intent": "diagnostic", "parameters": params}

    return {"intent": "other", "parameters": {}, "fallback_text": text}


def _apply_slot_memory(
    intents: List[Dict[str, Any]], history: List[Dict[str, str]]
) -> List[Dict[str, Any]]:
    last_dir = None
    for msg in reversed(history):
        if msg.get("role") == "user":
            dm = re.search(r"[/\\][\w/\\]+", msg.get("content", ""))
            if dm:
                last_dir = dm.group(0)
            break

    for item in intents:
        if item["intent"] == "search_files" and "directory" not in item["parameters"]:
            if last_dir:
                item["parameters"]["directory"] = last_dir

    return intents


def detect_environment(state: AgentState) -> Dict[str, Any]:
    env_data = state.get("environment", {})
    last_detected = env_data.get("last_detected", 0)
    ttl = env_data.get("cache_ttl", 3600)

    if (time.time() - last_detected) < ttl and env_data.get("os_type"):
        return {}

    os_type = EnvironmentTools.detect_os_type()
    os_info = EnvironmentTools.get_os_info()
    summary = EnvironmentTools.get_environment_summary()

    env_context = EnvironmentContext(
        os_type=os_type,
        os_info=os_info,
        hardware_info=summary.get("hardware"),
        last_detected=time.time()
    )

    audit_logger.log_environment_snapshot(
        session_id=state.get("session_id", ""),
        os_type=os_type,
        os_info=os_info,
        hardware_info=summary.get("hardware"),
        snapshot_data=summary
    )

    return {
        "environment": {
            **env_context.to_dict(),
            "summary": summary,
            "cache_ttl": ttl
        }
    }


def identify_intent(state: AgentState) -> Dict[str, Any]:
    user_input = state["user_input"]
    history = state.get("conversation_history", [])
    env = state.get("environment", {})
    os_type = env.get("os_type", "linux")

    if _is_confirmation_resume(state):
        task_sequence = state.get("task_sequence", [])
        current_idx = state.get("current_task_index", 0)
        current_task = task_sequence[current_idx] if task_sequence and current_idx < len(task_sequence) else {}
        return {
            "task_sequence": task_sequence,
            "current_task_index": current_idx,
            "task_status": state.get("task_status", "in_progress"),
            "conversation_history": history,
            "intent": state.get("intent", current_task.get("intent", "other")),
            "parameters": state.get("parameters", current_task.get("parameters", {})),
            "task_execution_order": state.get("task_execution_order", _compute_execution_order(task_sequence)),
            "execution_log": state.get("execution_log", []),
            "rollback_stack": state.get("rollback_stack", []),
            "branch_results": state.get("branch_results", {}),
            "last_intent": state.get("last_intent", current_task.get("intent", "")),
            "consistency_issues": state.get("consistency_issues", []),
        }

    use_llm = _api_initialized and task_decomposer is not None

    # 优先使用 LLM 进行任务分解（AI 原生路径）
    # 无论输入简单还是复杂，都先尝试 LLM；失败时退化到关键词规则
    if use_llm:
        try:
            llm_tasks = task_decomposer.decompose(user_input, os_type)
        except Exception:
            llm_tasks = []
        if llm_tasks:
            validation = task_decomposer.validate_plan(llm_tasks)
            if validation["valid"]:
                task_sequence = llm_tasks
            else:
                # LLM 计划无效，退化到规则解析
                intents = _parse_intents(user_input)
                intents = _apply_slot_memory(intents, history)
                task_sequence = _build_task_sequence(intents)
        else:
            # LLM 未返回结果，退化到规则解析
            intents = _parse_intents(user_input)
            intents = _apply_slot_memory(intents, history)
            task_sequence = _build_task_sequence(intents)
    else:
        # 未配置 API Key，使用规则解析
        intents = _parse_intents(user_input)
        intents = _apply_slot_memory(intents, history)
        task_sequence = _build_task_sequence(intents)

    execution_order = _compute_execution_order(task_sequence)

    validated = StateValidator.validate_state({
        **state,
        "task_sequence": task_sequence,
        "current_task_index": 0,
        "task_status": "in_progress" if task_sequence else "completed",
        "conversation_history": history + [{"role": "user", "content": user_input}],
        "task_execution_order": execution_order,
        "execution_log": [],
        "rollback_stack": [],
        "branch_results": {}
    })

    return {
        "task_sequence": task_sequence,
        "current_task_index": 0,
        "task_status": "in_progress" if task_sequence else "completed",
        "conversation_history": validated["conversation_history"],
        "intent": task_sequence[0]["intent"] if task_sequence else "other",
        "parameters": task_sequence[0].get("parameters", {}) if task_sequence else {},
        "task_execution_order": execution_order,
        "execution_log": [],
        "rollback_stack": [],
        "branch_results": {},
        "last_intent": task_sequence[0]["intent"] if task_sequence else "",
        "consistency_issues": []
    }


def _build_task_sequence(intents: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    task_sequence = []
    base_time = int(time.time())
    for idx, intent_item in enumerate(intents):
        task = TaskItem(
            intent=intent_item["intent"],
            description=intent_item.get("fallback_text", intent_item["intent"]),
            parameters=intent_item.get("parameters", {}),
            status="pending",
            task_id=f"task_{base_time}_{idx}"
        )
        task_sequence.append(task.to_dict())
    return task_sequence


def _compute_execution_order(tasks: List[Dict[str, Any]]) -> List[str]:
    if not tasks:
        return []

    task_map = {t["task_id"]: t for t in tasks}
    visited = set()
    order = []

    def visit(task_id: str):
        if task_id in visited:
            return
        visited.add(task_id)
        task = task_map.get(task_id)
        if task:
            for dep_id in task.get("depends_on", []):
                visit(dep_id)
        order.append(task_id)

    for task in tasks:
        visit(task["task_id"])

    return order


def pre_check_task(state: AgentState) -> Dict[str, Any]:
    task_sequence = state.get("task_sequence", [])
    idx = state.get("current_task_index", 0)

    if not task_sequence or idx >= len(task_sequence):
        return {"pre_check_passed": True}

    task = task_sequence[idx]
    pre_check = task.get("pre_check")

    if not pre_check:
        return {"pre_check_passed": True}

    check_cmd = pre_check.get("check_command", "")
    expected = pre_check.get("expected_condition", "")
    failure_action = pre_check.get("failure_action", "skip")

    if not check_cmd:
        return {"pre_check_passed": True}

    try:
        result = SystemTools._run_command(check_cmd, timeout=10)
        output = result.get("stdout", "") + result.get("stderr", "")
        passed = expected.lower() in output.lower() if expected else result.get("exit_code", -1) == 0

        if not passed:
            if failure_action == "skip":
                task_sequence_copy = list(task_sequence)
                task_sequence_copy[idx] = {**task_sequence_copy[idx], "status": "skipped", "result": f"预检未通过，跳过: {check_cmd}"}
                next_idx = _get_next_task_index(state, idx)
                return {
                    "task_sequence": task_sequence_copy,
                    "current_task_index": next_idx,
                    "task_status": "in_progress" if next_idx < len(task_sequence_copy) else "completed",
                    "pre_check_passed": False,
                    "skip_to_next": True
                }
            elif failure_action == "abort":
                return {
                    "task_status": "failed",
                    "execution_result": f"预检失败，中止执行: {check_cmd}",
                    "pre_check_passed": False,
                    "abort_execution": True
                }

        return {"pre_check_passed": passed}
    except Exception as e:
        return {"pre_check_passed": False, "pre_check_error": str(e)}


def generate_command(state: AgentState) -> Dict[str, Any]:
    task_sequence = state.get("task_sequence", [])
    idx = state.get("current_task_index", 0)
    env = state.get("environment", {})
    os_type = env.get("os_type", "linux")
    branch_results = state.get("branch_results", {})

    if _is_confirmation_resume(state):
        existing_risk = state.get("risk_assessment", {})
        return {
            "command": state.get("command", ""),
            "risk_level": state.get("risk_level", existing_risk.get("risk_level", "unknown")),
            "risk_explanation": state.get("risk_explanation", existing_risk.get("risk_explanation", "")),
            "risk_assessment": existing_risk,
        }

    if not task_sequence or idx >= len(task_sequence):
        return {"command": "", "risk_level": "low", "risk_explanation": "No tasks to execute"}

    task = task_sequence[idx]
    intent = task.get("intent", "other")
    params = task.get("parameters", {})

    # ── 条件分支处理（保持不变）────────────────────────────────────────────────
    if task.get("branch_type") == "conditional" and task.get("condition"):
        condition = task["condition"]
        cond_type = condition.get("type", "result_check")

        if cond_type == "result_check":
            check_cmd = condition.get("check_command", "")
            expected = condition.get("expected_condition", "")
            if check_cmd:
                try:
                    result = SystemTools._run_command(check_cmd, timeout=10)
                    output = result.get("stdout", "") + result.get("stderr", "")
                    condition_met = expected.lower() in output.lower() if expected else result.get("exit_code", -1) == 0
                    branch_key = task.get("task_id", "")
                    branch_results[branch_key] = condition_met

                    updated = list(task_sequence)
                    updated[idx] = {**updated[idx], "status": "completed", "result": f"条件检查: {'满足' if condition_met else '不满足'}"}

                    if condition_met:
                        on_true = task.get("on_true", [])
                        if on_true:
                            next_task_id = on_true[0]
                            for i, t in enumerate(updated):
                                if t.get("task_id") == next_task_id:
                                    return {
                                        "task_sequence": updated,
                                        "current_task_index": i,
                                        "branch_results": branch_results
                                    }
                    else:
                        on_false = task.get("on_false", [])
                        if on_false:
                            next_task_id = on_false[0]
                            for i, t in enumerate(updated):
                                if t.get("task_id") == next_task_id:
                                    return {
                                        "task_sequence": updated,
                                        "current_task_index": i,
                                        "branch_results": branch_results
                                    }

                    next_idx = _get_next_task_index({"task_sequence": updated, "task_execution_order": state.get("task_execution_order", [])}, idx)
                    return {
                        "command": "",
                        "risk_level": "low",
                        "risk_explanation": "条件分支已完成",
                        "task_sequence": updated,
                        "current_task_index": next_idx,
                        "task_status": "in_progress" if next_idx < len(updated) else "completed",
                        "branch_results": branch_results
                    }
                except Exception as e:
                    return {"command": "", "risk_level": "low", "risk_explanation": f"条件检查失败: {e}"}

    # ── Goal-based 命令推导（新的架构）─────────────────────────────────────────
    # 端口查询：针对特定端口使用 grep 过滤
    if intent == "port_status" and params.get("port"):
        port_num = params["port"]
        command = f"ss -tuln | head -1 && ss -tuln | grep :{_safe_arg(port_num, os_type)}"
    else:
        command = _derive_best_command(intent, params, os_type)

    # 特殊处理：需要动态组装命令的 intent ─────────────────────────────────────
    if intent == "search_files":
        directory = params.get("directory", ".")
        pattern = params.get("pattern", "*")
        if os_type == "windows":
            command = f'dir {_safe_arg(directory, os_type)}\\{_safe_arg(pattern, os_type)} /s'
        else:
            command = f"find {_safe_arg(directory, os_type)} -name {_safe_arg(pattern, os_type)}"
    elif intent == "create_user":
        username = params.get("username", "")
        password = params.get("password", "")
        if os_type == "windows":
            command = f'net user {_safe_arg(username, os_type)} /add'
        else:
            if password:
                command = f"useradd {_safe_arg(username, os_type)} && echo '{_safe_arg(username, os_type)}:{_safe_arg(password, os_type)}' | chpasswd"
            else:
                command = f"useradd {_safe_arg(username, os_type)}"
    elif intent == "delete_user":
        username = params.get("username", "")
        if os_type == "windows":
            command = f'net user {_safe_arg(username, os_type)} /delete'
        else:
            command = f"userdel {_safe_arg(username, os_type)}"
    elif intent == "install_software":
        package = params.get("package", "")
        if os_type in ("ubuntu", "debian"):
            command = f"apt-get update && apt-get install -y {_safe_arg(package, os_type)}"
        elif os_type in ("centos", "openeuler"):
            command = f"yum install -y {_safe_arg(package, os_type)}"
        else:
            command = f"apt-get install -y {_safe_arg(package, os_type)}"
    elif intent == "uninstall_software":
        package = params.get("package", "")
        if os_type in ("ubuntu", "debian"):
            command = f"apt-get remove -y {_safe_arg(package, os_type)}"
        elif os_type in ("centos", "openeuler"):
            command = f"yum remove -y {_safe_arg(package, os_type)}"
        else:
            command = f"apt-get remove -y {_safe_arg(package, os_type)}"
    elif intent == "manage_service":
        service = params.get("service", "")
        action = params.get("action", "status")
        if os_type in ("ubuntu", "debian", "centos", "openeuler"):
            command = f"systemctl {_safe_arg(action, os_type)} {_safe_arg(service, os_type)}"
        else:
            command = f"service {_safe_arg(service, os_type)} {_safe_arg(action, os_type)}"
    elif intent == "cleanup_logs":
        path = params.get("path", "/var/log")
        command = f"find {_safe_arg(path, os_type)} -name '*.log' -mtime +30 -delete"
    elif intent == "configure_sudo":
        username = params.get("username", "")
        if os_type in ("ubuntu", "debian"):
            command = f"usermod -aG sudo {_safe_arg(username, os_type)}"
        elif os_type in ("centos", "openeuler"):
            command = f"usermod -aG wheel {_safe_arg(username, os_type)}"
        else:
            command = f"usermod -aG sudo {_safe_arg(username, os_type)}"
    elif intent == "deploy_workspace":
        path = params.get("path", "")
        username = params.get("username", "")
        if not path:
            path = f"/home/{_safe_arg(username, os_type)}/workspace" if username else "/opt/workspace"
        command = f"mkdir -p {_safe_arg(path, os_type)}"
        if username:
            command += f" && chown {_safe_arg(username, os_type)}:{_safe_arg(username, os_type)} {_safe_arg(path, os_type)}"
    elif intent == "diagnostic":
        desc = params.get("description", "")
        if "80" in desc or "端口" in desc:
            command = "ss -tuln | grep :80 && systemctl status nginx 2>/dev/null || systemctl status apache2 2>/dev/null || echo 'No web server found'"
        else:
            command = "echo 'Diagnostic mode: please specify the issue'"
    elif intent == "other":
        fallback_command = (state.get("user_input", "") or params.get("fallback_text", "")).strip()
        if ALLOW_RAW_SHELL_FALLBACK and SecurityTools.is_safe_raw_shell_fallback(fallback_command):
            command = fallback_command
        else:
            risk = RiskAssessment(
                risk_level="high",
                risk_explanation="Unsupported request. Raw shell fallback is disabled by default.",
                risk_mitigation="Map the request to a supported intent or explicitly enable ALLOW_RAW_SHELL_FALLBACK.",
                command_impact=["未知操作"],
                environmental_risk=SecurityTools.assess_environmental_risk(fallback_command, env),
                requires_confirmation=False
            )
            return {
                "command": "",
                "risk_level": risk.risk_level,
                "risk_explanation": risk.risk_explanation,
                "risk_assessment": risk.to_dict(),
                "abort_execution": True,
                "execution_result": risk.risk_explanation,
                "task_status": "failed"
            }

    if not StateValidator.validate_command(command):
        return {"command": "", "risk_level": "low", "risk_explanation": "Invalid command"}

    risk = RiskAssessment(
        risk_level=SecurityTools.assess_risk_level(command, os_type),
        risk_explanation=SecurityTools.get_risk_explanation(command, os_type),
        risk_mitigation=SecurityTools.get_risk_mitigation_suggestion(command, os_type),
        command_impact=SecurityTools.analyze_command_impact(command, os_type),
        environmental_risk=SecurityTools.assess_environmental_risk(command, env),
        requires_confirmation=False
    )

    if risk.risk_level == "medium":
        risk.requires_confirmation = True

    return {
        "command": command,
        "risk_level": risk.risk_level,
        "risk_explanation": risk.risk_explanation,
        "risk_assessment": risk.to_dict()
    }


def check_risk_flow(state: AgentState) -> str:
    if state.get("abort_execution"):
        return "done"
    if state.get("skip_to_next"):
        return "loop"
    if not state.get("pre_check_passed", True):
        return "done"
    if state.get("user_confirmation") is not None:
        return "handle_confirmation"
    risk_assessment = state.get("risk_assessment", {})
    if risk_assessment.get("requires_confirmation"):
        return "need_confirmation"
    return "execute"


def execute_command(state: AgentState) -> Dict[str, Any]:
    command = state.get("command", "")
    env = state.get("environment", {})
    os_type = env.get("os_type", "linux")
    task_sequence = state.get("task_sequence", [])
    idx = state.get("current_task_index", 0)
    task = task_sequence[idx] if task_sequence and idx < len(task_sequence) else {}
    rollback_stack = state.get("rollback_stack", [])
    execution_log = state.get("execution_log", [])

    if not command:
        result_text = "无有效命令可执行"
        if task_sequence and idx < len(task_sequence):
            updated = list(task_sequence)
            updated[idx] = {**updated[idx], "status": "failed", "result": result_text}
            next_idx = _get_next_task_index(state, idx)
            return {
                "execution_result": result_text,
                "task_sequence": updated,
                "current_task_index": next_idx,
                "task_status": "in_progress" if next_idx < len(updated) else "completed"
            }
        return {"execution_result": result_text}

    if SecurityTools.should_block_command(command, os_type):
        result_text = f"已阻止高风险命令: {command}\n{state.get('risk_explanation', '')}"
        audit_logger.log_security_event(
            session_id=state.get("session_id", ""),
            event_type="high_risk_blocked",
            command=command,
            risk_level="high",
            risk_explanation=state.get("risk_explanation", ""),
            action_taken="blocked"
        )
        if task_sequence and idx < len(task_sequence):
            updated = list(task_sequence)
            updated[idx] = {**updated[idx], "status": "failed", "result": result_text}
            next_idx = _get_next_task_index(state, idx)
            return {
                "execution_result": result_text,
                "task_sequence": updated,
                "current_task_index": next_idx,
                "task_status": "in_progress" if next_idx < len(updated) else "completed"
            }
        return {"execution_result": result_text}

    max_retries = MAX_RETRIES
    result_text = ""
    success = False
    retries = 0

    for attempt in range(max_retries):
        try:
            result = SystemTools._run_command(command, timeout=DEFAULT_TIMEOUT)
            result_text = f"Exit code: {result['exit_code']}\n"
            if result["stdout"]:
                result_text += f"STDOUT:\n{result['stdout']}\n"
            if result["stderr"]:
                result_text += f"STDERR:\n{result['stderr']}\n"

            if result["exit_code"] == 0:
                success = True
                break

            if attempt + 1 < max_retries:
                retries += 1
                result_text += f"\n重试 ({retries}/{max_retries - 1})...\n"
                time.sleep(1)
        except Exception as e:
            result_text = f"执行错误: {str(e)}"
            if attempt + 1 < max_retries:
                retries += 1
                result_text += f"\n重试 ({retries}/{max_retries - 1})...\n"
                time.sleep(1)
    task_status = "completed" if success else "failed"

    post_validation = task.get("post_validation")
    if success and post_validation:
        val_cmd = post_validation.get("validation_command", "")
        expected = post_validation.get("expected_result", "")
        if val_cmd:
            try:
                val_result = SystemTools._run_command(val_cmd, timeout=10)
                val_output = val_result.get("stdout", "") + val_result.get("stderr", "")
                validated = expected.lower() in val_output.lower() if expected else val_result.get("exit_code", -1) == 0
                if not validated:
                    val_failure_action = post_validation.get("failure_action", "retry")
                    if val_failure_action == "retry" and retries < max_retries:
                        result_text += f"\n后验证失败，重试命令...\n"
                        task_status = "failed"
                    elif val_failure_action == "skip":
                        result_text += f"\n后验证失败，但标记为跳过\n"
                        task_status = "completed"
            except Exception as e:
                result_text += f"\n后验证执行错误: {str(e)}\n"

    if task.get("can_rollback") and task.get("rollback_action"):
        rollback_stack.append({
            "task_id": task.get("task_id", ""),
            "rollback_command": task["rollback_action"].get("command", ""),
            "description": task["rollback_action"].get("description", "")
        })

    log_entry = {
        "task_id": task.get("task_id", ""),
        "intent": task.get("intent", "other"),
        "command": command,
        "status": task_status,
        "timestamp": time.time(),
        "retries": retries
    }
    execution_log.append(log_entry)

    if task_sequence and idx < len(task_sequence):
        updated = list(task_sequence)
        updated[idx] = {
            **updated[idx],
            "status": task_status,
            "result": result_text,
            "retries": retries,
            "command": command
        }
        next_idx = _get_next_task_index(state, idx)

        audit_logger.log_task(
            session_id=state.get("session_id", ""),
            task_index=idx,
            intent=updated[idx].get("intent", "other"),
            parameters=updated[idx].get("parameters"),
            command=command,
            status=task_status,
            result=result_text,
            retries=retries,
            risk_info=state.get("risk_assessment")
        )

        return {
            "execution_result": result_text,
            "task_sequence": updated,
            "current_task_index": next_idx,
            "task_status": "in_progress" if next_idx < len(updated) else "completed",
            "rollback_stack": rollback_stack,
            "execution_log": execution_log
        }

    audit_logger.log_task(
        session_id=state.get("session_id", ""),
        task_index=idx,
        intent=task.get("intent", "other"),
        command=command,
        status=task_status,
        result=result_text,
        retries=retries,
        risk_info=state.get("risk_assessment")
    )

    return {
        "execution_result": result_text,
        "rollback_stack": rollback_stack,
        "execution_log": execution_log
    }


def check_loop(state: AgentState) -> str:
    if state.get("abort_execution"):
        return "done"
    if state.get("task_status") == "failed":
        return "handle_error"
    if state.get("task_status") == "in_progress":
        return "loop"
    return "done"


def generate_response(state: AgentState) -> Dict[str, Any]:
    user_input = state.get("user_input", "")
    execution_result = state.get("execution_result", "")
    task_sequence = state.get("task_sequence", [])
    env = state.get("environment", {})
    history = state.get("conversation_history", [])
    os_type = env.get("os_type", "Unknown")
    execution_log = state.get("execution_log", [])
    branch_results = state.get("branch_results", {})
    last_intent = state.get("last_intent", "")
    consistency_issues = state.get("consistency_issues", [])

    current_intent = task_sequence[-1].get("intent", "other") if task_sequence else "other"

    if state.get("risk_assessment", {}).get("requires_confirmation") and state.get("user_confirmation") is not True:
        risk_expl = state.get("risk_explanation", "")
        risk_level = state.get("risk_level", "medium")
        command = state.get("command", "")
        risk_assessment = state.get("risk_assessment", {})
        impact_list = risk_assessment.get("command_impact", []) if risk_assessment else []
        impact_text = "、".join(impact_list) if impact_list else "系统配置变更"
        confirmation_msg = f"⚠️ **该操作需要您的确认**\n\n"
        confirmation_msg += f"**风险等级**：{risk_level}\n"
        confirmation_msg += f"**待执行命令**：`{command}`\n"
        confirmation_msg += f"**风险说明**：{risk_expl}\n"
        confirmation_msg += f"**潜在影响**：{impact_text}\n\n"
        confirmation_msg += "请确认是否执行此操作。"
        return {
            "response": confirmation_msg,
            "requires_confirmation": True,
            "conversation_history": history,
            "explanation": explainer.explain_risk(risk_level, command),
            "last_intent": current_intent,
            "consistency_issues": consistency_issues
        }

    if last_intent and last_intent != current_intent:
        context_change = explainer.explain_context_change(last_intent, current_intent, len(history))
    else:
        context_change = ""

    if len(task_sequence) > 1:
        parts = []
        for i, t in enumerate(task_sequence):
            intent = t.get("intent", "other")
            status = t.get("status", "unknown")
            result = t.get("result", "")
            error = result if status == "failed" else ""
            op_expl = explainer.explain_operation(intent, status, result, error)
            parts.append(f"### 任务 {i+1}\n{op_expl}")
        summary = "\n\n".join(parts)

        if branch_results:
            branch_info = "\n**条件分支结果**：\n" + "\n".join(f"  - {k}: {'✓ 满足' if v else '✗ 不满足'}" for k, v in branch_results.items())
            summary += branch_info

        prompt = f"用户请求: {user_input}\n\n执行环境: {os_type}\n\n任务结果:\n{summary}\n\n请用中文给出综合执行结果摘要。"
    else:
        intent = task_sequence[0].get("intent", "other") if task_sequence else "other"
        status = task_sequence[0].get("status", "completed") if task_sequence else "completed"
        op_expl = explainer.explain_operation(intent, status, execution_result)
        prompt = f"用户请求: {user_input}\n\n执行环境: {os_type}\n\n{op_expl}\n\n请用中文给出清晰的执行结果说明。"

    if context_change:
        prompt += f"\n\n上下文变化说明：{context_change}"

    messages = [
        {"role": "system", "content": (
            "你是操作系统管理助手，运行在 Web 交互界面中。严格遵守以下回复规则：\n"
            "1. 重点是结果：直接展示命令执行的关键数据（数值、状态、列表），不要解释命令本身。\n"
            "2. 绝对禁止输出'相关命令'、'常用命令'、'你还可以'、'如需了解'等教学性段落。\n"
            "3. 禁止解释表头含义（如'PID是进程ID'）、字段说明、状态说明表格。\n"
            "4. 提示和建议最多一两句话放末尾，不超过30字。没有必要时不写。\n"
            "5. 表格数据完整展示全部数据行，禁止用省略号截断。\n"
            "6. 使用 Markdown 表格排版结构化数据。\n"
            "7. 回复语言：中文。回复总长度尽量控制在300字以内。"
        )}
    ]
    for msg in history[-5:]:
        messages.append(msg)
    messages.append({"role": "user", "content": prompt})

    if not _api_initialized or client is None:
        # 未配置 API Key 时，直接使用 explainability 引擎生成回复
        intent = task_sequence[0].get("intent", "other") if task_sequence else "other"
        response_text = explainer.generate_full_explanation(
            intent=intent,
            status=task_sequence[0].get("status", "completed") if task_sequence else "completed",
            command=state.get("command", ""),
            result=execution_result
        )
    else:
        try:
            resp = client.chat.completions.create(
                model=OPENAI_MODEL,
                messages=messages,
                temperature=0.7,
                max_tokens=800,
                timeout=30
            )
            response_text = resp.choices[0].message.content.strip()
            # 剥离 LLM 思考链标签（<think>...</think> 或 <thinking>...</thinking>）
            response_text = re.sub(r"<think>[\s\S]*?</think>\s*", "", response_text, flags=re.DOTALL)
            response_text = re.sub(r"<thinking>[\s\S]*?</thinking>\s*", "", response_text, flags=re.DOTALL)
            # 处理未闭合的思考标签（标签后的所有内容都是思考过程）
            for tag in ("<think>", "<thinking>"):
                idx = response_text.find(tag)
                if idx != -1:
                    response_text = response_text[:idx]
            response_text = response_text.strip()
        except Exception:
            intent = task_sequence[0].get("intent", "other") if task_sequence else "other"
            response_text = explainer.generate_full_explanation(
                intent=intent,
                status=task_sequence[0].get("status", "completed") if task_sequence else "completed",
                command=state.get("command", ""),
                result=execution_result
            )

    new_history = history + [{"role": "assistant", "content": response_text}]

    explanation_context = {
        "user_input": user_input,
        "os_type": os_type,
        "history": history
    }
    polished_explanation = explainer.polish_explanation(
        state.get("explanation", ""),
        explanation_context
    )

    audit_logger.log_interaction(
        session_id=state.get("session_id", ""),
        user_input=user_input,
        intent=state.get("intent", "other"),
        command=state.get("command", ""),
        risk_level=state.get("risk_level", "unknown"),
        execution_result=execution_result,
        response=response_text,
        metadata={"os_type": os_type, "task_count": len(task_sequence), "explanation": polished_explanation}
    )

    # 不返回 explanation（think内容）给前端，避免显示给用户
    return {
        "response": response_text,
        "conversation_history": new_history,
        "explanation": "",
        "last_intent": current_intent,
        "consistency_issues": consistency_issues
    }




def generate_response_streaming(state: AgentState):
    """流式生成 LLM 响应（用于 SSE 流式输出）"""
    user_input = state.get("user_input", "")
    execution_result = state.get("execution_result", "")
    task_sequence = state.get("task_sequence", [])
    env = state.get("environment", {})
    history = state.get("conversation_history", [])
    os_type = env.get("os_type", "Unknown")
    branch_results = state.get("branch_results", {})
    last_intent = state.get("last_intent", "")

    current_intent = task_sequence[-1].get("intent", "other") if task_sequence else "other"

    if len(task_sequence) > 1:
        parts = []
        for i, t in enumerate(task_sequence):
            intent = t.get("intent", "other")
            status = t.get("status", "unknown")
            result = t.get("result", "")
            error = result if status == "failed" else ""
            op_expl = explainer.explain_operation(intent, status, result, error)
            parts.append(f"### 任务 {i+1}\n{op_expl}")
        summary = "\n\n".join(parts)
        if branch_results:
            branch_info = "\n**条件分支结果**：\n" + "\n".join(f"  - {k}: {'✓ 满足' if v else '✗ 不满足'}" for k, v in branch_results.items())
            summary += branch_info
        prompt = f"用户请求: {user_input}\n\n执行环境: {os_type}\n\n任务结果:\n{summary}\n\n请用中文给出综合执行结果摘要。"
    else:
        intent = task_sequence[0].get("intent", "other") if task_sequence else "other"
        status = task_sequence[0].get("status", "completed") if task_sequence else "completed"
        op_expl = explainer.explain_operation(intent, status, execution_result)
        prompt = f"用户请求: {user_input}\n\n执行环境: {os_type}\n\n{op_expl}\n\n请用中文给出清晰的执行结果说明。"

    messages = [
        {"role": "system", "content": (
            "你是操作系统管理助手，运行在 Web 交互界面中。严格遵守以下回复规则：\n"
            "1. 重点是结果：直接展示命令执行的关键数据（数值、状态、列表），不要解释命令本身。\n"
            "2. 绝对禁止输出'相关命令'、'常用命令'、'你还可以'、'如需了解'等教学性段落。\n"
            "3. 禁止解释表头含义（如'PID是进程ID'）、字段说明、状态说明表格。\n"
            "4. 提示和建议最多一两句话放末尾，不超过30字。没有必要时不写。\n"
            "5. 表格数据完整展示全部数据行，禁止用省略号截断。\n"
            "6. 使用 Markdown 表格排版结构化数据。\n"
            "7. 回复语言：中文。回复总长度尽量控制在300字以内。"
        )}
    ]
    for msg in history[-5:]:
        messages.append(msg)
    messages.append({"role": "user", "content": prompt})

    def stream_generator():
        try:
            stream = client.chat.completions.create(
                model=OPENAI_MODEL,
                messages=messages,
                temperature=0.7,
                max_tokens=800,
                timeout=30,
                stream=True
            )
            buffer = []
            for chunk in stream:
                delta = chunk.choices[0].delta.content or ""
                if delta:
                    buffer.append(delta)
            # 流结束后整体剥离 think 标签，再 yield（SSE 最终内容）
            full_text = "".join(buffer)
            full_text = re.sub(r"<think>[\s\S]*?</think>\s*", "", full_text, flags=re.DOTALL)
            full_text = re.sub(r"<thinking>[\s\S]*?</thinking>\s*", "", full_text, flags=re.DOTALL)
            for tag in ("<think>", "<thinking>"):
                idx = full_text.find(tag)
                if idx != -1:
                    full_text = full_text[:idx]
            full_text = full_text.strip()
            # 逐字符流式发送（保留流式体验）
            import time as _time
            for ch in full_text:
                yield f"data: {ch}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as e:
            yield f"data: [ERROR] {str(e)}\n\n"

    return stream_generator()



def handle_confirmation(state: AgentState) -> Dict[str, Any]:
    user_confirmed = state.get("user_confirmation", False)
    command = state.get("command", "")
    task_sequence = state.get("task_sequence", [])
    idx = state.get("current_task_index", 0)

    confirmation_explanation = explainer.explain_decision("risk_decision", {
        "confirmed" if user_confirmed else "rejected": True,
        "reason": state.get("risk_explanation", ""),
        "level": state.get("risk_level", "medium")
    })

    audit_logger.log_security_event(
        session_id=state.get("session_id", ""),
        event_type="confirmation_request",
        command=command,
        risk_level=state.get("risk_level", "medium"),
        action_taken="confirmed" if user_confirmed else "rejected"
    )

    if user_confirmed:
        return {
            "risk_assessment": {**state.get("risk_assessment", {}), "requires_confirmation": False},
            "explanation": confirmation_explanation
        }
    else:
        result_text = "操作已取消（用户拒绝执行高风险操作）"
        if task_sequence and idx < len(task_sequence):
            updated = list(task_sequence)
            updated[idx] = {**updated[idx], "status": "cancelled", "result": result_text}
            next_idx = _get_next_task_index(state, idx)
            return {
                "execution_result": result_text,
                "task_sequence": updated,
                "current_task_index": next_idx,
                "task_status": "in_progress" if next_idx < len(updated) else "completed",
                "risk_assessment": {**state.get("risk_assessment", {}), "requires_confirmation": False},
                "explanation": confirmation_explanation
            }
        return {
            "execution_result": result_text,
            "risk_assessment": {**state.get("risk_assessment", {}), "requires_confirmation": False},
            "explanation": confirmation_explanation
        }


def handle_error(state: AgentState) -> Dict[str, Any]:
    task_sequence = state.get("task_sequence", [])
    idx = state.get("current_task_index", 0)
    task = task_sequence[idx] if task_sequence and idx < len(task_sequence) else {}
    error_strategy = task.get("error_strategy", "retry")
    rollback_stack = state.get("rollback_stack", [])
    result_text = "错误处理完成（默认重试策略由 execute_command 循环处理）"

    error_explanation = explainer.explain_decision("error_handling", {
        "strategy": error_strategy,
        "attempt": task.get("retries", 0),
        "action": error_strategy
    })

    if error_strategy == "skip":
        result_text = f"任务失败，根据策略跳过: {task.get('intent', '')}"
        if task_sequence and idx < len(task_sequence):
            updated = list(task_sequence)
            updated[idx] = {**updated[idx], "status": "skipped", "result": result_text}
            next_idx = _get_next_task_index(state, idx)
            return {
                "execution_result": result_text,
                "task_sequence": updated,
                "current_task_index": next_idx,
                "task_status": "in_progress" if next_idx < len(updated) else "completed",
                "explanation": error_explanation
            }
    elif error_strategy == "rollback":
        if rollback_stack:
            last_rollback = rollback_stack.pop()
            rb_cmd = last_rollback.get("rollback_command", "")
            if rb_cmd:
                try:
                    rb_result = SystemTools._run_command(rb_cmd, timeout=30)
                    result_text = f"已执行回滚: {rb_cmd}\n结果: {rb_result.get('stdout', '')}"
                    audit_logger.log_security_event(
                        session_id=state.get("session_id", ""),
                        event_type="rollback",
                        command=rb_cmd,
                        risk_level="low",
                        action_taken="rolled_back"
                    )
                    if task_sequence and idx < len(task_sequence):
                        updated = list(task_sequence)
                        updated[idx] = {**updated[idx], "status": "rolled_back", "result": result_text}
                        next_idx = _get_next_task_index(state, idx)
                        return {
                            "execution_result": result_text,
                            "task_sequence": updated,
                            "current_task_index": next_idx,
                            "task_status": "in_progress" if next_idx < len(updated) else "completed",
                            "rollback_stack": rollback_stack,
                            "explanation": error_explanation
                        }
                except Exception as e:
                    result_text = f"回滚执行失败: {str(e)}"
            else:
                result_text = "无可执行的回滚命令"
        else:
            result_text = "无回滚信息，无法回滚"
    elif error_strategy == "abort":
        result_text = "根据策略中止执行"
        return {
            "execution_result": result_text,
            "task_status": "failed",
            "explanation": error_explanation
        }

    if task_sequence and idx < len(task_sequence):
        updated = list(task_sequence)
        updated[idx] = {**updated[idx], "status": "failed", "result": result_text}
        next_idx = _get_next_task_index(state, idx)
        return {
            "execution_result": result_text,
            "task_sequence": updated,
            "current_task_index": next_idx,
            "task_status": "in_progress" if next_idx < len(updated) else "completed"
        }

    return {
        "execution_result": result_text,
        "task_status": "completed"
    }


def build_workflow():
    workflow = StateGraph(AgentState)

    workflow.add_node("detect_environment", detect_environment)
    workflow.add_node("identify_intent", identify_intent)
    workflow.add_node("pre_check_task", pre_check_task)
    workflow.add_node("generate_command", generate_command)
    workflow.add_node("handle_confirmation", handle_confirmation)
    workflow.add_node("execute_command", execute_command)
    workflow.add_node("handle_error", handle_error)
    workflow.add_node("generate_response", generate_response)

    workflow.set_entry_point("detect_environment")
    workflow.add_edge("detect_environment", "identify_intent")
    workflow.add_edge("identify_intent", "pre_check_task")
    workflow.add_conditional_edges(
        "pre_check_task",
        lambda s: "abort" if s.get("abort_execution") else ("skip" if s.get("skip_to_next") else "generate"),
        {"abort": "generate_response", "skip": "generate_command", "generate": "generate_command"}
    )
    workflow.add_conditional_edges(
        "generate_command",
        check_risk_flow,
        {
            "need_confirmation": "generate_response",
            "handle_confirmation": "handle_confirmation",
            "execute": "execute_command",
            "loop": "execute_command",
            "done": "generate_response"
        }
    )
    workflow.add_conditional_edges(
        "handle_confirmation",
        lambda s: "execute" if s.get("user_confirmation") is True else "done",
        {"execute": "execute_command", "done": "generate_response"}
    )
    workflow.add_conditional_edges(
        "execute_command",
        check_loop,
        {"loop": "generate_command", "handle_error": "handle_error", "done": "generate_response"}
    )
    workflow.add_edge("handle_error", "generate_response")
    workflow.add_edge("generate_response", END)

    return workflow.compile()
