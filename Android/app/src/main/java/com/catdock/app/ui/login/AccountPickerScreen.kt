package com.catdock.app.ui.login

import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowRight
import androidx.compose.material.icons.filled.Add
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.key
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.catdock.app.R
import com.catdock.app.data.ApiException
import com.catdock.app.data.AppRepository
import com.catdock.app.data.SavedAccount
import com.catdock.app.data.Session
import com.catdock.app.data.SessionStore
import com.catdock.app.ui.components.BentoBackdrop
import com.catdock.app.ui.components.CatBadge
import com.catdock.app.ui.components.CatButton
import com.catdock.app.ui.components.CatButtonVariant
import com.catdock.app.ui.components.CatCard
import com.catdock.app.ui.components.CatTone
import com.catdock.app.ui.components.bentoEnter
import com.catdock.app.ui.components.bentoPress
import com.catdock.app.ui.components.bentoSurface
import com.catdock.app.ui.theme.LocalPalette
import com.catdock.app.ui.theme.LocalSpec
import com.catdock.app.ui.theme.catControlShape
import kotlinx.coroutines.launch

/**
 * 账号选择页（启动页）：
 *  - 已登录过就记录下来：点已有账号，令牌有效直接进主界面，令牌失效用本地加密密码静默重登
 *  - 只在本机记录账号、没有密码的条目，点它进登录页（服务器地址 / KEY / 用户名已预填）
 *  - 底部「新用户登录」进空表单
 * 删除账号统一在「我的 → 切换账号」里，这里只负责进
 */
@Composable
fun AccountPickerScreen(
    repository: AppRepository,
    sessionStore: SessionStore,
    accounts: List<SavedAccount>,
    session: Session,
    onEnterApp: () -> Unit,
    onNeedPassword: () -> Unit,
    onNewLogin: () -> Unit,
) {
    val p = LocalPalette.current
    val spec = LocalSpec.current
    val scope = rememberCoroutineScope()

    // 没有令牌的账号是否还存着密码（决定点它时静默重登还是补密码）
    var pwdKeys by remember { mutableStateOf<Set<String>>(emptySet()) }
    var busyKey by remember { mutableStateOf("") }
    var error by remember { mutableStateOf<String?>(null) }

    LaunchedEffect(accounts) {
        pwdKeys = accounts
            .filter { it.token.isEmpty() }
            .filter { sessionStore.credentialsFor(it.key)?.second?.isNotBlank() == true }
            .map { it.key }
            .toSet()
    }

    fun pick(acc: SavedAccount) {
        if (busyKey.isNotEmpty()) return
        error = null
        // 令牌仍有效：切号即进主界面，不打扰用户
        if (acc.token.isNotEmpty()) {
            scope.launch {
                sessionStore.switchAccount(acc)
                onEnterApp()
            }
            return
        }
        busyKey = acc.key
        scope.launch {
            try {
                val cred = sessionStore.credentialsFor(acc.key)
                if (cred == null || cred.second.isBlank()) {
                    // 没存密码：切到该账号，登录页带上服务器 / KEY / 用户名
                    sessionStore.switchAccount(acc)
                    onNeedPassword()
                } else {
                    repository.login(
                        serverUrl = acc.serverUrl,
                        prefix = acc.urlPrefix,
                        key = cred.first,
                        user = acc.username,
                        password = cred.second,
                        trustAll = acc.trustAll,
                    )
                    onEnterApp()
                }
            } catch (e: ApiException) {
                // 服务端拒绝：只清密码保留 KEY，用户补密码即可
                sessionStore.forgetPassword(acc.key)
                pwdKeys = pwdKeys - acc.key
                error = "${acc.username}：${e.message}"
            } catch (e: Exception) {
                error = "无法连接服务器：${e.message ?: "网络错误"}"
            } finally {
                busyKey = ""
            }
        }
    }

    Box(Modifier.fillMaxSize()) {
        // 登录页没有正文遮挡，光斑抬一档，玻璃才透得出东西
        BentoBackdrop(blobLift = 1.35f)
        Column(
            Modifier
                .fillMaxSize()
                .verticalScroll(rememberScrollState())
                .statusBarsPadding()
                .padding(horizontal = spec.screenPadding.dp)
                // 底部多留 96dp：整块内容在剩余空间里居中偏上，不贴着屏幕正中
                .padding(top = spec.topInset.dp, bottom = spec.bottomInset.dp + 96.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.Center,
        ) {
            Row(
                Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(10.dp),
            ) {
                Box(
                    Modifier
                        .size(spec.minTouch.dp)
                        .bentoSurface(shape = catControlShape(), emphasis = true, strong = true),
                    contentAlignment = Alignment.Center,
                ) {
                    Image(
                        painter = painterResource(R.drawable.ic_account_picker_logo),
                        contentDescription = null,
                        modifier = Modifier.size(32.dp),
                    )
                }
                Column(Modifier.weight(1f)) {
                    Text("catdock", fontSize = 28.sp, fontWeight = FontWeight.Black, color = p.primary)
                    Text("选择账号继续", fontSize = 13.sp, color = p.text2)
                }
            }

            CatCard(
                Modifier
                    .fillMaxWidth()
                    .padding(top = 16.dp)
                    .bentoEnter(0),
                verticalArrangement = Arrangement.spacedBy(2.dp),
            ) {
                accounts.forEachIndexed { index, acc ->
                    key(acc.key) {
                        val active = acc.key == session.accountKey
                        val hasPassword = acc.key in pwdKeys
                        AccountRow(
                            acc = acc,
                            active = active,
                            hasPassword = hasPassword,
                            busy = busyKey == acc.key,
                            onClick = { pick(acc) },
                            enterIndex = index + 1,
                        )
                    }
                }
            }

            error?.let {
                Text(it, fontSize = 13.sp, color = p.red, modifier = Modifier.padding(top = 10.dp))
            }

            CatButton(
                text = "新用户登录",
                onClick = onNewLogin,
                modifier = Modifier.fillMaxWidth().padding(top = 16.dp),
                variant = CatButtonVariant.GHOST,
                icon = Icons.Filled.Add,
            )
            Text(
                "登录过的账号自动记住密码；要删除账号请到「我的 → 切换账号」",
                fontSize = 12.sp,
                color = p.text3,
                modifier = Modifier.padding(top = 10.dp),
            )
        }
    }
}

@Composable
private fun AccountRow(
    acc: SavedAccount,
    active: Boolean,
    hasPassword: Boolean,
    busy: Boolean,
    onClick: () -> Unit,
    enterIndex: Int,
) {
    val p = LocalPalette.current
    val spec = LocalSpec.current
    val ready = acc.token.isNotEmpty() || hasPassword
    Row(
        Modifier
            .fillMaxWidth()
            .bentoEnter(enterIndex)
            .bentoPress(
                onClick = onClick,
                enabled = !busy,
                emphasis = active,
                minHeight = spec.minTouch.dp,
            )
            .padding(horizontal = 6.dp, vertical = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        Box(
            Modifier
                .size(40.dp)
                .background(p.primarySoft, CircleShape)
                .border(1.dp, p.primary.copy(alpha = 0.28f), CircleShape),
            contentAlignment = Alignment.Center,
        ) {
            Text(
                acc.username.take(1).uppercase(),
                fontSize = 16.sp,
                fontWeight = FontWeight.Bold,
                color = p.primary,
            )
        }
        Column(Modifier.weight(1f)) {
            Text(
                acc.username,
                fontSize = 15.sp,
                fontWeight = if (active) FontWeight.Bold else FontWeight.Medium,
                color = p.text,
                maxLines = 1,
            )
            Text(
                buildString {
                    append("${acc.serverUrl.trimEnd('/')}/${acc.urlPrefix}")
                    append(" · ${if (acc.role == "admin") "管理员" else "下载用户"}")
                },
                fontSize = 12.sp,
                color = p.text3,
                maxLines = 1,
            )
        }
        when {
            busy -> CircularProgressIndicator(
                modifier = Modifier.size(16.dp),
                strokeWidth = 2.dp,
                color = p.primary,
            )

            ready -> CatBadge(
                if (acc.token.isNotEmpty()) "已登录" else "记住密码",
                if (acc.token.isNotEmpty()) CatTone.GREEN else CatTone.BLUE,
            )

            else -> CatBadge("需密码", CatTone.AMBER)
        }
        Icon(
            Icons.AutoMirrored.Filled.KeyboardArrowRight,
            contentDescription = null,
            modifier = Modifier.size(18.dp),
            tint = p.text3,
        )
    }
}
