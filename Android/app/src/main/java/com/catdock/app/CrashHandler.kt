package com.catdock.app

import android.content.Context
import android.os.Build
import java.io.File
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/**
 * 全局崩溃捕获：未捕获异常写入 filesDir/last_crash.txt，
 * 下次启动在界面展示崩溃报告（用户可一键复制反馈），避免无 adb 时无法定位闪退。
 */
object CrashHandler {

    private fun file(context: Context) = File(context.filesDir, "last_crash.txt")

    fun install(context: Context) {
        val previous = Thread.getDefaultUncaughtExceptionHandler()
        Thread.setDefaultUncaughtExceptionHandler { thread, throwable ->
            runCatching {
                file(context).writeText(
                    buildString {
                        appendLine("time: ${SimpleDateFormat("yyyy-MM-dd HH:mm:ss", Locale.CHINA).format(Date())}")
                        appendLine("device: ${Build.MANUFACTURER} ${Build.MODEL}")
                        appendLine("system: Android ${Build.VERSION.RELEASE} (API ${Build.VERSION.SDK_INT})")
                        appendLine("thread: ${thread.name}")
                        appendLine()
                        append(android.util.Log.getStackTraceString(throwable))
                        throwable.cause?.let {
                            appendLine()
                            appendLine("---- cause ----")
                            append(android.util.Log.getStackTraceString(it))
                        }
                    },
                )
            }
            // 交给系统默认处理（结束进程），保持标准崩溃行为
            previous?.uncaughtException(thread, throwable)
        }
    }

    /** 读取上次崩溃报告（存在则返回文本） */
    fun read(context: Context): String? {
        val f = file(context)
        if (!f.exists()) return null
        return runCatching { f.readText() }.getOrNull()?.takeIf { it.isNotBlank() }
    }

    /** 用户确认看过即删除：否则崩溃报告页会每次启动都弹 */
    fun clear(context: Context) {
        runCatching { file(context).delete() }
    }
}
