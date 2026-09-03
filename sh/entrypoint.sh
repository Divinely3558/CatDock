#!/bin/bash

set -e

echo "======================================"
echo "  catdock 启动中..."
echo "======================================"

# 确保目录存在
mkdir -p /home/downloader/config

# 默认配置文件路径（镜像内置模板，含占位密码；运行时配置由挂载卷覆盖）
DEFAULT_CONFIG="/home/downloader/config.example.json"
TARGET_CONFIG="/home/downloader/config/config.json"
DEFAULT_FILTER_RULES="/home/downloader/filter_rules.json"
TARGET_FILTER_RULES="/home/downloader/config/filter_rules.json"

# 如果目标配置文件不存在，复制默认配置
if [ ! -f "$TARGET_CONFIG" ]; then
    if [ -f "$DEFAULT_CONFIG" ]; then
        cp "$DEFAULT_CONFIG" "$TARGET_CONFIG"
        echo "已复制默认配置到: $TARGET_CONFIG"
    else
        echo "警告: 默认配置文件不存在"
    fi
else
    echo "使用已存在的配置文件: $TARGET_CONFIG"
fi

# 如果目标过滤规则文件不存在，复制默认配置
if [ ! -f "$TARGET_FILTER_RULES" ]; then
    if [ -f "$DEFAULT_FILTER_RULES" ]; then
        cp "$DEFAULT_FILTER_RULES" "$TARGET_FILTER_RULES"
        echo "已复制默认过滤规则到: $TARGET_FILTER_RULES"
    else
        echo "警告: 默认过滤规则文件不存在"
    fi
else
    echo "使用已存在的过滤规则文件: $TARGET_FILTER_RULES"
fi

# 等待宿主机硬件启动和网络就绪
echo "等待宿主机硬件初始化..."
MAX_WAIT=600
WAITED=0
NETWORK_STABLE_COUNT=0
REQUIRED_STABLE=2  # 需要连续2次检查通过才认为网络稳定

while [ $WAITED -lt $MAX_WAIT ]; do
    # 检查网络是否就绪（任一检查通过即可）
    if ping -c 1 -W 2 223.5.5.5 > /dev/null 2>&1 || \
       ping -c 1 -W 2 114.114.114.114 > /dev/null 2>&1 || \
       ping -c 1 -W 2 www.baidu.com > /dev/null 2>&1 || \
       curl -s --connect-timeout 3 --max-time 5 http://www.baidu.com > /dev/null 2>&1; then
        
        NETWORK_STABLE_COUNT=$((NETWORK_STABLE_COUNT + 1))
        echo "网络检查通过 (${NETWORK_STABLE_COUNT}/${REQUIRED_STABLE})"
        
        if [ $NETWORK_STABLE_COUNT -ge $REQUIRED_STABLE ]; then
            echo "网络已稳定 (等待了 ${WAITED} 秒，连续 ${REQUIRED_STABLE} 次检查通过)"
            break
        fi
    else
        NETWORK_STABLE_COUNT=0
    fi
    
    sleep 5
    WAITED=$((WAITED + 5))
    
    # 每30秒输出一次等待状态
    if [ $((WAITED % 30)) -eq 0 ]; then
        echo "仍在等待网络就绪... (${WAITED}/${MAX_WAIT} 秒)"
    fi
done

if [ $WAITED -ge $MAX_WAIT ]; then
    echo "警告: 网络等待超时，但仍尝试启动服务"
fi

# DNS 缓存预热
echo "正在预热 DNS 缓存..."
curl -s --connect-timeout 5 --max-time 10 -o /dev/null -w "网络延迟: %{time_total}s\n" \
    http://www.baidu.com 2>&1 || echo "DNS预热跳过"

# 额外等待几秒确保系统稳定
sleep 3

# 启动服务
PYTHONUNBUFFERED=1 python3 -u /home/downloader/main.py