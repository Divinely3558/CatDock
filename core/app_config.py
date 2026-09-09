#!/usr/bin/env python3
"""app_config - 全局配置与运行时状态

集中管理：
  - 文件路径常量
  - 全局可变状态（tasks / video_groups / 各功能开关）
  - load_config() 加载系统级环境变量（docker-compose.yml）+ 过滤规则 filter_rules.json
    + 管理员热配置 admin_config.json（auth_key）
  - 安全相关常量（SSRF 网段、限流、请求体上限、脱敏表）

其它模块统一 `import app_config as cfg` 后用 cfg.xxx 访问，
避免跨模块 global 与循环依赖。
"""
import os
import json
import re
import secrets
import threading
import ipaddress

# 时区固定为东八区（北京时间），需在任何 time.strftime 之前设置
os.environ['TZ'] = 'Asia/Shanghai'
import time
time.tzset()

import data_db

# ---- 文件路径 ----
DOWNLOAD_DIR = "/home/downloader/downloads"
TEMP_DIR = "/home/downloader/temp"
# 每用户配置根目录（独立挂载卷 /home/downloader/user，容器重建后保留）：
# user/<名>/ 下存放该用户的 tasks.json、success.log、failure.log、filter_rules.json
USER_DIR = "/home/downloader/user"
FFMPEG_PATH = "/usr/bin/ffmpeg"
N_M3U8DL = "/home/downloader/N_m3u8DL-RE"
# 系统配置目录（挂载卷 /home/downloader/config）：data.db、admin_config.json、
# filter_rules.json 均存放在此；系统级开关（URL_PREFIX/API_PORT/DEBUG 等）
# 全部由 docker-compose.yml 环境变量提供，不再读取 config.json
CONFIG_DIR = "/home/downloader/config"
# admin_config.json：用户管理员可热更新的配置（auth_key），
# 与系统级环境变量分离——普通管理员无权修改系统配置
ADMIN_CONFIG_FILE = os.path.join(CONFIG_DIR, 'admin_config.json')
# 全局 filter_rules.json 仅作为新用户首启的过滤规则模板；
# 下载用户实际读取 user/<名>/filter_rules.json（各自独立）
FILTER_RULES_FILE = os.path.join(CONFIG_DIR, 'filter_rules.json')
# 调试模式运行时状态文件（/tmp 非挂载卷，容器重启即清空）：
# debug 命令经 SIGUSR1/SIGUSR2 通知服务切换后写此文件，供 CLI 查询当前状态
DEBUG_STATE_FILE = '/tmp/catdock_debug.state'


def user_config_dir(username):
    """用户配置目录：/home/downloader/user/<用户名>"""
    return os.path.join(USER_DIR, username)


def user_tasks_file(username):
    return os.path.join(user_config_dir(username), 'tasks.json')


def user_success_log(username):
    return os.path.join(user_config_dir(username), 'success.log')


def user_failure_log(username):
    return os.path.join(user_config_dir(username), 'failure.log')


def user_filter_rules_file(username):
    return os.path.join(user_config_dir(username), 'filter_rules.json')


def user_temp_dir(username):
    """用户下载缓存目录：/home/downloader/temp/<用户名>"""
    return os.path.join(TEMP_DIR, username)

# ---- 文件大小阈值 ----
MIN_FILE_SIZE = 102400      # 最小有效文件大小（100KB）
MIN_FILE_SIZE_SMALL = 1024  # 小文件检测阈值（1KB）

# ---- 任务状态 ----
tasks = {}
tasks_lock = threading.RLock()
last_save_time = 0

# ---- 过滤/功能开关（load_config 填充）----
ad_keywords = []
keywords_enabled = False
filename_filters = []
filename_filter_enabled = False
filename_dedup_enabled = False
filename_dedup_rules = []
# 输出格式默认 mp4；用户可逐任务在网页/猫抓插件请求体中指定 format=mp4|mkv
output_format = "mp4"
auth_key = ""
url_prefix = ""
server_port = 8080
bound_port = None      # 实际监听端口（启动绑定后不变，/reload 改端口需重启容器）
debug_mode = False
same_video_by_filename_enabled = False
ssrf_protection = True
max_concurrent_tasks = 20
# 版本号：来自 web/version 文件（镜像构建时拷入），空则显示「未知」
version = ""

# ---- same_video_by_filename 模式内存结构 ----
# key: base_name (过滤后的标准文件名)
# value: dict -> {'task_id', 'urls', 'current_index', 'round_count', 'status'}
video_groups = {}
video_groups_lock = threading.RLock()

server_instance = None

# ---- 日志中需要脱敏的 URL 查询参数名 ----
_SENSITIVE_URL_PARAMS = (
    'token', 'sign', 'signature', 'key', 'auth', 'auth_key', 'password',
    'passwd', 'secret', 'api_key', 'apikey', 'access_key', 'access_token',
    'refresh_token', 'session', 'session_id', 'sid', 'cookie', 'authorization',
)

# ---- 安全：速率限制（每个 IP 在窗口内最大请求数）----
RATE_LIMIT_MAX = 60
RATE_LIMIT_WINDOW = 60
rate_limit_dict = {}      # {ip: [timestamp, ...]}
rate_limit_lock = threading.Lock()

# 请求体最大字节数
MAX_CONTENT_LENGTH = 1 * 1024 * 1024  # 1MB

# 文件名非法字符→'_' 的转换表（_get_sanitized_param 使用）
_SANITIZE_TABLE = str.maketrans({
    ' ': '_', '　': '_', '/': '_', '\\': '_', ':': '_', '*': '_', '?': '_',
    '"': '_', '<': '_', '>': '_', '|': '_', '\t': '_', '\n': '_', '\r': '_',
})

# SSRF 防护：禁止的私有/保留 IP 段
_BLOCKED_NETWORKS = [
    ipaddress.ip_network('0.0.0.0/8'),
    ipaddress.ip_network('10.0.0.0/8'),
    ipaddress.ip_network('100.64.0.0/10'),
    ipaddress.ip_network('127.0.0.0/8'),
    ipaddress.ip_network('169.254.0.0/16'),
    ipaddress.ip_network('172.16.0.0/12'),
    ipaddress.ip_network('192.0.0.0/24'),
    ipaddress.ip_network('192.0.2.0/24'),
    ipaddress.ip_network('192.168.0.0/16'),
    ipaddress.ip_network('198.18.0.0/15'),
    ipaddress.ip_network('198.51.100.0/24'),
    ipaddress.ip_network('203.0.113.0/24'),
    ipaddress.ip_network('224.0.0.0/4'),
    ipaddress.ip_network('240.0.0.0/4'),
    ipaddress.ip_network('::1/128'),
    ipaddress.ip_network('fc00::/7'),
    ipaddress.ip_network('fe80::/10'),
]

# /tasks 响应中需要隐藏的敏感字段
# _proc: subprocess.Popen 对象（不可 JSON 序列化，会导致 send_json 失败）
# _download_dir: per-user 下载目录路径（隐私敏感）
_SENSITIVE_TASK_FIELDS = ('_referer', '_cookie', '_user_agent', '_proc', '_download_dir')


def load_filters():
    """从 filter_rules.json 加载过滤规则（启动与 /reload 共用）。

    注意：本函数内部惰性导入 app_logger，以避免 app_config <-> app_logger
    的顶层循环导入（app_logger 顶层会 import app_config）。
    """
    from app_logger import log_info, log_error, debug_print

    ad_keywords = []
    keywords_enabled = False
    filename_filters = []
    filename_filter_enabled = False
    filename_dedup_enabled = False
    filename_dedup_rules = []
    filter_config = {}

    try:
        with open(FILTER_RULES_FILE, 'r', encoding='utf-8-sig') as f:
            filter_config = json.load(f)

        keywords_config = filter_config.get('keywords', {})
        keywords_enabled = keywords_config.get('enabled', True)
        ad_keywords = keywords_config.get('list', []) if keywords_enabled else []

        filter_config_obj = filter_config.get('filename_filter', {})
        filename_filter_enabled = filter_config_obj.get('enabled', True)
        filename_filters = filter_config_obj.get('list', []) if filename_filter_enabled else []

        dedup_config = filter_config.get('filename_dedup', {})
        filename_dedup_enabled = dedup_config.get('enabled', False)
        dedup_rules_raw = dedup_config.get('rules', [])
        if filename_dedup_enabled and dedup_rules_raw:
            for rule in dedup_rules_raw:
                pattern_str = rule.get('pattern', '')
                replacement = rule.get('replacement', '')
                if pattern_str:
                    try:
                        compiled = re.compile(pattern_str)
                        filename_dedup_rules.append((compiled, replacement))
                    except re.error as e:
                        log_info(f"文件名去重正则编译失败 [{pattern_str}]: {e}")

        debug_print(f"[启动] 过滤规则加载: 拦截关键字 {'启用' if keywords_enabled else '禁用'} ({len(ad_keywords)} 个), "
                    f"文件名过滤 {'启用' if filename_filter_enabled else '禁用'} ({len(filename_filters)} 个), "
                    f"文件名去重 {'启用' if filename_dedup_enabled else '禁用'} ({len(filename_dedup_rules)} 条正则规则)")
    except Exception as e:
        log_error(f"过滤规则加载失败: {e}")
        ad_keywords = []
        keywords_enabled = False
        filename_filters = []
        filename_filter_enabled = False
        filename_dedup_rules = []

    globals().update({
        'ad_keywords': ad_keywords,
        'keywords_enabled': keywords_enabled,
        'filename_filters': filename_filters,
        'filename_filter_enabled': filename_filter_enabled,
        'filename_dedup_enabled': filename_dedup_enabled,
        'filename_dedup_rules': filename_dedup_rules,
        'filters_raw': filter_config,
    })


def load_version():
    """读取版本号（web/VERSION 文件），写入模块全局 version。

    查找顺序：同目录（容器内平铺布局）→ ../web/（仓库源码布局）。
    文件不存在或内容为空时，version 保持空字符串，由调用方决定显示文案。
    """
    global version
    base = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.join(base, 'VERSION'),
        os.path.join(base, '..', 'web', 'VERSION'),
    ]
    for p in candidates:
        if os.path.isfile(p):
            try:
                with open(p, 'r', encoding='utf-8') as f:
                    v = f.read().strip()
                if v:
                    version = v
                    return
            except Exception:
                pass
    version = ""


def _env_flag(name, default=False):
    """读取布尔型环境变量：true/1/yes/on 为真，false/0/no/off 为假；
    未设置或值无法识别时返回 default。"""
    val = os.environ.get(name, '').strip().lower()
    if val in ('true', '1', 'yes', 'on'):
        return True
    if val in ('false', '0', 'no', 'off'):
        return False
    return default


def write_debug_state(enabled):
    """将调试模式当前状态写入运行时状态文件（/tmp，重启即清空）。

    由服务进程在启动重置与 SIGUSR1/SIGUSR2 信号处理时调用；
    写入失败不影响调试开关本身（内存状态为准）。
    """
    try:
        with open(DEBUG_STATE_FILE, 'w', encoding='utf-8') as f:
            f.write('on' if enabled else 'off')
    except OSError:
        pass


def read_debug_state():
    """读取调试模式运行时状态；状态文件不存在/不可读时视为关闭。"""
    try:
        with open(DEBUG_STATE_FILE, 'r', encoding='utf-8') as f:
            return f.read().strip().lower() == 'on'
    except OSError:
        return False


def load_config():
    """加载系统级配置（环境变量）、过滤规则与管理员热配置。

    配置分层约定：
      - 环境变量          系统级配置（URL_PREFIX/API_PORT/SAME_VIDEO_BY_FILENAME/
                          SSRF_PROTECTION/MAX_CONCURRENT_TASKS），在 docker-compose.yml
                          中配置，修改后重启容器生效，/reload 不读取；
      - 调试模式          运行时开关（不持久化），容器内 `debug yes/no` 命令经
                          SIGUSR1/SIGUSR2 信号即时切换，重启后恢复默认关闭；
      - admin_config.json 用户管理员可热更新的配置（auth_key），
                          管理网页修改即时写回并生效；
      - filter_rules.json 过滤规则，/reload 热加载。
    """
    from app_logger import debug_print

    # 版本号（web/VERSION），与系统配置无关，仅用于展示一致性
    load_version()

    # 系统级配置一律来自环境变量（本函数内全部使用局部变量，末尾 globals().update 一次性写回）
    # URL_PREFIX：规范化去首尾空格与斜杠，避免值带尾斜杠导致所有请求 404 并累积封禁计数
    url_prefix = os.environ.get('URL_PREFIX', '').strip().strip('/')
    # 监听端口：main.py 读取 API_PORT 环境变量，未设置时用此默认值
    server_port = 8080
    # 调试模式为纯运行时开关：每次启动重置为关闭，并刷新 /tmp 状态文件
    # （运行期由 debug 命令经 SIGUSR1/SIGUSR2 切换，不读环境变量、不持久化）
    debug_mode = False
    write_debug_state(False)
    same_video_by_filename_enabled = _env_flag('SAME_VIDEO_BY_FILENAME', False)
    ssrf_protection = _env_flag('SSRF_PROTECTION', True)

    # 最大并发下载任务数：未设置或非法时回退默认 20
    max_concurrent_tasks = 20
    env_max = os.environ.get('MAX_CONCURRENT_TASKS', '').strip()
    if env_max.isdigit() and int(env_max) > 0:
        max_concurrent_tasks = int(env_max)

    debug_print(f"[启动] 系统配置(环境变量): 同视频模式={'启用' if same_video_by_filename_enabled else '关闭'}, "
                f"SSRF防护={'启用' if ssrf_protection else '关闭'}, 最大并发={max_concurrent_tasks}；"
                f"调试模式运行时开关(debug yes/no)，当前关闭")

    # 安全校验：URL_PREFIX 必须设置（AUTH_KEY 为空时由 main.py 首启自动生成并写回）
    if not url_prefix:
        raise RuntimeError("URL_PREFIX 未设置，请在 docker-compose.yml 环境变量中指定")

    # 把加载结果写回模块属性（load_config 内的局部变量 -> 全局状态）
    globals().update({
        'url_prefix': url_prefix,
        'server_port': server_port,
        'debug_mode': debug_mode,
        'same_video_by_filename_enabled': same_video_by_filename_enabled,
        'ssrf_protection': ssrf_protection,
        'max_concurrent_tasks': max_concurrent_tasks,
    })

    # 数据库路径：config 目录下（data.db 承载封禁 IP + 用户）
    data_db.set_db_path(os.path.join(CONFIG_DIR, 'data.db'))

    # 过滤规则（filter_rules.json）与管理员热配置（admin_config.json：
    # auth_key，普通管理员可经管理网页热更新）
    load_filters()
    load_admin_config()


# admin_config.json 中 auth_key 占位符：entrypoint 从 admin_config.example.json
# 复制后，首启检测到该占位符即自动生成随机密钥写回
AUTH_KEY_PLACEHOLDER = 'CHANGE_ME'


def _read_admin_dict():
    """读取 admin_config.json 为 dict；文件不存在/损坏/不可读时返回空 dict。"""
    try:
        with open(ADMIN_CONFIG_FILE, 'r', encoding='utf-8-sig') as f:
            loaded = json.load(f)
        return loaded if isinstance(loaded, dict) else {}
    except Exception:
        return {}


def _write_json_atomic(path, obj, mode=0o600):
    """JSON 原子写入：临时文件 + fsync + os.replace，异常时清理残留。"""
    tmp_path = path + '.tmp'
    fd = os.open(tmp_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(obj, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except Exception:
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except OSError:
            pass
        raise


def load_admin_config():
    """从 admin_config.json 加载用户管理员可热更新的配置（auth_key）。

    文件缺失或 auth_key 为空/占位符时：保留内存中的现有密钥（首启为空，
    由 main.py 检测后生成随机密钥写回），避免 /reload 期间文件异常导致认证被置空。
    """
    global auth_key

    admin = _read_admin_dict()

    current_key = str(admin.get('auth_key', '') or '')
    if (not current_key or current_key == AUTH_KEY_PLACEHOLDER) \
            and auth_key and auth_key != AUTH_KEY_PLACEHOLDER:
        # 文件缺失/损坏/占位符时沿用内存中的现有密钥，认证不中断
        current_key = auth_key

    auth_key = current_key


def generate_random_key(nbytes=24):
    """生成随机密钥（URL 安全字符，约 nbytes*4/3 长度），用于首启 AUTH_KEY 自动生成"""
    return secrets.token_urlsafe(nbytes)


def save_auth_key(new_key):
    """将新 AUTH_KEY 原子写回 admin_config.json（保留其他字段），并更新内存状态。

    管理网页修改 AUTH_KEY 与首启自动生成共用此入口；调用方负责令牌吊销。
    """
    global auth_key
    from app_logger import debug_print
    admin = _read_admin_dict()
    admin['auth_key'] = new_key
    # 含认证密钥：文件权限限制为仅所有者可读写（0600）
    _write_json_atomic(ADMIN_CONFIG_FILE, admin, mode=0o600)
    auth_key = new_key
    debug_print(f"[启动] AUTH_KEY 已写回配置文件: {ADMIN_CONFIG_FILE}")
