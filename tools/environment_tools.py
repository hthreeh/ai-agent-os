import platform
import os
import subprocess
import re
import shutil

class EnvironmentTools:
    @staticmethod
    def _run_command(args, timeout=3):
        """执行系统命令并限制超时，避免环境探测阻塞主流程。"""
        return subprocess.run(args, capture_output=True, text=True, check=True, timeout=timeout)

    @staticmethod
    def get_os_info():
        """获取操作系统信息"""
        os_info = {
            "system": platform.system(),
            "release": platform.release(),
            "version": platform.version(),
            "machine": platform.machine(),
            "processor": platform.processor()
        }
        
        # 尝试获取更详细的发行版信息
        if os_info["system"] == "Linux":
            if os.path.exists("/etc/os-release"):
                with open("/etc/os-release", "r") as f:
                    for line in f:
                        if "=" in line:
                            key, value = line.strip().split("=", 1)
                            if value.startswith("\"") and value.endswith("\""):
                                value = value[1:-1]
                            os_info[key.lower()] = value
            elif os.path.exists("/etc/redhat-release"):
                with open("/etc/redhat-release", "r") as f:
                    os_info["redhat_release"] = f.read().strip()
        elif os_info["system"] == "Windows":
            try:
                result = EnvironmentTools._run_command(["systeminfo"], timeout=8)
                for line in result.stdout.split("\n"):
                    if "OS Name:" in line:
                        os_info["os_name"] = line.split(":", 1)[1].strip()
                    elif "OS Version:" in line:
                        os_info["os_version"] = line.split(":", 1)[1].strip()
                    elif "System Type:" in line:
                        os_info["system_type"] = line.split(":", 1)[1].strip()
            except Exception:
                pass
        
        return os_info
    
    @staticmethod
    def get_hardware_info():
        """获取硬件信息"""
        hardware_info = {}
        
        if platform.system() == "Linux":
            # 获取CPU信息
            try:
                with open("/proc/cpuinfo", "r") as f:
                    for line in f:
                        if "model name" in line:
                            hardware_info["cpu_model"] = line.split(":", 1)[1].strip()
                            break
            except Exception:
                pass
            
            # 获取内存信息
            try:
                with open("/proc/meminfo", "r") as f:
                    for line in f:
                        if "MemTotal" in line:
                            hardware_info["memory_total"] = line.split(":", 1)[1].strip()
                            break
            except Exception:
                pass
        elif platform.system() == "Windows":
            # 获取CPU信息
            try:
                result = EnvironmentTools._run_command(["wmic", "cpu", "get", "name"], timeout=5)
                lines = result.stdout.strip().split("\n")
                if len(lines) > 1:
                    hardware_info["cpu_model"] = lines[1].strip()
            except Exception:
                pass
            
            # 获取内存信息
            try:
                result = EnvironmentTools._run_command(["wmic", "OS", "get", "TotalVisibleMemorySize"], timeout=5)
                lines = result.stdout.strip().split("\n")
                if len(lines) > 1:
                    memory_kb = int(lines[1].strip())
                    memory_gb = memory_kb / (1024 * 1024)
                    hardware_info["memory_total"] = f"{memory_gb:.2f} GB"
            except Exception:
                pass
        
        return hardware_info
    
    @staticmethod
    def get_software_info():
        """获取软件信息"""
        software_info = {}
        
        # 获取Python版本
        software_info["python_version"] = platform.python_version()
        
        if platform.system() == "Linux":
            # 获取包管理器信息
            package_managers = {
                "apt": "apt --version",
                "yum": "yum --version",
                "dnf": "dnf --version",
                "pacman": "pacman --version"
            }
            
            for pm, cmd in package_managers.items():
                try:
                    binary = cmd.split()[0]
                    if not shutil.which(binary):
                        continue
                    result = EnvironmentTools._run_command(cmd.split(), timeout=2)
                    software_info[f"{pm}_version"] = result.stdout.strip().split("\n")[0]
                except Exception:
                    pass
        
        return software_info
    
    @staticmethod
    def get_network_info():
        """获取网络信息"""
        network_info = {}
        
        if platform.system() == "Linux":
            # 获取IP地址
            try:
                if not shutil.which("ip"):
                    return network_info
                result = EnvironmentTools._run_command(["ip", "addr"], timeout=3)
                ip_pattern = re.compile(r'inet\s+(\d+\.\d+\.\d+\.\d+)/\d+')
                ips = ip_pattern.findall(result.stdout)
                network_info["ip_addresses"] = ips
            except Exception:
                pass
        elif platform.system() == "Windows":
            # 获取IP地址
            try:
                result = EnvironmentTools._run_command(["ipconfig"], timeout=5)
                ip_pattern = re.compile(r'IPv4 Address\.\.\.\.\.\.\.\.\.\. : (\d+\.\d+\.\d+\.\d+)')
                ips = ip_pattern.findall(result.stdout)
                network_info["ip_addresses"] = ips
            except Exception:
                pass
        
        return network_info
    
    @staticmethod
    def get_environment_summary():
        """获取环境信息摘要"""
        summary = {
            "os": EnvironmentTools.get_os_info(),
            "hardware": EnvironmentTools.get_hardware_info(),
            "software": EnvironmentTools.get_software_info(),
            "network": EnvironmentTools.get_network_info()
        }
        return summary
    
    @staticmethod
    def detect_os_type():
        """检测操作系统类型"""
        os_info = EnvironmentTools.get_os_info()
        system = os_info.get("system", "").lower()
        
        if system == "linux":
            if "ubuntu" in os_info.get("name", "").lower():
                return "ubuntu"
            elif "centos" in os_info.get("name", "").lower() or "red hat" in os_info.get("redhat_release", "").lower():
                return "centos"
            elif "openeuler" in os_info.get("name", "").lower():
                return "openeuler"
            elif "debian" in os_info.get("name", "").lower():
                return "debian"
            else:
                return "linux"
        elif system == "windows":
            return "windows"
        else:
            return "other"
    
    @staticmethod
    def get_recommended_commands(os_type):
        """获取推荐的命令"""
        system = platform.system().lower()
        is_windows = system == "windows" or os_type == "windows"

        def pick(first_available, fallback):
            for cmd in first_available:
                if shutil.which(cmd):
                    return cmd
            return fallback

        disk_cmd = "wmic logicaldisk get size,freespace,caption" if is_windows else "df -h"
        process_cmd = "tasklist" if is_windows else "ps aux"
        port_binary = "netstat" if is_windows else pick(["ss", "netstat"], "ss")
        port_cmd = "netstat -ano" if is_windows else (f"{port_binary} -tuln")
        create_user_cmd = "net user /add" if is_windows else pick(["useradd", "adduser"], "useradd")
        delete_user_cmd = "net user /delete" if is_windows else "userdel"

        return {
            "disk_usage": disk_cmd,
            "process_status": process_cmd,
            "port_status": port_cmd,
            "create_user": create_user_cmd,
            "delete_user": delete_user_cmd
        }
