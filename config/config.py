import os
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()


def _get_bool_env(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


# ── API 配置 ────────────────────────────────────────────────
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "")

# ── Web 服务配置 ─────────────────────────────────────────────
_cors_origins = os.getenv("CORS_ALLOWED_ORIGINS", "http://localhost,http://127.0.0.1")
CORS_ALLOWED_ORIGINS = [
    origin.strip() for origin in _cors_origins.split(",") if origin.strip()
]
ALLOW_ALL_CORS = _get_bool_env("ALLOW_ALL_CORS", False)

# ── 功能开关 ─────────────────────────────────────────────────
# 允许原始 shell 命令兜底（存在安全风险，默认关闭）
ALLOW_RAW_SHELL_FALLBACK = _get_bool_env("ALLOW_RAW_SHELL_FALLBACK", False)

# ── 执行配置 ─────────────────────────────────────────────────
DEFAULT_TIMEOUT = 30  # 命令执行超时（秒）
MAX_RETRIES = 3       # 命令重试次数

# ── 安全配置：全局高危命令关键词列表 ────────────────────────────
# 匹配到这些关键词的命令将被直接拦截，不允许执行
HIGH_RISK_COMMANDS = [
    # 文件系统破坏类
    "rm -rf",
    "rm -rf /",
    "rm -rf /etc",
    "rm -rf /usr",
    "rm -rf /var",
    "rm -rf /home",
    "rm -f",
    "rmdir -p",
    # 磁盘操作类
    "format",
    "mkfs",
    "fdisk",
    "parted",
    "dd if=",
    "dd if=/dev/zero",
    "dd if=/dev/random",
    "dd if=/dev/urandom",
    # 用户/组破坏类
    "userdel -r",
    "groupdel",
    # 权限高危类（宽泛权限变更）
    "chmod 777",
    "chmod 666",
    "chmod 775",
    "chown root",
    "chown nobody",
    # 系统关机/重启
    "shutdown -r",
    "reboot",
    "halt",
    "poweroff",
    "init 0",
    "init 6",
    # 内核参数修改
    "sysctl -w",
    # 文件覆盖/追加（可覆盖关键配置）
    "echo >",
    "echo >>",
    "cat >",
    "cat >>",
    # 文件就地修改（高危）
    "sed -i",
    "awk -i",
]

# ── 环境检测配置 ─────────────────────────────────────────────
SUPPORTED_OS = ["ubuntu", "centos", "openeuler", "debian", "linux"]
