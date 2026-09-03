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
import time
import shutil
import uuid
import signal
import subprocess
import threading

import app_config as cfg
from app_logger import log_info, log_warning, log_error, debug_print
from task_store import save_tasks, append_log
from dedup import is_url_downloaded, is_filename_downloaded
from filters import filter_filename
from security import sanitize_url_for_log


# ---- per-user 下载目录（线程级上下文）----
# 下载在后台线程执行，请求线程的上下文不会自动传递；
# 在 run_download(请求线程) 与各 worker 入口显式设置，扫描类函数统一读 get_download_dir()。
_download_dir_local = threading.local()


def _set_thread_download_dir(path):
    """设置当前线程的下载目录（per-user）"""
    _download_dir_local.path = path


def get_download_dir():
    """获取当前线程的下载目录；未设置时回退到基础 DOWNLOAD_DIR"""
    return getattr(_download_dir_local, 'path', None) or cfg.DOWNLOAD_DIR


FORMAT_MAP = {
    'mp4': 'mp4',
    'mkv': 'matroska'
}


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


def is_video_file(file_name):
    return os.path.splitext(file_name)[1].lower() in VIDEO_EXTS


def extract_percent(line):
    match = re.search(r'(\d{1,3})%', line)
    if match:
        return int(match.group(1))
    return None


def match_base_name(name, base):
    return name == base or name.startswith(base + '.') or name.startswith(base + '_')


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


def cleanup_residue(base_name, exclude_file=None, preserve_source=True):
    """清理下载完成后残留的临时文件、文件夹和 .tmp 文件"""
    for dir_to_clean in [get_download_dir(), cfg.TEMP_DIR]:
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
            socket.setdefaulttimeout(3)
            socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect(('223.5.5.5', 53))
            return True
        except Exception:
            pass

        time.sleep(2)

    return False


def _build_m3u8_cmd(url, base_name, referer=None, cookie=None, user_agent=None):
    """构建 N_m3u8DL-RE 下载命令（resume_tasks 和 run_download 共用）"""
    cmd = [cfg.N_M3U8DL, url,
           '--tmp-dir', cfg.TEMP_DIR,
           '--save-dir', get_download_dir(),
           '--ffmpeg-binary-path', cfg.FFMPEG_PATH,
           '--save-name', base_name,
           '--auto-select']
    if referer:
        cmd.extend(['-H', f'Referer: {referer}'])
    if cookie:
        cmd.extend(['--cookie', cookie])
    if user_agent:
        cmd.extend(['--user-agent', user_agent])
    if cfg.keywords_enabled and cfg.ad_keywords:
        for keyword in cfg.ad_keywords:
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
        debug_print(f"终止下载进程失败: {e}")


def _run_download_with_retry(cmd, task_id, max_retries=5, initial_retry_count=0, base_name=""):
    """返回: True 下载成功 / False 重试耗尽 / 'paused' 任务被暂停 / 'deleted' 任务被删除"""
    retry_count = initial_retry_count
    while retry_count < max_retries:
        # 循环顶响应暂停/删除（覆盖退避等待、网络检查期间收到的请求）
        status = _get_task_status(task_id)
        if status is None:
            return 'deleted'
        if status == 'paused':
            debug_print(f"任务已暂停，停止下载尝试 (ID: {task_id})")
            return 'paused'

        debug_print(f"下载尝试 {retry_count + 1}/{max_retries} (ID: {task_id}, 名称: {base_name})")

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

        # 暂停/删除请求优先于结果判定，防止 SIGINT 退出码被误判为失败或误判成功
        status = _get_task_status(task_id)
        if status is None:
            return 'deleted'
        if status == 'paused':
            debug_print(f"任务已暂停，停止下载尝试 (ID: {task_id})")
            return 'paused'

        if return_code == 0:
            log_info(f"下载成功")
            return True

        existing_file = find_existing_source_file(base_name)
        if existing_file:
            debug_print(f"下载工具返回非零码 {return_code}，但已检测到可用输出文件: {existing_file}")
            return True

        debug_print(f"下载失败，返回码: {return_code}")

        with cfg.tasks_lock:
            if task_id in cfg.tasks:
                cfg.tasks[task_id]['_retry_count'] = retry_count + 1
                save_tasks(force=True)

        if retry_count < max_retries - 1:
            # 计算指数退避等待时间：5s, 10s, 20s, 40s...
            wait_time = min(5 * (2 ** retry_count), 60)
            debug_print(f"准备重试，保留已下载文件以便续传，等待 {wait_time} 秒...")

            # 在重试前检查网络状态
            if not _check_network_ready(max_wait=wait_time):
                debug_print(f"网络未就绪，继续等待...")
                if not _check_network_ready(max_wait=30):
                    debug_print(f"网络长时间未就绪，跳过本次重试")
                    retry_count += 1
                    continue

            time.sleep(1)

        retry_count += 1

    debug_print(f"下载失败，已尝试 {max_retries} 次")
    return False


def _do_single_download_attempt(base_name, url, referer, cookie, user_agent, task_id=None, output_format=None):
    """对单个 URL 进行单次下载尝试（不操作 tasks 状态，不写日志）

    适用于 same_video_by_filename 模式下调度器对单个链接的一次尝试。
    task_id 用于把下载进程挂到真实任务上（暂停/删除寻址），
    并透传 'paused'/'deleted' 状态给调度器。
    """
    fmt = output_format if output_format in ('mp4', 'mkv') else cfg.output_format
    debug_print(f"_do_single_download_attempt: base_name={base_name}, url={sanitize_url_for_log(url)[:100]}...")
    is_direct_video, video_ext = is_direct_video_url(url)

    if is_direct_video:
        output_file = os.path.join(get_download_dir(), f"{base_name}{video_ext}")
    else:
        output_file = os.path.join(get_download_dir(), f"{base_name}.{fmt}")

    # 尝试前先清理残留（避免上一次失败的残留影响，但是保留已存在的大文件 -> 直接成功）
    has_existing, existing_path = has_existing_video(base_name)
    if has_existing:
        debug_print(f"已存在同名视频文件，本次尝试直接视为成功: {existing_path}")
        return True
    if os.path.exists(output_file):
        file_size = os.path.getsize(output_file)
        if file_size >= cfg.MIN_FILE_SIZE:
            debug_print(f"输出文件已存在且完整: {output_file}")
            return True

    success = False
    try:
        if is_direct_video:
            # 直接视频下载，使用 curl，只重试1次
            cmd = _build_curl_cmd(url, output_file, referer, cookie, user_agent)

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
                debug_print(f"[单链接尝试] 任务已暂停，停止下载: {base_name}")
                return 'paused'

            if os.path.exists(output_file):
                file_size = os.path.getsize(output_file)
                if file_size >= cfg.MIN_FILE_SIZE:
                    if return_code == 0:
                        debug_print(f"[单链接尝试] 直接下载成功: {output_file}")
                        success = True
                    else:
                        debug_print(f"[单链接尝试] 命令返回非零但文件有效: {output_file}")
                        success = True
                else:
                    debug_print(f"[单链接尝试] 下载文件太小 ({file_size} bytes)")
                    try:
                        if os.path.exists(output_file):
                            os.remove(output_file)
                    except Exception:
                        pass
            else:
                debug_print(f"[单链接尝试] 直接下载失败，返回码: {return_code}")
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
                    debug_print(f"[单链接尝试] 命令报告失败但检测到可用文件: {existing_file}")
                    download_ok = True

            if not download_ok:
                debug_print(f"[单链接尝试] m3u8下载命令失败")
                cleanup_residue(base_name, preserve_source=True)
                return False

            time.sleep(0.5)

            # 后处理：调用共享函数完成 定位/转换/校验/清理
            ok, _final = _finalize_download_outputs(base_name, output_file, fmt)
            if ok:
                success = True

        if success:
            debug_print(f"[单链接尝试] 下载+后处理成功: {base_name}")
        return success

    except Exception as e:
        debug_print(f"[单链接尝试] 异常: {e}")
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
    all_files = [f for f in os.listdir(download_dir) if match_base_name(f, base_name)]
    ts_files = [f for f in all_files if f.lower().endswith('.ts')]
    mux_files = [f for f in all_files if f.lower().endswith('.mux.mp4')]
    video_files = [f for f in all_files if is_video_file(f) and '.mux.' not in f.lower()]

    source_file = None
    if mux_files:
        source_file = os.path.join(download_dir, mux_files[0])
    elif video_files:
        source_file = os.path.join(download_dir, video_files[0])
    elif ts_files:
        source_file = os.path.join(download_dir, ts_files[0])

    # (A) 输出文件已存在（可能由下载工具直接生成）
    if os.path.exists(output_file):
        file_size = os.path.getsize(output_file)
        if file_size >= cfg.MIN_FILE_SIZE:
            debug_print(f"[finalize] 输出文件已存在且完整: {output_file}")
            cleanup_residue(base_name, exclude_file=output_file, preserve_source=False)
            return True, output_file
        alt = find_existing_output_file(base_name)
        if alt and os.path.abspath(alt) != os.path.abspath(output_file):
            debug_print(f"[finalize] 找到备用输出文件: {alt}")
            cleanup_residue(base_name, exclude_file=alt, preserve_source=False)
            return True, alt

    # (B) 没有找到 source_file → 再试一次找 备用输出文件 / output_file 存在性
    if not source_file or not os.path.exists(source_file):
        debug_print(f"[finalize] 找不到源文件，检查备用输出文件")
        alt = find_existing_output_file(base_name)
        if alt:
            debug_print(f"[finalize] 使用现有备用输出文件: {alt}")
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
    if source_file.endswith('.ts') or source_file.endswith('.MUX.mp4'):
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
                debug_print(f"[finalize] 输出文件太小，使用源文件代替: {source_file}")
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
            debug_print(f"[finalize] 转换未生成输出，使用源文件作最终输出: {source_file}")
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


def has_any_existing_file(base_name):
    download_dir = get_download_dir()
    if not os.path.exists(download_dir):
        return False, None

    copy_pattern = re.compile(rf'^{re.escape(base_name)}(?:\.copy)+(\.(?:mp4|mkv))?$', re.IGNORECASE)

    for item in os.listdir(download_dir):
        if not match_base_name(item, base_name):
            continue

        item_path = os.path.join(download_dir, item)
        if os.path.isfile(item_path):
            if item == base_name:
                return True, item_path
            file_size = os.path.getsize(item_path)
            if file_size >= cfg.MIN_FILE_SIZE_SMALL:
                if copy_pattern.match(item) or is_video_file(item):
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
                    log_info(f"已清理重复文件: {item_path}")
                except Exception as e:
                    log_info(f"清理重复文件失败: {item_path} - {e}")
    elif copy_files:
        copy_files.sort(reverse=True, key=lambda x: x[0])
        keep_file = copy_files[0][1]
        keep_name = os.path.basename(keep_file)

        new_name = keep_name.replace('.copy', '')
        new_path = os.path.join(download_dir, new_name)

        try:
            if keep_file != new_path:
                os.rename(keep_file, new_path)
                log_info(f"已重命名主文件: {keep_file} -> {new_path}")
                keep_file = new_path
        except Exception as e:
            log_info(f"重命名主文件失败: {e}")

        for file_size, item_path in copy_files[1:]:
            if item_path != keep_file:
                try:
                    os.remove(item_path)
                    log_info(f"已清理重复文件: {item_path}")
                except Exception as e:
                    log_info(f"清理重复文件失败: {item_path} - {e}")


def _finish_task(task_id, success):
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
        log_file = cfg.SUCCESS_LOG_FILE if success else cfg.FAILURE_LOG_FILE
        try:
            append_log(log_file, task_data)
            debug_print(f"任务日志已写入: {task_id}, success={success}, log_file={log_file}")
        except Exception as e:
            log_error(f"写入日志失败，任务保留在列表中: {task_id} - {e}")
            debug_print(f"写入日志失败，任务保留在列表中: {task_id} - {e}")
            # 日志写入失败，保留任务以便重启后恢复
            return
        del cfg.tasks[task_id]
        save_tasks(force=True)
        debug_print(f"任务已删除: {task_id}, 剩余任务数={len(cfg.tasks)}")

    if task_data:
        log_info(f"任务 {task_id} {'已完成' if success else '失败'}并从任务列表中删除")


def _run_same_video_group_worker(task_id, base_name, output_format=None):
    """多链接调度 Worker: 按顺序轮流尝试同一个视频的所有链接。

    策略：
      - 把同一视频的所有 URL 按顺序排列，轮流依次尝试
      - 每一圈（从 current_index 开始，每个链接各尝试 1 次，
        直到回到"本轮起点"之前那个链接仍未成功）算一次"失败回合"
      - 总共 5 个失败回合后放弃该视频
      - 期间如果接收到新 URL，会在下一圈开始时加入队列
    """
    debug_print(f"[多链接调度] 启动视频组任务 {task_id}: {base_name}")

    # 继承 per-user 下载目录（后台线程 thread-local 默认为空）
    with cfg.tasks_lock:
        _td = cfg.tasks.get(task_id)
        if _td and _td.get('_download_dir'):
            _set_thread_download_dir(_td['_download_dir'])

    with cfg.video_groups_lock:
        group = cfg.video_groups.get(base_name)
        if group is None:
            debug_print(f"[多链接调度] 找不到视频组 {base_name}，任务结束")
            _finish_task(task_id, False)
            return
        group['status'] = 'running'
        task_url_for_log = group['urls'][0][0] if group['urls'] else ''

    # 先检查文件是否已经存在（可能是被并发其他流程下载的）
    has_existing, existing_path = has_existing_video(base_name)
    if has_existing:
        debug_print(f"[多链接调度] 视频已存在，视为成功: {existing_path}")
        with cfg.video_groups_lock:
            group = cfg.video_groups.get(base_name)
            if group:
                group['status'] = 'done'
        # 更新 task 的 url 以供日志写入
        with cfg.tasks_lock:
            if task_id in cfg.tasks:
                cfg.tasks[task_id]['url'] = task_url_for_log
                cfg.tasks[task_id]['save_name'] = base_name
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
                debug_print(f"[多链接调度] 视频组 {base_name} URL 列表为空，等待 5 秒...")
                time.sleep(5)
                # 等待期间如果有新 URL，则继续；否则超时放弃
                with cfg.video_groups_lock:
                    group = cfg.video_groups.get(base_name)
                    if group and group['urls']:
                        continue
                debug_print(f"[多链接调度] 视频组 {base_name} 长时间无 URL，放弃")
                break

            if round_count >= 5:
                debug_print(f"[多链接调度] {base_name} 已完成 5 轮失败，放弃下载")
                break

            n_urls = len(urls_snapshot)
            if total_urls_count_ever < n_urls:
                total_urls_count_ever = n_urls

            debug_print(f"[多链接调度] 第 {round_count + 1}/5 轮开始, "
                     f"共 {n_urls} 个链接, 起始索引={start_index} ({base_name})")

            # 一圈：每个链接尝试 1 次（按顺序轮转，一圈后仍未成功就算一个失败回合）
            round_succeed = False
            for i in range(n_urls):
                idx = (start_index + i) % n_urls
                url, ref, ck, ua = urls_snapshot[idx]

                # 每尝试一个链接之前，再次检查是否已成功（防止并发完成）
                has_existing, existing_path = has_existing_video(base_name)
                if has_existing:
                    debug_print(f"[多链接调度] 检测到视频已下载完成: {existing_path}")
                    round_succeed = True
                    break

                debug_print(f"[多链接调度] 尝试链接 {idx + 1}/{n_urls} (第{round_count+1}轮) "
                         f"[{sanitize_url_for_log(url)[:80]}...] -> {base_name}")

                # 更新进度（顺带响应 sleep 间隙收到的暂停/删除请求）
                with cfg.tasks_lock:
                    _t = cfg.tasks.get(task_id)
                    if _t is None:
                        debug_print(f"[多链接调度] 任务已删除，调度器退出: {base_name}")
                        return
                    if _t['status'] == 'paused':
                        with cfg.video_groups_lock:
                            g = cfg.video_groups.get(base_name)
                            if g:
                                g['status'] = 'paused'
                                g['current_index'] = idx
                        debug_print(f"[多链接调度] 任务已暂停，调度器退出: {base_name}")
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
                    debug_print(f"[多链接调度] 任务{'已暂停' if ok == 'paused' else '已删除'}，调度器退出: {base_name}")
                    return
                if ok:
                    debug_print(f"[多链接调度] 链接 {idx + 1} 下载成功: {base_name}")
                    round_succeed = True
                    break
                else:
                    debug_print(f"[多链接调度] 链接 {idx + 1} 失败，准备切换下一个...")
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
                _finish_task(task_id, True)
                return

            # 一整圈失败，回合数 + 1，移动起始索引（从下一个链接开始新一轮，达到"轮流"效果）
            with cfg.video_groups_lock:
                group = cfg.video_groups.get(base_name)
                if group:
                    group['round_count'] = round_count + 1
                    group['current_index'] = (start_index + 1) % max(1, len(group['urls']))
                    debug_print(f"[多链接调度] 第 {round_count + 1}/5 轮结束，所有链接均失败。"
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
        _finish_task(task_id, False)

    except Exception as e:
        debug_print(f"[多链接调度] 异常: {e}")
        with cfg.video_groups_lock:
            group = cfg.video_groups.get(base_name)
            if group:
                group['status'] = 'done'
        with cfg.tasks_lock:
            if task_id in cfg.tasks:
                cfg.tasks[task_id]['save_name'] = base_name
        _finish_task(task_id, False)


def _run_direct_download_worker(task_id, url, output_file, referer, cookie, user_agent, initial_retry_count=0):
    # 继承 per-user 下载目录（后台线程 thread-local 默认为空）
    with cfg.tasks_lock:
        _td = cfg.tasks.get(task_id)
        if _td and _td.get('_download_dir'):
            _set_thread_download_dir(_td['_download_dir'])
    try:
        cmd = _build_curl_cmd(url, output_file, referer, cookie, user_agent)

        base_name = os.path.basename(output_file)
        max_retries = 5
        retry_count = initial_retry_count
        while retry_count < max_retries:
            # 循环顶响应暂停/删除（覆盖退避等待、网络检查期间收到的请求）
            status = _get_task_status(task_id)
            if status is None:
                return
            if status == 'paused':
                debug_print(f"任务已暂停，停止下载尝试 (ID: {task_id})")
                return

            debug_print(f"直接下载尝试 {retry_count + 1}/{max_retries} (ID: {task_id}, 名称: {base_name}): {sanitize_url_for_log(url)} -> {output_file}")

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
                debug_print(f"任务已暂停，停止下载尝试 (ID: {task_id})")
                return

            if os.path.exists(output_file):
                file_size = os.path.getsize(output_file)
                if file_size >= cfg.MIN_FILE_SIZE:
                    if return_code == 0:
                        log_info(f"下载成功")
                        _finish_task(task_id, True)
                        return
                    else:
                        debug_print(f"直接下载命令返回非零码 {return_code}，但已检测到有效输出文件: {output_file} (大小: {file_size} bytes)")
                        _finish_task(task_id, True)
                        return
                else:
                    debug_print(f"下载文件太小 ({file_size} bytes)，可能是错误页面")

            debug_print(f"直接下载失败，返回码: {return_code}")

            with cfg.tasks_lock:
                if task_id in cfg.tasks:
                    cfg.tasks[task_id]['_retry_count'] = retry_count + 1
                    save_tasks(force=True)

            if retry_count < max_retries - 1:
                # 计算指数退避等待时间：5s, 10s, 20s, 40s...
                wait_time = min(5 * (2 ** retry_count), 60)
                debug_print(f"准备重试，保留已下载文件以便续传，等待 {wait_time} 秒...")

                # 在重试前检查网络状态
                if not _check_network_ready(max_wait=wait_time):
                    debug_print(f"网络未就绪，继续等待...")
                    if not _check_network_ready(max_wait=30):
                        debug_print(f"网络长时间未就绪，跳过本次重试")
                        retry_count += 1
                        continue

                time.sleep(1)

            retry_count += 1

        debug_print(f"直接下载失败，已尝试 {max_retries} 次")
        if os.path.exists(output_file):
            os.remove(output_file)
            debug_print(f"已删除不完整文件: {output_file}")
        _finish_task(task_id, False)
    except Exception as e:
        log_error(f"直接下载线程异常: {e}")
        if os.path.exists(output_file):
            os.remove(output_file)
        _finish_task(task_id, False)


def _run_worker(task_id, cmd, base_name, output_file, target_format, initial_retry_count=0):
    # 继承 per-user 下载目录（后台线程 thread-local 默认为空）
    with cfg.tasks_lock:
        _td = cfg.tasks.get(task_id)
        if _td and _td.get('_download_dir'):
            _set_thread_download_dir(_td['_download_dir'])
    try:
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
        if source_file and (source_file.endswith('.ts') or source_file.endswith('.MUX.mp4')):
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
    # 暂停中的任务重启后自动继续（与未完成任务一并恢复）
    with cfg.tasks_lock:
        interrupted_tasks = [task for task in cfg.tasks.values()
                             if task['status'] in ('running', 'paused')]

    if not interrupted_tasks:
        return

    log_info(f"发现 {len(interrupted_tasks)} 个未完成任务，准备恢复...")

    # 恢复任务前检查网络状态
    log_info("检查网络状态...")
    network_ready = _check_network_ready(max_wait=10)
    if not network_ready:
        log_warning("网络未就绪，尝试等待网络恢复...")
        network_ready = _check_network_ready(max_wait=30)
        if not network_ready:
            log_warning("网络长时间未就绪，仍然尝试恢复任务（下载会自动重试）")
    if network_ready:
        log_info("网络已就绪，开始恢复任务...")
    else:
        log_info("开始恢复任务（网络不稳定，下载会自动重试）")

    for task in interrupted_tasks:
        _resume_single_task(task)
        time.sleep(1)


def _resume_single_task(task):
    """恢复单个任务：文件命中检查 + 启动下载线程（resume_tasks 与网页端"继续"共用）"""
    task_id = task['id']
    url = task['url']
    save_name = task.get('save_name')
    referer = task.get('_referer')
    cookie = task.get('_cookie')
    user_agent = task.get('_user_agent')
    retry_count = task.get('_retry_count', 0)

    # 设置 per-user 下载目录上下文（恢复期文件检查在主线程执行）
    _ddir = task.get('_download_dir')
    if not _ddir:
        _u = task.get('user')
        if _u:
            _ddir = os.path.join(cfg.DOWNLOAD_DIR, _u)
    if _ddir:
        _set_thread_download_dir(_ddir)

    normalized_url = url.strip().rstrip('/')

    debug_print(f"恢复任务检查: task_id={task_id}, save_name={save_name}, url={sanitize_url_for_log(normalized_url)[:100]}...")

    url_hit, url_status = is_url_downloaded(url)
    if url_hit:
        display_name = save_name or task_id
        if url_status == 'success':
            log_info(f"文件{display_name}下载成功")
        else:
            log_info(f"文件{display_name}下载失败")
        _finish_task(task_id, True)
        return

    base_name = save_name or f"download_{task_id}"
    # 应用文件名过滤
    original_name = base_name
    base_name, _ = filter_filename(base_name)
    if base_name != original_name:
        # 更新任务中的 save_name 为过滤后的名称
        with cfg.tasks_lock:
            if task_id in cfg.tasks:
                cfg.tasks[task_id]['save_name'] = base_name

    has_existing, existing_path = has_existing_video(base_name)
    if has_existing:
        log_info(f"已存在同名视频文件，跳过恢复: {existing_path}")
        cleanup_copy_files(base_name)
        _finish_task(task_id, True)
        return

    # 检查是否存在未转换的源文件（下载完成但尚未转换）
    source_file = find_existing_source_file(base_name)
    if source_file and os.path.getsize(source_file) >= cfg.MIN_FILE_SIZE:
        log_info(f"已存在未转换的源文件，尝试转换: {source_file}")
        output_file = os.path.join(get_download_dir(), f"{base_name}.{cfg.output_format}")
        ok, _ = _finalize_download_outputs(base_name, output_file, cfg.output_format)
        _finish_task(task_id, ok)
        return

    has_any, any_path = has_any_existing_file(base_name)
    if has_any:
        log_info(f"已存在相关文件，跳过恢复并清理: {any_path}")
        cleanup_copy_files(base_name)
        _finish_task(task_id, True)
        return

    if os.path.exists(cfg.TEMP_DIR):
        temp_files = [f for f in os.listdir(cfg.TEMP_DIR) if match_base_name(f, base_name)]
        for temp_file in temp_files:
            temp_path = os.path.join(cfg.TEMP_DIR, temp_file)
            try:
                if temp_file.endswith('.tmp'):
                    os.remove(temp_path)
            except Exception as e:
                log_error(f"清理临时文件失败: {e}")

    is_direct_video, video_ext = is_direct_video_url(url)

    if is_direct_video:
        output_file = os.path.join(get_download_dir(), f"{base_name}{video_ext}")
    else:
        output_file = os.path.join(get_download_dir(), f"{base_name}.{cfg.output_format}")

    if os.path.exists(output_file):
        if is_direct_video:
            file_size = os.path.getsize(output_file)
            if file_size >= cfg.MIN_FILE_SIZE:
                log_info(f"文件已存在且完整，跳过恢复: {output_file}")
                _finish_task(task_id, True)
                return
            else:
                log_info(f"文件已存在但过小，继续断点续传: {output_file}")
        else:
            log_info(f"文件已存在，跳过恢复: {output_file}")
            _finish_task(task_id, True)
            return

    log_info(f"恢复下载: {save_name or task_id} (ID: {task_id})")
    debug_print(f"启动恢复任务线程: {task_id} (重试次数: {retry_count})")

    # 状态置回 running（暂停恢复时由 'paused' 改回）
    with cfg.tasks_lock:
        if task_id in cfg.tasks:
            cfg.tasks[task_id]['status'] = 'running'
    save_tasks()

    if is_direct_video:
        thread = threading.Thread(
            target=_run_direct_download_worker,
            args=(task_id, url, output_file, referer, cookie, user_agent, retry_count),
            daemon=True
        )
        thread.start()
    else:
        cmd = _build_m3u8_cmd(url, base_name, referer, cookie, user_agent)

        thread = threading.Thread(
            target=_run_worker,
            args=(task_id, cmd, base_name, output_file, cfg.output_format, retry_count),
            daemon=True
        )
        thread.start()


# ---- 网页端任务控制（暂停 / 继续 / 删除）----

def pause_task(task_id):
    """暂停任务：SIGINT 终止下载进程（N_m3u8DL-RE 保存进度 / curl 保留断点），
    任务状态置为 paused，worker 线程检测到后自行退出"""
    with cfg.tasks_lock:
        task = cfg.tasks.get(task_id)
        if not task:
            return False, '任务不存在或已结束'
        status = task['status']
        if status == 'paused':
            return False, '任务已是暂停状态'
        task['status'] = 'paused'
        proc = task.get('_proc')

    _terminate_proc(proc, graceful=True)
    save_tasks(force=True)
    log_info(f"任务已暂停: {task.get('save_name') or task_id} (ID: {task_id})")
    return True, '任务已暂停'


def resume_paused_task(task_id):
    """继续暂停的任务：走与重启恢复相同的检查流程后重新启动下载"""
    with cfg.tasks_lock:
        task = cfg.tasks.get(task_id)
        if not task:
            return False, '任务不存在或已结束'
        if task['status'] != 'paused':
            return False, '任务不在暂停状态'

    # 复制一份快照，避免与 worker 线程共享可变引用
    task_snapshot = dict(task)
    _resume_single_task(task_snapshot)
    return True, '任务已继续下载'


def delete_task(task_id):
    """删除任务：杀进程、移除任务与视频组、删除已下载文件（含临时文件）"""
    with cfg.tasks_lock:
        task = cfg.tasks.pop(task_id, None)
        if not task:
            return False, '任务不存在或已结束'
        proc = task.get('_proc')

    # 强杀下载进程（删除无需保留进度）
    _terminate_proc(proc, graceful=False)

    save_name = task.get('save_name') or ''
    base_name = save_name or f"download_{task_id}"

    # 移除同视频模式的视频组（调度器检测到组消失会自行退出）
    with cfg.video_groups_lock:
        cfg.video_groups.pop(base_name, None)

    save_tasks(force=True)

    # 删除已下载文件：下载目录（per-user）+ DOWNLOAD_DIR 根（旧恢复任务无 user 记录时的回退位置）+ 临时目录
    user_dir = os.path.join(cfg.DOWNLOAD_DIR, task.get('user') or 'default')
    removed = 0
    for target_dir in [user_dir, cfg.DOWNLOAD_DIR, cfg.TEMP_DIR]:
        if not os.path.exists(target_dir):
            continue
        for item in os.listdir(target_dir):
            if not match_base_name(item, base_name):
                continue
            item_path = os.path.join(target_dir, item)
            # 安全防护：DOWNLOAD_DIR 根目录下的子目录是用户隔离目录，不得整目录删除
            if os.path.abspath(target_dir) == os.path.abspath(cfg.DOWNLOAD_DIR) and os.path.isdir(item_path):
                continue
            try:
                if os.path.isdir(item_path):
                    shutil.rmtree(item_path)
                else:
                    os.remove(item_path)
                removed += 1
            except Exception as e:
                log_error(f"删除任务文件失败: {item_path} - {e}")

    log_info(f"任务已删除: {base_name} (ID: {task_id})，清理文件 {removed} 个")
    return True, f'任务已删除（清理文件 {removed} 个）'


def run_download(url, save_name=None, referer=None, cookie=None, user_agent=None, user=None, output_format=None):
    normalized_url = url.strip().rstrip('/')
    # 解析本次任务的输出格式：网页可逐任务指定，不传时回退到 config.json 全局设置
    fmt = output_format if output_format in ('mp4', 'mkv') else cfg.output_format
    # per-user 下载目录：/home/downloader/downloads/<用户名>
    if not user:
        user = 'default'
    download_dir = os.path.join(cfg.DOWNLOAD_DIR, user)
    try:
        os.makedirs(download_dir, exist_ok=True)
    except Exception as e:
        debug_print(f"创建用户下载目录失败: {e}")
    _set_thread_download_dir(download_dir)
    debug_print(f"run_download: URL={sanitize_url_for_log(normalized_url)[:100]}..., save_name={save_name}, user={user}")

    # ---- same_video_by_filename 模式分支 ----
    if cfg.same_video_by_filename_enabled:
        # 计算 base_name（标准过滤后的文件名）作为"同一视频"的唯一键
        task_id_tmp = str(uuid.uuid4())[:8]
        base_name_raw = save_name or f"download_{task_id_tmp}"
        base_name, ad_count = filter_filename(base_name_raw)

        # 1) 检查日志：文件名是否已成功/失败记录过
        name_hit, name_status = is_filename_downloaded(base_name)
        if name_hit:
            debug_print(f"[同视频模式] 文件名已下载记录过，跳过下载: {base_name}, status={name_status}")
            if name_status == 'success':
                log_info(f"文件{base_name}下载成功")
            else:
                log_info(f"文件{base_name}下载失败")
            return None, False

        # 2) 检查本地文件是否已存在（调用共享检查）
        skip, hit_path = _check_local_file_exists_skip(base_name)
        if skip:
            suffix = "同名视频文件" if hit_path and is_video_file(os.path.basename(hit_path)) else "相关文件"
            debug_print(f"[同视频模式] {suffix}已存在，跳过下载: {hit_path}")
            log_info(f"{suffix}已存在，跳过下载: {hit_path}")
            return None, False

        # 3) 加入 / 创建视频组
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
                    debug_print(f"[同视频模式] 视频组 {base_name} 追加新链接 (总计 {len(existing_group['urls'])} 个)")
                    # 同步更新关联任务的 urls 列表，供日志记录使用
                    with cfg.tasks_lock:
                        gt = cfg.tasks.get(existing_group['task_id'])
                        if gt is not None and normalized_url not in gt['urls']:
                            gt['urls'].append(normalized_url)
                else:
                    debug_print(f"[同视频模式] 视频组 {base_name} 链接已存在，忽略")

                if status in ('collecting', 'running'):
                    debug_print(f"[同视频模式] 复用视频组任务 {existing_group['task_id']} -> {base_name}")
                    return existing_group['task_id'], True
                elif status == 'done':
                    # 已经完成过，但日志没命中（可能是刚完成没写日志？），保守跳过
                    debug_print(f"[同视频模式] 视频组 {base_name} 已完成，跳过")
                    return None, False

            # 创建新视频组
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
            debug_print(f"[同视频模式] 新建视频组 {base_name}, task_id={task_id}, 链接数=1")

        # 创建对应的 tasks 记录（用于进度查询），然后启动调度器
        with cfg.tasks_lock:
            cfg.tasks[task_id] = {
                'id': task_id,
                'url': normalized_url,
                'urls': [normalized_url],
                'save_name': base_name,
                'status': 'running',
                'progress': 0,
                'user': user,
                '_download_dir': download_dir,
                '_referer': referer,
                '_cookie': cookie,
                '_user_agent': user_agent,
                '_retry_count': 0
            }
        save_tasks()

        debug_print(f"[同视频模式] 启动多链接调度任务: {base_name} (ID: {task_id})")
        log_info(f"开始下载任务: {base_name} (ID: {task_id})" + (f" 过滤广告 {ad_count} 个" if ad_count > 0 else ""))
        # 稍微延迟启动，给短时间内批量提交的同文件名链接留一个收集窗口
        def delayed_start():
            time.sleep(1)
            _run_same_video_group_worker(task_id, base_name, fmt)

        threading.Thread(target=delayed_start, daemon=True).start()
        return task_id, False

    # ---- 原有逻辑 (same_video_by_filename 关闭时) ----
    url_hit, url_status = is_url_downloaded(url)
    if url_hit:
        debug_print(f"URL已在日志中，跳过下载, status={url_status}")
        display_name = save_name or normalized_url
        if url_status == 'success':
            log_info(f"文件{display_name}下载成功")
        else:
            log_info(f"文件{display_name}下载失败")
        return None, False

    with cfg.tasks_lock:
        for task_id, task in cfg.tasks.items():
            task_url = task['url'].strip().rstrip('/')
            if task_url == normalized_url:
                if task['status'] == 'running':
                    debug_print(f"检测到重复链接，复用任务: {task_id}")
                    log_info(f"检测到重复链接，复用任务: {task_id}")
                    return task_id, True
                else:
                    debug_print(f"该URL任务已存在（{task['status']}），跳过下载")
                    log_info(f"该URL任务已存在（{task['status']}），跳过下载")
                    return None, False
        debug_print(f"任务列表中无匹配URL，准备创建新任务")

    is_direct_video, video_ext = is_direct_video_url(url)

    task_id = str(uuid.uuid4())[:8]
    base_name = save_name or f"download_{task_id}"

    # 应用文件名过滤
    base_name, ad_count = filter_filename(base_name)

    skip, hit_path = _check_local_file_exists_skip(base_name)
    if skip:
        if hit_path and is_video_file(os.path.basename(hit_path)):
            debug_print(f"已存在同名视频文件: {hit_path}")
            log_info(f"已存在同名视频文件，跳过下载: {hit_path}")
        else:
            debug_print(f"已存在相关文件（可能是.copy文件）: {hit_path}")
            log_info(f"已存在相关文件（可能是.copy文件），跳过下载: {hit_path}")
        return None, False

    if is_direct_video:
        output_file = os.path.join(get_download_dir(), f"{base_name}{video_ext}")
    else:
        output_file = os.path.join(get_download_dir(), f"{base_name}.{fmt}")

    if os.path.exists(output_file):
        if is_direct_video:
            file_size = os.path.getsize(output_file)
            if file_size < cfg.MIN_FILE_SIZE:
                log_info(f"文件已存在但过小 ({file_size} bytes)，继续断点续传: {output_file}")
            else:
                log_info(f"文件已存在，跳过下载: {output_file}")
                return None, False
        else:
            log_info(f"文件已存在，跳过下载: {output_file}")
            return None, False
    else:
        alternate_output = find_existing_output_file(base_name)
        if alternate_output:
            log_info(f"已检测到现有输出文件，跳过下载: {alternate_output}")
            return None, False

    with cfg.tasks_lock:
        cfg.tasks[task_id] = {
            'id': task_id,
            'url': url,
            'urls': [url],
            'save_name': base_name,
            'status': 'running',
            'progress': 0,
            'user': user,
            '_download_dir': download_dir,
            '_referer': referer,
            '_cookie': cookie,
            '_user_agent': user_agent,
            '_retry_count': 0
        }
        debug_print(f"任务已创建: {task_id}, base_name={base_name}, output={output_file}")

    save_tasks()

    log_info(f"开始下载任务: {base_name} (ID: {task_id})" + (f" 过滤广告 {ad_count} 个" if ad_count > 0 else ""))
    debug_print(f"任务启动: {task_id}, is_direct_video={is_direct_video}, output_file={output_file}")

    if is_direct_video:
        log_info(f"检测到直接视频链接，使用 curl 直接下载: {video_ext}")
        thread = threading.Thread(
            target=_run_direct_download_worker,
            args=(task_id, url, output_file, referer, cookie, user_agent),
            daemon=True
        )
        thread.start()
    else:
        cmd = _build_m3u8_cmd(url, base_name, referer, cookie, user_agent)

        if cfg.keywords_enabled and cfg.ad_keywords:
            log_info(f"已添加 {len(cfg.ad_keywords)} 个广告关键字过滤")

        thread = threading.Thread(target=_run_worker, args=(task_id, cmd, base_name, output_file, fmt), daemon=True)
        thread.start()

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
    _set_thread_download_dir(None)
