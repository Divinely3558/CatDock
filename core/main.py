#!/usr/bin/env python3
"""catdock 下载服务入口

启动编排：加载配置 → 初始化数据库 → 校验用户 → 清理残留 →
清空失败日志 → 注册信号 → 打印 banner → 启动 HTTP 服务。

业务模块：
  app_config   全局配置与状态
  app_logger   日志
  data_db      data.db（封禁 IP + 用户）
  task_store   任务持久化 / 下载日志
  dedup        去重缓存
  filters      广告/文件名过滤
  security     SSRF / 脱敏 / 限流
  downloader   下载核心
  api_server   HTTP 服务
"""
import os

import app_config as cfg
import data_db
from downloader import cleanup_all_copy_files
from api_server import start_server, register_signal_handlers


def main():
    cfg.load_config()
    # 初始化数据库（建表：封禁 IP / 认证失败计数 / 用户）
    data_db.init_db()
    # 无用户时不退出：服务先启动，便于通过 `docker exec ... userctl add <用户名>` 初始化；
    # 但在创建首个用户前，api_server 会拒绝所有业务请求（/health 除外）。
    _user_count = data_db.user_count()
    cleanup_all_copy_files()

    # 启动时清空失败日志，允许重新下载之前失败的 URL
    if os.path.exists(cfg.FAILURE_LOG_FILE):
        try:
            os.remove(cfg.FAILURE_LOG_FILE)
            print("已清空失败日志，允许重新下载之前失败的 URL")
        except Exception as e:
            print(f"清空失败日志失败: {e}")

    register_signal_handlers()

    port = int(os.environ.get('API_PORT', cfg.server_port))

    api_prefix = f"/{cfg.url_prefix}" if cfg.url_prefix else ""
    #╔════════════════════════════════════════════════════════╗
    # ║                       下载器启动成功                   ║##我已经手动对齐，务必不要修改
    #╚════════════════════════════════════════════════════════╝
    banner = f"""
╔════════════════════════════════════════════════════════╗
║                       下载器启动成功                   ║
╚════════════════════════════════════════════════════════╝

  📡 API 端口: {port}
  📤 输出格式: {cfg.output_format}
  🔗 URL前缀: {cfg.url_prefix}
  🛡️ SSRF防护: {'启用' if cfg.ssrf_protection else '关闭'}
  📊 最大并发: {cfg.max_concurrent_tasks}
  🎬 同视频模式: {'启用' if cfg.same_video_by_filename_enabled else '禁用'}
  📋 过滤规则: 拦截关键字{'✓' if cfg.keywords_enabled else '✗'}({len(cfg.ad_keywords)}) 文件名过滤{'✓' if cfg.filename_filter_enabled else '✗'} 去重{'✓' if cfg.filename_dedup_enabled else '✗'}
  👥 {f"下载用户: {_user_count}" if _user_count > 0 else "未创建任何用户，请在容器内执行 userctl add <用户名>"}
════════════════════════ 猫抓插件配置 ════════════════════════

    发送地址: http://你的容器IP:{port}{api_prefix}/download
    网页控制台: http://你的容器IP:{port}{api_prefix}/

    请求体:
    {{
      "url": "${{url}}",
      "saveName": "${{title}}",
      "referer": "${{referer}}",
      "cookie": "${{cookie}}",
      "userAgent": "${{userAgent}}",
      "key": "<你的AUTH_KEY>",
      "user": "<你的user>",
      "password": "<你的password>"
    }}

══════════════════════════ API 接口 ══════════════════════════

    POST {api_prefix}/download    添加下载任务
    POST {api_prefix}/reload      重载配置

╚══════════════════════════════════════════════════════════╝
"""
    print(banner)

    start_server(port)


if __name__ == '__main__':
    main()
