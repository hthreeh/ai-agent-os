import re
import time
import json
from typing import Any, Dict, List, Optional

from openai import OpenAI

from config.config import OPENAI_API_KEY, OPENAI_MODEL, OPENAI_BASE_URL


LLM_TASK_DECOMPOSITION_PROMPT = r"""你是一个操作系统任务规划专家。你的任务是将用户的复杂需求分解为可执行的子任务序列。

请严格按照以下JSON格式输出任务计划：
```json
{
  "tasks": [
    {
      "task_id": "task_0",
      "description": "任务描述",
      "intent": "任务意图类型",
      "parameters": {{}},
      "depends_on": [],
      "branch_type": "sequential",
      "error_strategy": "retry",
      "is_critical": true,
      "can_rollback": false
    }
  ]
}
```

可用意图类型：
- disk_usage: 检查磁盘使用情况
- process_status: 查看进程状态
- port_status: 查看端口状态
- os_info: 查看系统信息
- memory_usage: 查看内存使用
- cpu_usage: 查看CPU使用
- memory_top_processes: 查看内存占用最高的进程
- cpu_top_processes: 查看CPU占用最高的进程
- search_files: 搜索文件
- create_user: 创建用户
- delete_user: 删除用户
- install_software: 安装软件
- uninstall_software: 卸载软件
- manage_service: 管理服务（启动/停止/重启/状态）
- check_firewall: 检查防火墙规则
- cleanup_logs: 清理日志文件
- configure_sudo: 配置sudo权限
- deploy_workspace: 部署工作目录
- diagnostic: 诊断问题

用户输入：{user_input}
当前环境：{os_type}

请直接输出JSON，不要添加其他文字。
"""


class LLMTaskDecomposer:
    def __init__(self, api_key: str, model: str, base_url: str = ""):
        _kwargs = {"api_key": api_key}
        if base_url:
            _kwargs["base_url"] = base_url
        self.client = OpenAI(**_kwargs)
        self.model = model

    def decompose(self, user_input: str, os_type: str = "linux") -> List[Dict[str, Any]]:
        prompt = LLM_TASK_DECOMPOSITION_PROMPT.replace("{user_input}", user_input).replace("{os_type}", os_type)

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "你是一个操作系统任务规划专家。只输出JSON格式的任务计划。"},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,
                max_tokens=2000,
                timeout=30
            )

            content = response.choices[0].message.content.strip()
            content = self._extract_json(content)

            if content:
                plan = json.loads(content)
                tasks = plan.get("tasks", [])
                return self._normalize_tasks(tasks, user_input)
        except Exception as e:
            print(f"LLM 任务分解失败: {e}")

        return []

    def _extract_json(self, text: str) -> Optional[str]:
        # 尝试从文本中提取JSON
        text = text.strip()

        # 直接尝试解析
        if text.startswith("{"):
            return text

        # 查找JSON块
        json_match = re.search(r'```(?:json)?\s*(.*?)\s*```', text, re.DOTALL)
        if json_match:
            return json_match.group(1)

        # 查找第一个{到最后一个}
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            return text[start:end + 1]

        return None

    def _normalize_tasks(self, tasks: List[Dict], user_input: str) -> List[Dict[str, Any]]:
        normalized = []
        base_time = int(time.time())

        for idx, task in enumerate(tasks):
            normalized_task = {
                "task_id": task.get("task_id", f"task_{base_time}_{idx}"),
                "intent": task.get("intent", "other"),
                "description": task.get("description", task.get("intent", "")),
                "parameters": task.get("parameters", {}),
                "depends_on": task.get("depends_on", []),
                "branch_type": task.get("branch_type", "sequential"),
                "condition": task.get("condition"),
                "on_true": task.get("on_true"),
                "on_false": task.get("on_false"),
                "pre_check": task.get("pre_check"),
                "post_validation": task.get("post_validation"),
                "error_strategy": task.get("error_strategy", "retry"),
                "is_critical": task.get("is_critical", True),
                "can_rollback": task.get("can_rollback", False),
                "rollback_action": task.get("rollback_action"),
                "status": "pending",
                "result": None,
                "retries": 0,
                "command": None,
                "risk_info": None
            }
            normalized.append(normalized_task)

        return normalized

    def validate_plan(self, tasks: List[Dict]) -> Dict[str, Any]:
        # 检查循环依赖
        from src.state_manager import StateValidator
        cycles = StateValidator.detect_circular_dependencies(tasks)
        if cycles:
            return {
                "valid": False,
                "error": f"检测到循环依赖: {cycles}",
                "cycles": cycles
            }

        # 检查依赖是否存在
        task_ids = {t.get("task_id", f"fallback_{i}") for i, t in enumerate(tasks)}
        for idx, task in enumerate(tasks):
            task_id = task.get("task_id", f"fallback_{idx}")
            for dep_id in task.get("depends_on", []):
                if dep_id not in task_ids:
                    return {
                        "valid": False,
                        "error": f"任务 {task_id} 依赖不存在的任务 {dep_id}"
                    }

        for idx, task in enumerate(tasks):
            task_id = task.get("task_id", f"fallback_{idx}")
            if task.get("branch_type") == "conditional":
                if not task.get("condition"):
                    return {
                        "valid": False,
                        "error": f"任务 {task_id} 是条件分支但缺少 condition"
                    }

        return {"valid": True}
