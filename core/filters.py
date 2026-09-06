#!/usr/bin/env python3
"""filters - 广告关键字拦截与文件名过滤/去重（按用户隔离）

每用户独立的 filter_rules.json（user/<名>/filter_rules.json），首次使用时
从全局模板（config/filter_rules.json）复制；规则缓存于内存，保存后调用
reload_user_rules() 立即生效。

  - is_ad_content: 根据用户规则的 keywords 检测广告
  - filter_filename: 文件名关键字删除 + 正则去重 + 段级去重
  - get_user_rules / reload_user_rules: 规则读取与缓存刷新（API 编辑用）
"""
import os
import re
import json
import shutil
import threading

import app_config as cfg

# 每用户规则缓存：user -> 规则 dict（含编译后的正则）
_rules_cache = {}
_cache_lock = threading.Lock()

# 全局模板缺失时的内置兜底规则（与 config/filter_rules.json 结构一致）
_DEFAULT_RULES = {
    'keywords': {'enabled': False, 'list': []},
    'filename_filter': {'enabled': False, 'list': []},
    'filename_dedup': {
        'enabled': True,
        'rules': [{'pattern': '(\\w+)(_\\1)+', 'replacement': '\\1'}]
    },
}


def _log_error(msg):
    from app_logger import log_error
    log_error(msg)


def _load_rules_dict(path):
    """从文件加载过滤规则原始结构；文件缺失/损坏时返回 None。

    编译失败的正则跳过（与旧全局加载行为一致）。
    返回: dict(keywords/filename_filter/filename_dedup 原始结构 + 内部编译字段)
    """
    try:
        with open(path, 'r', encoding='utf-8-sig') as f:
            raw = json.load(f)
    except FileNotFoundError:
        return None
    except Exception as e:
        _log_error(f"过滤规则加载失败 {path}: {e}")
        return None
    if not isinstance(raw, dict):
        return None

    kw = raw.get('keywords') if isinstance(raw.get('keywords'), dict) else {}
    ff = raw.get('filename_filter') if isinstance(raw.get('filename_filter'), dict) else {}
    dd = raw.get('filename_dedup') if isinstance(raw.get('filename_dedup'), dict) else {}

    keywords_enabled = bool(kw.get('enabled', False))
    ad_keywords = [str(k) for k in kw.get('list', []) if str(k).strip()] if keywords_enabled else []

    ff_enabled = bool(ff.get('enabled', False))
    ff_list = [str(k) for k in ff.get('list', []) if str(k).strip()] if ff_enabled else []

    dd_enabled = bool(dd.get('enabled', False))
    dd_rules = []
    if dd_enabled:
        for rule in dd.get('rules', []):
            if not isinstance(rule, dict):
                continue
            pattern = str(rule.get('pattern', '') or '')
            replacement = str(rule.get('replacement', '') or '')
            if not pattern:
                continue
            try:
                dd_rules.append((re.compile(pattern), replacement))
            except re.error:
                _log_error(f"文件名去重正则编译失败 [{pattern}]")

    return {
        'raw': raw,
        'keywords_enabled': keywords_enabled,
        'ad_keywords': ad_keywords,
        'ff_enabled': ff_enabled,
        'ff_list': ff_list,
        'dd_enabled': dd_enabled,
        'dd_rules': dd_rules,
    }


def _ensure_user_filter_file(user):
    """确保用户过滤规则文件存在：缺失时从全局模板复制（模板也缺失则写内置默认）。

    返回规则文件路径；创建失败时也返回路径（读取端会按缺失兜底）。
    """
    path = cfg.user_filter_rules_file(user)
    if os.path.exists(path):
        return path
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if os.path.isfile(cfg.FILTER_RULES_FILE):
            shutil.copyfile(cfg.FILTER_RULES_FILE, path)
        else:
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(_DEFAULT_RULES, f, ensure_ascii=False, indent=2)
    except Exception as e:
        _log_error(f"创建用户过滤规则文件失败 {path}: {e}")
    return path


def get_user_rules(user, reload=False):
    """获取用户过滤规则（带缓存）。user 为空时返回空规则集。

    reload=True 时强制从文件重读（用户保存规则后调用，立即生效）。
    """
    if not user:
        return {'raw': {}, 'keywords_enabled': False, 'ad_keywords': [],
                'ff_enabled': False, 'ff_list': [], 'dd_enabled': False, 'dd_rules': []}
    with _cache_lock:
        cached = _rules_cache.get(user)
        if cached is not None and not reload:
            return cached
        path = _ensure_user_filter_file(user)
        rules = _load_rules_dict(path)
        if rules is None:
            # 文件读取失败：空规则兜底，不缓存损坏状态以外的结果
            rules = {'raw': {}, 'keywords_enabled': False, 'ad_keywords': [],
                     'ff_enabled': False, 'ff_list': [], 'dd_enabled': False, 'dd_rules': []}
            if not os.path.exists(path):
                _rules_cache[user] = rules
            return rules
        _rules_cache[user] = rules
        return rules


def reload_user_rules(user):
    """用户保存规则后刷新缓存，使新规则对后续任务立即生效。"""
    if user:
        with _cache_lock:
            _rules_cache.pop(user, None)


def save_user_rules(user, raw_rules):
    """整体保存用户过滤规则（原子写回）并刷新缓存。

    raw_rules 应为完整的 filter_rules.json 结构 dict；由 API 层做结构与正则校验。
    """
    path = cfg.user_filter_rules_file(user)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    cfg._write_json_atomic(path, raw_rules, mode=0o600)
    reload_user_rules(user)


def get_ad_keywords(user):
    """获取用户的广告拦截关键字列表（未启用时为空列表）。"""
    return get_user_rules(user)['ad_keywords']


def is_ad_content(save_name, url, user=None):
    """检测广告内容（按用户规则）。命中返回 (True, 关键字)。"""
    if not user:
        return False, None
    rules = get_user_rules(user)
    if not rules['keywords_enabled'] or not rules['ad_keywords']:
        return False, None

    check_text = (save_name or "") + " " + (url or "")
    for keyword in rules['ad_keywords']:
        if keyword in check_text:
            return True, keyword

    return False, None


def filter_filename(name, user=None):
    """
    按用户规则过滤文件名中的指定关键字，并应用正则规则和段级去重。
    1. filename_filter: 依次删除文件名中出现的关键字
       例如: name="abc_fhc_lka.mp4", filename_filters=["fh"]
            返回 "abc_c_lka.mp4"
    2. filename_dedup.rules: 按顺序应用多条正则规则，每条规则循环到不再变化
       例如: name="abc_abc_lcksmdnc_bnh_bnh.mp4", 规则 (\\w+)(_\\1)+ → \\1
            返回 "abc_lcksmdnc_bnh.mp4"
    3. 段级去重: 按 _ 分割后去除所有重复段（包括非连续重复），始终执行
       例如: name="abc_lcksmdnc_abc_bnh.mp4"
            返回 "abc_lcksmdnc_bnh.mp4"

    Returns:
        (filtered_name, ad_count) — ad_count 为关键字删除步骤命中的过滤词数量
    """
    if not name:
        return name, 0

    rules = get_user_rules(user)

    filtered_name = name
    ad_count = 0

    # 1. 关键字删除
    if rules['ff_enabled'] and rules['ff_list']:
        for keyword in rules['ff_list']:
            if keyword in filtered_name:
                filtered_name = filtered_name.replace(keyword, '')
                ad_count += 1

    # 2. 正则规则（按顺序，每条循环到不再变化）
    if rules['dd_enabled'] and rules['dd_rules']:
        for compiled, replacement in rules['dd_rules']:
            prev = None
            while prev != filtered_name:
                prev = filtered_name
                filtered_name = compiled.sub(replacement, filtered_name)

    # 3. 段级去重（按 _ 分割，去除所有重复段，保留首次出现，始终执行）
    if rules['dd_enabled']:
        if '.' in filtered_name:
            name_part, dot, ext = filtered_name.rpartition('.')
            ext = dot + ext
        else:
            name_part = filtered_name
            ext = ''
        segments = name_part.split('_')
        seen = set()
        unique_segments = []
        for seg in segments:
            if seg not in seen:
                seen.add(seg)
                unique_segments.append(seg)
        if len(unique_segments) < len(segments):
            filtered_name = '_'.join(unique_segments) + ext

    return filtered_name, ad_count
