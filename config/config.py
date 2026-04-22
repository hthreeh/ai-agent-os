import os
from dotenv import load_dotenv

# 鍔犺浇鐜鍙橀噺
load_dotenv()


def _get_bool_env(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "")

_cors_origins = os.getenv("CORS_ALLOWED_ORIGINS", "http://localhost,http://127.0.0.1")
CORS_ALLOWED_ORIGINS = [
    origin.strip() for origin in _cors_origins.split(",") if origin.strip()
]
ALLOW_ALL_CORS = _get_bool_env("ALLOW_ALL_CORS", False)
ALLOW_RAW_SHELL_FALLBACK = _get_bool_env("ALLOW_RAW_SHELL_FALLBACK", False)

# 绯荤粺閰嶇疆
DEFAULT_TIMEOUT = 30
MAX_RETRIES = 3

# 瀹夊叏閰嶇疆
HIGH_RISK_COMMANDS = [
    "rm -rf",
    "format",
    "dd if=",
    "userdel -r",
    "groupdel",
    "chmod 777",
    "chown root",
    "mkfs",
    "fdisk",
    "parted",
    "rm -f",
    "chmod 666",
    "chmod 775",
    "chown nobody",
    "rmdir -p",
    "shutdown -r",
    "reboot",
    "halt",
    "poweroff",
    "init 0",
    "init 6",
    "sysctl -w",
    "echo >",
    "echo >>",
    "cat >",
    "cat >>",
    "sed -i",
    "awk -i",
    "rm -rf /",
    "rm -rf /etc",
    "rm -rf /usr",
    "rm -rf /var",
    "rm -rf /home",
    "dd if=/dev/zero",
    "dd if=/dev/random",
    "dd if=/dev/urandom"
]

# 鐜妫€娴嬮厤缃?
SUPPORTED_OS = ["ubuntu", "centos", "openeuler", "debian"]
