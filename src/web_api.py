import os
import sys
import time
import json
import platform
import subprocess
import re as _re

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from typing import Optional, Dict, Any, List

from fastapi.middleware.cors import CORSMiddleware

from src.agent_workflow import build_workflow, _save_session, _load_session
from tools.audit_logger import AuditLogger
from config.config import CORS_ALLOWED_ORIGINS, ALLOW_ALL_CORS

audit_logger = AuditLogger()

app = FastAPI(
    title="操作系统智能代理",
    description="基于LangGraph的AI智能代理，支持自然语言交互进行Linux服务器管理",
    version="2.0.0",
)

cors_origins = ["*"] if ALLOW_ALL_CORS else (CORS_ALLOWED_ORIGINS or ["http://localhost", "http://127.0.0.1"])
allow_credentials = cors_origins != ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)

workflow = build_workflow()


# ── 数据模型 ─────────────────────────────────────────────────────────────────

class UserRequest(BaseModel):
    input: str
    session_id: Optional[str] = None


class ConfirmRequest(BaseModel):
    session_id: str
    confirmed: bool
    user_input: Optional[str] = None  # 仅用于生成回复，不用于恢复状态
    # 以下字段保留兼容性，但服务端会优先使用 session 中保存的状态
    risk_assessment: Optional[Dict] = None
    command: Optional[str] = None
    task_sequence: Optional[list] = None
    current_task_index: Optional[int] = None
    task_status: Optional[str] = None
    environment: Optional[Dict] = None
    risk_level: Optional[str] = None
    risk_explanation: Optional[str] = None


class AgentResponse(BaseModel):
    response: str
    execution_result: str
    risk_level: Optional[str] = None
    requires_confirmation: Optional[bool] = False
    risk_assessment: Optional[Dict] = None
    session_id: Optional[str] = None
    command: Optional[str] = None
    task_sequence: Optional[list] = None
    current_task_index: Optional[int] = None
    task_status: Optional[str] = None
    environment: Optional[Dict] = None
    branch_results: Optional[Dict] = None
    execution_log: Optional[list] = None
    explanation: Optional[str] = None


# ── 工具函数 ─────────────────────────────────────────────────────────────────

def _run_safe(args, timeout=5, shell=False):
    """安全执行子进程命令，失败返回空字符串"""
    try:
        r = subprocess.run(
            args, capture_output=True, text=True,
            timeout=timeout, check=False, shell=shell
        )
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception:
        return ""


# ── 实时环境信息 API ──────────────────────────────────────────────────────────

@app.get("/api/env/realtime")
async def get_realtime_env():
    """
    快速获取实时系统信息。
    直接读取 /proc 文件系统和少量系统命令，不经过 LLM，通常 <1s 完成。
    """
    info: Dict[str, Any] = {
        "hostname": platform.node(),
        "platform": platform.system(),
        "architecture": platform.machine(),
        "os_name": "",
        "kernel": "",
        "uptime": "",
        "load_avg": "",
        "cpu_percent": None,
        "memory": {},
        "disk": [],
        "network": [],
        "process_count": 0,
    }

    if platform.system() == "Linux":
        # OS 名称
        try:
            if os.path.exists("/etc/os-release"):
                with open("/etc/os-release", encoding="utf-8") as f:
                    for line in f:
                        if line.startswith("PRETTY_NAME="):
                            info["os_name"] = line.split("=", 1)[1].strip().strip('"')
                            break
        except Exception:
            pass

        # 内核版本
        info["kernel"] = _run_safe(["uname", "-r"])

        # 运行时间
        uptime_raw = _run_safe(["uptime", "-p"])
        info["uptime"] = uptime_raw.replace("up ", "", 1) if uptime_raw else ""

        # 负载均值（直接读 /proc/loadavg，极快）
        try:
            with open("/proc/loadavg", encoding="utf-8") as f:
                parts = f.read().split()
                info["load_avg"] = f"{parts[0]} {parts[1]} {parts[2]}"
        except Exception:
            pass

        # 内存（读 /proc/meminfo，比 free 命令快）
        try:
            mem: Dict[str, int] = {}
            with open("/proc/meminfo", encoding="utf-8") as f:
                for line in f:
                    parts = line.split()
                    key = parts[0].rstrip(":")
                    if key in ("MemTotal", "MemAvailable"):
                        mem[key] = int(parts[1])  # kB
            if "MemTotal" in mem and "MemAvailable" in mem:
                total_kb = mem["MemTotal"]
                avail_kb = mem["MemAvailable"]
                used_kb = total_kb - avail_kb
                total_mb = total_kb // 1024
                used_mb = used_kb // 1024
                info["memory"] = {
                    "total_mb": total_mb,
                    "used_mb": used_mb,
                    "percent": round(used_mb / total_mb * 100, 1) if total_mb > 0 else 0,
                    "total_str": f"{total_mb / 1024:.1f}GB" if total_mb >= 1024 else f"{total_mb}MB",
                    "used_str": f"{used_mb / 1024:.1f}GB" if used_mb >= 1024 else f"{used_mb}MB",
                }
        except Exception:
            pass

        # CPU 使用率（读两次 /proc/stat，间隔约 0.2s）
        try:
            import time as _time

            def _read_cpu():
                with open("/proc/stat", encoding="utf-8") as f:
                    line = f.readline()
                v = [int(x) for x in line.split()[1:8]]
                return sum(v), v[3]  # total, idle

            t1_total, t1_idle = _read_cpu()
            _time.sleep(0.2)
            t2_total, t2_idle = _read_cpu()
            dt = t2_total - t1_total
            di = t2_idle - t1_idle
            info["cpu_percent"] = round((1 - di / dt) * 100, 1) if dt > 0 else 0.0
        except Exception:
            pass

        # 磁盘使用情况
        disk_output = _run_safe(["df", "-h", "--output=target,size,used,avail,pcent"])
        _SKIP_MOUNTS = ("/proc", "/sys", "/dev", "/run", "/snap", "tmpfs", "udev", "cgroupfs")
        for line in disk_output.split("\n")[1:]:
            parts = line.split()
            if len(parts) < 5:
                continue
            mount = parts[0]
            if any(mount.startswith(p) for p in _SKIP_MOUNTS):
                continue
            try:
                pct = int(parts[4].rstrip("%"))
            except ValueError:
                pct = 0
            info["disk"].append({
                "mount": mount,
                "size": parts[1],
                "used": parts[2],
                "avail": parts[3],
                "percent": pct,
            })
            if len(info["disk"]) >= 5:
                break

        # 网络接口（优先用 ip -brief addr，更快）
        ip_brief = _run_safe(["ip", "-brief", "addr"])
        if ip_brief:
            for line in ip_brief.split("\n"):
                parts = line.split()
                if len(parts) < 3:
                    continue
                iface = parts[0]
                for addr_part in parts[2:]:
                    if "/" in addr_part:
                        ip = addr_part.split("/")[0]
                        if not ip.startswith("127.") and ":" not in ip:  # 跳过 IPv6 和 lo
                            info["network"].append({"iface": iface, "ip": ip})
        else:
            # 兜底：解析 ip addr 长格式
            ip_out = _run_safe(["ip", "addr"])
            matches = _re.findall(r"inet\s+(\d+\.\d+\.\d+\.\d+)/\d+[^\n]*\s+\w+\s+(\w+)$",
                                  ip_out, _re.MULTILINE)
            for ip, iface in matches:
                if not ip.startswith("127."):
                    info["network"].append({"iface": iface, "ip": ip})

        # 进程数
        proc_out = _run_safe(["bash", "-c", "ps -e --no-header | wc -l"])
        if proc_out.strip().isdigit():
            info["process_count"] = int(proc_out.strip())

    elif platform.system() == "Windows":
        info["os_name"] = f"Windows {platform.version()}"
        info["kernel"] = platform.release()

    return info


# ── 主页 HTML ─────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def root():
    return r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>OS Agent · 智能系统管理</title>
<meta name="description" content="基于 LangGraph 的 AI 原生操作系统管理助手，支持自然语言交互进行服务器运维">
<script src="https://cdn.jsdelivr.net/npm/marked@9.1.6/marked.min.js"></script>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/highlight.js@11.9.0/styles/github-dark.min.css">
<script src="https://cdn.jsdelivr.net/npm/highlight.js@11.9.0/highlight.min.js"></script>
<style>
:root {
  --bg-0:#070b14; --bg-1:#0d1117; --bg-2:#161b22; --bg-3:#1c2333; --bg-4:#21262d;
  --border:#30363d; --border-h:#484f58;
  --t1:#e6edf3; --t2:#8b949e; --t3:#6e7681;
  --blue:#58a6ff; --blue-d:#1f6feb;
  --green:#3fb950; --green-d:#238636;
  --red:#f85149; --orange:#ffa657; --purple:#bc8cff;
  --grad: linear-gradient(135deg,#58a6ff 0%,#bc8cff 100%);
  --shadow:0 8px 32px rgba(0,0,0,.5);
}
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','Noto Sans SC',sans-serif;background:var(--bg-0);color:var(--t1);height:100vh;overflow:hidden}

/* Layout */
.layout{display:flex;height:100vh}

/* Sidebar */
.sidebar{width:256px;background:var(--bg-1);border-right:1px solid var(--border);display:flex;flex-direction:column;flex-shrink:0}
.sb-top{padding:14px;border-bottom:1px solid var(--border)}
.app-logo{display:flex;align-items:center;gap:10px;margin-bottom:12px}
.app-logo .icon{width:32px;height:32px;background:var(--grad);border-radius:8px;display:flex;align-items:center;justify-content:center;font-size:16px;flex-shrink:0}
.app-logo .ttl{font-size:14px;font-weight:600}
.app-logo .ver{font-size:11px;color:var(--t3);margin-top:1px}
.new-btn{width:100%;padding:8px 12px;background:var(--bg-3);border:1px solid var(--border);border-radius:6px;color:var(--t2);font-size:13px;cursor:pointer;display:flex;align-items:center;gap:8px;transition:all .15s;font-family:inherit}
.new-btn:hover{background:var(--bg-4);border-color:var(--border-h);color:var(--t1)}
.new-btn .plus{font-size:18px;color:var(--blue);line-height:1}
.sb-search{padding:8px 12px;border-bottom:1px solid var(--border)}
.sb-search input{width:100%;padding:6px 10px;background:var(--bg-3);border:1px solid var(--border);border-radius:6px;color:var(--t2);font-size:12px;outline:none;font-family:inherit;transition:border-color .15s}
.sb-search input:focus{border-color:var(--blue-d);color:var(--t1)}
.sb-search input::placeholder{color:var(--t3)}
.sb-label{padding:8px 14px 4px;font-size:10px;color:var(--t3);text-transform:uppercase;letter-spacing:.6px;font-weight:700}
.ses-list{flex:1;overflow-y:auto;padding:4px 8px 8px}
.ses-item{padding:8px 10px;border-radius:6px;cursor:pointer;margin-bottom:1px;display:flex;align-items:center;gap:8px;transition:background .12s;position:relative}
.ses-item:hover{background:var(--bg-3)}
.ses-item.active{background:var(--bg-3);outline:1px solid var(--border)}
.ses-item .si{font-size:13px;flex-shrink:0;opacity:.7}
.ses-item .sb{flex:1;min-width:0}
.ses-item .st{font-size:13px;color:var(--t1);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;line-height:1.3}
.ses-item .sm{font-size:11px;color:var(--t3);margin-top:2px}
.ses-item .sd{opacity:0;background:none;border:none;color:var(--t3);cursor:pointer;padding:2px 4px;border-radius:4px;font-size:15px;transition:all .15s;flex-shrink:0;line-height:1}
.ses-item:hover .sd{opacity:1}
.ses-item .sd:hover{color:var(--red);background:rgba(248,81,73,.12)}

/* Main */
.main{flex:1;display:flex;flex-direction:column;min-width:0;overflow:hidden}
.mh{padding:11px 20px;border-bottom:1px solid var(--border);display:flex;align-items:center;justify-content:space-between;background:var(--bg-1);flex-shrink:0}
.mh h1{font-size:15px;font-weight:600;background:var(--grad);-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text}
.status-dot{width:6px;height:6px;border-radius:50%;background:var(--green);animation:pulse 2s infinite}
.status-badge{display:flex;align-items:center;gap:6px;font-size:12px;color:var(--t2)}

/* Messages */
.msgs-wrap{flex:1;overflow-y:auto}
.msgs{max-width:880px;margin:0 auto;padding:20px}
.mrow{display:flex;gap:12px;margin-bottom:20px;animation:fadeUp .22s ease}
.mrow.user{flex-direction:row-reverse}
.av{width:30px;height:30px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:12px;font-weight:700;flex-shrink:0;margin-top:3px}
.av.ai{background:var(--grad);color:#fff}
.av.usr{background:var(--bg-4);color:var(--t2);border:1px solid var(--border)}
.mcont{flex:1;min-width:0;max-width:82%}
.mrow.user .mcont{display:flex;flex-direction:column;align-items:flex-end}
.bubble{padding:11px 15px;border-radius:12px;line-height:1.65;font-size:14px;word-break:break-word}
.mrow.user .bubble{background:var(--blue-d);color:#fff;border-radius:12px 4px 12px 12px}
.mrow.ai .bubble{background:var(--bg-2);border:1px solid var(--border);border-radius:4px 12px 12px 12px;color:var(--t1);width:100%}
/* markdown inside bubble */
.bubble h1,.bubble h2,.bubble h3{margin:14px 0 6px;font-weight:600;line-height:1.3}
.bubble h1{font-size:17px;color:var(--blue)}
.bubble h2{font-size:15px;border-bottom:1px solid var(--border);padding-bottom:4px}
.bubble h3{font-size:14px;color:var(--t1)}
.bubble p{margin:5px 0}
.bubble ul,.bubble ol{margin:5px 0 5px 20px}
.bubble li{margin:2px 0;color:var(--t2)}
.bubble li strong{color:var(--t1)}
.bubble code{font-family:'Consolas','Monaco',monospace;font-size:12px;background:var(--bg-0);border:1px solid var(--border);border-radius:4px;padding:1px 5px;color:var(--orange)}
.bubble pre{background:var(--bg-0)!important;border:1px solid var(--border);border-radius:8px;padding:14px;margin:10px 0;overflow-x:auto}
.bubble pre code{background:none!important;border:none!important;padding:0!important;color:inherit!important;font-size:12px}
.bubble table{width:100%;border-collapse:collapse;margin:10px 0;font-size:13px}
.bubble th{background:var(--bg-3);padding:8px 11px;text-align:left;border:1px solid var(--border);font-weight:600;color:var(--blue)}
.bubble td{padding:6px 11px;border:1px solid var(--border);color:var(--t2)}
.bubble tr:hover td{background:var(--bg-3)}
.bubble blockquote{border-left:3px solid var(--blue-d);padding:6px 12px;margin:8px 0;color:var(--t2);background:var(--bg-3);border-radius:0 6px 6px 0}
.bubble a{color:var(--blue);text-decoration:none}
.bubble a:hover{text-decoration:underline}
.bubble strong{color:var(--t1)}
.bubble em{color:var(--t2)}
.bubble hr{border:none;border-top:1px solid var(--border);margin:10px 0}
.mtime{font-size:10px;color:var(--t3);margin-top:3px;padding:0 2px}
.mrow.user .mtime{text-align:right}

/* Risk card */
.risk-card{background:linear-gradient(135deg,#1a0a0a,#2d1111);border:1px solid #6e3333;border-radius:10px;padding:15px;margin-bottom:8px}
.risk-hd{display:flex;align-items:center;gap:10px;margin-bottom:10px}
.rbadge{background:var(--orange);color:#000;padding:2px 10px;border-radius:12px;font-size:11px;font-weight:800}
.risk-cmd{font-family:monospace;font-size:13px;color:var(--orange);background:var(--bg-0);padding:8px 12px;border-radius:6px;margin:8px 0;word-break:break-all}
.risk-desc{font-size:13px;color:#fca5a5;line-height:1.5}
.confirm-row{display:flex;gap:8px;margin-top:12px}
.confirm-row button{padding:7px 18px;border:none;border-radius:6px;font-size:13px;font-weight:600;cursor:pointer;transition:all .15s;font-family:inherit}
.btn-ok{background:var(--green-d);color:#fff}
.btn-ok:hover{background:var(--green)}
.btn-no{background:var(--bg-4);color:var(--t2);border:1px solid var(--border)}
.btn-no:hover{border-color:var(--red);color:var(--red)}
.confirm-row button:disabled{opacity:.4;cursor:not-allowed}

/* Task sequence */
.tseq{background:var(--bg-3);border:1px solid var(--border);border-radius:8px;padding:11px 13px;margin-bottom:10px}
.tseq-ttl{font-size:11px;color:var(--t3);font-weight:700;margin-bottom:9px;text-transform:uppercase;letter-spacing:.5px}
.tstep{display:flex;align-items:center;gap:9px;padding:4px 0;font-size:13px}
.ticon{width:20px;height:20px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:10px;font-weight:700;flex-shrink:0}
.ticon.done{background:var(--green);color:#fff}
.ticon.run{background:var(--blue-d);color:#fff}
.ticon.wait{background:var(--bg-4);color:var(--t3);border:1px solid var(--border)}
.tlbl{color:var(--t2)}
.tlbl.done{color:var(--green)}
.tlbl.run{color:var(--blue);font-weight:600}

/* Thinking */
.thinking{display:flex;gap:4px;align-items:center;padding:6px 0}
.thinking span{width:6px;height:6px;border-radius:50%;background:var(--blue);animation:bounce 1.4s infinite}
.thinking span:nth-child(2){animation-delay:.2s}
.thinking span:nth-child(3){animation-delay:.4s}

/* Status banner */
.status-banner{display:flex;align-items:center;gap:8px;font-size:12px;padding:4px 12px;border-radius:6px;margin-bottom:8px}
.status-banner.ok{background:rgba(63,185,80,.1);color:var(--green);border:1px solid rgba(63,185,80,.3)}
.status-banner.cancel{background:rgba(248,81,73,.1);color:var(--red);border:1px solid rgba(248,81,73,.3)}

/* Input */
.input-area{border-top:1px solid var(--border);background:var(--bg-1);padding:14px 20px;flex-shrink:0}
.inp-inner{max-width:880px;margin:0 auto}
.inp-row{display:flex;gap:8px;align-items:flex-end}
.inp-row textarea{flex:1;padding:10px 13px;background:var(--bg-2);border:1px solid var(--border);border-radius:8px;color:var(--t1);font-size:14px;outline:none;resize:none;line-height:1.5;min-height:42px;max-height:150px;overflow-y:auto;font-family:inherit;transition:border-color .15s}
.inp-row textarea:focus{border-color:var(--blue-d)}
.inp-row textarea::placeholder{color:var(--t3)}
.send-btn{padding:10px 18px;background:var(--blue-d);color:#fff;border:none;border-radius:8px;font-size:14px;font-weight:600;cursor:pointer;transition:background .15s;height:42px;white-space:nowrap;font-family:inherit}
.send-btn:hover{background:var(--blue)}
.send-btn:disabled{opacity:.4;cursor:not-allowed}
.qbtns{display:flex;flex-wrap:wrap;gap:5px;margin-top:9px}
.qb{background:var(--bg-3);border:1px solid var(--border);color:var(--t3);padding:3px 11px;border-radius:20px;font-size:12px;cursor:pointer;transition:all .15s;font-family:inherit}
.qb:hover{border-color:var(--blue-d);color:var(--blue)}

/* Env panel */
.epanel{width:272px;background:var(--bg-1);border-left:1px solid var(--border);display:flex;flex-direction:column;flex-shrink:0;overflow-y:auto}
.ep-hd{padding:13px 14px;border-bottom:1px solid var(--border);display:flex;align-items:center;justify-content:space-between;flex-shrink:0}
.ep-hd h3{font-size:12px;font-weight:700;color:var(--t2);text-transform:uppercase;letter-spacing:.6px}
.ep-refresh{background:none;border:none;color:var(--t3);cursor:pointer;font-size:14px;padding:3px 6px;border-radius:4px;transition:all .15s}
.ep-refresh:hover{color:var(--blue);background:var(--bg-3)}
.ep-body{padding:10px;display:flex;flex-direction:column;gap:7px}

/* env cards */
.ecard{background:var(--bg-2);border:1px solid var(--border);border-radius:8px;padding:11px}
.ec-ttl{font-size:10px;color:var(--t3);font-weight:700;text-transform:uppercase;letter-spacing:.5px;margin-bottom:8px}
.ec-os-name{font-size:14px;font-weight:600;color:var(--t1);margin-bottom:6px}
.drow{display:flex;justify-content:space-between;align-items:center;padding:2px 0}
.dlbl{font-size:11px;color:var(--t3)}
.dval{font-size:11px;color:var(--t2);font-family:monospace;max-width:148px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}

/* resource bars */
.res-item{margin-bottom:9px}
.res-item:last-child{margin-bottom:0}
.res-row{display:flex;justify-content:space-between;margin-bottom:3px}
.res-name{font-size:12px;color:var(--t2)}
.res-pct{font-size:12px;font-weight:700}
.res-bar{height:4px;background:var(--bg-0);border-radius:2px;overflow:hidden}
.res-fill{height:100%;border-radius:2px;transition:width .6s ease}
.rf-cpu{background:linear-gradient(90deg,#58a6ff,#bc8cff)}
.rf-mem{background:linear-gradient(90deg,#3fb950,#2ea043)}
.rf-dsk{background:linear-gradient(90deg,#ffa657,#f85149)}
.res-sub{font-size:10px;color:var(--t3);margin-top:2px}

/* disk list */
.disk-item{margin-bottom:7px}
.disk-item:last-child{margin-bottom:0}
.disk-row{display:flex;justify-content:space-between;margin-bottom:3px}
.disk-mnt{font-size:12px;color:var(--t2);font-family:monospace}
.disk-pct{font-size:12px;font-weight:700}

/* network */
.net-item{display:flex;justify-content:space-between;padding:3px 0;border-bottom:1px solid var(--border)}
.net-item:last-child{border-bottom:none}
.net-iface{font-size:11px;color:var(--t3);font-family:monospace}
.net-ip{font-size:12px;color:var(--t1);font-family:monospace}

/* stats grid */
.eg-grid{display:grid;grid-template-columns:1fr 1fr;gap:6px}
.eg-cell{background:var(--bg-2);border:1px solid var(--border);border-radius:8px;padding:9px;text-align:center}
.eg-val{font-size:20px;font-weight:700;color:var(--blue)}
.eg-lbl{font-size:10px;color:var(--t3);margin-top:2px;text-transform:uppercase;letter-spacing:.4px}

.ep-loading{display:flex;align-items:center;justify-content:center;padding:28px;color:var(--t3);font-size:12px;flex-direction:column;gap:8px}

/* scrollbars */
::-webkit-scrollbar{width:5px;height:5px}
::-webkit-scrollbar-track{background:transparent}
::-webkit-scrollbar-thumb{background:var(--border);border-radius:3px}
::-webkit-scrollbar-thumb:hover{background:var(--border-h)}

/* animations */
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.3}}
@keyframes bounce{0%,80%,100%{transform:translateY(0)}40%{transform:translateY(-5px)}}
@keyframes fadeUp{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:translateY(0)}}

/* responsive */
@media(max-width:1180px){.epanel{display:none}}
@media(max-width:860px){.sidebar{display:none}}
</style>
</head>
<body>
<div class="layout">

<!-- ── Sidebar ── -->
<aside class="sidebar">
  <div class="sb-top">
    <div class="app-logo">
      <div class="icon">⚡</div>
      <div>
        <div class="ttl">OS Agent</div>
        <div class="ver">v2.0 · LangGraph</div>
      </div>
    </div>
    <button class="new-btn" id="newChatBtn" onclick="newSession()">
      <span class="plus">+</span> 新建对话
    </button>
  </div>
  <div class="sb-search">
    <input type="text" id="sesSearch" placeholder="搜索对话..." oninput="filterSessions(this.value)">
  </div>
  <div class="sb-label">最近对话</div>
  <div class="ses-list" id="sesList"></div>
</aside>

<!-- ── Main ── -->
<main class="main">
  <div class="mh">
    <h1 id="mainTitle">操作系统智能助手</h1>
    <div class="status-badge">
      <span class="status-dot"></span>
      <span>在线</span>
    </div>
  </div>

  <div class="msgs-wrap" id="msgsWrap">
    <div class="msgs" id="msgs">
      <div class="mrow ai" id="welcomeMsg">
        <div class="av ai">AI</div>
        <div class="mcont">
          <div class="bubble">
            👋 欢迎使用 <strong>OS Agent</strong> — 基于 LangGraph 的 AI 原生系统管理助手。<br><br>
            我可以帮你完成：
            <ul style="margin:8px 0 0 18px">
              <li>系统监控（磁盘、内存、CPU、进程、端口）</li>
              <li>多步任务自动编排与依赖调度</li>
              <li>用户管理、服务管理与故障诊断</li>
              <li>高风险操作自动拦截与人工确认</li>
            </ul>
          </div>
          <div class="mtime">系统消息</div>
        </div>
      </div>
    </div>
  </div>

  <div class="input-area">
    <div class="inp-inner">
      <div class="inp-row">
        <textarea id="inp" placeholder="输入自然语言指令，例如：检查磁盘使用情况" rows="1"
          oninput="autoResize(this)" onkeydown="handleKey(event)"></textarea>
        <button class="send-btn" id="sendBtn" onclick="sendMsg()">发送</button>
      </div>
      <div class="qbtns">
        <button class="qb" onclick="qi('查询磁盘使用情况')">磁盘使用</button>
        <button class="qb" onclick="qi('查看内存使用情况')">内存状态</button>
        <button class="qb" onclick="qi('查看当前运行的进程')">进程列表</button>
        <button class="qb" onclick="qi('查看开放的网络端口')">端口监听</button>
        <button class="qb" onclick="qi('查看系统和内核信息')">系统信息</button>
        <button class="qb" onclick="qi('先查看磁盘，再查看进程，最后看端口')">多步任务</button>
        <button class="qb" onclick="qi('排查80端口无法访问的原因')">故障诊断</button>
        <button class="qb" onclick="qi('创建用户 dev1 并配置 sudo 权限')">用户部署</button>
      </div>
    </div>
  </div>
</main>

<!-- ── Env Panel ── -->
<aside class="epanel" id="epanel">
  <div class="ep-hd">
    <h3>系统状态</h3>
    <button class="ep-refresh" onclick="loadEnv()" title="刷新">↻</button>
  </div>
  <div class="ep-body" id="epBody">
    <div class="ep-loading">
      <div class="thinking"><span></span><span></span><span></span></div>
      <div>采集中...</div>
    </div>
  </div>
</aside>

</div><!-- .layout -->

<script>
(function(){
'use strict';

// ── 初始化 marked.js ───────────────────────────────────────────────────────
if(typeof marked!=='undefined'){
  // 自定义代码高亮 renderer
  var renderer=new marked.Renderer();
  renderer.code=function(code,lang){
    var validLang=lang&&typeof hljs!=='undefined'&&hljs.getLanguage(lang)?lang:null;
    var highlighted=validLang
      ?hljs.highlight(code,{language:validLang}).value
      :(typeof hljs!=='undefined'?hljs.highlightAuto(code).value:escHtml(code));
    return '<pre><code class="hljs'+(lang?' language-'+lang:'')+'">'+highlighted+'</code></pre>';
  };
  marked.use({renderer:renderer,breaks:true,gfm:true});
}

// ── 状态 ──────────────────────────────────────────────────────────────────
var sesId=localStorage.getItem('osa_sid')||genId();
var allSes=[];
var filterQ='';
var pendingState=null;
var pendingInput='';
var busy=false;

localStorage.setItem('osa_sid',sesId);

// ── 工具函数 ──────────────────────────────────────────────────────────────
function genId(){return 'ses_'+Date.now()+'_'+Math.random().toString(36).slice(2,6)}

function escHtml(s){
  var d=document.createElement('div');
  d.textContent=s;
  return d.innerHTML;
}

function stripThink(text){
  if(!text)return '';
  // 移除闭合 think/thinking 标签
  text=text.replace(/<think>[\s\S]*?<\/think>\s*/gi,'');
  text=text.replace(/<thinking>[\s\S]*?<\/thinking>\s*/gi,'');
  // 移除未闭合标签及其后所有内容
  var i=text.indexOf('<think>');
  if(i!==-1)text=text.substring(0,i);
  i=text.indexOf('<thinking>');
  if(i!==-1)text=text.substring(0,i);
  return text.trim();
}

function renderMd(text){
  text=stripThink(text);
  if(!text)return '';
  if(typeof marked!=='undefined'){
    try{return marked.parse(text)}catch(e){}
  }
  return escHtml(text).replace(/\n/g,'<br>');
}

function fmtTime(ts){
  var d=ts?new Date(ts*1000):new Date();
  return String(d.getHours()).padStart(2,'0')+':'+String(d.getMinutes()).padStart(2,'0');
}

function fmtRel(ts){
  if(!ts)return '';
  var s=Date.now()/1000-ts;
  if(s<60)return '刚刚';
  if(s<3600)return Math.floor(s/60)+' 分钟前';
  if(s<86400)return Math.floor(s/3600)+' 小时前';
  return Math.floor(s/86400)+' 天前';
}

// ── 会话本地存储 ──────────────────────────────────────────────────────────
function saveSes(id,data){
  try{
    var k='osa_'+id;
    var ex=getSes(id)||{};
    localStorage.setItem(k,JSON.stringify(Object.assign({},ex,data)));
  }catch(e){}
}
function getSes(id){
  try{var r=localStorage.getItem('osa_'+id);return r?JSON.parse(r):null}catch(e){return null}
}
function delSesLocal(id){try{localStorage.removeItem('osa_'+id)}catch(e){}}
function getSesTitle(id){var s=getSes(id);return(s&&s.title)?s.title:'新对话'}

// ── 加载会话列表 ──────────────────────────────────────────────────────────
async function loadSessions(){
  try{
    var r=await fetch('/api/sessions');
    var d=await r.json();
    var svr=(d.sessions||[]).map(function(s){return{id:s.session_id,ts:s.last_activity||0}});
    var map={};svr.forEach(function(s){map[s.id]=s});

    // 合并本地
    Object.keys(localStorage).filter(function(k){return k.startsWith('osa_ses_')||k.startsWith('osa_')&&k!=='osa_sid'}).forEach(function(k){
      var id=k.replace(/^osa_/,'');
      if(id&&!map[id]){var s=getSes(id);if(s)map[id]={id:id,ts:s.lastAt||0}}
    });

    allSes=Object.values(map).sort(function(a,b){return b.ts-a.ts});
    if(!allSes.find(function(s){return s.id===sesId})){
      allSes.unshift({id:sesId,ts:Date.now()/1000});
    }
  }catch(e){
    if(!allSes.length)allSes=[{id:sesId,ts:Date.now()/1000}];
  }
  renderSessions();
}

function renderSessions(){
  var list=document.getElementById('sesList');
  list.innerHTML='';
  var items=filterQ?allSes.filter(function(s){return getSesTitle(s.id).toLowerCase().includes(filterQ.toLowerCase())}):allSes;
  items.forEach(function(s){
    var title=getSesTitle(s.id);
    var active=s.id===sesId;
    var el=document.createElement('div');
    el.className='ses-item'+(active?' active':'');
    el.innerHTML='<span class="si">💬</span>'
      +'<div class="sb">'
        +'<div class="st">'+escHtml(title)+'</div>'
        +'<div class="sm">'+fmtRel(s.ts)+'</div>'
      +'</div>'
      +'<button class="sd" title="删除">×</button>';
    el.querySelector('.sb').onclick=function(){switchSes(s.id)};
    el.querySelector('.sd').onclick=function(e){e.stopPropagation();deleteSes(s.id)};
    list.appendChild(el);
  });
  // 更新标题
  var t=getSesTitle(sesId);
  document.getElementById('mainTitle').textContent=t==='新对话'?'操作系统智能助手':t;
}

window.filterSessions=function(q){filterQ=q;renderSessions()};

window.newSession=function(){
  sesId=genId();
  localStorage.setItem('osa_sid',sesId);
  saveSes(sesId,{title:'新对话',lastAt:Date.now()/1000});
  allSes.unshift({id:sesId,ts:Date.now()/1000});
  clearMsgs();
  addWelcome();
  renderSessions();
  document.getElementById('inp').focus();
};

function switchSes(id){
  if(id===sesId)return;
  sesId=id;
  localStorage.setItem('osa_sid',id);
  clearMsgs();
  renderSessions();
  loadHistory(id);
}

async function loadHistory(id){
  try{
    var r=await fetch('/api/session/'+id+'/history');
    var d=await r.json();
    (d.conversation_history||[]).forEach(function(m){
      if(m.role==='user')addUserBubble(m.content||'');
      else if(m.role==='assistant')addAiBubble(m.content||'');
    });
  }catch(e){addSysMsg('历史记录加载失败')}
}

async function deleteSes(id){
  try{await fetch('/api/session/'+id,{method:'DELETE'})}catch(e){}
  delSesLocal(id);
  allSes=allSes.filter(function(s){return s.id!==id});
  if(id===sesId){
    sesId=allSes.length?allSes[0].id:genId();
    if(!allSes.length)allSes=[{id:sesId,ts:Date.now()/1000}];
    localStorage.setItem('osa_sid',sesId);
    clearMsgs();addWelcome();
  }
  renderSessions();
}

// ── 消息渲染 ──────────────────────────────────────────────────────────────
function clearMsgs(){document.getElementById('msgs').innerHTML='';pendingState=null}

function addWelcome(){
  var msgs=document.getElementById('msgs');
  var d=document.createElement('div');
  d.className='mrow ai';
  d.innerHTML='<div class="av ai">AI</div>'
    +'<div class="mcont">'
      +'<div class="bubble">👋 新对话已就绪，请输入您的指令。<br>'
        +'<span style="color:var(--t3);font-size:13px">提示：复杂任务会被自动分解为多个步骤依次执行。</span>'
      +'</div>'
      +'<div class="mtime">'+fmtTime()+'</div>'
    +'</div>';
  msgs.appendChild(d);scrollM();
}

function addUserBubble(text){
  var msgs=document.getElementById('msgs');
  var d=document.createElement('div');
  d.className='mrow user';
  d.innerHTML='<div class="av usr">你</div>'
    +'<div class="mcont">'
      +'<div class="bubble">'+escHtml(text)+'</div>'
      +'<div class="mtime">'+fmtTime()+'</div>'
    +'</div>';
  msgs.appendChild(d);scrollM();
}

function addAiBubble(text,extraHtml){
  var msgs=document.getElementById('msgs');
  var d=document.createElement('div');
  d.className='mrow ai';
  var rendered=renderMd(text);
  d.innerHTML='<div class="av ai">AI</div>'
    +'<div class="mcont">'
      +(extraHtml||'')
      +'<div class="bubble">'+(rendered||'<em style="color:var(--t3)">（无内容）</em>')+'</div>'
      +'<div class="mtime">'+fmtTime()+'</div>'
    +'</div>';
  msgs.appendChild(d);
  // 代码高亮
  if(typeof hljs!=='undefined')d.querySelectorAll('pre code').forEach(function(el){hljs.highlightElement(el)});
  scrollM();
  return d;
}

function addSysMsg(text){
  var msgs=document.getElementById('msgs');
  var d=document.createElement('div');
  d.style.cssText='text-align:center;padding:8px;font-size:12px;color:var(--t3)';
  d.textContent=text;
  msgs.appendChild(d);scrollM();
}

function addThinking(){
  var msgs=document.getElementById('msgs');
  var d=document.createElement('div');
  d.id='think_ind';d.className='mrow ai';
  d.innerHTML='<div class="av ai">AI</div>'
    +'<div class="mcont"><div class="bubble">'
      +'<div class="thinking"><span></span><span></span><span></span></div>'
    +'</div></div>';
  msgs.appendChild(d);scrollM();
}

function rmThinking(){var el=document.getElementById('think_ind');if(el)el.remove()}

function buildTaskSeqHtml(tasks){
  var html='<div class="tseq"><div class="tseq-ttl">任务序列 · '+tasks.length+' 个步骤</div>';
  tasks.forEach(function(t,i){
    var lbl=escHtml((t&&t.description)?t.description:(t?t.intent:'步骤'+(i+1)));
    var ic=i===0?'run':'wait'; var lc=i===0?'run':'';
    var sym=i===0?'⟳':(i+1);
    html+='<div class="tstep"><div class="ticon '+ic+'">'+sym+'</div><span class="tlbl '+lc+'">'+lbl+'</span></div>';
  });
  return html+'</div>';
}

var _riskCardId=0;
function buildRiskHtml(d){
  _riskCardId++;
  var ra=d.risk_assessment||{};
  var impacts=(ra.command_impact||[]).join('、')||'影响系统配置';
  return '<div class="risk-card" data-rid="'+_riskCardId+'">'
    +'<div class="risk-hd"><span class="rbadge">⚠ 中等风险</span>'
    +'<span style="font-size:13px;color:#fca5a5">确认后才能执行</span></div>'
    +'<div class="risk-cmd">'+escHtml(d.command||'')+'</div>'
    +'<div class="risk-desc"><strong>风险说明：</strong>'+escHtml(ra.risk_explanation||'该操作存在一定风险')+'<br>'
    +'<strong>操作影响：</strong>'+escHtml(impacts)+'</div>'
    +'<div class="confirm-row">'
      +'<button class="btn-ok" onclick="doConfirm(true)">✓ 确认执行</button>'
      +'<button class="btn-no" onclick="doConfirm(false)">✕ 取消操作</button>'
    +'</div></div>';
}

function scrollM(){var w=document.getElementById('msgsWrap');w.scrollTop=w.scrollHeight}

// ── 输入区 ────────────────────────────────────────────────────────────────
window.autoResize=function(el){el.style.height='auto';el.style.height=Math.min(el.scrollHeight,150)+'px'};
window.handleKey=function(e){if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();sendMsg()}};
window.qi=function(t){var i=document.getElementById('inp');i.value=t;i.focus();autoResize(i)};

// ── 发送消息 ──────────────────────────────────────────────────────────────
async function sendMsg(){
  var inp=document.getElementById('inp');
  var txt=inp.value.trim();
  if(!txt||busy)return;

  busy=true;
  inp.value='';inp.style.height='auto';
  document.getElementById('sendBtn').disabled=true;
  pendingInput=txt;

  // 首条消息作为会话标题
  var sd=getSes(sesId);
  if(!sd||!sd.title||sd.title==='新对话'){
    var newT=txt.length>28?txt.slice(0,28)+'…':txt;
    saveSes(sesId,{title:newT,lastAt:Date.now()/1000});
    allSes=allSes.filter(function(s){return s.id!==sesId});
    allSes.unshift({id:sesId,ts:Date.now()/1000});
  }else{
    saveSes(sesId,{lastAt:Date.now()/1000});
    allSes=allSes.filter(function(s){return s.id!==sesId});
    allSes.unshift({id:sesId,ts:Date.now()/1000});
  }
  renderSessions();

  addUserBubble(txt);
  addThinking();

  try{
    var r=await ftTimeout('/api/query',{
      method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({input:txt,session_id:sesId})
    },120000);
    var d=await r.json();
    rmThinking();
    if(d.session_id)sesId=d.session_id;

    if(d.requires_confirmation){
      pendingState=d;
      var extra=(d.task_sequence&&d.task_sequence.length>1)?buildTaskSeqHtml(d.task_sequence):'';
      extra+=buildRiskHtml(d);
      var msgs=document.getElementById('msgs');
      var el=document.createElement('div');
      el.className='mrow ai';
      el.innerHTML='<div class="av ai">AI</div>'
        +'<div class="mcont">'+extra+'<div class="mtime">'+fmtTime()+'</div></div>';
      msgs.appendChild(el);scrollM();
    }else{
      var extra2=(d.task_sequence&&d.task_sequence.length>1)?buildTaskSeqHtml(d.task_sequence):'';
      addAiBubble(d.response||d.execution_result||'',extra2);
    }
  }catch(e){
    rmThinking();
    addAiBubble('❌ 请求失败：'+e.message);
  }

  busy=false;
  document.getElementById('sendBtn').disabled=false;
  inp.focus();
}
window.sendMsg=sendMsg;

// ── 风险确认 ──────────────────────────────────────────────────────────────
var confirmLocked=false;
window.doConfirm=async function(ok){
  // 三重保护：全局锁 + pendingState 清空 + DOM 禁用
  if(confirmLocked||!pendingState)return;
  confirmLocked=true;
  pendingState=null;
  // 禁用所有风险确认按钮（包括历史卡片中的）
  document.querySelectorAll('.btn-ok,.btn-no').forEach(function(b){
    b.disabled=true;b.style.opacity='0.3';b.style.cursor='not-allowed';b.onclick=null;
  });

  addThinking();
  try{
    var r=await ftTimeout('/api/confirm',{
      method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({session_id:sesId,confirmed:ok,user_input:pendingInput})
    },120000);
    var d=await r.json();
    rmThinking();
    var banner=ok
      ?'<div class="status-banner ok">✓ 已确认执行</div>'
      :'<div class="status-banner cancel">✕ 操作已取消</div>';
    addAiBubble(d.response||d.execution_result||(ok?'命令已执行':'已取消'),banner);
    if(d.session_id)sesId=d.session_id;
  }catch(e){
    rmThinking();
    addAiBubble('❌ 处理确认时出错：'+e.message);
  }
  // 请求完成后解锁，允许后续新的风险卡片被确认
  confirmLocked=false;
};

function ftTimeout(url,opts,ms){
  return Promise.race([
    fetch(url,opts),
    new Promise(function(_,rej){
      setTimeout(function(){rej(new Error('请求超时（'+Math.round(ms/1000)+'s）'))},ms)
    })
  ]);
}

// ── 环境信息面板 ──────────────────────────────────────────────────────────
async function loadEnv(){
  var body=document.getElementById('epBody');
  body.innerHTML='<div class="ep-loading"><div class="thinking"><span></span><span></span><span></span></div><div>采集中...</div></div>';
  try{
    var r=await fetch('/api/env/realtime');
    var d=await r.json();
    renderEnv(d);
  }catch(e){
    body.innerHTML='<div class="ep-loading" style="color:var(--red)">采集失败</div>';
  }
}
window.loadEnv=loadEnv;

function pct2Color(pct,red,orange){
  red=red||85;orange=orange||70;
  if(pct>=red)return 'var(--red)';
  if(pct>=orange)return 'var(--orange)';
  return 'var(--green)';
}

function renderEnv(d){
  var body=document.getElementById('epBody');
  var html='';

  // OS + 基础信息
  html+='<div class="ecard">';
  html+='<div class="ec-os-name">'+escHtml(d.os_name||d.platform||'未知系统')+'</div>';
  if(d.kernel)html+='<div class="drow"><span class="dlbl">内核</span><span class="dval">'+escHtml(d.kernel)+'</span></div>';
  if(d.hostname)html+='<div class="drow"><span class="dlbl">主机名</span><span class="dval">'+escHtml(d.hostname)+'</span></div>';
  if(d.architecture)html+='<div class="drow"><span class="dlbl">架构</span><span class="dval">'+escHtml(d.architecture)+'</span></div>';
  if(d.uptime)html+='<div class="drow"><span class="dlbl">运行时间</span><span class="dval">'+escHtml(d.uptime)+'</span></div>';
  html+='</div>';

  // CPU + 内存
  if(d.cpu_percent!==null||d.memory){
    html+='<div class="ecard"><div class="ec-ttl">资源使用</div>';
    if(d.cpu_percent!==null&&d.cpu_percent!==undefined){
      var cc=pct2Color(d.cpu_percent);
      html+='<div class="res-item">'
        +'<div class="res-row"><span class="res-name">CPU</span><span class="res-pct" style="color:'+cc+'">'+d.cpu_percent+'%</span></div>'
        +'<div class="res-bar"><div class="res-fill rf-cpu" style="width:'+Math.min(d.cpu_percent,100)+'%"></div></div>';
      if(d.load_avg)html+='<div class="res-sub">负载: '+escHtml(d.load_avg)+'</div>';
      html+='</div>';
    }
    if(d.memory&&d.memory.percent!==undefined){
      var mem=d.memory;var mc=pct2Color(mem.percent,85,70);
      html+='<div class="res-item">'
        +'<div class="res-row"><span class="res-name">内存</span><span class="res-pct" style="color:'+mc+'">'+mem.percent+'%</span></div>'
        +'<div class="res-bar"><div class="res-fill rf-mem" style="width:'+Math.min(mem.percent,100)+'%"></div></div>'
        +'<div class="res-sub">'+escHtml(mem.used_str||'')+'&nbsp;/&nbsp;'+escHtml(mem.total_str||'')+'</div>'
        +'</div>';
    }
    html+='</div>';
  }

  // 磁盘
  if(d.disk&&d.disk.length){
    html+='<div class="ecard"><div class="ec-ttl">磁盘</div>';
    d.disk.forEach(function(dk){
      var dc=pct2Color(dk.percent,90,75);
      html+='<div class="disk-item">'
        +'<div class="disk-row"><span class="disk-mnt">'+escHtml(dk.mount)+'</span><span class="disk-pct" style="color:'+dc+'">'+dk.percent+'%</span></div>'
        +'<div class="res-bar"><div class="res-fill rf-dsk" style="width:'+Math.min(dk.percent,100)+'%"></div></div>'
        +'<div class="res-sub">'+escHtml(dk.used)+' / '+escHtml(dk.size)+' · 剩余 '+escHtml(dk.avail)+'</div>'
        +'</div>';
    });
    html+='</div>';
  }

  // 网络
  if(d.network&&d.network.length){
    html+='<div class="ecard"><div class="ec-ttl">网络接口</div>';
    d.network.forEach(function(n){
      html+='<div class="net-item"><span class="net-iface">'+escHtml(n.iface)+'</span><span class="net-ip">'+escHtml(n.ip)+'</span></div>';
    });
    html+='</div>';
  }

  // 统计
  html+='<div class="eg-grid">';
  if(d.process_count)html+='<div class="eg-cell"><div class="eg-val">'+d.process_count+'</div><div class="eg-lbl">进程</div></div>';
  html+='<div class="eg-cell"><div class="eg-val" id="sesCount">'+allSes.length+'</div><div class="eg-lbl">会话</div></div>';
  html+='</div>';

  body.innerHTML=html;
}

// ── 启动 ──────────────────────────────────────────────────────────────────
(async function init(){
  var saved=getSes(sesId);
  if(!saved)saveSes(sesId,{title:'新对话',lastAt:Date.now()/1000});
  await loadSessions();
  loadEnv();
  setInterval(loadEnv,300000);  // 每5分钟自动刷新
  document.getElementById('inp').focus();
})();

})();
</script>
</body>
</html>"""


# ── API 端点 ──────────────────────────────────────────────────────────────────

@app.get("/api/health")
async def health_check():
    return {
        "status": "healthy",
        "timestamp": time.time(),
        "active_sessions": len(audit_logger.get_all_sessions(limit=1000))
    }


@app.post("/api/query", response_model=AgentResponse)
async def query(request: UserRequest):
    try:
        session_id = request.session_id or f"session_{int(time.time())}"

        saved = _load_session(session_id)
        history = saved.get("conversation_history", [])
        env = saved.get("environment", {})

        initial_state = {
            "session_id": session_id,
            "user_input": request.input,
            "conversation_history": history,
            "environment": env,
        }

        result = workflow.invoke(initial_state)

        # 保存 user_input 以便 /api/confirm 恢复状态时使用
        result["user_input"] = request.input

        if result.get("risk_assessment", {}).get("requires_confirmation"):
            _save_session(session_id, result)
            return AgentResponse(
                response="",
                execution_result="",
                risk_level=result.get("risk_level"),
                requires_confirmation=True,
                risk_assessment=result.get("risk_assessment"),
                session_id=session_id,
                command=result.get("command"),
                task_sequence=result.get("task_sequence"),
                current_task_index=result.get("current_task_index"),
                task_status=result.get("task_status"),
                environment=result.get("environment"),
                branch_results=result.get("branch_results"),
                execution_log=result.get("execution_log"),
                explanation="",
            )

        _save_session(session_id, result)
        return AgentResponse(
            response=result.get("response", ""),
            execution_result=result.get("execution_result", ""),
            session_id=session_id,
            task_sequence=result.get("task_sequence"),
            environment=result.get("environment"),
            branch_results=result.get("branch_results"),
            execution_log=result.get("execution_log"),
            explanation="",
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/confirm", response_model=AgentResponse)
async def confirm_risk(request: ConfirmRequest):
    """
    风险确认接口。
    安全策略：完全从服务端 session 恢复状态，不信任客户端传回的业务状态字段。
    """
    try:
        # 完全从服务端恢复状态
        saved = _load_session(request.session_id)
        if not saved:
            raise HTTPException(status_code=404, detail="Session not found")

        history = saved.get("conversation_history", [])
        task_sequence = saved.get("task_sequence", [])

        state = {
            "session_id": request.session_id,
            "user_input": saved.get("user_input", request.user_input or ""),
            "user_confirmation": request.confirmed,
            "conversation_history": history,
            "command": saved.get("command", ""),
            "task_sequence": task_sequence,
            "current_task_index": saved.get("current_task_index", 0),
            "task_status": saved.get("task_status", "in_progress"),
            "environment": saved.get("environment", {}),
            "risk_assessment": {
                **saved.get("risk_assessment", {}),
                "requires_confirmation": False,  # 重置标志，允许继续执行
            },
            "risk_level": saved.get("risk_level", "medium"),
            "risk_explanation": saved.get("risk_explanation", ""),
            "task_execution_order": saved.get("task_execution_order", []),
            "execution_log": saved.get("execution_log", []),
            "rollback_stack": saved.get("rollback_stack", []),
            "branch_results": saved.get("branch_results", {}),
            "intent": saved.get("intent", task_sequence[0].get("intent", "other") if task_sequence else "other"),
            "parameters": saved.get("parameters", task_sequence[0].get("parameters", {}) if task_sequence else {}),
            "last_intent": saved.get("last_intent", ""),
            "consistency_issues": saved.get("consistency_issues", []),
        }

        result = workflow.invoke(state)
        _save_session(request.session_id, result)

        return AgentResponse(
            response=result.get("response", ""),
            execution_result=result.get("execution_result", ""),
            session_id=request.session_id,
            task_sequence=result.get("task_sequence"),
            environment=result.get("environment"),
            branch_results=result.get("branch_results"),
            execution_log=result.get("execution_log"),
            explanation="",
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/sessions")
async def list_sessions():
    return {"sessions": audit_logger.get_all_sessions(limit=100)}


@app.delete("/api/session/{session_id}")
async def delete_session(session_id: str):
    from src.agent_workflow import SESSION_DIR
    path = os.path.join(SESSION_DIR, f"{session_id}.json")
    if os.path.exists(path):
        os.remove(path)
    return {"success": True}


@app.get("/api/session/{session_id}/history")
async def get_session_history(session_id: str):
    saved = _load_session(session_id)
    return {
        "conversation_history": saved.get("conversation_history", []),
        "environment": saved.get("environment", {}),
    }


@app.get("/api/audit/security")
async def security_events(session_id: Optional[str] = None):
    return {"events": audit_logger.get_security_events(session_id)}


@app.get("/api/audit/session/{session_id}")
async def session_audit(session_id: str):
    return {"history": audit_logger.get_session_history(session_id)}


# ── WebSocket 支持（保留原有功能）────────────────────────────────────────────

active_connections: Dict[str, WebSocket] = {}


@app.websocket("/ws/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str):
    await websocket.accept()
    active_connections[session_id] = websocket
    try:
        while True:
            data = await websocket.receive_text()
            try:
                request = json.loads(data)
                if request.get("type") == "execute":
                    user_input = request.get("input", "")
                    saved = _load_session(session_id)
                    ws_history = saved.get("conversation_history", [])
                    ws_env = saved.get("environment", {})
                    initial_state = {
                        "session_id": session_id,
                        "user_input": user_input,
                        "conversation_history": ws_history,
                        "environment": ws_env,
                    }
                    await websocket.send_json({"type": "task_started", "message": "开始执行任务...", "timestamp": time.time()})
                    result = workflow.invoke(initial_state)
                    task_sequence = result.get("task_sequence", [])
                    for i, task in enumerate(task_sequence):
                        await websocket.send_json({
                            "type": "task_progress",
                            "task_index": i,
                            "task_id": task.get("task_id", ""),
                            "intent": task.get("intent", ""),
                            "status": task.get("status", "pending"),
                            "result": task.get("result", ""),
                            "timestamp": time.time()
                        })
                    await websocket.send_json({
                        "type": "task_completed",
                        "response": result.get("response", ""),
                        "execution_result": result.get("execution_result", ""),
                        "task_sequence": task_sequence,
                        "environment": result.get("environment"),
                        "timestamp": time.time()
                    })
                    _save_session(session_id, result)
            except json.JSONDecodeError:
                await websocket.send_json({"type": "error", "message": "Invalid JSON format"})
    except WebSocketDisconnect:
        if session_id in active_connections:
            del active_connections[session_id]
