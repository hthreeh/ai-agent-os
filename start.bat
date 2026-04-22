@echo off
echo =========================================
echo  操作系统智能代理 - 快速启动
echo =========================================

echo [1/3] 检查虚拟环境...
if not exist venv (
    echo 创建虚拟环境...
    python -m venv venv
)

echo [2/3] 激活虚拟环境...
call venv\Scripts\activate.bat

echo [3/3] 安装依赖...
pip install -r requirements.txt -q

echo.
echo =========================================
echo  启动Web服务...
echo =========================================
echo 访问地址: http://localhost:8000
echo API文档: http://localhost:8000/docs
echo =========================================
echo.

python src\main.py web

pause
