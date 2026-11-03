package com.catdock.app.data

import android.content.Context
import androidx.datastore.preferences.core.booleanPreferencesKey
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.map
import kotlinx.serialization.Serializable
import kotlinx.serialization.builtins.ListSerializer
import kotlinx.serialization.builtins.MapSerializer
import kotlinx.serialization.builtins.serializer
import kotlinx.serialization.json.Json

private val Context.dataStore by preferencesDataStore(name = "catdock_session")

/**
 * 已保存账号：每个账号独立持有 Bearer 令牌（2 小时有效期，使用中经 X-New-Token 自动续期）。
 * 切换账号即切换激活项；令牌过期的账号切回时走 403 → 重新登录（用户名已预填）。
 */
@Serializable
data class SavedAccount(
    val serverUrl: String,
    val urlPrefix: String,
    val username: String,
    val role: String = "user",
    val token: String = "",
    val trustAll: Boolean = false,
) {
    /** 唯一键：同服务器同名 = 同一账号 */
    val key: String get() = "${serverUrl.trimEnd('/')}|$username"
}

/**
 * 会话状态持久化（多账号版）。
 *
 * AUTH_KEY/密码经 [SecureCredentials]（Android Keystore AES-GCM）加密后落盘，
 * 仅用于令牌失效时静默重登；令牌失效只清空该账号 token，账号条目与加密凭据保留，
 * 因此登录页永远能预填服务器地址、前缀、用户名与凭据。
 */
data class Session(
    val serverUrl: String = "",   // 形如 http://host:port（无尾斜杠、无前缀）
    val urlPrefix: String = "",   // 必填路径前缀
    val token: String = "",
    val username: String = "",
    val role: String = "user",
    val trustAllCerts: Boolean = false,
    /** 账号唯一键（serverUrl|username）：网络客户端与令牌续期都按它归属 */
    val accountKey: String = "",
) {
    val isLoggedIn: Boolean get() = token.isNotEmpty()
    val isAdmin: Boolean get() = role == "admin"
    /** API 基地址：{serverUrl}/{prefix}/（Retrofit 要求以 / 结尾） */
    val baseUrl: String get() = "${serverUrl.trimEnd('/')}/${urlPrefix.trim('/')}/"
    fun previewUrl(taskId: String) = "${baseUrl}tasks/$taskId/preview.m3u8"

    companion object {
        fun from(acc: SavedAccount) = Session(
            serverUrl = acc.serverUrl,
            urlPrefix = acc.urlPrefix,
            token = acc.token,
            username = acc.username,
            role = acc.role,
            trustAllCerts = acc.trustAll,
            accountKey = acc.key,
        )
    }
}

/** 加密前的凭据结构（仅在内存在明文，落盘走 [SecureCredentials.seal]） */
@Serializable
private data class CredPayload(
    val key: String = "",
    val password: String = "",
)

class SessionStore(private val context: Context) {

    private object Keys {
        val ACCOUNTS = stringPreferencesKey("accounts_json")
        val ACTIVE = stringPreferencesKey("active_key")
        val CREDENTIALS = stringPreferencesKey("credentials_json")
        // ---- 旧版单账号键：仅用于一次性迁移 ----
        val LEGACY_SERVER = stringPreferencesKey("server_url")
        val LEGACY_PREFIX = stringPreferencesKey("url_prefix")
        val LEGACY_TOKEN = stringPreferencesKey("token")
        val LEGACY_USER = stringPreferencesKey("username")
        val LEGACY_ROLE = stringPreferencesKey("role")
        val LEGACY_TRUST = booleanPreferencesKey("trust_all_certs")
        val CHAT_SEEN = stringPreferencesKey("chat_seen_json")
    }

    private val json = Json { ignoreUnknownKeys = true }

    private fun decodeAccounts(raw: String?): List<SavedAccount> =
        raw?.let { r ->
            runCatching { json.decodeFromString(ListSerializer(SavedAccount.serializer()), r) }
                .getOrDefault(emptyList())
        } ?: emptyList()

    private fun encodeAccounts(list: List<SavedAccount>): String =
        json.encodeToString(ListSerializer(SavedAccount.serializer()), list)

    private data class StoreState(val list: List<SavedAccount>, val activeKey: String?)

    /** 统一状态源：首次读取时把旧版单账号键迁移为多账号结构 */
    private val state: Flow<StoreState> = context.dataStore.data.map { p ->
        val stored = decodeAccounts(p[Keys.ACCOUNTS])
        if (p[Keys.ACCOUNTS] != null) return@map StoreState(stored, p[Keys.ACTIVE])
        val legacyToken = p[Keys.LEGACY_TOKEN]
        if (!legacyToken.isNullOrEmpty()) {
            val acc = SavedAccount(
                serverUrl = p[Keys.LEGACY_SERVER] ?: "",
                urlPrefix = p[Keys.LEGACY_PREFIX] ?: "",
                username = p[Keys.LEGACY_USER] ?: "",
                role = p[Keys.LEGACY_ROLE] ?: "user",
                token = legacyToken,
                trustAll = p[Keys.LEGACY_TRUST] ?: false,
            )
            context.dataStore.edit {
                it[Keys.ACCOUNTS] = encodeAccounts(listOf(acc))
                it[Keys.ACTIVE] = acc.key
                // 清理旧键
                it.remove(Keys.LEGACY_TOKEN); it.remove(Keys.LEGACY_SERVER)
                it.remove(Keys.LEGACY_PREFIX); it.remove(Keys.LEGACY_USER)
                it.remove(Keys.LEGACY_ROLE); it.remove(Keys.LEGACY_TRUST)
            }
            StoreState(listOf(acc), acc.key)
        } else {
            StoreState(emptyList(), p[Keys.ACTIVE])
        }
    }

    val accounts: Flow<List<SavedAccount>> = state.map { it.list }

    val session: Flow<Session> = state.map { (list, activeKey) ->
        // 令牌为空也要返回账号信息：登录页据此预填服务器/前缀/用户名，
        // 并在持有加密凭据时静默重登。isLoggedIn 由 token 是否非空决定。
        list.firstOrNull { it.key == activeKey }
            ?.let { Session.from(it) }
            ?: Session()
    }

    suspend fun current(): Session = session.first()

    suspend fun currentAccounts(): List<SavedAccount> = accounts.first()

    /** 登录成功：upsert 账号并设为激活，同时加密保存 AUTH_KEY/密码（供静默重登） */
    suspend fun saveLogin(
        serverUrl: String,
        prefix: String,
        username: String,
        login: LoginData,
        trustAll: Boolean,
        authKey: String = "",
        password: String = "",
    ) {
        val acc = SavedAccount(
            serverUrl = serverUrl.trimEnd('/'),
            urlPrefix = prefix.trim('/'),
            username = username,
            role = login.role,
            token = login.token,
            trustAll = trustAll,
        )
        context.dataStore.edit { p ->
            val list = decodeAccounts(p[Keys.ACCOUNTS])
            val updated = list.filterNot { it.key == acc.key } + acc
            p[Keys.ACCOUNTS] = encodeAccounts(updated)
            p[Keys.ACTIVE] = acc.key
        }
        if (authKey.isNotBlank() || password.isNotBlank()) {
            saveCredentials(acc.key, authKey, password)
        }
    }

    // ---------- 加密凭据（AUTH_KEY / 密码）：仅用于令牌失效后的静默重登 ----------

    private fun decodeCredentials(raw: String?): Map<String, String> =
        raw?.let { r ->
            runCatching {
                json.decodeFromString(MapSerializer(String.serializer(), String.serializer()), r)
            }.getOrDefault(emptyMap())
        } ?: emptyMap()

    private fun encodeCredentials(map: Map<String, String>): String =
        json.encodeToString(MapSerializer(String.serializer(), String.serializer()), map)

    /** 保存某账号的 AUTH_KEY 与密码（加密后写入 DataStore） */
    suspend fun saveCredentials(accountKey: String, authKey: String, password: String) {
        if (accountKey.isEmpty()) return
        val payload = json.encodeToString(CredPayload.serializer(), CredPayload(authKey, password))
        val sealed = SecureCredentials.seal(payload) ?: return
        context.dataStore.edit { p ->
            p[Keys.CREDENTIALS] = encodeCredentials(
                decodeCredentials(p[Keys.CREDENTIALS]) + (accountKey to sealed),
            )
        }
    }

    /** 读取某账号的 (AUTH_KEY, 密码)；未保存或解密失败返回 null */
    suspend fun credentialsFor(accountKey: String): Pair<String, String>? {
        if (accountKey.isEmpty()) return null
        val sealed = decodeCredentials(context.dataStore.data.first()[Keys.CREDENTIALS])[accountKey]
            ?: return null
        val plain = SecureCredentials.open(sealed) ?: return null
        val payload = runCatching {
            json.decodeFromString(CredPayload.serializer(), plain)
        }.getOrNull() ?: return null
        if (payload.key.isEmpty() && payload.password.isEmpty()) return null
        return payload.key to payload.password
    }

    /** 改密成功后同步本地保存的密码，避免下次静默重登仍用旧密码 */
    suspend fun updateStoredPassword(accountKey: String, password: String) {
        val saved = credentialsFor(accountKey) ?: return
        saveCredentials(accountKey, saved.first, password)
    }

    /** 删除某账号的加密凭据（注销 / 删除账号 / 凭据确认失效时） */
    suspend fun clearCredentials(accountKey: String) {
        if (accountKey.isEmpty()) return
        context.dataStore.edit { p ->
            val map = decodeCredentials(p[Keys.CREDENTIALS])
            if (map.containsKey(accountKey)) {
                p[Keys.CREDENTIALS] = encodeCredentials(map - accountKey)
            }
        }
    }

    /**
     * 令牌自动续期（X-New-Token）：只写回发起该请求的账号。
     * 早先按「当前激活账号」写入，切号后旧账号在途请求的新令牌会覆盖新账号令牌。
     */
    suspend fun updateToken(accountKey: String, token: String) {
        if (accountKey.isEmpty()) return
        context.dataStore.edit { p ->
            val list = decodeAccounts(p[Keys.ACCOUNTS])
            p[Keys.ACCOUNTS] = encodeAccounts(
                list.map { if (it.key == accountKey) it.copy(token = token) else it },
            )
        }
    }

    /** 登录失效（403）：仅清空该账号令牌，保留条目便于重登预填 */
    suspend fun invalidate(accountKey: String) {
        if (accountKey.isEmpty()) return
        context.dataStore.edit { p ->
            val list = decodeAccounts(p[Keys.ACCOUNTS])
            p[Keys.ACCOUNTS] = encodeAccounts(
                list.map { if (it.key == accountKey) it.copy(token = "") else it },
            )
        }
    }

    // ---------- 聊天已读水位（顶栏状态灯「有新消息」，按账号隔离，对应网页 localStorage 键） ----------

    val chatSeen: Flow<Map<String, Long>> = context.dataStore.data.map { p ->
        p[Keys.CHAT_SEEN]?.let { raw ->
            runCatching {
                json.decodeFromString(MapSerializer(String.serializer(), Long.serializer()), raw)
            }.getOrDefault(emptyMap())
        } ?: emptyMap()
    }

    suspend fun chatSeenFor(accountKey: String): Long =
        chatSeen.first()[accountKey] ?: 0L

    suspend fun markChatSeen(accountKey: String, id: Long) {
        if (accountKey.isEmpty()) return
        context.dataStore.edit { p ->
            val map = (p[Keys.CHAT_SEEN]?.let { raw ->
                runCatching {
                    json.decodeFromString(MapSerializer(String.serializer(), Long.serializer()), raw)
                }.getOrDefault(emptyMap())
            } ?: emptyMap()).toMutableMap()
            if ((map[accountKey] ?: 0L) < id) {
                map[accountKey] = id
                p[Keys.CHAT_SEEN] = json.encodeToString(
                    MapSerializer(String.serializer(), Long.serializer()), map,
                )
            }
        }
    }

    /** 注销：移除激活账号条目并删除其加密凭据（避免自动重登） */
    suspend fun logoutActive() {
        val activeKey = context.dataStore.data.first()[Keys.ACTIVE]
        if (activeKey.isNullOrEmpty()) return
        context.dataStore.edit { p ->
            val list = decodeAccounts(p[Keys.ACCOUNTS])
            p[Keys.ACCOUNTS] = encodeAccounts(list.filterNot { it.key == activeKey })
            p.remove(Keys.ACTIVE)
        }
        clearCredentials(activeKey)
    }

    /** 切换激活账号（不校验令牌，过期账号由 403 流程接管） */
    suspend fun switchAccount(acc: SavedAccount) {
        context.dataStore.edit { it[Keys.ACTIVE] = acc.key }
    }

    /** 删除账号；若删除的是激活账号，会话随之清空（UI 自动回登录页） */
    suspend fun removeAccount(acc: SavedAccount) {
        context.dataStore.edit { p ->
            val list = decodeAccounts(p[Keys.ACCOUNTS])
            p[Keys.ACCOUNTS] = encodeAccounts(list.filterNot { it.key == acc.key })
            if (p[Keys.ACTIVE] == acc.key) p.remove(Keys.ACTIVE)
        }
        clearCredentials(acc.key)
    }
}
