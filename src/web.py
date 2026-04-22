import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if __name__ == "__main__":
    print("注意: 请使用 python src/main.py --mode web 启动服务")
    print("该文件已废弃，请使用 src/web_api.py 作为主入口")
    from src.web_api import app
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
