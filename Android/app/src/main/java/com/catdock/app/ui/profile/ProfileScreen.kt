package com.catdock.app.ui.profile

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.Logout
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Lock
import androidx.compose.material.icons.filled.SwitchAccount
import androidx.compose.material.icons.filled.Tune
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.key
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.catdock.app.CatdockApp
import com.catdock.app.data.ApiException
import com.catdock.app.data.AppRepository
import com.catdock.app.data.AuthExpiredException
import com.catdock.app.data.SavedAccount
import com.catdock.app.data.ServerConfig
import com.catdock.app.data.Session
import com.catdock.app.data.SessionStore
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
import com.catdock.app.ui.components.CatTone
import com.catdock.app.ui.components.TrackBentoScroll
import com.catdock.app.ui.components.bentoEnter
import com.catdock.app.ui.components.bentoPress
import com.catdock.app.ui.components.catNumeric
import com.catdock.app.ui.filters.FiltersEditor
import com.catdock.app.ui.theme.Appearance
import com.catdock.app.ui.theme.LocalPalette
import com.catdock.app.ui.theme.LocalSpec
import com.catdock.app.ui.theme.ModePreference
import kotlinx.coroutines.launch

/**
 * 「我的」页：账号 / 外观 / 服务信息 / 本人过滤规则 / 修改密码 / 切换账号 / 退出。
 * 范围对齐网页端——顶栏用户菜单只有 修改密码·切换用户·过滤规则·退出，
 * user.html 另有一张服务信息卡，此外不再展示任何统计项。
 */
@Composable
fun ProfileScreen(
    repository: AppRepository,
    sessionStore: SessionStore,
    session: Session,
    onAuthExpired: (String) -> Unit,
    onAddAccount: () -> Unit,
) {
    val p = LocalPalette.current
    val spec = LocalSpec.current
    val app = LocalContext.current.applicationContext as CatdockApp
    val scope = rememberCoroutineScope()
    val appearance by app.appearanceStore.appearance.collectAsState(initial = Appearance())
    val accounts by sessionStore.accounts.collectAsState(initial = emptyList())
    // 按账号 keying：切号后不残留上一账号的服务端数据与提示
    var config by remember(session.accountKey) { mutableStateOf<ServerConfig?>(null) }
    var showChangePwd by remember { mutableStateOf(false) }
    var showSwitcher by remember { mutableStateOf(false) }
    var showFilters by remember(session.accountKey) { mutableStateOf(false) }
    LaunchedEffect(session.accountKey) {
        try {
            config = repository.serverConfig()
        } catch (e: AuthExpiredException) {
            onAuthExpired(e.message ?: "登录已过期")
        } catch (e: Exception) {
            // 信息卡加载失败不阻塞页面
        }
    }

    val scroll = rememberScrollState()
    TrackBentoScroll(scroll)

    Column(
        Modifier
            .fillMaxSize()
            .verticalScroll(scroll)
            .padding(horizontal = spec.screenPadding.dp)
            .padding(top = spec.topInset.dp - 8.dp, bottom = spec.bottomInset.dp + 16.dp),
        verticalArrangement = Arrangement.spacedBy(spec.gap.dp),
    ) {
        // 首屏左上黄金区放最高权重信息：当前账号与角色
        CatCard(
            Modifier
                .fillMaxWidth()
                .bentoEnter(0),
        ) {
            Row(
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                Column(Modifier.weight(1f)) {
                    Text(
                        session.username,
                        fontSize = 19.sp,
                        fontWeight = FontWeight.Bold,
                        color = p.text,
                        maxLines = 1,
                    )
                    Text(
                        "${session.serverUrl.trimEnd('/')}/${session.urlPrefix}",
                        fontSize = 12.sp,
                        color = p.text3,
                        maxLines = 1,
                    )
                }
                CatBadge(
                    if (session.isAdmin) "管理员" else "下载用户",
                    if (session.isAdmin) CatTone.PRIMARY else CatTone.NEUTRAL,
                )
            }
        }

        CatCard(
            Modifier
                .fillMaxWidth()
                .bentoEnter(1),
        ) {
            CatCardTitle("外观", modifier = Modifier.padding(bottom = 4.dp))
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(spec.gap.dp)) {
                ModePreference.entries.forEach { m ->
                    CatButton(
                        text = m.label,
                        onClick = { scope.launch { app.appearanceStore.setMode(m) } },
                        modifier = Modifier.weight(1f),
                        variant = if (appearance.mode == m) CatButtonVariant.PRIMARY else CatButtonVariant.GHOST,
                        small = true,
                    )
                }
            }
            Text("柔黄浅蓝 / 乌木鎏金两套配色，这里只切亮暗", fontSize = 12.sp, color = p.text3)
        }

        CatCard(
            Modifier
                .fillMaxWidth()
                .bentoEnter(2),
            verticalArrangement = Arrangement.spacedBy(2.dp),
        ) {
            CatCardTitle("服务信息", modifier = Modifier.padding(bottom = 8.dp))
            config?.let { c ->
                InfoRow("版本", c.version.ifEmpty { "未知" })
                InfoRow("端口", c.apiPort.toString())
                InfoRow("URL 前缀", c.urlPrefix.ifEmpty { "(无)" })
                InfoRow("SSRF 防护", onOff(c.ssrfProtection), ok = c.ssrfProtection)
                InfoRow("单用户并发", "${c.maxConcurrentTasks}")
                InfoRow("全局运行上限", "${c.maxTotalRunning}")
                InfoRow("同视频聚合", onOff(c.sameVideoMode), ok = c.sameVideoMode)
                InfoRow("下载用户数", if (c.userCount > 0) "${c.userCount} 个" else "未创建")
                // 分组靠留白，不画分割线
                Spacer(Modifier.height(10.dp))
                InfoRow("广告拦截", "${onOff(c.keywordsEnabled)}（${c.adKeywordCount} 条）", ok = c.keywordsEnabled)
                InfoRow("文件名过滤", "${onOff(c.filenameFilterEnabled)}（${c.filenameFilterCount} 条）", ok = c.filenameFilterEnabled)
                InfoRow("正则去重", "${onOff(c.filenameDedupEnabled)}（${c.filenameDedupCount} 条）", ok = c.filenameDedupEnabled)
            } ?: Text("配置信息加载中…", fontSize = 12.sp, color = p.text3)
        }

        // 管理员的过滤模板在「运维」页，这里只给下载用户本人规则
        if (!session.isAdmin) {
            CatCard(
                Modifier
                    .fillMaxWidth()
                    .bentoEnter(3),
                verticalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                CatButton(
                    text = if (showFilters) "收起过滤规则" else "我的过滤规则",
                    onClick = { showFilters = !showFilters },
                    modifier = Modifier.fillMaxWidth(),
                    variant = CatButtonVariant.GHOST,
                    icon = Icons.Filled.Tune,
                )
                Text(
                    if (showFilters) "规则只作用于本账号，保存后立即生效" else "展开编辑拦截关键字 / 文件名过滤 / 去重规则",
                    fontSize = 12.sp,
                    color = p.text3,
                )
            }
            if (showFilters) {
                FiltersEditor(
                    isAdmin = false,
                    repository = repository,
                    onAuthExpired = onAuthExpired,
                )
            }
        }

        // 次要/危险入口统一沉到底部操作区，留出单手可及的位置
        CatCard(
            Modifier
                .fillMaxWidth()
                .bentoEnter(4),
        ) {
            CatCardTitle("登录与安全", modifier = Modifier.padding(bottom = 4.dp))
            CatButton(
                text = "修改密码",
                onClick = { showChangePwd = true },
                modifier = Modifier.fillMaxWidth(),
                variant = CatButtonVariant.GHOST,
                icon = Icons.Filled.Lock,
            )
            Text("修改成功后服务端吊销全部令牌，所有设备都要重新登录", fontSize = 12.sp, color = p.text3)
            CatButton(
                text = "切换账号",
                onClick = { showSwitcher = true },
                modifier = Modifier.fillMaxWidth(),
                variant = CatButtonVariant.GHOST,
                icon = Icons.Filled.SwitchAccount,
            )
            Spacer(Modifier.height(4.dp))
            CatConfirmButton(
                text = "退出登录",
                confirmText = "退出后需重新登录",
                detail = "本机保存的登录态会被清除，下次进入要重新输入账号密码。",
                onConfirm = {
                    scope.launch {
                        repository.logout()
                        onAuthExpired("已注销")
                    }
                },
                modifier = Modifier.fillMaxWidth(),
                icon = Icons.AutoMirrored.Filled.Logout,
            )
        }
    }

    if (showChangePwd) {
        ChangePasswordDialog(
            onDismiss = { showChangePwd = false },
            onSubmit = { oldPwd, newPwd, onResult ->
                scope.launch {
                    try {
                        repository.changePassword(oldPwd, newPwd)
                        // 改密后旧令牌全废，本地会话留着也没有意义
                        onResult(null)
                        onAuthExpired("密码已修改，请重新登录")
                    } catch (e: AuthExpiredException) {
                        onResult(null)
                        onAuthExpired(e.message ?: "登录已过期")
                    } catch (e: ApiException) {
                        onResult(e.message ?: "修改失败")
                    } catch (e: Exception) {
                        onResult("网络错误：${e.message ?: ""}")
                    }
                }
            },
        )
    }

    if (showSwitcher) {
        AccountSwitcherDialog(
            accounts = accounts,
            session = session,
            onDismiss = { showSwitcher = false },
            onSwitch = { acc ->
                showSwitcher = false
                scope.launch { sessionStore.switchAccount(acc) }
            },
            onRemove = { acc -> scope.launch { sessionStore.removeAccount(acc) } },
            onAdd = {
                showSwitcher = false
                onAddAccount()
            },
        )
    }
}

/** 网页 `.info-item`：值 500 字重；开关类值按 `.val.on` / `.val.off` 上绿 / 上灰 */
@Composable
private fun InfoRow(label: String, value: String, ok: Boolean? = null) {
    val p = LocalPalette.current
    val color = when (ok) {
        true -> p.green
        false -> p.text3
        null -> p.text
    }
    Row(Modifier.fillMaxWidth().padding(vertical = 5.dp)) {
        Text(label, fontSize = 13.sp, color = p.text2, modifier = Modifier.weight(1f))
        Text(value, style = catNumeric(13, color, FontWeight.Medium))
    }
}

private fun onOff(enabled: Boolean) = if (enabled) "开启" else "关闭"

/** 修改密码：旧密码 1 遍 + 新密码 2 遍（与网页端一致），新密码至少 6 位 */
@Composable
private fun ChangePasswordDialog(
    onDismiss: () -> Unit,
    onSubmit: (old: String, new: String, onResult: (String?) -> Unit) -> Unit,
) {
    val p = LocalPalette.current
    var old by remember { mutableStateOf("") }
    var new1 by remember { mutableStateOf("") }
    var new2 by remember { mutableStateOf("") }
    var err by remember { mutableStateOf<String?>(null) }
    var busy by remember { mutableStateOf(false) }
    val pwdOptions = KeyboardOptions(keyboardType = KeyboardType.Password)

    BentoDialog(onDismiss) {
        BentoDialogTitle("修改密码")
        CatField(
            old,
            { old = it },
            "旧密码",
            visualTransformation = PasswordVisualTransformation(),
            keyboardOptions = pwdOptions,
        )
        CatField(
            new1,
            { new1 = it },
            "新密码（至少 6 位）",
            visualTransformation = PasswordVisualTransformation(),
            keyboardOptions = pwdOptions,
        )
        CatField(
            new2,
            { new2 = it },
            "再次输入新密码",
            visualTransformation = PasswordVisualTransformation(),
            keyboardOptions = pwdOptions,
        )
        err?.let { Text(it, fontSize = 12.sp, color = p.red) }
        BentoDialogButtons(
            confirmText = if (busy) "提交中…" else "确认修改",
            onConfirm = {
                when {
                    old.isEmpty() || new1.isEmpty() -> err = "请填写完整"
                    new1.length < 6 -> err = "新密码至少 6 位"
                    new1 != new2 -> err = "两次输入的新密码不一致"
                    else -> {
                        err = null
                        busy = true
                        onSubmit(old, new1) { e ->
                            busy = false
                            err = e
                            if (e == null) onDismiss()
                        }
                    }
                }
            },
            dismissText = "取消",
            onDismiss = onDismiss,
            confirmEnabled = !busy,
        )
    }
}

@Composable
private fun AccountSwitcherDialog(
    accounts: List<SavedAccount>,
    session: Session,
    onDismiss: () -> Unit,
    onSwitch: (SavedAccount) -> Unit,
    onRemove: (SavedAccount) -> Unit,
    onAdd: () -> Unit,
) {
    val p = LocalPalette.current
    val spec = LocalSpec.current
    BentoDialog(onDismiss) {
        BentoDialogTitle("切换账号")
        if (accounts.isEmpty()) {
            Text("还没有保存的账号", fontSize = 12.sp, color = p.text3)
        }
        accounts.forEach { acc ->
            // 按账号 keying：删除一条后行序前移，气泡的 pending 状态不会串到下一个账号
            key(acc.key) {
                val active = acc.key == session.accountKey
                Row(
                    Modifier
                        .fillMaxWidth()
                        .bentoPress(
                            onClick = { if (!active) onSwitch(acc) },
                            enabled = !active,
                            emphasis = active,
                            minHeight = spec.minTouch.dp,
                        )
                        .padding(horizontal = 12.dp, vertical = 8.dp),
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    Column(Modifier.weight(1f)) {
                        Text(
                            acc.username + if (active) "（当前）" else "",
                            fontSize = 14.sp,
                            fontWeight = if (active) FontWeight.Bold else FontWeight.Normal,
                            color = p.text,
                        )
                        Text(
                            buildString {
                                append("${acc.serverUrl.trimEnd('/')}/${acc.urlPrefix}")
                                append(" · ${if (acc.role == "admin") "管理员" else "下载用户"}")
                                // 令牌为空只是本地未存，条目仍在，切过去由登录页预填
                                if (acc.token.isEmpty()) append(" · 需重新登录")
                            },
                            fontSize = 12.sp,
                            color = p.text3,
                        )
                    }
                    if (!active) {
                        CatConfirmButton(
                            text = "删除",
                            confirmText = "删除该账号？",
                            onConfirm = { onRemove(acc) },
                            small = true,
                            detail = "只是从这个 App 里移除本机登录态，服务器上的账号和数据都不受影响。",
                        )
                    }
                }
            }
        }
        Spacer(Modifier.height(4.dp))
        CatButton(
            text = "添加新账号",
            onClick = onAdd,
            modifier = Modifier.fillMaxWidth(),
            variant = CatButtonVariant.GHOST,
            icon = Icons.Filled.Add,
        )
        Row(
            Modifier.fillMaxWidth(),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(6.dp),
        ) {
            Icon(
                Icons.Filled.SwitchAccount,
                contentDescription = null,
                modifier = Modifier.size(14.dp),
                tint = p.text3,
            )
            Text("点账号即切换", fontSize = 12.sp, color = p.text3, modifier = Modifier.weight(1f))
            CatButton(text = "关闭", onClick = onDismiss, variant = CatButtonVariant.GHOST, small = true)
        }
    }
}
