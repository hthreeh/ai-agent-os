import time
import json
import os

class StateManager:
    def __init__(self, state_file=None):
        """初始化状态管理器"""
        self.state_file = state_file or os.path.join(os.path.dirname(__file__), "..", "state.json")
        self.current_state = self.load_state()
        self.last_update_time = time.time()
    
    def load_state(self):
        """加载状态"""
        try:
            if os.path.exists(self.state_file):
                with open(self.state_file, "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception:
            pass
        return {
            "system": {
                "last_boot": time.time(),
                "uptime": 0
            },
            "tasks": {
                "completed": [],
                "failed": [],
                "pending": []
            },
            "security": {
                "high_risk_attempts": [],
                "last_security_check": time.time()
            },
            "environment": {
                "last_detection": 0,
                "changes": []
            },
            "audit": {
                "events": []
            }
        }
    
    def save_state(self):
        """保存状态"""
        try:
            os.makedirs(os.path.dirname(self.state_file), exist_ok=True)
            with open(self.state_file, "w", encoding="utf-8") as f:
                json.dump(self.current_state, f, indent=2)
        except Exception:
            pass
    
    def update_system_state(self):
        """更新系统状态"""
        current_time = time.time()
        self.current_state["system"]["uptime"] = current_time - self.current_state["system"]["last_boot"]
        self.last_update_time = current_time
        self.save_state()
    
    def add_task_result(self, task_id, status, result, risk_info=None, retries=0):
        """添加任务结果"""
        task_info = {
            "task_id": task_id,
            "timestamp": time.time(),
            "status": status,
            "result": result,
            "risk_info": risk_info,
            "retries": retries
        }
        
        if status == "completed":
            self.current_state["tasks"]["completed"].append(task_info)
        elif status == "failed":
            self.current_state["tasks"]["failed"].append(task_info)
        elif status == "cancelled":
            self.current_state["tasks"]["failed"].append(task_info)  # 取消的任务也记录为失败
        
        # 限制任务历史记录数量
        max_history = 100
        for task_type in ["completed", "failed"]:
            if len(self.current_state["tasks"][task_type]) > max_history:
                self.current_state["tasks"][task_type] = self.current_state["tasks"][task_type][-max_history:]
        
        self.save_state()
    
    def get_task_history(self, limit=20):
        """获取任务历史"""
        all_tasks = self.current_state["tasks"]["completed"] + self.current_state["tasks"]["failed"]
        all_tasks.sort(key=lambda x: x["timestamp"], reverse=True)
        return all_tasks[:limit]
    
    def get_failed_tasks(self, limit=10):
        """获取失败的任务"""
        failed_tasks = self.current_state["tasks"]["failed"]
        failed_tasks.sort(key=lambda x: x["timestamp"], reverse=True)
        return failed_tasks[:limit]
    
    def get_task_statistics(self):
        """获取任务统计信息"""
        total_completed = len(self.current_state["tasks"]["completed"])
        total_failed = len(self.current_state["tasks"]["failed"])
        total_tasks = total_completed + total_failed
        
        success_rate = (total_completed / total_tasks * 100) if total_tasks > 0 else 0
        
        return {
            "total_tasks": total_tasks,
            "total_completed": total_completed,
            "total_failed": total_failed,
            "success_rate": success_rate
        }
    
    def add_security_event(self, event_type, details):
        """添加安全事件"""
        event = {
            "timestamp": time.time(),
            "event_type": event_type,
            "details": details
        }
        
        if event_type == "high_risk_attempt":
            self.current_state["security"]["high_risk_attempts"].append(event)
            # 限制高风险尝试记录数量
            max_attempts = 50
            if len(self.current_state["security"]["high_risk_attempts"]) > max_attempts:
                self.current_state["security"]["high_risk_attempts"] = self.current_state["security"]["high_risk_attempts"][-max_attempts:]
        
        self.current_state["security"]["last_security_check"] = time.time()
        self.save_state()

    def add_audit_log(self, event_type, details):
        """添加可审计事件日志"""
        event = {
            "timestamp": time.time(),
            "event_type": event_type,
            "details": details
        }
        audit = self.current_state.setdefault("audit", {"events": []})
        audit["events"].append(event)
        if len(audit["events"]) > 500:
            audit["events"] = audit["events"][-500:]
        self.save_state()
    
    def update_environment_state(self, environment_info):
        """更新环境状态"""
        current_time = time.time()
        
        # 检测环境变化
        if self.current_state["environment"]["last_detection"] > 0:
            # 比较环境信息
            old_os_type = self.current_state.get("environment", {}).get("os_type")
            new_os_type = environment_info.get("os_type")
            
            if old_os_type != new_os_type:
                change = {
                    "timestamp": current_time,
                    "type": "os_type_change",
                    "old_value": old_os_type,
                    "new_value": new_os_type
                }
                self.current_state["environment"]["changes"].append(change)
        
        # 更新环境信息
        self.current_state["environment"].update(environment_info)
        self.current_state["environment"]["last_detection"] = current_time
        
        # 限制环境变化记录数量
        max_changes = 50
        if len(self.current_state["environment"]["changes"]) > max_changes:
            self.current_state["environment"]["changes"] = self.current_state["environment"]["changes"][-max_changes:]
        
        self.save_state()
    
    def get_state_summary(self):
        """获取状态摘要"""
        self.update_system_state()
        
        summary = {
            "system": {
                "uptime": self.current_state["system"]["uptime"],
                "last_update": self.last_update_time
            },
            "tasks": {
                "completed_count": len(self.current_state["tasks"]["completed"]),
                "failed_count": len(self.current_state["tasks"]["failed"])
            },
            "security": {
                "high_risk_attempts_count": len(self.current_state["security"]["high_risk_attempts"]),
                "last_security_check": self.current_state["security"]["last_security_check"]
            },
            "environment": {
                "last_detection": self.current_state["environment"]["last_detection"],
                "changes_count": len(self.current_state["environment"]["changes"])
            },
            "audit": {
                "event_count": len(self.current_state.get("audit", {}).get("events", []))
            }
        }
        
        return summary
    
    def make_decision(self, context):
        """基于状态做出决策"""
        # 检查高风险尝试频率
        high_risk_attempts = self.current_state["security"]["high_risk_attempts"]
        recent_attempts = [attempt for attempt in high_risk_attempts if time.time() - attempt["timestamp"] < 3600]  # 最近1小时
        
        if len(recent_attempts) > 5:
            return {
                "action": "restrict",
                "reason": "Too many high-risk attempts in the last hour",
                "severity": "high"
            }
        
        # 检查系统运行时间
        if self.current_state["system"]["uptime"] > 86400 * 7:  # 7天
            return {
                "action": "suggest",
                "reason": "System has been running for more than 7 days",
                "suggestion": "Consider rebooting the system for maintenance"
            }
        
        # 检查任务失败率
        total_tasks = len(self.current_state["tasks"]["completed"]) + len(self.current_state["tasks"]["failed"])
        if total_tasks > 10:
            failure_rate = len(self.current_state["tasks"]["failed"]) / total_tasks
            if failure_rate > 0.3:  # 失败率超过30%
                return {
                    "action": "alert",
                    "reason": "High task failure rate",
                    "suggestion": "Check system configuration and permissions"
                }
        
        return {
            "action": "allow",
            "reason": "System state is normal"
        }
    
    def reset_state(self):
        """重置状态"""
        self.current_state = {
            "system": {
                "last_boot": time.time(),
                "uptime": 0
            },
            "tasks": {
                "completed": [],
                "failed": [],
                "pending": []
            },
            "security": {
                "high_risk_attempts": [],
                "last_security_check": time.time()
            },
            "environment": {
                "last_detection": 0,
                "changes": []
            },
            "audit": {
                "events": []
            }
        }
        self.save_state()
