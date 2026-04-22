# 操作系统智能代理

基于LangGraph架构的操作系统智能代理，通过自然语言交互实现Linux服务器的智能管理。

## 项目亮点

- 🤖 **AI驱动**: 基于OpenAI大语言模型的意图理解和响应生成
- 🛡️ **安全优先**: 多层风险控制机制，自动拦截高风险操作
- 🔄 **连续任务**: 支持多步骤任务自动编排和执行
- 🌍 **环境感知**: 自动识别操作系统类型并生成适配命令
- 💬 **对话交互**: 支持多轮对话，保持上下文连贯性
- 🌐 **Web界面**: 内置美观的Web聊天界面，支持远程访问

## 快速开始

### 本地运行

```bash
# 安装依赖
pip install -r requirements.txt

# 配置API密钥
cp .env.example .env
# 编辑.env文件，填入OpenAI API密钥

# 启动CLI
python -m src.main

# 启动Web服务
python -m src.main web

# 指定地址和端口
python -m src.main web --host 0.0.0.0 --port 8000
```

### 部署到Ubuntu虚拟机

```bash
# 上传项目到虚拟机
scp -r langgraph_os_agent/ user@<IP>:/home/user/

# 在虚拟机中运行部署脚本
ssh user@<IP>
cd langgraph_os_agent
chmod +x deploy.sh
./deploy.sh

# 启动服务
source venv/bin/activate
python -m src.main web --host 0.0.0.0 --port 8000
```

## 使用示例

### 基础功能
- "查询磁盘使用情况"
- "查看系统信息"
- "查看当前运行的进程"
- "查看开放的端口"

### 文件搜索
- "搜索 /etc 目录下的所有 .conf 文件"
- "查找 /home 目录中的 .txt 文件"

### 用户管理
- "创建一个名为 testuser 的用户"
- "删除用户 testuser"

### 连续任务
- "先查看磁盘使用情况，然后查看进程状态"
- "查看系统信息，然后查看磁盘使用情况，最后查看端口状态"

### 安全测试
- "删除 /etc 目录" （将被拦截）
- "格式化磁盘" （将被拦截）

## 项目结构

```
langgraph_os_agent/
├── config/              # 配置文件
│   └── config.py        # 系统和安全配置
├── src/                 # 核心源代码
│   ├── agent_workflow.py  # LangGraph工作流定义
│   ├── cli.py           # 命令行界面
│   ├── main.py          # 入口程序
│   └── web_api.py       # Web API服务
├── tools/               # 工具模块
│   ├── system_tools.py      # 系统管理工具
│   ├── security_tools.py    # 安全控制工具
│   ├── environment_tools.py # 环境感知工具
│   ├── state_management.py  # 状态管理工具
│   └── ssh_tools.py         # SSH远程连接工具
├── tests/               # 测试文件
├── .env                 # 环境变量配置
├── .env.example         # 环境变量示例
├── requirements.txt     # Python依赖
├── deploy.sh            # Ubuntu部署脚本
└── start.bat            # Windows快速启动
```

## 架构设计

### LangGraph工作流

```
环境检测 → 状态决策 → 意图识别 → 命令生成 → 风险确认 → 命令执行 → 任务检查 → 响应生成
```

### 核心模块

1. **环境检测模块**: 自动识别操作系统类型和环境信息
2. **状态管理模块**: 跟踪系统状态、任务历史和安全事件
3. **意图识别模块**: 使用LLM解析用户意图和提取参数
4. **命令生成模块**: 根据环境和意图生成适配的系统命令
5. **安全控制模块**: 多层风险评估，自动拦截危险操作
6. **任务执行模块**: 带重试机制的命令执行
7. **响应生成模块**: 生成自然语言反馈

### 安全机制

- **高风险命令拦截**: 自动识别并阻止危险命令
- **中等风险确认**: 需要用户二次确认
- **风险评估依据**: 提供详细的风险分析说明
- **操作审计**: 记录所有操作和安全事件

## API文档

启动Web服务后访问 `http://localhost:8000/docs` 查看完整API文档。

### 主要接口

- `POST /api/query` - 发送自然语言请求
- `POST /api/confirm` - 确认高风险操作
- `GET /api/health` - 健康检查
- `GET /api/sessions` - 查看活跃会话

## 技术栈

- **核心框架**: LangGraph
- **语言模型**: OpenAI API
- **Web框架**: FastAPI
- **系统交互**: subprocess
- **SSH连接**: paramiko

## 演示视频录制指南

### 推荐演示顺序

1. **基础功能** (1-2分钟)
   - 查询磁盘使用情况
   - 查看系统信息
   - 查看进程状态

2. **高级功能** (1-2分钟)
   - 文件搜索
   - 连续任务执行

3. **安全特性** (1分钟)
   - 尝试高风险操作（演示拦截）

### 录制建议

- 使用分屏显示：左侧Web界面，右侧终端
- 展示完整交互过程
- 突出风险提示和确认流程

## 许可证

MIT License
