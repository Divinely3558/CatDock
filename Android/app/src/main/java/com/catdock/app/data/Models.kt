package com.catdock.app.data

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

/**
 * 服务器统一响应封装：{'success': bool, 'data'?: T, 'message'?: string}
 * /download 成功响应的 taskId/message/duplicate 等字段位于顶层，单独建模。
 */
@Serializable
data class ApiResp<T>(
    val success: Boolean,
    val data: T? = null,
    val message: String? = null,
)

@Serializable
data class DownloadResp(
    val success: Boolean,
    val taskId: String? = null,
    val message: String? = null,
    val duplicate: Boolean? = null,
    val blocked: Boolean? = null,
    val keyword: String? = null,
    @SerialName("output_format") val outputFormat: String? = null,
)

// ---------- 登录 ----------

@Serializable
data class LoginReq(
    val key: String,
    val user: String,
    val password: String,
)

@Serializable
data class LoginData(
    val token: String,
    val expiresIn: Long = 0,
    val role: String = "user",
)

// ---------- 任务 ----------

@Serializable
data class Task(
    val id: String,
    val url: String? = null,
    val urls: List<String>? = null,
    @SerialName("save_name") val saveName: String? = null,
    val status: String = "queued",
    // Double 防御：服务端进度可能带小数，Int 会导致整包解析失败
    val progress: Double = 0.0,
    val user: String? = null,
    @SerialName("output_file") val outputFile: String? = null,
    val segments: Segments? = null,
    @SerialName("queue_pos") val queuePos: Int? = null,
    @SerialName("preview_resume_time") val previewResumeTime: Double? = null,
    @SerialName("_retry_count") val retryCount: Int = 0,
    @SerialName("_output_format") val outputFormat: String? = null,
)

@Serializable
data class Segments(
    val done: Int = 0,
    val total: Int = 0,
)

@Serializable
data class DownloadReq(
    val url: String,
    @SerialName("saveName") val saveName: String? = null,
    val referer: String? = null,
    val cookie: String? = null,
    val userAgent: String? = null,
    val format: String? = null,
)

@Serializable
data class TaskOpReq(val taskId: String)

@Serializable
data class ResumeTimeReq(
    val taskId: String,
    @SerialName("resumeTime") val resumeTime: Double,
)

// ---------- 聊天 ----------

@Serializable
data class ChatData(
    val messages: List<ChatMessage> = emptyList(),
    @SerialName("last_id") val lastId: Long = 0,
)

@Serializable
data class ChatMessage(
    val id: Long,
    val user: String,
    val time: String,
    val msg: String,
)

@Serializable
data class ChatSendReq(val message: String)

@Serializable
data class ChatCleared(@SerialName("cleared_id") val clearedId: Long = 0)

// ---------- 服务信息 / 账号 ----------

@Serializable
data class ServerConfig(
    @SerialName("api_port") val apiPort: Int = 0,
    @SerialName("url_prefix") val urlPrefix: String = "",
    @SerialName("ssrf_protection") val ssrfProtection: Boolean = false,
    @SerialName("max_concurrent_tasks") val maxConcurrentTasks: Int = 0,
    @SerialName("max_total_running") val maxTotalRunning: Int = 0,
    @SerialName("same_video_mode") val sameVideoMode: Boolean = false,
    @SerialName("keywords_enabled") val keywordsEnabled: Boolean = false,
    @SerialName("ad_keyword_count") val adKeywordCount: Int = 0,
    @SerialName("filename_filter_enabled") val filenameFilterEnabled: Boolean = false,
    @SerialName("filename_filter_count") val filenameFilterCount: Int = 0,
    @SerialName("filename_dedup_enabled") val filenameDedupEnabled: Boolean = false,
    @SerialName("filename_dedup_count") val filenameDedupCount: Int = 0,
    @SerialName("user_count") val userCount: Int = 0,
    @SerialName("auth_key_masked") val authKeyMasked: String = "",
    val version: String = "",
)

@Serializable
data class ChangePasswordReq(
    @SerialName("oldPassword") val oldPassword: String,
    @SerialName("newPassword") val newPassword: String,
)

// ---------- 管理端（契约逐字对齐 core/api_server.py） ----------

/** GET /health 免鉴权：{'success':true,'status':'ok'}（无 data 包装） */
@Serializable
data class HealthResp(
    val success: Boolean = false,
    val status: String = "",
)

@Serializable
data class AdminUser(
    val username: String,
    val role: String = "user",
    val disabled: Boolean = false,
    @SerialName("created_at") val createdAt: String = "",
) {
    val isAdmin: Boolean get() = role == "admin"
}

@Serializable
data class BanEntry(
    val ip: String,
    @SerialName("banned_at") val bannedAt: String = "",
    val reason: String = "",
) {
    /** 服务端 reason：auto=认证失败自动封禁 / auto_perm=再犯永久 / manual=手动 */
    val reasonLabel: String
        get() = when (reason) {
            "auto" -> "自动（临时）"
            "auto_perm" -> "自动（永久）"
            "manual" -> "手动"
            "" -> "—"
            else -> reason
        }
}

@Serializable
data class UserAddReq(
    val username: String,
    val password: String,
    val role: String,
)

@Serializable
data class UsernameReq(val username: String)

@Serializable
data class UserPasswordReq(val username: String, val newPassword: String)

@Serializable
data class IpReq(val ip: String)

@Serializable
data class AuthKeyReq(val newKey: String)

/**
 * 过滤规则：GET/POST /admin/filters 与用户级 /filters 双向同构。
 * keywords / filename_filter 为关键字列表，filename_dedup 为「查找→替换」规则表。
 */
@Serializable
data class FilterConfig(
    val keywords: KeywordGroup = KeywordGroup(),
    @SerialName("filename_filter") val filenameFilter: NameGroup = NameGroup(),
    @SerialName("filename_dedup") val filenameDedup: DedupGroup = DedupGroup(),
)

@Serializable
data class KeywordGroup(
    val enabled: Boolean = false,
    val list: List<String> = emptyList(),
)

@Serializable
data class NameGroup(
    val enabled: Boolean = false,
    val list: List<String> = emptyList(),
)

@Serializable
data class DedupGroup(
    val enabled: Boolean = false,
    val rules: List<DedupRule> = emptyList(),
)

@Serializable
data class DedupRule(
    val pattern: String = "",
    val replacement: String = "",
)
