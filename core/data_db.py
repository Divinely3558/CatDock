#!/usr/bin/env python3
"""catdock 数据库模块 (data.db)

使用 SQLite 持久化存储：
  - 认证失败计数与封禁 IP 列表
  - 下载用户及其密码（哈希+盐）

服务端（main.py / api_server.py）与 CLI 工具（banip / userctl）共用本模块。

数据库表结构：
  - failed_attempts: 记录每个 IP 在时间窗内的认证失败次数（认证成功/触发封禁后清零）
  - banned_ips:      已封禁的 IP 列表（reason: auto=临时自动封禁, auto_perm=永久自动封禁, manual=手动封禁）
  - ip_ban_stats:    阶梯封禁统计（每 IP 历史触发自动封禁的次数，认证成功清零）
  - users:           用户列表（用户名 + 密码哈希 + 角色 admin/user + 禁用标志）
  - auth_tokens:     访问令牌登记（jti，支撑服务端主动吊销：注销/改密码/删用户失效）

CLI 用法（本文件直接作为脚本运行，或通过 banip 命令调用）：
    python data_db.py show
    python data_db.py add <IP地址>
    python data_db.py del <IP地址>
"""
import os
import re
import sqlite3
import string
import threading
import time
import hmac
import hashlib
import secrets

# 认证失败达到该次数后自动封禁
# IP 级封禁（AUTH_KEY 错误 / 不存在的用户名）：10 次触发
MAX_AUTH_FAILURES = 10
# 账号级封禁（密码错误，用户存在但密码不匹配）：5 次触发，自动禁用账号
MAX_ACCOUNT_FAILURES = 5

# 失败计数时间窗：仅累计最近 N 分钟内的失败，历史失败自动清零，
# 避免"长期偶发失误累积 + 一次手滑 = 封禁"的误伤
AUTH_FAILURE_WINDOW_MINUTES = 10

# 自动封禁时长：auto 封禁在 N 分钟后自动解封（manual 手动封禁仍为永久）
BAN_DURATION_MINUTES = 30

# 数据库文件路径：固定为容器内 config.json 同级目录
# 服务端会通过 set_db_path() 覆盖为 CONFIG_FILE 同级，CLI 直接使用此默认路径
DB_PATH = '/home/downloader/config/data.db'

# 用户名规则：仅字母+数字、不能全数字、字母字符数不少于 4
_USERNAME_RE = re.compile(r'^[A-Za-z0-9]+$')

# pbkdf2 迭代次数
_PBKDF2_ITERATIONS = 100000

_db_lock = threading.Lock()
_db_conn = None


def set_db_path(path):
    """设置数据库文件路径，并重置连接以便下次访问时使用新路径。

    服务端在 load_config 中调用，确保 .db 与 config.json 同级。
    """
    global DB_PATH, _db_conn
    with _db_lock:
        DB_PATH = path
        if _db_conn is not None:
            try:
                _db_conn.close()
            except Exception:
                pass
            _db_conn = None


def _get_conn():
    """获取（懒加载）数据库连接，自动建表"""
    global _db_conn
    if _db_conn is None:
        # 确保目录存在
        db_dir = os.path.dirname(DB_PATH)
        if db_dir and not os.path.exists(db_dir):
            os.makedirs(db_dir, exist_ok=True)
        _db_conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=30)
        # WAL 日志模式：读写不互斥（多线程轮询下读不阻塞写、写不阻塞读），
        # 显著降低 ThreadingHTTPServer 高并发时的 database is locked 冲突。
        # 会常驻生成 -wal/-shm 伴随文件（与 .db 同目录，位于 config 挂载卷内，容器重启自动恢复）。
        _db_conn.execute("PRAGMA journal_mode=WAL")
        # 锁冲突时最多等待 30 秒（与 connect timeout 一致），而非立即抛 database is locked
        _db_conn.execute("PRAGMA busy_timeout=30000")
        # WAL 模式下让 checkpoint 自动运行，避免 -wal 文件无限增长
        _db_conn.execute("PRAGMA wal_autocheckpoint=1000")
        _db_conn.execute("PRAGMA synchronous=NORMAL")
        _db_conn.execute("""
            CREATE TABLE IF NOT EXISTS failed_attempts (
                ip TEXT PRIMARY KEY,
                count INTEGER DEFAULT 0,
                last_attempt_time TEXT
            )
        """)
        _db_conn.execute("""
            CREATE TABLE IF NOT EXISTS banned_ips (
                ip TEXT PRIMARY KEY,
                banned_at TEXT,
                reason TEXT
            )
        """)
        _db_conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                username TEXT PRIMARY KEY,
                password_hash TEXT NOT NULL,
                created_at TEXT,
                role TEXT NOT NULL DEFAULT 'user',
                disabled INTEGER NOT NULL DEFAULT 0
            )
        """)
        # IP 阶梯封禁统计：记录每个 IP 历史触发"自动封禁"的次数，
        # 第 1 次触发 = 临时封禁（reason='auto'，30 分钟自动解封），
        # 第 2 次触发 = 永久封禁（reason='auto_perm'，只能 banip del 解除）。
        # 认证成功清零；临时封禁到期不清除（保留升级计数）。
        _db_conn.execute("""
            CREATE TABLE IF NOT EXISTS ip_ban_stats (
                ip TEXT PRIMARY KEY,
                temp_ban_count INTEGER DEFAULT 0,
                last_ban_time TEXT
            )
        """)
        # 账号级失败计数：密码错误累计达 MAX_ACCOUNT_FAILURES 次后自动禁用账号
        _db_conn.execute("""
            CREATE TABLE IF NOT EXISTS account_failures (
                username TEXT PRIMARY KEY,
                count INTEGER DEFAULT 0,
                last_attempt_time TEXT
            )
        """)
        # 访问令牌登记表：支撑服务端主动吊销（POST /logout 单令牌吊销、
        # 改密码/删用户全端下线）。签名仍无状态，吊销状态以本表为准。
        _db_conn.execute("""
            CREATE TABLE IF NOT EXISTS auth_tokens (
                jti TEXT PRIMARY KEY,
                username TEXT NOT NULL,
                expires_at INTEGER NOT NULL,
                revoked INTEGER DEFAULT 0,
                created_at TEXT
            )
        """)
        _db_conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_auth_tokens_username ON auth_tokens(username)")
        _db_conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_auth_tokens_expires ON auth_tokens(expires_at)")
        _db_conn.commit()
    return _db_conn


def init_db():
    """显式初始化数据库（建表），供服务端启动时调用"""
    with _db_lock:
        _get_conn()


def reconnect_db():
    """关闭并重新打开数据库连接，确保表结构存在（数据保留）。

    供 /reload 接口调用，应对 DB 文件被外部替换/移动的情况。
    """
    global _db_conn
    with _db_lock:
        if _db_conn is not None:
            try:
                _db_conn.close()
            except Exception:
                pass
            _db_conn = None
        _get_conn()


def is_ip_banned(ip):
    """检查 IP 是否已被封禁。

    auto（首次触发）封禁超过 BAN_DURATION_MINUTES 后自动解封（清除失败计数，
    但保留 ip_ban_stats 升级计数）；
    manual（banip add 手动）与 auto_perm（重复触发升级）为永久封禁，
    只能通过 banip del 手动解除。
    """
    with _db_lock:
        conn = _get_conn()
        cursor = conn.execute(
            "SELECT banned_at, reason FROM banned_ips WHERE ip = ?", (ip,)
        )
        row = cursor.fetchone()
        if row is None:
            return False
        # auto 临时封禁到期自动解封；auto_perm / manual 永久封禁不走此处
        if row[1] == 'auto':
            try:
                banned_at = time.strptime(row[0], '%Y-%m-%d %H:%M:%S')
                elapsed = time.time() - time.mktime(banned_at)
                if elapsed >= BAN_DURATION_MINUTES * 60:
                    conn.execute("DELETE FROM banned_ips WHERE ip = ?", (ip,))
                    conn.execute(
                        "DELETE FROM failed_attempts WHERE ip = ?", (ip,)
                    )
                    conn.commit()
                    return False
            except (ValueError, OverflowError):
                pass
        return True


def record_auth_failure(ip):
    """记录一次认证失败（AUTH_KEY 错误 或 用户名/密码错误）。

    仅累计最近 AUTH_FAILURE_WINDOW_MINUTES 分钟内的失败（时间窗外自动清零），
    累计达到 MAX_AUTH_FAILURES 次时触发封禁，阶梯升级：
      - 第 1 次触发：临时封禁 BAN_DURATION_MINUTES 分钟（reason='auto'，到期自动解封）；
      - 第 2 次及以后触发：永久封禁（reason='auto_perm'，只能 banip del 解除）。
    认证成功会清零升级计数（clear_auth_failure），正常用户偶发手滑不会被永久封禁。

    返回值：
      False   未触发封禁（仅累计失败次数）
      'temp'  本次触发临时封禁
      'perm'  本次触发永久封禁
    """
    with _db_lock:
        conn = _get_conn()
        now = time.strftime('%Y-%m-%d %H:%M:%S')
        cursor = conn.execute("SELECT count, last_attempt_time FROM failed_attempts WHERE ip = ?", (ip,))
        row = cursor.fetchone()
        if row:
            # 上次失败超出时间窗则从 1 重新计数
            in_window = False
            try:
                last = time.strptime(row[1], '%Y-%m-%d %H:%M:%S')
                in_window = (time.time() - time.mktime(last)) < AUTH_FAILURE_WINDOW_MINUTES * 60
            except (ValueError, OverflowError):
                in_window = False
            count = (row[0] + 1) if in_window else 1
            conn.execute(
                "UPDATE failed_attempts SET count = ?, last_attempt_time = ? WHERE ip = ?",
                (count, now, ip),
            )
        else:
            count = 1
            conn.execute(
                "INSERT INTO failed_attempts (ip, count, last_attempt_time) VALUES (?, ?, ?)",
                (ip, count, now),
            )
        conn.commit()

        if count >= MAX_AUTH_FAILURES:
            # 阶梯封禁：查询历史自动封禁次数，决定本次临时封禁还是永久封禁
            stats_row = conn.execute(
                "SELECT temp_ban_count FROM ip_ban_stats WHERE ip = ?", (ip,)
            ).fetchone()
            prior_temp_bans = stats_row[0] if stats_row else 0

            # 封禁后清除失败计数，避免解封后残留
            conn.execute("DELETE FROM failed_attempts WHERE ip = ?", (ip,))

            if prior_temp_bans >= 1:
                # 第 2 次及以后触发：永久封禁（升级），只能 banip del 解除
                conn.execute(
                    "INSERT OR REPLACE INTO banned_ips (ip, banned_at, reason) VALUES (?, ?, ?)",
                    (ip, now, 'auto_perm'),
                )
                conn.execute(
                    "INSERT INTO ip_ban_stats (ip, temp_ban_count, last_ban_time) VALUES (?, ?, ?) "
                    "ON CONFLICT(ip) DO UPDATE SET temp_ban_count = temp_ban_count + 1, "
                    "last_ban_time = excluded.last_ban_time",
                    (ip, 1, now),
                )
                conn.commit()
                return 'perm'
            else:
                # 第 1 次触发：临时封禁 30 分钟，到期自动解封
                conn.execute(
                    "INSERT OR REPLACE INTO banned_ips (ip, banned_at, reason) VALUES (?, ?, ?)",
                    (ip, now, 'auto'),
                )
                conn.execute(
                    "INSERT INTO ip_ban_stats (ip, temp_ban_count, last_ban_time) VALUES (?, 1, ?) "
                    "ON CONFLICT(ip) DO UPDATE SET temp_ban_count = temp_ban_count + 1, "
                    "last_ban_time = excluded.last_ban_time",
                    (ip, now),
                )
                conn.commit()
                return 'temp'
        return False


def add_banned_ip(ip):
    """手动添加封禁 IP，原因固定为 'manual'"""
    with _db_lock:
        conn = _get_conn()
        now = time.strftime('%Y-%m-%d %H:%M:%S')
        conn.execute(
            "INSERT OR REPLACE INTO banned_ips (ip, banned_at, reason) VALUES (?, ?, ?)",
            (ip, now, 'manual'),
        )
        conn.commit()


def remove_banned_ip(ip):
    """手动删除（解封）IP，同时清除其失败计数与阶梯封禁统计（解封后重新开始）"""
    with _db_lock:
        conn = _get_conn()
        conn.execute("DELETE FROM banned_ips WHERE ip = ?", (ip,))
        conn.execute("DELETE FROM failed_attempts WHERE ip = ?", (ip,))
        conn.execute("DELETE FROM ip_ban_stats WHERE ip = ?", (ip,))
        conn.commit()


def clear_auth_failure(ip):
    """认证成功后清除该 IP 的失败计数与阶梯封禁升级计数。

    已封禁（临时/永久）的 IP 在 handle() 阶段连接即被断开，走不到认证，
    因此清零升级计数不会影响正在生效的封禁。
    """
    with _db_lock:
        conn = _get_conn()
        conn.execute("DELETE FROM failed_attempts WHERE ip = ?", (ip,))
        # 成功登录：清零阶梯升级计数，正常用户偶发手滑不会升级为永久封禁
        conn.execute("DELETE FROM ip_ban_stats WHERE ip = ?", (ip,))
        conn.commit()


def record_account_failure(username):
    """记录一次账号级密码错误失败。

    累计达 MAX_ACCOUNT_FAILURES 次后自动禁用该账号（disabled=1）。
    返回 True 表示已触发自动禁用，False 表示仅累计。
    """
    with _db_lock:
        conn = _get_conn()
        now = time.strftime('%Y-%m-%d %H:%M:%S')
        cursor = conn.execute("SELECT count, last_attempt_time FROM account_failures WHERE username = ?", (username,))
        row = cursor.fetchone()
        if row:
            in_window = False
            try:
                last = time.strptime(row[1], '%Y-%m-%d %H:%M:%S')
                in_window = (time.time() - time.mktime(last)) < AUTH_FAILURE_WINDOW_MINUTES * 60
            except (ValueError, OverflowError):
                in_window = False
            count = (row[0] + 1) if in_window else 1
            conn.execute("UPDATE account_failures SET count = ?, last_attempt_time = ? WHERE username = ?",
                         (count, now, username))
        else:
            count = 1
            conn.execute("INSERT INTO account_failures (username, count, last_attempt_time) VALUES (?, ?, ?)",
                         (username, count, now))
        conn.commit()

        if count >= MAX_ACCOUNT_FAILURES:
            conn.execute("UPDATE users SET disabled = 1 WHERE username = ?", (username,))
            conn.execute("DELETE FROM account_failures WHERE username = ?", (username,))
            conn.commit()
            return True
        return False


def clear_account_failure(username):
    """认证成功后清除该账号的失败计数。"""
    with _db_lock:
        conn = _get_conn()
        conn.execute("DELETE FROM account_failures WHERE username = ?", (username,))
        conn.commit()


def get_account_failure_count(username):
    """获取指定账号的当前失败计数"""
    with _db_lock:
        conn = _get_conn()
        cursor = conn.execute("SELECT count FROM account_failures WHERE username = ?", (username,))
        row = cursor.fetchone()
        return row[0] if row else 0


def list_banned_ips():
    """返回所有封禁 IP 列表 [(ip, banned_at, reason), ...]"""
    with _db_lock:
        conn = _get_conn()
        cursor = conn.execute(
            "SELECT ip, banned_at, reason FROM banned_ips ORDER BY banned_at DESC"
        )
        return cursor.fetchall()


def get_failure_count(ip):
    """获取指定 IP 的当前失败计数（用于调试/展示）"""
    with _db_lock:
        conn = _get_conn()
        cursor = conn.execute("SELECT count FROM failed_attempts WHERE ip = ?", (ip,))
        row = cursor.fetchone()
        return row[0] if row else 0


# ============ 用户管理 ============

def validate_username(username):
    """校验用户名：仅字母+数字、不能全数字、字母字符数不少于 4。

    返回 (ok, reason)；ok=True 时 reason 为空。
    """
    if not username or not isinstance(username, str):
        return False, "用户名不能为空"
    if not _USERNAME_RE.match(username):
        return False, "用户名只允许字母和数字"
    if username.isdigit():
        return False, "用户名不能为纯数字"
    letter_count = sum(1 for c in username if c.isalpha())
    if letter_count < 4:
        return False, "用户名中字母数量不能少于 4 位"
    return True, ""


def _hash_password(password):
    """生成 pbkdf2 + 随机盐 的密码哈希字符串"""
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'),
                             bytes.fromhex(salt), _PBKDF2_ITERATIONS)
    return f"pbkdf2$sha256${_PBKDF2_ITERATIONS}${salt}${dk.hex()}"


def _verify_password(password, stored):
    """校验密码与存储的哈希是否匹配（恒定时间比较）"""
    try:
        algo, hashalgo, iterations, salt, hashhex = stored.split('$')
        if algo != 'pbkdf2':
            return False
        iterations = int(iterations)
        dk = hashlib.pbkdf2_hmac(hashalgo, password.encode('utf-8'),
                                 bytes.fromhex(salt), iterations)
        return hmac.compare_digest(dk.hex(), hashhex)
    except Exception:
        return False


def add_user(username, password, role='user'):
    """添加用户。用户名非法或已存在时抛出 ValueError。

    role: 'user' 下载用户（默认）/ 'admin' 管理员。
    """
    ok, reason = validate_username(username)
    if not ok:
        raise ValueError(reason)
    if not password:
        raise ValueError("密码不能为空")
    if role not in ('user', 'admin'):
        role = 'user'
    with _db_lock:
        conn = _get_conn()
        cursor = conn.execute("SELECT 1 FROM users WHERE username = ?", (username,))
        if cursor.fetchone() is not None:
            raise ValueError(f"用户已存在: {username}")
        conn.execute(
            "INSERT INTO users (username, password_hash, created_at, role, disabled) "
            "VALUES (?, ?, ?, ?, 0)",
            (username, _hash_password(password),
             time.strftime('%Y-%m-%d %H:%M:%S'), role),
        )
        conn.commit()


def del_user(username):
    """删除用户。返回 True 表示已删除；False 表示用户不存在。
    管理员账户至少保留一个：删除最后一个 role='admin' 时抛出 ValueError。
    """
    with _db_lock:
        conn = _get_conn()
        cursor = conn.execute("SELECT role FROM users WHERE username = ?", (username,))
        row = cursor.fetchone()
        if row is None:
            return False
        if row[0] == 'admin':
            admin_cnt = conn.execute("SELECT COUNT(*) FROM users WHERE role = 'admin'").fetchone()[0]
            if admin_cnt <= 1:
                raise ValueError("至少保留一个管理员账户，不能删除最后一个管理员")
        # 同步作废该用户全部令牌：防止删除后重建同名用户时旧令牌"复活"
        conn.execute("UPDATE auth_tokens SET revoked = 1 WHERE username = ?", (username,))
        conn.execute("DELETE FROM users WHERE username = ?", (username,))
        conn.commit()
        return True


def change_password(username, new_password):
    """修改用户密码。用户不存在或新密码为空时抛出 ValueError。

    改密码即全端强制下线：该用户已签发的全部令牌一并作废。
    """
    if not new_password:
        raise ValueError("密码不能为空")
    with _db_lock:
        conn = _get_conn()
        cursor = conn.execute("SELECT 1 FROM users WHERE username = ?", (username,))
        if cursor.fetchone() is None:
            raise ValueError(f"用户不存在: {username}")
        conn.execute(
            "UPDATE users SET password_hash = ? WHERE username = ?",
            (_hash_password(new_password), username),
        )
        conn.execute("UPDATE auth_tokens SET revoked = 1 WHERE username = ?", (username,))
        conn.commit()


def verify_user(username, password):
    """校验用户名+密码（被禁用用户一律视为校验失败）。返回 True/False。"""
    with _db_lock:
        conn = _get_conn()
        cursor = conn.execute(
            "SELECT password_hash FROM users WHERE username = ? AND disabled = 0",
            (username,))
        row = cursor.fetchone()
        if row is None:
            return False
        return _verify_password(password, row[0])


def verify_user_password(username, password):
    """仅校验密码是否正确（不看禁用状态）。

    供认证层区分"密码正确但账号被禁用"（不计 IP 封禁）与普通密码错误（计数）。
    """
    with _db_lock:
        conn = _get_conn()
        cursor = conn.execute(
            "SELECT password_hash FROM users WHERE username = ?", (username,))
        row = cursor.fetchone()
        if row is None:
            return False
        return _verify_password(password, row[0])


def user_exists(username):
    """用户名是否已存在"""
    with _db_lock:
        conn = _get_conn()
        cursor = conn.execute("SELECT 1 FROM users WHERE username = ?", (username,))
        return cursor.fetchone() is not None


def user_count():
    """返回当前用户总数（含管理员）"""
    with _db_lock:
        conn = _get_conn()
        cursor = conn.execute("SELECT COUNT(*) FROM users")
        return cursor.fetchone()[0]


def download_user_count():
    """返回下载用户（role='user'）总数，不含管理员"""
    with _db_lock:
        conn = _get_conn()
        return conn.execute("SELECT COUNT(*) FROM users WHERE role = 'user'").fetchone()[0]


def admin_count():
    """返回管理员账户（role='admin'）总数"""
    with _db_lock:
        conn = _get_conn()
        return conn.execute("SELECT COUNT(*) FROM users WHERE role = 'admin'").fetchone()[0]


def user_role(username):
    """返回用户角色 'admin'/'user'；用户不存在返回 None"""
    with _db_lock:
        conn = _get_conn()
        row = conn.execute("SELECT role FROM users WHERE username = ?", (username,)).fetchone()
        return row[0] if row else None


def is_user_active(username):
    """用户是否存在且未被禁用（令牌校验使用：禁用后令牌立即失效）"""
    with _db_lock:
        conn = _get_conn()
        row = conn.execute(
            "SELECT 1 FROM users WHERE username = ? AND disabled = 0", (username,)).fetchone()
        return row is not None


def set_user_disabled(username, flag):
    """设置用户禁用状态。返回 True 表示用户存在并已更新，False 表示用户不存在。

    禁用时同步作废该用户全部令牌（解禁不自动恢复旧令牌，需重新登录）。
    """
    with _db_lock:
        conn = _get_conn()
        if conn.execute("SELECT 1 FROM users WHERE username = ?", (username,)).fetchone() is None:
            return False
        conn.execute("UPDATE users SET disabled = ? WHERE username = ?",
                     (1 if flag else 0, username))
        if flag:
            conn.execute("UPDATE auth_tokens SET revoked = 1 WHERE username = ?", (username,))
        conn.commit()
        return True


def list_users_full():
    """返回所有用户 [(username, role, disabled, created_at), ...]"""
    with _db_lock:
        conn = _get_conn()
        cursor = conn.execute(
            "SELECT username, role, disabled, created_at FROM users ORDER BY created_at ASC")
        return cursor.fetchall()


def ensure_default_admin():
    """首次启动确保存在管理员账户：无 role='admin' 时创建默认管理员 admin。

    返回 (created, password)：
    - created=True 时 password 为 14 位随机明文初始密码（仅本次返回，由调用方
      输出到启动日志一次，库内只存哈希）；
    - 已存在管理员时返回 (False, None)；若用户名 admin 已被普通用户占用，
      跳过创建（由调用方提示通过 adminctl add 创建其他管理员）。
    """
    with _db_lock:
        conn = _get_conn()
        if conn.execute("SELECT COUNT(*) FROM users WHERE role = 'admin'").fetchone()[0] > 0:
            return False, None
        # 用户名 admin 已被普通用户占用：跳过自动创建，避免 UNIQUE 冲突
        if conn.execute("SELECT 1 FROM users WHERE username = 'admin'").fetchone() is not None:
            return False, None
        alphabet = string.ascii_letters + string.digits
        password = ''.join(secrets.choice(alphabet) for _ in range(14))
        conn.execute(
            "INSERT INTO users (username, password_hash, created_at, role, disabled) "
            "VALUES ('admin', ?, ?, 'admin', 0)",
            (_hash_password(password), time.strftime('%Y-%m-%d %H:%M:%S')),
        )
        conn.commit()
        return True, password


# ---------- 访问令牌吊销（auth_tokens 表）----------

def save_auth_token(jti, username, expires_at):
    """签发令牌时登记。返回 False 表示 jti 已存在（不应发生）。"""
    with _db_lock:
        conn = _get_conn()
        try:
            conn.execute(
                "INSERT INTO auth_tokens (jti, username, expires_at, revoked, created_at) "
                "VALUES (?, ?, ?, 0, ?)",
                (jti, username, expires_at, time.strftime('%Y-%m-%d %H:%M:%S')),
            )
            conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False


def is_token_valid(jti):
    """令牌登记记录是否存在且未吊销（过期与否由签名 exp 校验，此处仅查吊销状态）"""
    with _db_lock:
        conn = _get_conn()
        cursor = conn.execute(
            "SELECT 1 FROM auth_tokens WHERE jti = ? AND revoked = 0", (jti,))
        return cursor.fetchone() is not None


def revoke_auth_token(jti):
    """吊销单个令牌（POST /logout 调用）"""
    with _db_lock:
        conn = _get_conn()
        conn.execute("UPDATE auth_tokens SET revoked = 1 WHERE jti = ?", (jti,))
        conn.commit()


def revoke_user_tokens(username):
    """吊销某用户当前全部令牌（改密码/强制下线场景）"""
    with _db_lock:
        conn = _get_conn()
        conn.execute("UPDATE auth_tokens SET revoked = 1 WHERE username = ?", (username,))
        conn.commit()


def revoke_all_tokens():
    """作废全部令牌（AUTH_KEY 热更换后全员强制下线；签名密钥同时变更，双保险）"""
    with _db_lock:
        conn = _get_conn()
        conn.execute("UPDATE auth_tokens SET revoked = 1")
        conn.commit()


def cleanup_expired_tokens():
    """清理已过期的令牌登记行（惰性清理：签发新令牌时触发）"""
    with _db_lock:
        conn = _get_conn()
        conn.execute("DELETE FROM auth_tokens WHERE expires_at < ?", (int(time.time()),))
        conn.commit()


def list_users():
    """返回所有用户名列表 [(username, created_at), ...]"""
    with _db_lock:
        conn = _get_conn()
        cursor = conn.execute(
            "SELECT username, created_at FROM users ORDER BY created_at ASC")
        return cursor.fetchall()


# ============ CLI 子命令入口（banip） ============

def _print_usage():
    print("用法: banip <子命令> [参数]")
    print("")
    print("子命令:")
    print("  show            显示所有被封禁的 IP 列表")
    print("  add <IP地址>     手动添加封禁 IP")
    print("  del <IP地址>     手动删除（解封）封禁 IP")
    print("")
    print("示例:")
    print("  banip show")
    print("  banip add 192.168.1.100")
    print("  banip del 192.168.1.100")


def _cmd_show():
    import sys
    try:
        rows = list_banned_ips()
    except Exception as e:
        print(f"读取封禁列表失败: {e}", file=sys.stderr)
        print(f"数据库路径: {DB_PATH}", file=sys.stderr)
        return 1

    if not rows:
        print("当前没有被封禁的 IP")
        return 0

    print(f"封禁 IP 列表（共 {len(rows)} 个）:")
    print(f"{'序号':<6}{'IP 地址':<20}{'封禁时间':<22}{'封禁原因'}")
    print("-" * 60)
    for idx, (ip, banned_at, reason) in enumerate(rows, 1):
        reason_display = {
            'auto': '自动封禁(临时)',
            'auto_perm': '自动封禁(永久)',
            'manual': '手动添加',
        }.get(reason, reason)
        print(f"{idx:<6}{ip:<20}{banned_at:<22}{reason_display}")
    return 0


def _cmd_add(args):
    import sys
    import ipaddress
    if not args:
        print("用法: banip add <IP地址>", file=sys.stderr)
        return 1

    ip = args[0].strip()

    try:
        ipaddress.ip_address(ip)
    except ValueError:
        print(f"错误: '{ip}' 不是合法的 IP 地址", file=sys.stderr)
        return 1

    try:
        add_banned_ip(ip)
    except Exception as e:
        print(f"添加封禁 IP 失败: {e}", file=sys.stderr)
        print(f"数据库路径: {DB_PATH}", file=sys.stderr)
        return 1

    print(f"已封禁 IP: {ip}")
    return 0


def _cmd_del(args):
    import sys
    if not args:
        print("用法: banip del <IP地址>", file=sys.stderr)
        return 1

    ip = args[0].strip()

    try:
        if not is_ip_banned(ip):
            print(f"IP {ip} 不在封禁列表中")
            return 0
        remove_banned_ip(ip)
    except Exception as e:
        print(f"删除封禁 IP 失败: {e}", file=sys.stderr)
        print(f"数据库路径: {DB_PATH}", file=sys.stderr)
        return 1

    print(f"已解封 IP: {ip}")
    return 0


def main():
    import sys
    argv = sys.argv[1:]
    if not argv:
        _print_usage()
        sys.exit(1)

    subcmd = argv[0]
    rest = argv[1:]

    if subcmd == 'show':
        sys.exit(_cmd_show())
    elif subcmd == 'add':
        sys.exit(_cmd_add(rest))
    elif subcmd == 'del':
        sys.exit(_cmd_del(rest))
    elif subcmd in ('-h', '--help', 'help'):
        _print_usage()
        sys.exit(0)
    else:
        print(f"未知子命令: {subcmd}", file=sys.stderr)
        _print_usage()
        sys.exit(1)


if __name__ == '__main__':
    main()
