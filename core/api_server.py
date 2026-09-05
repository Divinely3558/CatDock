#!/usr/bin/env python3
"""api_server - HTTP 服务层

包含 DownloadHandler（认证 / 限流 / 路由）、TimeoutHTTPServer、
start_server / stop_server / 信号注册。

业务逻辑下沉到 downloader / task_store / dedup / filters / security / data_db。
"""
import sys
import os
import json
import hmac
import time
import base64
import hashlib
import secrets
import socket
import signal
import urllib.parse
import http.server

import app_config as cfg
from app_logger import log_info, log_error, debug_print
import data_db
from security import is_safe_url, sanitize_url_for_log, check_rate_limit
from filters import is_ad_content
from task_store import load_tasks
from dedup import init_dedup_cache
from downloader import run_download, resume_tasks, pause_task, resume_paused_task, delete_task
from webui import get_index_html


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


def issue_auth_token(username):
    """为已通过两层认证的用户签发令牌：base64url(payload).base64url(hmac_sha256 签名)

    payload 含唯一 jti 并登记到 data.db 的 auth_tokens 表，支持服务端主动吊销
    （注销 / 改密码全端下线）。签发时顺带惰性清理已过期的登记行。
    """
    payload = json.dumps({
        'user': username,
        'exp': int(time.time()) + TOKEN_TTL_SECONDS,
        'jti': secrets.token_hex(16),
    }, ensure_ascii=False).encode('utf-8')
    sig = hmac.new(_token_sign_key(), payload, hashlib.sha256).digest()
    claims = json.loads(payload)
    data_db.cleanup_expired_tokens()
    data_db.save_auth_token(claims['jti'], username, claims['exp'])
    return _b64url_encode(payload) + '.' + _b64url_encode(sig)


def get_token_claims(token):
    """解析令牌 payload（不验签，仅供签名校验通过后使用），失败返回 None"""
    try:
        payload = _b64url_decode(token.split('.', 1)[0])
        return json.loads(payload.decode('utf-8'))
    except Exception:
        return None


def verify_auth_token(token):
    """校验令牌，返回对应的用户名；无效/过期/已吊销/用户已删除时返回 None"""
    try:
        payload_b64, sig_b64 = token.split('.', 1)
        payload = _b64url_decode(payload_b64)
        expected = hmac.new(_token_sign_key(), payload, hashlib.sha256).digest()
        if not hmac.compare_digest(expected, _b64url_decode(sig_b64)):
            return None
        data = json.loads(payload.decode('utf-8'))
        username = data.get('user')
        exp = data.get('exp')
        jti = data.get('jti')
        if not username or not isinstance(exp, int) or exp < int(time.time()):
            return None
        # 吊销校验：jti 必须登记在册且未被吊销（改密码/注销/删用户后失效）
        if not jti or not data_db.is_token_valid(jti):
            return None
        # 用户在有效期内被 userctl del 删除后，令牌立即失效
        if not data_db.user_exists(username):
            return None
        return username
    except Exception:
        return None


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
            debug_print(f"发送响应失败: {e}")

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
            debug_print(f"发送页面失败: {e}")

    def handle(self):
        # IP 封禁检查：被封禁的 IP 直接断开连接，不返回任何响应
        client_ip = self.client_address[0]
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
        """两层认证：第一层 AUTH_KEY（环境变量），第二层 用户名+密码（data.db 的 users 表）

        凭证传递方式（按优先级）：
        1. Authorization: Bearer <token> 请求头（POST /login 签发，所有业务接口通用）
        2. 请求体 key/user/password 字段（仅 POST，兼容猫抓插件等第三方调用方）
        不再支持 URL 查询参数传凭证（URL 会进入浏览器历史与各级访问日志，存在泄露风险）
        """
        if not cfg.auth_key:
            return True

        # 方式 1：Bearer 令牌。携带令牌时仅校验令牌本身（签名/有效期/用户存在），
        # 令牌即已通过两层认证的凭证，无效令牌直接拒绝，不回退到明文凭证
        auth_header = self.headers.get('Authorization', '')
        if auth_header.startswith('Bearer '):
            token = auth_header[len('Bearer '):].strip()
            username = verify_auth_token(token) if token else None
            if username:
                # 认证成功：清除该 IP 的失败计数，避免历史偶发失误累积导致误封
                data_db.clear_auth_failure(self.client_address[0])
                self.authenticated_user = username
                return True
            log_error("认证失败：令牌无效或已过期")
            _record_failure_and_log(self.client_address[0])
            self.send_json({'success': False, 'message': '登录已过期，请重新登录'}, 403)
            return False

        # 方式 2：请求体凭证（POST 专用，GET 无请求体，也不再支持查询参数）
        def _get_field(*names):
            if data:
                val = self._get_param(data, *names)
                if val is not None:
                    return val
            return None

        # 第一层：AUTH_KEY（环境变量），通过 key/auth_key/token 字段传入
        # 第一层失败计入 IP 封禁计数（IP 级拦截）
        request_key = _get_field('key', 'auth_key', 'token')
        if request_key is None or not hmac.compare_digest(request_key, cfg.auth_key):
            log_error(f"认证失败：第一层 AUTH_KEY 校验未通过")
            # AUTH_KEY 错误，计入认证失败次数（阶梯封禁：首次临时、再次永久）
            _record_failure_and_log(self.client_address[0])
            self.send_json({'success': False, 'message': '认证失败，密钥不正确'}, 403)
            return False

        # 未初始化拦截：data.db 中无任何用户时，拒绝所有业务请求（/health 在此之前已放行）。
        # 不计入 IP 封禁（AUTH_KEY 已正确，属部署未完成而非攻击）；userctl add 后实时生效。
        if data_db.user_count() == 0:
            log_error(f"系统未初始化（无用户），拒绝请求: {self.path}")
            self.send_json({
                'success': False,
                'message': '系统尚未初始化：无可用用户，请在容器内执行 userctl add <用户名> 添加用户后重试'
            }, 503)
            return False

        # 第二层：用户名+密码（data.db 的 users 表），通过 user/password 字段传入
        # key 值 或 账号密码 任一不正确，均计入 IP 封禁计数
        # （10 分钟内累计 5 次：首次触发临时封禁 30 分钟，再次触发永久封禁）
        request_user = _get_field('user', 'usr')
        request_password = _get_field('password')
        if not request_user or not request_password or \
                not data_db.verify_user(request_user, request_password):
            log_error(f"认证失败：用户名或密码不正确")
            _record_failure_and_log(self.client_address[0])
            self.send_json({'success': False, 'message': '认证失败，用户名或密码不正确'}, 403)
            return False

        # 记录已认证用户，供下载目录分流 (/home/downloader/downloads/<用户名>)
        # 认证成功：清除该 IP 的失败计数，避免历史偶发失误累积导致误封
        data_db.clear_auth_failure(self.client_address[0])
        self.authenticated_user = request_user
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
            debug_print(f"路径前缀不正确，拒绝请求: {path}")
            return None

        return path

    def _check_rate_limit(self):
        client_ip = self.client_address[0]
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

        # /{prefix}（无尾斜杠）重定向到 /{prefix}/，便于浏览器直接打开网页控制台
        if cfg.url_prefix and raw_path == f'/{cfg.url_prefix}':
            self.send_response(302)
            self.send_header('Location', f'/{cfg.url_prefix}/')
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
                    debug_print(f"发送图标失败: {e}")
            return

        # 网页控制台：静态页面外壳（不含敏感信息），认证在页面内的 API 调用中完成
        if path in ('/', '/index.html'):
            self.send_html(get_index_html())
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
                'output_format': cfg.output_format,
                'url_prefix': cfg.url_prefix,
                'ssrf_protection': cfg.ssrf_protection,
                'max_concurrent_tasks': cfg.max_concurrent_tasks,
                'same_video_mode': cfg.same_video_by_filename_enabled,
                'keywords_enabled': cfg.keywords_enabled,
                'ad_keyword_count': len(cfg.ad_keywords),
                'filename_filter_enabled': cfg.filename_filter_enabled,
                'filename_dedup_enabled': cfg.filename_dedup_enabled,
                'user_count': data_db.user_count(),
                'auth_key_masked': '***' if cfg.auth_key else '',
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
                'token': issue_auth_token(self.authenticated_user),
                'expiresIn': TOKEN_TTL_SECONDS,
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
        elif path == '/download':
            try:
                data = self._read_json_body()
                if data is None:
                    return

                if not self._check_auth(data):
                    return

                if not self._check_rate_limit():
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
                # 网页控制台可逐任务指定输出格式（mp4/mkv），不传时回退到 config.json 全局设置
                output_format = self._get_param(data, 'format', 'output_format', 'outputFormat')

                # 限制最大并发任务数，防止资源耗尽
                with cfg.tasks_lock:
                    active_count = sum(1 for t in cfg.tasks.values() if t.get('status') in ('running', 'collecting'))
                if active_count >= cfg.max_concurrent_tasks:
                    log_error(f"并发任务数已达上限 ({cfg.max_concurrent_tasks})，拒绝新任务")
                    self.send_json({'success': False, 'message': f'并发任务数已达上限({cfg.max_concurrent_tasks})，请稍后再试'}, 429)
                    return

                is_ad, keyword = is_ad_content(save_name, url)
                if is_ad:
                    log_info(f"检测到广告内容，已拦截: {save_name} - 关键字: {keyword}")
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
                    # 返回实际使用的输出格式（网页传了 format 时为 per-task 值，否则为全局配置）
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

                # 认证密钥(auth_key)和URL前缀(url_prefix)由环境变量固定，
                # 重载配置时不覆盖，避免误改配置文件导致服务不可用
                if not self._check_rate_limit():
                    return

                saved_auth_key = cfg.auth_key
                saved_url_prefix = cfg.url_prefix
                try:
                    cfg.load_config()
                    # /reload 时重连数据库（关闭旧连接、重新打开、确保表结构）
                    data_db.reconnect_db()
                    # 检查用户数（del_user 已防删空，此处防外部替换 data.db 为空库）
                    _uc = data_db.user_count()
                    if _uc == 0:
                        log_error("警告: 重载后 data.db 中无用户，请运行: userctl add <用户名>")
                    else:
                        log_info(f"重载完成，当前用户数: {_uc}")
                finally:
                    cfg.auth_key = saved_auth_key
                    cfg.url_prefix = saved_url_prefix

                # 端口变更需重启容器才能生效（监听 socket 不会重绑）
                if cfg.server_port != cfg.bound_port:
                    log_error(f"警告: 端口已变更为 {cfg.server_port}，但需重启容器才能生效（当前仍监听 {cfg.bound_port}）")

                self.send_json({'success': True, 'message': '配置已重新加载'})
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

                log_info(f"任务操作 {path}: taskId={task_id}, 结果={ok}")
                self.send_json({'success': ok, 'message': message}, 200 if ok else 400)
            except Exception as e:
                self.send_json({'success': False, 'message': str(e)}, 500)
        else:
            self.send_json({'success': False, 'message': '路径不存在'}, 404)

    def log_message(self, format, *args):
        pass


class TimeoutHTTPServer(http.server.ThreadingHTTPServer):
    def __init__(self, server_address, RequestHandlerClass, bind_and_activate=True):
        super().__init__(server_address, RequestHandlerClass, bind_and_activate)
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.timeout = 60


def start_server(port):
    cfg.server_instance = TimeoutHTTPServer(('0.0.0.0', port), DownloadHandler)
    cfg.bound_port = port

    load_tasks()
    init_dedup_cache()
    resume_tasks()

    cfg.server_instance.serve_forever(poll_interval=1)


def stop_server(_signum=None, _frame=None):
    log_info("\n收到停止信号，正在关闭服务...")

    if cfg.server_instance:
        cfg.server_instance.shutdown()
        cfg.server_instance.server_close()
        log_info("服务已关闭")

    sys.exit(0)


def register_signal_handlers():
    try:
        signal.signal(signal.SIGTERM, stop_server)
        signal.signal(signal.SIGINT, stop_server)
    except Exception:
        pass
