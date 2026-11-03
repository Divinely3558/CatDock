package com.catdock.app.data

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.JsonElement
import okhttp3.ResponseBody
import retrofit2.HttpException
import retrofit2.Response
import java.util.concurrent.ConcurrentHashMap

/**
 * 仓库层：统一错误处理。所有调用挂 IO 调度器，
 * 业务失败（success=false）与非 2xx 均抛 ApiException（透出服务端 message），
 * 已鉴权请求的 401/403 抛 AuthExpiredException。
 */
class ApiException(message: String) : Exception(message)

class AppRepository(
    private val sessionStore: SessionStore,
    private val apiClient: ApiClient,
) {
    /** 静默重登已尝试的账号（每进程每账号一次，防止反复失败触发服务端锁定/封禁） */
    private val autoReloginTried = ConcurrentHashMap.newKeySet<String>()

    private suspend fun api(): CatdockApi {
        val session = sessionStore.current()
        // 令牌已空的账号不再发请求：服务端把「无 Bearer 的凭证校验失败」计入 IP 封禁阶梯，
        // 登录后残留的轮询器若带着空令牌继续跑，会把整个出口 IP 一路推到永久封禁
        if (!session.isLoggedIn) throw AuthExpiredException("登录已过期，请重新登录")
        return apiClient.create(session)
    }

    /**
     * Retrofit 对非 2xx 直接抛 HttpException，只留下 "HTTP 403 Forbidden" 这类状态行；
     * 服务端真正的拒绝理由（密钥不正确 / 用户不存在 / 账号锁定…）在响应体里，必须透出，
     * 否则用户只能盲重试，而密钥与用户名错误是会计入 IP 封禁阶梯的。
     * 已鉴权请求的 401/403 转 AuthExpiredException（登录请求本身除外）。
     */
    private suspend fun <T> unwrap(loginCall: Boolean = false, block: suspend () -> T): T =
        try {
            block()
        } catch (e: HttpException) {
            val body = runCatching { e.response()?.errorBody()?.string() }.getOrNull()
            val message = body?.let { jsonMessage.find(it)?.groupValues?.get(1) }
            if (!loginCall && (e.code() == 401 || e.code() == 403)) {
                throw AuthExpiredException(message ?: "登录已过期，请重新登录")
            }
            throw ApiException(message ?: "服务返回 HTTP ${e.code()}")
        }

    private suspend fun <T> call(block: suspend CatdockApi.() -> ApiResp<T>): T =
        withContext(Dispatchers.IO) {
            val resp = unwrap { block(api()) }
            if (!resp.success) throw ApiException(resp.message ?: "操作失败")
            resp.data ?: throw ApiException("响应缺少数据")
        }

    /** 只关心成败与提示语的写操作 */
    private suspend fun op(
        block: suspend CatdockApi.() -> ApiResp<JsonElement>,
        ok: String,
    ): String = withContext(Dispatchers.IO) {
        val resp = unwrap { block(api()) }
        if (!resp.success) throw ApiException(resp.message ?: "操作失败")
        resp.message ?: ok
    }

    /** 附件类响应（text/plain 导出）：非 2xx 时从错误 JSON 中取 message */
    private suspend fun raw(
        block: suspend CatdockApi.() -> Response<ResponseBody>,
    ): ByteArray = withContext(Dispatchers.IO) {
        val resp = block(api())
        if (!resp.isSuccessful) {
            val error = runCatching { resp.errorBody()?.string() }.getOrNull()
            val message = error?.let { jsonMessage.find(it)?.groupValues?.get(1) }
            if (resp.code() == 401 || resp.code() == 403) {
                throw AuthExpiredException(message ?: "登录已过期，请重新登录")
            }
            throw ApiException(message ?: "导出失败（HTTP ${resp.code()}）")
        }
        resp.body()?.bytes() ?: throw ApiException("导出内容为空")
    }

    private val jsonMessage = Regex("\\\"message\\\"\\s*:\\s*\\\"([^\\\"]+)\\\"")

    // ---------- 认证 ----------

    suspend fun login(serverUrl: String, prefix: String, key: String, user: String, password: String, trustAll: Boolean) {
        val trimmed = serverUrl.trimEnd('/')
        val session = Session(
            serverUrl = trimmed,
            urlPrefix = prefix,
            trustAllCerts = trustAll,
            accountKey = "$trimmed|$user",
        )
        // 登录请求此时尚无令牌（AuthInterceptor 见空令牌即跳过请求头），失败信息直接透出
        val resp = withContext(Dispatchers.IO) {
            unwrap(loginCall = true) {
                apiClient.create(session).login(LoginReq(key = key, user = user, password = password))
            }
        }
        if (!resp.success || resp.data == null) throw ApiException(resp.message ?: "登录失败")
        sessionStore.saveLogin(
            serverUrl = serverUrl,
            prefix = prefix,
            username = user,
            login = resp.data,
            trustAll = trustAll,
            authKey = key,
            password = password,
        )
    }

    /**
     * 令牌失效后的静默重登。
     *
     * 仅当本地存有该账号的加密凭据时尝试；每账号每进程最多一次。
     * 服务端明确拒绝（KEY 更换 / 密码改动 / 账号禁用）→ 清除凭据转人工登录；
     * 网络类故障保留凭据并允许后续重试（换网恢复后即可自动续上）。
     */
    suspend fun tryAutoRelogin(session: Session): Boolean {
        if (session.isLoggedIn || session.accountKey.isEmpty()) return false
        if (!autoReloginTried.add(session.accountKey)) return false
        val saved = sessionStore.credentialsFor(session.accountKey) ?: return false
        return try {
            login(
                serverUrl = session.serverUrl,
                prefix = session.urlPrefix,
                key = saved.first,
                user = session.username,
                password = saved.second,
                trustAll = session.trustAllCerts,
            )
            // 成功即重置尝试标记：同一进程内令牌日后再次过期（如长时间后台）仍可自动重登
            autoReloginTried.remove(session.accountKey)
            true
        } catch (e: ApiException) {
            sessionStore.clearCredentials(session.accountKey)
            false
        } catch (e: Exception) {
            autoReloginTried.remove(session.accountKey)
            false
        }
    }

    suspend fun logout() {
        val accountKey = sessionStore.current().accountKey
        withContext(Dispatchers.IO) {
            runCatching { api().logout() } // 尽力而为：本地清令牌即可
        }
        apiClient.evict(accountKey)
        sessionStore.logoutActive()
    }

    suspend fun changePassword(oldPassword: String, newPassword: String): String {
        call { changePassword(ChangePasswordReq(oldPassword, newPassword)) }
        // 服务端改密会吊销全部令牌：本地同步新密码，令牌失效后可用新密码静默重登
        val session = sessionStore.current()
        if (session.accountKey.isNotEmpty()) {
            sessionStore.updateStoredPassword(session.accountKey, newPassword)
        }
        return "密码已修改，请使用新密码重新登录"
    }

    suspend fun serverConfig(): ServerConfig = call { config() }

    // ---------- 任务 ----------

    suspend fun tasks(): List<Task> = call { tasks() }

    suspend fun task(id: String): Task = call { task(id) }

    /** 返回服务端 message（含排队位次 / 重复复用等提示） */
    suspend fun download(req: DownloadReq): DownloadResp =
        withContext(Dispatchers.IO) {
            val resp = unwrap { api().download(req) }
            if (!resp.success && resp.blocked != true) throw ApiException(resp.message ?: "提交失败")
            resp
        }

    private suspend fun taskOp(path: suspend CatdockApi.(TaskOpReq) -> ApiResp<JsonElement>, id: String): String =
        withContext(Dispatchers.IO) {
            val resp = path(api(), TaskOpReq(id))
            if (!resp.success) throw ApiException(resp.message ?: "操作失败")
            resp.message ?: "操作成功"
        }

    suspend fun pauseTask(id: String) = taskOp({ pauseTask(it) }, id)
    suspend fun resumeTask(id: String) = taskOp({ resumeTask(it) }, id)
    suspend fun deleteTask(id: String) = taskOp({ deleteTask(it) }, id)
    suspend fun pinTask(id: String) = taskOp({ pinTask(it) }, id)

    suspend fun saveResumeTime(id: String, seconds: Double) {
        withContext(Dispatchers.IO) {
            runCatching { api().saveResumeTime(ResumeTimeReq(id, seconds)) }
        }
    }

    // ---------- 聊天 ----------

    suspend fun chatAfter(after: Long): ChatData = call { chat(after) }

    suspend fun sendChat(message: String): ChatMessage = call { sendChat(ChatSendReq(message)) }

    suspend fun clearChat(): ChatCleared = call { clearChat() }

    suspend fun chatExport(): ByteArray = raw { chatExport() }

    // ---------- 服务状态 ----------

    /** 顶栏状态灯：health 免鉴权，异常（含网络不可达）一律视为红灯 */
    suspend fun healthOk(): Boolean = withContext(Dispatchers.IO) {
        runCatching { api().health() }.getOrNull()?.let { it.success && it.status == "ok" } ?: false
    }

    // ---------- 管理端：用户 ----------

    suspend fun adminUsers(): List<AdminUser> = call { adminUsers() }

    suspend fun adminAddUser(username: String, password: String, role: String) =
        op({ adminUserAdd(UserAddReq(username, password, role)) }, "用户已添加")

    suspend fun adminDeleteUser(username: String) =
        op({ adminUserDelete(UsernameReq(username)) }, "用户已删除")

    suspend fun adminUserPassword(username: String, newPassword: String) =
        op({ adminUserPassword(UserPasswordReq(username, newPassword)) }, "密码已修改")

    suspend fun adminBanUser(username: String) =
        op({ adminUserBan(UsernameReq(username)) }, "用户已禁用")

    suspend fun adminUnbanUser(username: String) =
        op({ adminUserUnban(UsernameReq(username)) }, "用户已解禁")

    // ---------- 管理端：IP 封禁 ----------

    suspend fun adminBans(): List<BanEntry> = call { adminBans() }

    suspend fun adminBanIp(ip: String) = op({ adminBanAdd(IpReq(ip)) }, "IP 已封禁")

    suspend fun adminUnbanIp(ip: String) = op({ adminBanDelete(IpReq(ip)) }, "IP 已解封")

    // ---------- 过滤规则（管理员=全局模板 /admin/filters，用户=本人 /filters） ----------

    suspend fun filters(isAdmin: Boolean): FilterConfig =
        call { if (isAdmin) adminFilters() else userFilters() }

    suspend fun saveFilters(config: FilterConfig, isAdmin: Boolean): String =
        op({ if (isAdmin) saveAdminFilters(config) else saveUserFilters(config) }, "过滤规则已保存")

    // ---------- 管理端：密钥与日志 ----------

    suspend fun setAuthKey(newKey: String): String {
        val result = op({ setAuthKey(AuthKeyReq(newKey)) }, "AUTH_KEY 已更换")
        // 换 KEY 会吊销全部令牌：同步本地加密保存的 AUTH_KEY，保证静默重登可用
        val session = sessionStore.current()
        if (session.accountKey.isNotEmpty()) {
            sessionStore.credentialsFor(session.accountKey)?.let { saved ->
                sessionStore.saveCredentials(session.accountKey, newKey, saved.second)
            }
        }
        return result
    }

    suspend fun logsExport(start: String, end: String): ByteArray = raw { logsExport(start, end) }
}
