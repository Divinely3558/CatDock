package com.catdock.app.ui

import android.content.Context
import android.content.Intent
import androidx.core.content.FileProvider
import java.io.File

/**
 * 服务端导出接口返回的是附件文本（聊天记录 / 日志），移动端交给系统分享面板落地。
 * 文件写入 cacheDir/exports，由 FileProvider 授权只读 URI。
 */
fun shareTextFile(context: Context, bytes: ByteArray, fileName: String) {
    val dir = File(context.cacheDir, "exports").apply { mkdirs() }
    val file = File(dir, fileName.substringAfterLast('/').ifEmpty { "export.txt" })
    file.writeBytes(bytes)
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
