#!/usr/bin/env python3
"""dedup - 下载去重内存缓存（按用户隔离）

每用户独立缓存（user/<名>/success.log、failure.log 惰性载入），
note_log_entry() 写日志后增量更新，避免每次下载检查都遍历日志文件。
用户删除后调用 drop_user_cache() 释放内存。
"""
import os
import json
import threading

import app_config as cfg
from app_logger import debug_print, log_error
from security import sanitize_url_for_log

# 每用户去重缓存：user -> {'success_urls': set, 'failure_urls': set,
#                          'success_names': [], 'failure_names': []}
_dedup_lock = threading.Lock()
_caches = {}


def _empty_cache():
    return {'success_urls': set(), 'failure_urls': set(),
            'success_names': [], 'failure_names': []}


def _load_user_cache(user):
    """从用户日志文件惰性载入去重缓存（调用方须持有 _dedup_lock）。"""
    cache = _empty_cache()
    for log_file, url_key, name_key in [
        (cfg.user_success_log(user), 'success_urls', 'success_names'),
        (cfg.user_failure_log(user), 'failure_urls', 'failure_names'),
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
                        if isinstance(entry, list) and len(entry) >= 3:
                            # 格式: [时间, 文件名, url1, url2, ...]
                            for u in entry[2:]:
                                if isinstance(u, str) and u.strip():
                                    cache[url_key].add(u.strip().rstrip('/'))
                            sn = entry[1]
                            if isinstance(sn, str) and sn:
                                cache[name_key].append(sn)
                    except json.JSONDecodeError:
                        continue
        except Exception as e:
            log_error(f"载入去重缓存失败 {log_file}: {e}")
    cache['_loaded'] = True
    return cache


def _get_cache(user):
    """获取用户缓存（未载入时惰性载入）。user 为空时返回空结构。"""
    if not user:
        return _empty_cache()
    cache = _caches.get(user)
    if cache is None:
        cache = _load_user_cache(user)
        _caches[user] = cache
    return cache


def drop_user_cache(user):
    """用户删除后释放其去重缓存。"""
    if not user:
        return
    with _dedup_lock:
        _caches.pop(user, None)


def note_log_entry(user, kind, save_name, unique_urls):
    """append_log 写入日志后增量更新去重缓存。

    kind: 'success' / 'failure'；user 为空时不更新。
    """
    if not user or kind not in ('success', 'failure'):
        return
    with _dedup_lock:
        cache = _get_cache(user)
        url_set = cache[f'{kind}_urls']
        name_list = cache[f'{kind}_names']
        for u in unique_urls:
            url_set.add(u.strip().rstrip('/'))
        if save_name:
            name_list.append(save_name)


def is_url_downloaded(url, user=None, check_failure=True):
    """检查 URL 是否已下载过（命中该用户的成功或失败日志）。

    Returns:
        (hit: bool, status: str | None) — status 为 'success' 或 'failure'
    """
    normalized_url = url.strip().rstrip('/')
    with _dedup_lock:
        cache = _get_cache(user)
        if normalized_url in cache['success_urls']:
            debug_print(f"[去重] URL 命中成功日志（用户={user}）: {sanitize_url_for_log(normalized_url)[:80]}")
            return True, 'success'
        if check_failure and normalized_url in cache['failure_urls']:
            debug_print(f"[去重] URL 命中失败日志（用户={user}）: {sanitize_url_for_log(normalized_url)[:80]}")
            return True, 'failure'
    # 未命中是常态（之后会正常启动下载），不打日志降噪
    return False, None


def is_filename_downloaded(save_name, user=None, check_failure=True):
    """same_video_by_filename 模式: 检查文件名是否已下载过（前缀匹配，按用户隔离）。

    Returns:
        (hit: bool, status: str | None) — status 为 'success' 或 'failure'
    """
    if not save_name:
        return False, None
    with _dedup_lock:
        cache = _get_cache(user)
        for name_key, status in [('success_names', 'success'), ('failure_names', 'failure')]:
            if status == 'failure' and not check_failure:
                continue
            for entry_save_name in cache[name_key]:
                if entry_save_name == save_name or \
                   entry_save_name.startswith(save_name + '.') or \
                   save_name.startswith(entry_save_name):
                    debug_print(f"[去重] 文件名命中{('成功' if status == 'success' else '失败')}日志（用户={user}）: {save_name}")
                    return True, status
    # 未命中是常态，不打日志降噪
    return False, None
