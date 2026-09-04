FROM debian:bookworm-slim

RUN sed -i 's/deb.debian.org/mirrors.tuna.tsinghua.edu.cn/g' /etc/apt/sources.list.d/debian.sources && \
    sed -i 's/security.debian.org/mirrors.tuna.tsinghua.edu.cn/g' /etc/apt/sources.list.d/debian.sources && \
    apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    python3 \
    curl \
    iputils-ping \
    tzdata \
    && rm -rf /var/lib/apt/lists/* && \
    ln -sf /usr/share/zoneinfo/Asia/Shanghai /etc/localtime && \
    echo "Asia/Shanghai" > /etc/timezone

RUN useradd -m -s /bin/bash downloader && \
    mkdir -p /home/downloader/downloads /home/downloader/temp /home/downloader/config && \
    chown -R downloader:downloader /home/downloader

WORKDIR /home/downloader

# 容器内保持平铺布局：core/ 模块与 web/cli/config 资源统一平铺到 /home/downloader/
COPY core/main.py core/api_server.py core/downloader.py core/app_config.py core/app_logger.py core/task_store.py core/dedup.py core/filters.py core/security.py core/data_db.py core/webui.py /home/downloader/
COPY web/webui.html web/favicon.ico cli/banip cli/userctl config/config.example.json config/filter_rules.json bin/N_m3u8DL-RE /home/downloader/
RUN chmod +x /home/downloader/N_m3u8DL-RE /home/downloader/main.py /home/downloader/banip /home/downloader/userctl && \
    ln -sf /home/downloader/banip /usr/local/bin/banip && \
    ln -sf /home/downloader/userctl /usr/local/bin/userctl

COPY sh/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

USER downloader

EXPOSE 8080

CMD ["/entrypoint.sh"]