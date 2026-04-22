import paramiko
import time

class SSHConnection:
    def __init__(self, host, port, username, password=None, key_path=None):
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.key_path = key_path
        self.client = None
    
    def connect(self):
        try:
            self.client = paramiko.SSHClient()
            self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            
            if self.key_path:
                self.client.connect(
                    self.host,
                    port=self.port,
                    username=self.username,
                    key_filename=self.key_path,
                    timeout=30
                )
            elif self.password:
                self.client.connect(
                    self.host,
                    port=self.port,
                    username=self.username,
                    password=self.password,
                    timeout=30
                )
            else:
                raise ValueError("Either password or key_path must be provided")
            
            return True
        except Exception as e:
            raise Exception(f"SSH连接失败: {str(e)}")
    
    def execute_command(self, command, timeout=30):
        if not self.client:
            raise Exception("未建立SSH连接")
        
        try:
            stdin, stdout, stderr = self.client.exec_command(command, timeout=timeout)
            
            exit_code = stdout.channel.recv_exit_status()
            stdout_data = stdout.read().decode('utf-8', errors='replace')
            stderr_data = stderr.read().decode('utf-8', errors='replace')
            
            return {
                "exit_code": exit_code,
                "stdout": stdout_data,
                "stderr": stderr_data
            }
        except Exception as e:
            raise Exception(f"命令执行失败: {str(e)}")
    
    def close(self):
        if self.client:
            self.client.close()
    
    def __enter__(self):
        self.connect()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

class SSHSystemTools:
    @staticmethod
    def get_disk_usage(ssh_conn):
        result = ssh_conn.execute_command("df -h")
        return result
    
    @staticmethod
    def search_files(ssh_conn, directory, pattern):
        result = ssh_conn.execute_command(f"find {directory} -name '{pattern}'")
        return result
    
    @staticmethod
    def get_process_status(ssh_conn):
        result = ssh_conn.execute_command("ps aux")
        return result
    
    @staticmethod
    def get_port_status(ssh_conn):
        result = ssh_conn.execute_command("netstat -tuln")
        return result
    
    @staticmethod
    def create_user(ssh_conn, username, password=None):
        if password:
            result1 = ssh_conn.execute_command(f"useradd {username}")
            result2 = ssh_conn.execute_command(f"echo '{username}:{password}' | chpasswd")
            return result2
        else:
            result = ssh_conn.execute_command(f"useradd {username}")
            return result
    
    @staticmethod
    def delete_user(ssh_conn, username):
        result = ssh_conn.execute_command(f"userdel {username}")
        return result
    
    @staticmethod
    def get_os_info(ssh_conn):
        result1 = ssh_conn.execute_command("uname -a")
        result2 = ssh_conn.execute_command("cat /etc/os-release")
        return {
            "stdout": result1["stdout"] + "\n" + result2["stdout"],
            "stderr": result1["stderr"] + "\n" + result2["stderr"],
            "exit_code": result1["exit_code"] if result1["exit_code"] != 0 else result2["exit_code"]
        }
