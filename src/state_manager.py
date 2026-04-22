from typing import TypedDict, Optional, Dict, Any, List
from dataclasses import dataclass, field
from enum import Enum
import time
import re


class TaskStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    SKIPPED = "skipped"
    ROLLED_BACK = "rolled_back"


class TaskBranchType(str, Enum):
    SEQUENTIAL = "sequential"
    CONDITIONAL = "conditional"
    PARALLEL = "parallel"


class ErrorStrategy(str, Enum):
    RETRY = "retry"
    SKIP = "skip"
    ROLLBACK = "rollback"
    ABORT = "abort"


@dataclass
class EnvironmentContext:
    os_type: str = "linux"
    os_info: Optional[Dict[str, Any]] = None
    hardware_info: Optional[Dict[str, Any]] = None
    last_detected: float = 0.0
    cache_ttl: int = 3600

    def is_expired(self) -> bool:
        return (time.time() - self.last_detected) > self.cache_ttl

    def to_dict(self) -> Dict[str, Any]:
        return {
            "os_type": self.os_type,
            "os_info": self.os_info,
            "hardware_info": self.hardware_info,
            "last_detected": self.last_detected
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EnvironmentContext":
        return cls(
            os_type=data.get("os_type", "linux"),
            os_info=data.get("os_info"),
            hardware_info=data.get("hardware_info"),
            last_detected=data.get("last_detected", 0),
            cache_ttl=data.get("cache_ttl", 3600)
        )


@dataclass
class RiskAssessment:
    risk_level: str = "unknown"
    risk_explanation: str = ""
    risk_mitigation: str = ""
    command_impact: List[str] = field(default_factory=list)
    environmental_risk: Optional[Dict[str, Any]] = None
    requires_confirmation: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "risk_level": self.risk_level,
            "risk_explanation": self.risk_explanation,
            "risk_mitigation": self.risk_mitigation,
            "command_impact": self.command_impact,
            "environmental_risk": self.environmental_risk,
            "requires_confirmation": self.requires_confirmation
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RiskAssessment":
        return cls(
            risk_level=data.get("risk_level", "unknown"),
            risk_explanation=data.get("risk_explanation", ""),
            risk_mitigation=data.get("risk_mitigation", ""),
            command_impact=data.get("command_impact", []),
            environmental_risk=data.get("environmental_risk"),
            requires_confirmation=data.get("requires_confirmation", False)
        )


@dataclass
class PreCheckConfig:
    check_type: str = ""
    check_command: str = ""
    expected_condition: str = ""
    failure_action: str = "skip"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "check_type": self.check_type,
            "check_command": self.check_command,
            "expected_condition": self.expected_condition,
            "failure_action": self.failure_action
        }


@dataclass
class PostValidationConfig:
    validation_type: str = ""
    validation_command: str = ""
    expected_result: str = ""
    failure_action: str = "retry"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "validation_type": self.validation_type,
            "validation_command": self.validation_command,
            "expected_result": self.expected_result,
            "failure_action": self.failure_action
        }


@dataclass
class RollbackAction:
    command: str = ""
    description: str = ""
    auto_execute: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "command": self.command,
            "description": self.description,
            "auto_execute": self.auto_execute
        }


@dataclass
class TaskItem:
    intent: str = "other"
    description: str = ""
    parameters: Optional[Dict[str, Any]] = None
    command: Optional[str] = None
    status: str = "pending"
    result: Optional[str] = None
    retries: int = 0
    risk_info: Optional[Dict[str, Any]] = None
    task_id: str = ""

    depends_on: List[str] = field(default_factory=list)
    branch_type: str = "sequential"
    condition: Optional[Dict[str, Any]] = None
    on_true: Optional[List[str]] = None
    on_false: Optional[List[str]] = None

    pre_check: Optional[Dict[str, Any]] = None
    post_validation: Optional[Dict[str, Any]] = None
    error_strategy: str = "retry"
    is_critical: bool = True

    rollback_action: Optional[Dict[str, Any]] = None
    can_rollback: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "intent": self.intent,
            "description": self.description,
            "parameters": self.parameters,
            "command": self.command,
            "status": self.status,
            "result": self.result,
            "retries": self.retries,
            "risk_info": self.risk_info,
            "task_id": self.task_id,
            "depends_on": self.depends_on,
            "branch_type": self.branch_type,
            "condition": self.condition,
            "on_true": self.on_true,
            "on_false": self.on_false,
            "pre_check": self.pre_check,
            "post_validation": self.post_validation,
            "error_strategy": self.error_strategy,
            "is_critical": self.is_critical,
            "rollback_action": self.rollback_action,
            "can_rollback": self.can_rollback
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TaskItem":
        return cls(
            intent=data.get("intent", "other"),
            description=data.get("description", ""),
            parameters=data.get("parameters"),
            command=data.get("command"),
            status=data.get("status", "pending"),
            result=data.get("result"),
            retries=data.get("retries", 0),
            risk_info=data.get("risk_info"),
            task_id=data.get("task_id", ""),
            depends_on=data.get("depends_on", []),
            branch_type=data.get("branch_type", "sequential"),
            condition=data.get("condition"),
            on_true=data.get("on_true"),
            on_false=data.get("on_false"),
            pre_check=data.get("pre_check"),
            post_validation=data.get("post_validation"),
            error_strategy=data.get("error_strategy", "retry"),
            is_critical=data.get("is_critical", True),
            rollback_action=data.get("rollback_action"),
            can_rollback=data.get("can_rollback", False)
        )


class AgentState(TypedDict, total=False):
    session_id: str
    user_input: str
    conversation_history: List[Dict[str, str]]

    intent: str
    parameters: Dict[str, Any]
    task_sequence: List[Dict[str, Any]]
    current_task_index: int
    task_status: str

    command: str
    risk_level: str
    risk_explanation: str
    execution_result: str
    response: str

    environment: Dict[str, Any]
    risk_assessment: Dict[str, Any]
    state_decision: Dict[str, Any]

    user_confirmation: Optional[bool]
    requires_confirmation: Optional[bool]
    risk_info: Optional[Dict[str, Any]]

    pending_user_input: Optional[str]

    execution_log: List[Dict[str, Any]]
    rollback_stack: List[Dict[str, Any]]
    branch_results: Dict[str, Any]
    task_execution_order: List[str]

    explanation: str
    last_intent: str
    consistency_issues: List[str]


class StateValidator:
    @staticmethod
    def validate_state(state: Dict[str, Any]) -> Dict[str, Any]:
        validated = dict(state)

        if "session_id" not in validated or not validated["session_id"]:
            validated["session_id"] = f"session_{int(time.time())}"

        if "conversation_history" not in validated:
            validated["conversation_history"] = []
        elif not isinstance(validated["conversation_history"], list):
            validated["conversation_history"] = []

        if "parameters" not in validated:
            validated["parameters"] = {}
        elif not isinstance(validated["parameters"], dict):
            validated["parameters"] = {}

        if "task_sequence" not in validated:
            validated["task_sequence"] = []
        elif not isinstance(validated["task_sequence"], list):
            validated["task_sequence"] = []

        if "current_task_index" not in validated:
            validated["current_task_index"] = 0

        if "task_status" not in validated:
            validated["task_status"] = "pending"

        if "environment" not in validated:
            validated["environment"] = {}
        elif not isinstance(validated["environment"], dict):
            validated["environment"] = {}

        if "risk_assessment" not in validated:
            validated["risk_assessment"] = {}
        elif not isinstance(validated["risk_assessment"], dict):
            validated["risk_assessment"] = {}

        if "execution_log" not in validated:
            validated["execution_log"] = []

        if "rollback_stack" not in validated:
            validated["rollback_stack"] = []

        if "branch_results" not in validated:
            validated["branch_results"] = {}

        if "task_execution_order" not in validated:
            validated["task_execution_order"] = []

        if "explanation" not in validated:
            validated["explanation"] = ""

        if "last_intent" not in validated:
            validated["last_intent"] = ""

        if "consistency_issues" not in validated:
            validated["consistency_issues"] = []

        return validated

    @staticmethod
    def validate_command(command: str) -> bool:
        if not command or not isinstance(command, str):
            return False
        if len(command) > 500:
            return False
        return True

    @staticmethod
    def validate_risk_level(risk_level: str) -> bool:
        return risk_level in ("high", "medium", "low", "unknown")

    @staticmethod
    def validate_task_status(status: str) -> bool:
        valid_statuses = {
            "pending", "in_progress", "completed", "failed",
            "cancelled", "skipped", "rolled_back"
        }
        return status in valid_statuses

    @staticmethod
    def validate_error_strategy(strategy: str) -> bool:
        return strategy in ("retry", "skip", "rollback", "abort")

    @staticmethod
    def merge_environment(cached: Dict[str, Any], realtime: Dict[str, Any]) -> Dict[str, Any]:
        merged = dict(cached)
        merged.update(realtime)
        merged["last_detected"] = time.time()
        return merged

    @staticmethod
    def detect_circular_dependencies(tasks: List[Dict[str, Any]]) -> List[str]:
        task_ids = {t.get("task_id", "") for t in tasks}
        cycles = []

        def dfs(task_id: str, visited: set, rec_stack: set, path: list):
            visited.add(task_id)
            rec_stack.add(task_id)
            path.append(task_id)

            task = next((t for t in tasks if t.get("task_id") == task_id), None)
            if task:
                for dep_id in task.get("depends_on", []):
                    if dep_id not in task_ids:
                        continue
                    if dep_id not in visited:
                        cycle = dfs(dep_id, visited, rec_stack, path)
                        if cycle:
                            return cycle
                    elif dep_id in rec_stack:
                        cycle_start = path.index(dep_id)
                        cycles.append(path[cycle_start:] + [dep_id])
                        return path[cycle_start:] + [dep_id]

            path.pop()
            rec_stack.discard(task_id)
            return None

        visited = set()
        for task in tasks:
            task_id = task.get("task_id", "")
            if task_id and task_id not in visited:
                dfs(task_id, visited, set(), [])

        return cycles
