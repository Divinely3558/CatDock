#!/usr/bin/env python3
"""chat - 顶栏状态灯彩蛋聊天室

所有登录用户（含管理员）共用的轻量频道：消息以 JSONL 按天追加写入
config/chatlog/ 目录（随配置卷持久化），每日一个文件（与系统日志同风格），
文件名 YYYY-MM-DD.log，每行一条（管理与用户格式一致，不区分角色）：
  {"user":"junjie","time":"2026-10-02 15:52:11","msg":"你好"}

- 文件内不存 id：消息 id = 基准值 + 全局行号（每日文件按日期升序合并编号；
  基准值 = 已被容量裁剪掉的消息总数，存于清理水位文件的 _id_base 键，
  属内部实现不入日志）；前端凭 id 增量拉取（?after=N）与判断新消息
- 旧版单文件 chat.log 不做迁移（保留原样，不再读写）
- 「清除聊天记录」按用户记录清理水位（chat_cleared.json），
  拉取时过滤水位之前的消息，刷新/重登后不再出现
- 总条数超过 MAX_MESSAGES 时从最旧的每日文件删起（只保留最近一半左右，
  仅剩单个文件时行级裁剪），id 经基准值保持连续
- 日期分隔线（如「2026年10月2日」）由前端按消息时间自行计算，不入库
"""
import json
import os
import re
import threading
import time

import app_config as cfg
from app_logger import log_error

# 聊天存档目录（config 挂载卷内，容器重建后保留），每日一个 YYYY-MM-DD.log
CHAT_DIR = os.path.join(cfg.CONFIG_DIR, 'chatlog')
# 每日存档文件名
_DAY_FILE_RE = re.compile(r'^\d{4}-\d{2}-\d{2}\.log$')
# 各用户的清理水位：{username: 已清理到的最大消息 id}（config 挂载卷内持久化）。
# 特殊键 _ID_BASE_KEY 保存 id 基准值（非用户名：用户名规则保证不会以下划线开头）
CLEARED_FILE = os.path.join(cfg.CONFIG_DIR, 'chat_cleared.json')
_ID_BASE_KEY = '_id_base'
# 水位文件结构版本。存档改为 chatlog/ 按天分文件后 id 从 1 重新编号，与旧版
# 单文件体系（消息自带 id、文件不迁移）的 id 空间互不相通：旧版遗留的水位
# 会把新体系的消息全部过滤掉（表现为点开弹窗消息"消失"），故版本不符时
# 整体作废旧水位，用户重新点一次「清除」即可。
_CLEARED_SCHEMA = 2
# 消息总条数上限：超过后从最旧文件删起收缩到一半左右（id 经基准值保持连续）
MAX_MESSAGES = 2000
# 单条消息最大长度
MAX_LENGTH = 500

_lock = threading.Lock()


def _line_payload(item):
    """提取写入文件的字段（id 等内部字段不入日志）"""
    return {'user': str(item.get('user', '')),
            'time': str(item.get('time', '')),
            'msg': str(item.get('msg', ''))}


def _read_base():
    """id 基准值 = 已被容量裁剪掉的消息总数（存于清理水位文件）"""
    v = _read_cleared().get(_ID_BASE_KEY, 0)
    return v if isinstance(v, int) and v >= 0 else 0


def _save_base(base):
    """更新 id 基准值（与清理水位同文件存储）"""
    data = _read_cleared()
    data[_ID_BASE_KEY] = base
    _write_cleared(data)


def _day_file_for(time_str):
    """按消息时间（YYYY-MM-DD HH:MM:SS）返回当日存档文件路径"""
    return os.path.join(CHAT_DIR, (time_str or '')[:10] + '.log')


def _list_day_files():
    """按日期升序返回存档目录下的每日文件路径列表"""
    try:
        names = [n for n in os.listdir(CHAT_DIR) if _DAY_FILE_RE.match(n)]
    except OSError:
        return []
    names.sort()
    return [os.path.join(CHAT_DIR, n) for n in names]


def _iter_jsonl(path):
    """逐行解析 JSONL 文件（坏行跳过）；读取失败返回空"""
    items = []
    try:
        with open(path, 'r', encoding='utf-8-sig') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    item = json.loads(line)
                except ValueError:
                    continue
                if isinstance(item, dict):
                    items.append(item)
    except OSError as e:
        log_error(f"[聊天] 读取 {path} 失败: {e}")
    return items


def _load_state():
    """读取消息列表与 id 基准值，须在 _lock 内调用。

    每日文件按日期升序逐行合并，消息 id = base + 全局行序（跨文件连续）。
    返回 (messages, base)。
    """
    raw = []
    for path in _list_day_files():
        raw.extend(_iter_jsonl(path))
    base = _read_base()
    messages = [dict(_line_payload(item), id=base + i)
                for i, item in enumerate(raw, 1)]
    return messages, base


def _append_line(item):
    """追加单条消息到当日存档文件（目录/文件按需创建，权限 600）"""
    line = json.dumps(_line_payload(item), ensure_ascii=False,
                      separators=(',', ':')) + '\n'
    path = _day_file_for(item.get('time', ''))
    try:
        os.makedirs(CHAT_DIR, exist_ok=True)
        if not os.path.exists(path):
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, 'a', encoding='utf-8') as f:
                f.write(line)
            return
        with open(path, 'a', encoding='utf-8') as f:
            f.write(line)
    except OSError as e:
        log_error(f"[聊天] 写入 {path} 失败: {e}")
        raise


def _count_lines(path):
    """统计存档文件内的消息行数（读取失败按 0 计）"""
    try:
        with open(path, 'r', encoding='utf-8-sig') as f:
            return sum(1 for line in f if line.strip())
    except OSError:
        return 0


def _trim_to_limit():
    """消息总量超过上限时收缩存档，返回推进的 id 基准量（裁掉的消息数）。

    策略：从最旧的每日文件整文件删除，直到剩余总量不超过一半（最旧的
    文件先删、最新文件保留）；若仅剩一个文件仍超限，则对该文件行级裁剪
    （原子重写保留最近一半）。
    """
    files = _list_day_files()
    if not files:
        return 0
    counts = {p: _count_lines(p) for p in files}
    total = sum(counts.values())
    removed = 0
    for path in files[:-1]:
        if total <= MAX_MESSAGES // 2:
            break
        total -= counts[path]
        removed += counts[path]
        try:
            os.unlink(path)
        except OSError as e:
            log_error(f"[聊天] 删除旧存档失败 {path}: {e}")
            return removed
    if total > MAX_MESSAGES:
        newest = files[-1]
        cut = counts[newest] - MAX_MESSAGES // 2
        if cut > 0:
            tmp_path = newest + '.tmp'
            try:
                with open(newest, 'r', encoding='utf-8-sig') as f:
                    lines = [l for l in f if l.strip()]
                fd = os.open(tmp_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
                with os.fdopen(fd, 'w', encoding='utf-8') as f:
                    f.writelines(lines[cut:])
                os.replace(tmp_path, newest)
                removed += cut
            except OSError as e:
                log_error(f"[聊天] 行级裁剪失败 {newest}: {e}")
    return removed


def _read_cleared():
    """读取各用户的清理水位 {username: id}；文件缺失/损坏/版本不符返回空 dict。

    版本不符（旧版遗留）整体作废：旧 id 空间的水位对新体系无意义且有害。
    """
    try:
        with open(CLEARED_FILE, 'r', encoding='utf-8-sig') as f:
            data = json.load(f)
        if not isinstance(data, dict) or data.get('_schema') != _CLEARED_SCHEMA:
            return {}
        return data
    except FileNotFoundError:
        return {}
    except Exception as e:
        log_error(f"[聊天] 读取清理水位失败 {CLEARED_FILE}: {e}")
        return {}


def _write_cleared(data):
    """原子写回清理水位文件（权限 600）；自动写入结构版本标记"""
    data = dict(data)
    data['_schema'] = _CLEARED_SCHEMA
    tmp_path = CLEARED_FILE + '.tmp'
    try:
        fd = os.open(tmp_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp_path, CLEARED_FILE)
    except OSError as e:
        log_error(f"[聊天] 写入清理水位失败 {CLEARED_FILE}: {e}")


def read_messages(after_id=0, user=None):
    """返回 (id > after_id 且未被该用户清理的消息列表, 当前最大消息 id)。

    after_id 传 0 / 负数返回全部（打开弹窗时全量拉取）。
    user 非 None 时叠加该用户的清理水位：id <= 水位的消息一并不返回
    （「清除聊天记录」后刷新/重登不再出现）。
    """
    with _lock:
        messages, _ = _load_state()
        cleared = _read_cleared().get(str(user), 0) if user else 0
    last_id = messages[-1]['id'] if messages else 0
    floor = max(after_id or 0, cleared or 0)
    if floor <= 0:
        return messages, last_id
    return [m for m in messages if m.get('id', 0) > floor], last_id


def append_message(user, msg):
    """追加一条消息并返回（含动态分配的 id 与服务端时间，东八区）。

    消息写入当日存档文件；总量超限时从最旧的文件删起收缩。
    写入失败时向上抛出异常，由调用方返回 500。
    """
    with _lock:
        messages, base = _load_state()
        next_id = (messages[-1]['id'] + 1) if messages else base + 1
        item = {
            'id': next_id,
            'user': str(user),
            'time': time.strftime('%Y-%m-%d %H:%M:%S'),
            'msg': str(msg)[:MAX_LENGTH],
        }
        _append_line(item)
        if len(messages) + 1 > MAX_MESSAGES:
            removed = _trim_to_limit()
            if removed:
                _save_base(base + removed)
    return item


def clear_chat(user):
    """记录该用户的清理水位（当前最大消息 id），返回清理到的 id。

    消息存档不删除；仅该用户此后拉取不到水位之前的消息。
    """
    with _lock:
        messages, _ = _load_state()
        cleared_id = messages[-1]['id'] if messages else 0
        data = _read_cleared()
        data[str(user)] = cleared_id
        _write_cleared(data)
    return cleared_id
