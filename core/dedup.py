#!/usr/bin/env python3
"""dedup - 下载去重内存缓存

启动时从 success.log / failure.log 一次性载入，append_log 时通过
note_log_entry() 增量更新，避免每次下载检查都同步遍历日志文件。
"""
import os
import json
import threading

import app_config as cfg
from app_logger import debug_print, log_error
from security import sanitize_url_for_log

# 去重缓存（启动载入 + 写日志时增量更新）
_dedup_lock = threading.Lock()
_success_urls = set()       # success.log 中出现过的 URL（已规范化）
_failure_urls = set()       # failure.log 中的 URL（启动清空后增量）
_success_filenames = []     # success.log 中的 save_name 列表（前缀匹配）
_failure_filenames = []     # failure.log 中的 save_name 列表


def note_log_entry(log_file, save_name, unique_urls):
    """append_log 写入日志后增量更新去重缓存。"""
    with _dedup_lock:
        if log_file == cfg.SUCCESS_LOG_FILE:
            u_set, n_list = _success_urls, _success_filenames
        elif log_file == cfg.FAILURE_LOG_FILE:
            u_set, n_list = _failure_urls, _failure_filenames
        else:
            return
        for u in unique_urls:
            u_set.add(u.strip().rstrip('/'))
        if save_name:
            n_list.append(save_name)


def is_url_downloaded(url, check_failure=True):
    """检查 URL 是否已下载过（命中成功或失败日志）。

    Returns:
        (hit: bool, status: str | None) — status 为 'success' 或 'failure'
    """
    normalized_url = url.strip().rstrip('/')
    debug_print(f"is_url_downloaded: URL={sanitize_url_for_log(normalized_url)[:80]}, check_failure={check_failure}")
    with _dedup_lock:
        if normalized_url in _success_urls:
            debug_print("is_url_downloaded: 命中 success.log")
            return True, 'success'
        if check_failure and normalized_url in _failure_urls:
            debug_print("is_url_downloaded: 命中 failure.log")
            return True, 'failure'
    debug_print("is_url_downloaded: 未命中")
    return False, None


def is_filename_downloaded(save_name, check_failure=True):
    """same_video_by_filename 模式: 检查文件名是否已下载过（前缀匹配）。

    Returns:
        (hit: bool, status: str | None) — status 为 'success' 或 'failure'
    """
    if not save_name:
        return False, None
    debug_print(f"is_filename_downloaded: name={save_name}, check_failure={check_failure}")
    with _dedup_lock:
        for name_list, status in [(_success_filenames, 'success'), (_failure_filenames, 'failure')]:
            if status == 'failure' and not check_failure:
                continue
            for entry_save_name in name_list:
                if entry_save_name == save_name or \
                   entry_save_name.startswith(save_name + '.') or \
                   save_name.startswith(entry_save_name):
                    debug_print(f"is_filename_downloaded: 命中{status}.log")
                    return True, status
    debug_print("is_filename_downloaded: 未命中")
    return False, None


def init_dedup_cache():
    """启动时从日志一次性载入去重缓存。

    须在清空 failure.log 之后、resume_tasks 之前调用（resume_tasks 会调用去重检查）。
    """
    with _dedup_lock:
        _success_urls.clear()
        _failure_urls.clear()
        _success_filenames.clear()
        _failure_filenames.clear()
        for log_file, url_set, name_list in [
            (cfg.SUCCESS_LOG_FILE, _success_urls, _success_filenames),
            (cfg.FAILURE_LOG_FILE, _failure_urls, _failure_filenames),
        ]:
            if not os.path.exists(log_file):
                continue
            try:
                with open(log_file, 'r', encoding='utf-8') as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            entry = json.loads(line)
                            if isinstance(entry, list) and len(entry) >= 2:
                                for u in entry[2:] if len(entry) >= 3 else []:
                                    if isinstance(u, str) and u.strip():
                                        url_set.add(u.strip().rstrip('/'))
                                sn = entry[1]
                                if isinstance(sn, str) and sn:
                                    name_list.append(sn)
                            elif isinstance(entry, dict):
                                u = entry.get('url', '')
                                if isinstance(u, str) and u.strip():
                                    url_set.add(u.strip().rstrip('/'))
                                sn = entry.get('save_name', '')
                                if isinstance(sn, str) and sn:
                                    name_list.append(sn)
                        except json.JSONDecodeError:
                            continue
            except Exception as e:
                log_error(f"载入去重缓存失败 {log_file}: {e}")
    debug_print(f"去重缓存已载入: success urls={len(_success_urls)} filenames={len(_success_filenames)}; failure urls={len(_failure_urls)} filenames={len(_failure_filenames)}")
