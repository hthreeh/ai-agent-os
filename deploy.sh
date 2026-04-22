#!/bin/bash

echo "========================================="
echo " 操作系统智能代理 - Ubuntu 部署脚本"
echo "========================================="

echo "[1/5] 更新系统包..."
sudo apt update -y

echo "[2/5] 安装Python和依赖..."
sudo apt install -y python3 python3-pip python3-venv

echo "[3/5] 创建虚拟环境..."
python3 -m venv venv
source venv/bin/activate

echo "[4/5] 安装Python依赖..."
pip install -r requirements.txt

echo "[5/5] 检查配置文件..."
if [ ! -f .env ]; then
    echo "创建.env配置文件..."
    cp .env.example .env
    echo "请编辑 .env 文件并填入您的OpenAI API密钥"
fi

echo ""
echo "========================================="
echo " 部署完成！"
echo "========================================="
echo ""
echo "启动服务："
echo "  source venv/bin/activate"
echo "  python src/main.py web"
echo ""
echo "访问地址："
echo "  http://localhost:8000"
echo "  http://localhost:8000/docs (API文档)"
echo ""
