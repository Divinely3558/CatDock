package com.catdock.app.data

import android.util.Log
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch
import kotlinx.serialization.json.Json
import okhttp3.Interceptor
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Response
import okhttp3.logging.HttpLoggingInterceptor
import retrofit2.Retrofit
import retrofit2.converter.kotlinx.serialization.asConverterFactory
import java.security.SecureRandom
import java.security.cert.X509Certificate
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicReference
import javax.net.ssl.SSLContext
import javax.net.ssl.TrustManager
import javax.net.ssl.X509TrustManager

/** 403（登录过期/无效令牌）时抛出，由 UI 层统一捕获并跳转登录页 */
class AuthExpiredException(message: String) : Exception(message)

/** 请求头注入 Bearer 令牌 */
private class AuthInterceptor(private val token: AtomicReference<String>) : Interceptor {
    override fun intercept(chain: Interceptor.Chain): Response {
        val value = token.get()
        val req = if (value.isEmpty()) chain.request()
        else chain.request().newBuilder().header("Authorization", "Bearer $value").build()
        return chain.proceed(req)
    }
}

/** 捕获 X-New-Token 响应头（令牌剩余 <30 分钟时服务端自动续期） */
private class TokenRenewalInterceptor(private val onNewToken: (String) -> Job) : Interceptor {
    override fun intercept(chain: Interceptor.Chain): Response {
        val resp = chain.proceed(chain.request())
        resp.header("X-New-Token")?.trim()?.takeIf { it.isNotEmpty() }?.let { onNewToken(it) }
        return resp
    }
}

/** 信任全部证书（仅用户在登录页显式勾选「信任自签名证书」时启用） */
internal object TrustAll {
    val trustManager = object : X509TrustManager {
        override fun checkClientTrusted(chain: Array<X509Certificate>, authType: String) {}
        override fun checkServerTrusted(chain: Array<X509Certificate>, authType: String) {}
        override fun getAcceptedIssuers(): Array<X509Certificate> = arrayOf()
    }

    fun sslContext(): SSLContext = SSLContext.getInstance("TLS").apply {
        init(null, arrayOf<TrustManager>(trustManager), SecureRandom())
    }
}

/**
 * 网络客户端工厂：按账号缓存 Retrofit / OkHttp 客户端。
 *
 * 每个账号一个令牌槽（AtomicReference）：请求头读它、`X-New-Token` 续期只写它，
 * 所以切换账号后残留的旧轮询器不会把令牌串到新账号上。
 *
 * 注意：这里不放「401/403 → 异常」的拦截器。拦截器跑在 OkHttp 线程上，
 * 抛出的 RuntimeException 会绕过协程与 runCatching，直接干掉进程
 * （OkHttp Dispatcher 未捕获异常崩溃），状态码一律交给仓库层翻译。
 */
class ApiClient(private val sessionStore: SessionStore) {

    val json = Json {
        ignoreUnknownKeys = true
        explicitNulls = false
        coerceInputValues = true
    }

    // 令牌续期写入 DataStore 的后台作用域（拦截器内非挂起环境）
    private val renewalScope = CoroutineScope(SupervisorJob() + Dispatchers.IO)

    /** 账号专属令牌槽：请求头与 `X-New-Token` 续期都只碰它，切号时互不串味 */
    private val tokenSlots = ConcurrentHashMap<String, AtomicReference<String>>()

    /** 每个账号最近一次从会话侧接受的令牌，用于区分「重新登录」与「本地续期领先 DataStore」 */
    private val accepted = ConcurrentHashMap<String, String>()
    private val clients = ConcurrentHashMap<String, CatdockApi>()
    private val httpClients = ConcurrentHashMap<String, OkHttpClient>()

    private fun tokenSlot(session: Session): AtomicReference<String> {
        val seed = session.token
        val accountKey = session.accountKey
        val slot = tokenSlots.getOrPut(accountKey) { AtomicReference(seed) }
        if (seed.isEmpty()) {
            // 会话里已无令牌（首次登录 / 403 后清空 / 新账号）时槽必须同步清空：
            // 服务端见到无效 Bearer 不会回退去校验请求体里的明文凭证，而是直接 403
            // 并计入 IP 封禁阶梯，带着上一个失效令牌去登录会越试越封
            if (slot.get().isNotEmpty()) {
                slot.set("")
                accepted.remove(accountKey)
            }
            return slot
        }
        // 种子与上次接受过的令牌不同 → 重新登录/切号，以会话为准；
        // 相同而槽内值不同 → 差异来自本槽续期写入，保留槽内新令牌（DataStore 可能还没落盘）
        if (accepted[accountKey] != seed) {
            accepted[accountKey] = seed
            slot.set(seed)
        }
        return slot
    }

    private fun normalizeBaseUrl(session: Session): String =
        if (session.baseUrl.startsWith("http")) session.baseUrl else "http://localhost/"

    private fun cacheKey(session: Session, baseUrl: String) =
        "${session.accountKey}|$baseUrl|${session.trustAllCerts}"

    private fun <V> MutableMap<String, V>.retainLatest(key: String, accountKey: String) {
        keys.filter { it.startsWith("$accountKey|") && it != key }.forEach { remove(it) }
    }

    /** 供 Media3 数据源复用：同账号同地址同证书策略共用一个连接池 */
    fun httpClient(session: Session): OkHttpClient {
        val baseUrl = normalizeBaseUrl(session)
        val key = cacheKey(session, baseUrl)
        val slot = tokenSlot(session)
        httpClients.retainLatest(key, session.accountKey)
        return httpClients.getOrPut(key) {
            buildHttp(session.accountKey, baseUrl, session.trustAllCerts, slot)
        }
    }

    private fun buildHttp(
        accountKey: String,
        baseUrl: String,
        trustAllCerts: Boolean,
        slot: AtomicReference<String>,
    ): OkHttpClient {
        val builder = OkHttpClient.Builder()
            .connectTimeout(15, TimeUnit.SECONDS)
            .readTimeout(30, TimeUnit.SECONDS)
            .writeTimeout(30, TimeUnit.SECONDS)
            .addInterceptor(AuthInterceptor(slot))
            .addInterceptor(TokenRenewalInterceptor { token ->
                if (accountKey.isEmpty()) doneJob()
                else {
                    slot.set(token)
                    renewalScope.launch { sessionStore.updateToken(accountKey, token) }
                }
            })
            // 请求/响应全量日志（tag=CatdockNet），便于 adb logcat 诊断。
            // 凭证一律脱敏：logcat 可读，POST /login 的 body 里有 AUTH_KEY 与密码
            .addInterceptor(
                HttpLoggingInterceptor { msg ->
                    Log.d("CatdockNet", msg.replace(Regex("Bearer [^\\s\"}]+"), "Bearer ***")
                        .replace(credJson, "$1\"***\""))
                }.apply { level = HttpLoggingInterceptor.Level.BODY },
            )

        if (trustAllCerts && baseUrl.startsWith("https")) {
            builder.sslSocketFactory(TrustAll.sslContext().socketFactory, TrustAll.trustManager)
                .hostnameVerifier { _, _ -> true }
        }
        return builder.build()
    }

    fun create(session: Session): CatdockApi {
        val baseUrl = normalizeBaseUrl(session)
        val key = cacheKey(session, baseUrl)
        // 命中缓存时 getOrPut 不会走 lambda，也就不会经 httpClient 校正令牌槽；
        // 必须在缓存判断之外先按会话校正一次，否则登录请求建的空令牌槽会被
        // 后续业务请求复用，请求不带 Bearer，服务端按「凭证校验失败」回 403 并计入封禁
        tokenSlot(session)
        clients.retainLatest(key, session.accountKey)
        return clients.getOrPut(key) {
            Retrofit.Builder()
                .baseUrl(baseUrl)
                .client(httpClient(session))
                .addConverterFactory(json.asConverterFactory("application/json".toMediaType()))
                .build()
                .create(CatdockApi::class.java)
        }
    }

    /** 账号被删除 / 登出时释放其令牌槽与缓存客户端 */
    fun evict(accountKey: String) {
        if (accountKey.isEmpty()) return
        tokenSlots.remove(accountKey)
        accepted.remove(accountKey)
        clients.keys.filter { it.startsWith("$accountKey|") }.forEach { clients.remove(it) }
        httpClients.keys.filter { it.startsWith("$accountKey|") }.forEach { httpClients.remove(it) }
    }

    private fun doneJob(): Job = Job().apply { complete() }

    private companion object {
        /** 日志脱敏：JSON 里的凭证字段（保留键名与冒号，值换成 ***） */
        val credJson = Regex("(\"(?:key|auth_key|token|password|old_password|new_password)\"\\s*:\\s*)\"[^\"]*\"")
    }
}
