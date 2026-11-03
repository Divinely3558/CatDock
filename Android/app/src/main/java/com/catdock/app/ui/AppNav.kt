package com.catdock.app.ui

import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import com.catdock.app.data.AppRepository
import com.catdock.app.data.Session
import com.catdock.app.data.SessionStore
import com.catdock.app.ui.login.LoginScreen
import com.catdock.app.ui.main.MainScreen
import com.catdock.app.ui.player.PlayerScreen
import kotlinx.coroutines.launch

/**
 * 顶层导航：
 *   login（无有效会话） → main（底部三栏：任务/聊天/我的） → player（预览播放）
 * 支持多账号：切换账号原位生效；令牌失效（403）清该账号令牌回登录页；
 * 「添加新账号」从 main 进入 login，此时抑制自动登录回跳。
 */
@Composable
fun AppNav(session: Session, repository: AppRepository, sessionStore: SessionStore) {
    val nav = rememberNavController()
    val scope = rememberCoroutineScope()
    var addingAccount by remember { mutableStateOf(false) }

    val onAuthExpired: (String) -> Unit = { _ ->
        // 403 后清掉本账号的失效令牌（保留账号条目与加密凭据，静默重登或预填）
        val accountKey = session.accountKey
        scope.launch { sessionStore.invalidate(accountKey) }
        addingAccount = false
        nav.navigate("login") { popUpTo(0) { inclusive = true } }
    }

    // 令牌失效（含切网络后长时间未用、后台超时）时用本地加密凭据静默重登，
    // 成功则立即回到主界面；凭据失效或网络不可达才停留在登录页（字段已预填）
    LaunchedEffect(session.accountKey, session.isLoggedIn, addingAccount) {
        if (!session.isLoggedIn && session.accountKey.isNotEmpty() && !addingAccount) {
            repository.tryAutoRelogin(session)
        }
    }

    NavHost(navController = nav, startDestination = "login") {
        composable("login") {
            LoginScreen(
                repository = repository,
                sessionStore = sessionStore,
                addingAccount = addingAccount,
                onCancelAdd = {
                    addingAccount = false
                    nav.popBackStack()
                },
                onLoggedIn = {
                    addingAccount = false
                    nav.navigate("main") { popUpTo("login") { inclusive = true } }
                },
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
                    addingAccount = true
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

    // 会话驱动的自动跳转：
    //  - 启动时已持有效令牌 → 进主界面（添加账号模式除外）
    //  - 会话被清空（删除当前账号 / 注销 / 令牌失效）→ 回登录页
    LaunchedEffect(session.isLoggedIn, addingAccount) {
        val current = nav.currentBackStackEntry?.destination?.route
        if (session.isLoggedIn && current == "login" && !addingAccount) {
            nav.navigate("main") { popUpTo("login") { inclusive = true } }
        } else if (!session.isLoggedIn && current == "main") {
            nav.navigate("login") { popUpTo(0) { inclusive = true } }
        }
    }
}
