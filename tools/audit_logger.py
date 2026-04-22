import sqlite3
import json
import time
import os
from typing import Optional, List, Dict, Any


class AuditLogger:
    def __init__(self, db_path: Optional[str] = None):
        if db_path is None:
            db_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "audit.db")
        self.db_path = db_path
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        conn = self._get_conn()
        cursor = conn.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL NOT NULL,
                session_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                user_input TEXT,
                intent TEXT,
                command TEXT,
                risk_level TEXT,
                execution_result TEXT,
                response TEXT,
                metadata TEXT
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS task_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL NOT NULL,
                session_id TEXT NOT NULL,
                task_index INTEGER NOT NULL,
                intent TEXT NOT NULL,
                parameters TEXT,
                command TEXT,
                status TEXT NOT NULL,
                result TEXT,
                retries INTEGER DEFAULT 0,
                risk_info TEXT
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS security_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL NOT NULL,
                session_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                command TEXT,
                risk_level TEXT,
                risk_explanation TEXT,
                action_taken TEXT,
                metadata TEXT
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS environment_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL NOT NULL,
                session_id TEXT NOT NULL,
                os_type TEXT,
                os_info TEXT,
                hardware_info TEXT,
                snapshot_data TEXT
            )
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_audit_session ON audit_log(session_id, timestamp)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_task_session ON task_history(session_id, timestamp)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_security_session ON security_events(session_id, timestamp)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_env_session ON environment_snapshots(session_id, timestamp)
        """)

        conn.commit()
        conn.close()

    def log_interaction(
        self,
        session_id: str,
        user_input: str,
        intent: str,
        command: str,
        risk_level: str,
        execution_result: str,
        response: str,
        metadata: Optional[Dict] = None
    ):
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO audit_log (
                timestamp, session_id, event_type, user_input, intent,
                command, risk_level, execution_result, response, metadata
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            time.time(),
            session_id,
            "interaction",
            user_input,
            intent,
            command,
            risk_level,
            execution_result,
            response,
            json.dumps(metadata or {}, ensure_ascii=False)
        ))
        conn.commit()
        conn.close()

    def log_task(
        self,
        session_id: str,
        task_index: int,
        intent: str,
        parameters: Optional[Dict] = None,
        command: Optional[str] = None,
        status: str = "pending",
        result: Optional[str] = None,
        retries: int = 0,
        risk_info: Optional[Dict] = None
    ):
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO task_history (
                timestamp, session_id, task_index, intent, parameters,
                command, status, result, retries, risk_info
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            time.time(),
            session_id,
            task_index,
            intent,
            json.dumps(parameters or {}, ensure_ascii=False),
            command,
            status,
            result,
            retries,
            json.dumps(risk_info or {}, ensure_ascii=False)
        ))
        conn.commit()
        conn.close()

    def log_security_event(
        self,
        session_id: str,
        event_type: str,
        command: Optional[str] = None,
        risk_level: Optional[str] = None,
        risk_explanation: Optional[str] = None,
        action_taken: Optional[str] = None,
        metadata: Optional[Dict] = None
    ):
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO security_events (
                timestamp, session_id, event_type, command, risk_level,
                risk_explanation, action_taken, metadata
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            time.time(),
            session_id,
            event_type,
            command,
            risk_level,
            risk_explanation,
            action_taken,
            json.dumps(metadata or {}, ensure_ascii=False)
        ))
        conn.commit()
        conn.close()

    def log_environment_snapshot(
        self,
        session_id: str,
        os_type: str,
        os_info: Optional[Dict] = None,
        hardware_info: Optional[Dict] = None,
        snapshot_data: Optional[Dict] = None
    ):
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO environment_snapshots (
                timestamp, session_id, os_type, os_info, hardware_info, snapshot_data
            ) VALUES (?, ?, ?, ?, ?, ?)
        """, (
            time.time(),
            session_id,
            os_type,
            json.dumps(os_info or {}, ensure_ascii=False),
            json.dumps(hardware_info or {}, ensure_ascii=False),
            json.dumps(snapshot_data or {}, ensure_ascii=False)
        ))
        conn.commit()
        conn.close()

    def get_session_history(self, session_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM audit_log
            WHERE session_id = ?
            ORDER BY timestamp DESC
            LIMIT ?
        """, (session_id, limit))
        rows = cursor.fetchall()
        conn.close()
        return [dict(row) for row in rows]

    def get_security_events(self, session_id: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
        conn = self._get_conn()
        cursor = conn.cursor()
        if session_id:
            cursor.execute("""
                SELECT * FROM security_events
                WHERE session_id = ?
                ORDER BY timestamp DESC
                LIMIT ?
            """, (session_id, limit))
        else:
            cursor.execute("""
                SELECT * FROM security_events
                ORDER BY timestamp DESC
                LIMIT ?
            """, (limit,))
        rows = cursor.fetchall()
        conn.close()
        return [dict(row) for row in rows]

    def get_session_statistics(self, session_id: str) -> Dict[str, Any]:
        conn = self._get_conn()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT COUNT(*) as total_interactions,
                   SUM(CASE WHEN risk_level = 'high' THEN 1 ELSE 0 END) as high_risk_count,
                   SUM(CASE WHEN risk_level = 'medium' THEN 1 ELSE 0 END) as medium_risk_count,
                   SUM(CASE WHEN risk_level = 'low' THEN 1 ELSE 0 END) as low_risk_count,
                   MIN(timestamp) as first_activity,
                   MAX(timestamp) as last_activity
            FROM audit_log WHERE session_id = ?
        """, (session_id,))
        stats = dict(cursor.fetchone())

        cursor.execute("""
            SELECT COUNT(*) as total_tasks,
                   SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as completed_tasks,
                   SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed_tasks
            FROM task_history WHERE session_id = ?
        """, (session_id,))
        task_stats = dict(cursor.fetchone())

        conn.close()
        return {**stats, **task_stats}

    def get_all_sessions(self, limit: int = 100) -> List[Dict[str, Any]]:
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT DISTINCT session_id,
                   COUNT(*) as interaction_count,
                   MAX(timestamp) as last_activity,
                   MIN(timestamp) as created_at
            FROM audit_log
            GROUP BY session_id
            ORDER BY last_activity DESC
            LIMIT ?
        """, (limit,))
        rows = cursor.fetchall()
        conn.close()
        return [dict(row) for row in rows]
