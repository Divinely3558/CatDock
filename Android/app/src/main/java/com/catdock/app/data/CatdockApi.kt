package com.catdock.app.data

import kotlinx.serialization.json.JsonElement
import retrofit2.http.Body
import retrofit2.http.GET
import retrofit2.http.POST
import retrofit2.http.Streaming
import retrofit2.http.Path
import retrofit2.http.Query

/**
 * catdock HTTP API（所有路径相对 {serverUrl}/{urlPrefix}/）。
 * 请求/响应契约与 core/api_server.py 逐一对应。
 */
interface CatdockApi {

    // ---------- 认证 ----------

    /** 两层认证（AUTH_KEY + 用户名/密码）换 2 小时 Bearer 令牌 */
    @POST("login")
    suspend fun login(@Body body: LoginReq): ApiResp<LoginData>

    /** 吊销当前令牌 */
    @POST("logout")
    suspend fun logout(): ApiResp<JsonElement>

    /** 修改自己密码（成功后吊销全部令牌，全端下线） */
    @POST("password")
    suspend fun changePassword(@Body body: ChangePasswordReq): ApiResp<JsonElement>

    /** 服务信息（版本 / 并发 / 过滤规则统计等） */
    @GET("config")
    suspend fun config(): ApiResp<ServerConfig>

    // ---------- 任务 ----------

    /** 当前登录用户的任务列表 */
    @GET("tasks")
    suspend fun tasks(): ApiResp<List<Task>>

    /** 任务详情（含 preview_resume_time 等） */
    @GET("tasks/{id}")
    suspend fun task(@Path("id") id: String): ApiResp<Task>

    /**
     * 提交下载任务。响应为顶层 taskId/message/duplicate 结构（无 data 包装）。
     * 广告拦截返回 success=false + blocked=true（HTTP 200）。
     */
    @POST("download")
    suspend fun download(@Body body: DownloadReq): DownloadResp

    /** 任务操作：暂停 / 恢复 / 删除 / 置顶到队首 */
    @POST("task/pause")
    suspend fun pauseTask(@Body body: TaskOpReq): ApiResp<JsonElement>

    @POST("task/resume")
    suspend fun resumeTask(@Body body: TaskOpReq): ApiResp<JsonElement>

    @POST("task/delete")
    suspend fun deleteTask(@Body body: TaskOpReq): ApiResp<JsonElement>

    @POST("task/pin")
    suspend fun pinTask(@Body body: TaskOpReq): ApiResp<JsonElement>

    /** 保存预览播放进度（退出播放器时上报） */
    @POST("task/resume_time")
    suspend fun saveResumeTime(@Body body: ResumeTimeReq): ApiResp<JsonElement>

    // ---------- 聊天室 ----------

    /** 增量拉取消息（after=已见最大 id），服务端叠加清理水位过滤 */
    @GET("chat")
    suspend fun chat(@Query("after") after: Long): ApiResp<ChatData>

    /** 发送消息（≤500 字，写入即存档无法撤回） */
    @POST("chat")
    suspend fun sendChat(@Body body: ChatSendReq): ApiResp<ChatMessage>

    /** 清除本账号聊天水位（存档不删除，其他用户不受影响） */
    @POST("chat/clear")
    suspend fun clearChat(): ApiResp<ChatCleared>

    /** 导出近 7 天聊天记录（服务端返回 text/plain 附件，非 JSON） */
    @Streaming
    @GET("chat/export")
    suspend fun chatExport(): retrofit2.Response<okhttp3.ResponseBody>

    // ---------- 服务状态 / 主题偏好 ----------

    /** 免鉴权健康检查，驱动顶栏状态灯 */
    @GET("health")
    suspend fun health(): HealthResp

    // ---------- 管理端：用户 ----------

    @GET("admin/users")
    suspend fun adminUsers(): ApiResp<List<AdminUser>>

    @POST("admin/users/add")
    suspend fun adminUserAdd(@Body body: UserAddReq): ApiResp<JsonElement>

    @POST("admin/users/delete")
    suspend fun adminUserDelete(@Body body: UsernameReq): ApiResp<JsonElement>

    @POST("admin/users/password")
    suspend fun adminUserPassword(@Body body: UserPasswordReq): ApiResp<JsonElement>

    @POST("admin/users/ban")
    suspend fun adminUserBan(@Body body: UsernameReq): ApiResp<JsonElement>

    @POST("admin/users/unban")
    suspend fun adminUserUnban(@Body body: UsernameReq): ApiResp<JsonElement>

    // ---------- 管理端：IP 封禁 ----------

    @GET("admin/bans")
    suspend fun adminBans(): ApiResp<List<BanEntry>>

    @POST("admin/bans/add")
    suspend fun adminBanAdd(@Body body: IpReq): ApiResp<JsonElement>

    @POST("admin/bans/delete")
    suspend fun adminBanDelete(@Body body: IpReq): ApiResp<JsonElement>

    // ---------- 过滤规则 ----------

    /** 管理员：全局过滤模板（新用户首启时复制） */
    @GET("admin/filters")
    suspend fun adminFilters(): ApiResp<FilterConfig>

    @POST("admin/filters")
    suspend fun saveAdminFilters(@Body body: FilterConfig): ApiResp<JsonElement>

    /** 下载用户：自己的过滤规则 */
    @GET("filters")
    suspend fun userFilters(): ApiResp<FilterConfig>

    @POST("filters")
    suspend fun saveUserFilters(@Body body: FilterConfig): ApiResp<JsonElement>

    // ---------- 管理端：密钥与日志 ----------

    /** 更换 AUTH_KEY：服务端会吊销全部令牌，全员下线 */
    @POST("admin/auth-key")
    suspend fun setAuthKey(@Body body: AuthKeyReq): ApiResp<JsonElement>

    /** 导出日志（≤15 天）：成功返回 text/plain 附件，失败返回 400 + JSON */
    @Streaming
    @GET("admin/logs/export")
    suspend fun logsExport(
        @Query("start") start: String,
        @Query("end") end: String,
    ): retrofit2.Response<okhttp3.ResponseBody>
}
