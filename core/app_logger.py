#!/usr/bin/env python3
"""app_logger - 统一日志输出

提供 log_info / log_warning / log_error / debug_print。
时间格式为短格式 [YYMMDD HH:MM:SS]，时区在 app_config 中固定为东八区。
"""
import time
import sys

import app_config as cfg


def log_info(*args, **kwargs):
    """普通信息输出，带时间戳"""
    timestamp = time.strftime('%y%m%d %H:%M:%S')
    print(f"[{timestamp}] INFO: ", end='')
    print(*args, **kwargs)


def log_warning(*args, **kwargs):
    """警告信息输出，带时间戳"""
    timestamp = time.strftime('%y%m%d %H:%M:%S')
    print(f"[{timestamp}] WARNING: ", end='')
    print(*args, **kwargs)


def log_error(*args, **kwargs):
    """错误信息输出到 stderr，带时间戳"""
    timestamp = time.strftime('%y%m%d %H:%M:%S')
    print(f"[{timestamp}] ERROR: ", end='', file=sys.stderr)
    print(*args, file=sys.stderr, **kwargs)


def debug_print(*args, **kwargs):
    """调试模式下输出日志，带时间戳"""
    if cfg.debug_mode:
        timestamp = time.strftime('%y%m%d %H:%M:%S')
        print(f"[{timestamp}] DEBUG: ", end='')
        print(*args, **kwargs)
