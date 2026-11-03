package com.catdock.app.ui.tasks

import android.util.Log
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.Download
import androidx.compose.material.icons.filled.Pause
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.PlayCircle
import androidx.compose.material.icons.filled.PushPin
import androidx.compose.material.icons.filled.TrendingUp
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
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.catdock.app.data.ApiException
import com.catdock.app.data.AppRepository
import com.catdock.app.data.AuthExpiredException
import com.catdock.app.data.DownloadReq
import com.catdock.app.data.Task
import com.catdock.app.ui.ScreenModel
import com.catdock.app.ui.components.BentoDialog
import com.catdock.app.ui.components.BentoDialogButtons
import com.catdock.app.ui.components.BentoDialogTitle
import com.catdock.app.ui.components.BentoSkeleton
import com.catdock.app.ui.components.CatBadge
import com.catdock.app.ui.components.CatButton
import com.catdock.app.ui.components.CatButtonVariant
import com.catdock.app.ui.components.CatCard
import com.catdock.app.ui.components.CatConfirmButton
import com.catdock.app.ui.components.CatEmptyState
import com.catdock.app.ui.components.CatField
import com.catdock.app.ui.components.CatProgress
import com.catdock.app.ui.components.CatToast
import com.catdock.app.ui.components.CatToastHost
import com.catdock.app.ui.components.CatTone
import com.catdock.app.ui.components.bentoEnter
import com.catdock.app.ui.components.catNumeric
import com.catdock.app.ui.components.catTap
import com.catdock.app.ui.components.colors
import com.catdock.app.ui.components.rememberCatToastState
import com.catdock.app.ui.theme.LocalPalette
import com.catdock.app.ui.theme.LocalSpec
import com.catdock.app.ui.theme.catControlShape
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.launch

/** 任务页模型：4s 静默轮询 + 任务操作 + 新建任务 */
class TasksModel(private val repo: AppRepository) : ScreenModel() {

    private val _tasks = MutableStateFlow<List<Task>>(emptyList())
    val tasks: StateFlow<List<Task>> = _tasks

    // 初值 true：首个响应到达前显示转圈，之后不再由轮询打开（见 refresh）
    private val _loading = MutableStateFlow(true)
    val loading: StateFlow<Boolean> = _loading

    private val _messages = MutableSharedFlow<CatToast>(extraBufferCapacity = 8)
    val messages: SharedFlow<CatToast> = _messages

    private val _authError = MutableSharedFlow<String>(extraBufferCapacity = 1)
    val authError: SharedFlow<String> = _authError

    private var polling = false

    fun startPolling() {
        if (polling) return
        polling = true
        scope.launch {
            while (polling) {
                refresh()
                delay(4000)
            }
        }
    }

    fun stopPolling() {
        polling = false
    }

    suspend fun refresh() {
        val firstAttempt = _loading.value
        try {
            _tasks.value = repo.tasks()
        } catch (e: AuthExpiredException) {
            _authError.tryEmit(e.message ?: "登录已过期")
        } catch (e: Exception) {
            // 轮询失败保留旧数据；记日志便于 adb logcat 诊断
            Log.w("CatdockNet", "tasks poll error: ${e.javaClass.simpleName}: ${e.message}")
        } finally {
            // 转圈只跟随首次拉取：失败后按 4s 静默重试，连接断了有顶栏状态灯提示。
            // 每次重试都开合转圈会让空态文案和转圈来回切换，看着像在闪跳
            if (firstAttempt) _loading.value = false
        }
    }

    fun op(action: String, id: String) {
        scope.launch {
            try {
                val msg = when (action) {
                    "pause" -> repo.pauseTask(id)
                    "resume" -> repo.resumeTask(id)
                    "pin" -> repo.pinTask(id)
                    "delete" -> repo.deleteTask(id)
                    else -> "未知操作"
                }
                _messages.tryEmit(CatToast(msg))
                refresh()
            } catch (e: AuthExpiredException) {
                _authError.tryEmit(e.message ?: "登录已过期")
            } catch (e: ApiException) {
                _messages.tryEmit(CatToast(e.message ?: "操作失败", error = true))
            } catch (e: Exception) {
                _messages.tryEmit(CatToast("网络错误：${e.message ?: ""}", error = true))
            }
        }
    }

    fun submit(req: DownloadReq) {
        scope.launch {
            try {
                val resp = repo.download(req)
                val blocked = resp.blocked == true
                _messages.tryEmit(
                    CatToast(
                        if (blocked) "已被广告关键字拦截：${resp.keyword ?: ""}"
                        else resp.message ?: "已提交",
                        error = blocked,
                    ),
                )
                refresh()
            } catch (e: AuthExpiredException) {
                _authError.tryEmit(e.message ?: "登录已过期")
            } catch (e: ApiException) {
                _messages.tryEmit(CatToast(e.message ?: "提交失败", error = true))
            } catch (e: Exception) {
                _messages.tryEmit(CatToast("网络错误：${e.message ?: ""}", error = true))
            }
        }
    }
}

private val STATUS_LABEL = mapOf(
    "queued" to "排队中",
    "collecting" to "收集中",
    "running" to "下载中",
    "paused" to "已暂停",
    "done" to "已完成",
    "failed" to "失败",
)

/** 对齐网页 .badge-* 配色：下载=主色蓝 收集=黄 排队=蓝 完成=绿 暂停=中性灰 失败=红 */
private val STATUS_TONE = mapOf(
    "queued" to CatTone.BLUE,
    "collecting" to CatTone.AMBER,
    "running" to CatTone.PRIMARY,
    "paused" to CatTone.NEUTRAL,
    "done" to CatTone.GREEN,
    "failed" to CatTone.RED,
)

@Composable
fun TasksScreen(
    vm: TasksModel,
    onAuthExpired: (String) -> Unit,
    onOpenPlayer: (String) -> Unit,
) {
    val spec = LocalSpec.current
    val tasks by vm.tasks.collectAsState()
    val loading by vm.loading.collectAsState()
    var showNewTask by remember { mutableStateOf(false) }
    val toast = rememberCatToastState()

    DisposableEffect(Unit) {
        vm.startPolling()
        onDispose { vm.stopPolling() }
    }
    LaunchedEffect(Unit) {
        vm.messages.collect { toast.show(it) }
    }
    LaunchedEffect(vm.authError) {
        vm.authError.collect { onAuthExpired(it) }
    }

    // 左右内边距统一由 spec 给：卡片不贴屏幕边，也不各页各留一套
    Box(
        Modifier
            .fillMaxSize()
            .padding(horizontal = spec.screenPadding.dp)
    ) {
        when {
            loading -> BentoSkeleton(
                rows = 4,
                modifier = Modifier.fillMaxWidth().padding(top = spec.topInset.dp - 8.dp, bottom = 104.dp),
            )

            tasks.isEmpty() -> Box(
                Modifier.fillMaxSize().padding(vertical = 24.dp, horizontal = 8.dp),
                contentAlignment = Alignment.Center,
            ) {
                CatEmptyState(
                    icon = Icons.Filled.Download,
                    text = "暂无任务",
                    hint = "点下方「新建下载」粘贴视频链接",
                )
            }

            else -> LazyColumn(
                // 底部多留 104dp：悬浮的「新建下载」不压住最后一张任务卡
                contentPadding = PaddingValues(
                    top = spec.topInset.dp - 8.dp,
                    bottom = 104.dp,
                ),
                verticalArrangement = Arrangement.spacedBy(spec.gap.dp),
                modifier = Modifier.fillMaxSize(),
            ) {
                itemsIndexed(tasks, key = { _, t -> t.id }) { index, t ->
                    TaskCard(
                        task = t,
                        enterIndex = index % 6,
                        onAction = { act -> vm.op(act, t.id) },
                        onPreview = { onOpenPlayer(t.id) },
                    )
                }
            }
        }

        // 主操作落在底部优先操作区，避开手势条与导航栏的安全留白
        CatButton(
            text = "新建下载",
            icon = Icons.Filled.Add,
            onClick = { showNewTask = true },
            modifier = Modifier.align(Alignment.BottomEnd).padding(end = 4.dp, bottom = 4.dp),
        )
        CatToastHost(toast)
    }

    if (showNewTask) {
        NewTaskDialog(
            onDismiss = { showNewTask = false },
            onSubmit = { req ->
                showNewTask = false
                vm.submit(req)
            },
        )
    }
}

@Composable
private fun TaskCard(
    task: Task,
    enterIndex: Int,
    onAction: (String) -> Unit,
    onPreview: () -> Unit,
) {
    val p = LocalPalette.current
    val tone = STATUS_TONE[task.status] ?: CatTone.NEUTRAL
    val (toneFg, _) = tone.colors()
    val previewable = task.status == "running" || task.status == "paused"

    CatCard(
        Modifier
            .fillMaxWidth()
            .bentoEnter(enterIndex),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Text(
                task.saveName ?: task.id,
                fontWeight = FontWeight.SemiBold,
                fontSize = 15.sp,
                color = p.text,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
                modifier = Modifier.weight(1f),
            )
            CatBadge(STATUS_LABEL[task.status] ?: task.status, tone)
        }

        if (task.status == "queued" && task.queuePos != null) {
            Text("排在第 ${task.queuePos} 位", style = catNumeric(12, p.text3))
        } else {
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                CatProgress(
                    fraction = (task.progress.toFloat() / 100f).coerceIn(0f, 1f),
                    modifier = Modifier.weight(1f),
                )
                // 网页 .pct：min-width 38px + 右对齐 + 等宽数字，轮询刷新时不左右跳
                Text(
                    buildString {
                        append("${task.progress.toInt()}%")
                        task.segments?.let { if (it.total > 0) append(" ${it.done}/${it.total}") }
                    },
                    style = catNumeric(12, p.text2),
                    maxLines = 1,
                    modifier = Modifier.widthIn(min = 38.dp),
                )
            }
        }

        Text(
            task.outputFile ?: task.url ?: "",
            fontSize = 12.sp,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
            color = p.text2,
        )

        Row(
            horizontalArrangement = Arrangement.spacedBy(6.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            if (previewable) {
                CatButton("预览", onPreview, variant = CatButtonVariant.GHOST,
                    icon = Icons.Filled.PlayCircle, small = true)
            }
            when (task.status) {
                "queued" -> CatButton("置顶", { onAction("pin") },
                    variant = CatButtonVariant.GHOST, icon = Icons.Filled.PushPin, small = true)

                "running", "collecting" -> CatButton("暂停", { onAction("pause") },
                    variant = CatButtonVariant.GHOST, icon = Icons.Filled.Pause, small = true)

                "paused" -> CatButton("恢复", { onAction("resume") },
                    variant = CatButtonVariant.GHOST, icon = Icons.Filled.PlayArrow, small = true)
            }
            Spacer(Modifier.weight(1f))
            CatConfirmButton(
                text = "删除",
                confirmText = "确认删除该任务？",
                onConfirm = { onAction("delete") },
                icon = Icons.Filled.Delete,
                small = true,
                detail = "任务记录和下载进度会一并从服务器上移除，已下载的文件不会被删。",
            )
        }

        if (task.retryCount > 0) {
            Row(
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(6.dp),
            ) {
                Icon(
                    Icons.Filled.TrendingUp,
                    contentDescription = null,
                    modifier = Modifier.size(13.dp),
                    tint = toneFg,
                )
                Text("已重试 ${task.retryCount} 次", fontSize = 12.sp, color = p.text3)
            }
        }
    }
}

/** 新建下载任务：URL 必填，高级选项（Referer / Cookie / UA）折叠 */
@Composable
private fun NewTaskDialog(onDismiss: () -> Unit, onSubmit: (DownloadReq) -> Unit) {
    val p = LocalPalette.current
    var url by remember { mutableStateOf("") }
    var saveName by remember { mutableStateOf("") }
    var referer by remember { mutableStateOf("") }
    var cookie by remember { mutableStateOf("") }
    var userAgent by remember { mutableStateOf("") }
    var format by remember { mutableStateOf("mp4") }
    var adv by remember { mutableStateOf(false) }

    BentoDialog(onDismiss) {
        BentoDialogTitle(
            "新建下载任务",
            trailing = {
                Icon(
                    Icons.Filled.Close,
                    contentDescription = "关闭",
                    tint = p.text3,
                    modifier = Modifier.size(20.dp).catTap(onClick = onDismiss, shape = catControlShape()),
                )
            },
        )
        CatField(url, { url = it }, "视频链接（m3u8 或直链）*", singleLine = false, minLines = 3)
        CatField(saveName, { saveName = it }, "保存文件名（可选）")
        Row(
            Modifier.fillMaxWidth(),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            Text("输出格式", fontSize = 13.sp, color = p.text2, modifier = Modifier.weight(1f))
            listOf("mp4", "mkv").forEach { f ->
                CatButton(
                    text = f,
                    onClick = { format = f },
                    variant = if (f == format) CatButtonVariant.PRIMARY else CatButtonVariant.GHOST,
                    small = true,
                )
            }
        }
        CatButton(
            text = if (adv) "收起高级选项" else "高级选项（Referer / Cookie / UA）",
            onClick = { adv = !adv },
            variant = CatButtonVariant.GHOST,
            modifier = Modifier.fillMaxWidth(),
            small = true,
        )
        if (adv) {
            CatField(referer, { referer = it }, "Referer")
            CatField(cookie, { cookie = it }, "Cookie", singleLine = false, minLines = 2)
            CatField(userAgent, { userAgent = it }, "User-Agent")
        }
        BentoDialogButtons(
            confirmText = "提交",
            onConfirm = {
                onSubmit(
                    DownloadReq(
                        url = url.trim(),
                        saveName = saveName.trim().ifEmpty { null },
                        referer = referer.trim().ifEmpty { null },
                        cookie = cookie.trim().ifEmpty { null },
                        userAgent = userAgent.trim().ifEmpty { null },
                        format = format,
                    ),
                )
            },
            dismissText = "取消",
            onDismiss = onDismiss,
            confirmEnabled = url.isNotBlank(),
        )
    }
}
