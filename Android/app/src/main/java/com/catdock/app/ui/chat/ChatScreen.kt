package com.catdock.app.ui.chat

import android.util.Log
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.Chat
import androidx.compose.material.icons.automirrored.filled.Send
import androidx.compose.material.icons.filled.DeleteSweep
import androidx.compose.material.icons.filled.Download
import androidx.compose.material3.Icon
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
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
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.catdock.app.data.ApiException
import com.catdock.app.data.AppRepository
import com.catdock.app.data.AuthExpiredException
import com.catdock.app.data.ChatMessage
import com.catdock.app.ui.ScreenModel
import com.catdock.app.ui.components.CatButton
import com.catdock.app.ui.components.CatButtonVariant
import com.catdock.app.ui.components.CatCard
import com.catdock.app.ui.components.CatCardTitle
import com.catdock.app.ui.components.CatConfirmButton
import com.catdock.app.ui.components.CatToast
import com.catdock.app.ui.components.CatToastHost
import com.catdock.app.ui.components.TrackBentoScroll
import com.catdock.app.ui.components.bentoEnter
import com.catdock.app.ui.components.bentoSurface
import com.catdock.app.ui.components.catNumeric
import com.catdock.app.ui.components.rememberCatToastState
import com.catdock.app.ui.theme.LocalPalette
import com.catdock.app.ui.theme.LocalSpec
import com.catdock.app.ui.theme.catControlShape
import com.catdock.app.ui.shareTextFile
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch

/** 聊天室模型：固定节拍轮询（对齐网页端 setInterval + 防重入） */
class ChatModel(
    private val repo: AppRepository,
    val selfUser: String,
) : ScreenModel() {

    private val _messages = MutableStateFlow<List<ChatMessage>>(emptyList())
    val messages: StateFlow<List<ChatMessage>> = _messages

    private val _latestId = MutableStateFlow(0L)
    val latestId: StateFlow<Long> = _latestId

    private val _toasts = MutableSharedFlow<CatToast>(extraBufferCapacity = 8)
    val toasts: SharedFlow<CatToast> = _toasts

    private val _authError = MutableSharedFlow<String>(extraBufferCapacity = 1)
    val authError: SharedFlow<String> = _authError

    private var inFlight = false
    private var started = false

    /** 按 id 去重后追加：同一条被重复投递时，LazyColumn 的重复 key 会直接崩掉进程 */
    private fun merge(incoming: List<ChatMessage>) {
        if (incoming.isEmpty()) return
        val seen = _messages.value.mapTo(HashSet(incoming.size)) { it.id }
        val fresh = incoming.filterNot { it.id in seen }
        if (fresh.isNotEmpty()) _messages.value = _messages.value + fresh
    }

    fun start() {
        if (started) return
        started = true
        scope.launch {
            while (isActive) {
                if (!inFlight) {
                    inFlight = true
                    try {
                        val data = repo.chatAfter(_latestId.value)
                        merge(data.messages)
                        data.lastId.takeIf { it > _latestId.value }?.let { _latestId.value = it }
                    } catch (e: AuthExpiredException) {
                        _authError.tryEmit(e.message ?: "登录已过期")
                    } catch (e: Exception) {
                        // 网络抖动保留旧消息；记日志便于 adb logcat 诊断
                        Log.w("CatdockNet", "chat poll error: ${e.javaClass.simpleName}: ${e.message}")
                    } finally {
                        inFlight = false
                    }
                }
                delay(5000)
            }
        }
    }

    fun send(text: String) {
        val msg = text.trim()
        if (msg.isEmpty() || msg.length > 500) {
            _toasts.tryEmit(
                CatToast(
                    if (msg.length > 500) "消息过长（最多 500 字）" else "消息不能为空",
                    error = true,
                ),
            )
            return
        }
        scope.launch {
            try {
                val item = repo.sendChat(msg)
                _messages.value = _messages.value + item
                item.id.takeIf { it > _latestId.value }?.let { _latestId.value = it }
            } catch (e: AuthExpiredException) {
                _authError.tryEmit(e.message ?: "登录已过期")
            } catch (e: ApiException) {
                _toasts.tryEmit(CatToast(e.message ?: "发送失败", error = true))
            } catch (e: Exception) {
                _toasts.tryEmit(CatToast("网络错误：${e.message ?: ""}", error = true))
            }
        }
    }

    /** 清除本账号聊天水位：服务端存档不删，其他用户不受影响 */
    fun clear() {
        scope.launch {
            try {
                val resp = repo.clearChat()
                _latestId.value = resp.clearedId
                _messages.value = emptyList()
                _toasts.tryEmit(CatToast("已清除聊天记录"))
            } catch (e: AuthExpiredException) {
                _authError.tryEmit(e.message ?: "登录已过期")
            } catch (e: ApiException) {
                _toasts.tryEmit(CatToast(e.message ?: "清除失败", error = true))
            } catch (e: Exception) {
                _toasts.tryEmit(CatToast("网络错误：${e.message ?: ""}", error = true))
            }
        }
    }

    /** 导出近 7 天记录，回调交给系统分享面板 */
    fun export(onText: (ByteArray) -> Unit) {
        scope.launch {
            try {
                onText(repo.chatExport())
                _toasts.tryEmit(CatToast("已生成聊天记录文件"))
            } catch (e: AuthExpiredException) {
                _authError.tryEmit(e.message ?: "登录已过期")
            } catch (e: Exception) {
                _toasts.tryEmit(CatToast(e.message ?: "导出失败", error = true))
            }
        }
    }
}

@Composable
fun ChatScreen(
    vm: ChatModel,
    onAuthExpired: (String) -> Unit,
    onSeen: (Long) -> Unit,
) {
    val context = LocalContext.current
    val p = LocalPalette.current
    val spec = LocalSpec.current
    val msgs by vm.messages.collectAsState()
    val latestId by vm.latestId.collectAsState()
    var input by remember { mutableStateOf("") }
    val listState = rememberLazyListState()
    val toast = rememberCatToastState()

    DisposableEffect(Unit) {
        vm.start()
        onDispose { }
    }
    LaunchedEffect(Unit) {
        vm.toasts.collect { toast.show(it) }
    }
    LaunchedEffect(vm.authError) {
        vm.authError.collect { onAuthExpired(it) }
    }
    // 打开聊天即视为已读（网页端 chatSeen_<user> 水位）
    LaunchedEffect(latestId) { if (latestId > 0) onSeen(latestId) }
    LaunchedEffect(msgs.size) {
        if (msgs.isNotEmpty()) listState.animateScrollToItem(msgs.size - 1)
    }

    Box(Modifier.fillMaxSize()) {
        Column(
            Modifier
                .fillMaxSize()
                .padding(horizontal = spec.screenPadding.dp)
                .padding(top = 10.dp, bottom = 6.dp),
            verticalArrangement = Arrangement.spacedBy(spec.gap.dp),
        ) {
            // 网页把聊天室做成一张 .card：标题行 + 消息面板 + 输入条，这里同构
            CatCard(
                Modifier
                    .fillMaxWidth()
                    .weight(1f)
                    .bentoEnter(0),
            ) {
                CatCardTitle(
                    "聊天室",
                    trailing = {
                        Row(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalAlignment = Alignment.CenterVertically) {
                            CatButton(
                                "导出",
                                { vm.export { bytes -> shareTextFile(context, bytes, "catdock_chat.txt") } },
                                variant = CatButtonVariant.GHOST,
                                icon = Icons.Filled.Download,
                                small = true,
                            )
                            CatConfirmButton(
                                text = "清除",
                                confirmText = "仅清除本账号记录",
                                onConfirm = { vm.clear() },
                                icon = Icons.Filled.DeleteSweep,
                                small = true,
                                detail = "只清除当前账号的聊天记录，其他账号不受影响。",
                            )
                        }
                    },
                )
                Box(
                    Modifier
                        .fillMaxWidth()
                        .weight(1f)
                        .background(p.codeBg, catControlShape())
                        // 内凹感靠一圈发丝描边撑出来，否则暗色下就是一块死黑
                        .border(spec.stroke.dp, p.border, catControlShape()),
                ) {
                    if (msgs.isEmpty()) {
                        Column(
                            Modifier.fillMaxSize(),
                            horizontalAlignment = Alignment.CenterHorizontally,
                            verticalArrangement = Arrangement.Center,
                        ) {
                            Icon(
                                Icons.AutoMirrored.Filled.Chat,
                                contentDescription = null,
                                tint = p.text3,
                                modifier = Modifier.size(30.dp),
                            )
                            Spacer(Modifier.height(8.dp))
                            Text("暂无消息", fontSize = 15.sp, color = p.text2)
                            Spacer(Modifier.height(4.dp))
                            Text(
                                "在下方输入，发送后 5 秒内同步到网页端",
                                fontSize = 12.sp,
                                color = p.text3,
                            )
                        }
                    } else {
                        TrackBentoScroll(listState)
                        LazyColumn(
                            state = listState,
                            modifier = Modifier.fillMaxSize(),
                            contentPadding = PaddingValues(12.dp),
                            verticalArrangement = Arrangement.spacedBy(10.dp),
                        ) {
                            itemsIndexed(msgs, key = { _, m -> m.id }) { index, m ->
                                ChatRow(m, mine = m.user == vm.selfUser, prev = msgs.getOrNull(index - 1))
                            }
                        }
                    }
                }
            }

            Row(
                Modifier.fillMaxWidth().imePadding(),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                OutlinedTextField(
                    value = input,
                    onValueChange = { if (it.length <= 500) input = it },
                    placeholder = { Text("说点什么…（≤500 字）", fontSize = 14.sp, color = p.text3) },
                    singleLine = true,
                    maxLines = 1,
                    textStyle = TextStyle(fontSize = 14.sp, color = p.text),
                    shape = catControlShape(),
                    colors = OutlinedTextFieldDefaults.colors(
                        focusedTextColor = p.text,
                        unfocusedTextColor = p.text,
                        focusedContainerColor = p.inputBg,
                        unfocusedContainerColor = p.inputBg.copy(alpha = p.inputBg.alpha * 0.75f),
                        cursorColor = p.primary,
                        focusedBorderColor = p.primary,
                        unfocusedBorderColor = p.border,
                    ),
                    modifier = Modifier.weight(1f).height(56.dp),
                )
                CatButton(
                    text = "发送",
                    onClick = {
                        vm.send(input)
                        input = ""
                    },
                    enabled = input.isNotBlank(),
                    icon = Icons.AutoMirrored.Filled.Send,
                    small = true,
                    modifier = Modifier.height(56.dp),
                )
            }
        }
        CatToastHost(toast)
    }
}

/** 微信式布局：自己的消息靠右；跨天插入日期分隔（不用分割线，靠留白分层） */
@Composable
private fun ChatRow(m: ChatMessage, mine: Boolean, prev: ChatMessage?) {
    val p = LocalPalette.current
    val day = m.time.take(10)
    if (prev == null || prev.time.take(10) != day) {
        Box(Modifier.fillMaxWidth().padding(vertical = 6.dp), contentAlignment = Alignment.Center) {
            Text(day, style = catNumeric(12, p.text3), textAlign = TextAlign.Center)
        }
    }
    Row(
        Modifier.fillMaxWidth(),
        horizontalArrangement = if (mine) Arrangement.End else Arrangement.Start,
    ) {
        Column(
            horizontalAlignment = if (mine) Alignment.End else Alignment.Start,
            modifier = Modifier.widthIn(max = 320.dp),
        ) {
            Text(
                "${m.user} · ${m.time.take(16)}",
                fontSize = 12.sp,
                color = p.text3,
                modifier = Modifier.padding(horizontal = 6.dp, vertical = 2.dp),
            )
            Box(
                Modifier
                    .padding(horizontal = 4.dp)
                    // 气泡走同一套玻璃面：自己的用主色着色，对方的只留底与描边
                    .bentoSurface(shape = catControlShape(), emphasis = mine, strong = mine)
                    .padding(horizontal = 12.dp, vertical = 9.dp),
            ) {
                Text(m.msg, fontSize = 14.sp, color = p.text, lineHeight = 21.sp)
            }
        }
    }
}
