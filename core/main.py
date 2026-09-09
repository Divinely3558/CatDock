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
    # 首启初始化 AUTH_KEY：admin_config.json 为空/占位符时生成随机密钥并写回，
    # 之后可在管理网页热更新（无需重启容器）
    _initial_auth_key = None
    if not cfg.auth_key or cfg.auth_key == cfg.AUTH_KEY_PLACEHOLDER:
        _initial_auth_key = cfg.generate_random_key()
        cfg.save_auth_key(_initial_auth_key)
    # 初始化数据库（建表：封禁 IP / 认证失败计数 / 用户+角色 / 令牌）
    data_db.init_db()
    # 首启初始化管理员：无 role='admin' 时创建默认 admin（14 位随机密码）
    _admin_created, _admin_pw = data_db.ensure_default_admin()
    _user_count = data_db.user_count()
    cleanup_all_copy_files()

    # 启动时清空各用户的失败日志，允许重新下载之前失败的 URL
    # （日志按用户隔离存放在 user/<名>/failure.log）
    _cleared_failure = 0
    if os.path.isdir(cfg.USER_DIR):
        for _u in os.listdir(cfg.USER_DIR):
            _flog = cfg.user_failure_log(_u)
            if os.path.exists(_flog):
                try:
                    os.remove(_flog)
                    _cleared_failure += 1
                except Exception as e:
                    print(f"清空失败日志失败: {_flog} - {e}")
    if _cleared_failure:
        print("已清空失败日志，允许重新下载之前失败的 URL")

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

  🏷️ 版本: {cfg.version or '未知'}
  📡 API 端口: {port}
  🔗 URL前缀: {cfg.url_prefix}
  🛡️ SSRF防护: {'启用' if cfg.ssrf_protection else '关闭'}
  📊 最大并发: {cfg.max_concurrent_tasks}
  🎬 同视频模式: {'启用' if cfg.same_video_by_filename_enabled else '禁用'}
  📋 过滤规则: 拦截关键字{'✓' if cfg.keywords_enabled else '✗'}({len(cfg.ad_keywords)}) 文件名过滤{'✓' if cfg.filename_filter_enabled else '✗'} 去重{'✓' if cfg.filename_dedup_enabled else '✗'}
  👥 {f"下载用户: {_user_count}" if _user_count > 0 else "未创建任何用户，请在容器内执行 userctl add <用户名>"}
════════════════════════ 猫抓插件配置 ════════════════════════

    发送地址: http://你的容器IP:{port}{api_prefix}/download
    网页控制台: http://你的容器IP:{port}{api_prefix}/login.html

    请求体:
    {{
      "url": "${{url}}",
      "saveName": "${{title}}_${{now}}",
      "referer": "${{referer}}",
      "cookie": "${{cookie}}",
      "userAgent": "${{userAgent}}",
      "key": "<你的AUTH_KEY>",
      "user": "<你的user>",
      "password": "<你的password>",
      "format": "mp4"
    }}

══════════════════════════ API 接口 ══════════════════════════

    POST {api_prefix}/download    添加下载任务
    POST {api_prefix}/reload      重载配置

╚══════════════════════════════════════════════════════════╝
"""
    print(banner)

    # 首启凭据仅在生成时输出一次（banner 外，避免改动框线区块）
    if _initial_auth_key:
        print(f"首次启动：已自动生成 AUTH_KEY 并写入 admin_config.json: {_initial_auth_key}")
        print("请妥善保存；可在管理网页修改 AUTH_KEY（修改后全员需用新 KEY 重新登录）")
    if _admin_created:
        print(f"首次启动：已创建默认管理员账户 admin，初始密码: {_admin_pw}")
        print("请尽快登录管理网页或使用 adminctl password 命令修改密码")
    elif data_db.admin_count() == 0:
        print("警告: 用户名 admin 已被普通用户占用，未自动创建管理员")
        print("请在容器内执行 adminctl add <用户名> 创建管理员账户")

    start_server(port)


if __name__ == '__main__':
    main()
