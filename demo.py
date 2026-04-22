import sys
import os

# 添加项目根目录到Python路径
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from src.agent_workflow import build_workflow

def demo():
    print("操作系统智能代理演示")
    print("==================")
    
    # 构建工作流
    workflow = build_workflow()
    
    # 测试用例
    test_cases = [
        "查询磁盘使用情况",
        "查看系统信息",
        "查看进程状态",
        "查看端口状态",
        "创建用户 testuser",
        "删除用户 testuser",
        "搜索文件: *.py"
    ]
    
    for i, test_case in enumerate(test_cases):
        print(f"\n测试用例 {i+1}: {test_case}")
        print("-" * 50)
        
        try:
            # 运行工作流
            result = workflow.invoke({
                "user_input": test_case
            })
            
            # 显示结果
            print("响应:")
            print(result["response"])
            print("\n执行结果:")
            print(result["execution_result"])
        except Exception as e:
            print(f"错误: {str(e)}")
        
        print("=" * 50)

if __name__ == "__main__":
    demo()
