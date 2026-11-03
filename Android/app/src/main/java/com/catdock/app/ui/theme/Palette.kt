package com.catdock.app.ui.theme

import androidx.compose.ui.graphics.Color
import kotlin.math.roundToInt

/**
 * 双主题色板：亮色「柔黄浅蓝通透」+ 暗色「乌木鎏金微光」。
 * 所有色值集中在这里，配合 BentoSpec 配置表整体换肤，不散落到各页面。
 */

/** 亮暗模式偏好 */
enum class ModePreference(val label: String) {
    SYSTEM("跟随系统"),
    LIGHT("浅色"),
    DARK("深色"),
}

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
 *  · 背景层 bg / bgTop / bgBottom / blob*
 *  · 玻璃层 glassCard / glassStrong / card / dialog / hairline / glow
 *  · 文字层 text / text2 / text3
 *  · 语义色 primary / green / amber / red / blue + 各自 soft
 *  · 组件底 codeBg / inputBg / ghostBg / ghostHover / mask / shadow / buttonStroke
 */
data class CatPalette(
    val bg: Color,
    /** 45° 线性渐变起点（屏幕左上） */
    val bgTop: Color,
    /** 45° 线性渐变终点（屏幕右下） */
    val bgBottom: Color,
    /** 背景光斑：三团同色系柔光，制造通透层次 */
    val blobA: Color,
    val blobB: Color,
    val blobC: Color,
    /** 卡片玻璃基底（半透，靠背景透出渐变色） */
    val glassCard: Color,
    /** 顶栏 / 底部导航 / 弹窗：需要压住背景的可读性，透明度更高 */
    val glassStrong: Color,
    /** 需要不透明底色的场合（旧 card 语义） */
    val card: Color,
    /** 弹窗压底色：近乎不透明，浮在正文上时不能透出下层文字 */
    val dialog: Color,
    val border: Color,
    /** 卡片上沿环境反光高光 */
    val hairline: Color,
    /** 暗色卡片边缘微光 / 亮色主色环境光 */
    val glow: Color,
    val text: Color,
    val text2: Color,
    val text3: Color,
    val primary: Color,
    val primaryHover: Color,
    val primarySoft: Color,
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
    /** 主按钮细描边：亮色走炭黑 #1A1A1D，暗色走同色鎏金发光描边 */
    val buttonStroke: Color,
    /** 主按钮上的文字色 */
    val onPrimary: Color,
    /** 开关滑块 */
    val knob: Color,
)

// ===== 亮色 · 柔黄浅蓝通透版 =====
private val BentoLight = CatPalette(
    bg = C(0xF7F4E8),
    bgTop = C(0xFFFFD0),
    bgBottom = C(0xD8EFFF),
    blobA = rgba(255, 236, 148, 0.75f),
    blobB = rgba(198, 232, 255, 0.70f),
    blobC = rgba(246, 180, 210, 0.45f),
    glassCard = rgba(255, 255, 255, 0.44f),
    glassStrong = rgba(255, 255, 255, 0.66f),
    card = rgba(255, 255, 255, 0.82f),
    dialog = rgba(253, 251, 249, 0.97f),
    border = rgba(26, 26, 29, 0.12f),
    hairline = rgba(255, 255, 255, 0.85f),
    glow = rgba(230, 57, 124, 0.18f),
    text = C(0x222222),
    text2 = C(0x444444),
    text3 = C(0x777777),
    primary = C(0xE6397C),
    primaryHover = C(0xC22B64),
    primarySoft = rgba(230, 57, 124, 0.13f),
    green = C(0x17A05F),
    greenSoft = rgba(23, 160, 95, 0.14f),
    amber = C(0xC97C10),
    amberSoft = rgba(201, 124, 16, 0.16f),
    red = C(0xD93B3B),
    redSoft = rgba(217, 59, 59, 0.14f),
    blue = C(0x3E6FD1),
    blueSoft = rgba(62, 111, 209, 0.14f),
    codeBg = rgba(255, 255, 255, 0.52f),
    inputBg = rgba(255, 255, 255, 0.60f),
    ghostBg = rgba(255, 255, 255, 0.55f),
    ghostHover = rgba(230, 57, 124, 0.10f),
    mask = rgba(34, 34, 34, 0.40f),
    shadow = rgba(42, 46, 56, 0.16f),
    buttonStroke = C(0x1A1A1D),
    onPrimary = C(0xFFFFFF),
    knob = C(0xFFFFFF),
)

// ===== 暗色 · 乌木鎏金微光版 =====
private val BentoDark = CatPalette(
    bg = C(0x2E2A27),
    bgTop = C(0x34302B),
    bgBottom = C(0x221E1B),
    blobA = rgba(198, 154, 75, 0.26f),
    blobB = rgba(92, 78, 66, 0.40f),
    blobC = rgba(230, 57, 124, 0.10f),
    glassCard = rgba(40, 38, 35, 0.52f),
    glassStrong = rgba(46, 42, 39, 0.72f),
    card = rgba(52, 47, 42, 0.88f),
    dialog = rgba(48, 43, 38, 0.97f),
    border = rgba(232, 221, 200, 0.16f),
    hairline = rgba(232, 221, 200, 0.14f),
    glow = rgba(198, 154, 75, 0.42f),
    text = C(0xE8DDC8),
    text2 = C(0xBFB29C),
    text3 = C(0x8F8471),
    primary = C(0xC69A4B),
    primaryHover = C(0xD9AE63),
    primarySoft = rgba(198, 154, 75, 0.20f),
    green = C(0x7BC98F),
    greenSoft = rgba(123, 201, 143, 0.18f),
    amber = C(0xE3B45C),
    amberSoft = rgba(227, 180, 92, 0.18f),
    red = C(0xE4696B),
    redSoft = rgba(228, 105, 107, 0.18f),
    blue = C(0x7FA6E0),
    blueSoft = rgba(127, 166, 224, 0.18f),
    codeBg = rgba(0, 0, 0, 0.22f),
    inputBg = rgba(255, 246, 226, 0.08f),
    ghostBg = rgba(232, 221, 200, 0.08f),
    ghostHover = rgba(198, 154, 75, 0.18f),
    mask = rgba(0, 0, 0, 0.60f),
    shadow = rgba(0, 0, 0, 0.55f),
    buttonStroke = C(0xC69A4B),
    onPrimary = C(0x241F19),
    knob = C(0xE8DDC8),
)

fun paletteOf(dark: Boolean): CatPalette = if (dark) BentoDark else BentoLight
