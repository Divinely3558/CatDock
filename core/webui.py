#!/usr/bin/env python3
"""webui - 内置网页页面加载

包含三个零依赖单文件页面（规范地址；旧入口由 api_server 302 跳转）：
  - login.html：登录页，GET /{prefix}/login.html 返回
  - user.html：下载控制台（普通用户），GET /{prefix}/user.html 返回
  - admin.html：管理控制台（管理员），GET /{prefix}/admin.html 返回
首次访问时读取并缓存。页面中的 __SHARED_CSS__ / __SHARED_JS__ 占位符
会替换为 web/shared.css、web/shared.js 的共享内容，浏览器收到的仍是完整单文件页面。
"""
import os

import app_config as cfg

_LOGIN_HTML_CACHE = None
_USER_HTML_CACHE = None
_ADMIN_HTML_CACHE = None


def _version_display():
    """版本号展示文案：空则显示「未知」。"""
    return cfg.version if cfg.version else "未知"


def _find_web_file(filename):
    """定位 web 资源文件。

    查找顺序：同目录（容器内平铺布局）→ ../web/（仓库源码布局）
    """
    base = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(base, filename)
    if not os.path.isfile(path):
        path = os.path.join(base, '..', 'web', filename)
    return path


def _read_html(filename):
    """读取 HTML 文件（带缓存），并注入共享样式/脚本与 __VERSION__ 占位符。"""
    with open(_find_web_file(filename), 'r', encoding='utf-8') as f:
        html = f.read()
    with open(_find_web_file('shared.css'), 'r', encoding='utf-8') as f:
        shared_css = f.read()
    with open(_find_web_file('shared.js'), 'r', encoding='utf-8') as f:
        shared_js = f.read()
    html = html.replace('/*__SHARED_CSS__*/', shared_css)
    html = html.replace('/*__SHARED_JS__*/', shared_js)
    return html.replace('__VERSION__', _version_display())


def get_login_html():
    """读取 login.html 登录页内容（带缓存）"""
    global _LOGIN_HTML_CACHE
    if _LOGIN_HTML_CACHE is None:
        _LOGIN_HTML_CACHE = _read_html('login.html')
    return _LOGIN_HTML_CACHE


def get_user_html():
    """读取 user.html 下载控制台内容（带缓存）"""
    global _USER_HTML_CACHE
    if _USER_HTML_CACHE is None:
        _USER_HTML_CACHE = _read_html('user.html')
    return _USER_HTML_CACHE


def get_admin_html():
    """读取 admin.html 管理控制台内容（带缓存）"""
    global _ADMIN_HTML_CACHE
    if _ADMIN_HTML_CACHE is None:
        _ADMIN_HTML_CACHE = _read_html('admin.html')
    return _ADMIN_HTML_CACHE
