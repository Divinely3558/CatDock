package com.catdock.app.ui

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import com.catdock.app.data.AppRepository
import com.catdock.app.data.Session
import com.catdock.app.data.SessionStore
import com.catdock.app.ui.components.BentoBackdrop
import com.catdock.app.ui.login.AccountPickerScreen
import com.catdock.app.ui.login.LoginScreen
import com.catdock.app.ui.main.MainScreen
import com.catdock.app.ui.player.PlayerScreen
import kotlinx.coroutines.launch

/**
 * 顶层导航：
 *   accounts（有记录账号） / login（一台都没登录过） → main（底部三栏） → player（预览播放）
 *
 * 启动三档：令牌仍有效 → 直接进主界面；有记录账号 → 账号选择页；无记录账号 → 登录表单。
 * 令牌失效（403）/ 注销 / 删除当前账号 → 回账号选择页（账号都删光了才回登录表单）。
 * 「添加新账号」「新用户登录」进空表单，可返回账号列表。
 */
@Composable
fun AppNav(session: Session, repository: AppRepository, sessionStore: SessionStore) {
    val nav = rememberNavController()
    val scope = rememberCoroutineScope()
    val accounts by sessionStore.accounts.collectAsState(initial = emptyList())

    // 起始页要等本地会话读出来才能定，先留一帧空态避免闪一下登录表单
    var startRoute by remember { mutableStateOf<String?>(null) }
    var blankLoginForm by remember { mutableStateOf(false) }
    /** 登录页来源：accounts（可返回账号列表）/ main（「我的」添加账号，返回上级） */
    var loginSource by remember { mutableStateOf("") }

    LaunchedEffect(Unit) {
        val current = sessionStore.current()
        startRoute = when {
            current.isLoggedIn -> "main"
            sessionStore.currentAccounts().isNotEmpty() -> "accounts"
            else -> "login"
        }
    }

    fun enterMain() {
        nav.navigate("main") { popUpTo(0) { inclusive = true } }
    }

    /** 回到账号列表；一个账号都不剩时回登录表单（新用户第一次进来就是这个路径） */
    suspend fun backToAccountList() {
        val remain = sessionStore.currentAccounts()
        val target = if (remain.isEmpty()) "login" else "accounts"
        if (nav.currentBackStackEntry?.destination?.route == target) return
        nav.navigate(target) { popUpTo(0) { inclusive = true } }
    }

    // 回调可能在切号后才到达（旧账号在途请求返回 403）：只有当前激活账号仍是
    // 发起请求的账号时才登出，避免清掉新账号令牌
    val callbackAccountKey = session.accountKey
    val onAuthExpired: (String) -> Unit = { _ ->
        scope.launch {
            val currentKey = sessionStore.current().accountKey
            if (currentKey != callbackAccountKey) return@launch
            // 403 后清掉本账号的失效令牌（保留账号条目与加密凭据，账号列表里可直接重登）
            sessionStore.invalidate(currentKey)
            backToAccountList()
        }
    }

    val route = startRoute
    if (route == null) {
        Box(Modifier.fillMaxSize()) { BentoBackdrop() }
        return
    }

    NavHost(navController = nav, startDestination = route) {
        composable("accounts") {
            AccountPickerScreen(
                repository = repository,
                sessionStore = sessionStore,
                accounts = accounts,
                session = session,
                onEnterApp = { enterMain() },
                onNeedPassword = {
                    blankLoginForm = false
                    loginSource = "accounts"
                    nav.navigate("login")
                },
                onNewLogin = {
                    blankLoginForm = true
                    loginSource = "accounts"
                    nav.navigate("login")
                },
            )
        }
        composable("login") {
            LoginScreen(
                repository = repository,
                sessionStore = sessionStore,
                blankForm = blankLoginForm,
                showBack = loginSource.isNotEmpty(),
                backLabel = if (loginSource == "accounts") "返回账号列表" else "返回",
                onBack = { nav.popBackStack() },
                onLoggedIn = { enterMain() },
            )
        }
        composable("main") {
            MainScreen(
                repository = repository,
                sessionStore = sessionStore,
                session = session,
                onAuthExpired = onAuthExpired,
                onOpenPlayer = { taskId -> nav.navigate("player/$taskId") },
                onAddAccount = {
                    blankLoginForm = true
                    loginSource = "main"
                    nav.navigate("login")
                },
            )
        }
        composable("player/{taskId}") { entry ->
            val taskId = entry.arguments?.getString("taskId").orEmpty()
            PlayerScreen(
                repository = repository,
                session = session,
                taskId = taskId,
                onBack = { nav.popBackStack() },
                onAuthExpired = { onAuthExpired(it) },
            )
        }
    }

    // 当前账号被删除（注销 / 「我的」里移除）后会话清空：主界面没有可用身份，回账号列表
    LaunchedEffect(session.accountKey, session.isLoggedIn) {
        val current = nav.currentBackStackEntry?.destination?.route
        if (current == "main" && session.accountKey.isEmpty()) backToAccountList()
    }
}
