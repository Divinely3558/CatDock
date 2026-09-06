#!/usr/bin/env python3
"""webui - 内置网页页面加载

包含三个零依赖单文件页面：
  - login.html：登录页，GET /{prefix}/ 返回
  - user.html：下载控制台（普通用户），GET /{prefix}/user 返回
  - admin.html：管理控制台（管理员），GET /{prefix}/admin/ 返回
首次访问时读取并缓存。
"""
import os

_LOGIN_HTML_CACHE = None
_USER_HTML_CACHE = None
_ADMIN_HTML_CACHE = None


def _read_html(filename):
    """读取 HTML 文件（带缓存）

    查找顺序：同目录（容器内平铺布局）→ ../web/（仓库源码布局）
    """
    base = os.path.dirname(os.path.abspath(__file__))
    html_path = os.path.join(base, filename)
    if not os.path.isfile(html_path):
        html_path = os.path.join(base, '..', 'web', filename)
    with open(html_path, 'r', encoding='utf-8') as f:
        return f.read()


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
