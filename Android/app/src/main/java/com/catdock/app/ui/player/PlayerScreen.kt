package com.catdock.app.ui.player

import android.app.Activity
import android.content.Context
import android.content.ContextWrapper
import android.content.pm.ActivityInfo
import android.view.WindowManager
import androidx.activity.compose.BackHandler
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Fullscreen
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import androidx.core.view.WindowInsetsControllerCompat
import androidx.media3.common.MediaItem
import androidx.media3.common.PlaybackException
import androidx.media3.common.Player
import androidx.media3.common.util.UnstableApi
import androidx.media3.datasource.DefaultDataSource
import androidx.media3.datasource.DefaultHttpDataSource
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.exoplayer.hls.HlsMediaSource
import androidx.media3.ui.AspectRatioFrameLayout
import androidx.media3.ui.PlayerView
import com.catdock.app.data.AppRepository
import com.catdock.app.data.AuthExpiredException
import com.catdock.app.data.Session
import com.catdock.app.data.Task
import com.catdock.app.ui.ScreenModel
import com.catdock.app.ui.components.CatButton
import com.catdock.app.ui.components.CatButtonVariant
import com.catdock.app.ui.rememberScreenModel
import com.catdock.app.ui.theme.LocalPalette
import com.catdock.app.ui.theme.LocalSpec
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch

/**
 * 预览页模型：任务信息 10s 刷新（供进度行与断点续看用）。
 * 退出时的进度上报走独立作用域——页面销毁会取消模型作用域，若共用则最后一次断点必然丢失。
 */
class PlayerModel(
    private val repo: AppRepository,
    private val taskId: String,
) : ScreenModel() {
    val task = MutableStateFlow<Task?>(null)
    val error = MutableStateFlow<String?>(null)
    val authError = MutableSharedFlow<String>(extraBufferCapacity = 1)

    private val ioScope = CoroutineScope(SupervisorJob() + Dispatchers.IO)

    init {
        scope.launch {
            while (isActive) {
                try {
                    task.value = repo.task(taskId)
                } catch (e: AuthExpiredException) {
                    authError.tryEmit(e.message ?: "登录已过期")
                } catch (e: Exception) {
                    if (task.value == null) error.value = "获取任务信息失败：${e.message ?: ""}"
                }
                delay(10_000)
            }
        }
    }

    fun saveResumeTime(positionMs: Long) {
        if (positionMs <= 0) return
        ioScope.launch { runCatching { repo.saveResumeTime(taskId, positionMs / 1000.0) } }
    }
}

private tailrec fun Context.findActivity(): Activity? = when (this) {
    is Activity -> this
    is ContextWrapper -> baseContext.findActivity()
    else -> null
}

/**
 * m3u8 边下边看预览（对齐网页端行为）：仅 running/paused 可预览，地址
 * {prefix}/tasks/{id}/preview.m3u8 需 Bearer 头，进入 seek 到 preview_resume_time、
 * 退出上报 /task/resume_time。全屏＝横屏 + 沉浸系统栏 + 画面撑满（BUG-2）。
 */
@UnstableApi
@Composable
fun PlayerScreen(
    repository: AppRepository,
    session: Session,
    taskId: String,
    onBack: () -> Unit,
    onAuthExpired: (String) -> Unit,
) {
    val p = LocalPalette.current
    val spec = LocalSpec.current
    val context = LocalContext.current
    val activity = context.findActivity()
    val vm = rememberScreenModel(taskId) { PlayerModel(repository, taskId) }
    val task by vm.task.collectAsState()
    val loadError by vm.error.collectAsState()
    var playerError by remember { mutableStateOf<String?>(null) }
    var fullscreen by remember { mutableStateOf(false) }
    var prepared by remember { mutableStateOf(false) }

    val exoPlayer = remember(session.accountKey, taskId) {
        ExoPlayer.Builder(context).build().apply { playWhenReady = true }
    }
    val httpFactory = remember(session.accountKey) {
        DefaultHttpDataSource.Factory()
            .setAllowCrossProtocolRedirects(true)
            .setConnectTimeoutMs(15_000)
            .setReadTimeoutMs(30_000)
    }
    val dataSourceFactory = remember(httpFactory) { DefaultDataSource.Factory(context, httpFactory) }

    // 令牌续期只换请求头，不重建播放器：后续分片请求自然带新令牌
    LaunchedEffect(session.token) {
        httpFactory.setDefaultRequestProperties(mapOf("Authorization" to "Bearer ${session.token}"))
    }

    DisposableEffect(exoPlayer) {
        exoPlayer.addListener(object : Player.Listener {
            override fun onPlayerError(err: PlaybackException) {
                playerError = "播放失败：${err.errorCodeName}"
            }
        })
        onDispose {
            vm.saveResumeTime(exoPlayer.currentPosition)
            exoPlayer.stop()
            exoPlayer.release()
        }
    }

    LaunchedEffect(task) {
        val t = task ?: return@LaunchedEffect
        if (prepared) return@LaunchedEffect
        if (t.status != "running" && t.status != "paused") {
            playerError = "当前状态（${t.status}）不支持预览，仅下载中/已暂停任务可边下边看"
            return@LaunchedEffect
        }
        prepared = true
        val source = HlsMediaSource.Factory(dataSourceFactory)
            .createMediaSource(MediaItem.fromUri(session.previewUrl(taskId)))
        exoPlayer.setMediaSource(source, ((t.previewResumeTime ?: 0.0) * 1000).toLong().coerceAtLeast(0L))
        exoPlayer.prepare()
    }

    LaunchedEffect(vm.authError) {
        vm.authError.collect { onAuthExpired(it) }
    }

    // 离开页面一律还原方向与系统栏
    DisposableEffect(fullscreen) {
        val controller = activity?.window
            ?.let { WindowCompat.getInsetsController(it, it.decorView) }
        if (fullscreen) {
            activity?.requestedOrientation = ActivityInfo.SCREEN_ORIENTATION_SENSOR_LANDSCAPE
            controller?.systemBarsBehavior = WindowInsetsControllerCompat.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE
            controller?.hide(WindowInsetsCompat.Type.systemBars())
        } else {
            activity?.requestedOrientation = ActivityInfo.SCREEN_ORIENTATION_UNSPECIFIED
            controller?.show(WindowInsetsCompat.Type.systemBars())
        }
        onDispose {
            activity?.requestedOrientation = ActivityInfo.SCREEN_ORIENTATION_UNSPECIFIED
            controller?.show(WindowInsetsCompat.Type.systemBars())
        }
    }

    BackHandler { if (fullscreen) fullscreen = false else onBack() }

    DisposableEffect(activity) {
        activity?.window?.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        onDispose { activity?.window?.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON) }
    }

    Column(
        Modifier
            .fillMaxSize()
            .background(if (fullscreen) Color.Black else Color.Transparent),
    ) {
        if (!fullscreen) {
            Row(
                Modifier
                    .fillMaxWidth()
                    .statusBarsPadding()
                    .padding(horizontal = spec.screenPadding.dp)
                    .padding(top = 8.dp, bottom = spec.gap.dp),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                CatButton(
                    "返回",
                    onBack,
                    variant = CatButtonVariant.GHOST,
                    icon = Icons.AutoMirrored.Filled.ArrowBack,
                    small = true,
                )
                Column(Modifier.weight(1f)) {
                    Text(
                        task?.saveName ?: taskId,
                        fontSize = 15.sp,
                        fontWeight = FontWeight.SemiBold,
                        color = p.text,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                    )
                    task?.let { Text("下载进度 ${it.progress.toInt()}%", fontSize = 12.sp, color = p.text3) }
                }
                CatButton(
                    "全屏",
                    { fullscreen = true },
                    variant = CatButtonVariant.GHOST,
                    icon = Icons.Filled.Fullscreen,
                    small = true,
                )
            }
        }

        Box(
            Modifier
                .weight(1f)
                .fillMaxWidth()
                .then(
                    if (fullscreen) Modifier
                    else Modifier
                        .padding(horizontal = spec.screenPadding.dp)
                        .navigationBarsPadding()
                        .padding(bottom = spec.bottomInset.dp)
                ),
        ) {
            val message = playerError ?: loadError
            if (message != null) {
                Text(message, color = p.red, fontSize = 13.sp, modifier = Modifier.fillMaxWidth().padding(24.dp))
            } else {
                AndroidView(
                    factory = { ctx ->
                        PlayerView(ctx).apply {
                            player = exoPlayer
                            useController = true
                            // 单条预览流没有上/下一曲可切，网页端预览条也只有播放+进度+时间
                            setShowPreviousButton(false)
                            setShowNextButton(false)
                            setShutterBackgroundColor(android.graphics.Color.TRANSPARENT)
                        }
                    },
                    update = { view ->
                        view.resizeMode = if (fullscreen) {
                            AspectRatioFrameLayout.RESIZE_MODE_ZOOM
                        } else {
                            AspectRatioFrameLayout.RESIZE_MODE_FIT
                        }
                    },
                    modifier = Modifier.fillMaxSize(),
                )
            }
        }
    }
}
