#!/usr/bin/env python3
"""security - 安全相关工具

  - is_safe_url: SSRF 防护（仅允许 http/https，禁止内网/回环地址）
  - check_redirect_chain: 重定向链逐跳预检（防 302 跳向内网绕过 SSRF 防护）
  - sanitize_url_for_log: 日志 URL 脱敏（隐藏 token/sign/key 等查询参数）
  - check_rate_limit: 基于 IP 的速率限制
"""
import time
import socket
import ipaddress
import urllib.parse
import urllib.request
import urllib.error

import app_config as cfg

# 重定向链预检的跟随上限：超过视为不安全
REDIRECT_MAX_HOPS = 5
# 预检单跳请求超时（秒）
_PEEK_TIMEOUT = 10


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
    except (socket.gaierror, UnicodeError, OSError):
        # DNS 解析失败视为不安全，避免绕过（UnicodeError：非法 IDN 编码）
        return False

    for addrinfo in addrinfo_list:
        ip_str = addrinfo[4][0]
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            return False
        # IPv4-mapped IPv6（::ffff:a.b.c.d）不在 IPv4 禁用网段内，
        # 还原为纯 IPv4 后判定，防止内网地址以映射形式绕过
        if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
            ip = ip.ipv4_mapped
        for network in cfg._BLOCKED_NETWORKS:
            if ip in network:
                return False

    return True


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """禁用 urllib 自动跟随重定向：3xx 原样返回给调用方处理"""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _peek_redirect(url):
    """向 URL 发起一次探测请求，返回其 Location 重定向目标；无重定向返回 None。

    优先 HEAD；服务器不支持（405/501 等）时退化为 Range GET（仅取 1 字节）。
    仅读取响应头，不下载内容。
    """
    attempts = (('HEAD', {}), ('GET', {'Range': 'bytes=0-0'}))
    for method, extra_headers in attempts:
        try:
            req = urllib.request.Request(url, headers=extra_headers, method=method)
            opener = urllib.request.build_opener(_NoRedirect)
            with opener.open(req, timeout=_PEEK_TIMEOUT) as resp:
                if 300 <= resp.status < 400:
                    return resp.headers.get('Location')
                return None
        except urllib.error.HTTPError as e:
            # _NoRedirect 下 3xx 以 HTTPError 形式抛出
            if 300 <= e.code < 400:
                loc = e.headers.get('Location')
                if loc:
                    return loc
                return None
            if method == 'HEAD':
                continue  # HEAD 不被支持，退化为 Range GET
            return None
        except Exception:
            if method == 'HEAD':
                continue
            return None
    return None


def check_redirect_chain(url):
    """逐跳预检重定向链：跟随 Location 并对每一跳执行 SSRF 校验。

    提交时安全的公网 URL 可能经 302 跳转向内网（下载器/curl -L 均会自动
    跟随重定向），本函数在提交时提前暴露此类绕过。

    返回 (safe, offending_url)：safe=False 时 offending_url 为首个不安全
    或超出跳数上限的地址。预检网络异常时放行（尽力而为的预检，不因
    网络抖动误拒正常任务；探测失败的目标实际下载时也会失败）。
    """
    if not cfg.ssrf_protection:
        return True, url
    current = url
    for _ in range(REDIRECT_MAX_HOPS):
        if not is_safe_url(current):
            return False, current
        loc = _peek_redirect(current)
        if not loc:
            return True, current
        # Location 可能是相对路径，需基于当前 URL 拼接
        current = urllib.parse.urljoin(current, loc)
        if urllib.parse.urlparse(current).scheme not in ('http', 'https'):
            return False, current
    return False, current


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
