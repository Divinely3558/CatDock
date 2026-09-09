#!/usr/bin/env python3
"""api_server - HTTP 服务层

包含 DownloadHandler（认证 / 限流 / 路由）、TimeoutHTTPServer、
start_server / stop_server / 信号注册。

业务逻辑下沉到 downloader / task_store / dedup / filters / security / data_db。
"""
import sys
import os
import re
import json
import hmac
import time
import base64
import hashlib
import secrets
import socket
import signal
import ipaddress
import urllib.parse
import http.server

import app_config as cfg
from app_logger import log_info, log_error, debug_print
import data_db
from security import is_safe_url, sanitize_url_for_log, check_rate_limit
from filters import is_ad_content, get_user_rules, save_user_rules
from task_store import load_tasks
from downloader import run_download, resume_tasks, pause_task, resume_paused_task, delete_task, cleanup_user_data
from webui import get_login_html, get_user_html, get_admin_html


# 已警告过的 IP（尝试登录已封禁账号时首次仅提示，再次尝试直接封 IP）
_banned_account_warned_ips = set()


def _normalize_ip(addr):
    """规范化客户端 IP。

    dual-stack 监听下，IPv4 客户端在 socket 层呈现为 IPv4-mapped IPv6
    （如 ::ffff:1.2.3.4）。统一还原为纯 IPv4 字符串，使其与 CLI
    banip add <IP> / data.db 中存储的 key 一致，避免同一 IP 因表示形式
    不同而绕过封禁或重复计数。无法解析的原样返回。
    """
    try:
        ip = ipaddress.ip_address(addr)
        if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
            return str(ip.ipv4_mapped)
        return str(ip)
    except ValueError:
        return addr


def _record_failure_and_log(client_ip):
    """记录一次认证失败并按阶梯封禁结果输出日志。

    返回 data_db.record_auth_failure 的结果：False（未封禁）/ 'temp'（临时封禁）/ 'perm'（永久封禁）。
    """
    result = data_db.record_auth_failure(client_ip)
    if result == 'perm':
        log_error(f"IP {client_ip} 重复触发封禁阈值，已永久封禁（需在容器内执行 banip del {client_ip} 手动解除）")
    elif result == 'temp':
        log_error(f"IP {client_ip} 认证失败累计达阈值，已临时封禁 30 分钟")
    return result


# ---------- 访问令牌（access_token）----------
# 无状态 HMAC 签名令牌：POST /login 两层认证通过后签发，
# 业务接口通过 Authorization: Bearer <token> 请求头携带，
# 避免在 URL 查询参数中传递密钥/账号密码（URL 会进入浏览器历史与各级访问日志）。
TOKEN_TTL_SECONDS = 7200  # 令牌有效期 2 小时，过期后需重新登录
_TOKEN_INFO = b'catdock-token-v1'  # 派生盐，AUTH_KEY 变更后旧令牌自动全部失效


def _token_sign_key():
    """由 AUTH_KEY 派生令牌签名密钥（不在内存中直接复用 AUTH_KEY 本体做签名）"""
    return hmac.new(cfg.auth_key.encode('utf-8'), _TOKEN_INFO, hashlib.sha256).digest()


def _b64url_encode(raw):
    return base64.urlsafe_b64encode(raw).rstrip(b'=').decode('ascii')


def _b64url_decode(text):
    pad = '=' * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + pad)


def issue_auth_token(username, role='user'):
    """为已通过两层认证的用户签发令牌：base64url(payload).base64url(hmac_sha256 签名)

    payload 含唯一 jti 与角色 role 并登记到 data.db 的 auth_tokens 表，支持服务端
    主动吊销（注销 / 改密码 / 删用户 / 禁用用户 / AUTH_KEY 热更换）。
    签发时顺带惰性清理已过期的登记行。
    """
    payload = json.dumps({
        'user': username,
        'role': role,
        'exp': int(time.time()) + TOKEN_TTL_SECONDS,
        'jti': secrets.token_hex(16),
    }, ensure_ascii=False).encode('utf-8')
    sig = hmac.new(_token_sign_key(), payload, hashlib.sha256).digest()
    claims = json.loads(payload)
    data_db.cleanup_expired_tokens()
    data_db.save_auth_token(claims['jti'], username, claims['exp'])
    return _b64url_encode(payload) + '.' + _b64url_encode(sig)


def verify_token_claims(token):
    """仅校验签名与有效期，返回 claims（含 user/role/jti/exp）；无效返回 None。

    不含吊销/禁用状态校验，供认证层细分失败原因（如账号被禁用不计封禁）。
    """
    try:
        payload_b64, sig_b64 = token.split('.', 1)
        payload = _b64url_decode(payload_b64)
        expected = hmac.new(_token_sign_key(), payload, hashlib.sha256).digest()
        if not hmac.compare_digest(expected, _b64url_decode(sig_b64)):
            return None
        data = json.loads(payload.decode('utf-8'))
        username = data.get('user')
        exp = data.get('exp')
        if not username or not isinstance(exp, int) or exp < int(time.time()):
            return None
        return data
    except Exception:
        return None


def get_token_claims(token):
    """解析令牌 payload（不验签，仅供签名校验通过后使用），失败返回 None"""
    try:
        payload = _b64url_decode(token.split('.', 1)[0])
        return json.loads(payload.decode('utf-8'))
    except Exception:
        return None


def verify_auth_token(token):
    """完整校验令牌（签名/有效期/未吊销/用户存在且未禁用），返回用户名；无效返回 None"""
    data = verify_token_claims(token)
    if data is None:
        return None
    jti = data.get('jti')
    username = data.get('user')
    # 吊销校验：jti 必须登记在册且未被吊销（改密码/注销/删用户/禁用/换 KEY 后失效）
    if not jti or not data_db.is_token_valid(jti):
        return None
    # 用户在有效期内被删除或禁用后，令牌立即失效
    if not username or not data_db.is_user_active(username):
        return None
    return username


class DownloadHandler(http.server.BaseHTTPRequestHandler):
    REQUEST_TIMEOUT = 30

    def send_json(self, data, status=200):
        try:
            # 先序列化 body，再发响应头：若 json.dumps 失败（如含不可序列化对象），
            # 此时尚未发送任何字节，客户端不会收到"有头无体"的截断响应
            body = json.dumps(data, ensure_ascii=False).encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Connection', 'close')
            self.end_headers()
            self.wfile.write(body)
        except Exception as e:
            debug_print(f"[HTTP] 响应发送失败（客户端可能已断开）: {e}")

    def send_html(self, html, status=200):
        try:
            body = html.encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Connection', 'close')
            self.end_headers()
            self.wfile.write(body)
        except Exception as e:
            debug_print(f"[HTTP] 页面发送失败（客户端可能已断开）: {e}")

    def handle(self):
        # IP 封禁检查：被封禁的 IP 直接断开连接，不返回任何响应
        # dual-stack 监听下 IPv4 客户端呈现为 ::ffff:1.2.3.4，统一规范化为纯 IPv4，
        # 与 banip CLI / data.db 存储 key 一致，避免表示差异导致误判或重复计数
        client_ip = _normalize_ip(self.client_address[0])
        self._client_ip = client_ip
        if data_db.is_ip_banned(client_ip):
            try:
                self.connection.shutdown(socket.SHUT_RDWR)
            except Exception:
                pass
            try:
                self.connection.close()
            except Exception:
                pass
            return
        try:
            self.connection.settimeout(self.REQUEST_TIMEOUT)
            super().handle()
        except socket.timeout:
            log_error(f"请求超时: {self.path}")
            try:
                self.send_json({'success': False, 'message': '请求超时'}, 408)
            except Exception:
                pass
        except Exception as e:
            log_error(f"请求处理异常: {e}")

    def _read_json_body(self):
        try:
            content_length = int(self.headers.get('Content-Length', 0))
            if content_length < 0:
                self.send_json({'success': False, 'message': 'Content-Length 不合法'}, 400)
                return None
            if content_length > cfg.MAX_CONTENT_LENGTH:
                self.send_json({'success': False, 'message': '请求体过大'}, 413)
                return None
            body = self.rfile.read(content_length).decode('utf-8')
            return json.loads(body) if content_length > 0 else {}
        except json.JSONDecodeError:
            self.send_json({'success': False, 'message': 'JSON格式错误'}, 400)
            return None
        except Exception as e:
            self.send_json({'success': False, 'message': str(e)}, 500)
            return None

    def _get_param(self, data, *names):
        for name in names:
            value = data.get(name)
            if value is not None:
                if isinstance(value, str):
                    stripped = value.strip()
                    return stripped if stripped else None
                return value
        return None

    def _get_sanitized_param(self, data, *names):
        for name in names:
            value = data.get(name)
            if value is not None:
                if isinstance(value, str):
                    stripped = value.strip()
                    if stripped:
                        stripped = stripped.translate(cfg._SANITIZE_TABLE)
                        while '__' in stripped:
                            stripped = stripped.replace('__', '_')
                        stripped = stripped.strip('_')
                    return stripped if stripped else None
                return value
        return None

    def _check_auth(self, data=None):
        """两层认证：第一层 AUTH_KEY（admin_config.json 的 auth_key 字段，支持热更新），
        第二层 用户名+密码（data.db 的 users 表，区分 admin/user 角色）

        凭证传递方式（按优先级）：
        1. Authorization: Bearer <token> 请求头（POST /login 签发，所有业务接口通用）
        2. 请求体 key/user/password 字段（仅 POST，兼容猫抓插件等第三方调用方）
        不再支持 URL 查询参数传凭证（URL 会进入浏览器历史与各级访问日志，存在泄露风险）
        """
        if not cfg.auth_key:
            return True

        # 方式 1：Bearer 令牌。携带令牌时仅校验令牌本身（签名/有效期/吊销/用户启用），
        # 令牌即已通过两层认证的凭证，无效令牌直接拒绝，不回退到明文凭证
        auth_header = self.headers.get('Authorization', '')
        if auth_header.startswith('Bearer '):
            token = auth_header[len('Bearer '):].strip()
            claims = verify_token_claims(token) if token else None
            username = verify_auth_token(token) if token else None
            if username:
                # 认证成功：清除该 IP 的失败计数，避免历史偶发失误累积导致误封
                data_db.clear_auth_failure(self._client_ip)
                self.authenticated_user = username
                self.authenticated_role = (claims.get('role') if claims else None) \
                    or data_db.user_role(username) or 'user'
                return True
            # 签名有效但账号已被禁用：明确提示且不计入 IP 封禁（用户已被管理员禁用）
            if claims and data_db.user_exists(claims.get('user', '')) \
                    and not data_db.is_user_active(claims['user']):
                log_error("认证失败：账号已被禁用")
                self.send_json({'success': False, 'message': '账号已被禁用，请联系管理员'}, 403)
                return False
            log_error("认证失败：令牌无效或已过期")
            _record_failure_and_log(self._client_ip)
            self.send_json({'success': False, 'message': '登录已过期，请重新登录'}, 403)
            return False

        # 方式 2：请求体凭证（POST 专用，GET 无请求体，也不再支持查询参数）
        def _get_field(*names):
            if data:
                val = self._get_param(data, *names)
                if val is not None:
                    return val
            return None

        # 第一层：AUTH_KEY（admin_config.json，管理网页可热更新），通过 key/auth_key/token 字段传入
        # 第一层失败计入 IP 封禁计数（IP 级拦截）
        request_key = _get_field('key', 'auth_key', 'token')
        if request_key is None or not hmac.compare_digest(request_key, cfg.auth_key):
            log_error("认证失败：第一层 AUTH_KEY 校验未通过")
            # AUTH_KEY 错误，计入认证失败次数（阶梯封禁：首次临时、再次永久）
            _record_failure_and_log(self._client_ip)
            self.send_json({'success': False, 'message': '认证失败，密钥不正确'}, 403)
            return False

        # 未初始化拦截：data.db 中无任何用户时，拒绝所有业务请求（/health 在此之前已放行）。
        # 不计入 IP 封禁（AUTH_KEY 已正确，属部署未完成而非攻击）；userctl/adminctl add 后实时生效。
        if data_db.user_count() == 0:
            log_error(f"系统未初始化（无用户），拒绝请求: {self.path}")
            self.send_json({
                'success': False,
                'message': '系统尚未初始化：无可用用户，请在容器内执行 adminctl add 或 userctl add 添加用户后重试'
            }, 503)
            return False

        # 第二层：用户名+密码（data.db 的 users 表），通过 user/password 字段传入
        # 分两种失败路径：
        #   - 用户不存在 → IP 级封禁（10 次触发，防扫描爆破）
        #   - 用户存在但密码错误 → 账号级封禁（5 次触发，自动禁用该账号）
        request_user = _get_field('user', 'usr')
        request_password = _get_field('password')

        # 用户不存在 → IP 级封禁
        if not request_user or not data_db.user_exists(request_user):
            log_error("认证失败：用户名或密码不正确")
            _record_failure_and_log(self._client_ip)
            self.send_json({'success': False, 'message': '认证失败，用户名或密码不正确'}, 403)
            return False

        # 账号已禁用（管理员手动禁用 或 密码错误自动禁用）
        # 首次尝试：提示警告
        # 再次尝试：直接封 IP（封禁后连接会被直接断开，无需返回响应）
        if not data_db.is_user_active(request_user):
            ip = self._client_ip
            if ip in _banned_account_warned_ips:
                data_db.add_banned_ip(ip)
                log_error(f"IP {ip} 反复尝试已封禁账号 {request_user}，已直接封禁 IP")
                self.send_json({'success': False, 'message': '账号已被封禁'}, 403)
            else:
                _banned_account_warned_ips.add(ip)
                log_error(f"认证失败：账号 {request_user} 已被禁用（IP {ip} 首次尝试，仅提示）")
                self.send_json({'success': False,
                                'message': '该账号已被封禁，再次尝试将封禁您的 IP 地址'}, 403)
            return False

        # 密码错误（用户存在）→ 账号级封禁
        if not request_password or not data_db.verify_user(request_user, request_password):
            log_error(f"认证失败：密码不正确（用户: {request_user}）")
            locked = data_db.record_account_failure(request_user)
            if locked:
                log_error(f"账号 {request_user} 因连续 {data_db.MAX_ACCOUNT_FAILURES} 次密码错误已被自动禁用")
                self.send_json({'success': False,
                                'message': f'密码错误次数过多，账号已被禁用，请联系管理员'}, 403)
            else:
                remaining = data_db.MAX_ACCOUNT_FAILURES - data_db.get_account_failure_count(request_user)
                self.send_json({'success': False,
                                'message': f'认证失败，密码不正确（剩余 {remaining} 次机会）'}, 403)
            return False

        # 记录已认证用户与角色，供下载目录分流与管理员鉴权
        # 认证成功：清除该 IP 和该账号的失败计数
        data_db.clear_auth_failure(self._client_ip)
        data_db.clear_account_failure(request_user)
        self.authenticated_user = request_user
        self.authenticated_role = data_db.user_role(request_user) or 'user'
        return True

    def _require_admin(self):
        """管理员权限校验（在 _check_auth 通过后调用）。返回 True/False 并已发送响应。"""
        if getattr(self, 'authenticated_role', 'user') != 'admin':
            log_error(f"非管理员访问管理接口被拒绝: {self.path} (用户: {getattr(self, 'authenticated_user', '?')})")
            self.send_json({'success': False, 'message': '需要管理员权限'}, 403)
            return False
        return True

    def _require_download_user(self):
        """下载用户身份校验：管理员不参与下载（无个人过滤规则/下载目录隔离需求）。"""
        if getattr(self, 'authenticated_role', 'user') == 'admin':
            log_error(f"管理员账户被拒绝执行下载相关操作: {self.path}")
            self.send_json({'success': False,
                            'message': '管理员账户不能发起下载，请使用下载用户账号'}, 403)
            return False
        return True

    def get_path(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if cfg.url_prefix:
            prefix_pattern = f'/{cfg.url_prefix}'
            if path == prefix_pattern:
                return None
            if path.startswith(prefix_pattern + '/'):
                return path[len(prefix_pattern):]
            # URL_PREFIX/网页链接错误：仅返回 404，不计入封禁计数
            # （扫描器探测、浏览器误访问、链接敲错等不触发 IP 封禁）
            debug_print(f"[HTTP] 路径前缀不正确，拒绝请求: {path}")
            return None

        return path

    def _check_rate_limit(self):
        client_ip = self._client_ip
        allowed, _ = check_rate_limit(client_ip)
        if not allowed:
            self.send_json({'success': False, 'message': '请求过于频繁，请稍后再试'}, 429)
            return False
        return True

    def _mask_task(self, task):
        """返回隐藏敏感字段的任务副本"""
        return {k: v for k, v in task.items() if k not in cfg._SENSITIVE_TASK_FIELDS}

    def do_GET(self):
        raw_path = urllib.parse.urlparse(self.path).path

        # /{prefix}（无尾斜杠）重定向到登录页规范地址，便于浏览器直接打开网页控制台
        if cfg.url_prefix and raw_path == f'/{cfg.url_prefix}':
            self.send_response(302)
            self.send_header('Location', f'/{cfg.url_prefix}/login.html')
            self.send_header('Content-Length', '0')
            self.send_header('Connection', 'close')
            self.end_headers()
            return

        path = self.get_path()
        if path is None:
            self.send_response(404)
            self.send_header('Content-Type', 'text/plain')
            self.end_headers()
            self.wfile.write(b'404 Not Found')
            return

        # 网页规范地址统一为 /login.html、/user.html、/admin.html；
        # 旧入口（根路径、/index.html、/login、/user、/admin 及带尾斜杠形式、/admin/index.html）
        # 一律 302 跳转到对应规范地址（仅 GET 页面；POST /login 等 API 不受影响）
        page_redirects = {
            '/': '/login.html',
            '/index.html': '/login.html',
            '/login': '/login.html',
            '/login/': '/login.html',
            '/user': '/user.html',
            '/user/': '/user.html',
            '/admin': '/admin.html',
            '/admin/': '/admin.html',
            '/admin/index.html': '/admin.html',
        }
        if path in page_redirects:
            base = f'/{cfg.url_prefix}' if cfg.url_prefix else ''
            self.send_response(302)
            self.send_header('Location', f'{base}{page_redirects[path]}')
            self.send_header('Content-Length', '0')
            self.send_header('Connection', 'close')
            self.end_headers()
            return

        # 网页图标
        if path == '/favicon.png' or path == '/favicon.ico':
            # 查找顺序：同目录（容器内平铺布局）→ ../web/（仓库源码布局）
            base = os.path.dirname(os.path.abspath(__file__))
            ico_path = os.path.join(base, 'favicon.ico')
            if not os.path.isfile(ico_path):
                ico_path = os.path.join(base, '..', 'web', 'favicon.ico')
            if os.path.isfile(ico_path):
                try:
                    with open(ico_path, 'rb') as f:
                        body = f.read()
                    self.send_response(200)
                    self.send_header('Content-Type', 'image/x-icon')
                    self.send_header('Content-Length', str(len(body)))
                    self.send_header('Cache-Control', 'public, max-age=86400')
                    self.send_header('Connection', 'close')
                    self.end_headers()
                    self.wfile.write(body)
                except Exception as e:
                    debug_print(f"[HTTP] 图标发送失败（客户端可能已断开）: {e}")
            return

        # 登录页：静态外壳，认证在页面内的 API 调用中完成（仅规范地址提供页面）
        if path == '/login.html':
            self.send_html(get_login_html())
            return

        # 下载控制台：普通用户页面
        if path == '/user.html':
            self.send_html(get_user_html())
            return

        # 管理网页：独立静态外壳（用户管理 / AUTH_KEY），认证在页面内的 API 调用中完成
        if path == '/admin.html':
            self.send_html(get_admin_html())
            return

        if path == '/health':
            self.send_json({'success': True, 'status': 'ok'})
            return

        # 认证必须在速率限制之前，防止未认证请求占用限流配额（DoS 防护）
        data = {}
        if not self._check_auth(data):
            return

        if not self._check_rate_limit():
            return

        if path == '/config':
            self.send_json({'success': True, 'data': {
                'api_port': cfg.bound_port or cfg.server_port,
                'url_prefix': cfg.url_prefix,
                'ssrf_protection': cfg.ssrf_protection,
                'max_concurrent_tasks': cfg.max_concurrent_tasks,
                'same_video_mode': cfg.same_video_by_filename_enabled,
                'keywords_enabled': cfg.keywords_enabled,
                'ad_keyword_count': len(cfg.ad_keywords),
                'filename_filter_enabled': cfg.filename_filter_enabled,
                'filename_dedup_enabled': cfg.filename_dedup_enabled,
                'user_count': data_db.download_user_count(),
                'auth_key_masked': '***' if cfg.auth_key else '',
                'version': cfg.version,
            }})
        elif path == '/admin/users':
            if not self._require_admin():
                return
            users = [
                {'username': u, 'role': r, 'disabled': bool(d), 'created_at': c}
                for (u, r, d, c) in data_db.list_users_full()
            ]
            self.send_json({'success': True, 'data': users})
        elif path == '/admin/bans':
            if not self._require_admin():
                return
            bans = [
                {'ip': ip, 'banned_at': banned_at, 'reason': reason}
                for (ip, banned_at, reason) in data_db.list_banned_ips()
            ]
            self.send_json({'success': True, 'data': bans})
        elif path == '/admin/filters':
            # 全局过滤规则模板（config/filter_rules.json），新用户首启时复制
            if not self._require_admin():
                return
            raw = getattr(cfg, 'filters_raw', {}) or {}
            kw = raw.get('keywords') if isinstance(raw.get('keywords'), dict) else {}
            ff = raw.get('filename_filter') if isinstance(raw.get('filename_filter'), dict) else {}
            dd = raw.get('filename_dedup') if isinstance(raw.get('filename_dedup'), dict) else {}
            self.send_json({'success': True, 'data': {
                'keywords': {
                    'enabled': bool(kw.get('enabled', False)),
                    'list': [str(k) for k in kw.get('list', []) if str(k).strip()],
                },
                'filename_filter': {
                    'enabled': bool(ff.get('enabled', False)),
                    'list': [str(k) for k in ff.get('list', []) if str(k).strip()],
                },
                'filename_dedup': {
                    'enabled': bool(dd.get('enabled', False)),
                    'rules': [
                        {'pattern': str(r.get('pattern', '') or ''),
                         'replacement': str(r.get('replacement', '') or '')}
                        for r in dd.get('rules', []) if isinstance(r, dict)
                    ],
                },
            }})
        elif path == '/tasks':
            with cfg.tasks_lock:
                current_user = self.authenticated_user
                user_tasks = [self._mask_task(t) for t in cfg.tasks.values()
                              if t.get('user', '') == current_user]
                self.send_json({'success': True, 'data': user_tasks})
        elif path.startswith('/tasks/'):
            task_id = path.split('/')[2]
            with cfg.tasks_lock:
                task = cfg.tasks.get(task_id)
                if task and task.get('user', '') == self.authenticated_user:
                    self.send_json({'success': True, 'data': self._mask_task(task)})
                else:
                    self.send_json({'success': False, 'message': '任务不存在'}, 404)
        elif path == '/filters':
            # 用户各自的过滤规则（user/<名>/filter_rules.json）
            if not self._require_download_user():
                return
            username = self.authenticated_user
            raw = get_user_rules(username).get('raw') or {}
            kw = raw.get('keywords') if isinstance(raw.get('keywords'), dict) else {}
            ff = raw.get('filename_filter') if isinstance(raw.get('filename_filter'), dict) else {}
            dd = raw.get('filename_dedup') if isinstance(raw.get('filename_dedup'), dict) else {}
            self.send_json({'success': True, 'data': {
                'keywords': {
                    'enabled': bool(kw.get('enabled', False)),
                    'list': [str(k) for k in kw.get('list', []) if str(k).strip()],
                },
                'filename_filter': {
                    'enabled': bool(ff.get('enabled', False)),
                    'list': [str(k) for k in ff.get('list', []) if str(k).strip()],
                },
                'filename_dedup': {
                    'enabled': bool(dd.get('enabled', False)),
                    'rules': [
                        {'pattern': str(r.get('pattern', '') or ''),
                         'replacement': str(r.get('replacement', '') or '')}
                        for r in dd.get('rules', []) if isinstance(r, dict)
                    ],
                },
            }})
        else:
            self.send_json({'success': False, 'message': '路径不存在'}, 404)

    def do_POST(self):
        path = self.get_path()
        if path is None:
            self.send_response(404)
            self.send_header('Content-Type', 'text/plain')
            self.end_headers()
            self.wfile.write(b'404 Not Found')
            return

        # 登录接口：请求体提交 key/user/password，两层认证通过后签发访问令牌。
        # 认证同样先于限流（DoS 防护），失败计入 IP 封禁（与其他接口一致）
        if path == '/login':
            data = self._read_json_body()
            if data is None:
                return

            if not self._check_auth(data):
                return

            if not self._check_rate_limit():
                return

            self.send_json({'success': True, 'data': {
                'token': issue_auth_token(self.authenticated_user,
                                          getattr(self, 'authenticated_role', 'user')),
                'expiresIn': TOKEN_TTL_SECONDS,
                'role': getattr(self, 'authenticated_role', 'user'),
            }})
        # 切换用户：当前用户已持有效 Bearer 令牌（无需 AUTH_KEY），
        # 输入目标账户用户名+密码，校验通过后吊销当前令牌并为目标账户签发新令牌。
        # 允许跨角色切换（用户↔管理员），只要知道目标账户密码。
        elif path == '/switch-user':
            data = self._read_json_body()
            if data is None:
                return

            if not self._check_auth(data):
                return

            if not self._check_rate_limit():
                return

            target_user = self._get_param(data, 'username', 'user')
            target_password = self._get_param(data, 'password')
            if not target_user or not target_password:
                self.send_json({'success': False, 'message': '用户名和密码不能为空'}, 400)
                return

            # 目标用户不存在
            if not data_db.user_exists(target_user):
                self.send_json({'success': False, 'message': '目标用户不存在'}, 403)
                return

            # 目标用户被禁用
            if not data_db.is_user_active(target_user):
                self.send_json({'success': False, 'message': '目标账号已被禁用'}, 403)
                return

            # 校验目标密码（密码错误计入目标账号失败计数，连续错误会自动禁用目标账号）
            if not data_db.verify_user(target_user, target_password):
                locked = data_db.record_account_failure(target_user)
                if locked:
                    self.send_json({'success': False,
                                    'message': '密码错误次数过多，目标账号已被禁用'}, 403)
                else:
                    remaining = data_db.MAX_ACCOUNT_FAILURES - data_db.get_account_failure_count(target_user)
                    self.send_json({'success': False,
                                    'message': f'密码不正确（剩余 {remaining} 次机会）'}, 403)
                return

            # 密码正确：清除目标账号失败计数
            data_db.clear_account_failure(target_user)

            # 吊销当前令牌（切换后旧令牌立即失效）
            auth_header = self.headers.get('Authorization', '')
            token = auth_header[len('Bearer '):].strip()
            claims = get_token_claims(token)
            if claims and claims.get('jti'):
                data_db.revoke_auth_token(claims['jti'])

            # 为目标账户签发新令牌
            target_role = data_db.user_role(target_user) or 'user'
            self.send_json({'success': True, 'data': {
                'token': issue_auth_token(target_user, target_role),
                'expiresIn': TOKEN_TTL_SECONDS,
                'role': target_role,
            }})
        # 注销：吊销当前 Bearer 令牌（服务端 auth_tokens 表置 revoked），
        # 使该令牌在所有设备上立即失效；此后仅清理本地副本
        elif path == '/logout':
            data = self._read_json_body()
            if data is None:
                return

            if not self._check_auth(data):
                return

            if not self._check_rate_limit():
                return

            auth_header = self.headers.get('Authorization', '')
            token = auth_header[len('Bearer '):].strip()
            claims = get_token_claims(token)
            if claims and claims.get('jti'):
                data_db.revoke_auth_token(claims['jti'])
            self.send_json({'success': True, 'message': '已注销，令牌已失效'})
        # 修改自己密码：校验旧密码后更新并吊销全部令牌（改密即全端下线）
        elif path == '/password':
            try:
                data = self._read_json_body()
                if data is None:
                    return

                if not self._check_auth(data):
                    return

                if not self._check_rate_limit():
                    return

                username = self.authenticated_user
                old_password = self._get_param(data, 'oldPassword', 'old_password', 'oldPwd')
                new_password = self._get_param(data, 'newPassword', 'new_password', 'newPwd')
                if not old_password or not new_password:
                    self.send_json({'success': False, 'message': '旧密码与新密码不能为空'}, 400)
                    return
                if len(new_password) < 6:
                    self.send_json({'success': False, 'message': '新密码至少 6 位'}, 400)
                    return
                # 旧密码校验：错误计入 IP 封禁计数（防令牌泄露后暴力试旧密码）
                if not data_db.verify_user(username, old_password):
                    log_error(f"修改密码失败：旧密码不正确 (用户: {username})")
                    _record_failure_and_log(self._client_ip)
                    # 返回 400 而非 403：网页端 403 统一按"登录失效"处理会误登出
                    self.send_json({'success': False, 'message': '旧密码不正确'}, 400)
                    return
                data_db.change_password(username, new_password)
                log_info(f"用户修改密码: {username}（全部登录令牌已吊销）")
                self.send_json({'success': True,
                                'message': '密码已修改，所有登录已失效，请使用新密码重新登录'})
            except Exception as e:
                self.send_json({'success': False, 'message': str(e)}, 500)
        # 全局过滤规则模板编辑：保存到 config/filter_rules.json，新用户首启时复制
        elif path == '/admin/filters':
            try:
                data = self._read_json_body()
                if data is None:
                    return

                if not self._check_auth(data):
                    return

                if not self._check_rate_limit():
                    return

                if not self._require_admin():
                    return

                kw = data.get('keywords') if isinstance(data.get('keywords'), dict) else None
                ff = data.get('filename_filter') if isinstance(data.get('filename_filter'), dict) else None
                dd = data.get('filename_dedup') if isinstance(data.get('filename_dedup'), dict) else None
                if kw is None or ff is None or dd is None:
                    self.send_json({'success': False, 'message': '缺少 keywords / filename_filter / filename_dedup 字段'}, 400)
                    return

                kw_list = [str(k).strip() for k in kw.get('list', []) if str(k).strip()]
                ff_list = [str(k).strip() for k in ff.get('list', []) if str(k).strip()]
                rules_out = []
                for rule in dd.get('rules', []):
                    if not isinstance(rule, dict):
                        continue
                    pattern = str(rule.get('pattern', '') or '').strip()
                    replacement = str(rule.get('replacement', '') or '')
                    if not pattern:
                        continue
                    try:
                        re.compile(pattern)
                    except re.error as e:
                        self.send_json({'success': False,
                                        'message': f'正则表达式不合法: {pattern} ({e})'}, 400)
                        return
                    rules_out.append({'pattern': pattern, 'replacement': replacement})

                new_rules = {
                    'keywords': {'enabled': bool(kw.get('enabled', False)), 'list': kw_list},
                    'filename_filter': {'enabled': bool(ff.get('enabled', False)), 'list': ff_list},
                    'filename_dedup': {'enabled': bool(dd.get('enabled', False)), 'rules': rules_out},
                }
                cfg._write_json_atomic(cfg.FILTER_RULES_FILE, new_rules, mode=0o644)
                cfg.load_filters()
                log_info(f"管理员更新过滤规则模板（拦截关键字 {len(kw_list)} / 文件名过滤 {len(ff_list)} / 去重规则 {len(rules_out)}）")
                self.send_json({'success': True, 'message': '过滤规则模板已保存，新用户将使用此模板'})
            except Exception as e:
                self.send_json({'success': False, 'message': str(e)}, 500)
        # 用户过滤规则编辑：读取见 GET /filters；此处整体保存（原子写回，立即生效）
        elif path == '/filters':
            try:
                data = self._read_json_body()
                if data is None:
                    return

                if not self._check_auth(data):
                    return

                if not self._check_rate_limit():
                    return

                if not self._require_download_user():
                    return

                username = self.authenticated_user
                kw = data.get('keywords') if isinstance(data.get('keywords'), dict) else None
                ff = data.get('filename_filter') if isinstance(data.get('filename_filter'), dict) else None
                dd = data.get('filename_dedup') if isinstance(data.get('filename_dedup'), dict) else None
                if kw is None or ff is None or dd is None:
                    self.send_json({'success': False, 'message': '缺少 keywords / filename_filter / filename_dedup 字段'}, 400)
                    return

                kw_list = kw.get('list', [])
                ff_list = ff.get('list', [])
                dd_rules = dd.get('rules', [])
                if not isinstance(kw_list, list) or not isinstance(ff_list, list) or not isinstance(dd_rules, list):
                    self.send_json({'success': False, 'message': 'list / rules 字段必须为数组'}, 400)
                    return
                kw_list = [str(k).strip() for k in kw_list if str(k).strip()]
                ff_list = [str(k).strip() for k in ff_list if str(k).strip()]

                rules_out = []
                for rule in dd_rules:
                    if not isinstance(rule, dict):
                        continue
                    pattern = str(rule.get('pattern', '') or '').strip()
                    replacement = str(rule.get('replacement', '') or '')
                    if not pattern:
                        continue
                    try:
                        re.compile(pattern)
                    except re.error as e:
                        self.send_json({'success': False,
                                        'message': f'正则表达式不合法: {pattern} ({e})'}, 400)
                        return
                    rules_out.append({'pattern': pattern, 'replacement': replacement})

                new_rules = {
                    'keywords': {'enabled': bool(kw.get('enabled', False)), 'list': kw_list},
                    'filename_filter': {'enabled': bool(ff.get('enabled', False)), 'list': ff_list},
                    'filename_dedup': {'enabled': bool(dd.get('enabled', False)), 'rules': rules_out},
                }
                save_user_rules(username, new_rules)
                log_info(f"用户更新过滤规则: {username}（拦截关键字 {len(kw_list)} / 文件名过滤 {len(ff_list)} / 去重规则 {len(rules_out)}）")
                self.send_json({'success': True,
                                'message': '过滤规则已保存，对新增下载任务立即生效'})
            except Exception as e:
                self.send_json({'success': False, 'message': str(e)}, 500)
        elif path == '/download':
            try:
                data = self._read_json_body()
                if data is None:
                    return

                if not self._check_auth(data):
                    return

                if not self._check_rate_limit():
                    return

                # 管理员不参与下载（下载用户专属）
                if not self._require_download_user():
                    return

                url = self._get_param(data, 'url', 'URL')
                if not url:
                    self.send_json({'success': False, 'message': 'URL不能为空'}, 400)
                    return

                if not is_safe_url(url):
                    log_error(f"SSRF 防护：拦截不安全的 URL: {sanitize_url_for_log(url)}")
                    self.send_json({'success': False, 'message': 'URL不合法或指向内网地址，已拒绝'}, 400)
                    return

                save_name = self._get_sanitized_param(data, 'saveName', 'save_name', 'name', 'filename', 'title')
                referer = self._get_param(data, 'referer', 'Referer', 'referrer')
                cookie = self._get_param(data, 'cookie', 'Cookie')
                user_agent = self._get_param(data, 'userAgent', 'user_agent', 'User-Agent', 'ua')
                # 网页控制台与猫抓插件均可逐任务指定输出格式（mp4/mkv），不传时默认 mp4
                output_format = self._get_param(data, 'format', 'output_format', 'outputFormat')

                # 限制最大并发任务数，防止资源耗尽
                with cfg.tasks_lock:
                    active_count = sum(1 for t in cfg.tasks.values() if t.get('status') in ('running', 'collecting'))
                if active_count >= cfg.max_concurrent_tasks:
                    log_error(f"并发任务数已达上限 ({cfg.max_concurrent_tasks})，拒绝新任务")
                    self.send_json({'success': False, 'message': f'并发任务数已达上限({cfg.max_concurrent_tasks})，请稍后再试'}, 429)
                    return

                is_ad, keyword = is_ad_content(save_name, url, user=self.authenticated_user)
                if is_ad:
                    log_info(f"已拦截广告: {save_name}")
                    debug_print(f"[HTTP] 广告拦截命中关键字: {keyword}，URL: {sanitize_url_for_log(url)[:80]}")
                    self.send_json({
                        'success': False,
                        'message': f'检测到广告内容，已拦截。关键字: {keyword}',
                        'blocked': True,
                        'keyword': keyword
                    }, 200)
                    return

                task_id, is_duplicate = run_download(url, save_name, referer, cookie, user_agent, user=getattr(self, 'authenticated_user', None), output_format=output_format)

                if task_id is None:
                    self.send_json({
                        'success': False,
                        'message': '文件已存在，跳过下载',
                        'duplicate': True
                    })
                else:
                    # 返回实际使用的输出格式（网页/插件传了 format 时为 per-task 值，否则默认 mp4）
                    _fmt = output_format if output_format in ('mp4', 'mkv') else cfg.output_format
                    self.send_json({
                        'success': True,
                        'taskId': task_id,
                        'message': '检测到重复链接，已复用任务' if is_duplicate else '下载任务已添加',
                        'duplicate': is_duplicate,
                        'output_format': _fmt
                    })
            except Exception as e:
                self.send_json({'success': False, 'message': str(e)}, 500)
        elif path == '/reload':
            try:
                data = self._read_json_body()
                if data is None:
                    return

                if not self._check_auth(data):
                    return

                if not self._check_rate_limit():
                    return

                if not self._require_admin():
                    return

                # 重载仅作用于管理员热配置（admin_config.json：auth_key）
                # 与过滤规则（filter_rules.json）；config.json 为系统级配置，
                # 仅系统管理员修改且重启容器后生效，不随 reload 读取
                old_auth_key = cfg.auth_key
                cfg.load_filters()
                cfg.load_admin_config()
                # /reload 时重连数据库（关闭旧连接、重新打开、确保表结构）
                data_db.reconnect_db()
                # 检查用户数（del_user 已防删空，此处防外部替换 data.db 为空库）
                _uc = data_db.user_count()
                if _uc == 0:
                    log_error("警告: 重载后 data.db 中无用户，请运行: adminctl add <用户名> 或 userctl add <用户名>")
                else:
                    log_info(f"系统重载配置完成（当前用户 {_uc} 个）")

                # AUTH_KEY 变更后旧令牌签名立即失效，同时全量吊销登记令牌（双保险）
                if cfg.auth_key != old_auth_key:
                    data_db.revoke_all_tokens()
                    debug_print("[启动] reload 检测到 AUTH_KEY 变更，已吊销全部令牌")

                self.send_json({'success': True, 'message': '配置已重新加载'})
            except Exception as e:
                self.send_json({'success': False, 'message': str(e)}, 500)
        elif path.startswith('/admin/'):
            try:
                data = self._read_json_body()
                if data is None:
                    return

                if not self._check_auth(data):
                    return

                if not self._check_rate_limit():
                    return

                if not self._require_admin():
                    return

                if path == '/admin/auth-key':
                    new_key = self._get_param(data, 'newKey', 'new_key', 'authKey')
                    if not new_key or len(new_key) < 8:
                        self.send_json({'success': False, 'message': '新 AUTH_KEY 长度不能少于 8 位'}, 400)
                        return
                    cfg.save_auth_key(new_key)
                    # 令牌签名密钥源自 AUTH_KEY，旧令牌签名即刻失效；登记令牌一并全量吊销
                    data_db.revoke_all_tokens()
                    log_info("管理员更新 AUTH_KEY（全员需重新登录）")
                    self.send_json({'success': True,
                                    'message': 'AUTH_KEY 已更新，所有登录已失效，请使用新 KEY 重新登录'})
                elif path == '/admin/users/add':
                    username = self._get_param(data, 'username', 'user')
                    password = self._get_param(data, 'password', 'newPassword')
                    if not username or not password:
                        self.send_json({'success': False, 'message': '用户名和密码不能为空'}, 400)
                        return
                    try:
                        data_db.add_user(username, password, role='user')
                    except ValueError as e:
                        self.send_json({'success': False, 'message': str(e)}, 400)
                        return
                    log_info(f"管理员添加用户: {username}")
                    self.send_json({'success': True, 'message': f'已添加用户: {username}'})
                elif path == '/admin/users/delete':
                    username = self._get_param(data, 'username', 'user')
                    if not username:
                        self.send_json({'success': False, 'message': '用户名不能为空'}, 400)
                        return
                    role = data_db.user_role(username)
                    if role is None:
                        self.send_json({'success': False, 'message': f'用户不存在: {username}'}, 400)
                        return
                    if role == 'admin':
                        self.send_json({'success': False,
                                        'message': '管理员账户请使用 adminctl 命令行工具管理'}, 400)
                        return
                    # 删除用户全部数据：终止其任务 + 删除 user/<名>、temp/<名>、downloads/<名>
                    killed, cleanup_ok = cleanup_user_data(username)
                    data_db.del_user(username)
                    log_info(f"管理员删除用户: {username}（终止任务 {killed} 个，文件清理{'成功' if cleanup_ok else '存在失败'}）")
                    msg = f'已删除用户: {username}（其全部任务与文件已一并清除）'
                    self.send_json({'success': True if cleanup_ok else False, 'message': msg})
                elif path == '/admin/users/password':
                    username = self._get_param(data, 'username', 'user')
                    new_password = self._get_param(data, 'newPassword', 'password', 'new_password')
                    if not username or not new_password:
                        self.send_json({'success': False, 'message': '用户名和新密码不能为空'}, 400)
                        return
                    role = data_db.user_role(username)
                    if role is None:
                        self.send_json({'success': False, 'message': f'用户不存在: {username}'}, 400)
                        return
                    if role == 'admin':
                        self.send_json({'success': False,
                                        'message': '管理员账户请使用 adminctl password 命令修改'}, 400)
                        return
                    try:
                        data_db.change_password(username, new_password)
                    except ValueError as e:
                        self.send_json({'success': False, 'message': str(e)}, 400)
                        return
                    log_info(f"管理员重置密码: {username}")
                    self.send_json({'success': True, 'message': f'已重置用户密码: {username}'})
                elif path in ('/admin/users/ban', '/admin/users/unban'):
                    username = self._get_param(data, 'username', 'user')
                    if not username:
                        self.send_json({'success': False, 'message': '用户名不能为空'}, 400)
                        return
                    role = data_db.user_role(username)
                    if role is None:
                        self.send_json({'success': False, 'message': f'用户不存在: {username}'}, 400)
                        return
                    if role == 'admin':
                        self.send_json({'success': False,
                                        'message': '管理员账户不可禁用，请使用 adminctl 命令行工具管理'}, 400)
                        return
                    flag = (path == '/admin/users/ban')
                    data_db.set_user_disabled(username, flag)
                    log_info(f"管理员{'禁用用户' if flag else '解禁用户'}: {username}")
                    self.send_json({'success': True,
                                    'message': f"已{'禁用' if flag else '解禁'}用户: {username}"})
                elif path == '/admin/bans/add':
                    ip = self._get_param(data, 'ip')
                    if not ip:
                        self.send_json({'success': False, 'message': 'IP 地址不能为空'}, 400)
                        return
                    ip = ip.strip()
                    try:
                        ip = str(ipaddress.ip_address(ip))
                    except ValueError:
                        self.send_json({'success': False, 'message': f'无效的 IP 地址: {ip}'}, 400)
                        return
                    data_db.add_banned_ip(ip)
                    log_info(f"管理员手动封禁 IP: {ip}")
                    self.send_json({'success': True, 'message': f'已封禁 IP: {ip}'})
                elif path == '/admin/bans/delete':
                    ip = self._get_param(data, 'ip')
                    if not ip:
                        self.send_json({'success': False, 'message': 'IP 地址不能为空'}, 400)
                        return
                    ip = ip.strip()
                    banned = {row[0] for row in data_db.list_banned_ips()}
                    if ip not in banned:
                        self.send_json({'success': False, 'message': f'该 IP 不在封禁列表中: {ip}'}, 400)
                        return
                    data_db.remove_banned_ip(ip)
                    log_info(f"管理员解封 IP: {ip}")
                    self.send_json({'success': True,
                                    'message': f'已解封 IP: {ip}（失败计数与阶梯封禁统计已一并清除）'})
                else:
                    self.send_json({'success': False, 'message': '路径不存在'}, 404)
            except Exception as e:
                self.send_json({'success': False, 'message': str(e)}, 500)
        elif path in ('/task/pause', '/task/resume', '/task/delete'):
            try:
                data = self._read_json_body()
                if data is None:
                    return

                if not self._check_auth(data):
                    return

                if not self._check_rate_limit():
                    return

                task_id = self._get_param(data, 'taskId', 'task_id', 'id')
                if not task_id:
                    self.send_json({'success': False, 'message': 'taskId不能为空'}, 400)
                    return

                if path == '/task/pause':
                    ok, message = pause_task(task_id)
                elif path == '/task/resume':
                    ok, message = resume_paused_task(task_id)
                else:
                    ok, message = delete_task(task_id)

                debug_print(f"[HTTP] 任务操作 {path}: taskId={task_id}, 结果={ok}")
                self.send_json({'success': ok, 'message': message}, 200 if ok else 400)
            except Exception as e:
                self.send_json({'success': False, 'message': str(e)}, 500)
        else:
            self.send_json({'success': False, 'message': '路径不存在'}, 404)

    def log_message(self, format, *args):
        pass


class TimeoutHTTPServer(http.server.ThreadingHTTPServer):
    # AF_INET6 + 绑定 '::'：Linux 默认 IPV6_V6ONLY=0，单个 socket 同时接收
    # IPv4 与 IPv6 连接（dual-stack）。IPv4 客户端在 socket 层呈现为
    # ::ffff:1.2.3.4，由 _normalize_ip 还原为纯 IPv4。
    address_family = socket.AF_INET6
    allow_reuse_address = True

    def __init__(self, server_address, RequestHandlerClass, bind_and_activate=True):
        super().__init__(server_address, RequestHandlerClass, bind_and_activate)
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.timeout = 60


def start_server(port):
    cfg.server_instance = TimeoutHTTPServer(('::', port), DownloadHandler)
    cfg.bound_port = port

    load_tasks()
    resume_tasks()

    cfg.server_instance.serve_forever(poll_interval=1)


def stop_server(_signum=None, _frame=None):
    log_info("系统关闭: 收到停止信号，正在停止服务")

    if cfg.server_instance:
        cfg.server_instance.shutdown()
        cfg.server_instance.server_close()
        log_info("系统关闭完成")

    sys.exit(0)


def register_signal_handlers():
    try:
        signal.signal(signal.SIGTERM, stop_server)
        signal.signal(signal.SIGINT, stop_server)
    except Exception:
        pass
