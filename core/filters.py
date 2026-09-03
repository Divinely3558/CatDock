#!/usr/bin/env python3
"""filters - 广告关键字拦截与文件名过滤/去重

  - is_ad_content: 根据 filter_rules.json 的 keywords 检测广告
  - filter_filename: 文件名关键字删除 + 正则去重 + 段级去重
"""
import app_config as cfg


def is_ad_content(save_name, url):
    if not cfg.keywords_enabled or not cfg.ad_keywords:
        return False, None

    check_text = (save_name or "") + " " + (url or "")

    for keyword in cfg.ad_keywords:
        if keyword in check_text:
            return True, keyword

    return False, None


def filter_filename(name):
    """
    过滤文件名中的指定关键字，并应用正则规则和段级去重。
    1. filename_filters: 依次删除文件名中出现的关键字
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

    filtered_name = name
    ad_count = 0

    # 1. 关键字删除
    if cfg.filename_filter_enabled and cfg.filename_filters:
        for keyword in cfg.filename_filters:
            if keyword in filtered_name:
                filtered_name = filtered_name.replace(keyword, '')
                ad_count += 1

    # 2. 正则规则（按顺序，每条循环到不再变化）
    if cfg.filename_dedup_enabled and cfg.filename_dedup_rules:
        for compiled, replacement in cfg.filename_dedup_rules:
            prev = None
            while prev != filtered_name:
                prev = filtered_name
                filtered_name = compiled.sub(replacement, filtered_name)

    # 3. 段级去重（按 _ 分割，去除所有重复段，保留首次出现，始终执行）
    if cfg.filename_dedup_enabled:
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
