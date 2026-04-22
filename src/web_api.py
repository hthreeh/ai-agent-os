import os
import sys
import time
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from typing import Optional, Dict, Any

from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

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


class UserRequest(BaseModel):
    input: str
    session_id: Optional[str] = None


class ConfirmRequest(BaseModel):
    user_input: str
    confirmed: bool
    session_id: str
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


@app.get("/", response_class=HTMLResponse)
async def root():
    return r"""
    <!DOCTYPE html>
    <html lang="zh-CN">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>操作系统智能代理 | OS Agent</title>
        <style>
            :root {
                --bg-primary: #0a0e1a;
                --bg-secondary: #111827;
                --bg-tertiary: #1a2235;
                --bg-card: #1e293b;
                --border-color: #2a3550;
                --text-primary: #e2e8f0;
                --text-secondary: #94a3b8;
                --text-muted: #64748b;
                --accent-blue: #3b82f6;
                --accent-cyan: #38bdf8;
                --accent-green: #22c55e;
                --accent-red: #ef4444;
                --accent-orange: #f97316;
                --accent-purple: #a855f7;
                --gradient-primary: linear-gradient(135deg, #3b82f6 0%, #8b5cf6 100%);
                --gradient-dark: linear-gradient(180deg, #111827 0%, #0a0e1a 100%);
                --shadow-sm: 0 1px 2px rgba(0,0,0,0.3);
                --shadow-md: 0 4px 12px rgba(0,0,0,0.4);
                --shadow-lg: 0 8px 32px rgba(0,0,0,0.5);
                --radius-sm: 6px;
                --radius-md: 10px;
                --radius-lg: 16px;
            }
            * { margin: 0; padding: 0; box-sizing: border-box; }
            body { font-family: 'Segoe UI', -apple-system, BlinkMacSystemFont, sans-serif; background: var(--gradient-dark); color: var(--text-primary); min-height: 100vh; }
            
            .layout { display: flex; height: 100vh; overflow: hidden; }
            
            .sidebar {
                width: 280px; background: var(--bg-secondary); border-right: 1px solid var(--border-color);
                display: flex; flex-direction: column; flex-shrink: 0;
            }
            .sidebar-header { padding: 20px; border-bottom: 1px solid var(--border-color); }
            .sidebar-header h2 { font-size: 16px; color: var(--accent-cyan); margin-bottom: 4px; }
            .sidebar-header p { font-size: 12px; color: var(--text-muted); }
            .new-chat-btn {
                width: 100%; padding: 10px; margin-top: 12px; background: var(--gradient-primary);
                border: none; border-radius: var(--radius-md); color: white; font-weight: 600;
                cursor: pointer; font-size: 14px; transition: opacity 0.2s;
            }
            .new-chat-btn:hover { opacity: 0.9; }
            .session-list { flex: 1; overflow-y: auto; padding: 8px; }
            .session-item {
                padding: 10px 12px; border-radius: var(--radius-sm); cursor: pointer;
                margin-bottom: 4px; transition: background 0.2s; display: flex; justify-content: space-between; align-items: center;
            }
            .session-item:hover { background: var(--bg-tertiary); }
            .session-item.active { background: var(--bg-tertiary); border-left: 3px solid var(--accent-blue); }
            .session-item .title { font-size: 13px; color: var(--text-primary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; flex: 1; }
            .session-item .delete-btn {
                background: none; border: none; color: var(--text-muted); cursor: pointer;
                padding: 2px 6px; border-radius: 4px; font-size: 12px; opacity: 0; transition: opacity 0.2s;
            }
            .session-item:hover .delete-btn { opacity: 1; }
            .session-item .delete-btn:hover { color: var(--accent-red); background: rgba(239,68,68,0.1); }
            
            .main-content { flex: 1; display: flex; flex-direction: column; min-width: 0; }
            .main-header {
                padding: 16px 24px; border-bottom: 1px solid var(--border-color);
                display: flex; justify-content: space-between; align-items: center; background: var(--bg-secondary);
            }
            .main-header h1 {
                font-size: 20px; background: var(--gradient-primary); -webkit-background-clip: text;
                -webkit-text-fill-color: transparent; background-clip: text;
            }
            .main-header .status { font-size: 13px; color: var(--text-muted); display: flex; align-items: center; gap: 6px; }
            .status-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--accent-green); animation: pulse 2s infinite; }
            
            .chat-area { flex: 1; display: flex; flex-direction: column; overflow: hidden; }
            .messages { flex: 1; overflow-y: auto; padding: 24px; }
            
            .msg-wrapper { display: flex; gap: 12px; margin-bottom: 20px; animation: fadeIn 0.3s ease; }
            .msg-wrapper.user { flex-direction: row-reverse; }
            .avatar {
                width: 36px; height: 36px; border-radius: 50%; display: flex; align-items: center;
                justify-content: center; font-size: 16px; flex-shrink: 0;
            }
            .avatar.agent { background: var(--gradient-primary); }
            .avatar.user { background: var(--bg-tertiary); border: 1px solid var(--border-color); }
            .msg {
                max-width: 75%; padding: 14px 18px; border-radius: var(--radius-lg);
                line-height: 1.6; font-size: 14px; word-wrap: break-word;
            }
            .msg-wrapper.user .msg { background: var(--accent-blue); color: white; border-bottom-right-radius: 4px; }
            .msg-wrapper.agent .msg { background: var(--bg-card); border: 1px solid var(--border-color); border-bottom-left-radius: 4px; }
            .msg .time { font-size: 11px; color: var(--text-muted); margin-top: 6px; }
            .msg-wrapper.user .msg .time { color: rgba(255,255,255,0.6); }
            
            .msg-risk {
                background: linear-gradient(135deg, #450a0a 0%, #7f1d1d 100%); border: 1px solid #dc2626;
                border-radius: var(--radius-md); padding: 16px; margin-bottom: 12px;
            }
            .msg-risk .risk-header { display: flex; align-items: center; gap: 8px; margin-bottom: 10px; }
            .msg-risk .risk-badge {
                background: #dc2626; color: white; padding: 2px 10px; border-radius: 12px;
                font-size: 12px; font-weight: 600;
            }
            .msg-risk .risk-title { color: #fca5a5; font-weight: 600; font-size: 14px; }
            .msg-risk .risk-detail { font-size: 13px; color: #fecaca; line-height: 1.5; margin-bottom: 12px; }
            .confirm-btns { display: flex; gap: 10px; margin-top: 12px; }
            .confirm-btns button {
                padding: 8px 20px; border: none; border-radius: var(--radius-sm); cursor: pointer;
                font-weight: 600; font-size: 13px; transition: transform 0.1s;
            }
            .confirm-btns button:active { transform: scale(0.96); }
            .btn-yes { background: var(--accent-green); color: white; }
            .btn-no { background: var(--accent-red); color: white; }
            
            .task-sequence {
                background: var(--bg-tertiary); border: 1px solid var(--border-color); border-radius: var(--radius-md);
                padding: 14px; margin: 10px 0;
            }
            .task-sequence .task-title { font-size: 13px; color: var(--accent-cyan); font-weight: 600; margin-bottom: 10px; }
            .task-step { display: flex; align-items: center; gap: 10px; padding: 6px 0; font-size: 13px; }
            .task-step .step-icon { width: 20px; height: 20px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 10px; flex-shrink: 0; }
            .task-step .step-icon.done { background: var(--accent-green); color: white; }
            .task-step .step-icon.running { background: var(--accent-blue); color: white; animation: pulse 1.5s infinite; }
            .task-step .step-icon.pending { background: var(--text-muted); color: var(--bg-primary); }
            .task-step .step-text { color: var(--text-secondary); }
            .task-step .step-text.done { color: var(--accent-green); }
            .task-step .step-text.running { color: var(--accent-cyan); font-weight: 600; }
            .task-progress { height: 4px; background: var(--bg-primary); border-radius: 2px; margin-top: 10px; overflow: hidden; }
            .task-progress .bar { height: 100%; background: var(--gradient-primary); border-radius: 2px; transition: width 0.5s ease; }
            
            .thinking-indicator { display: flex; gap: 6px; padding: 8px 0; }
            .thinking-indicator span {
                width: 8px; height: 8px; border-radius: 50%; background: var(--accent-cyan);
                animation: bounce 1.4s infinite;
            }
            .thinking-indicator span:nth-child(2) { animation-delay: 0.2s; }
            .thinking-indicator span:nth-child(3) { animation-delay: 0.4s; }
            
            .input-area { padding: 16px 24px; border-top: 1px solid var(--border-color); background: var(--bg-secondary); }
            .input-row { display: flex; gap: 10px; }
            .input-row input {
                flex: 1; padding: 12px 16px; border: 1px solid var(--border-color); border-radius: var(--radius-md);
                background: var(--bg-primary); color: var(--text-primary); font-size: 14px; outline: none;
                transition: border-color 0.2s;
            }
            .input-row input:focus { border-color: var(--accent-blue); }
            .input-row button {
                padding: 12px 24px; border: none; border-radius: var(--radius-md);
                background: var(--gradient-primary); color: white; cursor: pointer;
                font-weight: 600; font-size: 14px; transition: opacity 0.2s;
            }
            .input-row button:hover { opacity: 0.9; }
            .input-row button:disabled { opacity: 0.5; cursor: not-allowed; }
            .examples { margin-top: 10px; display: flex; flex-wrap: wrap; gap: 6px; }
            .ex-btn {
                background: var(--bg-tertiary); border: 1px solid var(--border-color); color: var(--text-secondary);
                padding: 6px 14px; border-radius: 20px; cursor: pointer; font-size: 12px; transition: all 0.2s;
            }
            .ex-btn:hover { border-color: var(--accent-cyan); color: var(--accent-cyan); }
            
            .env-panel {
                width: 280px; background: var(--bg-secondary); border-left: 1px solid var(--border-color);
                padding: 20px; overflow-y: auto; flex-shrink: 0;
            }
            .env-panel h3 { font-size: 14px; color: var(--accent-cyan); margin-bottom: 16px; display: flex; align-items: center; gap: 6px; }
            .env-card {
                background: var(--bg-card); border: 1px solid var(--border-color); border-radius: var(--radius-md);
                padding: 14px; margin-bottom: 12px;
            }
            .env-card .label { font-size: 12px; color: var(--text-muted); margin-bottom: 4px; }
            .env-card .value { font-size: 14px; color: var(--text-primary); font-weight: 500; }
            .env-card .value.highlight { color: var(--accent-green); }
            .env-stats { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
            .env-stat { text-align: center; padding: 10px; background: var(--bg-tertiary); border-radius: var(--radius-sm); }
            .env-stat .stat-val { font-size: 18px; font-weight: 700; color: var(--accent-cyan); }
            .env-stat .stat-label { font-size: 11px; color: var(--text-muted); margin-top: 2px; }
            
            @keyframes pulse { 0%,100% { opacity: 1; } 50% { opacity: 0.4; } }
            @keyframes bounce { 0%,80%,100% { transform: translateY(0); } 40% { transform: translateY(-8px); } }
            @keyframes fadeIn { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: translateY(0); } }
            
            @media (max-width: 1024px) {
                .env-panel { display: none; }
                .sidebar { width: 240px; }
            }
            @media (max-width: 768px) {
                .sidebar { display: none; }
                .main-header h1 { font-size: 16px; }
                .msg { max-width: 90%; }
            }
            
            .messages::-webkit-scrollbar, .session-list::-webkit-scrollbar, .env-panel::-webkit-scrollbar { width: 6px; }
            .messages::-webkit-scrollbar-track, .session-list::-webkit-scrollbar-track, .env-panel::-webkit-scrollbar-track { background: transparent; }
            .messages::-webkit-scrollbar-thumb, .session-list::-webkit-scrollbar-thumb, .env-panel::-webkit-scrollbar-thumb { background: var(--border-color); border-radius: 3px; }
            .messages::-webkit-scrollbar-thumb:hover, .session-list::-webkit-scrollbar-thumb:hover, .env-panel::-webkit-scrollbar-thumb:hover { background: var(--text-muted); }
        </style>
    </head>
    <body>
        <div class="layout">
            <aside class="sidebar">
                <div class="sidebar-header">
                    <h2>会话管理</h2>
                    <p>管理你的对话历史</p>
                    <button class="new-chat-btn" onclick="newSession()">+ 新建对话</button>
                </div>
                <div class="session-list" id="sessionList"></div>
            </aside>
            
            <main class="main-content">
                <div class="main-header">
                    <h1>操作系统智能代理</h1>
                    <div class="status"><span class="status-dot"></span>在线</div>
                </div>
                <div class="chat-area">
                    <div class="messages" id="messages">
                        <div class="msg-wrapper agent">
                            <div class="avatar agent">AI</div>
                            <div class="msg">
                                欢迎使用 <b>操作系统智能代理</b>！我可以帮你管理 Linux 服务器。<br><br>
                                支持功能：
                                <ul style="margin-left: 18px; margin-top: 6px;">
                                    <li>系统信息查询</li>
                                    <li>进程和端口管理</li>
                                    <li>文件和目录操作</li>
                                    <li>连续任务自动执行</li>
                                </ul>
                                <div class="time">系统</div>
                            </div>
                        </div>
                    </div>
                    <div class="input-area">
                        <div class="input-row">
                            <input type="text" id="inp" placeholder="输入命令，如：查询磁盘使用情况" onkeypress="if(event.key==='Enter')sendMessage()">
                            <button id="sendBtn" onclick="sendMessage()">发送</button>
                        </div>
                        <div class="examples">
                            <button class="ex-btn" onclick="set('查询磁盘使用情况')">磁盘使用</button>
                            <button class="ex-btn" onclick="set('查看当前运行的进程')">查看进程</button>
                            <button class="ex-btn" onclick="set('查看开放的端口')">查看端口</button>
                            <button class="ex-btn" onclick="set('搜索 /etc 目录下的所有 .conf 文件')">搜索配置</button>
                            <button class="ex-btn" onclick="set('查看系统信息')">系统信息</button>
                            <button class="ex-btn" onclick="set('先查看磁盘使用情况，然后查看进程状态')">连续任务</button>
                            <button class="ex-btn" onclick="set('检查磁盘空间，如果不足就清理日志，然后安装 nginx')">场景一</button>
                            <button class="ex-btn" onclick="set('创建新用户 dev1，配置 sudo 权限，部署工作目录')">场景二</button>
                            <button class="ex-btn" onclick="set('排查80端口无法访问的原因')">场景三</button>
                        </div>
                    </div>
                </div>
            </main>
            
            <aside class="env-panel">
                <h3>环境信息</h3>
                <div class="env-card">
                    <div class="label">操作系统</div>
                    <div class="value highlight" id="env-os">检测中...</div>
                </div>
                <div class="env-card">
                    <div class="label">主机名</div>
                    <div class="value" id="env-hostname">-</div>
                </div>
                <div class="env-card">
                    <div class="label">内核版本</div>
                    <div class="value" id="env-kernel">-</div>
                </div>
                <div class="env-card">
                    <div class="label">会话统计</div>
                    <div class="env-stats">
                        <div class="env-stat"><div class="stat-val" id="stat-sessions">0</div><div class="stat-label">会话数</div></div>
                        <div class="env-stat"><div class="stat-val" id="stat-msgs">0</div><div class="stat-label">消息数</div></div>
                    </div>
                </div>
            </aside>
        </div>
        <script>
        (function() {
            let sessionId = localStorage.getItem('os_agent_session') || ('session_' + Date.now());
            let sessions = [];
            let pendingUserInput = '';
            let pendingState = null;
            let messageCount = 0;

            function formatTime(ts) {
                var d = ts ? new Date(ts * 1000) : new Date();
                var h = String(d.getHours()).padStart(2, '0');
                var m = String(d.getMinutes()).padStart(2, '0');
                return h + ':' + m;
            }

            function updateStats() {
                document.getElementById('stat-sessions').textContent = sessions.length;
                document.getElementById('stat-msgs').textContent = messageCount;
            }

            function updateSessions() {
                var list = document.getElementById('sessionList');
                list.innerHTML = '';
                sessions.forEach(function(s) {
                    var div = document.createElement('div');
                    div.className = 'session-item' + (s.id === sessionId ? ' active' : '');
                    var span = document.createElement('span');
                    span.className = 'title';
                    var savedTitle = localStorage.getItem('session_title_' + s.id);
                    span.textContent = savedTitle || s.title || ('对话 ' + s.id.slice(-6));
                    span.onclick = function() { switchSession(s.id); };
                    var del = document.createElement('button');
                    del.className = 'delete-btn';
                    del.textContent = '×';
                    del.onclick = function(e) { e.stopPropagation(); deleteSession(s.id); };
                    div.appendChild(span);
                    div.appendChild(del);
                    list.appendChild(div);
                });
            }

            async function loadSessions() {
                try {
                    var r = await fetch('/api/sessions');
                    var d = await r.json();
                    sessions = (d.sessions || []).map(function(s) {
                        var title = localStorage.getItem('session_title_' + s.session_id);
                        return { id: s.session_id, title: title || ('对话 ' + s.session_id.slice(-6)) };
                    });
                    if (sessions.length === 0) {
                        sessions.push({ id: sessionId, title: '新对话' });
                    }
                    updateSessions();
                    updateStats();
                } catch(e) {
                    if (sessions.length === 0) {
                        sessions.push({ id: sessionId, title: '新对话' });
                        updateSessions();
                    }
                }
            }

            window.newSession = function() {
                sessionId = 'session_' + Date.now();
                localStorage.setItem('os_agent_session', sessionId);
                var title = prompt('输入会话名称（可选）：') || '新对话';
                localStorage.setItem('session_title_' + sessionId, title);
                sessions.push({ id: sessionId, title: title });
                updateSessions();
                updateStats();
                document.getElementById('messages').innerHTML = '';
                addAgentMsg('新对话已创建！我可以帮你管理 Linux 服务器。');
            };

            async function switchSession(id) {
                sessionId = id;
                localStorage.setItem('os_agent_session', id);
                updateSessions();
                document.getElementById('messages').innerHTML = '';
                try {
                    var r = await fetch('/api/session/' + id + '/history');
                    var d = await r.json();
                    var history = d.conversation_history || [];
                    messageCount = 0;
                    history.forEach(function(msg) {
                        addMsgWrapper(msg.role, escHtml(msg.content || ''));
                    });
                } catch(e) {
                    addAgentMsg('会话历史加载失败');
                }
            }
            window.switchSession = switchSession;

            async function deleteSession(id) {
                try {
                    await fetch('/api/session/' + id, { method: 'DELETE' });
                } catch(e) {}
                localStorage.removeItem('session_title_' + id);
                sessions = sessions.filter(function(s) { return s.id !== id; });
                if (id === sessionId && sessions.length > 0) {
                    sessionId = sessions[sessions.length - 1].id;
                    localStorage.setItem('os_agent_session', sessionId);
                    document.getElementById('messages').innerHTML = '';
                    try {
                        var r = await fetch('/api/session/' + sessionId + '/history');
                        var d = await r.json();
                        (d.conversation_history || []).forEach(function(msg) {
                            addMsgWrapper(msg.role, escHtml(msg.content || ''));
                        });
                    } catch(e) {}
                } else if (sessions.length === 0) {
                    sessionId = 'session_' + Date.now();
                    localStorage.setItem('os_agent_session', sessionId);
                }
                updateSessions();
                updateStats();
            }
            window.deleteSession = deleteSession;
            
            window.set = function(t) {
                document.getElementById('inp').value = t;
                document.getElementById('inp').focus();
            };
            
            function addMsgWrapper(cls, inner, time) {
                var wrapper = document.createElement('div');
                wrapper.className = 'msg-wrapper ' + cls;
                var avatar = document.createElement('div');
                avatar.className = 'avatar ' + cls;
                avatar.textContent = cls === 'user' ? '' : 'AI';
                var msg = document.createElement('div');
                msg.className = 'msg';
                msg.innerHTML = inner + '<div class="time">' + (time || formatTime()) + '<\/div>';
                wrapper.appendChild(avatar);
                wrapper.appendChild(msg);
                var messages = document.getElementById('messages');
                messages.appendChild(wrapper);
                messages.scrollTop = messages.scrollHeight;
                messageCount++;
                updateStats();
            }
            
            function addAgentMsg(html) {
                addMsgWrapper('agent', html);
            }
            
            function addThinking() {
                var id = 'thinking_' + Date.now();
                var wrapper = document.createElement('div');
                wrapper.className = 'msg-wrapper agent';
                wrapper.id = id;
                var avatar = document.createElement('div');
                avatar.className = 'avatar agent';
                avatar.textContent = 'AI';
                var msg = document.createElement('div');
                msg.className = 'msg';
                msg.innerHTML = '<div class="thinking-indicator"><span><\/span><span><\/span><span><\/span><\/div><div class="time">思考中...<\/div>';
                wrapper.appendChild(avatar);
                wrapper.appendChild(msg);
                document.getElementById('messages').appendChild(wrapper);
                document.getElementById('messages').scrollTop = document.getElementById('messages').scrollHeight;
                return id;
            }
            
            function removeThinking(id) {
                var el = document.getElementById(id);
                if (el) el.remove();
            }
            
            function addTaskSequence(tasks) {
                var html = '<div class="task-sequence"><div class="task-title">任务序列 (' + tasks.length + ' 步)<\/div>';
                tasks.forEach(function(t, i) {
                    var icon = i === 0 ? 'running' : 'pending';
                    var txt = i === 0 ? 'running' : '';
                    var label = (t && t.description) ? t.description : ((t && t.intent) ? t.intent : ('任务 ' + (i + 1)));
                    var extras = '';
                    if (t && t.branch_type && t.branch_type !== 'sequential') {
                        var branchLabel = t.branch_type === 'conditional' ? '条件分支' : '并行';
                        extras += ' <span style="color:var(--accent-orange);font-size:11px;">[' + branchLabel + ']<\/span>';
                    }
                    if (t && t.depends_on && t.depends_on.length > 0) {
                        extras += ' <span style="color:var(--text-muted);font-size:11px;">(依赖: ' + t.depends_on.join(', ') + ')<\/span>';
                    }
                    html += '<div class="task-step"><div class="step-icon ' + icon + '">' + (i === 0 ? '⟳' : (i + 1)) + '<\/div><span class="step-text ' + txt + '">' + label + extras + '<\/span><\/div>';
                });
                html += '<div class="task-progress"><div class="bar" style="width: ' + (100 / tasks.length) + '%"><\/div><\/div><\/div>';
                addAgentMsg(html);
            }
            
            function escHtml(s) { var d = document.createElement('div'); d.textContent = s; return d.innerHTML; }
            function escBr(s) { return escHtml(s).replace(/\n/g, '<' + 'br>'); }

            function fetchWithTimeout(url, options, timeout) {
                return Promise.race([
                    fetch(url, options),
                    new Promise(function(_, reject) {
                        setTimeout(function() { reject(new Error('请求超时，请检查网络或重试')); }, timeout);
                    })
                ]);
            }

            async function sendMessage() {
                var inp = document.getElementById('inp');
                var txt = inp.value.trim();
                if (!txt) return;
                inp.value = '';
                document.getElementById('sendBtn').disabled = true;
                pendingUserInput = txt;
                addMsgWrapper('user', escHtml(txt));

                var thinkId = addThinking();

                try {
                    var r = await fetchWithTimeout('/api/query', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({input: txt, session_id: sessionId})
                    }, 120000);
                    var d = await r.json();
                    removeThinking(thinkId);

                    if (d.requires_confirmation) {
                        var riskHtml = '<div class="msg-risk">';
                        riskHtml += '<div class="risk-header"><span class="risk-badge">中风险</span><span class="risk-title">需要您的确认</span></div>';
                        if (d.risk_assessment) {
                            riskHtml += '<div class="risk-detail">';
                            riskHtml += '风险解释: ' + (d.risk_assessment.risk_explanation || '该操作存在一定风险') + '<br>';
                            if (d.risk_assessment.command_impact) {
                                riskHtml += '潜在影响: ' + d.risk_assessment.command_impact.join(', ') + '<br>';
                            }
                            riskHtml += '</div>';
                        }
                        riskHtml += '<div class="confirm-btns"><button class="btn-yes" onclick="confirmRisk(true)">确认执行</button><button class="btn-no" onclick="confirmRisk(false)">取消</button></div>';
                        riskHtml += '</div>';
                        addMsgWrapper('agent', riskHtml);
                        pendingState = d;
                        if (d.session_id) sessionId = d.session_id;
                    } else {
                        var resp = escBr(d.response || d.execution_result || '');
                        addAgentMsg(resp);
                        if (d.session_id) sessionId = d.session_id;
                        if (d.environment) {
                            var env = d.environment;
                            var osInfo = env.os_info || {};
                            document.getElementById('env-os').textContent = env.os_type || '未知';
                            document.getElementById('env-hostname').textContent = osInfo.name || osInfo.hostname || osInfo.pretty_name || '-';
                            document.getElementById('env-kernel').textContent = osInfo.release || '-';
                        }
                    }
                } catch (e) {
                    removeThinking(thinkId);
                    addAgentMsg('<div style="color:var(--accent-red);">错误: ' + e.message + '</div>');
                }
                document.getElementById('sendBtn').disabled = false;
            }
            
            function typeText(html) {
                var id = 'typed_' + Date.now();
                var wrapper = document.createElement('div');
                wrapper.className = 'msg-wrapper agent';
                wrapper.id = id;
                var avatar = document.createElement('div');
                avatar.className = 'avatar agent';
                avatar.textContent = 'AI';
                var msg = document.createElement('div');
                msg.className = 'msg';
                msg.innerHTML = '<span class="typing-cursor"><\/span><div class="time">' + formatTime() + '<\/div>';
                wrapper.appendChild(avatar);
                wrapper.appendChild(msg);
                document.getElementById('messages').appendChild(wrapper);
                document.getElementById('messages').scrollTop = document.getElementById('messages').scrollHeight;
                
                var plain = html.split('<' + 'br>').join('\n').replace(new RegExp('<[^>]*>', 'g'), '');
                var idx = 0;
                var speed = 15;
                var timer = setInterval(function() {
                    if (idx >= plain.length) {
                        clearInterval(timer);
                        msg.innerHTML = html + '<div class="time">' + formatTime() + '<\/div>';
                        return;
                    }
                    var chunk = plain.slice(0, idx + 3);
                    idx += 3;
                    msg.innerHTML = escHtml(chunk).replace(/\n/g, '<' + 'br>') + '<span class="typing-cursor">▌<\/span><div class="time">' + formatTime() + '<\/div>';
                    document.getElementById('messages').scrollTop = document.getElementById('messages').scrollHeight;
                }, speed);
            }
            
            async function confirmRisk(ok) {
                var ps = pendingState || {};
                if (!ps.risk_assessment && !ps.command) {
                    addAgentMsg('<div style="color:var(--accent-red);">无可确认的操作，请重新发送请求</div>');
                    return;
                }
                // 禁用按钮 + loading 反馈
                var btns = document.querySelectorAll('.confirm-btns .btn-yes, .confirm-btns .btn-no');
                btns.forEach(function(b) { b.disabled = true; b.style.opacity = '0.5'; });
                var thinkId = addThinking();
                try {
                    var r = await fetchWithTimeout('/api/confirm', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({
                            user_input: pendingUserInput,
                            confirmed: ok,
                            session_id: sessionId,
                            risk_assessment: ps.risk_assessment,
                            command: ps.command,
                            task_sequence: ps.task_sequence,
                            current_task_index: ps.current_task_index,
                            task_status: ps.task_status,
                            environment: ps.environment,
                            risk_level: ps.risk_level,
                            risk_explanation: ps.risk_explanation
                        })
                    }, 120000);
                    var d = await r.json();
                    removeThinking(thinkId);
                    var statusMsg = ok ? '<div style="color:var(--accent-green);font-weight:600;">已确认执行<\/div>' : '<div style="color:var(--accent-red);font-weight:600;">已取消操作<\/div>';
                    if (d.explanation) {
                        statusMsg += '<div style="background:var(--bg-tertiary);border:1px solid var(--accent-purple);border-radius:var(--radius-md);padding:12px;margin-top:8px;font-size:13px;color:var(--accent-purple);">' + escHtml(d.explanation) + '<\/div>';
                    }
                    var resp = escBr(d.response || d.execution_result || '');
                    addAgentMsg(statusMsg + resp);
                    if (d.session_id) sessionId = d.session_id;
                    if (d.environment) {
                        var env = d.environment;
                        var osInfo = env.os_info || {};
                        document.getElementById('env-os').textContent = env.os_type || '未知';
                        document.getElementById('env-hostname').textContent = osInfo.name || osInfo.hostname || osInfo.pretty_name || '-';
                        document.getElementById('env-kernel').textContent = osInfo.release || '-';
                    }
                } catch (e) {
                    removeThinking(thinkId);
                    addAgentMsg('<div style="color:var(--accent-red);">错误: ' + e.message + '</div>');
                    btns.forEach(function(b) { b.disabled = false; b.style.opacity = '1'; });
                }
                // 确认操作完成后，按钮永久禁用，防止重复点击
                btns.forEach(function(b) { b.disabled = true; b.style.opacity = '0.3'; b.style.cursor = 'not-allowed'; });
            }
            
            updateSessions();
            updateStats();
            window.sendMessage = sendMessage;
            window.confirmRisk = confirmRisk;
            loadSessions();
        })();
        </script>
    </body>
    </html>
    """


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
    try:
        saved = _load_session(request.session_id)
        history = saved.get("conversation_history", [])
        task_sequence = request.task_sequence or saved.get("task_sequence", [])
        risk_assessment = {
            **saved.get("risk_assessment", {}),
            **(request.risk_assessment or {}),
            "requires_confirmation": False
        }

        state = {
            "session_id": request.session_id,
            "user_input": request.user_input,
            "user_confirmation": request.confirmed,
            "conversation_history": history,
            "command": request.command or saved.get("command", ""),
            "task_sequence": task_sequence,
            "current_task_index": request.current_task_index if request.current_task_index is not None else saved.get("current_task_index", 0),
            "task_status": request.task_status or saved.get("task_status", "in_progress"),
            "environment": request.environment or saved.get("environment", {}),
            "risk_assessment": risk_assessment,
            "risk_level": request.risk_level or saved.get("risk_level", risk_assessment.get("risk_level", "medium")),
            "risk_explanation": request.risk_explanation or saved.get("risk_explanation", risk_assessment.get("risk_explanation", "")),
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
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/sessions")
async def list_sessions():
    return {"sessions": audit_logger.get_all_sessions(limit=100)}


@app.delete("/api/session/{session_id}")
async def delete_session(session_id: str):
    from src.agent_workflow import SESSION_DIR
    import os
    path = os.path.join(SESSION_DIR, f"{session_id}.json")
    if os.path.exists(path):
        os.remove(path)
    return {"success": True}


@app.get("/api/session/{session_id}/history")
async def get_session_history(session_id: str):
    from src.agent_workflow import _load_session
    saved = _load_session(session_id)
    return {
        "conversation_history": saved.get("conversation_history", []),
        "environment": saved.get("environment", {})
    }


@app.get("/api/audit/security")
async def security_events(session_id: Optional[str] = None):
    return {"events": audit_logger.get_security_events(session_id)}


@app.get("/api/audit/session/{session_id}")
async def session_audit(session_id: str):
    return {"history": audit_logger.get_session_history(session_id)}


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

                    await websocket.send_json({
                        "type": "task_started",
                        "message": "开始执行任务...",
                        "timestamp": time.time()
                    })

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
                await websocket.send_json({
                    "type": "error",
                    "message": "Invalid JSON format"
                })
    except WebSocketDisconnect:
        if session_id in active_connections:
            del active_connections[session_id]
