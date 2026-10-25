#!/usr/bin/env python3
"""downloader - 下载核心逻辑

包含：
  - per-user 下载目录（线程级上下文）
  - 下载命令构建（N_m3u8DL-RE / curl）、重试、各类 worker
  - 文件扫描/清理/格式转换
  - run_download（新建任务）、resume_tasks（重启恢复）
  - pause_task / resume_paused_task / delete_task（网页端任务控制）
  - same_video_by_filename 多链接调度
"""
import os
import re
import json
import time
import shutil
import uuid
import signal
import subprocess
import threading
import urllib.parse
import urllib.request

import app_config as cfg
from app_logger import log_info, log_warning, log_error, debug_print
from task_store import save_tasks, append_log
from dedup import is_url_downloaded, is_filename_downloaded
from filters import filter_filename, get_ad_keywords, reload_user_rules
from security import sanitize_url_for_log, is_safe_url, check_redirect_chain


# ---- per-user 上下文（线程级）----
# 下载在后台线程执行，请求线程的上下文不会自动传递；
# 在 run_download(请求线程) 与各 worker 入口显式设置，扫描类函数统一读取。
# 携带：用户名（过滤规则/日志/去重按用户隔离）、下载目录、缓存目录
_ctx = threading.local()


def _set_thread_context(user=None, download_dir=None, temp_dir=None):
    """设置当前线程的 per-user 上下文"""
    _ctx.user = user
    _ctx.download_dir = download_dir
    _ctx.temp_dir = temp_dir


def _set_thread_download_dir(path):
    """兼容入口：仅设置下载目录（启动期扫描等场景）"""
    _ctx.download_dir = path


def get_download_dir():
    """获取当前线程的下载目录；未设置时回退到基础 DOWNLOAD_DIR"""
    return getattr(_ctx, 'download_dir', None) or cfg.DOWNLOAD_DIR


def get_temp_dir():
    """获取当前线程的下载缓存目录；未设置时回退到基础 TEMP_DIR"""
    return getattr(_ctx, 'temp_dir', None) or cfg.TEMP_DIR


def get_current_user():
    """获取当前线程的下载用户名；未设置时返回 None"""
    return getattr(_ctx, 'user', None)


def _inherit_task_context(task_id):
    """后台 worker 继承任务的 per-user 上下文（下载目录/缓存目录/用户名）"""
    with cfg.tasks_lock:
        task = cfg.tasks.get(task_id)
    if task is None:
        return
    user = task.get('user') or 'default'
    _set_thread_context(user,
                        task.get('_download_dir') or os.path.join(cfg.DOWNLOAD_DIR, user),
                        cfg.user_temp_dir(user))


FORMAT_MAP = {
    'mp4': 'mp4',
    'mkv': 'matroska'
}


def _count_active_tasks(user=None):
    """当前活跃任务数（running/collecting），须在持有 cfg.tasks_lock 时调用。

    user 非 None 时仅统计该用户的任务（per-user 并发上限）；
    user 为 None 时统计所有用户（全局安全上限）。
    """
    return sum(1 for t in cfg.tasks.values()
               if t.get('status') in ('running', 'collecting')
               and (user is None or t.get('user') == user))


# 启动恢复闸门：resume_tasks 期间为 True，阻止队列泵提前拉起步任务
_resume_guard = False


def _next_qseq():
    """分配下一个排队序号（单调递增，持久化到 tasks.json 的 qseq 字段）。

    序号全局单调递增，但队列泵按用户分别挑选（per-user FIFO）。
    须在持有 cfg.tasks_lock 时调用。
    """
    return max((t.get('_qseq', 0) for t in cfg.tasks.values()), default=0) + 1


def _queued_tasks(user=None):
    """按排队序号升序返回排队中的任务（须在持有 cfg.tasks_lock 时调用）。

    user 非 None 时仅返回该用户的排队任务（per-user 队列）；
    user 为 None 时返回所有用户的排队任务。
    """
    return sorted((t for t in cfg.tasks.values()
                   if t.get('status') == 'queued'
                   and (user is None or t.get('user') == user)),
                  key=lambda t: t.get('_qseq', 0))


def queue_position(task_id):
    """排队中任务在其所属用户队列内的 1 起位次；非排队任务返回 None"""
    with cfg.tasks_lock:
        task = cfg.tasks.get(task_id)
        if not task or task.get('status') != 'queued':
            return None
        user = task.get('user')
        for pos, t in enumerate(_queued_tasks(user), 1):
            if t['id'] == task_id:
                return pos
    return None


def _pump_queue():
    """队列泵：按用户分别检查并发上限，有空名额时按排队序号拉起任务。

    两层限制：
      - 每用户上限 cfg.max_concurrent_tasks（该用户 running/collecting 数）
      - 全局安全上限 cfg.max_total_running（所有用户 running/collecting 总和）

    每轮扫描所有有排队任务的用户，取 qseq 最小的任务启动，
    保证跨用户公平（不偏向最后触发泵的用户）。
    在任一任务结束/暂停/删除后调用，实现「有坑自动补位」。
    """
    if _resume_guard:
        # 启动恢复期间禁止补位：此时多数任务尚未做完文件体检、也未生成
        # _plan，提前拉起会绕过「成品已存在」检查造成重复下载。
        # resume_tasks 收尾后统一放行（见该函数末尾的 _pump_queue）。
        return
    started = []
    with cfg.tasks_lock:
        # 一次性统计当前活跃数（全局 + per-user），循环内增量更新，避免反复遍历
        total_active = 0
        user_active = {}
        for t in cfg.tasks.values():
            if t.get('status') in ('running', 'collecting'):
                total_active += 1
                u = t.get('user')
                user_active[u] = user_active.get(u, 0) + 1

        while total_active < cfg.max_total_running:
            # 找出所有有排队任务且未达 per-user 并发上限的用户
            best = None
            for u in set(t.get('user') for t in cfg.tasks.values()
                         if t.get('status') == 'queued'):
                if user_active.get(u, 0) >= cfg.max_concurrent_tasks:
                    continue
                queued = _queued_tasks(u)
                if queued and (best is None
                               or queued[0].get('_qseq', 0) < best.get('_qseq', 0)):
                    best = queued[0]
            if best is None:
                break
            best['status'] = 'running'
            started.append(best['id'])
            total_active += 1
            bu = best.get('user')
            user_active[bu] = user_active.get(bu, 0) + 1
    if not started:
        return
    save_tasks(force=True)
    for task_id in started:
        _launch_task(task_id)


def _log_task_start(user, name, task_id):
    """任务登记后按最终状态打日志：已获名额→开始下载；否则→排队中（第 N 位）"""
    pos = queue_position(task_id)
    if pos is None:
        log_info(f"[{user}] 开始下载: {name}")
    else:
        log_info(f"[{user}] 排队中: {name}（第 {pos} 位）")


def _build_plan_from_task(task):
    """从任务记录重建启动计划（仅在 _plan 缺失时兜底，如异常数据）。

    重启恢复走 _resume_single_task（那里已完成文件检查并生成计划），
    此函数只做类型探测与输出路径计算。
    """
    user = task.get('user') or 'default'
    url = task.get('url') or (task.get('urls') or [''])[0]
    base_name = task.get('save_name') or f"download_{task['id']}"
    # 输出路径按任务自带用户目录计算：本函数在队列泵线程上运行，
    # 线程上下文属于别的用户，不能依赖 thread-local 的 get_download_dir()。
    task_download_dir = task.get('_download_dir') \
        or os.path.join(cfg.DOWNLOAD_DIR, user)
    is_direct_video, video_ext = classify_video_url(
        url, task.get('_referer'), task.get('_cookie'), task.get('_user_agent'))
    if is_direct_video:
        curl_target = output_file = \
            os.path.join(task_download_dir, f"{base_name}{video_ext}")
    else:
        curl_target, output_file = None, \
            os.path.join(task_download_dir, f"{base_name}.{cfg.output_format}")
    return {
        'kind': 'direct' if is_direct_video else 'm3u8',
        'url': url,
        'base_name': base_name,
        'curl_target': curl_target,
        'output_file': output_file,
        'target_format': cfg.output_format,
        'retry_count': task.get('_retry_count', 0),
    }


def _launch_task(task_id):
    """按任务自带的 _plan 真正拉起下载线程（由队列泵在锁外调用）"""
    try:
        with cfg.tasks_lock:
            task = cfg.tasks.get(task_id)
            if task is None:
                return
            plan = dict(task.get('_plan') or {})
        if not plan:
            plan = _build_plan_from_task(task)
            with cfg.tasks_lock:
                if task_id in cfg.tasks:
                    cfg.tasks[task_id]['_plan'] = plan

        user = task.get('user') or 'default'
        referer = task.get('_referer')
        cookie = task.get('_cookie')
        user_agent = task.get('_user_agent')
        kind = plan.get('kind')
        if kind == 'same_video':
            base_name = plan['base_name']
            fmt = plan.get('fmt')

            def delayed_start():
                time.sleep(1)
                _run_same_video_group_worker(task_id, base_name, fmt)

            threading.Thread(target=delayed_start, daemon=True).start()
        elif kind == 'direct':
            threading.Thread(
                target=_run_direct_download_worker,
                args=(task_id, plan['url'], plan['curl_target'], referer, cookie,
                      user_agent, plan.get('retry_count', 0)),
                daemon=True
            ).start()
        else:
            # 按任务自带用户显式构建命令：本函数由队列泵在锁外以「启动线程」
            # 身份调用，线程上下文属于别的用户，不能依赖 thread-local。
            task_download_dir = task.get('_download_dir') \
                or os.path.join(cfg.DOWNLOAD_DIR, user)
            cmd = _build_m3u8_cmd(plan['url'], plan['base_name'], referer, cookie,
                                  user_agent, user=user,
                                  download_dir=task_download_dir,
                                  temp_dir=cfg.user_temp_dir(user))
            threading.Thread(
                target=_run_worker,
                args=(task_id, cmd, plan['base_name'], plan['output_file'],
                      plan.get('target_format'), plan.get('retry_count', 0)),
                daemon=True
            ).start()
    except Exception as e:
        log_error(f"启动任务线程失败: {task_id} - {e}")
        _finish_task(task_id, False)


def convert_to_format(input_file, output_file, target_format):
    fmt = FORMAT_MAP.get(target_format, 'mp4')

    ffmpeg_cmd = [
        cfg.FFMPEG_PATH,
        '-i', input_file,
        '-c:v', 'copy',
        '-c:a', 'copy',
        '-f', fmt,
        '-y',
        output_file
    ]

    try:
        process = subprocess.Popen(
            ffmpeg_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True
        )

        try:
            for _ in iter(process.stdout.readline, ''):
                pass
        finally:
            process.stdout.close()

        return_code = process.wait()
        if return_code == 0:
            return True
        else:
            log_error(f"转换失败, 返回码: {return_code}")
            return False
    except Exception as e:
        log_error(f"转换异常: {e}")
        return False


VIDEO_EXTS = ('.mp4', '.mkv')
DIRECT_VIDEO_EXTS = ('.mp4', '.mkv', '.ts', '.flv', '.avi', '.webm', '.mov', '.wmv')


def is_direct_video_url(url):
    import urllib.parse
    parsed = urllib.parse.urlsplit(url)
    path = parsed.path.lower()
    ext = os.path.splitext(path)[1]
    return ext in DIRECT_VIDEO_EXTS, ext


def is_playlist_url(url):
    """URL 路径扩展名明确为流媒体播放列表（m3u8/mpd），无需内容探测"""
    import urllib.parse
    path = urllib.parse.urlsplit(url).path.lower()
    return os.path.splitext(path)[1] in ('.m3u8', '.mpd')


# 已知视频扩展名中明确不支持下载的格式（支持列表见 DIRECT_VIDEO_EXTS，
# m3u8/mpd 播放列表另行走 N_m3u8DL-RE）。这些格式的魔数探测同样无法识别
# （MPEG-PS / RealMedia / ASF / Ogg / BDAV / MXF 均不在 _sniff_media_magic
# 内），放行只会误入 m3u8 路径产生无效重试与模糊报错，故在任务创建入口拒绝。
# 注意 3gp/m4v/f4v/divx 等魔数为 ftyp/RIFF 的格式可被探测救回（保存为
# .mp4/.avi），不得加入本清单。
UNSUPPORTED_VIDEO_EXTS = ('.rmvb', '.rm', '.mpg', '.mpeg', '.vob', '.asf',
                          '.ogv', '.m2ts', '.mts', '.mxf')


def unsupported_video_ext(url):
    """URL 路径扩展名为明确不支持的视频格式时返回该扩展名，否则返回 None。

    仅做零成本扩展名检查，不做探测：无扩展名 URL 交给 classify_video_url
    的探测兜底判定，避免误伤探测超时但实际可下载的链接。
    """
    import urllib.parse
    ext = os.path.splitext(urllib.parse.urlsplit(url).path.lower())[1]
    return ext if ext in UNSUPPORTED_VIDEO_EXTS else None


# 明确的流媒体播放列表 / 直链视频 Content-Type 映射
_CONTENT_TYPE_KIND = {
    'application/vnd.apple.mpegurl': 'm3u8',
    'application/x-mpegurl': 'm3u8',
    'audio/mpegurl': 'm3u8',
    'video/mp4': '.mp4',
    'video/quicktime': '.mov',
    'video/x-flv': '.flv',
    'video/x-matroska': '.mkv',
    'video/webm': '.webm',
    'video/x-msvideo': '.avi',
    'video/x-ms-wmv': '.wmv',
    'video/mp2t': '.ts',
}


def _sniff_media_magic(head):
    """根据响应内容前若干字节的魔数判断媒体类型。

    返回 'mp4'（ISO BMFF：mp4/f4v/mov）/ 'flv' / 'm3u8' / 'avi' / 'mkv' / None。
    """
    h = head[:4096].lstrip()
    if h.startswith(b'FLV'):
        return 'flv'
    if len(h) >= 12 and h[4:8] == b'ftyp':
        return 'mp4'
    if h.startswith(b'#EXTM3U'):
        return 'm3u8'
    if h.startswith(b'RIFF') and len(h) >= 12 and h[8:12] == b'AVI ':
        return 'avi'
    if h.startswith(b'\x1a\x45\xdf\xa3'):
        return 'mkv'
    return None


def _ext_from_content_disposition(header_value):
    """从 Content-Disposition 头解析文件名扩展名（兼容 filename*= UTF-8'' 形式）"""
    if not header_value:
        return None
    m = re.search(r"filename\*\s*=\s*[^']*'[^']*'([^;]+)", header_value, re.I)
    if not m:
        m = re.search(r'filename\s*=\s*"([^"]+)"', header_value, re.I)
    if not m:
        m = re.search(r'filename\s*=\s*([^;]+)', header_value, re.I)
    if not m:
        return None
    import urllib.parse
    name = urllib.parse.unquote(m.group(1).strip())
    ext = os.path.splitext(name)[1].lower()
    return ext if ext else None


def _parse_last_response_headers(raw_headers):
    """curl -D - 在跟随多次跳转时会输出多段响应头，取最后一段解析为 dict"""
    blocks = re.split(rb'(?m)^HTTP/', raw_headers)
    last = blocks[-1] if blocks else b''
    headers = {}
    for line in last.splitlines()[1:]:
        try:
            text = line.decode('utf-8', errors='ignore').strip()
        except Exception:
            continue
        if ':' in text:
            key, val = text.split(':', 1)
            headers[key.strip().lower()] = val.strip()
    return headers


def _probe_media_url(url, referer=None, cookie=None, user_agent=None):
    """探测无扩展名 URL 的真实媒体类型（如下载页链接 ?dl_id=295 经
    Content-Disposition 返回视频文件）。

    一次轻量 GET（Range 前 64KB，--max-time 20s）同时获取最终响应头与内容头，
    按 魔数 > Content-Disposition 文件名扩展名 > Content-Type 的优先级判定。

    返回:
      ('direct', ext)  直链视频，ext 为推断扩展名（如 '.flv'/'.mp4'）
      ('m3u8', None)   m3u8/mpd 播放列表
      (None, None)     无法判定（调用方按原逻辑处理）
    """
    body_file = os.path.join(get_temp_dir(), f".probe_{uuid.uuid4().hex[:8]}.bin")
    try:
        # 探测请求不跳过 TLS 校验（-k），避免中间人攻击；
        # 实际下载时保留 -k 以兼容自签名证书的源站
        cmd = ['curl', '-s', '-L', '--max-time', '20',
               '-r', '0-65535', '-D', '-', '-o', body_file]
        if referer:
            cmd.extend(['-H', f'Referer: {referer}'])
        if cookie:
            cmd.extend(['-H', f'Cookie: {cookie}'])
        if user_agent:
            cmd.extend(['-A', user_agent])
        cmd.append(url)
        r = subprocess.run(cmd, capture_output=True, timeout=25)
        headers = _parse_last_response_headers(r.stdout or b'')
        cd_ext = _ext_from_content_disposition(headers.get('content-disposition', ''))
        ct = (headers.get('content-type', '').split(';')[0] or '').strip().lower()

        magic = None
        try:
            with open(body_file, 'rb') as f:
                magic = _sniff_media_magic(f.read(4096))
        except Exception as e:
            debug_print(f"[探测] 读取响应内容失败: {e}")

        debug_print(f"[探测] 探测结果: url={sanitize_url_for_log(url)[:80]} "
                    f"magic={magic} cd_ext={cd_ext} content-type={ct}")

        # 1) 魔数优先：内容是什么最可信
        if magic == 'm3u8':
            return 'm3u8', None
        if magic == 'flv':
            return 'direct', '.flv'
        if magic == 'mp4':
            return 'direct', cd_ext if cd_ext in ('.mp4', '.mov', '.m4v', '.mkv') else '.mp4'
        if magic == 'avi':
            return 'direct', '.avi'
        if magic == 'mkv':
            return 'direct', cd_ext if cd_ext in ('.webm', '.mkv') else '.mkv'
        # 2) 无魔数（Range 不支持/body 为空等）：靠 Content-Disposition 文件名
        if cd_ext in DIRECT_VIDEO_EXTS:
            return 'direct', cd_ext
        if cd_ext in ('.m3u8', '.mpd'):
            return 'm3u8', None
        # 3) 最后靠 Content-Type
        kind = _CONTENT_TYPE_KIND.get(ct)
        if kind == 'm3u8':
            return 'm3u8', None
        if isinstance(kind, str) and kind.startswith('.'):
            return 'direct', kind
        return None, None
    except Exception as e:
        debug_print(f"[探测] 探测失败: {e}")
        return None, None
    finally:
        try:
            if os.path.exists(body_file):
                os.remove(body_file)
        except Exception:
            pass


def classify_video_url(url, referer=None, cookie=None, user_agent=None):
    """判定链接走直链（curl）还是流媒体播放列表（N_m3u8DL-RE）。

    先按 URL 路径扩展名判定；路径无明确扩展名时（如 /?dl_id=295 下载页链接）
    发一次轻量探测，依据 Content-Disposition / 内容魔数 / Content-Type 判定。
    返回 (is_direct: bool, ext: str|None)。
    """
    is_direct, ext = is_direct_video_url(url)
    if is_direct:
        return True, ext
    if is_playlist_url(url):
        return False, ext
    debug_print(f"[探测] 链接无视频扩展名，发送 64KB 探测请求: {sanitize_url_for_log(url)[:100]}")
    kind, detected_ext = _probe_media_url(url, referer, cookie, user_agent)
    if kind == 'direct':
        debug_print(f"[探测] 判定为直链视频 {detected_ext}")
        return True, detected_ext
    if kind == 'm3u8':
        debug_print("[探测] 判定为流媒体播放列表（m3u8/mpd）")
    return False, None


def is_video_file(file_name):
    return os.path.splitext(file_name)[1].lower() in VIDEO_EXTS


def extract_percent(text):
    # 兼容小数百分比（N_m3u8DL-RE 输出形如 "... 13/30 43.33% ..."，
    # 旧正则 (\d{1,3})% 会误取小数部分，导致 43.33% 被解析为 33%）
    # 取最后一个匹配：0.6.0+ 在非 TTY 下进度更新不带换行，一次读到的文本
    # 可能含多条进度，最新的一条才是当前真实进度
    matches = re.findall(r'(\d{1,3}(?:\.\d+)?)%', text)
    if matches:
        # 已检测到下载输出但进度不足 1% 时显示 1%，避免被误认为未开始下载
        return min(100, max(1, int(float(matches[-1]))))
    return None


def extract_segments(text):
    """从 N_m3u8DL-RE 进度输出解析已下载分片数/总分片数（仅 m3u8 下载有）。

    进度形如 "Vid Kbps ━━━ 13/30 43.33% 1.07MB/6.45MB 1.07MBps 00:00:01"。
    正则锚定 N/M 后必须紧跟百分比，避免误匹配其中的 "1.07MB/6.45MB"
    （其后是 MBps 速率而非百分比数字）。匹配返回 (done, total)，否则 None。

    同 extract_percent：取最后一个匹配，适应无换行的批量进度输出。
    """
    matches = re.findall(r'(\d{1,5})\s*/\s*(\d{1,5})\s+\d{1,3}(?:\.\d+)?%', text)
    for done_s, total_s in reversed(matches):
        done, total = int(done_s), int(total_s)
        if 0 <= done <= total and total > 0:
            return done, total
    return None


def iter_output_chunks(stream, size=256, carry=200):
    """分块读取子进程输出，替代 readline 的按行读取。

    N_m3u8DL-RE 0.6.0+ 在 stdout 为管道（非 TTY）时，进度更新之间不输出任何
    换行/回车分隔符（100 分片的下载把 130 次进度挤在同一块里），readline 会
    一直阻塞到进程退出，进度条与分片计数全程冻结在 0。改为固定块读取 + 保留
    上一块尾部若干字符再拼接，既能实时解析，也能让被块边界切断的进度标记在
    下一块里完整匹配（旧值被重复匹配不影响结果，解析函数取最后一次匹配）。

    兼容 0.5.1 及 curl 的按行输出：换行只是普通字符，不影响正则匹配。
    """
    tail = ''
    while True:
        chunk = stream.read(size)
        if not chunk:
            break
        text = tail + chunk
        yield text
        tail = text[-carry:]


def match_base_name(name, base):
    if name == base or name.startswith(base + '.') or name.startswith(base + '_'):
        return True
    # 兜底：N_m3u8DL-RE 保存文件时会剥掉任务名结尾的半角点。
    # 任务名若带尾点（如 'X。.'——站点标题自带全角句号'。'、插件追加的
    # 扩展名被过滤词删除后残留），实际产物 'X。.mp4' 无法按 base+'.' 前缀
    # 匹配，导致后处理找不到文件、任务被误判失败并反复重下，产物被
    # N_m3u8DL-RE 逐轮改名堆积成 X.copy.mp4 / X.copy.copy.mp4。
    # 这里补充按剥点后的任务名再匹配一次。
    base2 = base.rstrip('.')
    if base2 and base2 != base and (
            name == base2 or name.startswith(base2 + '.') or name.startswith(base2 + '_')):
        return True
    return False


def sanitize_base_name(name, fallback=''):
    """任务名兜底净化：去首尾空白与半角点。

    站点标题自带全角句号'。'且插件追加的扩展名被用户过滤词删除后，
    任务名会残留尾点（如 'X。.'）；N_m3u8DL-RE 保存时会剥掉尾点，
    产物与任务名错位导致误判失败。提交入口统一剥点，保证命名一致。
    净化后为空（仅由点/空白组成或被过滤词删空）时回退到 fallback，
    避免产出 '<dir>/.mp4' 隐藏路径及 match_base_name 空前缀误匹配。
    """
    return (name or '').strip().strip('.') or fallback


def find_existing_output_file(base_name):
    download_dir = get_download_dir()
    if not os.path.exists(download_dir):
        return None

    candidates = []
    for item in os.listdir(download_dir):
        if not match_base_name(item, base_name):
            continue
        item_path = os.path.join(download_dir, item)
        if not os.path.isfile(item_path):
            continue
        if is_video_file(item):
            try:
                if os.path.getsize(item_path) >= cfg.MIN_FILE_SIZE:
                    candidates.append((os.path.getsize(item_path), item_path))
            except Exception:
                continue
    if not candidates:
        return None
    candidates.sort(reverse=True, key=lambda x: x[0])
    return candidates[0][1]


def find_existing_source_file(base_name):
    download_dir = get_download_dir()
    if not os.path.exists(download_dir):
        return None

    candidates = []
    for item in os.listdir(download_dir):
        if not match_base_name(item, base_name):
            continue
        item_path = os.path.join(download_dir, item)
        if not os.path.isfile(item_path):
            continue
        lower_item = item.lower()
        if lower_item.endswith(('.ts', '.mux.mp4')) or is_video_file(item):
            try:
                file_size = os.path.getsize(item_path)
                if file_size >= cfg.MIN_FILE_SIZE:
                    candidates.append((file_size, item_path))
            except Exception:
                continue
    if not candidates:
        return None
    candidates.sort(reverse=True, key=lambda x: x[0])
    return candidates[0][1]


def find_pending_merge_source(base_name):
    """查找"已合并但未转封装成成品"的 .ts / .mux.mp4 源文件。

    N_m3u8DL-RE 仅在转封装成功后才删除合并出的 .ts 源文件，因此：
      - .ts 与成品共存 ⇒ 转封装中途被打断（成品残缺），重新合成即可；
      - 仅剩 .ts      ⇒ 合并完成、转封装未开始，重新合成即可。
    断电/停容器后恢复任务时命中此函数可跳过整段重新下载。
    注意：不能复用 find_existing_source_file——它会返回体积最大的候选，
    共存的残缺成品往往比 .ts 大，会被误选。这里只扫描 .ts/.mux.mp4。
    返回源文件路径（≥ MIN_FILE_SIZE）或 None。
    """
    download_dir = get_download_dir()
    if not os.path.exists(download_dir):
        return None
    candidates = []
    for item in os.listdir(download_dir):
        if not match_base_name(item, base_name):
            continue
        item_path = os.path.join(download_dir, item)
        if not os.path.isfile(item_path):
            continue
        if not item.lower().endswith(('.ts', '.mux.mp4')):
            continue
        try:
            size = os.path.getsize(item_path)
        except Exception:
            continue
        if size >= cfg.MIN_FILE_SIZE:
            candidates.append((size, item_path))
    if not candidates:
        return None
    candidates.sort(reverse=True, key=lambda x: x[0])
    return candidates[0][1]


def cleanup_residue(base_name, exclude_file=None, preserve_source=True):
    """清理下载完成后残留的临时文件、文件夹和 .tmp 文件"""
    for dir_to_clean in [get_download_dir(), get_temp_dir()]:
        if not os.path.exists(dir_to_clean):
            continue
        for item in os.listdir(dir_to_clean):
            if not match_base_name(item, base_name):
                continue
            item_path = os.path.join(dir_to_clean, item)
            if exclude_file and os.path.abspath(item_path) == os.path.abspath(exclude_file):
                continue
            try:
                if os.path.isdir(item_path):
                    shutil.rmtree(item_path)
                elif preserve_source and item.lower().endswith(('.ts', '.mux.mp4')):
                    continue
                elif item.lower().endswith(('.tmp', '.ts', '.mux.mp4')):
                    os.remove(item_path)
            except Exception as e:
                log_error(f"清理残留失败: {item_path} - {e}")


def _check_network_ready(max_wait=30):
    """检查网络是否就绪，尝试连接国内常用服务

    Args:
        max_wait: 最大等待秒数

    Returns:
        bool: 网络是否就绪
    """
    import urllib.request
    import socket

    end_time = time.time() + max_wait
    while time.time() < end_time:
        try:
            # 尝试连接百度
            req = urllib.request.Request('http://www.baidu.com', headers={'User-Agent': 'Mozilla/5.0'})
            response = urllib.request.urlopen(req, timeout=5)
            response.close()
            return True
        except Exception:
            pass

        try:
            # 尝试连接阿里云DNS
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(3)  # 仅作用于本连接，不改全局默认超时
                sock.connect(('223.5.5.5', 53))
            return True
        except Exception:
            pass

        time.sleep(2)

    return False


# ---- master 型 m3u8 预解析选流 ----
# N_m3u8DL-RE 的 --ad-keyword 只在子播放列表解析路径生效：直接喂 master
# （含 #EXT-X-STREAM-INF 多码率变体）+ --auto-select 时广告剔除不生效。
# 因此构建命令前本地预解析：master 型按最高 BANDWIDTH 选流，把子播放
# 列表 URL 传给 N_m3u8DL-RE；子列表型或预解析失败则原样直传（尽力而为，
# 不阻塞下载）。

_MASTER_VARIANT_RE = re.compile(r'^#EXT-X-STREAM-INF:(.*)$')
_MASTER_BANDWIDTH_RE = re.compile(r'BANDWIDTH=(\d+)')


def _resolve_m3u8_media_url(url, referer=None, cookie=None, user_agent=None):
    """master 型 m3u8 预解析选流，返回选中变体的子播放列表 URL。

    子列表型 URL / 拉取失败 / 无有效变体 / 变体地址不安全 → 原样返回 url。
    """
    # 拉取前按提交时同规则做重定向链 SSRF 预检（urlopen 会自动跟随重定向）
    safe, _ = check_redirect_chain(url)
    if not safe:
        return url
    headers = {'User-Agent': user_agent or 'Mozilla/5.0'}
    if referer:
        headers['Referer'] = referer
    if cookie:
        headers['Cookie'] = cookie
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as resp:
            # master 播放列表体积小，1MB 截断足够覆盖（超大子列表被截断
            # 也只会判定为非 master 而原样直传，行为不变）
            content = resp.read(1024 * 1024).decode('utf-8', errors='replace')
    except Exception as e:
        debug_print(f"[m3u8] master 预解析拉取失败，按原 URL 直传: {e}")
        return url
    if '#EXT-X-STREAM-INF' not in content:
        return url
    # 解析变体：#EXT-X-STREAM-INF 属性行的下一非空非注释行为变体 URI，
    # 按 --auto-select 同等语义选最高 BANDWIDTH
    best_bandwidth, best_uri = -1, None
    lines = [ln.strip() for ln in content.splitlines()]
    for i, line in enumerate(lines):
        m = _MASTER_VARIANT_RE.match(line)
        if not m:
            continue
        bw_m = _MASTER_BANDWIDTH_RE.search(m.group(1))
        bandwidth = int(bw_m.group(1)) if bw_m else 0
        uri = None
        for nxt in lines[i + 1:]:
            if not nxt:
                continue
            if not nxt.startswith('#'):
                uri = nxt
            break
        if uri and bandwidth > best_bandwidth:
            best_bandwidth, best_uri = bandwidth, uri
    if not best_uri:
        return url
    variant_url = urllib.parse.urljoin(url, best_uri)
    # 变体地址来自远端内容（不可信），需过 SSRF 校验才能交给下载器
    if not is_safe_url(variant_url):
        log_error(f"SSRF 防护：master 变体指向不安全地址，按原 URL 直传: "
                  f"{sanitize_url_for_log(variant_url)}")
        return url
    debug_print(f"[m3u8] master 预解析选流: BANDWIDTH={best_bandwidth} -> "
                f"{sanitize_url_for_log(variant_url)[:120]}")
    return variant_url


def _build_m3u8_cmd(url, base_name, referer=None, cookie=None, user_agent=None,
                    user=None, download_dir=None, temp_dir=None):
    """构建 N_m3u8DL-RE 下载命令（resume_tasks 和 run_download 共用）。

    缓存目录与广告关键字必须按任务所属用户显式传入（user/download_dir/
    temp_dir）：队列泵在锁外以「启动线程」的身份调用本函数，若缺省回退到
    当前线程 per-user 上下文，会把用户 B 的排队任务写进用户 A 的目录。
    """
    if download_dir is None:
        download_dir = get_download_dir()
    if temp_dir is None:
        temp_dir = get_temp_dir()
    if user is None:
        user = get_current_user()
    cmd = [cfg.N_M3U8DL, _resolve_m3u8_media_url(url, referer, cookie, user_agent),
           '--tmp-dir', temp_dir,
           '--save-dir', download_dir,
           '--ffmpeg-binary-path', cfg.FFMPEG_PATH,
           '--save-name', base_name,
           '--auto-select']
    if referer:
        cmd.extend(['-H', f'Referer: {referer}'])
    # N_m3u8DL-RE 没有 --cookie/--user-agent 选项（0.5.1 与 0.6.0 均如此），
    # 传入会报 "Unrecognized command or argument" 并直接打印 usage 退出；
    # 请求头统一走 -H，与下方 curl 的构造方式一致。
    if cookie:
        cmd.extend(['-H', f'Cookie: {cookie}'])
    if user_agent:
        cmd.extend(['-H', f'User-Agent: {user_agent}'])
    ad_keywords = get_ad_keywords(user)
    if ad_keywords:
        for keyword in ad_keywords:
            cmd.extend(['--ad-keyword', keyword])
    cmd.extend(['--no-log'])
    return cmd


def _build_curl_cmd(url, output_file, referer=None, cookie=None, user_agent=None):
    """构建 curl 下载命令（_run_direct_download_worker 和 _do_single_download_attempt 共用）"""
    cmd = ['curl', '-L', '-C', '-', '-k', '--fail', '-o', output_file]
    if referer:
        cmd.extend(['-H', f'Referer: {referer}'])
    if cookie:
        cmd.extend(['-H', f'Cookie: {cookie}'])
    if user_agent:
        cmd.extend(['-A', user_agent])
    cmd.append(url)
    return cmd


# ---- m3u8 边下边看（预览播放）----
# 预览只读 N_m3u8DL-RE 的临时缓存目录（<temp>/<user>/<save_name>/0__*/<NNN>.ts）：
# 分片下载中为 .ts.tmp，完成后原子改名为 .ts，读到的无后缀文件均为稳定态；
# AES-128 源落盘前已解密，播放列表无需携带 EXT-X-KEY。

_PREVIEW_SEG_NAME_RE = re.compile(r'^(\d+)\.ts$')
_PREVIEW_QUALITY_DIR_RE = re.compile(r'^\d+__')


def _find_preview_seg_dir(task):
    """定位任务的临时分片目录（质量目录下文件数最多的一个）。

    返回 (分片目录路径, 目录内文件名列表)；缓存目录不存在时返回 (None, [])。
    """
    user = task.get('user') or ''
    save_name = task.get('save_name') or f"download_{task.get('id', '')}"
    base_dir = os.path.join(cfg.user_temp_dir(user), save_name)
    try:
        entries = os.listdir(base_dir)
    except OSError:
        return None, []
    best_dir, best_files = None, []
    for entry in entries:
        # 质量目录形如 0__mp4a.40.2,avc1.640028_6221600_（--auto-select 通常只选一个，仍按最多文件兜底）
        if not _PREVIEW_QUALITY_DIR_RE.match(entry):
            continue
        sub = os.path.join(base_dir, entry)
        if not os.path.isdir(sub):
            continue
        try:
            files = os.listdir(sub)
        except OSError:
            continue
        if len(files) > len(best_files):
            best_dir, best_files = sub, files
    return best_dir, best_files


def _load_preview_meta(seg_dir):
    """从 N_m3u8DL-RE 写出的 meta_selected.json 读取分片时长与保留序号。

    meta_selected.json 位于 seg_dir 的父目录（<save_name>/meta_selected.json），
    包含 N_m3u8DL-RE 过滤广告后实际保留的 MediaSegments，字段 Index 与 Duration
    直接对应磁盘上的 NN.ts 分片序号。读不到或解析失败时返回 (空字典, None)，
    由调用方按时长 10 秒兜底；保留序号为 None 表示无法识别广告洞。
    """
    durations = {}
    kept_indices = None
    meta_path = os.path.join(os.path.dirname(seg_dir), 'meta_selected.json')
    try:
        with open(meta_path, 'r', encoding='utf-8-sig') as f:
            data = json.load(f)
        if isinstance(data, list) and data:
            kept_indices = set()
            for part in (data[0].get('Playlist') or {}).get('MediaParts', []):
                for seg in (part.get('MediaSegments') or []):
                    idx = seg.get('Index')
                    if isinstance(idx, int) and idx >= 0:
                        kept_indices.add(idx)
                        dur = seg.get('Duration')
                        if isinstance(dur, (int, float)) and dur > 0:
                            durations[idx] = float(dur)
            if not kept_indices:
                kept_indices = None
    except (OSError, ValueError, TypeError, KeyError):
        pass
    return durations, kept_indices


def build_preview_playlist(task):
    """生成任务的 EVENT 型预览播放列表（边下边看）。

    只含已落盘完成（无 .tmp 后缀）的 .ts 分片，按数值排序；广告分片下载期
    已被 --ad-keyword 剔除不落盘，天然缺席。序号空洞若全部不在 meta 保留
    列表中，即为永久广告洞：PTS 在此跳变，须插 DISCONTINUITY 令 hls.js
    重对齐时间线，否则 seek 落入洞后区域会因播放头与时间线错位而卡死
    （顺序播放可被 hls.js 逐片自愈，seek 不行）；含未下载分片的临时空洞
    不插标记（分片补上后相邻关系会变，EVENT 前缀的标记不可增删）。
    不写 EXT-X-ENDLIST，hls.js 周期轮询增量。

    优先从 N_m3u8DL-RE 的 meta_selected.json 读取分片真实时长，确保预览进度
    条与总时间显示正确；找不到时回退到 10 秒兜底。

    返回 (playlist_text, None)；不可预览时返回 (None, (http_status, message))。
    """
    if task.get('status') not in ('running', 'paused'):
        return None, (404, '任务当前不可预览')
    seg_dir, files = _find_preview_seg_dir(task)
    if seg_dir is None:
        return None, (404, '下载缓存尚未就绪，请稍后再试')
    # 单次遍历：同时检测 fMP4 源和收集已完成 .ts 分片
    segs = []
    for f in files:
        base = f[:-4] if f.endswith('.tmp') else f
        if base.endswith(('.m4s', '.mp4')):
            return None, (415, 'fMP4 格式暂不支持预览')
        m = _PREVIEW_SEG_NAME_RE.match(f)
        if m:
            segs.append((int(m.group(1)), f))
    if not segs:
        return None, (404, '暂无已完成分片，请稍后再试')
    segs.sort()

    # 读取真实分片时长与保留序号，取不到用 10.0 兜底
    durations, kept_indices = _load_preview_meta(seg_dir)
    default_dur = 10.0
    extinfs = [durations.get(idx, default_dur) for idx, _ in segs]
    target_dur = int(max(extinfs)) + 1  # EXT-X-TARGETDURATION 须 ≥ 所有 EXTINF 上取整

    lines = [
        '#EXTM3U',
        '#EXT-X-VERSION:3',
        '#EXT-X-PLAYLIST-TYPE:EVENT',
        f'#EXT-X-TARGETDURATION:{target_dur}',
        '#EXT-X-MEDIA-SEQUENCE:0',
    ]
    prev_idx = None
    for dur, (idx, fname) in zip(extinfs, segs):
        if prev_idx is not None and kept_indices is not None:
            hole = range(prev_idx + 1, idx)
            if hole and kept_indices.isdisjoint(hole):
                lines.append('#EXT-X-DISCONTINUITY')
        lines.append(f'#EXTINF:{dur:.3f},')
        lines.append(f'seg/{fname}')
        prev_idx = idx
    return '\n'.join(lines) + '\n', None


def resolve_preview_segment(task, filename):
    """校验并返回预览分片的磁盘路径（seg 端点用）。

    白名单 ^\\d+\\.ts$（天然排除路径分隔符与 .tmp）；
    非法/不存在返回 None。
    """
    if not _PREVIEW_SEG_NAME_RE.match(filename):
        return None
    seg_dir, _ = _find_preview_seg_dir(task)
    if seg_dir is None:
        return None
    path = os.path.join(seg_dir, filename)
    if not os.path.isfile(path):
        return None
    return path


# CDN 调度 JSON 响应中可能携带真实下载地址的字段名（爱奇艺 pcw-data 接口使用 'l'）
_DISPATCH_URL_KEYS = ('l', 'url')


def _extract_dispatch_url(file_path):
    """检测下载到的小文件是否为 CDN 调度 JSON 响应。

    部分站点（如爱奇艺 pcw-data.video.iqiyi.com）的媒体链接返回的不是视频本身，
    而是一小段 JSON，形如 {"l": "https://真实CDN节点/xxx.f4v?...", "e": "0"}，
    真实视频地址在 'l' 字段中（每次请求动态分配节点）。

    命中且真实地址通过 SSRF 安全校验时返回该地址，否则返回 None。
    """
    try:
        if not os.path.exists(file_path) or os.path.getsize(file_path) > 64 * 1024:
            return None
        with open(file_path, 'rb') as f:
            head = f.read(8192).lstrip()
        if not head.startswith(b'{'):
            return None
        data = json.loads(head.decode('utf-8', errors='ignore'))
        if not isinstance(data, dict):
            return None
        for key in _DISPATCH_URL_KEYS:
            candidate = data.get(key)
            if isinstance(candidate, str) and candidate.startswith(('http://', 'https://')):
                if not is_safe_url(candidate):
                    debug_print(f"[调度] 真实地址未通过安全校验，忽略: "
                                f"{sanitize_url_for_log(candidate)[:100]}")
                    return None
                return candidate
    except Exception as e:
        debug_print(f"[调度] 调度响应解析失败: {e}")
    return None


# ---- 任务控制辅助：进程关联与状态查询 ----

def _register_proc(task_id, process):
    """把下载进程挂到任务上，供暂停/删除操作寻址"""
    with cfg.tasks_lock:
        if task_id in cfg.tasks:
            cfg.tasks[task_id]['_proc'] = process


def _unregister_proc(task_id, process):
    with cfg.tasks_lock:
        t = cfg.tasks.get(task_id)
        if t and t.get('_proc') is process:
            t['_proc'] = None


def _get_task_status(task_id):
    """查询任务状态；任务已被删除时返回 None"""
    with cfg.tasks_lock:
        t = cfg.tasks.get(task_id)
        return t['status'] if t else None


def _terminate_proc(process, graceful=True):
    """终止下载进程：默认 SIGINT 让 N_m3u8DL-RE 保存进度 / curl 保留断点文件"""
    if process is None:
        return
    try:
        if process.poll() is None:
            process.send_signal(signal.SIGINT if graceful else signal.SIGKILL)
    except Exception as e:
        debug_print(f"[下载] 终止下载进程失败: {e}")


def _run_download_with_retry(cmd, task_id, max_retries=5, initial_retry_count=0, base_name=""):
    """返回: True 下载成功 / False 重试耗尽 / 'paused' 任务被暂停 / 'deleted' 任务被删除"""
    retry_count = initial_retry_count
    while retry_count < max_retries:
        # 循环顶响应暂停/删除（覆盖退避等待、网络检查期间收到的请求）
        status = _get_task_status(task_id)
        if status is None:
            return 'deleted'
        if status == 'paused':
            debug_print(f"[下载] 任务已暂停，停止尝试: {base_name} (ID: {task_id})")
            return 'paused'

        debug_print(f"[下载] 第 {retry_count + 1}/{max_retries} 次尝试: {base_name} (ID: {task_id})")

        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            cwd='/home/downloader'
        )

        _register_proc(task_id, process)
        try:
            # 分块读取而非 readline：N_m3u8DL-RE 0.6.0+ 管道输出无换行分隔
            for chunk in iter_output_chunks(process.stdout):
                with cfg.tasks_lock:
                    if task_id in cfg.tasks:
                        percent = extract_percent(chunk)
                        if percent:
                            cfg.tasks[task_id]['progress'] = percent
                        # m3u8 分片计数（直链 curl 无此信息，不写该字段）
                        segs = extract_segments(chunk)
                        if segs:
                            cfg.tasks[task_id]['segments'] = {
                                'done': segs[0], 'total': segs[1]}
        finally:
            process.stdout.close()

        return_code = process.wait()
        _unregister_proc(task_id, process)

        # 暂停/删除请求优先于结果判定，防止 SIGINT 退出码被误判为失败或误判成功
        status = _get_task_status(task_id)
        if status is None:
            return 'deleted'
        if status == 'paused':
            debug_print(f"[下载] 任务已暂停，停止尝试: {base_name} (ID: {task_id})")
            return 'paused'

        if return_code == 0:
            debug_print(f"[下载] 命令执行成功: {base_name}")
            return True

        existing_file = find_existing_source_file(base_name)
        if existing_file:
            debug_print(f"[下载] 返回非零码 {return_code}，但检测到可用输出文件: {existing_file}")
            return True

        debug_print(f"[下载] 失败，返回码 {return_code}: {base_name}")

        with cfg.tasks_lock:
            if task_id in cfg.tasks:
                cfg.tasks[task_id]['_retry_count'] = retry_count + 1
                save_tasks(force=True)

        if retry_count < max_retries - 1:
            # 计算指数退避等待时间：5s, 10s, 20s, 40s...
            wait_time = min(5 * (2 ** retry_count), 60)
            debug_print(f"[下载] 保留已下载文件断点续传，{wait_time} 秒后重试: {base_name}")

            # 快速检查网络（3 秒）；长时间不通则跳过重试
            if not _check_network_ready(max_wait=3):
                debug_print(f"[下载] 网络未就绪，继续等待...")
                if not _check_network_ready(max_wait=wait_time):
                    debug_print(f"[下载] 网络长时间未就绪，跳过本次重试")
                    retry_count += 1
                    continue

            time.sleep(wait_time)

        retry_count += 1

    debug_print(f"[下载] 已重试 {max_retries} 次仍失败: {base_name}")
    return False


def _do_single_download_attempt(base_name, url, referer, cookie, user_agent, task_id=None, output_format=None):
    """对单个 URL 进行单次下载尝试（不操作 tasks 状态，不写日志）

    适用于 same_video_by_filename 模式下调度器对单个链接的一次尝试。
    task_id 用于把下载进程挂到真实任务上（暂停/删除寻址），
    并透传 'paused'/'deleted' 状态给调度器。
    """
    fmt = output_format if output_format in ('mp4', 'mkv') else cfg.output_format
    is_direct_video, video_ext = classify_video_url(url, referer, cookie, user_agent)

    if is_direct_video:
        curl_target = output_file = os.path.join(get_download_dir(), f"{base_name}{video_ext}")
    else:
        curl_target, output_file = None, os.path.join(get_download_dir(), f"{base_name}.{fmt}")

    # 尝试前先清理残留（避免上一次失败的残留影响，但是保留已存在的大文件 -> 直接成功）
    # .ts 源文件仍在（上次合成被打断）时优先直接重新合成，避免整段重新下载
    pending_src = find_pending_merge_source(base_name)
    if pending_src:
        debug_print(f"[去重] 发现未合成完的源文件，直接重新合成（无需重新下载）: {pending_src}")
        if _finalize_download_outputs(base_name, output_file, fmt)[0]:
            return True
    has_existing, existing_path = has_existing_video(base_name)
    if has_existing:
        debug_print(f"[去重] 同名视频文件已存在，直接视为成功: {existing_path}")
        return True
    if os.path.exists(output_file):
        file_size = os.path.getsize(output_file)
        if file_size >= cfg.MIN_FILE_SIZE:
            debug_print(f"[去重] 输出文件已存在且完整: {output_file}")
            return True

    success = False
    try:
        if is_direct_video:
            # 直接视频下载，使用 curl，只重试1次
            # dl_url 可能在检测到 CDN 调度 JSON（爱奇艺 pcw-data 等）后切换为真实地址，
            # 最多跟随 3 跳
            dl_url = url
            seen_urls = {url}
            for _hop in range(4):
                cmd = _build_curl_cmd(dl_url, curl_target, referer, cookie, user_agent)

                process = subprocess.Popen(
                    cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, cwd='/home/downloader'
                )
                _register_proc(task_id, process)
                try:
                    for _ in iter(process.stdout.readline, ''):
                        pass
                finally:
                    process.stdout.close()
                return_code = process.wait()
                _unregister_proc(task_id, process)

                # 暂停/删除优先于结果判定（SIGINT 退出码不可信）
                status = _get_task_status(task_id) if task_id else None
                if task_id and status is None:
                    return 'deleted'
                if task_id and status == 'paused':
                    debug_print(f"[下载] 任务已暂停，停止尝试: {base_name}")
                    return 'paused'

                if os.path.exists(curl_target):
                    file_size = os.path.getsize(curl_target)
                    if file_size >= cfg.MIN_FILE_SIZE:
                        if return_code == 0:
                            debug_print(f"[下载] curl 下载成功: {base_name}")
                        else:
                            debug_print(f"[下载] 返回非零码 {return_code} 但文件有效: {base_name}")
                        success = True
                        break

                    # 文件过小：可能是 CDN 调度 JSON（{"l": "真实地址"}）
                    resolved = _extract_dispatch_url(curl_target)
                    if resolved and resolved not in seen_urls and len(seen_urls) < 4:
                        seen_urls.add(resolved)
                        debug_print(f"[调度] 检测到 CDN 调度响应，转向真实地址: "
                                    f"{sanitize_url_for_log(resolved)[:120]}")
                        try:
                            os.remove(curl_target)
                        except Exception:
                            pass
                        dl_url = resolved
                        continue
                    debug_print(f"[下载] 下载文件太小 ({file_size} bytes)，可能是错误页面: {base_name}")
                    try:
                        if os.path.exists(curl_target):
                            os.remove(curl_target)
                    except Exception:
                        pass
                else:
                    debug_print(f"[下载] curl 下载失败，返回码 {return_code}: {base_name}")
                break
        else:
            # m3u8 下载，使用 N_m3u8DL，只重试1次
            cmd = _build_m3u8_cmd(url, base_name, referer, cookie, user_agent)

            # 调用下载命令，max_retries=1 表示每个链接只试一次（不内部多次重试）
            download_ok = _run_download_with_retry(
                cmd, task_id=task_id,
                max_retries=1, initial_retry_count=0,
                base_name=base_name
            )
            if download_ok in ('paused', 'deleted'):
                return download_ok
            if not download_ok:
                # 但即使命令说失败，也要检查一下文件
                existing_file = find_existing_source_file(base_name)
                if existing_file:
                    debug_print(f"[下载] 命令报告失败但检测到可用文件: {existing_file}")
                    download_ok = True

            if not download_ok:
                debug_print(f"[下载] m3u8 下载命令失败: {base_name}")
                cleanup_residue(base_name, preserve_source=True)
                return False

            time.sleep(0.5)

            # 后处理：调用共享函数完成 定位/转换/校验/清理
            ok, _final = _finalize_download_outputs(base_name, output_file, fmt)
            if ok:
                success = True

        if success:
            debug_print(f"[下载] 下载+后处理成功: {base_name}")
        return success

    except Exception as e:
        debug_print(f"[下载] 下载异常: {base_name} - {e}")
        try:
            cleanup_residue(base_name, preserve_source=True)
        except Exception:
            pass
        return False


def _finalize_download_outputs(base_name, output_file, target_format):
    """共享后处理：m3u8下载后 或 单链接尝试后的 文件定位/转格式/校验/清理流程。

    行为与 _run_worker 原有的 100+ 行 保持等价：
      1. 列目录找 .ts / .mux.mp4 / video 源文件
      2. 若 output_file 已完整 → 成功
      3. 若 source_file 存在 → 需要格式转换时 convert_to_format(最多3次, 间隔2s);
         否则直接 rename
      4. 转换后若 output_file 太小 → fallback 用 source_file rename
      5. 转换失败但 source_file 足够大 → 用 source_file 作为最终输出
      6. 全流程失败返回 False, 成功返回 True

    不操作 tasks, 不调用 _finish_task, 不写 log_info（保持纯后处理）。
    返回: (success: bool, actual_output_file_or_none: str|None)
    """
    download_dir = get_download_dir()
    try:
        all_files = [f for f in os.listdir(download_dir) if match_base_name(f, base_name)]
    except OSError as e:
        # 目录被删/卷异常时按失败返回而非抛异常：调用方（含 _run_worker 的
        # except 分支）若在此时二次异常逃出线程，_finish_task 不会执行，
        # 任务将永久停在 running 占住并发名额
        debug_print(f"[后处理] 列出下载目录失败: {download_dir} - {e}")
        return False, None
    ts_files = [f for f in all_files if f.lower().endswith('.ts')]
    mux_files = [f for f in all_files if f.lower().endswith('.mux.mp4')]
    video_files = [f for f in all_files if is_video_file(f) and '.mux.' not in f.lower()]

    source_file = None
    # 源文件优先级：.mux.mp4 > .ts > 成品视频。
    # .ts 与成品共存是"转封装中途被打断"的现场，成品残缺，必须以 .ts 为源
    # 重新合成覆盖，不能选残缺成品（否则直接原样返回损坏文件）。
    if mux_files:
        source_file = os.path.join(download_dir, mux_files[0])
    elif ts_files:
        source_file = os.path.join(download_dir, ts_files[0])
    elif video_files:
        source_file = os.path.join(download_dir, video_files[0])

    # (A) 输出文件已存在（可能由下载工具直接生成）
    # 注意：.ts/.mux.mp4 源文件仍在时，说明上次转封装中途被打断，
    # 成品是残缺文件，不能直接认定完整，须继续走 (C) 以 -y 重新合成覆盖。
    if os.path.exists(output_file) and not ts_files and not mux_files:
        file_size = os.path.getsize(output_file)
        if file_size >= cfg.MIN_FILE_SIZE:
            debug_print(f"[后处理] 输出文件已存在且完整: {output_file}")
            cleanup_residue(base_name, exclude_file=output_file, preserve_source=False)
            return True, output_file
        alt = find_existing_output_file(base_name)
        if alt and os.path.abspath(alt) != os.path.abspath(output_file):
            debug_print(f"[后处理] 找到备用输出文件: {alt}")
            cleanup_residue(base_name, exclude_file=alt, preserve_source=False)
            return True, alt

    # (B) 没有找到 source_file → 再试一次找 备用输出文件 / output_file 存在性
    if not source_file or not os.path.exists(source_file):
        debug_print(f"[后处理] 找不到源文件，检查备用输出文件")
        alt = find_existing_output_file(base_name)
        if alt:
            debug_print(f"[后处理] 使用现有备用输出文件: {alt}")
            cleanup_residue(base_name, exclude_file=alt, preserve_source=False)
            return True, alt
        if os.path.exists(output_file):
            file_size = os.path.getsize(output_file)
            if file_size >= cfg.MIN_FILE_SIZE:
                cleanup_residue(base_name, exclude_file=output_file, preserve_source=False)
                return True, output_file
        cleanup_residue(base_name, preserve_source=True)
        return False, None

    # (C) 有 source_file → 转换/重命名
    _conversion_done = False
    if source_file.endswith('.ts') or source_file.lower().endswith('.mux.mp4'):
        for _ in range(3):
            if convert_to_format(source_file, output_file, target_format):
                _conversion_done = True
                break
            time.sleep(2)
    elif source_file != output_file:
        try:
            os.rename(source_file, output_file)
            _conversion_done = True
        except Exception:
            _conversion_done = False

    # 转换失败且 .ts/.mux 源仍在：此时 output_file 只能是上次合成中断留下的
    # 残缺成品（ts 与成品共存 ⇒ 成品残缺），绝不能误判为成功——明确删除残缺
    # 文件、保留源文件，返回失败。后续恢复/重试会再次命中"直接重新合成"捷径，
    # 无需重新下载。
    if not _conversion_done and (ts_files or mux_files):
        if os.path.exists(output_file):
            try:
                os.remove(output_file)
                debug_print(f"[后处理] 转换失败，删除残缺成品文件: {output_file}")
            except Exception:
                pass
        cleanup_residue(base_name, preserve_source=True)
        return False, None

    # (D) 检查转换/重命名后的 output_file
    if os.path.exists(output_file):
        file_size = os.path.getsize(output_file)
        if file_size >= cfg.MIN_FILE_SIZE:
            cleanup_residue(base_name, exclude_file=output_file, preserve_source=False)
            return True, output_file
        # output_file 太小 → fallback: 直接用 source_file
        if source_file and os.path.exists(source_file):
            source_size = os.path.getsize(source_file)
            if source_size >= cfg.MIN_FILE_SIZE:
                debug_print(f"[后处理] 输出文件太小，使用源文件代替: {source_file}")
                try:
                    os.rename(source_file, output_file)
                except Exception:
                    pass
                if os.path.exists(output_file) or os.path.exists(source_file):
                    final = output_file if os.path.exists(output_file) else source_file
                    cleanup_residue(base_name, exclude_file=final, preserve_source=False)
                    return True, final
        cleanup_residue(base_name, preserve_source=True)
        return False, None

    # (E) 转换失败但 source_file 还在，且够大 → 直接用 source_file
    if os.path.exists(source_file):
        source_size = os.path.getsize(source_file)
        if source_size >= cfg.MIN_FILE_SIZE:
            debug_print(f"[后处理] 转换未生成输出，使用源文件作最终输出: {source_file}")
            try:
                os.rename(source_file, output_file)
            except Exception:
                pass
            final = output_file if os.path.exists(output_file) else source_file
            cleanup_residue(base_name, exclude_file=final, preserve_source=False)
            return True, final
        cleanup_residue(base_name, exclude_file=source_file, preserve_source=True)
        return False, None

    # (F) 兜底
    cleanup_residue(base_name, preserve_source=True)
    return False, None


def has_existing_video(base_name):
    download_dir = get_download_dir()
    if not os.path.exists(download_dir):
        return False, None

    for item in os.listdir(download_dir):
        if not match_base_name(item, base_name):
            continue
        if is_video_file(item):
            item_path = os.path.join(download_dir, item)
            if os.path.isfile(item_path):
                file_size = os.path.getsize(item_path)
                if file_size >= cfg.MIN_FILE_SIZE:
                    return True, item_path
    return False, None


# 缓存已编译的正则表达式，避免 has_any_existing_file 每次调用都重新编译
_copy_pattern_cache = {}

def has_any_existing_file(base_name):
    download_dir = get_download_dir()
    if not os.path.exists(download_dir):
        return False, None

    if base_name not in _copy_pattern_cache:
        _copy_pattern_cache[base_name] = re.compile(
            rf'^{re.escape(base_name)}(?:\.copy)+(\.(?:mp4|mkv))?$', re.IGNORECASE)
    copy_pattern = _copy_pattern_cache[base_name]

    for item in os.listdir(download_dir):
        if not match_base_name(item, base_name):
            continue

        item_path = os.path.join(download_dir, item)
        if os.path.isfile(item_path):
            if item == base_name:
                return True, item_path
            file_size = os.path.getsize(item_path)
            # .copy 重复成品：任一大小都视为已有成品；
            # 但 .mp4/.mkv 视频必须 ≥ MIN_FILE_SIZE 才算成品——
            # 否则直链视频（curl 断点续传）下载到一半的小分片（几十 KB）
            # 会被误判为“已完成”而跳过恢复，导致任务被错误标记成功。
            if copy_pattern.match(item):
                return True, item_path
            if is_video_file(item) and file_size >= cfg.MIN_FILE_SIZE:
                return True, item_path
    return False, None


def _check_local_file_exists_skip(base_name):
    """run_download 两段模式共用的"本地文件命中即跳过"检查。

    返回: (should_skip: bool, label_or_None)
      - should_skip=True 时调用方应直接 return None, False
      - label 是被命中的具体路径（用于日志）
    """
    has_existing, existing_path = has_existing_video(base_name)
    if has_existing:
        return True, existing_path
    has_any, any_path = has_any_existing_file(base_name)
    if has_any:
        return True, any_path
    return False, None


def cleanup_copy_files(base_name):
    download_dir = get_download_dir()
    if not os.path.exists(download_dir):
        return

    copy_pattern = re.compile(rf'^{re.escape(base_name)}(?:\.copy)+(\.(?:mp4|mkv))?$')
    main_pattern = re.compile(rf'^{re.escape(base_name)}(\.(?:mp4|mkv))?$')

    copy_files = []
    main_files = []

    for item in os.listdir(download_dir):
        item_path = os.path.join(download_dir, item)
        if not os.path.isfile(item_path):
            continue

        if copy_pattern.match(item):
            try:
                file_size = os.path.getsize(item_path)
                copy_files.append((file_size, item_path))
            except Exception:
                pass
        elif main_pattern.match(item):
            try:
                file_size = os.path.getsize(item_path)
                if file_size >= cfg.MIN_FILE_SIZE_SMALL:
                    main_files.append((file_size, item_path))
            except Exception:
                pass

    if main_files:
        main_files.sort(reverse=True, key=lambda x: x[0])
        keep_file = main_files[0][1]

        for file_size, item_path in copy_files:
            if item_path != keep_file:
                try:
                    os.remove(item_path)
                    debug_print(f"[清理] 已删除重复文件: {item_path}")
                except Exception as e:
                    debug_print(f"[清理] 删除重复文件失败: {item_path} - {e}")
    elif copy_files:
        copy_files.sort(reverse=True, key=lambda x: x[0])
        keep_file = copy_files[0][1]
        keep_name = os.path.basename(keep_file)

        new_name = keep_name.replace('.copy', '')
        new_path = os.path.join(download_dir, new_name)

        try:
            if keep_file != new_path:
                os.rename(keep_file, new_path)
                debug_print(f"[清理] 已重命名主文件: {keep_file} -> {new_path}")
                keep_file = new_path
        except Exception as e:
            debug_print(f"[清理] 重命名主文件失败: {e}")

        for file_size, item_path in copy_files[1:]:
            if item_path != keep_file:
                try:
                    os.remove(item_path)
                    debug_print(f"[清理] 已删除重复文件: {item_path}")
                except Exception as e:
                    debug_print(f"[清理] 删除重复文件失败: {item_path} - {e}")


def _finish_task(task_id, success, write_log=True):
    """任务结束处理：写成功/失败日志 → 从内存删除任务 → 持久化。

    write_log=False 用于重启恢复时“URL 已存在于日志”的清理分支：
    该任务在历史上已写过日志（is_url_downloaded 命中即证明），
    无需重复追加一条记录，只需把残留的任务记录从列表/磁盘清除。
    """
    task_data = None
    with cfg.tasks_lock:
        if task_id in cfg.tasks:
            task_data = cfg.tasks[task_id].copy()
        else:
            log_error(f"任务 {task_id} 已不存在于任务列表中")
            return

    # 同视频模式兜底：从视频组补充全部 URL，确保日志记录所有链接
    save_name = task_data.get('save_name', '')
    if save_name:
        with cfg.video_groups_lock:
            group = cfg.video_groups.get(save_name)
            if group and group.get('urls'):
                group_urls = [u[0] for u in group['urls']]
                merged = list(task_data['urls'])
                for u in group_urls:
                    if u not in merged:
                        merged.append(u)
                task_data['urls'] = merged

    with cfg.tasks_lock:
        if task_id not in cfg.tasks:
            return
        # 在删除任务前先写入日志，防止竞态条件导致重复下载
        # 日志按用户隔离：user/<名>/success.log 或 failure.log
        user = task_data.get('user') or 'default'
        if write_log:
            log_file = cfg.user_success_log(user) if success else cfg.user_failure_log(user)
            try:
                append_log(log_file, task_data, 'success' if success else 'failure')
            except Exception as e:
                # 日志写不进去已无法补写；若保留任务，下载线程已退出而任务
                # 停在 running 永久占住并发名额（僵尸任务直到重启）。
                # 继续删除任务并泵队列，代价仅是该 URL 未来不参与去重。
                log_error(f"写入日志失败（任务仍按完成清理）: {task_id} - {e}")
        del cfg.tasks[task_id]
        save_tasks(force=True)

    if task_data:
        name = task_data.get('save_name') or task_id
        if success:
            log_info(f"[{user}] 下载完成: {name}")
        else:
            log_error(f"[{user}] 下载失败: {name}")
        debug_print(f"[入口] 任务结束: {name} (ID: {task_id})，剩余任务 {len(cfg.tasks)} 个")

    # 任务结束释放并发名额，立即从队列取下一个任务补位
    _pump_queue()


def _run_same_video_group_worker(task_id, base_name, output_format=None):
    """多链接调度 Worker: 按顺序轮流尝试同一个视频的所有链接。

    策略：
      - 把同一视频的所有 URL 按顺序排列，轮流依次尝试
      - 每一圈（从 current_index 开始，每个链接各尝试 1 次，
        直到回到"本轮起点"之前那个链接仍未成功）算一次"失败回合"
      - 总共 5 个失败回合后放弃该视频
      - 期间如果接收到新 URL，会在下一圈开始时加入队列
    """
    debug_print(f"[调度器] 启动视频组任务 {task_id}: {base_name}")

    # 继承 per-user 上下文（后台线程 thread-local 默认为空）
    _inherit_task_context(task_id)

    with cfg.video_groups_lock:
        group = cfg.video_groups.get(base_name)
        if group is None:
            debug_print(f"[调度器] 找不到视频组 {base_name}，任务结束")
            _finish_task(task_id, False)
            return
        group['status'] = 'running'
        task_url_for_log = group['urls'][0][0] if group['urls'] else ''

    # 先检查文件是否已经存在（可能是被并发其他流程下载的）
    has_existing, existing_path = has_existing_video(base_name)
    if has_existing:
        debug_print(f"[调度器] 视频已存在，视为成功: {existing_path}")
        with cfg.video_groups_lock:
            group = cfg.video_groups.get(base_name)
            if group:
                group['status'] = 'done'
        # 更新 task 的 url 以供日志写入
        with cfg.tasks_lock:
            if task_id in cfg.tasks:
                cfg.tasks[task_id]['url'] = task_url_for_log
                cfg.tasks[task_id]['save_name'] = base_name
        cleanup_copy_files(base_name)
        _finish_task(task_id, True)
        return

    total_urls_count_ever = 0

    try:
        while True:
            with cfg.video_groups_lock:
                group = cfg.video_groups.get(base_name)
                if group is None:
                    break
                urls_snapshot = list(group['urls'])
                start_index = group['current_index']
                round_count = group['round_count']

            if not urls_snapshot:
                debug_print(f"[调度器] 视频组 {base_name} URL 列表为空，等待 5 秒...")
                time.sleep(5)
                # 等待期间如果有新 URL，则继续；否则超时放弃
                with cfg.video_groups_lock:
                    group = cfg.video_groups.get(base_name)
                    if group and group['urls']:
                        continue
                debug_print(f"[调度器] 视频组 {base_name} 长时间无 URL，放弃")
                break

            if round_count >= 5:
                debug_print(f"[调度器] {base_name} 已完成 5 轮失败，放弃下载")
                break

            n_urls = len(urls_snapshot)
            if total_urls_count_ever < n_urls:
                total_urls_count_ever = n_urls

            debug_print(f"[调度器] 第 {round_count + 1}/5 轮开始, "
                     f"共 {n_urls} 个链接, 起始索引={start_index} ({base_name})")

            # 一圈：每个链接尝试 1 次（按顺序轮转，一圈后仍未成功就算一个失败回合）
            round_succeed = False
            for i in range(n_urls):
                idx = (start_index + i) % n_urls
                url, ref, ck, ua = urls_snapshot[idx]

                # 每尝试一个链接之前，再次检查是否已成功（防止并发完成）
                has_existing, existing_path = has_existing_video(base_name)
                if has_existing:
                    debug_print(f"[调度器] 检测到视频已下载完成: {existing_path}")
                    round_succeed = True
                    break

                debug_print(f"[调度器] 尝试链接 {idx + 1}/{n_urls} (第{round_count+1}轮) "
                         f"[{sanitize_url_for_log(url)[:80]}...] -> {base_name}")

                # 更新进度（顺带响应 sleep 间隙收到的暂停/删除请求）
                with cfg.tasks_lock:
                    _t = cfg.tasks.get(task_id)
                    if _t is None:
                        debug_print(f"[调度器] 任务已删除，调度器退出: {base_name}")
                        return
                    if _t['status'] == 'paused':
                        with cfg.video_groups_lock:
                            g = cfg.video_groups.get(base_name)
                            if g:
                                g['status'] = 'paused'
                                g['current_index'] = idx
                        debug_print(f"[调度器] 任务已暂停，调度器退出: {base_name}")
                        return
                    _t['url'] = url
                    _t['_referer'] = ref
                    _t['_cookie'] = ck
                    _t['_user_agent'] = ua
                    overall_progress = int(
                        (round_count * n_urls + i) * 100 / max(1, 5 * n_urls)
                    )
                    _t['progress'] = min(99, overall_progress)
                    save_tasks()

                ok = _do_single_download_attempt(base_name, url, ref, ck, ua, task_id=task_id, output_format=output_format)
                if ok in ('paused', 'deleted'):
                    # 暂停/删除：退出调度循环，不写完成日志、不移除任务；
                    # 继续下载时由 API 侧按恢复流程重新启动
                    with cfg.video_groups_lock:
                        g = cfg.video_groups.get(base_name)
                        if g and ok == 'paused':
                            g['status'] = 'paused'
                            g['current_index'] = idx  # 恢复时从当前链接重试
                    debug_print(f"[调度器] 任务{'已暂停' if ok == 'paused' else '已删除'}，调度器退出: {base_name}")
                    return
                if ok:
                    debug_print(f"[调度器] 链接 {idx + 1} 下载成功: {base_name}")
                    round_succeed = True
                    break
                else:
                    debug_print(f"[调度器] 链接 {idx + 1} 失败，准备切换下一个...")
                    # 失败后稍等，给网络恢复时间
                    time.sleep(2)

            if round_succeed:
                with cfg.video_groups_lock:
                    group = cfg.video_groups.get(base_name)
                    if group:
                        group['status'] = 'done'
                with cfg.tasks_lock:
                    if task_id in cfg.tasks:
                        cfg.tasks[task_id]['save_name'] = base_name
                        cfg.tasks[task_id]['progress'] = 100
                cleanup_copy_files(base_name)
                _finish_task(task_id, True)
                return

            # 一整圈失败，回合数 + 1，移动起始索引（从下一个链接开始新一轮，达到"轮流"效果）
            with cfg.video_groups_lock:
                group = cfg.video_groups.get(base_name)
                if group:
                    group['round_count'] = round_count + 1
                    group['current_index'] = (start_index + 1) % max(1, len(group['urls']))
                    debug_print(f"[调度器] 第 {round_count + 1}/5 轮结束，所有链接均失败。"
                             f"下一轮起始索引={group['current_index']}")

        # 5 轮都没成功
        with cfg.video_groups_lock:
            group = cfg.video_groups.get(base_name)
            if group:
                group['status'] = 'done'
        with cfg.tasks_lock:
            if task_id in cfg.tasks:
                cfg.tasks[task_id]['save_name'] = base_name
                if urls_snapshot:
                    cfg.tasks[task_id]['url'] = urls_snapshot[0][0]
        cleanup_copy_files(base_name)
        _finish_task(task_id, False)

    except Exception as e:
        debug_print(f"[调度器] 异常: {e}")
        with cfg.video_groups_lock:
            group = cfg.video_groups.get(base_name)
            if group:
                group['status'] = 'done'
        with cfg.tasks_lock:
            if task_id in cfg.tasks:
                cfg.tasks[task_id]['save_name'] = base_name
        cleanup_copy_files(base_name)
        _finish_task(task_id, False)


def _run_direct_download_worker(task_id, url, output_file, referer, cookie, user_agent,
                                initial_retry_count=0):
    """直链下载 worker（curl + 断点续传）。output_file 为 curl 下载目标即成品。"""
    # 继承 per-user 上下文（后台线程 thread-local 默认为空）
    _inherit_task_context(task_id)
    try:
        base_name = os.path.basename(output_file)
        max_retries = 5
        retry_count = initial_retry_count
        # dl_url 可能在检测到 CDN 调度 JSON（爱奇艺 pcw-data 等）后切换为真实地址，
        # 最多跟随 3 跳；切换地址不消耗重试次数
        dl_url = url
        seen_urls = {url}
        while retry_count < max_retries:
            # 循环顶响应暂停/删除（覆盖退避等待、网络检查期间收到的请求）
            status = _get_task_status(task_id)
            if status is None:
                return
            if status == 'paused':
                debug_print(f"[下载] 任务已暂停，停止尝试: {base_name} (ID: {task_id})")
                return

            cmd = _build_curl_cmd(dl_url, output_file, referer, cookie, user_agent)

            debug_print(f"[下载] 第 {retry_count + 1}/{max_retries} 次尝试: {base_name} (ID: {task_id})，"
                        f"目标 {output_file}")

            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                cwd='/home/downloader'
            )

            _register_proc(task_id, process)
            try:
                for line in iter(process.stdout.readline, ''):
                    line = line.strip()
                    with cfg.tasks_lock:
                        if task_id in cfg.tasks:
                            percent = extract_percent(line)
                            if percent:
                                cfg.tasks[task_id]['progress'] = percent
            finally:
                process.stdout.close()

            return_code = process.wait()
            _unregister_proc(task_id, process)

            # 暂停/删除请求优先于结果判定（SIGINT 退出码不可信），且不清理部分文件
            status = _get_task_status(task_id)
            if status is None:
                return
            if status == 'paused':
                debug_print(f"[下载] 任务已暂停，停止尝试: {base_name} (ID: {task_id})")
                return

            if os.path.exists(output_file):
                file_size = os.path.getsize(output_file)
                if file_size >= cfg.MIN_FILE_SIZE:
                    if return_code != 0:
                        debug_print(f"[下载] 返回非零码 {return_code}，但检测到有效输出文件 "
                                    f"(大小 {file_size} bytes): {base_name}")
                    debug_print(f"[下载] 直链下载成功: {base_name}")
                    _finish_task(task_id, True)
                    return
                else:
                    debug_print(f"[下载] 下载文件太小 ({file_size} bytes)，可能是错误页面: {base_name}")
                    # 小文件可能是 CDN 调度 JSON（如爱奇艺 pcw-data 返回 {"l": "真实地址"}）
                    resolved = _extract_dispatch_url(output_file)
                    if resolved and resolved not in seen_urls and len(seen_urls) < 4:
                        seen_urls.add(resolved)
                        debug_print(f"[调度] 检测到 CDN 调度响应，转向真实地址: "
                                    f"{sanitize_url_for_log(resolved)[:120]}")
                        try:
                            os.remove(output_file)
                        except Exception:
                            pass
                        dl_url = resolved
                        continue

            debug_print(f"[下载] 直链下载失败，返回码 {return_code}: {base_name}")

            with cfg.tasks_lock:
                if task_id in cfg.tasks:
                    cfg.tasks[task_id]['_retry_count'] = retry_count + 1
                    save_tasks(force=True)

            if retry_count < max_retries - 1:
                # 计算指数退避等待时间：5s, 10s, 20s, 40s...
                wait_time = min(5 * (2 ** retry_count), 60)
                debug_print(f"[下载] 保留已下载文件断点续传，{wait_time} 秒后重试: {base_name}")

                # 快速检查网络（3 秒）；长时间不通则跳过重试
                if not _check_network_ready(max_wait=3):
                    debug_print(f"[下载] 网络未就绪，继续等待...")
                    if not _check_network_ready(max_wait=wait_time):
                        debug_print(f"[下载] 网络长时间未就绪，跳过本次重试")
                        retry_count += 1
                        continue

                time.sleep(wait_time)

            retry_count += 1

        debug_print(f"[下载] 直链下载已重试 {max_retries} 次仍失败: {base_name}")
        # 保留不完整文件：curl -C - 可在下次重试时断点续传，删除则前功尽弃
        _finish_task(task_id, False)
    except Exception as e:
        log_error(f"直接下载线程异常: {e}")
        # 保留不完整文件供后续断点续传
        _finish_task(task_id, False)


def _run_worker(task_id, cmd, base_name, output_file, target_format, initial_retry_count=0):
    # 继承 per-user 上下文（后台线程 thread-local 默认为空）
    _inherit_task_context(task_id)
    try:
        # .ts 源文件仍在（上次合成被打断）时优先直接重新合成，避免整段重新下载
        if find_pending_merge_source(base_name):
            debug_print(f"[下载] 发现未合成完的源文件，直接重新合成（无需重新下载）: {base_name}")
            if _finalize_download_outputs(base_name, output_file, target_format)[0]:
                _finish_task(task_id, True)
                return
        dl_result = _run_download_with_retry(cmd, task_id, max_retries=5, initial_retry_count=initial_retry_count, base_name=base_name)
        if dl_result in ('paused', 'deleted'):
            # 任务已暂停/已删除：保留部分下载文件（暂停续传），不写日志、不移除任务
            return
        if not dl_result:
            cleanup_residue(base_name, preserve_source=True)
            _finish_task(task_id, False)
            return

        time.sleep(1)

        # 在转格式阶段把进度更新到 90%（与原逻辑保持一致）
        source_file = find_existing_source_file(base_name)
        if source_file and (source_file.endswith('.ts') or source_file.lower().endswith('.mux.mp4')):
            with cfg.tasks_lock:
                if task_id in cfg.tasks:
                    cfg.tasks[task_id]['progress'] = 90
            save_tasks()

        ok, _final = _finalize_download_outputs(base_name, output_file, target_format)
        _finish_task(task_id, ok)

    except Exception as e:
        log_error(f"工作线程异常: {e}")
        # 异常时尝试共享后处理：若 output_file/source_file 还在，直接视为成功
        ok, _ = _finalize_download_outputs(base_name, output_file, target_format)
        _finish_task(task_id, ok)


def resume_tasks():
    global _resume_guard
    # 暂停中的任务重启后自动继续；排队中的任务保留其队列位置。
    # 统一按排队序号升序处理（FIFO），全部回到 queued 后由队列泵按名额拉起
    with cfg.tasks_lock:
        interrupted_tasks = [task for task in cfg.tasks.values()
                             if task['status'] in ('running', 'paused', 'queued')]
        interrupted_tasks.sort(key=lambda t: t.get('_qseq', 0))

    if not interrupted_tasks:
        return

    log_info(f"检测到 {len(interrupted_tasks)} 个未完成任务，开始恢复")

    # 恢复任务前检查网络状态
    debug_print("[恢复] 检查网络状态...")
    network_ready = _check_network_ready(max_wait=10)
    if not network_ready:
        debug_print("[恢复] 网络未就绪，尝试等待网络恢复...")
        network_ready = _check_network_ready(max_wait=30)
        if not network_ready:
            log_warning("网络长时间未就绪，仍尝试恢复任务（下载会自动重试）")
    debug_print(f"[恢复] 网络{'已就绪' if network_ready else '不稳定'}，开始恢复任务")

    # 恢复期间挂起队列泵：逐个完成任务体检与启动计划重建（成品已存在的直接
    # 收尾），全部处理完再统一放行，保证体检结果不被绕过、排队次序稳定
    _resume_guard = True
    try:
        for task in interrupted_tasks:
            try:
                _resume_single_task(task)
            except Exception as e:
                # 逐任务隔离：单个任务恢复异常（目录被删/数据损坏等）不应
                # 中断其余任务的恢复流程
                log_error(f"[恢复] 恢复任务失败 {task.get('id')}: {e}")
    finally:
        _resume_guard = False
    _pump_queue()


def _resume_single_task(task):
    """恢复单个任务：文件体检 + 重建启动计划并回到排队（resume_tasks 与网页端"继续"共用）"""
    task_id = task['id']
    url = task['url']
    save_name = task.get('save_name')
    referer = task.get('_referer')
    cookie = task.get('_cookie')
    user_agent = task.get('_user_agent')
    retry_count = task.get('_retry_count', 0)
    # per-task 输出格式：优先用任务自带的，回退到全局默认
    task_fmt = task.get('_output_format') or ''
    fmt = task_fmt if task_fmt in ('mp4', 'mkv') else cfg.output_format

    # 设置 per-user 上下文（恢复期文件检查在主线程执行）
    user = task.get('user') or 'default'
    _ddir = task.get('_download_dir') or os.path.join(cfg.DOWNLOAD_DIR, user)
    _tdir = cfg.user_temp_dir(user)
    _set_thread_context(user, _ddir, _tdir)
    # 确保 per-user 目录存在（卷内目录被删除后，恢复下载不致因目录缺失直接失败）
    try:
        os.makedirs(_ddir, exist_ok=True)
        os.makedirs(_tdir, exist_ok=True)
    except Exception as e:
        debug_print(f"[恢复] 创建用户目录失败: {e}")

    normalized_url = url.strip().rstrip('/')

    debug_print(f"[恢复] 恢复检查: {save_name or task_id} (ID: {task_id})，"
                f"url={sanitize_url_for_log(normalized_url)[:100]}...")

    url_hit, url_status = is_url_downloaded(url, user=user)
    if url_hit:
        debug_print(f"[恢复] URL 已在{'成功' if url_status == 'success' else '失败'}日志中，"
                    f"清理残留任务记录: {save_name or task_id}")
        # URL 已存在于成功/失败日志（is_url_downloaded 命中即证明），
        # 仅清除残留任务记录，不重复追加日志；按真实记录给出结果行
        _finish_task(task_id, url_status == 'success', write_log=False)
        return

    base_name = save_name or f"download_{task_id}"
    # 应用文件名过滤（按用户规则）
    original_name = base_name
    base_name, _ = filter_filename(base_name, user=user)
    base_name = sanitize_base_name(base_name, fallback=f"download_{task_id}")
    if base_name != original_name:
        # 更新任务中的 save_name 为过滤后的名称
        with cfg.tasks_lock:
            if task_id in cfg.tasks:
                cfg.tasks[task_id]['save_name'] = base_name

    # 优先处理"已合并 .ts 但未转封装成品"的残留（断电/停容器打断合成）：
    # 直接重新合成即可，无需重新下载。必须先于 has_existing_video 检查——
    # 转封装中途打断会留下体积达标但残缺的成品，先查成品会把损坏文件误判为完成。
    pending_src = find_pending_merge_source(base_name)
    if pending_src:
        debug_print(f"[恢复] 发现未合成完的源文件，直接重新合成（无需重新下载）: {pending_src}")
        output_file = os.path.join(get_download_dir(), f"{base_name}.{fmt}")
        ok, _ = _finalize_download_outputs(base_name, output_file, fmt)
        _finish_task(task_id, ok)
        return

    has_existing, existing_path = has_existing_video(base_name)
    if has_existing:
        debug_print(f"[恢复] 同名视频文件已存在，跳过恢复: {existing_path}")
        cleanup_copy_files(base_name)
        _finish_task(task_id, True)
        return

    has_any, any_path = has_any_existing_file(base_name)
    if has_any:
        debug_print(f"[恢复] 相关文件已存在，跳过恢复并清理: {any_path}")
        cleanup_copy_files(base_name)
        _finish_task(task_id, True)
        return

    user_temp = get_temp_dir()
    if os.path.exists(user_temp):
        temp_files = [f for f in os.listdir(user_temp) if match_base_name(f, base_name)]
        for temp_file in temp_files:
            temp_path = os.path.join(user_temp, temp_file)
            try:
                if temp_file.endswith('.tmp'):
                    os.remove(temp_path)
            except Exception as e:
                log_error(f"清理临时文件失败: {e}")

    is_direct_video, video_ext = classify_video_url(url, referer, cookie, user_agent)

    if is_direct_video:
        curl_target = output_file = os.path.join(get_download_dir(), f"{base_name}{video_ext}")
    else:
        curl_target, output_file = None, \
            os.path.join(get_download_dir(), f"{base_name}.{fmt}")

    if os.path.exists(output_file):
        if is_direct_video:
            file_size = os.path.getsize(output_file)
            if file_size >= cfg.MIN_FILE_SIZE:
                debug_print(f"[恢复] 文件已存在且完整，跳过恢复: {output_file}")
                _finish_task(task_id, True)
                return
            else:
                debug_print(f"[恢复] 文件已存在但过小 ({file_size} bytes)，继续断点续传: {output_file}")
        else:
            # m3u8 下载经 ffmpeg 转封装，输出文件已存在时仍需检查完整性：
            # 转封装中途被打断会留下体积不达标的残缺文件
            file_size = os.path.getsize(output_file)
            if file_size >= cfg.MIN_FILE_SIZE:
                debug_print(f"[恢复] 文件已存在且完整，跳过恢复: {output_file}")
                _finish_task(task_id, True)
                return
            else:
                debug_print(f"[恢复] 文件已存在但过小 ({file_size} bytes)，重新下载: {output_file}")
                try:
                    os.remove(output_file)
                except OSError:
                    pass

    # 重建启动计划并回到排队状态：暂停恢复与容器重启恢复统一走队列，
    # 由队列泵按并发名额拉起（前端「继续」与重启恢复共用本函数）
    plan = {
        'kind': 'direct' if is_direct_video else 'm3u8',
        'url': url,
        'base_name': base_name,
        'curl_target': curl_target,
        'output_file': output_file,
        'target_format': fmt,
        'retry_count': retry_count,
    }
    with cfg.tasks_lock:
        if task_id in cfg.tasks:
            cfg.tasks[task_id]['status'] = 'queued'
            if cfg.tasks[task_id].get('_qseq') is None:
                cfg.tasks[task_id]['_qseq'] = _next_qseq()
            cfg.tasks[task_id]['_plan'] = plan
    save_tasks(force=True)

    debug_print(f"[恢复] 重建启动计划: {save_name or task_id} (ID: {task_id})，"
                f"类型={'直链.' + str(video_ext) if is_direct_video else 'm3u8'}，已重试 {retry_count} 次")
    _pump_queue()
    pos = None if _resume_guard else queue_position(task_id)
    if pos is None:
        log_info(f"[{user}] 恢复下载: {save_name or task_id}")
    else:
        log_info(f"[{user}] 排队中: {save_name or task_id}（第 {pos} 位）")


# ---- 网页端任务控制（暂停 / 继续 / 删除）----

def pause_task(task_id, owner=None):
    """暂停任务：SIGINT 终止下载进程（N_m3u8DL-RE 保存进度 / curl 保留断点），
    任务状态置为 paused，worker 线程检测到后自行退出。

    owner 非 None 时校验任务所有权（不匹配按任务不存在处理，防止跨用户操作）。
    """
    with cfg.tasks_lock:
        task = cfg.tasks.get(task_id)
        if not task:
            return False, '任务不存在或已结束'
        if owner is not None and task.get('user', '') != owner:
            return False, '任务不存在或已结束'
        status = task['status']
        if status == 'paused':
            return False, '任务已是暂停状态'
        if status == 'queued':
            # 排队中的任务尚无下载进程，暂停无意义（前端只提供置顶 / 删除）
            return False, '排队中的任务无法暂停，可直接置顶或删除'
        task['status'] = 'paused'
        proc = task.get('_proc')

    _terminate_proc(proc, graceful=True)
    save_tasks(force=True)
    name = task.get('save_name') or task_id
    user = task.get('user') or 'default'
    log_info(f"[{user}] 已暂停: {name}")
    debug_print(f"[入口] 任务已暂停: {name} (ID: {task_id})")
    # 暂停释放并发名额，从队列取下一个任务补位
    _pump_queue()
    return True, '任务已暂停'


def resume_paused_task(task_id, owner=None):
    """继续暂停的任务：走与重启恢复相同的检查流程后重新启动下载。

    owner 非 None 时校验任务所有权（不匹配按任务不存在处理）。
    """
    with cfg.tasks_lock:
        task = cfg.tasks.get(task_id)
        if not task:
            return False, '任务不存在或已结束'
        if owner is not None and task.get('user', '') != owner:
            return False, '任务不存在或已结束'
        if task['status'] != 'paused':
            return False, '任务不在暂停状态'

    # 复制一份快照，避免与 worker 线程共享可变引用
    task_snapshot = dict(task)
    _resume_single_task(task_snapshot)
    return True, '任务已继续下载'


def delete_task(task_id, owner=None):
    """删除任务：杀进程、移除任务与视频组、删除已下载文件（含临时文件）。

    owner 非 None 时校验任务所有权（不匹配按任务不存在处理，不执行任何删除）。
    """
    with cfg.tasks_lock:
        task = cfg.tasks.get(task_id)
        if not task:
            return False, '任务不存在或已结束'
        if owner is not None and task.get('user', '') != owner:
            return False, '任务不存在或已结束'
        # 校验通过，同一锁内移出任务表
        cfg.tasks.pop(task_id, None)
        proc = task.get('_proc')

    # 强杀下载进程（删除无需保留进度）
    _terminate_proc(proc, graceful=False)

    save_name = task.get('save_name') or ''
    base_name = save_name or f"download_{task_id}"

    # 移除同视频模式的视频组（调度器检测到组消失会自行退出）
    with cfg.video_groups_lock:
        cfg.video_groups.pop(base_name, None)

    save_tasks(force=True)

    # 删除已下载文件：该用户的下载目录 + 缓存目录（temp/<用户>）
    user = task.get('user') or 'default'
    removed = 0
    for target_dir in [os.path.join(cfg.DOWNLOAD_DIR, user), cfg.user_temp_dir(user)]:
        if not os.path.exists(target_dir):
            continue
        for item in os.listdir(target_dir):
            if not match_base_name(item, base_name):
                continue
            item_path = os.path.join(target_dir, item)
            try:
                if os.path.isdir(item_path):
                    shutil.rmtree(item_path)
                else:
                    os.remove(item_path)
                removed += 1
            except Exception as e:
                log_error(f"删除任务文件失败: {item_path} - {e}")

    log_info(f"[{user}] 已删除: {base_name}")
    debug_print(f"[入口] 任务已删除: {base_name} (ID: {task_id})，清理文件 {removed} 个")
    # 删除释放并发名额，从队列取下一个任务补位
    _pump_queue()
    return True, f'任务已删除（清理文件 {removed} 个）'


def pin_task(task_id, owner=None):
    """把排队中的任务置顶（插到队首，优先获取下一个并发名额）。

    owner 非 None 时校验任务所有权（不匹配按任务不存在处理）。
    非排队状态的任务不可置顶（置顶只影响队列次序）。
    """
    with cfg.tasks_lock:
        task = cfg.tasks.get(task_id)
        if not task:
            return False, '任务不存在或已结束'
        if owner is not None and task.get('user', '') != owner:
            return False, '任务不存在或已结束'
        if task.get('status') != 'queued':
            return False, '仅排队中的任务可置顶'
        user = task.get('user')
        waiting = [t for t in _queued_tasks(user) if t['id'] != task_id]
        # 取当前用户队列中（排除自身）最小序号减一，保证排在该用户所有排队任务之前
        task['_qseq'] = (waiting[0].get('_qseq', 0) if waiting else 0) - 1
    save_tasks(force=True)
    name = task.get('save_name') or task_id
    user = task.get('user') or 'default'
    log_info(f"[{user}] 已置顶: {name}")
    _pump_queue()
    return True, '已置顶到队首'


def run_download(url, save_name=None, referer=None, cookie=None, user_agent=None, user=None, output_format=None):
    normalized_url = url.strip().rstrip('/')
    # 解析本次任务的输出格式：网页可逐任务指定，不传时回退到全局默认（mp4）
    fmt = output_format if output_format in ('mp4', 'mkv') else cfg.output_format
    # per-user 目录：下载 /home/downloader/downloads/<用户名>，缓存 /home/downloader/temp/<用户名>
    if not user:
        user = 'default'
    download_dir = os.path.join(cfg.DOWNLOAD_DIR, user)
    user_temp_dir = cfg.user_temp_dir(user)
    try:
        os.makedirs(download_dir, exist_ok=True)
        os.makedirs(user_temp_dir, exist_ok=True)
    except Exception as e:
        debug_print(f"[入口] 创建用户目录失败: {e}")
    _set_thread_context(user, download_dir, user_temp_dir)
    debug_print(f"[入口] 收到任务: {save_name or '(未命名)'} | 用户={user} | "
                f"URL={sanitize_url_for_log(normalized_url)[:100]}")

    # ---- same_video_by_filename 模式分支 ----
    if cfg.same_video_by_filename_enabled:
        # 计算 base_name（标准过滤后的文件名）作为"同一视频"的唯一键
        task_id_tmp = str(uuid.uuid4())[:8]
        base_name_raw = save_name or f"download_{task_id_tmp}"
        base_name, ad_count = filter_filename(base_name_raw, user=user)
        base_name = sanitize_base_name(base_name, fallback=f"download_{task_id_tmp}")

        # 1) 检查日志：文件名是否已成功/失败记录过（按用户隔离）
        name_hit, name_status = is_filename_downloaded(base_name, user=user)
        if name_hit and not (name_status == 'failure'
                             and find_pending_merge_source(base_name)):
            # 失败记录通常拦下重试；但若上次是合成中途被打断（.ts 源仍在），
            # 放行重建任务——调度器入口会直接重新合成，无需重新下载
            debug_print(f"[去重] 文件名命中{('成功' if name_status == 'success' else '失败')}记录，跳过: {base_name}")
            reason = "已下载过" if name_status == 'success' else "此前已失败"
            log_info(f"[{user}] 跳过下载: {base_name}（{reason}）")
            return None, False

        # 2) 检查本地文件是否已存在（调用共享检查）
        skip, hit_path = _check_local_file_exists_skip(base_name)
        if skip:
            suffix = "同名视频文件" if hit_path and is_video_file(os.path.basename(hit_path)) else "相关文件"
            debug_print(f"[去重] {suffix}已存在，跳过: {hit_path}")
            log_info(f"[{user}] 跳过下载: {base_name}（文件已存在）")
            return None, False

        # 3) 加入 / 创建视频组
        # 锁序约定：video_groups_lock → tasks_lock 禁止嵌套（_run_same_video_group_worker
        # 以 tasks_lock → video_groups_lock 顺序持有），此处先在 video_groups_lock 内
        # 记录需要同步的 task_id，释放后再持 tasks_lock 更新，避免 ABBA 死锁
        _sync_task_id = None
        _reuse_result = None
        with cfg.video_groups_lock:
            existing_group = cfg.video_groups.get(base_name)
            if existing_group is not None:
                status = existing_group['status']
                # URL 去重后加入
                new_tuple = (normalized_url, referer or '', cookie or '', user_agent or '')
                url_exists = any(
                    u[0] == new_tuple[0] for u in existing_group['urls']
                )
                if not url_exists:
                    existing_group['urls'].append(new_tuple)
                    _sync_task_id = existing_group['task_id']
                    debug_print(f"[调度器] 视频组 {base_name} 追加新链接 (总计 {len(existing_group['urls'])} 个)")
                else:
                    debug_print(f"[调度器] 视频组 {base_name} 链接已存在，忽略")

                if status in ('collecting', 'running'):
                    _reuse_result = existing_group['task_id']
                elif status == 'done':
                    # 视频组此前 5 轮失败后标记为 done，新 URL 提交时重置状态允许重试
                    existing_group['status'] = 'collecting'
                    existing_group['round_count'] = 0
                    existing_group['current_index'] = len(existing_group['urls']) - 1
                    debug_print(f"[调度器] 视频组 {base_name} 此前已失败，重置状态允许重试")

            if _reuse_result is None:
                # 创建新视频组（existing_group 为 None，或状态非 collecting/running/done）
                new_task_id = str(uuid.uuid4())[:8]
                new_group = {
                    'task_id': new_task_id,
                    'urls': [(normalized_url, referer or '', cookie or '', user_agent or '')],
                    'current_index': 0,
                    'round_count': 0,
                    'status': 'collecting',
                    'output_format': fmt
                }
                cfg.video_groups[base_name] = new_group
                task_id = new_task_id
                debug_print(f"[调度器] 新建视频组 {base_name}, task_id={task_id}, 链接数=1")

        # 在 video_groups_lock 外同步更新关联任务的 urls 列表，避免死锁
        if _sync_task_id:
            with cfg.tasks_lock:
                gt = cfg.tasks.get(_sync_task_id)
                if gt is not None and normalized_url not in gt['urls']:
                    gt['urls'].append(normalized_url)

        # 复用已有视频组：状态已在锁内判定，锁外返回
        if _reuse_result is not None:
            if _reuse_result is False:
                debug_print(f"[调度器] 视频组 {base_name} 已完成，跳过")
                return None, False
            debug_print(f"[调度器] 复用视频组任务 {_reuse_result} -> {base_name}")
            return _reuse_result, True

        # 创建对应的 tasks 记录（用于进度/排队），随后交给队列泵按名额启动
        plan = {'kind': 'same_video', 'url': normalized_url,
                'base_name': base_name, 'fmt': fmt}
        with cfg.tasks_lock:
            cfg.tasks[task_id] = {
                'id': task_id,
                'url': normalized_url,
                'urls': [normalized_url],
                'save_name': base_name,
                'status': 'queued',
                'progress': 0,
                'user': user,
                '_download_dir': download_dir,
                '_referer': referer,
                '_cookie': cookie,
                '_user_agent': user_agent,
                '_retry_count': 0,
                '_qseq': _next_qseq(),
                '_output_format': fmt,
                '_plan': plan
            }
        save_tasks()

        debug_print(f"[入口] 任务登记: {base_name} (ID: {task_id}) | 模式=同视频调度"
                    + (f" | 文件名过滤 {ad_count} 处" if ad_count > 0 else ""))
        _pump_queue()
        _log_task_start(user, base_name, task_id)
        return task_id, False

    # ---- 原有逻辑 (same_video_by_filename 关闭时) ----
    url_hit, url_status = is_url_downloaded(url, user=user)
    if url_hit:
        display_name = save_name or normalized_url
        reason = "已下载过" if url_status == 'success' else "此前已失败"
        log_info(f"[{user}] 跳过下载: {display_name}（{reason}）")
        return None, False

    with cfg.tasks_lock:
        for task_id, task in cfg.tasks.items():
            # 仅在同用户内查重：跨用户复用会让提交者拿到他人的 task_id，
            # 而 /tasks 列表与暂停/删除均有 owner 校验，该次下载对其「消失」。
            if task.get('user') != user:
                continue
            task_url = task['url'].strip().rstrip('/')
            if task_url == normalized_url:
                dup_name = task.get('save_name') or task_id
                if task['status'] in ('running', 'queued'):
                    debug_print(f"[去重] 重复链接，复用进行中任务: {dup_name} (ID: {task_id})")
                    log_info(f"[{user}] 跳过下载: {dup_name}（任务已在处理中）")
                    return task_id, True
                else:
                    debug_print(f"[去重] URL 任务已存在（{task['status']}）: {dup_name} (ID: {task_id})")
                    log_info(f"[{user}] 跳过下载: {dup_name}（任务已存在:{task['status']}）")
                    return None, False

    is_direct_video, video_ext = classify_video_url(url, referer, cookie, user_agent)

    task_id = str(uuid.uuid4())[:8]
    base_name = save_name or f"download_{task_id}"

    # 应用文件名过滤（按用户规则）
    base_name, ad_count = filter_filename(base_name, user=user)
    base_name = sanitize_base_name(base_name, fallback=f"download_{task_id}")

    skip, hit_path = _check_local_file_exists_skip(base_name)
    if skip:
        if hit_path and is_video_file(os.path.basename(hit_path)):
            debug_print(f"[去重] 同名视频文件已存在: {hit_path}")
        else:
            debug_print(f"[去重] 相关文件已存在（可能是.copy文件）: {hit_path}")
        log_info(f"[{user}] 跳过下载: {base_name}（文件已存在）")
        return None, False

    if is_direct_video:
        curl_target = output_file = os.path.join(get_download_dir(), f"{base_name}{video_ext}")
    else:
        curl_target, output_file = None, \
            os.path.join(get_download_dir(), f"{base_name}.{fmt}")

    if os.path.exists(output_file):
        if is_direct_video:
            file_size = os.path.getsize(output_file)
            if file_size < cfg.MIN_FILE_SIZE:
                debug_print(f"[去重] 输出文件过小 ({file_size} bytes)，继续断点续传: {base_name}")
            else:
                debug_print(f"[去重] 输出文件已存在: {output_file}")
                log_info(f"[{user}] 跳过下载: {base_name}（文件已存在）")
                return None, False
        else:
            debug_print(f"[去重] 输出文件已存在: {output_file}")
            log_info(f"[{user}] 跳过下载: {base_name}（文件已存在）")
            return None, False
    else:
        alternate_output = find_existing_output_file(base_name)
        if alternate_output:
            debug_print(f"[去重] 检测到其他格式成品: {alternate_output}")
            log_info(f"[{user}] 跳过下载: {base_name}（文件已存在）")
            return None, False

    plan = {
        'kind': 'direct' if is_direct_video else 'm3u8',
        'url': url,
        'base_name': base_name,
        'curl_target': curl_target,
        'output_file': output_file,
        'target_format': fmt,
        'retry_count': 0,
    }

    with cfg.tasks_lock:
        cfg.tasks[task_id] = {
            'id': task_id,
            'url': url,
            'urls': [url],
            'save_name': base_name,
            'status': 'queued',
            'progress': 0,
            'user': user,
            '_download_dir': download_dir,
            '_referer': referer,
            '_cookie': cookie,
            '_user_agent': user_agent,
            '_retry_count': 0,
            '_qseq': _next_qseq(),
            '_output_format': fmt,
            '_plan': plan
        }

    save_tasks()

    debug_print(f"[入口] 任务登记: {base_name} (ID: {task_id}) | "
                f"类型={'直链' + str(video_ext) if is_direct_video else 'm3u8'} | "
                f"输出={output_file}" + (f" | 文件名过滤 {ad_count} 处" if ad_count > 0 else ""))
    if is_direct_video:
        debug_print(f"[下载] 直链视频 {video_ext}：curl 直接下载: {base_name}")
    else:
        _user_kws = get_ad_keywords(user)
        if _user_kws:
            debug_print(f"[入口] 广告关键字过滤 {len(_user_kws)} 个: {base_name}")

    _pump_queue()
    _log_task_start(user, base_name, task_id)
    return task_id, False


def cleanup_all_copy_files():
    """启动期清理：扫描基础目录 + 所有 per-user 子目录的 .copy 残留"""
    if not os.path.exists(cfg.DOWNLOAD_DIR):
        return

    # 基础目录 + 所有 per-user 子目录
    dirs_to_scan = [cfg.DOWNLOAD_DIR]
    try:
        for name in os.listdir(cfg.DOWNLOAD_DIR):
            sub = os.path.join(cfg.DOWNLOAD_DIR, name)
            if os.path.isdir(sub):
                dirs_to_scan.append(sub)
    except Exception:
        pass

    copy_pattern = re.compile(r'^(.+?)(?:\.copy)+(\.(?:mp4|mkv))?$')

    for scan_dir in dirs_to_scan:
        if not os.path.exists(scan_dir):
            continue
        # 让 cleanup_copy_files 在本线程扫描此目录
        _set_thread_download_dir(scan_dir)
        processed_base_names = set()
        try:
            for item in os.listdir(scan_dir):
                item_path = os.path.join(scan_dir, item)
                if not os.path.isfile(item_path):
                    continue
                match = copy_pattern.match(item)
                if match:
                    base_name = match.group(1)
                    if base_name not in processed_base_names:
                        processed_base_names.add(base_name)
                        cleanup_copy_files(base_name)
        except Exception:
            pass
    # 清理后重置上下文，回退到基础目录
    _set_thread_context(None, None, None)


def cleanup_user_data(username):
    """删除用户的全部数据：终止其所有任务（杀进程/移出任务表）并删除三个目录。

    目录：user/<名>/（配置与日志）、temp/<名>/（缓存）、downloads/<名>/（成品）。
    返回 (终止任务数, 是否全部清理成功)。
    """
    killed = 0
    with cfg.tasks_lock:
        user_task_ids = [t['id'] for t in cfg.tasks.values() if t.get('user') == username]
    for task_id in user_task_ids:
        try:
            delete_task(task_id)
            killed += 1
        except Exception as e:
            log_error(f"删除用户任务失败: {task_id} - {e}")

    all_ok = True
    for target_dir in [cfg.user_config_dir(username), cfg.user_temp_dir(username),
                       os.path.join(cfg.DOWNLOAD_DIR, username)]:
        if not os.path.exists(target_dir):
            continue
        try:
            shutil.rmtree(target_dir)
        except Exception as e:
            all_ok = False
            log_error(f"删除用户目录失败: {target_dir} - {e}")

    # 释放该用户的去重缓存与过滤规则缓存
    import dedup
    dedup.drop_user_cache(username)
    reload_user_rules(username)
    debug_print(f"[清理] 已删除用户 {username} 的数据目录，终止任务 {killed} 个，"
                f"目录清理{'完成' if all_ok else '存在失败项'}")
    return killed, all_ok
