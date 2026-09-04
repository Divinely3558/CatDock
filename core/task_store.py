#!/usr/bin/env python3
"""task_store - 任务列表持久化与下载日志写入

  - save_tasks / load_tasks: tasks.json 读写
  - append_log: 写 success.log / failure.log，并增量更新去重缓存
"""
import os
import json
import time
import shutil

import app_config as cfg
from app_logger import log_error, debug_print
import dedup


def save_tasks(force=False):
    current_time = time.time()
    if not force and current_time - cfg.last_save_time < 2:
        return

    try:
        os.makedirs(os.path.dirname(cfg.TASKS_FILE), exist_ok=True)
        temp_file = cfg.TASKS_FILE + '.tmp'

        with cfg.tasks_lock:
            tasks_data = []
            for task in cfg.tasks.values():
                task_data = {
                    'id': task['id'],
                    'urls': task['urls'],
                    'save_name': task.get('save_name', ''),
                    'status': task['status'],
                    'progress': task.get('progress', 0),
                    'user': task.get('user', '')
                }
                tasks_data.append(task_data)

        with open(temp_file, 'w', encoding='utf-8') as f:
            json.dump(tasks_data, f, ensure_ascii=False, indent=2)

        os.replace(temp_file, cfg.TASKS_FILE)
        cfg.last_save_time = current_time
    except Exception as e:
        log_error(f"保存任务失败: {e}")


def load_tasks():
    # 旧版 tasks.json 存放在挂载卷 config/ 下（网页端时代已无需对外展示），
    # 首次升级时自动迁移到容器内 .data/ 目录；跨挂载文件系统需用 shutil.move
    try:
        if os.path.exists(cfg.LEGACY_TASKS_FILE) and not os.path.exists(cfg.TASKS_FILE):
            os.makedirs(os.path.dirname(cfg.TASKS_FILE), exist_ok=True)
            shutil.move(cfg.LEGACY_TASKS_FILE, cfg.TASKS_FILE)
            print(f"已迁移任务文件: {cfg.LEGACY_TASKS_FILE} -> {cfg.TASKS_FILE}")
    except Exception as e:
        log_error(f"迁移任务文件失败: {e} - 尝试从旧路径加载")

    tasks_file = cfg.TASKS_FILE
    if not os.path.exists(tasks_file) and os.path.exists(cfg.LEGACY_TASKS_FILE):
        tasks_file = cfg.LEGACY_TASKS_FILE  # 迁移失败时回退读取旧路径，保证功能不受影响

    if not os.path.exists(tasks_file):
        return

    try:
        with open(tasks_file, 'r', encoding='utf-8-sig') as f:
            tasks_data = json.load(f)

        with cfg.tasks_lock:
            cfg.tasks.clear()
            for task in tasks_data:
                task_urls = task['urls']
                cfg.tasks[task['id']] = {
                    'id': task['id'],
                    'url': task_urls[0],
                    'urls': task_urls,
                    'save_name': task.get('save_name', ''),
                    'status': task.get('status', 'running'),
                    'progress': task.get('progress', 0),
                    'user': task.get('user', ''),
                    '_referer': '',
                    '_cookie': '',
                    '_user_agent': '',
                    '_retry_count': 0
                }

        debug_print(f"已加载 {len(cfg.tasks)} 个任务")
    except Exception as e:
        log_error(f"加载任务失败: {e}")


def append_log(log_file, task_data):
    """写入日志文件，失败时抛出异常

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
    # 增量更新去重缓存
    dedup.note_log_entry(log_file, save_name, unique_urls)
