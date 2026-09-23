#!/usr/bin/env python3
"""app_logger - 统一日志输出

提供 log_info / log_warning / log_error / debug_print。
时间格式为短格式 [YYMMDD HH:MM:SS]，时区在 app_config 中固定为东八区。

同时将全部级别日志写入每日日志文件 {LOG_DIR}/YYYY-MM-DD.log，
供管理端「日志导出」功能按日期合并导出。
"""
import os
import sys
import time
import threading

import app_config as cfg

# 文件写入锁（ThreadingHTTPServer 多线程并发写日志时保证行级原子）
_file_lock = threading.Lock()
# 当前已打开的日志文件句柄与对应日期，惰性初始化 + 按日切换
_log_fp = None
_log_date = ""


def _ensure_log_dir():
    """确保日志目录存在，失败不抛异常（仅控制台日志不受影响）"""
    try:
        os.makedirs(cfg.LOG_DIR, exist_ok=True)
        return True
    except OSError:
        return False


def _get_log_fp():
    """获取当前日期的日志文件句柄，日期变更时自动切换到新文件。

    返回 None 表示无法写入文件（目录创建失败等），调用方应仅输出到控制台。
    """
    global _log_fp, _log_date
    today = time.strftime('%Y-%m-%d')
    if _log_fp is not None and _log_date == today:
        return _log_fp
    # 日期变更或首次写入：关闭旧文件，打开新文件
    if _log_fp is not None:
        try:
            _log_fp.close()
        except Exception:
            pass
        _log_fp = None
    if not _ensure_log_dir():
        return None
    try:
        _log_fp = open(os.path.join(cfg.LOG_DIR, today + '.log'),
                       'a', encoding='utf-8')
        _log_date = today
    except OSError:
        _log_fp = None
        _log_date = ""
    return _log_fp


def _write_to_file(level, *args, **kwargs):
    """将一条日志追加写入当日日志文件（带时间戳与级别标记）。

    与控制台输出格式保持一致：[YYMMDD HH:MM:SS] LEVEL: message
    文件写入失败不影响控制台输出，仅在调试模式下打印失败原因。
    """
    fp = _get_log_fp()
    if fp is None:
        return
    timestamp = time.strftime('%y%m%d %H:%M:%S')
    parts = [str(a) for a in args]
    message = ' '.join(parts)
    line = f"[{timestamp}] {level}: {message}\n"
    try:
        with _file_lock:
            fp.write(line)
            fp.flush()
    except Exception:
        # 文件写入异常（磁盘满/权限等）时不再尝试，避免反复报错刷屏
        pass


def log_info(*args, **kwargs):
    """普通信息输出，带时间戳"""
    timestamp = time.strftime('%y%m%d %H:%M:%S')
    print(f"[{timestamp}] INFO: ", end='')
    print(*args, **kwargs)
    _write_to_file('INFO', *args, **kwargs)


def log_warning(*args, **kwargs):
    """警告信息输出，带时间戳"""
    timestamp = time.strftime('%y%m%d %H:%M:%S')
    print(f"[{timestamp}] WARNING: ", end='')
    print(*args, **kwargs)
    _write_to_file('WARNING', *args, **kwargs)


def log_error(*args, **kwargs):
    """错误信息输出到 stderr，带时间戳"""
    timestamp = time.strftime('%y%m%d %H:%M:%S')
    print(f"[{timestamp}] ERROR: ", end='', file=sys.stderr)
    print(*args, file=sys.stderr, **kwargs)
    _write_to_file('ERROR', *args, **kwargs)


def debug_print(*args, **kwargs):
    """调试模式下输出日志，带时间戳；debug 关闭时不输出控制台也不写入文件"""
    if not cfg.debug_mode:
        return
    timestamp = time.strftime('%y%m%d %H:%M:%S')
    print(f"[{timestamp}] DEBUG: ", end='')
    print(*args, **kwargs)
    _write_to_file('DEBUG', *args, **kwargs)
