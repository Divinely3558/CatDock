package com.catdock.app.ui

import android.content.Context
import android.content.Intent
import android.os.Handler
import android.os.Looper
import android.util.Log
import androidx.core.content.FileProvider
import java.io.File

/**
 * 服务端导出接口返回的是附件文本（聊天记录 / 日志），移动端交给系统分享面板落地。
 * 文件写入 cacheDir/exports，由 FileProvider 授权只读 URI。
 *
 * 写盘放到后台线程：导出内容可达数 MB，在主线程写会卡顿；分享面板回到主线程再拉起。
 */
fun shareTextFile(context: Context, bytes: ByteArray, fileName: String) {
    val dir = File(context.cacheDir, "exports").apply { mkdirs() }
    val file = File(dir, fileName.substringAfterLast('/').ifEmpty { "export.txt" })
    val main = Handler(Looper.getMainLooper())
    Thread {
        val written = runCatching { file.writeBytes(bytes) }.isSuccess
        main.post {
            if (!written) {
                Log.w("CatdockNet", "export write failed: ${file.name}")
                return@post
            }
            val uri = FileProvider.getUriForFile(context, "${context.packageName}.fileprovider", file)
            val intent = Intent(Intent.ACTION_SEND).apply {
                type = "text/plain"
                putExtra(Intent.EXTRA_STREAM, uri)
                addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
            }
            context.startActivity(Intent.createChooser(intent, "导出 $fileName").apply {
                addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            })
        }
    }.start()
}
