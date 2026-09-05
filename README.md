# 🎬 catdock

基于 N_m3u8DL-RE 的 Docker 容器下载工具，支持通过猫抓浏览器插件远程控制容器下载视频。

## ✨ 功能特性

- **🐳 Docker 容器部署**：轻量级 Debian 基础镜像，非 root 用户运行
- **🔌 猫抓插件支持**：通过数据发送功能远程控制容器下载
- **📡 HTTP API**：提供下载触发接口，支持任务查询与配置热重载
- **🎬 完整下载参数**：支持 referer、cookie、user-agent 等关键参数
- **💾 数据持久化**：下载文件、临时文件与配置文件均持久化到宿主机
- **🔒 URL 路径前缀**：支持设置访问前缀（如 `/admin`），增强接口安全性
- **🔑 请求体认证**：支持 `key` 参数认证，防止未授权访问
- **🔐 敏感配置隔离**：`AUTH_KEY` 与 `URL_PREFIX` 仅通过 Docker 环境变量注入，不写入配置文件，且**必须设置**，否则程序拒绝启动
- **📋 任务持久化**：任务列表自动保存到 `tasks.json`，重启后自动恢复
- **🎥 输出格式配置**：支持 MP4/MKV 格式切换
- **📹 直接视频下载**：支持 mp4、mkv、ts、flv、avi、webm、mov、wmv 等格式的直链下载
- **🔄 断点续传**：支持 HTTP 断点续传，网络中断后自动恢复
- **🛡️ 重复下载防护**：检测 URL 是否已下载过，避免重复下载
- **🔍 过滤规则**：支持广告拦截（`keywords`）和文件名清理（`filename_filter`）两种过滤机制
- **🎬 同视频模式**：按文件名判定同一视频，多链接轮流切换下载（每轮 5 次后放弃）
- **🐞 调试模式**：支持开启调试日志，便于问题排查
- **⏱️ 请求超时处理**：30 秒请求超时保护，防止连接阻塞
- **🚪 优雅关闭**：支持 SIGTERM/SIGINT 信号，安全停止服务
- **🌏 东八区时间**：日志时间戳统一使用北京时间（UTC+8）
- **🌐 网络就绪检测**：容器启动前自动检测网络状态，确保下载环境就绪
- **🔁 失败重置**：启动时自动清空 `failure.log`，允许重新下载之前失败的 URL
- **🧠 自动恢复**：容器重启后自动恢复未完成下载任务，保留进度
- **🛡️ SSRF 防护**：拦截指向内网/回环/云元数据地址的下载请求，可开关
- **🚦 速率限制**：每 IP 60 秒内最多 60 次请求，防止暴力破解与 DoS
- **📊 并发任务限制**：默认最多 20 个并发下载任务，防止资源耗尽
- **🔒 接口认证全覆盖**：所有 API 接口（含 GET）均需认证，未带前缀的请求返回 404
- **🔑 恒定时间密钥比较**：使用 `hmac.compare_digest` 防止时序攻击
- **🙈 日志 URL 脱敏**：自动隐藏 URL 中的 token/sign/key 等敏感查询参数
- **🙈 敏感字段隐藏**：`/tasks` 响应不返回 `_cookie`、`_referer`、`_user_agent`
- **🎨 网页主题切换**：三套主题色（墨绿默认 / 暖橙 / 紫罗兰）× 亮暗双模式，跟随系统外观，设置保存在浏览器本地
- **📱 移动端适配**：网页控制台响应式布局，手机端顶栏精简、触控目标加大、底部弹出详情

## 📁 项目结构

```text
catdock/
├── core/                # 🐍 核心 Python 模块（容器内平铺到 /home/downloader/）
│   ├── main.py          # 🚀 服务入口（启动编排 + banner）
│   ├── api_server.py    # 📡 HTTP API 服务（路由/认证/限流/网页托管）
│   ├── webui.py         # 🖥️ 网页控制台页面加载
│   ├── downloader.py    # 📥 下载核心（命令构建/重试/worker/文件处理）
│   ├── app_config.py    # ⚙️ 全局配置与运行时状态
│   ├── app_logger.py    # 📝 日志输出
│   ├── task_store.py    # 💾 任务持久化与下载日志
│   ├── dedup.py         # 🔁 下载去重缓存
│   ├── filters.py       # 🔍 广告拦截 + 文件名过滤/去重
│   ├── security.py      # 🛡️ SSRF 防护 / URL 脱敏 / 限流
│   └── data_db.py       # 🗄️ data.db（封禁 IP + 用户）
├── cli/                 # 🔧 命令行工具
│   ├── banip            # 🔧 IP 封禁管理 CLI
│   └── userctl          # 👤 下载用户管理 CLI
├── web/                 # 🖥️ 前端资源
│   ├── webui.html       # 🖥️ 网页控制台单文件页面（HTML/CSS/JS）
│   └── favicon.ico      # 🌐 网页图标
├── sh/                  # 📜 Shell 脚本
│   ├── entrypoint.sh    # 🚀 容器启动脚本
│   └── deploy.sh        # 📦 镜像构建/推送/清理脚本（本地使用）
├── config/              # ⚙️ 配置模板
│   ├── config.example.json  # ⚙️ 配置模板（真实 config.json 运行时挂载）
│   └── filter_rules.json    # 🔍 过滤规则配置（广告拦截 + 文件名过滤）
├── bin/                 # 📥 第三方二进制
│   └── N_m3u8DL-RE      # 📥 核心下载工具(Linux版)
├── Dockerfile           # 🐳 Docker 构建文件（根目录，便于 docker build .）
├── docker-compose.yml   # 📋 Docker Compose 配置
└── README.md            # 📖 本文档
```

## 🚀 快速开始

### 1. 准备宿主机目录

```bash
mkdir -p /youdir/{downloads,config}
```

将 `/youdir` 替换为你希望存放下载文件的实际路径。

### 2. 修改 docker-compose.yml

```yaml
services:
  catdock:
    container_name: catdock
    build: .
    volumes:
      - /youdir:/home/downloader/temp
      - /youdir/downloads:/home/downloader/downloads
      - /youdir/config:/home/downloader/config
    ports:
      - 5000:8080
    image: ghcr.nju.edu.cn/divinely3558/catdock
    restart: always
    dns:
      - 223.5.5.5
      - 223.6.6.6
      - 114.114.114.114
      - 119.29.29.29
    environment:
      - AUTH_KEY=your_secure_password_here # 🔑 必须设置：认证密钥（建议 14 位以上随机字符串）
      - URL_PREFIX=admin # 🔒 必须设置：URL 路径前缀（建议 8 位随机字符串）
      - SSRF_PROTECTION=true # 🛡️ SSRF防护: true=拦截内网地址, false=允许内网下载
      - MAX_CONCURRENT_TASKS=20 # 📊 最大并发下载任务数
```

### 3. 构建并启动容器

```bash
docker-compose up -d --build
```

### 4. 查看启动信息

```bash
docker logs -f catdock
```

容器启动后会依次输出：

1. 宿主机硬件初始化等待与网络就绪检测结果
2. 猫抓插件发送地址与请求体模板
3. API 接口列表
4. 当前加载的配置摘要

## 📂 目录挂载说明

容器内部使用以下目录，全部通过 `volumes` 挂载到宿主机：

| 容器路径                     | 宿主机路径          | 用途                     |
| ---------------------------- | ------------------- | ------------------------ |
| `/home/downloader/temp`      | `/youdir`           | 下载过程中的临时分片目录 |
| `/home/downloader/downloads` | `/youdir/downloads` | 最终视频文件输出目录     |
| `/home/downloader/config`    | `/youdir/config`    | 配置、任务与日志文件目录 |

`config` 目录中会生成/保存以下文件：

| 文件                | 说明                                              |
| ------------------- | ------------------------------------------------- |
| `config.json`       | 端口、输出格式、调试开关等非敏感配置              |
| `filter_rules.json` | 过滤规则配置（广告拦截 + 文件名过滤）             |
| `tasks.json`        | 当前正在下载的任务列表（自动生成，无需手动编辑）  |
| `success.log`       | 已成功下载的 URL 记录（用于去重）                 |
| `failure.log`       | 下载失败的 URL 记录（启动时会自动清空以允许重试） |

## 🔌 猫抓插件配置

### 使用方法

猫抓插件通过 **数据发送** 功能直接调用容器的 HTTP API。

### 配置步骤

1. **打开猫抓设置** → **数据发送**

2. **发送地址**（假设 `url_prefix` 设置为 `admin`）：

   ```
   http://你的容器IP:5000/admin/download
   ```

3. **请求体**（JSON 格式，必须包含两层认证 + 用户字段）：

   ```json
   {
     "url": "${url}",
     "saveName": "${title}",
     "referer": "${referer}",
     "cookie": "${cookie}",
     "userAgent": "${userAgent}",
     "key": "<你的AUTH_KEY>",
     "user": "<你的user>",
     "password": "<你的password>"
   }
   ```

   > `saveName` 默认建议只填 `${title}`（纯标题，不加时间戳）。如需在文件名后追加时间戳，可写成 `${title}_${now}`。

4. **保存设置**

### 使用流程

1. 在浏览器中打开视频网页
2. 猫抓插件捕获到 m3u8 链接或直接视频链接
3. 点击资源列表中的 **发送** 按钮
4. 下载任务自动发送到容器执行
5. 文件保存在宿主机的 `/youdir/downloads` 目录

### 注意事项

- 发送地址必须包含 `url_prefix`，如 `http://你的容器IP:5000/admin/download`
- `key` 字段必须与 `AUTH_KEY` 环境变量一致，`password` 字段必须与 `config.json` 中的 `password` 一致，`user` 字段必须为容器内已创建的用户，三者均正确才能通过认证，否则返回 403
- 支持直接视频链接（mp4、mkv、ts、flv 等），自动使用 curl 下载

### 猫抓内置变量对照

请求体中以 `${xxx}` 形式出现的占位符由猫抓插件在发送时自动替换为实际值，服务端无需也无法解析这些变量：

| 变量         | 含义                           | 用途                           |
| ------------ | ------------------------------ | ------------------------------ |
| `${url}`     | 当前资源的下载链接（m3u8/直链）| 填入 `url` 字段，**必填**       |
| `${title}`   | 资源标题（来自页面/文件名）    | 填入 `saveName`，建议默认值    |
| `${now}`     | 当前时间戳（毫秒）             | 可选拼接到 `saveName` 防重名    |
| `${referer}` | 来源页面地址                   | 填入 `referer`，部分站点必需   |
| `${cookie}`  | 浏览器 Cookie                  | 填入 `cookie`，部分站点必需    |
| `${userAgent}` | 浏览器 User-Agent            | 填入 `userAgent`，按需          |

> - `key`、`user`、`password` 三个认证字段**不是**猫抓变量，需在猫抓「数据发送」配置中手动填写真实值。
> - `${now}` 为毫秒级时间戳，如 `1672329448871`。默认 `saveName` 不含 `${now}`，仅在需要防重名时追加。

## 🖥️ 网页控制台

服务内置了一个零依赖的单文件网页控制台，浏览器直接访问即可管理下载任务：

```
http://你的容器IP:5000/admin/
```

> 访问 `http://你的容器IP:5000/admin`（不带尾斜杠）会自动 302 跳转到 `/admin/`。

- **登录**：输入 `AUTH_KEY`、容器内 `userctl add` 创建的用户名和密码；凭证仅保存在当前浏览器（localStorage），下次访问自动填充，可点「退出」清除
- **新建下载**：粘贴视频 URL、填写保存文件名（选填），支持折叠的高级选项（Referer / Cookie / User-Agent）
- **任务列表**：每 3 秒自动刷新，显示文件名、状态徽章（收集中 / 下载中）、进度条与所属用户；点击任务可弹出详情（任务 ID、全部链接、重试次数等）
- **运维操作**：顶栏实时显示服务健康状态（每 10 秒探测 `/health`），并提供「重载配置」按钮（等价于 `POST /{prefix}/reload`）
- 页面为纯静态外壳（不含任何敏感信息），所有数据操作均携带两层认证调用 API；任务完成（成功或失败）后会自动从列表中移除

## 📡 API 接口

> 注意：**所有接口路径均需要添加 URL 前缀**（如 `/admin`），未带前缀的请求返回 `404 Not Found`。所有接口（含 GET，`/health` 除外）均需**两层认证 + 用户**：POST 通过请求体传 `key`/`user`/`password`，GET 通过查询参数 `?key=<AUTH_KEY>&user=<用户名>&password=<密码>` 传递。

| 接口                     | 方法 | 说明                           | 认证 |
| ------------------------ | ---- | ------------------------------ | ---- |
| `/{prefix}/download`     | POST | 添加下载任务                   | 是   |
| `/{prefix}/tasks`        | GET  | 获取所有任务                   | 是   |
| `/{prefix}/tasks/{id}`   | GET  | 获取任务详情                   | 是   |
| `/{prefix}/task/pause`   | POST | 暂停下载任务（进度保留）       | 是   |
| `/{prefix}/task/resume`  | POST | 继续暂停的任务                 | 是   |
| `/{prefix}/task/delete`  | POST | 删除任务（同时删除已下载文件） | 是   |
| `/{prefix}/reload`       | POST | 重新加载配置                   | 是   |
| `/{prefix}/health`       | GET  | 健康检查                       | 否   |

> 示例：如果 `URL_PREFIX` 设置为 `admin`，则完整路径为 `/admin/download`

### 任务控制接口（pause / resume / delete）

三个接口请求体格式一致：

```json
{
  "taskId": "<任务ID>",
  "key": "<你的AUTH_KEY>",
  "user": "<你的user>",
  "password": "<你的password>"
}
```

- **pause**：优雅终止下载进程（N_m3u8DL-RE 保存进度、curl 保留断点文件），任务进入"已暂停"状态
- **resume**：继续暂停的任务，重新走文件命中检查后启动下载（断点续传）
- **delete**：删除任务并**同时删除已下载文件与临时文件**（不可恢复）；容器重启后暂停任务会自动继续下载

### POST /{prefix}/download

请求体（全部字段如下，未标注必填的可省略）：

```json
{
  "url": "https://example.com/stream.m3u8",
  "saveName": "我的视频",
  "referer": "https://example.com/",
  "cookie": "session=abc123",
  "userAgent": "Mozilla/5.0...",
  "key": "<你的AUTH_KEY>",
  "user": "<你的user>",
  "password": "<你的password>"
}
```

| 参数        | 类型   | 必填 | 默认值                  | 说明                                                                              |
| ----------- | ------ | ---- | ----------------------- | --------------------------------------------------------------------------------- |
| `url`       | string | 是   | —                       | m3u8 视频链接或直接视频链接（mp4/mkv/ts/flv/avi/webm/mov/wmv 等直链自动用 curl）  |
| `saveName`  | string | 否   | `download_<任务ID>`     | 保存文件名（不含扩展名，扩展名由输出格式决定）。默认**不追加时间戳**             |
| `referer`   | string | 否   | 空                      | 来源页面地址，部分站点下载必需                                                     |
| `cookie`    | string | 否   | 空                      | 认证 Cookie，部分站点下载必需                                                      |
| `userAgent` | string | 否   | 空                      | 自定义 User-Agent                                                                  |
| `key`       | string | 是   | —                       | 第一层认证：须与 Docker 环境变量 `AUTH_KEY` 一致                                  |
| `user`      | string | 是   | —                       | 下载用户名：须为容器内 `userctl add` 创建的用户，下载文件存入其隔离目录            |
| `password`  | string | 是   | —                       | 第二层认证：须与 `config.json` 中 `password` 一致，可通过 `/reload` 热更新       |

> **saveName 说明**：
> - 默认建议只传标题（如 `"saveName": "${title}"`），**不加时间戳**。
> - 如需追加时间戳防重名，可写成 `"saveName": "${title}_${now}"`，`_${now}` 会被猫抓替换为毫秒时间戳。
> - 完全省略 `saveName` 字段时，服务端自动用 `download_<任务ID>` 命名（如 `download_abc12345`）。
> - 文件名会依次经过 `filename_filter`（关键字删除）→ `filename_dedup`（正则去重）→ 段级去重处理，最终扩展名由输出格式（mp4/mkv）决定。

响应（成功）：

```json
{
  "success": true,
  "taskId": "abc12345",
  "message": "下载任务已添加",
  "duplicate": false,
  "output_format": "mp4"
}
```

响应（重复任务）：

```json
{
  "success": true,
  "taskId": "abc12345",
  "message": "检测到重复链接，已复用任务",
  "duplicate": true,
  "output_format": "mp4"
}
```

响应（文件已存在）：

```json
{
  "success": false,
  "message": "文件已存在，跳过下载",
  "duplicate": true
}
```

响应（广告拦截）：

```json
{
  "success": false,
  "message": "检测到广告内容，已拦截。关键字: 广告",
  "blocked": true,
  "keyword": "广告"
}
```

### GET /{prefix}/tasks

需要在 URL 后携带认证参数：`GET /{prefix}/tasks?key=<AUTH_KEY>&user=<用户名>&password=<密码>`

响应：

```json
{
  "success": true,
  "data": [
    {
      "id": "abc12345",
      "urls": ["https://example.com/stream.m3u8"],
      "save_name": "我的视频",
      "status": "running",
      "progress": 45
    }
  ]
}
```

> **注意**：响应中已隐藏 `_cookie`、`_referer`、`_user_agent` 等敏感字段。同视频模式下 `urls` 可能包含多个链接。

### GET /{prefix}/tasks/{id}

需要在 URL 后携带认证参数：`GET /{prefix}/tasks/{id}?key=<AUTH_KEY>&user=<用户名>&password=<密码>`

响应（成功）：

```json
{
  "success": true,
  "data": {
    "id": "abc12345",
    "urls": ["https://example.com/stream.m3u8"],
    "save_name": "我的视频",
    "status": "running",
    "progress": 45
  }
}
```

响应（失败）：

```json
{
  "success": false,
  "message": "任务不存在"
}
```

### POST /{prefix}/reload

重新加载配置文件，无需重启容器。

请求体：

```json
{
  "key": "<你的AUTH_KEY>",
  "user": "<你的user>",
  "password": "<你的password>"
}
```

响应：

```json
{
  "success": true,
  "message": "配置已重新加载"
}
```

### GET /{prefix}/health

健康检查接口，无需认证，但**必须包含 URL 前缀**。

响应：

```json
{
  "success": true,
  "status": "ok"
}
```

## ⚙️ 配置说明

### docker-compose.yml 配置

```yaml
services:
  catdock:
    container_name: catdock
    build: .
    volumes:
      - /youdir:/home/downloader/temp
      - /youdir/downloads:/home/downloader/downloads
      - /youdir/config:/home/downloader/config
    ports:
      - 5000:8080
    image: ghcr.nju.edu.cn/divinely3558/catdock
    restart: always
    dns:
      - 223.5.5.5
      - 223.6.6.6
      - 114.114.114.114
      - 119.29.29.29
    environment:
      - AUTH_KEY=your_secure_password_here # 🔑 必须设置：认证密钥
      - URL_PREFIX=admin # 🔒 必须设置：URL路径前缀
      - SSRF_PROTECTION=true # 🛡️ SSRF防护开关
      - MAX_CONCURRENT_TASKS=20 # 📊 最大并发任务数
      # - API_PORT=8080                        # 可选：覆盖默认端口
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8080/${URL_PREFIX}/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 30s
    mem_limit: 512m
    memswap_limit: 512m
    cpus: "1.0"
```

### 环境变量

| 变量名              | 说明                                       | 默认值 | 是否必填 |
| ------------------- | ------------------------------------------ | ------ | -------- |
| `API_PORT`          | 覆盖配置文件中的端口设置                   | 8080   | 否       |
| `AUTH_KEY`          | 第一层认证密钥（所有接口必须）             | 空     | **是**   |
| `URL_PREFIX`        | URL 路径前缀（所有接口必须）               | 空     | **是**   |
| `SSRF_PROTECTION`   | SSRF 防护开关，`false` 允许内网地址下载    | true   | 否       |
| `MAX_CONCURRENT_TASKS` | 最大并发下载任务数                       | 20     | 否       |

> **安全建议**：`AUTH_KEY` 和 `URL_PREFIX` 必须通过环境变量设置，**不要**写入 `config.json`。未设置时程序会拒绝启动。
>
> **两层认证**：系统采用两层认证机制——第一层 `AUTH_KEY`（环境变量，不可通过 reload 修改），第二层 `password`（`config.json` 中的 `password` 字段，可通过 `/reload` 热更新）。请求必须同时携带正确的 `key` 和 `password` 才能通过认证。
>
> `AUTH_KEY` 与 `URL_PREFIX` 的生效优先级为：**环境变量 > config.json 中的默认值 > 内置默认值**。

### 启动网络检测

容器启动时会自动检测网络状态（为宿主机硬件和网络留有缓冲时间）：

1. **检测目标**：依次尝试
   - ping 阿里云 DNS（`223.5.5.5`）
   - ping 114 DNS（`114.114.114.114`）
   - ping 百度（`www.baidu.com`）
   - HTTP 请求百度（`http://www.baidu.com`）
2. **通过判定**：以上任一检查通过即视为网络可达
3. **稳定判定**：需要连续 2 次检查通过才认为网络稳定
4. **最大等待**：最长等待 10 分钟（每 5 秒检查一次）
5. **DNS 预热**：网络稳定后会对百度发起一次请求预热 DNS 缓存
6. **最终等待**：服务启动前额外 sleep 3 秒确保系统稳定
7. **失败处理**：即使超时也会启动服务，下载过程中会自动重试

### 资源限制

| 资源 | 限制   | 说明                          |
| ---- | ------ | ----------------------------- |
| 内存 | 512 MB | 防止下载过程中内存溢出        |
| CPU  | 1 核   | 限制 CPU 使用，防止影响宿主机 |

### 健康检查

容器配置了 Docker 健康检查：

- **检查接口**：`GET /{prefix}/health`（需包含 URL 前缀）
- **检查间隔**：30 秒
- **超时时间**：10 秒
- **重试次数**：3 次
- **启动宽限期**：30 秒

如果连续 3 次健康检查失败，Docker 会自动标记容器为 `unhealthy`。

## 📋 任务持久化

容器支持任务列表自动保存和重启恢复功能，确保正在下载的任务不会因容器重启而丢失。

### 工作原理

1. **自动保存**：每次任务状态变更时，任务列表自动保存到 `tasks.json` 文件（仅保存 `running` 状态的任务）
2. **重启恢复**：容器启动时自动加载 `tasks.json`，并恢复所有正在下载的任务
3. **临时文件清理**：恢复任务前会自动清理上次中断产生的临时文件
4. **任务删除**：任务完成或失败后立即从 `tasks.json` 中删除，释放内存和磁盘空间
5. **下载日志**：完成/失败的任务会记录到 `success.log` 和 `failure.log`，用于防止重复下载
6. **失败日志重置**：容器启动时会自动清空 `failure.log`，允许重新下载之前失败的 URL

### tasks.json 文件

任务列表文件位于 `config` 目录下：

```
/youdir/config/tasks.json
```

文件格式：

```json
[
  {
    "id": "abc12345",
    "urls": ["https://example.com/stream.m3u8"],
    "save_name": "我的视频_1672329448871",
    "status": "running",
    "progress": 45
  }
]
```

> 同视频模式下 `urls` 可能包含多个链接。

### 任务状态说明

> **注意**：任务完成或失败后会立即从 tasks.json 中删除，因此文件中只会包含 `running` 状态的任务。

| 状态      | 说明       |
| --------- | ---------- |
| `running` | 正在下载中 |

### 恢复机制

当容器重启时：

1. 自动加载 `tasks.json` 文件
2. 检测所有状态为 `running` 的任务
3. 检查 URL 是否已成功下载过（通过 `success.log`）
4. 检查是否已存在同名视频文件
5. 检查是否存在未转换的源文件（`.ts` 或 `.MUX.mp4`），如有则尝试转换
6. 清理相关临时文件
7. 重新提交下载任务，生成新的任务 ID
8. 删除旧任务记录

### 重复下载防护

系统通过以下优先级检测重复下载：

1. **下载历史**：检查 `success.log` 和 `failure.log`（最近 300 条记录）
2. **任务列表**：检查当前正在运行的任务
3. **已存在视频**：检查 downloads 目录中是否已存在完整视频文件
4. **.copy 文件**：检查是否存在重复的 `.copy` 文件

### 同视频模式（same_video_by_filename）

开启 `same_video_by_filename: true` 后，系统按文件名判定同一视频：

- **聚合链接**：同一文件名的多个不同下载链接自动聚合为一个视频组
- **轮流切换**：每个链接尝试 1 次后切换下一个，所有链接失败算一个"失败回合"
- **5 轮放弃**：共尝试 5 个失败回合后放弃下载
- **去重**：文件名已在 `success.log` 或 `failure.log` 中记录时直接跳过，提示"文件xxx下载成功/失败"

| 轮次  | 尝试顺序（2个链接） | 结果          |
| ----- | ------------------- | ------------- |
| 第1轮 | 链接1 → 链接2       | 都失败        |
| 第2轮 | 链接2 → 链接1       | 都失败        |
| ...   | ...                 | ...           |
| 第5轮 | 链接1 → 链接2       | 都失败 → 放弃 |

## 🔍 过滤规则

容器支持可配置的过滤规则，包括广告拦截和文件名清理两种功能。

### 默认配置

默认情况下 `keywords` 和 `filename_filter` 均为空列表，即默认不执行任何过滤。

### 自定义配置

配置文件分为两个独立文件，放在同一个 `config` 目录下：

| 文件                | 用途                                  |
| ------------------- | ------------------------------------- |
| `config.json`       | 端口、输出格式、调试开关              |
| `filter_rules.json` | 过滤规则配置（广告拦截 + 文件名过滤） |

#### 步骤 1：创建 config 目录

```bash
mkdir -p /youdir/config
```

#### 步骤 2：创建 config.json

```bash
cat > /youdir/config/config.json << 'EOF'
{
  "port": 8080,
  "output_format": {
    "format": "mp4"
  },
  "debug": false,
  "same_video_by_filename": false,
  "ssrf_protection": true,
  "max_concurrent_tasks": 20,
  "password": "your_password_here"
}
EOF```

#### 步骤 3：创建 filter_rules.json

```bash
cat > /youdir/config/filter_rules.json << 'EOF'
{
  "keywords": {
    "enabled": true,
    "list": []
  },
  "filename_filter": {
    "enabled": true,
    "list": []
  },
  "filename_dedup": {
    "enabled": true,
    "rules": [
      {
        "pattern": "(\\w+)(_\\1)+",
        "replacement": "\\1"
      }
    ]
  }
}
EOF
```

#### 步骤 4：修改 docker-compose.yml 添加挂载

```yaml
volumes:
  - /youdir:/home/downloader/temp
  - /youdir/downloads:/home/downloader/downloads
  - /youdir/config:/home/downloader/config
```

#### 步骤 5：重启容器

```bash
docker-compose up -d --build
```

### config.json 参数说明

| 参数                     | 说明                                             | 默认值 |
| ------------------------ | ------------------------------------------------ | ------ |
| `port`                   | 服务监听端口，可被环境变量 `API_PORT` 覆盖       | 8080   |
| `output_format.format`   | 输出格式，`mp4` 或 `mkv`                         | `mp4`  |
| `debug`                  | 是否启用调试模式，开启后会输出详细日志           | false  |
| `same_video_by_filename` | 是否启用同视频模式（按文件名聚合多链接轮流下载） | false  |
| `ssrf_protection`        | 是否启用 SSRF 防护（拦截内网地址），可被环境变量覆盖 | true   |
| `max_concurrent_tasks`   | 最大并发下载任务数，可被环境变量覆盖             | 20     |
| `password`               | 第二层认证密码，请求体 `password` 字段需与此一致，可通过 `/reload` 热更新 | 空     |

> ⚠️ `config.json` 中**不再**包含 `auth_key` 与 `url_prefix`，这两个敏感参数统一通过 Docker 环境变量注入。

### filter_rules.json 参数说明

| 参数              | 说明                                                                    |
| ----------------- | ----------------------------------------------------------------------- |
| `keywords`        | 拦截关键字配置对象。文件名或 URL 中包含这些关键字时整个下载请求会被拦截 |
| `filename_filter` | 文件名过滤配置对象。下载时从文件名中删除这些关键字（不拦截下载）        |
| `filename_dedup`  | 文件名去重配置对象，用正则表达式去除连续重复的段                        |

> **三种过滤机制说明**：
>
> - `keywords`：拦截整个下载请求（用于屏蔽广告）
> - `filename_filter`：仅过滤文件名，不影响下载（用于清理文件名中的无用字符）
> - `filename_dedup`：用正则表达式去除文件名中连续重复的段（不拦截下载）
>
> 示例：
>
> - `filename_filter.list: ["fh"]`，文件名 `abc_fhc_lka.mp4` → `abc_c_lka.mp4`
> - `filename_dedup` 启用（默认正则 `(\w+)(_\1)+` → `\1`）：
>   - `abc_abc_lcksmdnc_bnh_bnh.mp4` → `abc_lcksmdnc_bnh.mp4`
>   - `abc_abc_lcksmdnc_bnh.mp4` → `abc_lcksmdnc_bnh.mp4`
>   - `abc_lcksmdnc_bnh_bnh.mp4` → `abc_lcksmdnc_bnh.mp4`

#### keywords 子参数

| 参数      | 说明                   | 默认值 |
| --------- | ---------------------- | ------ |
| `enabled` | 是否启用拦截关键字     | `true` |
| `list`    | 关键字列表，支持中英文 | `[]`   |

#### filename_filter 子参数

| 参数      | 说明                                     | 默认值 |
| --------- | ---------------------------------------- | ------ |
| `enabled` | 是否启用文件名过滤                       | `true` |
| `list`    | 过滤关键字列表，从文件名中删除这些关键字 | `[]`   |

#### filename_dedup 子参数

| 参数      | 说明                         | 默认值 |
| --------- | ---------------------------- | ------ |
| `enabled` | 是否启用文件名去重           | `true` |
| `rules`   | 正则规则列表，按顺序依次应用 | `[]`   |

每条规则包含：

| 参数          | 说明                                                   |
| ------------- | ------------------------------------------------------ |
| `pattern`     | Python 标准正则表达式字符串（JSON 中 `\` 需写成 `\\`） |
| `replacement` | 替换文本，`\1` `\2` 等引用捕获组                       |

> **段级去重（始终启用）**：当 `filename_dedup.enabled` 为 `true` 时，除了应用 `rules` 中的正则规则外，还会自动按 `_` 分割文件名并去除所有重复段（包括非连续重复）。无需额外配置。
>
> | 输入                               | 仅正则能处理                               | 加上段级去重（自动）   |
> | ---------------------------------- | ------------------------------------------ | ---------------------- |
> | `abc_abc_lcksmdnc_bnh_bnh.mp4`     | `abc_lcksmdnc_bnh.mp4`                     | `abc_lcksmdnc_bnh.mp4` |
> | `abc_lcksmdnc_abc_bnh.mp4`         | `abc_lcksmdnc_abc_bnh.mp4` (未去重)        | `abc_lcksmdnc_bnh.mp4` |
> | `abc_abc_lcksmdnc_abc_bnh_bnh.mp4` | `abc_lcksmdnc_abc_bnh.mp4` (中间abc未去重) | `abc_lcksmdnc_bnh.mp4` |

#### 正则规则编写指南

##### 第一步：理解 JSON 转义

JSON 字符串中 `\` 是转义符，所以正则中的 `\` 必须写成 `\\`：

| 你脑海中想写的正则 | JSON 中应写为 |
| ------------------ | ------------- |
| `\w`               | `\\w`         |
| `\d`               | `\\d`         |
| `\.`               | `\\.`         |
| `\1`（反向引用）   | `\\1`         |
| `\s`               | `\\s`         |

> 口诀：**正则里每个 `\`，JSON 里写两个 `\\`**

##### 第二步：掌握常用正则语法

**字符匹配**：

| 语法     | 含义                       | 示例                           |
| -------- | -------------------------- | ------------------------------ |
| `\w`     | 字母、数字、下划线         | `\w+` 匹配 `abc_123`           |
| `\d`     | 数字                       | `\d{4}` 匹配 `2024`            |
| `\s`     | 空白字符（空格、制表符等） | `\s+` 匹配一个或多个空格       |
| `.`      | 任意字符（不含换行）       | `a.c` 匹配 `abc`、`axc`        |
| `[...]`  | 字符集，匹配其中任意一个   | `[abc]` 匹配 `a` 或 `b` 或 `c` |
| `[^...]` | 取反字符集                 | `[^0-9]` 匹配非数字            |
| `[a-z]`  | 字符范围                   | `[a-z]` 匹配任意小写字母       |

**量词（控制匹配次数）**：

| 语法    | 含义                   | 示例                             |
| ------- | ---------------------- | -------------------------------- |
| `+`     | 前一个出现 1 次或多次  | `a+` 匹配 `a`、`aaa`             |
| `*`     | 前一个出现 0 次或多次  | `ab*` 匹配 `a`、`abbb`           |
| `?`     | 前一个出现 0 次或 1 次 | `colou?r` 匹配 `color`、`colour` |
| `{n}`   | 前一个出现恰好 n 次    | `\d{4}` 匹配 `2024`              |
| `{n,m}` | 前一个出现 n 到 m 次   | `\d{2,4}` 匹配 `20`、`2024`      |
| `{n,}`  | 前一个出现至少 n 次    | `\d{2,}` 匹配 `20`、`12345`      |

**分组与引用**：

| 语法 | 含义                                  | 示例                             |
| ---- | ------------------------------------- | -------------------------------- |
| `()` | 捕获组，可用 `\1` `\2` 在替换中引用   | `(ab)` 匹配并捕获 `ab`           |
| `\1` | 反向引用，匹配与第 1 个捕获组相同文本 | `(\w+)(_\1)+` 匹配 `abc_abc`     |
| `\2` | 反向引用第 2 个捕获组                 | `(a)(b)\2` 匹配 `abb`            |
| `\|` | 或（在 `()` 或 `[]` 内使用）          | `(cat\|dog)` 匹配 `cat` 或 `dog` |

**位置锚点**：

| 语法 | 含义       | 示例                        |
| ---- | ---------- | --------------------------- |
| `^`  | 字符串开头 | `^abc` 匹配以 `abc` 开头    |
| `$`  | 字符串结尾 | `\.mp4$` 匹配以 `.mp4` 结尾 |

**特殊字符转义**（需要匹配这些字符本身时，前面加 `\`）：

| 字符    | JSON 写法   | 说明                                               |
| ------- | ----------- | -------------------------------------------------- |
| `.`     | `\\.`       | 匹配实际的点号                                     |
| `_`     | `_`         | 下划线无需转义                                     |
| `-`     | `\\-`       | 在 `[]` 外通常无需转义，在 `[]` 内放首位或末位即可 |
| `(` `)` | `\\(` `\\)` | 匹配实际的括号                                     |
| `[` `]` | `\\[` `\\]` | 匹配实际的方括号                                   |
| `{` `}` | `\\{` `\\}` | 匹配实际的花括号                                   |
| `\`     | `\\\\`      | 匹配实际的反斜杠                                   |

##### 第三步：理解 replacement 替换文本

`replacement` 是匹配成功后替换为什么文本：

| 替换文本         | 含义                                | 示例                                             |
| ---------------- | ----------------------------------- | ------------------------------------------------ |
| `\\1`            | 第 1 个捕获组的内容                 | pattern `(\\w+)_\\d+`，`abc_123` → `abc`         |
| `\\2`            | 第 2 个捕获组的内容                 | pattern `\\d+_(\\w+)_(\\w+)`，`123_ab_cd` → `cd` |
| `\\g<1>`         | 第 1 个捕获组（等价 `\\1`，更清晰） | 同上                                             |
| `""`（空字符串） | 删除匹配内容                        | pattern `_(1080p)`，`v_1080p_e` → `v_e`          |
| `固定文本`       | 替换为固定字符串                    | replacement `"_"`，把匹配内容换成下划线          |

##### 第四步：理解执行流程

1. **关键字删除**（`filename_filter`）先执行
2. **正则规则**（`filename_dedup.rules`）按数组顺序依次执行，每条循环到不再变化
3. **段级去重**（自动）最后执行，按 `_` 分割去除所有重复段（包括非连续重复）

##### 第五步：实战示例

**示例 1**：去除连续重复段

```json
{
  "pattern": "(\\w+)(_\\1)+",
  "replacement": "\\1"
}
```

- 原理：`(\w+)` 捕获一段文字，`(_\1)+` 匹配后续连续重复的相同段，替换为只保留第一段
- `abc_abc_lcksmdnc_bnh_bnh.mp4` → `abc_lcksmdnc_bnh.mp4`
- `abc_abc_lcksmdnc_bnh.mp4` → `abc_lcksmdnc_bnh.mp4`
- `abc_lcksmdnc_bnh_bnh.mp4` → `abc_lcksmdnc_bnh.mp4`

**示例 2**：删除分辨率标记

```json
{
  "pattern": "_(1080p|720p|4K|480p)",
  "replacement": ""
}
```

- 原理：`|` 匹配多种分辨率，`()` 分组，替换为空即删除
- `video_1080p_episode1.mp4` → `video_episode1.mp4`
- `show_720p_s01e02.mp4` → `show_s01e02.mp4`

**示例 3**：删除日期时间戳（如 `20240115_` 前缀）

```json
{
  "pattern": "^\\d{8}_",
  "replacement": ""
}
```

- 原理：`^` 锚定开头，`\d{8}` 匹配 8 位数字，`_` 匹配下划线
- `20240115_video_name.mp4` → `video_name.mp4`

**示例 4**：合并连续下划线

```json
{
  "pattern": "_+",
  "replacement": "_"
}
```

- 原理：`_+` 匹配一个或多个下划线，替换为单个
- `abc___def__ghi.mp4` → `abc_def_ghi.mp4`

**示例 5**：替换分隔符（下划线改空格）

```json
{
  "pattern": "_",
  "replacement": " "
}
```

- `My_Video_Episode_01.mp4` → `My Video Episode 01.mp4`

**示例 6**：删除方括号标记（如 `[原创]`、`[字幕组]`）

```json
{
  "pattern": "\\[[^\\]]+\\]",
  "replacement": ""
}
```

- 原理：`\\[` 匹配 `[`，`[^\\]]+` 匹配除 `]` 外的任意字符，`\\]` 匹配 `]`
- `[原创]video_name.mp4` → `video_name.mp4`
- `video[字幕组]_01.mp4` → `video_01.mp4`

**示例 7**：多个规则组合使用

```json
"rules": [
  {
    "pattern": "(\\w+)(_\\1)+",
    "replacement": "\\1"
  },
  {
    "pattern": "_(1080p|720p|4K)",
    "replacement": ""
  },
  {
    "pattern": "\\[[^\\]]+\\]",
    "replacement": ""
  },
  {
    "pattern": "_+",
    "replacement": "_"
  }
]
```

执行过程（以 `abc_abc_[AD]_1080p_bnh_bnh.mp4` 为例）：

1. 去重复段 → `abc_[AD]_1080p_bnh.mp4`
2. 删分辨率 → `abc_[AD]_bnh.mp4`
3. 删方括号 → `abc__bnh.mp4`
4. 合并下划线 → `abc_bnh.mp4`

##### 第六步：调试技巧

- **先测试**：在 Python 中用 `re.sub(pattern, replacement, filename)` 测试你的正则
- **从简单开始**：一条规则只做一件事，用多条规则组合
- **注意顺序**：可能产生副作用的规则放后面（如合并下划线放最后）
- **查看日志**：文件名被过滤后直接使用过滤结果，不再显示过滤过程。有广告过滤时在"开始下载任务"日志中追加 `过滤广告 x 个`

### 输出格式配置

| 格式  | 说明                                 |
| ----- | ------------------------------------ |
| `mp4` | MP4 格式，兼容性好，适合大多数播放器 |
| `mkv` | MKV 格式，支持更多音轨和字幕         |

### 拦截行为

当检测到 `keywords` 中的广告关键字时：

- 返回 HTTP 200，`success: false`
- 包含 `blocked: true` 和触发的关键字
- 容器日志会记录拦截信息

当启用 `filename_filter` 时：

- 下载成功后，文件名中包含的过滤关键字会被自动删除
- 例如 `abc_fhc_lka.mp4` + `filename_filter: ["fh"]` → `abc_c_lka.mp4`

当启用 `filename_dedup` 时：

- 下载成功后，文件名中连续重复的段会被自动去重
- 例如 `abc_abc_lcksmdnc_bnh_bnh.mp4` → `abc_lcksmdnc_bnh.mp4`

## 🐳 Docker 管理命令

### 查看日志

```bash
docker logs catdock
docker logs -f catdock      # 实时跟踪
docker logs --tail 200 catdock   # 查看最近 200 行
```

### 进入容器

```bash
docker exec -it catdock bash
```

### 停止容器

```bash
docker-compose down
```

### 重启容器

```bash
docker-compose restart
```

### 重建并启动

```bash
docker-compose up -d --build
```

## 🛠️ 故障排查

### 断电/宿主机重启后容器无法下载

catdock 已针对断电重启场景做了特殊处理：

1. **自动清空失败日志**：容器启动时会自动清空 `failure.log`，允许重新下载之前失败的 URL
2. **恢复未完成任务**：通过 `tasks.json` 自动恢复断电前正在下载的任务
3. **网络就绪检测**：容器启动前会主动检测网络，避免在网络未就绪时盲目下载
4. **下载重试机制**：下载过程中如遇网络中断会自动重试

如果断电后仍然无法下载，建议：

```bash
# 1. 查看启动日志，确认网络检测和失败日志清空是否正常
docker logs --tail 50 catdock

# 2. 重启容器（会触发上述全部恢复流程）
docker-compose restart catdock

# 3. 若仍无改善，删除 tasks.json 手动清空任务后再重启
rm /youdir/config/tasks.json
docker-compose restart catdock
```

### 物理机开机后容器报 "Temporary failure in name resolution"

#### 现象

物理机开机后，容器随 `restart: always` 自动启动，但下载时出现 `Temporary failure in name resolution`，手动重启容器后恢复正常。

#### 原因

Docker 守护进程通常在宿主机 DNS（如 `systemd-resolved`）完全就绪之前就启动了容器。容器启动时会复制宿主机的 `/etc/resolv.conf`，若此时 DNS 尚未就绪，容器拿到的就是不完整的解析配置，导致域名解析失败。手动重启容器时宿主机 DNS 已就绪，因此恢复正常。

#### 解决方案

在 `docker-compose.yml` 中通过 `dns` 字段显式指定 DNS 服务器：

```yaml
    dns:
      - 223.5.5.5        # 阿里 DNS
      - 223.6.6.6        # 阿里 DNS 备用
      - 114.114.114.114  # 114 DNS
      - 119.29.29.29     # 腾讯 DNS
```

这样容器启动时 Docker 会将这些 DNS 作为上游服务器直接配置，不再依赖宿主机开机时未就绪的 `resolv.conf`，从根本上避免时序问题。

> 容器运行在 docker-compose 创建的自定义网络中时，`/etc/resolv.conf` 中会显示 `nameserver 127.0.0.11`（Docker 内置 DNS 解析器），而你指定的 DNS 会以 `ExtServers` 形式作为其上游。这是正常且理想的状态。

#### 验证

```bash
# 查看容器内 DNS 配置
docker exec catdock cat /etc/resolv.conf

# 测试域名解析
docker exec catdock getent hosts baidu.com
```

### 接口返回 403 Forbidden

说明认证未通过，请逐一检查：

- **第一层（key）**：检查 docker-compose.yml 中 `AUTH_KEY` 设置，确认请求体的 `key` 字段与之一致
- **第二层（user/password）**：确认 `user` 为容器内 `userctl add` 创建的用户，`password` 与 `config.json` 中 `password` 字段一致
- 确认修改环境变量后已 `docker-compose up -d` 重新创建容器

### 健康检查接口访问不到

- 确认端口映射 `5000:8080` 未被占用
- 确认容器内服务已正常启动（查看 `docker logs catdock`）
- 容器启动时会等待网络就绪，最长 10 秒内才会开始启动 API

### 下载卡在 "仍在等待网络就绪..."

网络检测最长等待 10 分钟。如果持续超时：

- 检查宿主机是否可以正常访问公网
- 宿主机防火墙是否放行 Docker 出站流量
- DNS 是否可用（容器使用 `docker-compose.yml` 中 `dns` 字段指定的 DNS 服务器）

即使网络检测超时，容器也会继续启动，下载过程中会自动重试。

## 📝 注意事项

1. **猫抓版本**：建议使用猫抓 2.3.8+ 版本以支持 `${cookie}` 标签
2. **下载参数**：某些网站需要 `referer` 和 `cookie` 才能下载，请确保猫抓正确捕获这些参数
3. **端口安全**：建议在生产环境修改 HTTP 端口（通过 `API_PORT` 环境变量或 `port` 配置）
4. **配置修改**：修改 `config.json` 或 `filter_rules.json` 后可以通过 `POST /{prefix}/reload` 接口重新加载，无需重启容器
5. **环境变量修改**：修改 `AUTH_KEY`、`URL_PREFIX` 等环境变量需要 `docker-compose up -d` 重新创建容器
6. **文件格式**：下载完成后会自动转换为配置的输出格式（MP4/MKV）
7. **URL 前缀**：`URL_PREFIX` 为必填项，所有 API 接口（含健康检查）路径都必须添加前缀，未带前缀返回 404
8. **两层认证 + 用户**：`AUTH_KEY`（环境变量）、`config.json` 中 `password`、以及容器内 `userctl add` 创建的用户名均为必填，所有请求必须同时携带正确的 `key`、`user` 和 `password`，否则返回 403；GET 请求通过查询参数 `?key=&user=&password=` 传递
9. **任务持久化**：任务列表自动保存到 `tasks.json`，容器重启后会自动恢复未完成的任务
10. **重复下载**：同一 URL 不会重复下载，系统会自动检测下载历史和已存在的文件
11. **调试模式**：开启 `debug: true` 可查看详细日志，便于排查问题
12. **时区**：容器内所有日志和时间统一使用北京时间（UTC+8 / Asia/Shanghai）
13. **SSRF 防护**：默认启用，拦截内网地址下载；如需下载内网/Docker 网络资源，设置 `SSRF_PROTECTION=false`
14. **速率限制**：每 IP 60 秒内最多 60 次请求，超限返回 429
15. **并发限制**：默认最多 20 个并发下载任务，超限返回 429

## ❓ 常见问题 FAQ

**Q: 为什么断电重启电脑后容器会卡在等待网络就绪？**
A: 宿主机断电重启后网络服务需要一定时间初始化，容器会主动检测网络状态避免在网络未就绪时盲目下载。最长等待 10 分钟，超时后仍会启动服务。

**Q: 我把 AUTH_KEY 写在 config.json 里会生效吗？**
A: 为了安全，`config.json` 中不支持 `auth_key` 与 `url_prefix`，请务必通过 Docker 环境变量设置。但 `password`（第二层认证密码）需要写在 `config.json` 中。

**Q: 如何修改输出格式？**
A: 修改 `config.json` 中 `output_format.format` 为 `mp4` 或 `mkv`，然后调用 `POST /{prefix}/reload` 接口即可。

**Q: 容器会自动重启吗？**
A: `docker-compose.yml` 中已配置 `restart: always`，容器崩溃或宿主机重启后会自动重启。结合健康检查可实现更完善的自愈。

**Q: 可以在容器内直接执行 N_m3u8DL-RE 吗？**
A: 可以，容器内 `/home/downloader/N_m3u8DL-RE` 为 Linux amd64 版本。

**Q: 物理机开机后容器报 "Temporary failure in name resolution" 怎么办？**
A: 这是 Docker 在宿主机 DNS 就绪前启动容器导致的时序问题。`docker-compose.yml` 中已通过 `dns` 字段显式指定了国内 DNS 服务器（阿里、114、腾讯），容器启动时直接使用这些 DNS 而不依赖宿主机未就绪的 `resolv.conf`。修改后需 `docker compose up -d --force-recreate` 重新创建容器生效。详见「故障排查」章节。

## 📄 许可证

本项目基于 [木兰宽松许可证，第2版](http://license.coscl.org.cn/MulanPSL2) 开源。

## 🙏 致谢

- [N_m3u8DL-RE](https://github.com/nilaoda/N_m3u8DL-RE) - 📥 核心下载工具
- [FFmpeg](https://ffmpeg.org/) - 🎬 视频处理工具
- [猫抓插件](https://cat-catch.94cat.com/) - 🔌 浏览器资源嗅探插件
