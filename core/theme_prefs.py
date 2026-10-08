#!/usr/bin/env python3
"""theme_prefs - 账号默认主题色板偏好（下载/管理两个控制台共用）

按角色分开存储，原子写入、0600 权限：
  - 下载用户：/home/downloader/user/<用户名>/theme_prefs.json
    格式 {"default": "<色板 id>"}，随用户配置卷保留，
    删除用户时随整目录一并清除
  - 管理员：config/theme_admin.json（不创建管理员用户目录）
    格式 {"<管理员用户名>": "<色板 id>"}，按用户名分键
  - "random" 值（或文件/键不存在）即随机：打开页面恢复会话随机色板
  - 再次点击已点亮的星星时写入 "random"，文件始终保留
  - 色板 id 白名单与前端四主题保持一致：default / pixel / tech / morandi
"""
import json
import os
import threading

import app_config as cfg
from app_logger import log_error

# 与 web/shared.js 的 PALETTES 一致
VALID_PALETTES = ('default', 'pixel', 'tech', 'morandi')

# "default"/管理员键 的随机占位值：取消收藏时不删文件，改写为此值
RANDOM = 'random'

# 管理员偏好文件：config/theme_admin.json
THEME_ADMIN_FILE = os.path.join(cfg.CONFIG_DIR, 'theme_admin.json')

_lock = threading.Lock()


def _user_prefs_file(user):
    """下载用户偏好文件路径：/home/downloader/user/<用户名>/theme_prefs.json"""
    return os.path.join(cfg.user_config_dir(str(user)), 'theme_prefs.json')


def _load_json(path):
    """读取 JSON 文件；缺失/损坏时返回 None（损坏时记日志，不阻断页面加载）。"""
    try:
        with open(path, 'r', encoding='utf-8-sig') as f:
            return json.load(f)
    except FileNotFoundError:
        return None
    except Exception as e:
        log_error(f"主题偏好读取失败 {path}: {e}")
        return None


def _valid(palette):
    """色板 id 合法（在白名单内）返回原值，否则 None（随机）。"""
    return palette if palette in VALID_PALETTES else None


def get_palette(user, role='user'):
    """返回账号保存的默认色板 id；"random"、文件/键缺失、值非法时返回 None（随机）。"""
    if not user:
        return None
    key = str(user)
    if role == 'admin':
        data = _load_json(THEME_ADMIN_FILE)
        return _valid(data.get(key)) if isinstance(data, dict) else None
    data = _load_json(_user_prefs_file(user))
    palette = data.get('default') if isinstance(data, dict) else None
    return _valid(palette)


def set_palette(user, palette, role='user'):
    """保存/清除账号的默认色板。

    palette 为合法 id 时写入；为 None/空串/非法值时写入 "random"（恢复随机）。
    文件始终保留、不删除。返回最终生效的色板 id（或 None）。
    """
    if not user:
        return None
    key = str(user)
    wanted = _valid(palette)
    with _lock:
        if role == 'admin':
            data = _load_json(THEME_ADMIN_FILE)
            data = data if isinstance(data, dict) else {}
            data[key] = wanted or RANDOM
            cfg._write_json_atomic(THEME_ADMIN_FILE, data, mode=0o600)
        else:
            path = _user_prefs_file(user)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            cfg._write_json_atomic(path, {'default': wanted or RANDOM}, mode=0o600)
    return wanted
