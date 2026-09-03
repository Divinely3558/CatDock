#!/usr/bin/env python3
"""webui - 内置网页控制台页面加载

页面为单文件 webui.html（纯 HTML/CSS/JS，无外部依赖），
由 api_server 在 GET /{prefix}/ 时返回。首次访问时读取并缓存。
"""
import os

_HTML_CACHE = None


def get_index_html():
    """读取 webui.html 内容（带缓存）

    查找顺序：同目录（容器内平铺布局）→ ../web/（仓库源码布局）
    """
    global _HTML_CACHE
    if _HTML_CACHE is None:
        base = os.path.dirname(os.path.abspath(__file__))
        html_path = os.path.join(base, 'webui.html')
        if not os.path.isfile(html_path):
            html_path = os.path.join(base, '..', 'web', 'webui.html')
        with open(html_path, 'r', encoding='utf-8') as f:
            _HTML_CACHE = f.read()
    return _HTML_CACHE
