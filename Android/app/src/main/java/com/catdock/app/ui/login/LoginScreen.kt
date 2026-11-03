package com.catdock.app.ui.login

import androidx.compose.foundation.Image
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
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Visibility
import androidx.compose.material.icons.filled.VisibilityOff
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.catdock.app.R
import com.catdock.app.data.ApiException
import com.catdock.app.data.AppRepository
import com.catdock.app.data.Session
import com.catdock.app.data.SessionStore
import com.catdock.app.ui.components.BentoBackdrop
import com.catdock.app.ui.components.CatButton
import com.catdock.app.ui.components.CatButtonVariant
import com.catdock.app.ui.components.CatCard
import com.catdock.app.ui.components.CatField
import com.catdock.app.ui.components.CatSwitch
import com.catdock.app.ui.components.bentoEnter
import com.catdock.app.ui.components.bentoSurface
import com.catdock.app.ui.theme.LocalPalette
import com.catdock.app.ui.theme.LocalSpec
import com.catdock.app.ui.theme.catControlShape
import kotlinx.coroutines.launch

/**
 * 登录页：服务器完整链接（含 URL 前缀）+ AUTH_KEY + 用户名/密码，
 * 与服务器两层认证（key → user/password）一一对应。
 * 从「我的→添加新账号」进入时带返回。
 */
@Composable
fun LoginScreen(
    repository: AppRepository,
    sessionStore: SessionStore,
    addingAccount: Boolean = false,
    onCancelAdd: () -> Unit = {},
    onLoggedIn: () -> Unit,
) {
    val p = LocalPalette.current
    val spec = LocalSpec.current
    val saved by sessionStore.session.collectAsState(initial = Session())

    var server by remember(saved) {
        mutableStateOf(
            if (saved.serverUrl.isEmpty()) ""
            else saved.serverUrl.trimEnd('/') + "/" + saved.urlPrefix,
        )
    }
    var key by remember { mutableStateOf("") }
    var user by remember(saved) { mutableStateOf(saved.username) }
    var password by remember { mutableStateOf("") }
    var trustAll by remember(saved) { mutableStateOf(saved.trustAllCerts) }
    var showPwd by remember { mutableStateOf(false) }
    var loading by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    val scope = rememberCoroutineScope()

    fun submit() {
        if (loading) return
        error = null
        if (server.isBlank() || key.isBlank() || user.isBlank() || password.isBlank()) {
            error = "请填写完整登录信息"
            return
        }
        // 解析完整链接：{scheme}://{host:port}/{prefix}
        var url = server.trim().trimEnd('/')
        if (!url.startsWith("http://") && !url.startsWith("https://")) url = "http://$url"
        val schemeEnd = url.indexOf("://") + 3
        val pathStart = url.indexOf('/', schemeEnd)
        val host = if (pathStart == -1) url else url.substring(0, pathStart)
        val prefix = if (pathStart == -1) "" else url.substring(pathStart + 1).trim('/')
        if (host.isBlank() || prefix.isBlank()) {
            error = "请输入带 URL 前缀的完整链接，例如 http://192.168.1.10:8080/qj52lajx"
            return
        }
        loading = true
        scope.launch {
            try {
                repository.login(host, prefix, key.trim(), user.trim(), password, trustAll)
                onLoggedIn()
            } catch (e: ApiException) {
                error = e.message
            } catch (e: Exception) {
                error = "无法连接服务器：${e.message ?: "网络错误"}"
            } finally {
                loading = false
            }
        }
    }

    Box(Modifier.fillMaxSize()) {
        BentoBackdrop()
        Column(
            Modifier
                .fillMaxSize()
                .verticalScroll(rememberScrollState())
                .statusBarsPadding()
                .padding(horizontal = spec.screenPadding.dp)
                .padding(top = spec.topInset.dp, bottom = spec.bottomInset.dp),
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
                        painter = painterResource(
                            if (addingAccount) R.drawable.ic_add_account_logo else R.drawable.ic_login_logo,
                        ),
                        contentDescription = if (addingAccount) "新增" else "登录",
                        modifier = Modifier.size(32.dp),
                    )
                }
                Column(Modifier.weight(1f)) {
                    Text(
                        "catdock",
                        fontSize = 28.sp,
                        fontWeight = FontWeight.Black,
                        color = p.primary,
                    )
                    Text("容器下载控制台", fontSize = 13.sp, color = p.text2)
                }
            }

            if (addingAccount) {
                CatButton(
                    "返回上一个账号",
                    onCancelAdd,
                    modifier = Modifier.fillMaxWidth().padding(top = 16.dp),
                    variant = CatButtonVariant.GHOST,
                    icon = Icons.AutoMirrored.Filled.ArrowBack,
                    small = true,
                )
            }

            CatCard(
                Modifier
                    .fillMaxWidth()
                    .padding(top = 16.dp)
                    .bentoEnter(0),
                verticalArrangement = Arrangement.spacedBy(12.dp),
            ) {
                CatField(server, { server = it }, "服务器地址（含 URL 前缀）*", helper = "例如 http://192.168.1.10:8080/qj52lajx")
                CatField(
                    key,
                    { key = it },
                    "访问密钥（AUTH_KEY）*",
                    visualTransformation = PasswordVisualTransformation(),
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password),
                )
                CatField(user, { user = it }, "用户名*")
                CatField(
                    password,
                    { password = it },
                    "密码*",
                    visualTransformation = if (showPwd) VisualTransformation.None else PasswordVisualTransformation(),
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password),
                    trailingIcon = {
                        IconButton(onClick = { showPwd = !showPwd }) {
                            Icon(
                                if (showPwd) Icons.Filled.VisibilityOff else Icons.Filled.Visibility,
                                contentDescription = if (showPwd) "隐藏密码" else "显示密码",
                                tint = p.text3,
                            )
                        }
                    },
                )
                Row(
                    Modifier.fillMaxWidth(),
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    CatSwitch(trustAll, onCheckedChange = { trustAll = it })
                    Text("信任自签名证书（HTTPS 服务器用）", fontSize = 12.sp, color = p.text2)
                }
                error?.let { Text(it, fontSize = 13.sp, color = p.red) }
                Row(
                    Modifier.fillMaxWidth(),
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(10.dp),
                ) {
                    CatButton(
                        text = "登录",
                        onClick = { submit() },
                        modifier = Modifier.weight(1f),
                        enabled = !loading,
                    )
                    if (loading) {
                        CircularProgressIndicator(
                            modifier = Modifier.size(18.dp),
                            strokeWidth = 2.dp,
                            color = p.primary,
                        )
                    }
                }
            }
        }
    }
}
