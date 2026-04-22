import glob
import os
import platform
import re
import shlex
import subprocess


class SystemTools:
    SHELL_CONTROL_TOKENS = ("&&", "||", "|", ";", ">", "<", "$(", "`")

    @staticmethod
    def _prepare_command(command):
        if isinstance(command, (list, tuple)):
            return list(command)

        if not isinstance(command, str):
            raise TypeError("command must be a string or a sequence")

        candidate = command.strip()
        if not candidate:
            raise ValueError("command must not be empty")

        if platform.system() == "Windows":
            return ["powershell", "-NoProfile", "-Command", candidate]

        if any(token in candidate for token in SystemTools.SHELL_CONTROL_TOKENS):
            return ["/bin/bash", "-lc", candidate]

        return shlex.split(candidate)

    @staticmethod
    def _run_command(command, timeout: int = 30) -> dict:
        """Execute a command and return exit_code/stdout/stderr."""
        result = subprocess.run(
            SystemTools._prepare_command(command),
            shell=False,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False
        )
        return {
            "exit_code": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr
        }

    @staticmethod
    def _run(command, timeout=30):
        """Unified command execution entry point."""
        result = subprocess.run(
            SystemTools._prepare_command(command),
            shell=False,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False
        )
        if result.returncode != 0:
            stderr = result.stderr.strip() or "Unknown error"
            return f"Error ({result.returncode}): {stderr}"
        return result.stdout

    @staticmethod
    def _is_safe_username(username: str) -> bool:
        return bool(re.fullmatch(r"[a-zA-Z_][a-zA-Z0-9_-]{0,31}", username or ""))

    @staticmethod
    def get_disk_usage():
        try:
            if platform.system() == "Windows":
                return SystemTools._run(["wmic", "logicaldisk", "get", "size,freespace,caption"])
            return SystemTools._run(["df", "-h"])
        except Exception as e:
            return f"Error: {str(e)}"

    @staticmethod
    def search_files(directory, pattern):
        try:
            normalized_directory = os.path.abspath(directory or ".")
            if not os.path.isdir(normalized_directory):
                return f"Error: Directory not found: {normalized_directory}"

            normalized_pattern = pattern or "*"
            matches = glob.glob(os.path.join(normalized_directory, "**", normalized_pattern), recursive=True)
            if not matches:
                return f"No files matched pattern '{normalized_pattern}' in {normalized_directory}"

            preview = matches[:200]
            suffix = "\n...truncated..." if len(matches) > 200 else ""
            return "\n".join(preview) + suffix
        except Exception as e:
            return f"Error: {str(e)}"

    @staticmethod
    def get_process_status():
        try:
            if platform.system() == "Windows":
                return SystemTools._run(["tasklist"])
            return SystemTools._run(["ps", "aux"])
        except Exception as e:
            return f"Error: {str(e)}"

    @staticmethod
    def get_port_status():
        try:
            if platform.system() == "Windows":
                return SystemTools._run(["netstat", "-ano"])

            output = SystemTools._run(["ss", "-tuln"])
            if not output.startswith("Error"):
                return output
            return SystemTools._run(["netstat", "-tuln"])
        except Exception as e:
            return f"Error: {str(e)}"

    @staticmethod
    def create_user(username, password=None):
        try:
            if not SystemTools._is_safe_username(username):
                return "Error: Invalid username format."

            if platform.system() == "Windows":
                if password:
                    result = SystemTools._run(["net", "user", username, password, "/add"])
                else:
                    result = SystemTools._run(["net", "user", username, "/add"])
            else:
                result = SystemTools._run(["useradd", username])
                if password:
                    pw_res = subprocess.run(
                        ["chpasswd"],
                        input=f"{username}:{password}",
                        capture_output=True,
                        text=True,
                        timeout=30,
                        check=False
                    )
                    if pw_res.returncode != 0:
                        return f"Error ({pw_res.returncode}): {pw_res.stderr.strip() or 'chpasswd failed'}"
            if isinstance(result, str) and result.startswith("Error"):
                return result
            return f"User {username} created successfully"
        except Exception as e:
            return f"Error: {str(e)}"

    @staticmethod
    def delete_user(username):
        try:
            if not SystemTools._is_safe_username(username):
                return "Error: Invalid username format."

            if platform.system() == "Windows":
                result = SystemTools._run(["net", "user", username, "/delete"])
            else:
                result = SystemTools._run(["userdel", username])
            if isinstance(result, str) and result.startswith("Error"):
                return result
            return f"User {username} deleted successfully"
        except Exception as e:
            return f"Error: {str(e)}"

    @staticmethod
    def get_os_info():
        try:
            if platform.system() == "Windows":
                output = SystemTools._run(["systeminfo"])
                return output[:2000]

            os_info = SystemTools._run(["uname", "-a"])
            if os.path.exists("/etc/os-release"):
                with open("/etc/os-release", "r", encoding="utf-8") as f:
                    os_info += "\n" + f.read()
            return os_info
        except Exception as e:
            return f"Error: {str(e)}"
