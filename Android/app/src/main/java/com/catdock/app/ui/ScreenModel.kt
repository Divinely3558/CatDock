package com.catdock.app.ui

import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.remember
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel

/**
 * 页面级状态容器，自带可取消的作用域。
 *
 * 不用 androidx.ViewModel：主界面里的模型是 `remember { }` 创建的，不挂在 ViewModelStore 上，
 * `viewModelScope` 因此永不取消——切换账号后旧账号的轮询还在跑（BUG-1）。
 * 配合 [rememberScreenModel] 按账号 keying，key 一变旧模型即刻 close。
 */
abstract class ScreenModel {
    protected val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate)

    fun close() {
        scope.cancel()
    }
}

/** 按 [key]（一般是账号或任务 id）持有模型；key 变化或离开组合时关闭上一个模型 */
@Composable
fun <T : ScreenModel> rememberScreenModel(key: Any?, factory: () -> T): T {
    val model = remember(key) { factory() }
    DisposableEffect(model) {
        onDispose { model.close() }
    }
    return model
}
