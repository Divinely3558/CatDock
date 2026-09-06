#!/usr/bin/env python3
"""task_store - 任务列表持久化与下载日志写入（按用户隔离）

  - save_tasks / load_tasks: 按用户分文件读写 user/<名>/tasks.json
  - append_log: 写用户目录下的 success.log / failure.log，并增量更新去重缓存
"""
import os
import json
import time

import app_config as cfg
from app_logger import log_error, debug_print
import dedup


def save_tasks(force=False):
    """把内存任务按 user 分组，原子写回各用户的 tasks.json（2 秒节流）。"""
    current_time = time.time()
    if not force and current_time - cfg.last_save_time < 2:
        return

    try:
        with cfg.tasks_lock:
            # user -> [task_data, ...]（无 user 的任务归入 default）
            grouped = {}
            for task in cfg.tasks.values():
                user = task.get('user') or 'default'
                task_data = {
                    'id': task['id'],
                    'urls': task['urls'],
                    'save_name': task.get('save_name', ''),
                    'status': task['status'],
                    'progress': task.get('progress', 0),
                    'user': user,
                }
                grouped.setdefault(user, []).append(task_data)

            # 需要落盘的用户：内存中有任务的用户 ∪ 磁盘上已存在 tasks.json 的用户。
            # 关键：当某用户最后一个任务完成并从内存删除后，grouped 不再包含该用户，
            # 若此时不回写，其 tasks.json 中的已完成记录会永久残留，
            # 导致每次重启都重复“恢复→判定已完成→删除”但文件始终不清空。
            users_to_write = set(grouped.keys())
            if os.path.isdir(cfg.USER_DIR):
                for username in os.listdir(cfg.USER_DIR):
                    if os.path.isfile(cfg.user_tasks_file(username)):
                        users_to_write.add(username)

        for user in users_to_write:
            tasks_data = grouped.get(user, [])
            tasks_file = cfg.user_tasks_file(user)
            os.makedirs(os.path.dirname(tasks_file), exist_ok=True)
            temp_file = tasks_file + '.tmp'
            with open(temp_file, 'w', encoding='utf-8') as f:
                json.dump(tasks_data, f, ensure_ascii=False, indent=2)
            os.replace(temp_file, tasks_file)

        cfg.last_save_time = current_time
    except Exception as e:
        log_error(f"保存任务失败: {e}")


def load_tasks():
    """启动时扫描 user/ 下所有用户的 tasks.json 并载入内存。"""
    if not os.path.isdir(cfg.USER_DIR):
        return

    loaded_count = 0
    try:
        for username in os.listdir(cfg.USER_DIR):
            tasks_file = cfg.user_tasks_file(username)
            if not os.path.isfile(tasks_file):
                continue
            try:
                with open(tasks_file, 'r', encoding='utf-8-sig') as f:
                    tasks_data = json.load(f)
            except Exception as e:
                log_error(f"加载任务失败 {tasks_file}: {e}")
                continue

            with cfg.tasks_lock:
                for task in tasks_data:
                    task_urls = task['urls']
                    cfg.tasks[task['id']] = {
                        'id': task['id'],
                        'url': task_urls[0],
                        'urls': task_urls,
                        'save_name': task.get('save_name', ''),
                        'status': task.get('status', 'running'),
                        'progress': task.get('progress', 0),
                        'user': task.get('user', '') or username,
                        '_referer': '',
                        '_cookie': '',
                        '_user_agent': '',
                        '_retry_count': 0
                    }
                    loaded_count += 1

        if loaded_count:
            debug_print(f"已加载 {loaded_count} 个任务")
    except Exception as e:
        log_error(f"加载任务失败: {e}")


def append_log(log_file, task_data, kind):
    """写入日志文件，失败时抛出异常

    kind: 'success' / 'failure'（用于去重缓存归类）
    记录格式: [时间, 文件名, url1, url2, ...]
    同一文件的所有链接记录在同一条目内
    """
    os.makedirs(os.path.dirname(log_file), exist_ok=True)
    log_time = time.strftime('%Y-%m-%d %H:%M', time.localtime())
    urls = task_data['urls']
    # 去重并保持顺序
    seen = set()
    unique_urls = []
    for u in urls:
        if u and u not in seen:
            seen.add(u)
            unique_urls.append(u)
    save_name = task_data.get('save_name', '')
    log_entry = [log_time, save_name] + unique_urls
    with open(log_file, 'a', encoding='utf-8') as f:
        f.write(json.dumps(log_entry, ensure_ascii=False) + '\n')
    # 增量更新去重缓存（按用户隔离）
    dedup.note_log_entry(task_data.get('user') or 'default', kind,
                         save_name, unique_urls)
