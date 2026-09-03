#!/usr/bin/env python3
"""security - 安全相关工具

  - is_safe_url: SSRF 防护（仅允许 http/https，禁止内网/回环地址）
  - sanitize_url_for_log: 日志 URL 脱敏（隐藏 token/sign/key 等查询参数）
  - check_rate_limit: 基于 IP 的速率限制
"""
import time
import socket
import ipaddress
import urllib.parse

import app_config as cfg


def is_safe_url(url):
    """SSRF 防护：校验 URL 是否安全（仅允许 http/https，禁止指向内网/回环地址）"""
    # 关闭 SSRF 防护时，放行所有 URL（适用于纯内网/Docker 环境）
    if not cfg.ssrf_protection:
        return True

    try:
        parsed = urllib.parse.urlparse(url)
    except Exception:
        return False

    # 仅允许 http/https 协议
    if parsed.scheme not in ('http', 'https'):
        return False

    hostname = parsed.hostname
    if not hostname:
        return False

    # 禁止 localhost
    if hostname.lower() in ('localhost', 'localhost.localdomain'):
        return False

    # 解析主机名对应的所有 IP，任一命中黑名单则拒绝
    try:
        addrinfo_list = socket.getaddrinfo(hostname, None)
    except socket.gaierror:
        # DNS 解析失败视为不安全，避免绕过
        return False

    for addrinfo in addrinfo_list:
        ip_str = addrinfo[4][0]
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            return False
        for network in cfg._BLOCKED_NETWORKS:
            if ip in network:
                return False

    return True


def sanitize_url_for_log(url):
    """日志脱敏：移除 URL 中的敏感查询参数（token/sign/key 等）"""
    try:
        parsed = urllib.parse.urlparse(url)
        query = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
        sanitized = {k: ('***' if k.lower() in cfg._SENSITIVE_URL_PARAMS else v)
                     for k, v in query.items()}
        new_query = urllib.parse.urlencode(sanitized, doseq=True)
        return urllib.parse.urlunparse(parsed._replace(query=new_query))
    except Exception:
        return url


def check_rate_limit(ip):
    """基于 IP 的速率限制，返回 (允许, 剩余次数)"""
    now = time.time()
    window_start = now - cfg.RATE_LIMIT_WINDOW
    with cfg.rate_limit_lock:
        # 清理所有时间戳已全部过期的 IP，防止字典无限增长导致内存泄漏
        expired_ips = [k for k, v in cfg.rate_limit_dict.items()
                       if not any(t > window_start for t in v)]
        for k in expired_ips:
            del cfg.rate_limit_dict[k]

        timestamps = cfg.rate_limit_dict.get(ip, [])
        # 清理窗口外的记录
        timestamps = [t for t in timestamps if t > window_start]
        if len(timestamps) >= cfg.RATE_LIMIT_MAX:
            cfg.rate_limit_dict[ip] = timestamps
            return False, 0
        timestamps.append(now)
        cfg.rate_limit_dict[ip] = timestamps
        return True, cfg.RATE_LIMIT_MAX - len(timestamps)
