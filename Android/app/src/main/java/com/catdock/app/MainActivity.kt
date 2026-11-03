package com.catdock.app

import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.os.Bundle
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.catdock.app.data.Session
import com.catdock.app.ui.AppNav
import com.catdock.app.ui.theme.Appearance
import com.catdock.app.ui.theme.CatdockTheme
import com.catdock.app.ui.theme.ModePreference

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        val app = application as CatdockApp
        setContent {
            val appearance by app.appearanceStore.appearance
                .collectAsStateWithLifecycle(initialValue = Appearance())
            val dark = when (appearance.mode) {
                ModePreference.SYSTEM -> isSystemInDarkTheme()
                ModePreference.LIGHT -> false
                ModePreference.DARK -> true
            }
            CatdockTheme(darkTheme = dark) {
                // 上次运行发生过崩溃：优先展示崩溃报告页（可复制反馈），
                // 此时不再渲染主界面，避免同一崩溃反复触发
                var crashReport by remember { mutableStateOf(CrashHandler.read(this)) }
                if (crashReport != null) {
                    CrashReportScreen(
                        report = crashReport ?: "",
                        onContinue = { CrashHandler.clear(this); crashReport = null },
                    )
                } else {
                    val session by app.sessionStore.session
                        .collectAsStateWithLifecycle(initialValue = Session())
                    AppNav(session = session, repository = app.repository, sessionStore = app.sessionStore)
                }
            }
        }
    }
}

/** 崩溃报告页：等宽字体展示堆栈，一键复制便于反馈 */
@Composable
private fun CrashReportScreen(report: String, onContinue: () -> Unit) {
    val context = LocalContext.current
    Surface(color = MaterialTheme.colorScheme.surface, modifier = Modifier.fillMaxSize()) {
        Column(Modifier.fillMaxSize().padding(20.dp)) {
            Text("上次运行发生崩溃", fontSize = 20.sp, fontWeight = FontWeight.Bold)
            Text(
                "请点击「复制报告」后把内容发给开发者",
                fontSize = 13.sp,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.padding(top = 4.dp, bottom = 12.dp),
            )
            Text(
                report,
                fontSize = 11.sp,
                fontFamily = FontFamily.Monospace,
                modifier = Modifier
                    .weight(1f)
                    .fillMaxWidth()
                    .verticalScroll(rememberScrollState())
                    .horizontalScroll(rememberScrollState()),
            )
            Row(Modifier.fillMaxWidth().padding(top = 12.dp)) {
                Button(onClick = { copyToClipboard(context, report) }) { Text("复制报告") }
                Spacer(Modifier.weight(1f))
                OutlinedButton(onClick = onContinue) { Text("继续使用") }
            }
        }
    }
}

private fun copyToClipboard(context: Context, text: String) {
    val cm = context.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
    cm.setPrimaryClip(ClipData.newPlainText("catdock crash", text))
    Toast.makeText(context, "已复制崩溃报告", Toast.LENGTH_SHORT).show()
}
