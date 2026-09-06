# 🎬 catdock

基于 N_m3u8DL-RE 的 Docker 容器下载工具，支持通过猫抓浏览器插件远程控制容器下载视频。

## ✨ 功能特性

- **🐳 Docker 容器部署**：轻量级 Debian 基础镜像，非 root 用户运行
- **🔌 猫抓插件支持**：通过数据发送功能远程控制容器下载
- **📡 HTTP API**：提供下载触发、任务查询、用户管理等接口
- **🖥️ 三套网页**：登录页 `/{prefix}/login.html`、下载控制台 `/{prefix}/user.html`、管理控制台 `/{prefix}/admin.html`；旧地址（根路径、`/login`、`/user`、`/admin` 及带尾斜杠形式）访问时 302 跳转到对应 `.html` 规范地址；登录后按角色自动跳转，纯静态外壳 + Bearer 令牌调用 API
- **🎬 完整下载参数**：支持 referer、cookie、user-agent、逐任务输出格式（mp4/mkv）等
- **💾 数据持久化**：配置、用户数据、下载缓存与成品文件均持久化到宿主机，重建容器不丢失
- **🔒 URL 路径前缀**：支持设置访问前缀（如 `/qj52lajx`），增强接口安全性
- **🎫 访问令牌认证**：登录签发 2 小时短期令牌（Bearer Token），凭证不再通过 URL 传递；POST 接口兼容请求体凭证（猫抓插件等第三方调用方）
- **🔄 令牌吊销**：网页「退出」立即吊销当前令牌；改密码/删用户/禁用用户/更换 AUTH_KEY 后相关令牌强制失效（全端下线）
- **👥 多用户隔离**：任务列表按登录用户过滤；配置/日志/缓存/成品分别存入 `user/<用户名>`、`temp/<用户名>`、`downloads/<用户名>` 独立目录
- **🛠️ 管理员体系**：管理员/下载用户两种角色；首启自动创建默认管理员 `admin`（14 位随机密码，见启动日志）；管理网页可增删用户、改密、禁用、热更新 AUTH_KEY、编辑过滤规则模板；管理员账户增删通过容器内 `adminctl` 命令
- **🔑 AUTH_KEY 热更新**：`AUTH_KEY` 存于 admin_config.json（首启自动随机生成），管理网页修改后立即写回文件并生效、全员强制重新登录，无需重启容器
- **🗂️ 配置分层**：系统级配置（config.json，仅系统管理员经命令行/文件修改，重启容器生效）与管理员热配置（admin_config.json，管理网页修改即时生效）相互独立
- **🚫 用户禁用**：`userctl ban/unban` 或管理网页可禁用用户，被禁用户立即无法登录、已签发令牌全部失效
- **🔐 修改密码**：网页菜单「修改密码」（旧密码 1 遍 + 新密码 2 遍），成功后该用户全部令牌吊销并回到登录页；CLI 等价命令 `userctl password` / `adminctl password`
- **🚨 分级封禁**：AUTH_KEY 错误或用户不存在按 **IP 级**计数（10 分钟内 10 次 → 临时封禁 30 分钟，再次触发永久封禁）；密码错误按 **账号级**计数（10 分钟内 5 次 → 自动禁用该账号）；`banip` CLI 管理 IP 封禁
- **🔍 每用户过滤规则**：广告拦截关键字 / 文件名关键字过滤 / 正则去重三套机制各自独立开关，用户在网页菜单「过滤规则」中自助编辑（chips 增删 + 正则前端校验），保存即时生效；管理员可编辑全局模板，新用户首次使用自动复制
- **🔐 敏感配置隔离**：`URL_PREFIX` 仅通过 Docker 环境变量注入（生产地址恒定），config.json / admin_config.json 不入 git
- **📋 任务持久化**：任务按用户自动保存到 `user/<用户名>/tasks.json`，任务完成立即清除记录；重启后自动恢复未完成任务
- **🎥 逐任务输出格式**：下载请求可带 `format` 字段指定 mp4/mkv（默认 mp4），网页新建任务时下拉选择
- **📹 直接视频下载**：支持 mp4、mkv、ts、flv、f4v、avi、webm、mov、wmv 等格式的直链下载（curl 断点续传）；`.f4v` 下载后直接改名为 `.mp4`（标准碎片化 MP4 容器，无需转码）
- **🔎 无扩展名链接自动嗅探**：路径没有视频扩展名的下载链接（如下载页跳转 `?dl_id=xxx`，文件名在 `Content-Disposition` 响应头中），自动通过响应头与内容魔数（`ftyp`/`FLV`/`#EXTM3U` 等）识别真实类型后选择直链或 m3u8 下载方式
- **🧭 CDN 调度链接自动解析**：个别站点的媒体链接返回 JSON 调度响应而非视频本身，自动解析其中的真实 CDN 地址并跟随下载（经 SSRF 校验，最多 3 跳）
- **🔄 断点续传**：m3u8 分片与直链断点在重启/重建后保留并自动续传，网络中断自动重试
- **🛡️ 重复下载防护**：检测 URL 是否已下载过，避免重复下载
- **🎬 同视频模式**：按文件名判定同一视频，多链接轮流切换下载（每轮 5 次后放弃）
- **🐞 调试模式**：支持开启调试日志，便于问题排查
- **⏱️ 请求超时处理**：30 秒请求超时保护，防止连接阻塞
- **🚪 优雅关闭**：支持 SIGTERM/SIGINT 信号，安全停止服务
- **🌏 东八区时间**：日志时间戳统一使用北京时间（UTC+8）
- **🌐 网络就绪检测**：容器启动前自动检测网络状态，确保下载环境就绪
- **🔁 失败重置**：启动时自动清空各用户 `failure.log`，允许重新下载之前失败的 URL
- **🧠 自动恢复**：容器重启后自动恢复未完成下载任务，保留进度与分片
- **🛡️ SSRF 防护**：拦截指向内网/回环/云元数据地址的下载请求，可开关
- **🚦 速率限制**：每 IP 60 秒内最多 60 次请求，防止暴力破解与 DoS
- **📊 并发任务限制**：默认最多 20 个并发下载任务，防止资源耗尽
- **🔒 接口认证全覆盖**：网页页面（登录/下载/管理）与 favicon、`/health` 为公开静态资源，其余所有 API 均需认证；未带前缀的请求返回 404
- **🔑 恒定时间密钥比较**：使用 `hmac.compare_digest` 防止时序攻击
- **🙈 日志 URL 脱敏**：自动隐藏 URL 中的 token/sign/key 等敏感查询参数
- **🙈 敏感字段隐藏**：`/tasks` 响应不返回 `_cookie`、`_referer`、`_user_agent`
- **🎨 网页主题切换**：登录页与下载控制台提供三套主题色（墨绿默认 / 暖橙 / 紫罗兰）× 亮暗双模式，设置保存在浏览器本地；管理控制台固定默认墨绿亮色主题
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
│   └── data_db.py       # 🗄️ data.db（封禁 IP + 用户/角色/禁用 + 令牌）
├── cli/                 # 🔧 命令行工具（容器内加入 PATH，可直接执行）
│   ├── banip            # 🔧 IP 封禁管理 CLI（show/add/del）
│   ├── userctl          # 👤 下载用户管理 CLI（add/del/password/ban/unban）
│   └── adminctl         # 🛠️ 管理员账户管理 CLI（add/del/password/list）
├── web/                 # 🖥️ 前端资源（容器内平铺到 /home/downloader/）
│   ├── login.html       # 🔑 登录页（按角色自动跳转）
│   ├── user.html        # 🖥️ 下载控制台（普通用户）
│   ├── admin.html       # 🛠️ 管理控制台（管理员）
│   └── favicon.ico      # 🌐 网页图标
├── sh/                  # 📜 Shell 脚本
│   ├── entrypoint.sh    # 🚀 容器启动脚本
│   └── deploy.sh        # 📦 镜像构建/推送/清理脚本（本地使用）
├── config/              # ⚙️ 配置模板
│   ├── config.example.json  # ⚙️ 系统级配置模板（真实 config.json 运行时挂载）
│   ├── admin_config.example.json # 🔑 管理员热配置模板（真实 admin_config.json 运行时挂载）
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
mkdir -p /youdir/{config,user,temp,downloads}
```

将 `/youdir` 替换为你希望存放下载文件的实际路径。四个目录分别对应：配置与数据库、每用户配置/日志、下载缓存分片、最终成品视频。

### 2. 修改 docker-compose.yml

```yaml
services:
  catdock:
    container_name: catdock
    build: .
    volumes:
      - /youdir/config:/home/downloader/config
      - /youdir/user:/home/downloader/user
      - /youdir/temp:/home/downloader/temp
      - /youdir/downloads:/home/downloader/downloads
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
      - URL_PREFIX=qj52lajx # 🔒 必须设置：URL 路径前缀（建议 8 位以上随机字符串）
      - SSRF_PROTECTION=true # 🛡️ SSRF防护: true=拦截内网地址, false=允许内网下载
      - MAX_CONCURRENT_TASKS=20 # 📊 最大并发下载任务数
```

> `AUTH_KEY` 不通过环境变量配置：它保存在 admin_config.json 的 `auth_key` 字段，首次启动自动随机生成，之后可在管理网页热更新。config.json 为系统级配置（端口/调试/同视频模式等），仅系统管理员修改、重启容器后生效。

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
2. **首次启动凭据**：自动生成的 `AUTH_KEY` 与默认管理员 `admin` 的 14 位随机初始密码（仅显示一次，请妥善保存并尽快修改）
3. 猫抓插件发送地址与请求体模板
4. API 接口列表
5. 当前加载的配置摘要

## 📂 目录挂载说明

容器内部使用以下目录，全部通过 `volumes` 挂载到宿主机（重建容器数据不丢）：

| 容器路径                     | 宿主机路径          | 用途                                                          |
| ---------------------------- | ------------------- | ------------------------------------------------------------- |
| `/home/downloader/config`    | `/youdir/config`    | 系统配置、管理员热配置、全局过滤模板、data.db                 |
| `/home/downloader/user`      | `/youdir/user`      | 每用户配置目录：`user/<用户名>/` 下的任务、日志、个人过滤规则 |
| `/home/downloader/temp`      | `/youdir/temp`      | 下载缓存分片，按用户隔离 `temp/<用户名>/`                     |
| `/home/downloader/downloads` | `/youdir/downloads` | 最终视频成品，按用户隔离 `downloads/<用户名>/`                |

`config` 目录中会生成/保存以下文件：

| 文件                | 说明                                                                         |
| ------------------- | ---------------------------------------------------------------------------- |
| `config.json`       | 系统级配置：端口、调试开关、同视频模式等（仅系统管理员修改，重启生效）       |
| `admin_config.json` | 管理员热配置：`auth_key` 认证密钥（管理网页修改即时生效）                    |
| `filter_rules.json` | 全局过滤规则模板（广告拦截 + 文件名过滤/去重），新用户首次使用时自动复制一份 |
| `data.db`           | SQLite 数据库（封禁 IP + 用户/角色/禁用状态 + 认证失败计数 + 令牌吊销登记）  |

每个用户在 `user/<用户名>/` 目录下拥有独立的文件：

| 文件                | 说明                                                         |
| ------------------- | ------------------------------------------------------------ |
| `tasks.json`        | 该用户未完成的任务列表（任务完成后自动清除，无需手动编辑）   |
| `success.log`       | 该用户已成功下载的 URL 记录（用于去重）                      |
| `failure.log`       | 该用户下载失败的 URL 记录（容器启动时自动清空以允许重试）    |
| `filter_rules.json` | 该用户个人的过滤规则（网页「过滤规则」编辑器保存，即时生效） |

> 删除用户时，该用户的 `user/<用户名>`、`temp/<用户名>`、`downloads/<用户名>` 三个目录会一并删除，数据不可恢复（管理网页删除时有明确确认提示）。

## 🔌 猫抓插件配置

### 使用方法

猫抓插件通过 **数据发送** 功能直接调用容器的 HTTP API。

### 配置步骤

1. **打开猫抓设置** → **数据发送**

2. **发送地址**（前缀以 `qj52lajx` 为例）：

   ```
   http://你的容器IP:5000/qj52lajx/download
   ```

3. **请求体**（JSON 格式，必须包含两层认证 + 用户字段）：

   ```json
   {
     "url": "${url}",
     "saveName": "${title}_${now}",
     "referer": "${referer}",
     "cookie": "${cookie}",
     "userAgent": "${userAgent}",
     "key": "<你的AUTH_KEY>",
     "user": "<你的user>",
     "password": "<你的password>",
     "format": "mp4"
   }
   ```

   > `saveName` 默认建议填 `${title}_${now}`（标题 + 毫秒时间戳）：同一网页存在多个视频时标题往往相同，追加时间戳可避免文件名相同被去重/合并为一个任务而只下载到一个。如希望同一视频的多条链接自动合并下载，可只填 `${title}`。

4. **保存设置**

### 使用流程

1. 在浏览器中打开视频网页
2. 猫抓插件捕获到 m3u8 链接或直接视频链接
3. 点击资源列表中的 **发送** 按钮
4. 下载任务自动发送到容器执行
5. 文件保存在宿主机的 `/youdir/downloads` 目录

### 注意事项

- 发送地址必须包含 `url_prefix`，如 `http://你的容器IP:5000/qj52lajx/download`
- `key` 字段必须与 admin_config.json 中的 `auth_key` 一致（首启自动生成，见启动日志；管理网页可热更新），`user`/`password` 必须为已创建的用户（管理员或 `userctl add` 创建的下载用户）及其密码，三者均正确才能通过认证，否则返回 403
- 支持直接视频链接（mp4、mkv、ts、flv、f4v、avi、webm、mov、wmv 等），自动使用 curl 下载；`.f4v` 下载完成后自动改名为 `.mp4`；路径无扩展名的下载页链接（如 `?dl_id=xxx`）也能通过响应头/内容嗅探自动识别，返回 JSON 调度响应的链接会自动解析真实地址后下载，详见[直链视频下载](#直链视频下载与-f4v-支持)

### 猫抓内置变量对照

请求体中以 `${xxx}` 形式出现的占位符由猫抓插件在发送时自动替换为实际值，服务端无需也无法解析这些变量：

| 变量           | 含义                            | 用途                               |
| -------------- | ------------------------------- | ---------------------------------- |
| `${url}`       | 当前资源的下载链接（m3u8/直链） | 填入 `url` 字段，**必填**          |
| `${title}`     | 资源标题（来自页面/文件名）     | 填入 `saveName`                    |
| `${now}`       | 当前时间戳（毫秒）              | 建议默认拼接到 `saveName` 后防重名 |
| `${referer}`   | 来源页面地址                    | 填入 `referer`，部分站点必需       |
| `${cookie}`    | 浏览器 Cookie                   | 填入 `cookie`，部分站点必需        |
| `${userAgent}` | 浏览器 User-Agent               | 填入 `userAgent`，按需             |

> - `key`、`user`、`password` 三个认证字段**不是**猫抓变量，需在猫抓「数据发送」配置中手动填写真实值。
> - `${now}` 为毫秒级时间戳，如 `1672329448871`。`saveName` 建议默认写作 `${title}_${now}`，避免同一网页多个视频同名而只下载到一个。

## 🖥️ 网页控制台

服务内置三个零依赖的单文件网页，浏览器直接访问即可：

| 页面       | 地址（前缀以 `qj52lajx` 为例）               | 说明                           |
| ---------- | -------------------------------------------- | ------------------------------ |
| 登录页     | `http://你的容器IP:5000/qj52lajx/login.html` | 统一入口，登录后按角色自动跳转 |
| 下载控制台 | `http://你的容器IP:5000/qj52lajx/user.html`  | 普通用户页面                   |
| 管理控制台 | `http://你的容器IP:5000/qj52lajx/admin.html` | 管理员页面                     |

> **旧地址兼容（302 跳转）**：`/{prefix}`、`/{prefix}/`、`/index.html`、`/login`、`/login/`、`/user`、`/user/`、`/admin`、`/admin/`、`/admin/index.html` 在浏览器打开时都会 302 跳转到对应的 `.html` 规范地址。此跳转仅作用于 GET 网页访问；`POST /{prefix}/login` 等 API 路径不受影响。

- **登录**：输入 `AUTH_KEY`（admin_config.json 的 `auth_key`，首启自动生成）与用户名/密码，换取 2 小时有效期的访问令牌；登录响应返回用户角色，**管理员自动跳转到管理控制台**，普通用户进入下载控制台；浏览器仅保存令牌与用户名（明文密钥/密码不落盘），「退出」会吊销服务端令牌并回到登录页，令牌过期后需重新登录
- **新建下载**（下载控制台）：粘贴视频 URL、填写保存文件名（选填）、选择输出格式（MP4/MKV，默认 MP4），支持折叠的高级选项（Referer / Cookie / User-Agent）
- **任务列表**：每 3 秒自动刷新，仅显示**当前登录用户自己的任务**；显示文件名、状态徽章（收集中 / 下载中 / 已暂停）、进度条；点击任务可弹出详情（任务 ID、全部链接、重试次数等），可暂停 / 继续 / 删除任务；任务完成（成功或失败）后自动从列表移除
- **用户菜单**（右上角）：修改密码（旧密码 1 遍 + 新密码 2 遍，成功后全部令牌吊销并回到登录页）、过滤规则编辑、主题切换、退出
- **猫抓配置弹窗**：一键查看当前前缀对应的猫抓发送地址与请求体模板（含 `key`/`user`/`password`/`format` 占位）
- 页面均为纯静态外壳（不含任何敏感信息），所有数据操作均在 `Authorization: Bearer` 请求头中携带访问令牌调用 API

## 🛠️ 管理控制台

管理员账户登录后自动进入独立的管理网页（不含任何下载功能，管理员账户不能提交下载任务）：

- **用户管理**：查看全部用户（用户名/角色/状态/创建时间）、添加下载用户、删除用户（确认弹窗明确提示配置目录、下载缓存、成品文件将全部删除且不可恢复）、重置用户密码、禁用（ban）/解禁（unban）用户；被禁用用户立即无法登录且已签发令牌全部失效，禁用状态下即使密码正确也返回 403 且不计入 IP 封禁
- **AUTH_KEY 热更新**：在「服务器配置」中点击「🎲 随机」自动生成新 KEY（**输入框只读，不支持手填**；密钥固定 14 位，含至少 1 个大写字母、1 个小写字母、1 个数字和 1-3 个符号，使用浏览器密码学随机源生成），保存后立即写回 admin_config.json 并生效，**包括管理员在内的所有用户令牌全部吊销**（全员强制重新登录）；之后把新 KEY 通知各用户即可，用户密码无需改动；猫抓插件请求体中的 `key` 也需同步更换
- **过滤规则模板**：编辑全局过滤规则模板（config/filter_rules.json），保存即时生效；**新用户**首次使用时自动复制一份作为个人规则，已有用户的个人规则不受影响
- **修改密码**：管理员修改自己的密码（同网页菜单「修改密码」）
- **命令行参考**：页面内附 `adminctl` / `userctl` / `banip` 全部命令速查
- **管理员账户增删**：管理网页不提供入口，仅通过容器内 `adminctl` CLI 完成（见命令行工具章节），至少保留一个管理员；管理控制台固定墨绿亮色主题，无主题切换

## 📡 API 接口

> 注意：**所有接口路径均需要添加 URL 前缀**（如 `/qj52lajx`），未带前缀的请求返回 `404 Not Found`。网页页面（`/login.html`、`/user.html`、`/admin.html` 三个规范地址，旧地址 302 跳转）与 `favicon.ico`、`/health` 为公开静态资源；其余 API 均需认证，**推荐使用访问令牌（Bearer Token）**：先调用 `POST /{prefix}/login` 用 `key`/`user`/`password`（请求体）换取 2 小时有效期的短期令牌，后续请求在 `Authorization: Bearer <token>` 请求头中携带令牌即可。**凭证不通过 URL 查询参数传递**（URL 会进入浏览器历史与各级访问日志，存在泄露风险）。POST 接口同时兼容请求体传 `key`/`user`/`password`（如猫抓插件等第三方调用方）。

| 接口                             | 方法     | 说明                                                                                                               | 认证          |
| -------------------------------- | -------- | ------------------------------------------------------------------------------------------------------------------ | ------------- |
| `/{prefix}/login.html`           | GET      | 登录页（纯静态外壳）；`/`、`/index.html`、`/login`、`/login/` 302 跳转到此                                         | 公开          |
| `/{prefix}/user.html`            | GET      | 下载控制台页面；`/user`、`/user/` 302 跳转到此                                                                     | 公开          |
| `/{prefix}/admin.html`           | GET      | 管理控制台页面（纯静态外壳，无下载功能；页内 API 需管理员）；`/admin`、`/admin/`、`/admin/index.html` 302 跳转到此 | 公开          |
| `/{prefix}/health`               | GET      | 健康检查                                                                                                           | 否            |
| `/{prefix}/login`                | POST     | 登录并签发访问令牌（有效期 2 小时）                                                                                | 两层凭证      |
| `/{prefix}/logout`               | POST     | 退出并吊销当前访问令牌                                                                                             | 令牌          |
| `/{prefix}/password`             | POST     | 修改自己的密码（旧密码 + 新密码，成功后该用户令牌全部吊销）                                                        | 令牌          |
| `/{prefix}/config`               | GET      | 获取运行配置摘要（端口/前缀/开关/用户数，AUTH_KEY 脱敏）                                                           | 令牌          |
| `/{prefix}/download`             | POST     | 添加下载任务（仅下载用户，管理员不可下载）                                                                         | 令牌/两层凭证 |
| `/{prefix}/tasks`                | GET      | 获取当前用户的任务（按登录用户过滤）                                                                               | 令牌          |
| `/{prefix}/tasks/{id}`           | GET      | 获取任务详情（非本人任务返回 404）                                                                                 | 令牌          |
| `/{prefix}/task/pause`           | POST     | 暂停下载任务（进度保留）                                                                                           | 令牌/两层凭证 |
| `/{prefix}/task/resume`          | POST     | 继续暂停的任务                                                                                                     | 令牌/两层凭证 |
| `/{prefix}/task/delete`          | POST     | 删除任务（同时删除已下载文件）                                                                                     | 令牌/两层凭证 |
| `/{prefix}/filters`              | GET      | 获取自己的过滤规则                                                                                                 | 令牌          |
| `/{prefix}/filters`              | POST     | 保存自己的过滤规则（keywords/filename_filter/filename_dedup 三段，即时生效）                                       | 令牌          |
| `/{prefix}/admin/users`          | GET      | 获取全部用户列表（角色/状态/创建时间）                                                                             | 管理员        |
| `/{prefix}/admin/users/add`      | POST     | 添加下载用户                                                                                                       | 管理员        |
| `/{prefix}/admin/users/delete`   | POST     | 删除下载用户（连同其配置/缓存/成品三个目录）                                                                       | 管理员        |
| `/{prefix}/admin/users/password` | POST     | 重置下载用户密码                                                                                                   | 管理员        |
| `/{prefix}/admin/users/ban`      | POST     | 禁用用户（令牌立即失效）                                                                                           | 管理员        |
| `/{prefix}/admin/users/unban`    | POST     | 解禁用户                                                                                                           | 管理员        |
| `/{prefix}/admin/auth-key`       | POST     | 热更新 AUTH_KEY（全员令牌吊销；`newKey` ≥8 位，管理网页仅支持「🎲 随机」生成 14 位）                               | 管理员        |
| `/{prefix}/admin/filters`        | GET/POST | 获取/保存全局过滤规则模板（新用户首次使用复制）                                                                    | 管理员        |
| `/{prefix}/reload`               | POST     | 重新加载 admin_config.json 与全局过滤模板（auth_key 变更则全员令牌失效）                                           | 管理员        |

> 示例：如果 `URL_PREFIX` 设置为 `qj52lajx`，则完整路径为 `/qj52lajx/download`

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
  "password": "<你的password>",
  "format": "mp4"
}
```

| 参数        | 类型   | 必填 | 默认值              | 说明                                                                                                                                                                                     |
| ----------- | ------ | ---- | ------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `url`       | string | 是   | —                   | m3u8 视频链接或直接视频链接（mp4/mkv/ts/flv/f4v/avi/webm/mov/wmv 等直链自动用 curl；`.f4v` 下载后自动改名为 `.mp4`；无扩展名链接自动嗅探类型；返回 JSON 调度响应的链接自动解析真实地址） |
| `saveName`  | string | 否   | `download_<任务ID>` | 保存文件名（不含扩展名，扩展名由输出格式决定）。猫抓请求体建议用 `${title}_${now}` 追加时间戳，避免同网页多视频同名只下载一个                                                            |
| `format`    | string | 否   | `mp4`               | 逐任务输出格式：`mp4` 或 `mkv`；网页新建任务时下拉选择，猫抓请求体可固定写 `mp4`                                                                                                         |
| `referer`   | string | 否   | 空                  | 来源页面地址，部分站点下载必需                                                                                                                                                           |
| `cookie`    | string | 否   | 空                  | 认证 Cookie，部分站点下载必需                                                                                                                                                            |
| `userAgent` | string | 否   | 空                  | 自定义 User-Agent                                                                                                                                                                        |
| `key`       | string | 是\* | —                   | 第一层认证：须与 admin_config.json 中的 `auth_key` 一致（首启随机生成，管理网页可热更新）；字段名也接受 `auth_key`                                                                       |
| `user`      | string | 是\* | —                   | 用户名：`userctl add` 创建的下载用户（管理员不能提交下载任务）；下载文件存入该用户隔离目录                                                                                               |
| `password`  | string | 是\* | —                   | 第二层认证：该用户创建/修改时设置的密码，可用 `userctl password` 修改（改后该用户全部令牌失效）；被禁用用户无法通过认证                                                                  |

> **认证字段说明**：标 `是*` 的三个字段在使用 `Authorization: Bearer <token>` 令牌调用时可全部省略（令牌通过 `POST /{prefix}/login` 换取）；猫抓插件等第三方调用方仍通过请求体传递。

> **saveName 说明**：
>
> - 建议默认写成 `"saveName": "${title}_${now}"`（标题 + 毫秒时间戳）：同一网页有多个视频时标题往往相同，追加时间戳可避免被文件名去重/同视频合并逻辑当作同一个视频而只下载到一个。
> - 如希望同一视频的多条不同链接（多 CDN / 多清晰度）自动合并为一个任务下载，可只传标题 `"saveName": "${title}"`，不加时间戳。
> - `_${now}` 会被猫抓替换为毫秒时间戳（如 `1672329448871`）。
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

### POST /{prefix}/login

登录接口：请求体提交 `key`（或 `auth_key`）/`user`/`password`，两层认证通过后签发短期访问令牌（有效期 2 小时）。

```json
{
  "key": "<你的AUTH_KEY>",
  "user": "<用户名>",
  "password": "<用户密码>"
}
```

响应（成功）：

```json
{
  "success": true,
  "data": {
    "token": "<访问令牌>",
    "role": "admin 或 user",
    "expiresIn": 7200
  }
}
```

> 被禁用用户即使密码正确也返回 403「账号已被禁用」，且**不计入**封禁计数。

> **注意（分级封禁）**：
>
> - **AUTH_KEY 错误 / 用户不存在**：计入 **IP 级**失败计数——10 分钟内累计 10 次首次触发临时封禁 30 分钟（到期自动解封），解封后再次触发升级为永久封禁（仅 `banip del` 可解除）。
> - **用户存在但密码错误**：计入该**账号级**失败计数——10 分钟内累计 5 次自动禁用该账号（提示剩余次数），需管理员解禁或重置密码。
> - 已封禁/禁用账号继续尝试登录时，首次仅警告，再次尝试将直接封禁来源 IP。
> - 认证成功会清零该 IP 与该账号的失败计数；账号禁用导致的 403 不计入。

### POST /{prefix}/logout

注销接口：在请求头携带 `Authorization: Bearer <token>`，服务端将该令牌立即吊销（`data.db` 的 `auth_tokens` 表置 `revoked`），被吊销的令牌在所有设备上即刻失效。

```bash
curl -X POST -H "Authorization: Bearer <token>" http://容器IP:5000/{prefix}/logout
```

> **吊销机制**：令牌签名依赖 AUTH_KEY 且签发时登记唯一 `jti` 到 `auth_tokens` 表，每次业务请求校验签名与吊销状态。除网页「注销」外，以下操作也会批量作废令牌：`userctl password` 修改密码、禁用用户（`userctl ban` / 管理网页）、删除用户（防止重建同名用户后旧令牌复活）——该用户全部令牌失效；管理网页热更新 AUTH_KEY 或管理员执行 `/reload` 导致 KEY 变化——**全员**令牌失效（签名同时失效，双保险）。已过期的登记行会在下次签发令牌时自动清理。

### GET /{prefix}/tasks

在请求头携带访问令牌：`Authorization: Bearer <token>`

```bash
curl -H "Authorization: Bearer <token>" http://容器IP:5000/{prefix}/tasks
```

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

在请求头携带访问令牌：`Authorization: Bearer <token>`

```bash
curl -H "Authorization: Bearer <token>" http://容器IP:5000/{prefix}/tasks/{id}
```

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

重新加载配置文件，无需重启容器。**仅管理员可用**（推荐管理网页「重载配置」按钮，或携带管理员令牌）：

```bash
curl -X POST -H "Authorization: Bearer <管理员令牌>" http://容器IP:5000/{prefix}/reload
```

响应：

```json
{
  "success": true,
  "message": "配置已重新加载"
}
```

> 重载内容：admin_config.json（`auth_key`）与全局过滤规则模板 config/filter_rules.json，并重连 data.db。若重载后 `auth_key` 发生变化（文件被外部修改），全员令牌会被自动吊销，需用新 KEY 重新登录。系统级 config.json 不随 `/reload` 重载，任何修改需重启容器后生效。日常使用中管理网页的保存操作本身即时生效，通常无需手动调用本接口。

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
      - /youdir/config:/home/downloader/config
      - /youdir/user:/home/downloader/user
      - /youdir/temp:/home/downloader/temp
      - /youdir/downloads:/home/downloader/downloads
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
      - URL_PREFIX=qj52lajx # 🔒 必须设置：URL路径前缀
      - SSRF_PROTECTION=true # 🛡️ SSRF防护开关
      - MAX_CONCURRENT_TASKS=20 # 📊 最大并发任务数
      # - API_PORT=8080                        # 可选：覆盖容器内监听端口
```

> 四个挂载卷缺一不可：`config`（配置与 data.db）、`user`（每用户任务/日志/个人过滤规则）、`temp`（下载缓存分片）、`downloads`（成品视频）。重建容器（`up -d --build` / 换新镜像）后数据全部保留。

### 环境变量

| 变量名                 | 说明                                    | 默认值 | 是否必填 |
| ---------------------- | --------------------------------------- | ------ | -------- |
| `API_PORT`             | 覆盖配置文件中的端口设置                | 8080   | 否       |
| `URL_PREFIX`           | URL 路径前缀（所有接口必须）            | 空     | **是**   |
| `SSRF_PROTECTION`      | SSRF 防护开关，`false` 允许内网地址下载 | true   | 否       |
| `MAX_CONCURRENT_TASKS` | 最大并发下载任务数                      | 20     | 否       |

> **配置位置**：`URL_PREFIX` 仅通过环境变量设置（保证生产访问地址恒定，未设置时程序拒绝启动）；`AUTH_KEY` 保存在 admin_config.json 的 `auth_key` 字段（首启自动随机生成，管理网页可热更新，无需重启容器）。
>
> **两层认证**：系统采用两层认证机制——第一层 `AUTH_KEY`（admin_config.json，管理网页热更新后全员重新登录），第二层用户名+密码（管理员或 `userctl add` 创建的用户，密码可用 `userctl password` 修改，改后该用户全部令牌失效）。推荐先调用 `POST /{prefix}/login` 换取访问令牌，业务接口在 `Authorization: Bearer <token>` 请求头携带令牌即可；POST 接口同时兼容请求体传 `key`/`user`/`password`（猫抓插件等第三方调用方）。

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

### 健康检查接口

服务提供 `GET /{prefix}/health` 健康检查接口（需包含 URL 前缀，无需认证），返回 `{"success": true, "status": "ok"}`。可用于外部监控、反熔探针或自行在 compose 中配置 `healthcheck`：

```yaml
healthcheck:
  test: ["CMD", "curl", "-f", "http://localhost:8080/qj52lajx/health"]
  interval: 30s
  timeout: 10s
  retries: 3
  start_period: 60s # 启动阶段含网络就绪检测，建议宽限 ≥ 1 分钟
```

## 📋 任务持久化

容器支持任务列表自动保存和重启恢复功能，确保正在下载的任务不会因容器重启而丢失。

### 工作原理

1. **自动保存**：每次任务状态变更时，任务列表按用户自动保存到各自的 `user/<用户名>/tasks.json`（含 `running`/`collecting`/`paused` 等未完成任务，2 秒节流、关键节点强制落盘）
2. **重启恢复**：容器启动时扫描 `user/` 加载全部用户的 `tasks.json`，恢复所有未完成任务（含暂停状态）
3. **断点保留**：恢复时仅清理缓存目录中陈旧的 `.tmp` 锁文件；m3u8 分片（`.m4s/.ts` 等）与直链断点文件**保留**供工具续传，无法续传时自动重下，不会误删成品
4. **任务删除**：任务完成或失败后立即从内存与 `tasks.json` 同步清除（该用户最后一个任务结束时文件回写为空列表）
5. **下载日志**：完成/失败的任务记录到该用户的 `success.log` / `failure.log`，用于防止重复下载
6. **失败日志重置**：容器启动时自动清空各用户 `failure.log`，允许重新下载之前失败的 URL

### tasks.json 文件

任务列表按用户隔离，位于 `user` 挂载卷下：

```
/youdir/user/<用户名>/tasks.json
```

文件格式：

```json
[
  {
    "id": "abc12345",
    "urls": ["https://example.com/stream.m3u8"],
    "save_name": "我的视频",
    "status": "running",
    "progress": 45,
    "user": "alice"
  }
]
```

> 同视频模式下 `urls` 可能包含多个链接。同目录下还有该用户的 `success.log`、`failure.log`、`filter_rules.json`。

### 任务状态说明

> **注意**：任务完成或失败后会立即从 tasks.json 中删除，文件中只包含尚未结束的任务。

| 状态         | 说明                                  |
| ------------ | ------------------------------------- |
| `running`    | 正在下载中                            |
| `collecting` | 正在收集视频信息（任务初始阶段）      |
| `paused`     | 已暂停（断点保留，重启/点继续后续传） |

### 恢复机制

当容器重启/重建时（任务 ID 保持不变，不生成新 ID）：

1. 扫描 `user/<用户名>/tasks.json` 加载未完成任务
2. 检测所有状态为 `running` 或 `paused` 的任务（暂停任务重启后自动继续）
3. 检查 URL 是否已在该用户日志中记录（已成功/失败 → 直接清除残留任务记录，不重复写日志）
4. 检查 downloads 目录是否已存在完整成品（≥ 100KB 的 mp4/mkv）→ 任务收尾
5. 检查是否存在未转换的源文件（`.ts` / `.mux.mp4` / 直链下载后未改名的 `.f4v`）→ 自动补转换/补改名
6. 清理缓存目录中陈旧的 `.tmp` 文件（分片保留）
7. 直链视频（.mp4/.ts/.f4v 等）若已有小体积不完整文件 → curl `-C -` 断点续传；m3u8 → 重新拉起 N_m3u8DL-RE 续传

### 重复下载防护

按用户隔离，通过以下优先级检测重复下载：

1. **下载历史**：检查该用户 `success.log` 和 `failure.log`（最近 300 条记录）
2. **任务列表**：检查当前正在运行的任务
3. **已存在视频**：检查该用户 downloads 目录中是否已存在完整视频文件
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

### 直链视频下载与 f4v 支持

直链视频使用 curl 下载（`-L -C -` 跟随跳转、断点续传），支持以下扩展名：

```
.mp4  .mkv  .ts  .flv  .f4v  .avi  .webm  .mov  .wmv
```

- **普通直链**（mp4/mkv/ts/flv 等）：下载完成即成品，扩展名保持不变。
- **`.f4v` 直链**：`.f4v` 是 Adobe 碎片化 MP4 容器（ISO BMFF，文件头 `ftypf4v`），本身就是 MP4 容器，多数播放器不认识 `.f4v` 扩展名。因此 curl 下载完成后**直接改名为 `.mp4`** 即可正常播放（不重新编码、不调用 ffmpeg，秒级完成），中间 `.f4v` 文件自动删除；容器重启后发现残留未改名的 `.f4v` 源文件也会自动补改名。
  - 极少数站点的 `.f4v` 链接实际内容为 FLV 封装（文件头 `FLV`）：此时自动改用 ffmpeg `-c copy` 无损转封装为 `.mp4`；转封装失败则兜底改名 `.flv` 保留，不丢失已下载数据。
- **无扩展名链接自动嗅探**：部分下载链接路径本身没有视频扩展名（如下载页跳转 `https://www.samplefiles.org/?dl_id=295`，真实文件名在 `Content-Disposition: attachment; filename="xxx.f4v"` 响应头中）。新建任务时会先发一次轻量探测请求（只取前 64KB），按 **内容魔数（`ftyp`/`FLV`/`#EXTM3U` 等）→ Content-Disposition 文件名 → Content-Type** 的顺序判定真实类型：识别为直链视频则走 curl 下载，识别为 m3u8 播放列表则走 N_m3u8DL-RE，无法判定时按原 m3u8 流程处理；HTML 网页等非媒体内容不会被误判。
- **CDN 调度链接自动解析**：个别站点的媒体链接返回的不是视频本身，而是一小段 JSON 调度响应（如 `{"l": "https://真实CDN节点/xxx.f4v?...", "e": "0"}`）。下载后若发现文件过小（< 64KB）且内容为 JSON，会自动解析 `l`（兼容 `url`）字段中的真实地址，删除小文件后重新下载：真实地址必须通过 SSRF 校验（禁止内网/回环地址），最多跟随 3 跳且**不消耗**重试次数；任务记录与下载日志始终保存用户提交的原始链接用于去重。

## 🔍 过滤规则

容器支持三套相互独立的过滤机制，各有自己的 `enabled` 开关：

| 机制                            | 作用                                                        |
| ------------------------------- | ----------------------------------------------------------- |
| `keywords`（拦截关键字）        | 文件名或 URL 命中关键字时**整个下载请求被拦截**（屏蔽广告） |
| `filename_filter`（文件名过滤） | 下载时从文件名中**删除**指定关键字（不拦截下载）            |
| `filename_dedup`（文件名去重）  | 用正则 + 段级去重清理文件名中重复的段（不拦截下载）         |

### 规则存放与编辑方式

- **每用户规则**：`user/<用户名>/filter_rules.json`。用户在下载控制台右上角菜单「**过滤规则**」中自助编辑（关键字 chips 增删、三套开关、正则保存前前端校验合法性），**保存即时生效**，无需重启或 reload。
- **全局模板**：`config/filter_rules.json`（镜像内置默认模板，首启复制到挂载卷）。管理员在管理控制台菜单「**过滤模板**」中编辑；**新用户**首次使用时自动复制一份作为其个人规则，已有用户的个人规则不受影响。
- 默认情况下关键字列表为空，即不执行任何拦截/过滤。

> 以下章节的 JSON 结构、正则语法与示例同时适用于全局模板和每用户规则（文件结构完全一致）。

### 配置文件参考（系统级 config.json）

`config` 挂载卷中的系统级与管理员配置：

| 文件                | 用途                                                      |
| ------------------- | --------------------------------------------------------- |
| `config.json`       | 系统级配置：端口、调试开关、同视频模式（重启容器生效）    |
| `admin_config.json` | 管理员热配置：`auth_key` 认证密钥（管理网页修改即时生效） |
| `filter_rules.json` | 全局过滤规则模板（新用户复制，管理员网页编辑）            |

#### 步骤 1：创建 config 目录

```bash
mkdir -p /youdir/config
```

#### 步骤 2：创建 config.json（系统级配置）

```bash
cat > /youdir/config/config.json << 'EOF'
{
  "port": 8080,
  "debug": false,
  "same_video_by_filename": false
}
EOF
```

> SSRF 开关与并发数优先由环境变量 `SSRF_PROTECTION` / `MAX_CONCURRENT_TASKS` 控制；不设置时使用内置默认值（开启 / 20）。

#### 步骤 3：创建 admin_config.json（管理员热配置）

```bash
cat > /youdir/config/admin_config.json << 'EOF'
{
  "auth_key": "CHANGE_ME"
}
EOF
```

> `auth_key` 可省略或保留 `CHANGE_ME` 占位符——首次启动时程序会自动生成随机密钥并写回文件，启动日志中可见；之后建议在管理网页中修改（热更新，无需重启容器）。

#### 步骤 4：创建 filter_rules.json（全局模板）

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

#### 步骤 5：修改 docker-compose.yml 添加挂载

```yaml
volumes:
  - /youdir/config:/home/downloader/config
  - /youdir/user:/home/downloader/user
  - /youdir/temp:/home/downloader/temp
  - /youdir/downloads:/home/downloader/downloads
```

#### 步骤 6：重启容器

```bash
docker-compose up -d --build
```

### config.json 参数说明（系统级，重启容器生效）

| 参数                     | 说明                                                 | 默认值 |
| ------------------------ | ---------------------------------------------------- | ------ |
| `port`                   | 服务监听端口，可被环境变量 `API_PORT` 覆盖           | 8080   |
| `debug`                  | 是否启用调试模式，开启后会输出详细日志               | false  |
| `same_video_by_filename` | 是否启用同视频模式（按文件名聚合多链接轮流下载）     | false  |
| `ssrf_protection`        | 是否启用 SSRF 防护（拦截内网地址），可被环境变量覆盖 | true   |
| `max_concurrent_tasks`   | 最大并发下载任务数，可被环境变量覆盖                 | 20     |

### admin_config.json 参数说明（管理员热配置，即时生效）

| 参数       | 说明                                                                                      | 默认值   |
| ---------- | ----------------------------------------------------------------------------------------- | -------- |
| `auth_key` | 第一层认证密钥：留空或 `CHANGE_ME` 时首启自动随机生成并写回；管理网页热更新后全员令牌失效 | 随机生成 |

> ⚠️ 配置分层：`auth_key` 存于 admin_config.json（管理网页可热更新），普通管理员无权修改 config.json；`url_prefix` 不在配置文件中，仅通过 Docker 环境变量 `URL_PREFIX` 注入，保证生产访问地址恒定。输出格式（mp4/mkv）为逐任务参数（下载请求 `format` 字段 / 网页下拉框），不属于全局配置。

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

### 输出格式

输出格式为**逐任务**参数，不是全局配置：

| 格式  | 说明                                         |
| ----- | -------------------------------------------- |
| `mp4` | MP4 格式，兼容性好，适合大多数播放器（默认） |
| `mkv` | MKV 格式，支持更多音轨和字幕                 |

- 网页新建下载时通过格式下拉框选择；猫抓插件可在请求体中固定加 `"format": "mp4"`（或 `"mkv"`）
- 不传 `format` 字段时默认 `mp4`；仅对当前任务生效，不影响其他任务

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

## 🧰 容器内命令行工具

### adminctl — 管理员账户管理

```bash
docker exec -it catdock adminctl add <用户名>        # 创建管理员（交互式输入密码）
docker exec -it catdock adminctl password <用户名>   # 重置管理员密码（该账户全部令牌失效）
docker exec -it catdock adminctl del <用户名>        # 删除管理员（至少保留一个管理员）
docker exec -it catdock adminctl list                # 列出全部用户（用户名/角色/状态/创建时间）
```

- 首启自动创建默认管理员 `admin`（14 位随机初始密码，仅在启动日志显示一次，请尽快登录修改）
- 管理员账户只能通过本 CLI 增删（管理网页不提供入口）；非管理员账户使用本命令会报错并提示改用 `userctl`

### userctl — 下载用户管理

```bash
docker exec -it catdock userctl add <用户名>        # 创建下载用户（交互式输入密码）
docker exec -it catdock userctl password <用户名>   # 修改密码（该用户全部访问令牌立即失效）
docker exec -it catdock userctl del <用户名>        # 删除用户（配置/缓存/成品三个目录一并删除）
docker exec -it catdock userctl ban <用户名>        # 禁用用户（无法登录，已有令牌立即失效）
docker exec -it catdock userctl unban <用户名>      # 解禁用户
```

- 用户名规则：仅字母+数字、不能为纯数字、字母字符不少于 4 位
- `ban`/`unban` 为可逆禁用：被禁用户密码正确时返回 403「账号已被禁用」，且**不计入**封禁失败计数
- `ban`/`del`/`password` 不能作用于管理员账户（请改用 `adminctl` 命令）；下载用户可全部删除
- 以上操作也可在管理网页 `/{prefix}/admin.html` 中完成（管理员增删除外）

### banip — IP 封禁管理

```bash
docker exec -it catdock banip show                 # 查看封禁列表（区分临时/永久/手动）
docker exec -it catdock banip add <IP地址>         # 手动封禁（永久，需 banip del 解除）
docker exec -it catdock banip del <IP地址>         # 解封（同时清零失败计数与阶梯升级计数）
```

自动封禁为分级机制（计数窗口均为 10 分钟）：

- **IP 级**（AUTH_KEY 错误、用户不存在、无效令牌）：累计 **10** 次 → 第 1 次触发临时封禁 30 分钟（`自动封禁(临时)`，到期自动解封并清零计数），解封后再次触发升级为永久封禁（`自动封禁(永久)`，仅 `banip del` 可解除）
- **账号级**（用户存在但密码错误）：累计 **5** 次 → 自动禁用该账号（需 `userctl unban` / 管理网页解禁或重置密码）
- URL 前缀错误返回 404 **不**计数；账号已禁用导致的 403 不计数；认证成功自动清零该 IP 与该账号的计数

## 🛠️ 故障排查

### 断电/宿主机重启后容器无法下载

catdock 已针对断电重启场景做了特殊处理：

1. **自动清空失败日志**：容器启动时会自动清空各用户的 `user/<用户名>/failure.log`，允许重新下载之前失败的 URL
2. **恢复未完成任务**：通过各用户的 `user/<用户名>/tasks.json` 自动恢复断电前正在下载的任务（分片保留、断点续传）
3. **网络就绪检测**：容器启动前会主动检测网络，避免在网络未就绪时盲目下载
4. **下载重试机制**：下载过程中如遇网络中断会自动重试

如果断电后仍然无法下载，建议：

```bash
# 1. 查看启动日志，确认网络检测和失败日志清空是否正常
docker logs --tail 50 catdock

# 2. 重启容器（会触发上述全部恢复流程）
docker-compose restart catdock

# 3. 若仍无改善，清空对应用户的 tasks.json 后再重启（<用户名> 替换为实际用户名）
rm /youdir/user/<用户名>/tasks.json
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
  - 223.5.5.5 # 阿里 DNS
  - 223.6.6.6 # 阿里 DNS 备用
  - 114.114.114.114 # 114 DNS
  - 119.29.29.29 # 腾讯 DNS
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

- **令牌方式（Bearer）**：确认令牌未过期（2 小时有效期）且未被吊销（注销/改密码/删用户/禁用用户/更换 AUTH_KEY 后全部失效），过期或失效后重新调用 `POST /{prefix}/login` 获取
- **第一层（key）**：确认请求体的 `key` 与 admin_config.json 中当前 `auth_key` 一致（查看管理网页「服务器配置」或启动日志；管理员可在管理网页热更新）
- **第二层（user/password）**：确认 `user` 为已创建的用户（管理员或 `userctl add` 创建的下载用户），`password` 为该用户创建/修改时设置的密码
- **账号被禁用**：返回「账号已被禁用」时联系管理员解禁（`userctl unban` 或管理网页）；可能是管理员手动封禁，也可能是 10 分钟内密码错误 5 次触发的账号级自动禁用。此类 403 不计入 IP 封禁计数
- **需要管理员权限**：管理接口（`/admin/*`、`/reload`）仅管理员可用，普通用户调用返回 403

### 健康检查接口访问不到

- 确认端口映射 `5000:8080` 未被占用
- 确认容器内服务已正常启动（查看 `docker logs catdock`）
- 容器启动时会等待网络就绪，最长 10 分钟内才会开始启动 API

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
4. **配置修改**：每用户过滤规则在网页「过滤规则」中编辑后立即生效，无需重载；管理员修改全局过滤模板（`config/filter_rules.json`）或手工改了 `admin_config.json` 后，可通过 `POST /{prefix}/reload` 接口或管理网页「重载配置」热加载（auth_key 也可直接在管理网页「服务器配置」修改，立即生效并全员重新登录）；系统级 `config.json` 不随 reload 生效，任何修改需重启容器
5. **环境变量修改**：修改 `URL_PREFIX` 等环境变量需要 `docker-compose up -d` 重新创建容器（`URL_PREFIX` 变更会改变访问地址，故不建议生产环境变动）
6. **文件格式**：下载完成后自动封装为 MP4 或 MKV，格式逐任务选择（网页下拉框 / 请求体 `format` 字段，默认 MP4）
7. **URL 前缀**：`URL_PREFIX` 为必填项，所有 API 接口（含健康检查）路径都必须添加前缀，未带前缀返回 404
8. **两层认证 + 用户 + 令牌**：`AUTH_KEY`（admin_config.json 的 `auth_key` 字段，首启随机生成、管理网页可热更新）与用户名/密码（管理员或 `userctl add` 创建的用户）均为必填。先调用 `POST /{prefix}/login`（请求体传 `key`/`user`/`password`）换取 2 小时有效期的访问令牌，业务接口在 `Authorization: Bearer <token>` 请求头携带令牌；POST 接口同时兼容请求体传 `key`/`user`/`password`（猫抓插件等第三方）。凭证不支持通过 URL 查询参数传递，否则返回 403
9. **任务持久化**：任务列表按用户自动保存到 `user/<用户名>/tasks.json`，容器重启后自动恢复未完成任务（分片保留续传）
10. **重复下载**：同一用户的同一 URL 不会重复下载（按用户隔离检测下载历史和已存在文件；不同用户互不影响）
11. **调试模式**：开启 `debug: true` 可查看详细日志，便于排查问题
12. **时区**：容器内所有日志和时间统一使用北京时间（UTC+8 / Asia/Shanghai）
13. **SSRF 防护**：默认启用，拦截内网地址下载；如需下载内网/Docker 网络资源，设置 `SSRF_PROTECTION=false`
14. **速率限制**：每 IP 60 秒内最多 60 次请求，超限返回 429
15. **并发限制**：默认最多 20 个并发下载任务，超限返回 429

## ❓ 常见问题 FAQ

**Q: 为什么断电重启电脑后容器会卡在等待网络就绪？**
A: 宿主机断电重启后网络服务需要一定时间初始化，容器会主动检测网络状态避免在网络未就绪时盲目下载。最长等待 10 分钟，超时后仍会启动服务。

**Q: AUTH_KEY 在哪里配置？可以随时修改吗？**
A: `AUTH_KEY` 保存在 admin_config.json 的 `auth_key` 字段：首次启动若为空或 `CHANGE_ME` 会自动随机生成并写回文件，同时在启动日志打印一次。修改方式：管理员登录管理网页 `/{prefix}/admin.html`，在「服务器配置」中填写新 KEY（至少 8 位，可随机生成）并保存，立即写回 admin_config.json 并生效——**包括管理员在内全员令牌吊销**，所有用户用新 KEY 重新登录即可，用户密码无需改动、无需重启容器。`URL_PREFIX` 仍仅通过环境变量配置以保证访问地址恒定。用户密码（第二层认证）通过 `userctl add/password` 或管理网页管理；管理员账户通过 `adminctl` CLI 管理。

**Q: 默认管理员账户是什么？**
A: 首次启动自动创建管理员 `admin`，密码为 14 位随机字符串，仅在启动日志显示一次（`docker logs catdock`）。请妥善保存并尽快登录管理网页修改；管理员登录后自动进入管理控制台，可添加/删除下载用户、重置密码、禁用用户、热更新 AUTH_KEY、编辑全局过滤模板。管理员账户的增删需在容器内用 `adminctl add/del/password/list` 命令操作。

**Q: 如何禁止某个用户登录？**
A: 管理员在管理网页对该用户点「禁用」，或在容器内执行 `userctl ban <用户名>`：该用户已签发令牌立即失效，之后即使密码正确也返回 403「账号已被禁用」（不计入 IP 封禁）；`userctl unban <用户名>` 或网页「解禁」可恢复。注意账号级自动封禁（10 分钟内密码错误 5 次）同样进入禁用状态，解禁方式相同。

**Q: 如何修改输出格式？**
A: 输出格式是逐任务参数，没有全局开关：网页新建下载时在格式下拉框选择 MP4/MKV；猫抓等 API 调用在请求体中加 `"format": "mp4"`（或 `"mkv"`）。不传时默认 MP4。已有任务的格式不受新任务影响。

**Q: 容器会自动重启吗？**
A: `docker-compose.yml` 中已配置 `restart: always`，容器崩溃或宿主机重启后会自动重启。服务自带 `/{prefix}/health` 接口，可自行配置 Docker healthcheck 或接外部监控实现更完善的自愈。

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
