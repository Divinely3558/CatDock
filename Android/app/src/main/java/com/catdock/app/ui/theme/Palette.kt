package com.catdock.app.ui.theme

import androidx.compose.ui.graphics.Color
import kotlin.math.roundToInt

/**
 * 极光玻璃单主题：「晨雾极光」（亮色）。
 * 所有色值集中在这里，配合 BentoSpec 配置表整体换肤，不散落到各页面。
 * 设计依据：.test/docs/android-redesign-aurora.md（aurora-ui + glassmorphism 规范）。
 */

/** CSS 六位色值直取（0xRRGGBB），补不透明 alpha */
private fun C(rgb: Int) = Color(rgb or 0xFF000000.toInt())

/** 带 alpha 的色值（0xAARRGGBB），对应 CSS rgba */
private fun A(argb: Int) = Color(argb)

/** rgba(r,g,b,a) → 0xAARRGGBB，方便照抄设计稿 */
private fun rgba(r: Int, g: Int, b: Int, a: Float): Color =
    A(
        ((a.coerceIn(0f, 1f) * 255).roundToInt() shl 24) or
            ((r.clamp255() shl 16) or (g.clamp255() shl 8) or b.clamp255()),
    )

private fun Int.clamp255() = this.coerceIn(0, 255)

/**
 * 语义色板。字段命名按用途分组：
 *  · 背景层 bg / bgTop / bgBottom / auroraA~D（四层极光带，青紫品绿错速流动）
 *  · 玻璃层 glassCard / glassStrong / card / dialog / hairline / glow
 *  · 文字层 text / text2 / text3
 *  · 语义色 primary(+Gradient) / green / amber / red / blue + 各自 soft
 *  · 组件底 codeBg / inputBg / ghostBg / ghostHover / mask / shadow / buttonStroke
 */
data class CatPalette(
    val bg: Color,
    /** 纵向深空渐变起点（屏幕顶部） */
    val bgTop: Color,
    /** 纵向深空渐变终点（屏幕底部） */
    val bgBottom: Color,
    /** 极光带一：青 */
    val auroraA: Color,
    /** 极光带二：紫 */
    val auroraB: Color,
    /** 极光带三：品红 */
    val auroraC: Color,
    /** 极光带四：绿（最慢、最淡） */
    val auroraD: Color,
    /** 卡片玻璃基底（半透，靠背景透出极光） */
    val glassCard: Color,
    /** 顶栏 / 悬浮底导航 / 弹窗：压住流动极光的可读性，透明度更高 */
    val glassStrong: Color,
    /** 需要不透明底色的场合（聊天气泡等） */
    val card: Color,
    /** 弹窗压底色：近乎不透明，浮在正文上时不能透出下层文字 */
    val dialog: Color,
    val border: Color,
    /** 卡片上沿环境反光高光 */
    val hairline: Color,
    /** CTA 光晕 / 选中态边缘光 */
    val glow: Color,
    val text: Color,
    val text2: Color,
    val text3: Color,
    /** 主色实心回退（禁用态、非渐变场合） */
    val primary: Color,
    val primaryHover: Color,
    val primarySoft: Color,
    /** CTA 极光渐变：青 → 紫 → 品红（135°） */
    val primaryGradient: List<Color>,
    val green: Color,
    val greenSoft: Color,
    val amber: Color,
    val amberSoft: Color,
    val red: Color,
    val redSoft: Color,
    val blue: Color,
    val blueSoft: Color,
    val codeBg: Color,
    val inputBg: Color,
    val ghostBg: Color,
    val ghostHover: Color,
    val mask: Color,
    /** 柔和投影着色 */
    val shadow: Color,
    /** 渐变按钮上的细描边：弱化存在感的白边 */
    val buttonStroke: Color,
    /** 主按钮上的文字色 */
    val onPrimary: Color,
    /** 开关滑块 */
    val knob: Color,
)

private val AURORA_GRADIENT = listOf(C(0x22D3EE), C(0x8B5CF6), C(0xE879F9))

// ===== 亮色 · 晨雾极光 =====
private val BentoLight = CatPalette(
    bg = C(0xF2F5FC),
    bgTop = C(0xEAF1FF),
    bgBottom = C(0xF6F0FA),
    auroraA = rgba(191, 239, 233, 0.72f),
    auroraB = rgba(221, 211, 251, 0.76f),
    auroraC = rgba(248, 217, 242, 0.66f),
    auroraD = rgba(211, 244, 229, 0.60f),
    glassCard = rgba(255, 255, 255, 0.58f),
    glassStrong = rgba(255, 255, 255, 0.78f),
    card = rgba(255, 255, 255, 0.85f),
    dialog = rgba(253, 253, 255, 0.97f),
    border = rgba(24, 24, 52, 0.10f),
    hairline = rgba(255, 255, 255, 0.85f),
    glow = rgba(108, 92, 231, 0.20f),
    text = C(0x181B2E),
    text2 = C(0x3E4460),
    text3 = C(0x5D6378),
    primary = C(0x6C5CE7),
    primaryHover = C(0x5A4BD1),
    primarySoft = rgba(108, 92, 231, 0.14f),
    primaryGradient = AURORA_GRADIENT,
    green = C(0x0E9F6E),
    greenSoft = rgba(14, 159, 110, 0.14f),
    amber = C(0xB45309),
    amberSoft = rgba(180, 83, 9, 0.14f),
    red = C(0xDC2626),
    redSoft = rgba(220, 38, 38, 0.14f),
    blue = C(0x2563EB),
    blueSoft = rgba(37, 99, 235, 0.14f),
    codeBg = rgba(255, 255, 255, 0.55f),
    inputBg = rgba(255, 255, 255, 0.62f),
    ghostBg = rgba(255, 255, 255, 0.55f),
    ghostHover = rgba(108, 92, 231, 0.10f),
    mask = rgba(24, 27, 46, 0.35f),
    shadow = rgba(30, 34, 60, 0.16f),
    buttonStroke = rgba(24, 27, 46, 0.10f),
    onPrimary = C(0xFFFFFF),
    knob = C(0xFFFFFF),
)

/** 单主题：晨雾极光（亮色） */
fun paletteOf(): CatPalette = BentoLight
