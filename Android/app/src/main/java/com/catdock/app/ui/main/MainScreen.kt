package com.catdock.app.ui.main

import android.util.Log
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.isImeVisible
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.Chat
import androidx.compose.material.icons.filled.DarkMode
import androidx.compose.material.icons.filled.Person
import androidx.compose.material.icons.filled.Tune
import androidx.compose.material.icons.filled.WbSunny
import androidx.compose.material.icons.filled.Download
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.catdock.app.CatdockApp
import com.catdock.app.data.AppRepository
import com.catdock.app.data.Session
import com.catdock.app.data.SessionStore
import com.catdock.app.ui.ScreenModel
import com.catdock.app.ui.rememberScreenModel
import com.catdock.app.ui.chat.ChatModel
import com.catdock.app.ui.chat.ChatScreen
import com.catdock.app.ui.components.BentoBackdrop
import com.catdock.app.ui.components.CatBadge
import com.catdock.app.ui.components.CatTone
import com.catdock.app.ui.components.HealthDot
import com.catdock.app.ui.components.HealthState
import com.catdock.app.ui.components.LocalBentoFx
import com.catdock.app.ui.components.bentoPress
import com.catdock.app.ui.components.bentoSurface
import com.catdock.app.ui.components.rememberBentoFx
import com.catdock.app.ui.ops.OpsScreen
import com.catdock.app.ui.profile.ProfileScreen
import com.catdock.app.ui.tasks.TasksModel
import com.catdock.app.ui.tasks.TasksScreen
import com.catdock.app.ui.theme.Appearance
import com.catdock.app.ui.theme.LocalPalette
import com.catdock.app.ui.theme.LocalSpec
import com.catdock.app.ui.theme.ModePreference
import com.catdock.app.ui.theme.catControlShape
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch

/**
 * 顶栏状态灯模型：10s 健康检查（对齐网页 /health 节拍）。
 * 「有新消息」蓝点由主界面用聊天水位与已读水位比较得出，不进这里。
 */
class HealthModel(private val repo: AppRepository) : ScreenModel() {
    private val _state = MutableStateFlow(HealthState.CHECKING)
    val state: StateFlow<HealthState> = _state

    init {
        scope.launch {
            while (isActive) {
                _state.value = runCatching {
                    if (repo.healthOk()) HealthState.OK else HealthState.BAD
                }.getOrDefault(HealthState.BAD)
                delay(10_000)
            }
        }
    }
}

private data class NavTab(val key: String, val label: String, val icon: ImageVector)

/**
 * 主界面壳：Bento 渐变背景层 + 透明顶栏 + 页面 + 玻璃底部导航。
 *   下载用户 = 任务 / 聊天 / 我的
 *   管理员   = 运维 / 聊天 / 我的（网页 admin 页没有任务列表，这里同样不提供）
 * 状态模型按账号 keying：切号即销毁重建，旧账号轮询随之停止。
 */
@OptIn(ExperimentalLayoutApi::class)
@Composable
fun MainScreen(
    repository: AppRepository,
    sessionStore: SessionStore,
    session: Session,
    onAuthExpired: (String) -> Unit,
    onOpenPlayer: (String) -> Unit,
    onAddAccount: () -> Unit,
) {
    val tabs = if (session.isAdmin) {
        listOf(
            NavTab("ops", "运维", Icons.Filled.Tune),
            NavTab("chat", "聊天", Icons.AutoMirrored.Filled.Chat),
            NavTab("me", "我的", Icons.Filled.Person),
        )
    } else {
        listOf(
            NavTab("tasks", "任务", Icons.Filled.Download),
            NavTab("chat", "聊天", Icons.AutoMirrored.Filled.Chat),
            NavTab("me", "我的", Icons.Filled.Person),
        )
    }

    val uiScope = rememberCoroutineScope()
    // 滚动视差：页面里的滚动容器上报，背景光斑按倍速跟随
    val fx = rememberBentoFx()

    var tab by remember(session.accountKey) { mutableIntStateOf(0) }
    // 状态提升到主界面级别：切 Tab 不丢状态、轮询不断连；聊天对齐网页——打开 App 即持续轮询
    val tasksVm = rememberScreenModel(session.accountKey) { TasksModel(repository) }
    val chatVm = rememberScreenModel(session.accountKey) { ChatModel(repository, session.username) }
    val healthVm = rememberScreenModel(session.accountKey) { HealthModel(repository) }

    val health by healthVm.state.collectAsState()
    val chatLast by chatVm.latestId.collectAsState()
    var chatSeen by remember(session.accountKey) { mutableStateOf(0L) }
    LaunchedEffect(session.accountKey) {
        chatSeen = sessionStore.chatSeenFor(session.accountKey)
    }
    val dotState = if (chatLast > chatSeen) HealthState.NEW_MESSAGE else health

    Box(Modifier.fillMaxSize()) {
        BentoBackdrop()
        CompositionLocalProvider(LocalBentoFx provides fx) {
            Column(Modifier.fillMaxSize()) {
                CatTopBar(
                    title = tabs[tab].label,
                    session = session,
                    dot = dotState,
                )
                Box(Modifier.weight(1f).fillMaxWidth()) {
                    when (tabs[tab].key) {
                        "tasks" -> TasksScreen(tasksVm, onAuthExpired, onOpenPlayer)
                        "ops" -> OpsScreen(repository, session, onAuthExpired)
                        "chat" -> ChatScreen(chatVm, onAuthExpired) { id ->
                            chatSeen = id
                            uiScope.launch { sessionStore.markChatSeen(session.accountKey, id) }
                        }
                        else -> ProfileScreen(repository, sessionStore, session, onAuthExpired, onAddAccount)
                    }
                }
                if (!WindowInsets.isImeVisible) {
                    CatNavBar(tabs, tab) { tab = it }
                }
            }
        }
    }
}

/** 顶栏：透明压在渐变上，只留状态灯、标题、身份徽章与右上角主题锚点 */
@Composable
private fun CatTopBar(
    title: String,
    session: Session,
    dot: HealthState,
) {
    val p = LocalPalette.current
    val spec = LocalSpec.current
    Row(
        Modifier
            .fillMaxWidth()
            .statusBarsPadding()
            .padding(horizontal = spec.screenPadding.dp)
            // 状态栏之外再留 20–28dp，标题不透头顶
            .padding(top = spec.topInset.dp - 10.dp, bottom = 10.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        HealthDot(dot)
        // 左上黄金视觉区：页面标题 + 当前账号
        Column(Modifier.weight(1f)) {
            Text(title, fontSize = 22.sp, fontWeight = FontWeight.Bold, color = p.text, maxLines = 1)
            Text(session.username, fontSize = 12.sp, color = p.text3, maxLines = 1)
        }
        CatBadge(
            if (session.isAdmin) "管理员" else "下载用户",
            if (session.isAdmin) CatTone.PRIMARY else CatTone.NEUTRAL,
        )
    }
}


/**
 * 底部导航：全宽玻璃贴底条，手势区在框内留白，控件不塞进手势热区。
 * 不用 Material NavigationBarItem——它的固定选中块会盖掉 Bento 的层次与微光。
 */
@Composable
private fun CatNavBar(tabs: List<NavTab>, selected: Int, onSelect: (Int) -> Unit) {
    val spec = LocalSpec.current
    Box(Modifier.fillMaxWidth()) {
        Row(
            Modifier
                .fillMaxWidth()
                .bentoSurface(strong = true)
                .navigationBarsPadding()
                .padding(horizontal = 8.dp, vertical = 6.dp),
            horizontalArrangement = Arrangement.spacedBy(spec.gap.dp),
        ) {
            tabs.forEachIndexed { index, t ->
                NavItem(t, index == selected, Modifier.weight(1f)) { onSelect(index) }
            }
        }
    }
}

@Composable
private fun NavItem(tab: NavTab, on: Boolean, modifier: Modifier = Modifier, onSelect: () -> Unit) {
    val p = LocalPalette.current
    Column(
        modifier
            .padding(horizontal = 4.dp)
            .heightIn(min = 44.dp)
            .bentoPress(
                onClick = onSelect,
                emphasis = on,
                shape = catControlShape(),
                minHeight = 44.dp,
            ),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(2.dp, Alignment.CenterVertically),
    ) {
        Icon(
            tab.icon,
            contentDescription = tab.label,
            modifier = Modifier.size(22.dp),
            tint = if (on) p.primary else p.text3,
        )
        Text(
            tab.label,
            fontSize = 12.sp,
            fontWeight = if (on) FontWeight.SemiBold else FontWeight.Normal,
            color = if (on) p.primary else p.text3,
        )
    }
}
