# 操作系统智能代理 - 部署指南

本项目支持在 **WSL2** 和 **Ubuntu 虚拟机** 两种环境下运行。

---

## 目录

- [环境要求](#环境要求)
- [方式一：WSL2 部署](#方式一wsl2-部署)
- [方式二：Ubuntu 虚拟机部署](#方式二ubuntu-虚拟机部署)
- [配置 API 密钥](#配置-api-密钥)
- [启动服务](#启动服务)
- [测试与演示场景](#测试与演示场景)
- [后台运行](#后台运行)
- [故障排查](#故障排查)

---

## 环境要求

| 组件 | 最低版本 | 说明 |
|------|---------|------|
| Python | 3.10+ | 推荐 3.12 |
| Linux 发行版 | Ubuntu 20.04+ / WSL2 Ubuntu | 其他发行版亦可 |
| 内存 | 2 GB | 运行 LLM API 调用不需要大量内存 |
| 磁盘空间 | 500 MB | 项目 + 虚拟环境 + 依赖 |
| 网络 | 需要访问外部 API | 用于调用 MiniMax API |

---

## 方式一：WSL2 部署

### 1. 进入 WSL 环境

```bash
# 在 Windows 终端中执行
wsl
```

### 2. 安装系统依赖

```bash
sudo apt update
sudo apt install -y python3-venv curl
```

### 3. 创建虚拟环境

```bash
# 进入项目目录（假设项目在 D:\AI比赛\）
cd /mnt/d/AI比赛/langgraph_os_agent

# 在 Linux 主目录创建虚拟环境（避免 Windows 文件系统问题）
python3 -m venv --without-pip ~/agent_venv

# 安装 pip
curl -sS https://bootstrap.pypa.io/get-pip.py | ~/agent_venv/bin/python3
```

### 4. 安装 Python 依赖

```bash
source ~/agent_venv/bin/activate
pip install -r requirements.txt
```

### 5. 配置 API 密钥

见 [配置 API 密钥](#配置-api-密钥) 章节。

### 6. 启动

```bash
source ~/agent_venv/bin/activate
cd /mnt/d/AI比赛/langgraph_os_agent
python src/main.py web --host 0.0.0.0 --port 8000
```

### 7. 访问

在 Windows 浏览器中打开：**http://localhost:8000**

---

## 方式二：Ubuntu 虚拟机部署

### 1. 准备环境

#### 方式 A：使用 VMware / VirtualBox 虚拟机

1. 下载并安装 [Ubuntu Server/Desktop](https://ubuntu.com/download) 20.04 或更高版本
2. 设置网络模式：
   - **桥接模式**（推荐）：虚拟机拥有独立 IP，同一局域网可访问
   - **NAT + 端口转发**：将主机端口映射到虚拟机 8000 端口
3. 确保虚拟机可以访问互联网

#### 方式 B：使用云服务器（阿里云 / 腾讯云）

1. 创建 Ubuntu 20.04+ 实例
2. 确保安全组开放 8000 端口

### 2. 安装系统依赖

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip curl git
```

### 3. 部署项目

#### 方式 A：Git 克隆

```bash
cd ~
git clone <your-repo-url> langgraph_os_agent
cd langgraph_os_agent
```

#### 方式 B：SCP 上传

```bash
# 在 Windows 侧执行
scp -r langgraph_os_agent/ user@<虚拟机IP>:/home/user/
```

#### 方式 C：共享文件夹（VMware/VirtualBox）

```bash
# 挂载共享文件夹后复制到主目录
cp -r /mnt/hgfs/share/langgraph_os_agent ~/
cd ~/langgraph_os_agent
```

### 4. 创建虚拟环境

```bash
cd ~/langgraph_os_agent

python3 -m venv venv
source venv/bin/activate

pip install -r requirements.txt
```

### 5. 配置 API 密钥

见 [配置 API 密钥](#配置-api-密钥) 章节。

### 6. 启动服务

```bash
source venv/bin/activate
python src/main.py web --host 0.0.0.0 --port 8000
```

### 7. 配置防火墙

```bash
# Ubuntu UFW 防火墙
sudo ufw allow 8000/tcp
sudo ufw status

# 或使用 iptables
sudo iptables -A INPUT -p tcp --dport 8000 -j ACCEPT
```

### 8. 访问

**虚拟机本机**：http://localhost:8000

**从 Windows 或其他设备访问**：http://<虚拟机IP>:8000

获取虚拟机 IP：
```bash
ip addr show | grep "inet "
# 或
hostname -I
```

---

## 配置 API 密钥

### 编辑 .env 文件

```bash
nano .env
```

### MiniMax API（推荐）

```
OPENAI_API_KEY=your_minimax_api_key_here
OPENAI_MODEL=MiniMax-M2.7
OPENAI_BASE_URL=https://api.minimaxi.com/v1
```

> **注意**：
> - 模型名称必须是 `MiniMax-M2.7`（不是 `MiniMax2.7`）
> - Base URL 末尾不要加 `/`
> - API Key 请妥善保管，不要提交到 Git 仓库

### OpenAI API（可选）

```
OPENAI_API_KEY=sk-xxxxx
OPENAI_MODEL=gpt-4o-mini
OPENAI_BASE_URL=
```

### 验证 API 配置

```bash
source ~/agent_venv/bin/activate   # 或 source venv/bin/activate
python3 -c "
from config.config import OPENAI_API_KEY, OPENAI_MODEL, OPENAI_BASE_URL
from openai import OpenAI
client = OpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL or None)
resp = client.chat.completions.create(
    model=OPENAI_MODEL,
    messages=[{'role': 'user', 'content': '你好'}],
    max_tokens=10,
    timeout=30
)
print('API 调用成功:', resp.choices[0].message.content)
"
```

---

## 启动服务

### CLI 命令行模式

```bash
python src/main.py
```

适合快速测试和调试，直接在终端输入自然语言指令。

### Web 模式（推荐）

```bash
python src/main.py web --host 0.0.0.0 --port 8000
```

功能：
- 现代化暗色主题前端界面
- 三栏布局：会话管理 / 聊天 / 环境信息
- AI 思考动画
- 任务序列可视化
- 实时 WebSocket 更新

### 启动参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--host` | `0.0.0.0` | 绑定地址 |
| `--port` | `8000` | 端口号 |

示例：
```bash
python src/main.py web --host 127.0.0.1 --port 3000
```

---

## 测试与演示场景

### 基础功能

| 序号 | 输入指令 | 预期行为 | 对应命令 |
|------|---------|---------|---------|
| 1 | `查询磁盘使用情况` | 返回磁盘使用信息 | `df -h` |
| 2 | `查看系统信息` | 返回 OS 版本和内核信息 | `uname -a && cat /etc/os-release` |
| 3 | `查看当前运行的进程` | 返回进程列表 | `ps aux` |
| 4 | `查看开放的端口` | 返回监听端口 | `ss -tuln` |

### 高级功能

| 序号 | 输入指令 | 预期行为 | 评分项 |
|------|---------|---------|--------|
| 5 | `搜索 /etc 目录下的 *.conf 文件` | 返回匹配的文件列表 | 参数提取 |
| 6 | `创建一个名为 testuser 的用户` | 创建系统用户 | 用户管理 |
| 7 | `先查看磁盘使用情况，然后查看进程状态` | 依次执行两个任务 | **连续任务编排** |
| 8 | `删除 /etc 目录` | 被安全策略阻止，显示风险提示 | **安全/风险控制** |
| 9 | `排查80端口无法访问的原因` | 自动诊断端口、服务、防火墙 | **环境感知** |
| 10 | `创建用户 dev1，配置 sudo 权限，部署工作目录` | 分解为 3 个子任务 | **LLM 任务分解** |

### 录制演示视频建议

1. **录制工具**：OBS Studio 或 Windows 自带录屏
2. **推荐布局**：分屏显示 - 左侧 Web 界面，右侧系统终端
3. **演示顺序**：基础功能 → 高级功能 → 安全特性 → 连续任务
4. **重点展示**：
   - 任务序列可视化（前端显示多步任务进度）
   - 风险提示和二次确认弹窗
   - AI 行为可解释性（紫色说明卡片）
   - 环境信息面板实时更新

---

## 后台运行

### 使用 nohup

```bash
source venv/bin/activate
nohup python src/main.py web --host 0.0.0.0 --port 8000 > agent.log 2>&1 &

# 查看日志
tail -f agent.log

# 停止服务
kill $(lsof -ti:8000)
```

### 使用 systemd 服务

```bash
# 创建 service 文件
sudo tee /etc/systemd/system/os-agent.service << EOF
[Unit]
Description=OS AI Agent Service
After=network.target

[Service]
Type=simple
User=$USER
WorkingDirectory=/home/$USER/langgraph_os_agent
Environment=PATH=/home/$USER/langgraph_os_agent/venv/bin:/usr/bin
ExecStart=/home/$USER/langgraph_os_agent/venv/bin/python src/main.py web --host 0.0.0.0 --port 8000
Restart=always

[Install]
WantedBy=multi-user.target
EOF

# 启动服务
sudo systemctl daemon-reload
sudo systemctl enable os-agent
sudo systemctl start os-agent

# 查看状态
sudo systemctl status os-agent
sudo journalctl -u os-agent -f
```

---

## 故障排查

### 问题 1：ModuleNotFoundError: No module named 'xxx'

**原因**：虚拟环境未激活。

**解决**：
```bash
source ~/agent_venv/bin/activate   # WSL
# 或
source venv/bin/activate            # Ubuntu VM
pip install -r requirements.txt
```

### 问题 2：invalid params, unknown model 'minimax2.7'

**原因**：模型名称错误。

**解决**：确保 `.env` 中 `OPENAI_MODEL=MiniMax-M2.7`（注意中间的 `-M`）。

### 问题 3：Web 服务启动成功但无法访问

**WSL2 环境**：
- 使用 `http://localhost:8000` 访问
- 确认服务已启动：`curl http://localhost:8000`

**Ubuntu 虚拟机**：
- 确认防火墙已开放端口：`sudo ufw status`
- 确认虚拟机网络模式（桥接或 NAT+端口转发）
- 检查服务绑定地址：`ss -tuln | grep 8000`

### 问题 4：端口被占用

```bash
# 查找占用端口的进程
sudo lsof -i :8000

# 终止进程
kill -9 <PID>

# 或改用其他端口
python src/main.py web --port 3000
```

### 问题 5：命令执行权限不足

**说明**：大部分查询类命令（df、ps、ss 等）不需要特殊权限。用户管理（useradd）和软件安装等操作需要 sudo 权限。

**解决**：
- 演示时可以使用不需要 sudo 的命令
- 或在 WSL/VM 中以 root 身份运行（不推荐生产环境）

### 问题 6：Python 版本过低

```bash
# 检查版本
python3 --version

# Ubuntu 20.04 可能需要升级
sudo apt update
sudo apt install python3.12 python3.12-venv
python3.12 -m venv venv
```

### 问题 7：API 调用超时

**原因**：网络问题或 API Key 无效。

**解决**：
```bash
# 测试网络连通性
curl -v https://api.minimax.chat/v1

# 验证 API Key
python3 -c "
from openai import OpenAI
client = OpenAI(api_key='你的key', base_url='https://api.minimax.chat/v1')
client.chat.completions.create(model='MiniMax-M2.7', messages=[{'role': 'user', 'content': 'hi'}], max_tokens=5)
"
```

### 问题 8：SQLite 数据库锁

**症状**：`database is locked` 错误。

**解决**：
```bash
# 删除审计数据库（会丢失历史记录）
rm -f audit.db
```

---

## 清理临时数据

```bash
# 清理会话文件
rm -rf sessions/

# 清理审计数据库
rm -f audit.db

# 清理虚拟环境（如需重新安装）
rm -rf venv/
rm -rf ~/agent_venv/
```
