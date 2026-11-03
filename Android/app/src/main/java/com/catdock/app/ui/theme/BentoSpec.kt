package com.catdock.app.ui.theme

import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.runtime.Composable
import androidx.compose.runtime.ProvidableCompositionLocal
import androidx.compose.runtime.compositionLocalOf
import androidx.compose.ui.graphics.Shape
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp

/**
 * Bento 配置表：栅格、安全边距、圆角、玻璃模糊、微光强度、动效时长集中在这里。
 * 任何一处调参全 App 生效，页面代码只读语义字段，不写死数字。
 * 单位用 Float（dp 数值），是为了让主题切换时能整体插值过渡。
 */
data class BentoSpec(
    /** 基准栅格 */
    val grid: Float = 8f,
    /** 网格 gap：亮 12 / 暗 14，小屏压缩到 10 */
    val gap: Float,
    /** 屏幕左右内边距 */
    val screenPadding: Float = 14f,
    /** 卡片内边距（最小 10） */
    val cardPadding: Float = 14f,
    /** 状态栏之外再预留的高度（20–28） */
    val topInset: Float = 22f,
    /** 手势导航区预留（18–24） */
    val bottomInset: Float = 20f,
    /** 卡片圆角，全局统一 12 */
    val cardRadius: Float = 12f,
    /** 控件圆角，与卡片同值，避免圆角种类过多 */
    val controlRadius: Float = 12f,
    /** 徽章用胶囊 */
    val badgeRadius: Float = 999f,
    /** 描边宽度 */
    val stroke: Float = 1f,
    /** 主按钮描边宽度：0.75–1 */
    val buttonStroke: Float = 0.9f,
    /** 玻璃模糊半径（背景光斑用；px 量级，Compose 侧按 dp 用） */
    val blurRadius: Float,
    /** 卡片边缘微光半径 */
    val glowRadius: Float,
    /** 发光通道开关：亮色主按钮关掉（0f），暗色鎏金按钮打开（1f），按半径乘算 */
    val buttonGlow: Float,
    /** 卡片软阴影高度 */
    val elevation: Float,
    /** 按下微缩比例 */
    val pressScale: Float = 0.97f,
    /** 最小触控热区 */
    val minTouch: Float = 48f,
    /** 弹窗最大宽度 */
    val dialogMaxWidth: Float = 520f,
    /** 主题切换插值时长 */
    val themeMillis: Int = 420,
    /** 卡片入场时长 */
    val enterMillis: Int = 380,
    /** 卡片入场错距 */
    val staggerMillis: Int = 55,
    /** 入场时模糊收敛的起始半径 */
    val entryBlur: Float = 5f,
    /** 动效总开关：低端机关闭后退化为直切 */
    val motion: Boolean = true,
)

private val BentoSpecLight = BentoSpec(
    gap = 12f,
    blurRadius = 20f,
    glowRadius = 6f,
    buttonGlow = 0f,
    elevation = 5f,
)

private val BentoSpecDark = BentoSpec(
    gap = 14f,
    blurRadius = 26f,
    glowRadius = 12f,
    buttonGlow = 1f,
    elevation = 2f,
)

fun specOf(dark: Boolean): BentoSpec = if (dark) BentoSpecDark else BentoSpecLight

/**
 * 响应断点：
 *   ≤360dp 小屏 → 2 列、gap 压到 10、禁用跨 2 行的大卡
 *   360–600dp 主流手机 → 2 列标准布局
 *   ≥600dp 平板 → 3 列，≥840dp 4 列
 */
data class BentoWindow(val columns: Int, val gap: Float, val screenDp: Float, val wide: Boolean)

fun bentoWindowOf(screenDp: Float, baseGap: Float): BentoWindow = when {
    screenDp < 360f -> BentoWindow(columns = 2, gap = 10f, screenDp = screenDp, wide = false)
    screenDp < 600f -> BentoWindow(columns = 2, gap = baseGap, screenDp = screenDp, wide = false)
    screenDp < 840f -> BentoWindow(columns = 3, gap = baseGap + 2f, screenDp = screenDp, wide = true)
    else -> BentoWindow(columns = 4, gap = baseGap + 4f, screenDp = screenDp, wide = true)
}

val LocalPalette: ProvidableCompositionLocal<CatPalette> = compositionLocalOf { paletteOf(false) }
val LocalSpec: ProvidableCompositionLocal<BentoSpec> = compositionLocalOf { specOf(false) }
val LocalBento: ProvidableCompositionLocal<BentoWindow> =
    compositionLocalOf { bentoWindowOf(411f, 12f) }

@Composable
fun bentoSpec(): BentoSpec = LocalSpec.current

/** 统一 12dp 卡片圆角 */
@Composable
fun catCardShape(): Shape =
    RoundedCornerShape(LocalSpec.current.cardRadius.dp)

@Composable
fun catControlShape(): Shape =
    RoundedCornerShape(LocalSpec.current.controlRadius.dp)

@Composable
fun catBadgeShape(): Shape =
    RoundedCornerShape(LocalSpec.current.badgeRadius.dp)

@Composable
fun bentoGap(): Dp = LocalBento.current.gap.dp

@Composable
fun bentoScreenPadding(): Dp = LocalSpec.current.screenPadding.dp
