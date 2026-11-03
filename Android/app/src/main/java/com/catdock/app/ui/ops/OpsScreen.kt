package com.catdock.app.ui.ops

import android.content.Context
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.key
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.catdock.app.data.AdminUser
import com.catdock.app.data.ApiException
import com.catdock.app.data.AppRepository
import com.catdock.app.data.AuthExpiredException
import com.catdock.app.data.BanEntry
import com.catdock.app.data.Session
import com.catdock.app.ui.ScreenModel
import com.catdock.app.ui.rememberScreenModel
import com.catdock.app.ui.components.BentoDialog
import com.catdock.app.ui.components.BentoDialogButtons
import com.catdock.app.ui.components.BentoDialogTitle
import com.catdock.app.ui.components.CatBadge
import com.catdock.app.ui.components.CatButton
import com.catdock.app.ui.components.CatButtonVariant
import com.catdock.app.ui.components.CatCard
import com.catdock.app.ui.components.CatCardTitle
import com.catdock.app.ui.components.CatConfirmButton
import com.catdock.app.ui.components.CatField
import com.catdock.app.ui.components.CatSwitch
import com.catdock.app.ui.components.CatTone
import com.catdock.app.ui.components.TrackBentoScroll
import com.catdock.app.ui.components.bentoEnter
import com.catdock.app.ui.components.bentoSurface
import com.catdock.app.ui.filters.FiltersEditor
import com.catdock.app.ui.shareTextFile
import com.catdock.app.ui.theme.LocalPalette
import com.catdock.app.ui.theme.LocalSpec
import com.catdock.app.ui.theme.catCardShape
import java.security.SecureRandom
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.launch

/**
 * 运维页状态：对齐网页 admin.html 的五张卡——用户 / IP 封禁 / AUTH_KEY / 过滤 / 日志导出。
 * 网页没有的（在线统计、全量任务、掩码密钥）一律不做。
 */
class OpsModel(private val repo: AppRepository) : ScreenModel() {

    private val _users = MutableStateFlow<List<AdminUser>>(emptyList())
    val users: StateFlow<List<AdminUser>> = _users
    private val _bans = MutableStateFlow<List<BanEntry>>(emptyList())
    val bans: StateFlow<List<BanEntry>> = _bans
    private val _error = MutableStateFlow<String?>(null)
    val error: StateFlow<String?> = _error
    private val _notice = MutableStateFlow<String?>(null)
    val notice: StateFlow<String?> = _notice
    // 令牌失效经此上抛，由界面统一转 onAuthExpired（读取/写入共用一条通道）
    private val _authEvent = MutableStateFlow<String?>(null)
    val authEvent: StateFlow<String?> = _authEvent

    init {
        loadUsers()
        loadBans()
    }

    fun clearError() { _error.value = null }
    fun clearAuth() { _authEvent.value = null }

    fun loadUsers() {
        scope.launch {
            _notice.value = null
            try {
                _users.value = repo.adminUsers()
                _error.value = null
            } catch (e: Exception) {
                handle(e)
            }
        }
    }

    fun loadBans() {
        scope.launch {
            _notice.value = null
            try {
                _bans.value = repo.adminBans()
                _error.value = null
            } catch (e: Exception) {
                handle(e)
            }
        }
    }

    fun addUser(username: String, password: String, role: String) =
        mutate("用户", reload = ::loadUsers) { repo.adminAddUser(username, password, role) }

    fun deleteUser(username: String) =
        mutate("删除", reload = ::loadUsers) { repo.adminDeleteUser(username) }

    fun setPassword(username: String, newPassword: String) =
        mutate("改密", reload = ::loadUsers) { repo.adminUserPassword(username, newPassword) }

    fun banUser(username: String) =
        mutate("禁用", reload = ::loadUsers) { repo.adminBanUser(username) }

    fun unbanUser(username: String) =
        mutate("解禁", reload = ::loadUsers) { repo.adminUnbanUser(username) }

    fun banIp(ip: String) =
        mutate("封禁", reload = ::loadBans) { repo.adminBanIp(ip) }

    fun unbanIp(ip: String) =
        mutate("解封", reload = ::loadBans) { repo.adminUnbanIp(ip) }

    /** 全员下线：成功后本会话令牌即失效，走 authEvent 回登录页（对应网页 backToLogin） */
    fun setAuthKey(newKey: String) {
        _error.value = null
        scope.launch {
            try {
                _authEvent.value = repo.setAuthKey(newKey) + "，请重新登录"
            } catch (e: AuthExpiredException) {
                _authEvent.value = e.message ?: "登录已过期"
            } catch (e: Exception) {
                _error.value = e.message ?: "保存失败"
            }
        }
    }

    fun exportLogs(start: String, end: String, onBytes: (ByteArray) -> Unit) {
        _error.value = null
        scope.launch {
            try {
                onBytes(repo.logsExport(start, end))
            } catch (e: AuthExpiredException) {
                _authEvent.value = e.message ?: "登录已过期"
            } catch (e: Exception) {
                _error.value = e.message ?: "导出失败"
            }
        }
    }

    private fun mutate(label: String, reload: () -> Unit, block: suspend () -> String) {
        _error.value = null
        _notice.value = null
        scope.launch {
            try {
                _notice.value = block()
                reload()
            } catch (e: AuthExpiredException) {
                _authEvent.value = e.message ?: "登录已过期"
            } catch (e: ApiException) {
                _error.value = e.message ?: "${label}失败"
            } catch (e: Exception) {
                _error.value = e.message ?: "${label}失败"
            }
        }
    }

    private fun handle(e: Throwable) {
        when (e) {
            is AuthExpiredException -> _authEvent.value = e.message ?: "登录已过期"
            else -> _error.value = e.message ?: "加载失败"
        }
    }
}

private enum class OpsTab(val label: String) {
    USERS("用户"), BANS("封禁"), KEY("密钥"), FILTERS("过滤"), LOGS("日志")
}

@Composable
fun OpsScreen(repository: AppRepository, session: Session, onAuthExpired: (String) -> Unit) {
    val spec = LocalSpec.current
    val context = LocalContext.current
    val model = rememberScreenModel(session.accountKey) { OpsModel(repository) }

    val users by model.users.collectAsState()
    val bans by model.bans.collectAsState()
    val error by model.error.collectAsState()
    val notice by model.notice.collectAsState()
    val auth by model.authEvent.collectAsState()

    var tab by remember(session.accountKey) { mutableStateOf(OpsTab.USERS) }
    var addOpen by remember { mutableStateOf(false) }
    var banOpen by remember { mutableStateOf(false) }
    var pwdFor by remember { mutableStateOf<String?>(null) }

    LaunchedEffect(auth) { auth?.let { onAuthExpired(it); model.clearAuth() } }
    LaunchedEffect(tab) { model.clearError() }

    Column(Modifier.fillMaxSize().padding(horizontal = spec.screenPadding.dp)) {
        // 五段做成一整条玻璃分段控件：选中段自身上玻璃，不靠分割线切区
        Row(
            Modifier
                .fillMaxWidth()
                .padding(top = 10.dp, bottom = spec.gap.dp)
                .bentoSurface(strong = true)
                .padding(5.dp),
            horizontalArrangement = Arrangement.spacedBy(5.dp),
        ) {
            OpsTab.entries.forEach { t ->
                CatButton(
                    text = t.label,
                    onClick = { tab = t },
                    modifier = Modifier.weight(1f),
                    variant = if (tab == t) CatButtonVariant.PRIMARY else CatButtonVariant.GHOST,
                    small = true,
                )
            }
        }

        Box(Modifier.weight(1f).fillMaxWidth()) {
            when (tab) {
                OpsTab.FILTERS -> FiltersEditor(isAdmin = true, repository, onAuthExpired)
                else -> SectionScroll {
                    InlineMsg(error, notice)
                    when (tab) {
                        OpsTab.USERS -> UsersSection(users, model,
                            onAdd = { addOpen = true },
                            onPassword = { pwdFor = it },
                        )
                        OpsTab.BANS -> BansSection(bans, model, onBan = { banOpen = true })
                        OpsTab.KEY -> KeySection(model)
                        OpsTab.LOGS -> LogsSection(model, context)
                        OpsTab.FILTERS -> {}
                    }
                }
            }
        }
    }

    if (addOpen) AddUserDialog(onDismiss = { addOpen = false }, onSubmit = { u, pw, role ->
        addOpen = false; model.addUser(u, pw, role)
    })
    if (banOpen) BanIpDialog(onDismiss = { banOpen = false }, onSubmit = { ip ->
        banOpen = false; model.banIp(ip)
    })
    pwdFor?.let { name ->
        ChangePasswordDialog(username = name, onDismiss = { pwdFor = null }, onSubmit = { pw ->
            pwdFor = null; model.setPassword(name, pw)
        })
    }
}

@Composable
private fun SectionScroll(content: @Composable () -> Unit) {
    val spec = LocalSpec.current
    val scroll = rememberScrollState()
    TrackBentoScroll(scroll)
    Column(
        Modifier
            .fillMaxSize()
            .verticalScroll(scroll)
            .padding(top = 2.dp, bottom = spec.bottomInset.dp + 12.dp),
        verticalArrangement = Arrangement.spacedBy(spec.gap.dp),
    ) { content() }
}

@Composable
private fun InlineMsg(error: String?, notice: String?) {
    val p = LocalPalette.current
    error?.let { Text(it, fontSize = 12.sp, color = p.red) }
    notice?.let { Text(it, fontSize = 12.sp, color = p.green) }
}

@Composable
private fun UsersSection(users: List<AdminUser>, model: OpsModel, onAdd: () -> Unit, onPassword: (String) -> Unit) {
    CatCard(Modifier.fillMaxWidth().bentoEnter(0)) {
        CatCardTitle("用户管理", trailing = {
            Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                CatButton("添加用户", onAdd, variant = CatButtonVariant.PRIMARY, icon = Icons.Filled.Add, small = true)
                CatButton("刷新", { model.loadUsers() }, variant = CatButtonVariant.GHOST, icon = Icons.Filled.Refresh, small = true)
            }
        })
        Text("管理员的改密、删除需在容器内用 adminctl 操作。", fontSize = 12.sp, color = LocalPalette.current.text3)

        if (users.isEmpty()) {
            Text("暂无用户", fontSize = 13.sp, color = LocalPalette.current.text3)
        }
        users.forEach { u ->
            Row(
                Modifier.fillMaxWidth().padding(vertical = 6.dp),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                Column(Modifier.weight(1f)) {
                    Text(u.username, fontSize = 14.sp, color = LocalPalette.current.text)
                    Text(u.createdAt.ifBlank { "-" }, fontSize = 12.sp, color = LocalPalette.current.text3)
                }
                Column(
                    horizontalAlignment = Alignment.End,
                    verticalArrangement = Arrangement.spacedBy(4.dp),
                ) {
                    Row(horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                        CatBadge(if (u.isAdmin) "管理员" else "用户", if (u.isAdmin) CatTone.PRIMARY else CatTone.NEUTRAL)
                        CatBadge(if (u.disabled) "已禁用" else "正常", if (u.disabled) CatTone.RED else CatTone.GREEN)
                    }
                    if (u.isAdmin) {
                        // 管理员只给禁用态按钮 + 提示，避免误触
                        Row(horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                            CatButton("改密", {}, variant = CatButtonVariant.GHOST, small = true, enabled = false)
                            CatButton(if (u.disabled) "解禁" else "禁用", {}, variant = CatButtonVariant.GHOST, small = true, enabled = false)
                            CatButton("删除", {}, variant = CatButtonVariant.DANGER, small = true, enabled = false)
                        }
                        Text("请用 adminctl 管理", fontSize = 12.sp, color = LocalPalette.current.text3)
                    } else {
                        Row(horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                            CatButton("改密", { onPassword(u.username) }, variant = CatButtonVariant.GHOST, small = true)
                            CatButton(
                                if (u.disabled) "解禁" else "禁用",
                                { if (u.disabled) model.unbanUser(u.username) else model.banUser(u.username) },
                                variant = CatButtonVariant.GHOST, small = true,
                            )
                            // 按用户名 keying：删除后列表重排，气泡不会串到下一行造成误删
                            key(u.username) {
                                CatConfirmButton(
                                    "删除",
                                    "删除 ${u.username}？",
                                    { model.deleteUser(u.username) },
                                    small = true,
                                    detail = "连账号带其任务、聊天记录一起从服务器上抹掉，不可恢复。要临时停用请改用「禁用」。",
                                )
                            }
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun BansSection(bans: List<BanEntry>, model: OpsModel, onBan: () -> Unit) {
    CatCard(Modifier.fillMaxWidth().bentoEnter(0)) {
        CatCardTitle("IP 封禁管理", trailing = {
            Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                CatButton("封禁 IP", onBan, variant = CatButtonVariant.PRIMARY, icon = Icons.Filled.Add, small = true)
                CatButton("刷新", { model.loadBans() }, variant = CatButtonVariant.GHOST, icon = Icons.Filled.Refresh, small = true)
            }
        })
        if (bans.isEmpty()) {
            Text("当前没有被封禁的 IP", fontSize = 13.sp, color = LocalPalette.current.text3)
        }
        bans.forEach { b ->
            Row(
                Modifier.fillMaxWidth().padding(vertical = 6.dp),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                Column(Modifier.weight(1f)) {
                    Text(b.ip, fontSize = 14.sp, color = LocalPalette.current.text)
                    Text(b.bannedAt.ifBlank { "-" }, fontSize = 12.sp, color = LocalPalette.current.text3)
                }
                CatBadge(b.reasonLabel, banTone(b.reason))
                key(b.ip) {
                    CatConfirmButton(
                        "解封",
                        "解封 ${b.ip}？",
                        { model.unbanIp(b.ip) },
                        small = true,
                        detail = "解封后该 IP 立即可重新访问服务器；若仍触发风控会被再次自动封禁。",
                    )
                }
            }
        }
    }
}

private fun banTone(reason: String): CatTone = when (reason) {
    "auto" -> CatTone.GREEN
    "auto_perm" -> CatTone.PRIMARY
    "manual" -> CatTone.AMBER
    else -> CatTone.NEUTRAL
}

@Composable
private fun KeySection(model: OpsModel) {
    val p = LocalPalette.current
    var newKey by remember { mutableStateOf("") }
    var localErr by remember { mutableStateOf<String?>(null) }
    val modelErr by model.error.collectAsState()

    CatCard(Modifier.fillMaxWidth().bentoEnter(0)) {
        CatCardTitle("服务器配置")
        Text(
            "⚠️ 更换后：猫抓插件的 key 需同步更新，网页需重新登录。",
            fontSize = 12.sp,
            color = p.amber,
            modifier = Modifier.fillMaxWidth().background(p.amberSoft, catCardShape()).padding(12.dp),
        )
        // 只读：值仅由「随机」生成；网页不展示当前/掩码密钥，这里同样不展示
        CatField(
            value = newKey,
            onValueChange = {},
            label = "新 AUTH_KEY",
            enabled = false,
            helper = "点击「随机」按钮自动生成",
            trailingIcon = {
                CatButton("随机", { newKey = randomAuthKey() }, variant = CatButtonVariant.GHOST, small = true)
            },
        )
        localErr?.let { Text(it, fontSize = 12.sp, color = p.red) }
        modelErr?.let { Text(it, fontSize = 12.sp, color = p.red) }
        CatConfirmButton(
            text = "保存并全员下线",
            confirmText = "更换密钥并强制全员下线？",
            detail = "所有客户端持有的旧令牌立即失效，需要重新登录才能继续访问。",
            onConfirm = {
                if (newKey.isBlank()) localErr = "请先点击「随机」生成 AUTH_KEY"
                else { localErr = null; model.setAuthKey(newKey) }
            },
            modifier = Modifier.fillMaxWidth(),
        )
    }
}

@Composable
private fun LogsSection(model: OpsModel, context: Context) {
    val p = LocalPalette.current
    val today = remember { DateFormatter.today() }
    var start by remember { mutableStateOf(today) }
    var end by remember { mutableStateOf(today) }
    var localErr by remember { mutableStateOf<String?>(null) }
    val modelErr by model.error.collectAsState()

    CatCard(Modifier.fillMaxWidth().bentoEnter(0)) {
        CatCardTitle("日志导出")
        Text("📅 单次最多导出 15 天，无日志的日期自动跳过。", fontSize = 12.sp, color = p.amber)
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            CatField(
                value = start,
                onValueChange = { start = it },
                label = "开始日期",
                modifier = Modifier.weight(1f),
                helper = "yyyy-MM-dd",
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
            )
            CatField(
                value = end,
                onValueChange = { end = it },
                label = "结束日期",
                modifier = Modifier.weight(1f),
                helper = "yyyy-MM-dd",
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
            )
        }
        localErr?.let { Text(it, fontSize = 12.sp, color = p.red) }
        modelErr?.let { Text(it, fontSize = 12.sp, color = p.red) }
        CatButton(
            text = "导出日志",
            onClick = {
                localErr = validateRange(start, end, today)
                if (localErr == null) {
                    model.exportLogs(start, end) { bytes -> shareTextFile(context, bytes, "log_export.log") }
                }
            },
            modifier = Modifier.fillMaxWidth(),
        )
    }
}

// yyyy-MM-dd 字符串可直接字典序比较，起止/未来判定无需解析
private fun validateRange(start: String, end: String, today: String): String? {
    if (!DATE_RE.matches(start) || !DATE_RE.matches(end)) return "日期格式应为 yyyy-MM-dd"
    if (start > end) return "开始日期不能晚于结束日期"
    if (end > today) return "不能导出未来日期的日志"
    val span = DateFormatter.daySpan(start, end) ?: return "日期无效"
    if (span > 15) return "导出范围不能超过 15 天"
    return null
}

private val DATE_RE = Regex("""\d{4}-\d{2}-\d{2}""")

private object DateFormatter {
    private val fmt = SimpleDateFormat("yyyy-MM-dd", Locale.US)
    fun today(): String = fmt.format(Date())
    fun daySpan(start: String, end: String): Int? = runCatching {
        val s = fmt.parse(start)!!.time
        val e = fmt.parse(end)!!.time
        ((e - s) / 86_400_000L).toInt() + 1
    }.getOrNull()
}

/** 14 位密钥：≥1 大写 / 小写 / 数字，1-3 符号，余下取字母数字，Fisher-Yates 洗牌（对齐网页 genRandomKey） */
private fun randomAuthKey(): String {
    val upper = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    val lower = "abcdefghijklmnopqrstuvwxyz"
    val digit = "0123456789"
    val symbol = "!@#$%^&*"
    val all = upper + lower + digit
    val rnd = SecureRandom()
    fun pick(set: String) = set[rnd.nextInt(set.length)]
    val chars = mutableListOf(pick(upper), pick(lower), pick(digit))
    repeat(1 + rnd.nextInt(3)) { chars.add(pick(symbol)) }
    while (chars.size < 14) chars.add(pick(all))
    for (j in chars.size - 1 downTo 1) {
        val k = rnd.nextInt(j + 1)
        val t = chars[j]; chars[j] = chars[k]; chars[k] = t
    }
    return chars.joinToString("")
}

@Composable
private fun AddUserDialog(onDismiss: () -> Unit, onSubmit: (String, String, String) -> Unit) {
    var username by remember { mutableStateOf("") }
    var pwd by remember { mutableStateOf("") }
    var pwd2 by remember { mutableStateOf("") }
    var admin by remember { mutableStateOf(false) }
    var errU by remember { mutableStateOf<String?>(null) }
    var errP by remember { mutableStateOf<String?>(null) }
    var errP2 by remember { mutableStateOf<String?>(null) }

    BentoDialog(onDismiss) {
        BentoDialogTitle("添加用户")
        Row(
            Modifier.fillMaxWidth(),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            CatSwitch(checked = admin, onCheckedChange = { admin = it })
            Text("添加为管理员", fontSize = 13.sp, color = LocalPalette.current.text2)
        }
        CatField(username, { username = it }, "用户名", error = errU, helper = "字母+数字，字母≥4 位")
        CatField(pwd, { pwd = it }, "密码", error = errP, visualTransformation = PasswordVisualTransformation())
        CatField(pwd2, { pwd2 = it }, "确认密码", error = errP2, visualTransformation = PasswordVisualTransformation())
        BentoDialogButtons(
            confirmText = "确定",
            onConfirm = {
                errU = if (username.isBlank()) "用户名不能为空" else null
                errP = if (pwd.length < 6) "密码至少 6 位" else null
                errP2 = if (pwd != pwd2) "两次输入的密码不一致" else null
                if (errU == null && errP == null && errP2 == null) onSubmit(username.trim(), pwd, if (admin) "admin" else "user")
            },
            dismissText = "取消",
            onDismiss = onDismiss,
        )
    }
}

@Composable
private fun ChangePasswordDialog(username: String, onDismiss: () -> Unit, onSubmit: (String) -> Unit) {
    var pwd by remember { mutableStateOf("") }
    var pwd2 by remember { mutableStateOf("") }
    var errP by remember { mutableStateOf<String?>(null) }
    var errP2 by remember { mutableStateOf<String?>(null) }

    BentoDialog(onDismiss) {
        BentoDialogTitle("改密 - $username")
        CatField(pwd, { pwd = it }, "新密码", error = errP, visualTransformation = PasswordVisualTransformation())
        CatField(pwd2, { pwd2 = it }, "确认新密码", error = errP2, visualTransformation = PasswordVisualTransformation())
        BentoDialogButtons(
            confirmText = "确定",
            onConfirm = {
                errP = if (pwd.length < 6) "密码至少 6 位" else null
                errP2 = if (pwd != pwd2) "两次输入的密码不一致" else null
                if (errP == null && errP2 == null) onSubmit(pwd)
            },
            dismissText = "取消",
            onDismiss = onDismiss,
        )
    }
}

@Composable
private fun BanIpDialog(onDismiss: () -> Unit, onSubmit: (String) -> Unit) {
    var ip by remember { mutableStateOf("") }
    var err by remember { mutableStateOf<String?>(null) }

    BentoDialog(onDismiss) {
        BentoDialogTitle("封禁 IP")
        CatField(ip, { ip = it }, "IP 地址（IPv4 / IPv6）", error = err, helper = "如 192.168.1.100")
        BentoDialogButtons(
            confirmText = "确定",
            onConfirm = {
                err = if (ip.isBlank()) "IP 地址不能为空" else null
                if (err == null) onSubmit(ip.trim())
            },
            dismissText = "取消",
            onDismiss = onDismiss,
        )
    }
}
