# WSL 部署与测试指南

## 前提条件

- Windows 10/11 已安装 WSL2（推荐 Ubuntu 发行版）
- 项目目录位于 Windows 侧，通过 `/mnt/d/AI比赛/langgraph_os_agent` 访问

---

## 第一步：进入 WSL 环境

```bash
# 打开 PowerShell 或 CMD，输入：
wsl
```

---

## 第二步：检查环境

```bash
# 检查 Python 版本（需要 3.10+）
python3 --version

# 检查 pip 是否可用
python3 -m pip --version
```

---

## 第三步：安装系统依赖

```bash
sudo apt update
sudo apt install -y python3-venv
```

---

## 第四步：创建虚拟环境

```bash
# 进入项目目录
cd /mnt/d/AI比赛/langgraph_os_agent

# 创建虚拟环境（在 Linux 侧创建，避免 Windows 文件系统权限问题）
python3 -m venv ~/agent_venv

# 安装 pip 到虚拟环境
~/agent_venv/bin/python3 -m ensurepip --upgrade

# 或者使用 get-pip.py（如果 ensurepip 不可用）
curl -sS https://bootstrap.pypa.io/get-pip.py | ~/agent_venv/bin/python3

# 激活虚拟环境
source ~/agent_venv/bin/activate

# 验证 pip 可用
pip --version
```

---

## 第五步：安装 Python 依赖

```bash
# 确保虚拟环境已激活
source ~/agent_venv/bin/activate

cd /mnt/d/AI比赛/langgraph_os_agent

# 安装依赖
pip install -r requirements.txt
```

---

## 第六步：配置 API 密钥

编辑 `.env` 文件：

```bash
nano .env
```

确保包含以下内容（已配置好的 MiniMax API）：

```
OPENAI_API_KEY=sk-cp-Q9wXd2Ed5sYRg5Fk_zfjdwbCnbCQDl3XMJiba5sPUoakmQS1v5jKEBzHpSTZWprNc_kmIa-YQO9p573oxh6zJ89HTTt_7PALVb4cwxsGiX5SC_ykXVmRra8
OPENAI_MODEL=MiniMax-M2.7
OPENAI_BASE_URL=https://api.minimaxi.com/v1
```

> **注意**：模型名称是 `MiniMax-M2.7`（不是 `MiniMax2.7`）。

---

## 第七步：测试运行

### 方式一：CLI 命令行模式

```bash
cd /mnt/d/AI比赛/langgraph_os_agent
source ~/agent_venv/bin/activate

python src/main.py
```

然后输入自然语言指令测试，例如：
```
请输入的命令: 查询磁盘使用情况
请输入的命令: 查看系统信息
请输入的命令: 搜索 /etc 目录下的 *.conf 文件
请输入的命令: exit
```

### 方式二：Web 模式（推荐）

```bash
cd /mnt/d/AI比赛/langgraph_os_agent
source ~/agent_venv/bin/activate

python src/main.py web --host 0.0.0.0 --port 8000
```

启动成功后，在 Windows 浏览器中访问：
```
http://localhost:8000
```

---

## 快速一键启动脚本

在 WSL 中创建启动脚本：

```bash
cat > ~/start_os_agent.sh << 'EOF'
#!/bin/bash
source ~/agent_venv/bin/activate
cd /mnt/d/AI比赛/langgraph_os_agent
python src/main.py web --host 0.0.0.0 --port 8000
EOF

chmod +x ~/start_os_agent.sh
```

以后只需运行：

```bash
~/start_os_agent.sh
```

---

## 常用测试场景

| 场景 | 测试指令 | 预期行为 |
|------|---------|---------|
| 磁盘查询 | `查询磁盘使用情况` | 执行 `df -h` 并返回结果 |
| 进程查看 | `查看当前运行的进程` | 执行 `ps aux` |
| 端口检查 | `查看开放的端口` | 执行 `ss -tuln` |
| 文件搜索 | `搜索 /etc 目录下的 *.conf 文件` | 执行 `find /etc -name '*.conf'` |
| 系统信息 | `查看系统信息` | 执行 `uname -a && cat /etc/os-release` |
| 连续任务 | `先查看磁盘，然后查看进程` | 依次执行两个任务 |
| 用户管理 | `创建新用户 testuser` | 执行 `useradd testuser` |
| 安全拦截 | `删除 /etc 目录` | 被安全策略阻止 |

---

## 故障排查

### 问题 1：`ModuleNotFoundError: No module named 'dotenv'`

**原因**：虚拟环境未激活或未安装依赖。

**解决**：
```bash
source ~/agent_venv/bin/activate
pip install -r requirements.txt
```

### 问题 2：`invalid params, unknown model`

**原因**：模型名称不正确。

**解决**：确保 `.env` 中的 `OPENAI_MODEL=MiniMax-M2.7`（注意中间的 `-M`）。

### 问题 3：Web 服务启动成功但浏览器无法访问

**解决**：
- WSL2 中使用 `localhost` 即可访问
- 检查防火墙是否阻止：`sudo ufw status`
- 尝试确认端口：`curl http://localhost:8000`

### 问题 4：命令执行权限不足

**解决**：部分系统命令需要 sudo 权限。对于演示目的，大部分查询类命令不需要特殊权限。

---

## 清理临时数据

如果需要清理会话和审计数据：

```bash
cd /mnt/d/AI比赛/langgraph_os_agent
rm -rf sessions/
rm -f audit.db
```
