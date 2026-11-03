package com.catdock.app.ui.theme

import android.app.Activity
import android.os.Build
import androidx.compose.animation.core.Animatable
import androidx.compose.animation.core.FastOutSlowInEasing
import androidx.compose.animation.core.tween
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.foundation.shape.CornerBasedShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Shapes
import androidx.compose.material3.Typography
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.SideEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Shape
import androidx.compose.ui.graphics.lerp
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalView
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.view.WindowCompat

/**
 * 唯一渲染入口：Bento 双主题。
 * 主题切换不把色板与配置表直接换成新值，而是整体按 420ms ease-in-out 插值，
 * 于是颜色、渐变、发光、模糊、栅格间距一起平滑过渡，不会一刀切跳变。
 */
@Composable
fun CatdockTheme(
    darkTheme: Boolean = isSystemInDarkTheme(),
    content: @Composable () -> Unit,
) {
    val spec = rememberBentoSpec(specOf(darkTheme))
    val palette = rememberBentoPalette(paletteOf(darkTheme), spec.themeMillis)
    val window = bentoWindowOf(
        screenDp = LocalConfiguration.current.screenWidthDp.toFloat(),
        baseGap = spec.gap,
    )
    val scheme = colorSchemeOf(palette, darkTheme)
    val view = LocalView.current
    val activityWindow = (LocalContext.current as? Activity)?.window

    if (!view.isInEditMode && activityWindow != null) {
        SideEffect {
            // 暗色是低亮度乌木底，状态栏图标反白；亮色通透底用深色图标
            WindowCompat.getInsetsController(activityWindow, view).isAppearanceLightStatusBars = !darkTheme
        }
    }

    MaterialTheme(
        colorScheme = scheme,
        typography = catTypography(),
        shapes = Shapes(
            extraSmall = radiusShape(spec.controlRadius),
            small = radiusShape(spec.controlRadius),
            medium = radiusShape(spec.cardRadius),
            large = radiusShape(spec.cardRadius),
            extraLarge = radiusShape(spec.cardRadius),
        ),
        content = {
            // 各页面统一从 LocalPalette / LocalSpec / LocalBento 取值；
            // 不 provider 的话永远落在亮色默认值上，深色模式即失效
            CompositionLocalProvider(
                LocalPalette provides palette,
                LocalSpec provides spec,
                LocalBento provides window,
                content = content,
            )
        },
    )
}

/** 系统模糊通道：Android 12（API 31）起支持 RenderEffect，低版本自动降级为高透纯色底 */
val supportsSystemBlur: Boolean
    get() = Build.VERSION.SDK_INT >= Build.VERSION_CODES.S

private val EaseInOut = FastOutSlowInEasing

@Composable
private fun rememberBentoSpec(target: BentoSpec): BentoSpec {
    if (!target.motion) return target
    var from by remember { mutableStateOf(target) }
    var to by remember { mutableStateOf(target) }
    var current by remember { mutableStateOf(target) }
    val anim = remember { Animatable(1f) }

    LaunchedEffect(target) {
        if (to == target) return@LaunchedEffect
        from = current
        to = target
        anim.snapTo(0f)
        anim.animateTo(1f, animationSpec = tween(target.themeMillis, easing = EaseInOut)) {
            current = lerpSpec(from, to, value)
        }
        current = to
    }
    return current
}

@Composable
private fun rememberBentoPalette(target: CatPalette, millis: Int): CatPalette {
    var from by remember { mutableStateOf(target) }
    var to by remember { mutableStateOf(target) }
    var current by remember { mutableStateOf(target) }
    val anim = remember { Animatable(1f) }

    LaunchedEffect(target) {
        if (to == target) return@LaunchedEffect
        // 动画中途再次切换时从当前插值结果继续，避免跳色
        from = current
        to = target
        anim.snapTo(0f)
        anim.animateTo(1f, animationSpec = tween(millis, easing = EaseInOut)) {
            current = lerpPalette(from, to, value)
        }
        current = to
    }
    return current
}

private fun lerpSpec(a: BentoSpec, b: BentoSpec, t: Float): BentoSpec {
    fun f(x: Float, y: Float) = x + (y - x) * t
    return BentoSpec(
        grid = f(a.grid, b.grid),
        gap = f(a.gap, b.gap),
        screenPadding = f(a.screenPadding, b.screenPadding),
        cardPadding = f(a.cardPadding, b.cardPadding),
        topInset = f(a.topInset, b.topInset),
        bottomInset = f(a.bottomInset, b.bottomInset),
        cardRadius = f(a.cardRadius, b.cardRadius),
        controlRadius = f(a.controlRadius, b.controlRadius),
        badgeRadius = f(a.badgeRadius, b.badgeRadius),
        stroke = f(a.stroke, b.stroke),
        buttonStroke = f(a.buttonStroke, b.buttonStroke),
        blurRadius = f(a.blurRadius, b.blurRadius),
        glowRadius = f(a.glowRadius, b.glowRadius),
        buttonGlow = f(a.buttonGlow, b.buttonGlow),
        elevation = f(a.elevation, b.elevation),
        pressScale = f(a.pressScale, b.pressScale),
        minTouch = f(a.minTouch, b.minTouch),
        dialogMaxWidth = f(a.dialogMaxWidth, b.dialogMaxWidth),
        themeMillis = a.themeMillis,
        enterMillis = a.enterMillis,
        staggerMillis = a.staggerMillis,
        entryBlur = f(a.entryBlur, b.entryBlur),
        motion = true,
    )
}

private fun lerpPalette(a: CatPalette, b: CatPalette, t: Float): CatPalette {
    fun c(x: Color, y: Color) = lerp(x, y, t)
    return CatPalette(
        bg = c(a.bg, b.bg),
        bgTop = c(a.bgTop, b.bgTop),
        bgBottom = c(a.bgBottom, b.bgBottom),
        blobA = c(a.blobA, b.blobA),
        blobB = c(a.blobB, b.blobB),
        blobC = c(a.blobC, b.blobC),
        glassCard = c(a.glassCard, b.glassCard),
        glassStrong = c(a.glassStrong, b.glassStrong),
        card = c(a.card, b.card),
        dialog = c(a.dialog, b.dialog),
        border = c(a.border, b.border),
        hairline = c(a.hairline, b.hairline),
        glow = c(a.glow, b.glow),
        text = c(a.text, b.text),
        text2 = c(a.text2, b.text2),
        text3 = c(a.text3, b.text3),
        primary = c(a.primary, b.primary),
        primaryHover = c(a.primaryHover, b.primaryHover),
        primarySoft = c(a.primarySoft, b.primarySoft),
        green = c(a.green, b.green),
        greenSoft = c(a.greenSoft, b.greenSoft),
        amber = c(a.amber, b.amber),
        amberSoft = c(a.amberSoft, b.amberSoft),
        red = c(a.red, b.red),
        redSoft = c(a.redSoft, b.redSoft),
        blue = c(a.blue, b.blue),
        blueSoft = c(a.blueSoft, b.blueSoft),
        codeBg = c(a.codeBg, b.codeBg),
        inputBg = c(a.inputBg, b.inputBg),
        ghostBg = c(a.ghostBg, b.ghostBg),
        ghostHover = c(a.ghostHover, b.ghostHover),
        mask = c(a.mask, b.mask),
        shadow = c(a.shadow, b.shadow),
        buttonStroke = c(a.buttonStroke, b.buttonStroke),
        onPrimary = c(a.onPrimary, b.onPrimary),
        knob = c(a.knob, b.knob),
    )
}

private fun radiusShape(radius: Float): CornerBasedShape = RoundedCornerShape(radius.dp)

private fun colorSchemeOf(p: CatPalette, dark: Boolean) =
    (if (dark) darkColorScheme() else lightColorScheme()).copy(
        primary = p.primary,
        onPrimary = p.onPrimary,
        primaryContainer = p.primarySoft,
        onPrimaryContainer = p.primary,
        secondary = p.text2,
        onSecondary = p.bg,
        secondaryContainer = p.ghostHover,
        onSecondaryContainer = p.text,
        tertiary = p.blue,
        onTertiary = Color.White,
        background = p.bg,
        onBackground = p.text,
        surface = p.card,
        onSurface = p.text,
        surfaceVariant = p.codeBg,
        onSurfaceVariant = p.text2,
        inverseSurface = p.text,
        inverseOnSurface = p.bg,
        outline = p.border,
        outlineVariant = p.border,
        error = p.red,
        onError = Color.White,
        errorContainer = p.redSoft,
        onErrorContainer = p.red,
        scrim = p.mask,
    )

/** 正文基准 14sp、行高 1.6；层级靠字重区分，系统动态字体缩放照常生效 */
private fun catTypography() = Typography().let { base ->
    fun TextStyle.at(size: Int, weight: FontWeight? = null) = copy(
        fontFamily = FontFamily.Default,
        fontWeight = weight ?: fontWeight,
        fontSize = size.sp,
        lineHeight = (size * 1.6f).sp,
    )
    base.copy(
        displaySmall = base.displaySmall.at(28),
        headlineMedium = base.headlineMedium.at(22),
        headlineSmall = base.headlineSmall.at(19),
        titleLarge = base.titleLarge.at(17, FontWeight.SemiBold),
        titleMedium = base.titleMedium.at(15, FontWeight.SemiBold),
        titleSmall = base.titleSmall.at(13, FontWeight.Medium),
        bodyLarge = base.bodyLarge.at(14),
        bodyMedium = base.bodyMedium.at(13),
        bodySmall = base.bodySmall.at(12),
        labelLarge = base.labelLarge.at(14, FontWeight.Medium),
        labelMedium = base.labelMedium.at(12, FontWeight.Medium),
        labelSmall = base.labelSmall.at(12),
    )
}
