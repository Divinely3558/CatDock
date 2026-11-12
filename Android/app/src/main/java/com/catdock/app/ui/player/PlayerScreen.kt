package com.catdock.app.ui.player

import android.app.Activity
import android.content.Context
import android.content.ContextWrapper
import android.content.pm.ActivityInfo
import android.view.WindowManager
import androidx.activity.compose.BackHandler
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.detectHorizontalDragGestures
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Fullscreen
import androidx.compose.material.icons.filled.FullscreenExit
import androidx.compose.material.icons.filled.Pause
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
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
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.input.pointer.pointerInput
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
import com.catdock.app.ui.components.bentoSurface
import com.catdock.app.ui.components.catNumeric
import com.catdock.app.ui.components.glassHalo
import com.catdock.app.ui.rememberScreenModel
import com.catdock.app.ui.theme.LocalPalette
import com.catdock.app.ui.theme.LocalSpec
import com.catdock.app.ui.theme.catControlShape
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
    // 自绘控制层状态：播放中 / 进度 / 控制条可见性（nonce 重置 3s 自动隐藏计时）
    var playing by remember { mutableStateOf(true) }
    var buffering by remember { mutableStateOf(true) }
    var posMs by remember { mutableStateOf(0L) }
    var durMs by remember { mutableStateOf(0L) }
    var controlsVisible by remember { mutableStateOf(true) }
    var controlsNonce by remember { mutableStateOf(0) }

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

            override fun onIsPlayingChanged(isPlaying: Boolean) {
                playing = isPlaying
            }

            override fun onPlaybackStateChanged(playbackState: Int) {
                buffering = playbackState == Player.STATE_BUFFERING
                if (playbackState == Player.STATE_READY) durMs = exoPlayer.duration.coerceAtLeast(0L)
            }
        })
        onDispose {
            vm.saveResumeTime(exoPlayer.currentPosition)
            exoPlayer.stop()
            exoPlayer.release()
        }
    }

    // 进度轮询 500ms：驱动自绘进度条与时间文本（ExoPlayer 不推进度事件）
    LaunchedEffect(exoPlayer) {
        while (true) {
            posMs = exoPlayer.currentPosition.coerceAtLeast(0L)
            val d = exoPlayer.duration
            if (d > 0) durMs = d
            delay(500)
        }
    }

    // 横屏全屏下 3s 无操作自动隐藏控制层；任何交互经 nonce 重置计时
    LaunchedEffect(fullscreen, controlsVisible, controlsNonce) {
        if (fullscreen && controlsVisible) {
            delay(3000)
            controlsVisible = false
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

    // 视频全出血：上下各叠一层 glassStrong 控制条；竖屏黑底容纳信箱模式
    Box(
        Modifier
            .fillMaxSize()
            .background(Color.Black),
    ) {
        val message = playerError ?: loadError
        if (message != null) {
            Text(
                message,
                color = p.red,
                fontSize = 13.sp,
                modifier = Modifier
                    .align(Alignment.Center)
                    .padding(24.dp),
            )
        } else {
            AndroidView(
                factory = { ctx ->
                    PlayerView(ctx).apply {
                        player = exoPlayer
                        // 控制层全部自绘（玻璃条），关掉 ExoPlayer 原生控制器
                        useController = false
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

        // 点击切换控制层显隐（无 ripple 的整屏透明热区）
        Box(
            Modifier
                .fillMaxSize()
                .clickable(
                    interactionSource = remember { MutableInteractionSource() },
                    indication = null,
                ) {
                    controlsVisible = !controlsVisible
                    controlsNonce++
                },
        )

        if (buffering && message == null) {
            CircularProgressIndicator(
                modifier = Modifier.align(Alignment.Center).size(40.dp),
                color = p.primary,
                strokeWidth = 3.dp,
            )
        }

        if (controlsVisible) {
            // 上控制条：返回 + 标题/下载进度 + 全屏开关
            Row(
                Modifier
                    .align(Alignment.TopCenter)
                    .fillMaxWidth()
                    .statusBarsPadding()
                    .padding(horizontal = spec.screenPadding.dp, vertical = 10.dp)
                    .bentoSurface(shape = catControlShape(), strong = true)
                    .padding(horizontal = 6.dp, vertical = 4.dp),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(4.dp),
            ) {
                ControlIcon(Icons.AutoMirrored.Filled.ArrowBack, "返回") {
                    if (fullscreen) fullscreen = false else onBack()
                }
                Column(Modifier.weight(1f).padding(start = 4.dp)) {
                    Text(
                        task?.saveName ?: taskId,
                        fontSize = 14.sp,
                        fontWeight = FontWeight.SemiBold,
                        color = p.text,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                    )
                    task?.let { Text("下载进度 ${it.progress.toInt()}%", fontSize = 11.sp, color = p.text3) }
                }
                ControlIcon(
                    if (fullscreen) Icons.Filled.FullscreenExit else Icons.Filled.Fullscreen,
                    if (fullscreen) "退出全屏" else "全屏",
                ) {
                    fullscreen = !fullscreen
                    controlsNonce++
                }
            }

            // 下控制条：56dp 渐变播放钮 + 44dp 触控进度条 + 时间
            Row(
                Modifier
                    .align(Alignment.BottomCenter)
                    .fillMaxWidth()
                    .navigationBarsPadding()
                    .padding(horizontal = spec.screenPadding.dp, vertical = 10.dp)
                    .bentoSurface(shape = catControlShape(), strong = true)
                    .padding(horizontal = 12.dp, vertical = 10.dp),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(12.dp),
            ) {
                // 56dp 极光渐变圆形播放钮 + 光晕（aurora CTA 规范）
                Box(
                    Modifier
                        .size(56.dp)
                        .glassHalo(spec.glowRadius.dp, p.glow, CircleShape)
                        .background(Brush.linearGradient(p.primaryGradient), CircleShape)
                        .clickable {
                            if (playing) exoPlayer.pause() else exoPlayer.play()
                            controlsNonce++
                        },
                    contentAlignment = Alignment.Center,
                ) {
                    Icon(
                        if (playing) Icons.Filled.Pause else Icons.Filled.PlayArrow,
                        contentDescription = if (playing) "暂停" else "播放",
                        tint = Color.White,
                        modifier = Modifier.size(28.dp),
                    )
                }
                Column(Modifier.weight(1f)) {
                    PlayerSeekBar(
                        fraction = if (durMs > 0) (posMs.toFloat() / durMs).coerceIn(0f, 1f) else 0f,
                        onSeek = { f ->
                            if (durMs > 0) {
                                val target = (f * durMs).toLong()
                                exoPlayer.seekTo(target)
                                posMs = target
                            }
                            controlsNonce++
                        },
                        modifier = Modifier.fillMaxWidth(),
                    )
                    Row(Modifier.fillMaxWidth()) {
                        Text(formatPlayerTime(posMs), style = catNumeric(11, p.text2))
                        Text(" / ${formatPlayerTime(durMs)}", style = catNumeric(11, p.text3))
                    }
                }
            }
        }
    }
}

/** 玻璃控制条里的 48dp 图标热区按钮 */
@Composable
private fun ControlIcon(
    icon: androidx.compose.ui.graphics.vector.ImageVector,
    desc: String,
    onClick: () -> Unit,
) {
    Box(
        Modifier
            .size(44.dp)
            .clickable(onClick = onClick),
        contentAlignment = Alignment.Center,
    ) {
        Icon(icon, contentDescription = desc, tint = LocalPalette.current.text, modifier = Modifier.size(20.dp))
    }
}

/** 44dp 触控热区进度条：4dp 视觉轨道 + 极光渐变已播段，点按/拖动都可 seek */
@Composable
private fun PlayerSeekBar(
    fraction: Float,
    onSeek: (Float) -> Unit,
    modifier: Modifier = Modifier,
) {
    val p = LocalPalette.current
    var drag by remember { mutableStateOf<Float?>(null) }
    val shown = drag ?: fraction
    Box(
        modifier
            .height(44.dp)
            .pointerInput(Unit) {
                detectTapGestures { offset -> onSeek((offset.x / size.width).coerceIn(0f, 1f)) }
            }
            .pointerInput(Unit) {
                detectHorizontalDragGestures(
                    onDragStart = { offset -> drag = (offset.x / size.width).coerceIn(0f, 1f) },
                    onHorizontalDrag = { change, _ ->
                        change.consume()
                        drag = (change.position.x / size.width).coerceIn(0f, 1f)
                    },
                    onDragEnd = {
                        drag?.let(onSeek)
                        drag = null
                    },
                    onDragCancel = { drag = null },
                )
            },
        contentAlignment = Alignment.CenterStart,
    ) {
        Box(
            Modifier
                .fillMaxWidth()
                .height(4.dp)
                .background(Color.White.copy(alpha = 0.28f), CircleShape),
        )
        Box(
            Modifier
                .fillMaxWidth(shown)
                .height(4.dp)
                .background(Brush.horizontalGradient(p.primaryGradient), CircleShape),
        )
        // 已播段端点小圆点：暗底视频上给手指一个明确落点
        Box(
            Modifier
                .align(Alignment.CenterStart)
                .fillMaxWidth(shown),
            contentAlignment = Alignment.CenterEnd,
        ) {
            Box(
                Modifier
                    .size(10.dp)
                    .background(Color.White, CircleShape),
            )
        }
    }
}

private fun formatPlayerTime(ms: Long): String {
    if (ms <= 0) return "00:00"
    val totalSec = ms / 1000
    val h = totalSec / 3600
    val m = totalSec % 3600 / 60
    val s = totalSec % 60
    return if (h > 0) "%d:%02d:%02d".format(h, m, s) else "%02d:%02d".format(m, s)
}
