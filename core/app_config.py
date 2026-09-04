#!/usr/bin/env python3
"""app_config - 全局配置与运行时状态

集中管理：
  - 文件路径常量
  - 全局可变状态（tasks / video_groups / 各功能开关）
  - load_config() 从 config.json / filter_rules.json / 环境变量加载配置
  - 安全相关常量（SSRF 网段、限流、请求体上限、脱敏表）

其它模块统一 `import app_config as cfg` 后用 cfg.xxx 访问，
避免跨模块 global 与循环依赖。
"""
import os
import json
import re
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
FFMPEG_PATH = "/usr/bin/ffmpeg"
N_M3U8DL = "/home/downloader/N_m3u8DL-RE"
CONFIG_FILE = "/home/downloader/config/config.json"
FILTER_RULES_FILE = "/home/downloader/config/filter_rules.json"
TASKS_FILE = "/home/downloader/.data/tasks.json"
LEGACY_TASKS_FILE = "/home/downloader/config/tasks.json"  # 旧版任务文件位置，启动时自动迁移
SUCCESS_LOG_FILE = "/home/downloader/config/success.log"
FAILURE_LOG_FILE = "/home/downloader/config/failure.log"

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
output_format = "mp4"
auth_key = ""
url_prefix = ""
server_port = 8080
bound_port = None      # 实际监听端口（启动绑定后不变，/reload 改端口需重启容器）
debug_mode = False
same_video_by_filename_enabled = False
ssrf_protection = True
max_concurrent_tasks = 20

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
_SENSITIVE_TASK_FIELDS = ('_referer', '_cookie', '_user_agent')


def load_config():
    """从 filter_rules.json / config.json / 环境变量加载配置。

    注意：本函数内部惰性导入 app_logger，以避免 app_config <-> app_logger
    的顶层循环导入（app_logger 顶层会 import app_config）。
    """
    from app_logger import log_info, log_error, debug_print

    # 重置为默认值（本函数内全部使用局部变量，末尾 globals().update 一次性写回）
    ad_keywords = []
    keywords_enabled = False
    filename_filters = []
    filename_filter_enabled = False
    filename_dedup_enabled = False
    filename_dedup_rules = []
    output_format = 'mp4'
    auth_key = ""
    url_prefix = ""
    server_port = 8080
    debug_mode = False
    same_video_by_filename_enabled = False
    ssrf_protection = True
    max_concurrent_tasks = 20

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

        debug_print(f"过滤规则加载成功: 拦截关键字 {'启用' if keywords_enabled else '禁用'} ({len(ad_keywords)} 个), 文件名过滤 {'启用' if filename_filter_enabled else '禁用'} ({len(filename_filters)} 个), 文件名去重: {'启用' if filename_dedup_enabled else '禁用'} ({len(filename_dedup_rules)} 条正则规则)")
    except Exception as e:
        log_error(f"过滤规则加载失败: {e}")
        ad_keywords = []
        keywords_enabled = False
        filename_filters = []
        filename_filter_enabled = False
        filename_dedup_rules = []

    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8-sig') as f:
            config = json.load(f)

        output_section = config.get('output_format', {})
        output_format = output_section.get('format', 'mp4')
        if output_format not in ['mp4', 'mkv']:
            output_format = 'mp4'

        # 优先从环境变量读取 auth_key，环境变量优先级高于配置文件
        env_auth_key = os.environ.get('AUTH_KEY', '')
        if env_auth_key:
            auth_key = env_auth_key
            debug_print("认证密钥来源: 环境变量")
        else:
            auth_key = config.get('auth_key', '')
            debug_print("认证密钥来源: 配置文件")

        # 优先从环境变量读取 url_prefix，环境变量优先级高于配置文件
        # 规范化：去首尾空格与斜杠，避免配置值带尾斜杠导致所有请求 404 并累积封禁计数
        env_url_prefix = os.environ.get('URL_PREFIX', '').strip()
        if env_url_prefix:
            url_prefix = env_url_prefix.strip('/')
            debug_print("URL前缀来源: 环境变量")
        else:
            url_prefix = str(config.get('url_prefix', '')).strip().strip('/')
            debug_print("URL前缀来源: 配置文件")

        server_port = int(config.get('port', 8080))

        debug_mode = bool(config.get('debug', False))

        same_video_by_filename_enabled = bool(config.get('same_video_by_filename', False))

        # SSRF 防护开关：环境变量优先（SSRF_PROTECTION=false 可关闭）
        env_ssrf = os.environ.get('SSRF_PROTECTION', '').lower()
        if env_ssrf in ('false', '0', 'no', 'off'):
            ssrf_protection = False
        elif env_ssrf in ('true', '1', 'yes', 'on'):
            ssrf_protection = True
        else:
            ssrf_protection = bool(config.get('ssrf_protection', True))

        # 最大并发任务数：环境变量优先
        env_max = os.environ.get('MAX_CONCURRENT_TASKS', '')
        if env_max.isdigit() and int(env_max) > 0:
            max_concurrent_tasks = int(env_max)
        else:
            max_concurrent_tasks = int(config.get('max_concurrent_tasks', 20))
    except Exception as e:
        log_error(f"配置加载失败: {e}")
        output_format = 'mp4'
        auth_key = ""
        url_prefix = ""
        server_port = 8080

    # 安全校验：AUTH_KEY 和 URL_PREFIX 必须设置，否则拒绝启动
    if not auth_key:
        raise RuntimeError("AUTH_KEY 未设置，请在环境变量或配置文件中指定")
    if not url_prefix:
        raise RuntimeError("URL_PREFIX 未设置，请在环境变量或配置文件中指定")

    # 把加载结果写回模块属性（load_config 内的局部变量 -> 全局状态）
    globals().update({
        'ad_keywords': ad_keywords,
        'keywords_enabled': keywords_enabled,
        'filename_filters': filename_filters,
        'filename_filter_enabled': filename_filter_enabled,
        'filename_dedup_enabled': filename_dedup_enabled,
        'filename_dedup_rules': filename_dedup_rules,
        'output_format': output_format,
        'auth_key': auth_key,
        'url_prefix': url_prefix,
        'server_port': server_port,
        'debug_mode': debug_mode,
        'same_video_by_filename_enabled': same_video_by_filename_enabled,
        'ssrf_protection': ssrf_protection,
        'max_concurrent_tasks': max_concurrent_tasks,
    })

    # 数据库路径：与 config.json 同级目录（data.db 承载封禁 IP + 用户）
    data_db.set_db_path(os.path.join(os.path.dirname(CONFIG_FILE), 'data.db'))
