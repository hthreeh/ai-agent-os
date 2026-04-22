import sys
import os

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def main():
    if len(sys.argv) > 1 and sys.argv[1] == "web":
        import uvicorn
        
        host = "0.0.0.0"
        port = 8000
        
        if "--host" in sys.argv:
            host_idx = sys.argv.index("--host")
            if host_idx + 1 < len(sys.argv):
                host = sys.argv[host_idx + 1]
        
        if "--port" in sys.argv:
            port_idx = sys.argv.index("--port")
            if port_idx + 1 < len(sys.argv):
                port = int(sys.argv[port_idx + 1])
        
        print("=" * 60)
        print("  操作系统智能代理 - Web服务")
        print("=" * 60)
        print(f"  访问地址: http://{host}:{port}")
        print(f"  API文档: http://{host}:{port}/docs")
        print("=" * 60)
        
        from src.web_api import app
        uvicorn.run(app, host=host, port=port)
    else:
        from src.cli import CLI
        cli = CLI()
        cli.run()

if __name__ == "__main__":
    main()
