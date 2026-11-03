package com.catdock.app.ui.components

import androidx.compose.animation.core.Animatable
import androidx.compose.animation.core.FastOutSlowInEasing
import androidx.compose.animation.animateColorAsState
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.interaction.collectIsPressedAsState
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxScope
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.layout.wrapContentWidth
import androidx.compose.foundation.lazy.LazyListState
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.material3.ripple
import androidx.compose.animation.core.animateFloat
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.ProvidableCompositionLocal
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.runtime.snapshotFlow
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.blur
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.draw.scale
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.RoundRect
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Outline
import androidx.compose.ui.graphics.Shape
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.graphics.lerp
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import com.catdock.app.ui.theme.LocalBento
import com.catdock.app.ui.theme.LocalPalette
import com.catdock.app.ui.theme.LocalSpec
import com.catdock.app.ui.theme.catCardShape
import com.catdock.app.ui.theme.supportsSystemBlur
import kotlinx.coroutines.delay

/**
 * Bento 布局基元：毛玻璃背景层、玻璃面、栅格、入场动效、骨架屏、弹窗外框。
 *
 * 玻璃面为什么不做「采样背景再模糊」：Compose 没有系统背景模糊通道，逐卡自建模糊层
 * 在低端机上必然掉帧。这里用半透玻璃基底直接透出 45° 渐变 + 上沿环境反光 + 软阴影/微光，
 * 静态观感与毛玻璃等价，且 API 24 起表现一致；真正的模糊只用在背景光斑上（一层，成本恒定）。
 */

/** 滚动视差状态：滚动容器上报像素，背景层按倍速跟随 */
class BentoFx {
    var scrollPx by mutableFloatStateOf(0f)
}

val LocalBentoFx: ProvidableCompositionLocal<BentoFx> = staticCompositionLocalOf { BentoFx() }

@Composable
fun rememberBentoFx(): BentoFx = remember { BentoFx() }

@Composable
fun TrackBentoScroll(scroll: androidx.compose.foundation.ScrollState) {
    val fx = LocalBentoFx.current
    LaunchedEffect(scroll, fx) {
        snapshotFlow { scroll.value.toFloat() }.collect { fx.scrollPx = it }
    }
}

@Composable
fun TrackBentoScroll(state: LazyListState) {
    val fx = LocalBentoFx.current
    LaunchedEffect(state, fx) {
        snapshotFlow {
            val first = state.layoutInfo.visibleItemsInfo.firstOrNull()
            val index = first?.index ?: 0
            val inItem = (first?.offset ?: 0).toFloat()
            index * 120f - inItem
        }.collect { fx.scrollPx = it }
    }
}

/** 系统模糊通道存在才加模糊，低配设备退化为高透渐变底 */
private fun Modifier.softBlur(radius: Dp): Modifier =
    if (supportsSystemBlur && radius > 0.dp) this.blur(radius) else this

/**
 * 背景层：45° 线性渐变（柔黄→浅冰蓝 / 乌木→深乌木）+ 三团同色系柔光 + 滚动视差。
 * 透明度压得很低，不抢卡片内容；状态栏与手势区由渐变本身覆盖。
 */
@Composable
fun BentoBackdrop(modifier: Modifier = Modifier) {
    val p = LocalPalette.current
    val spec = LocalSpec.current
    val fx = LocalBentoFx.current
    val blur = spec.blurRadius.dp
    val parallax = -fx.scrollPx * 0.25f

    Box(modifier.fillMaxSize()) {
        Box(
            Modifier
                .fillMaxSize()
                .background(
                    Brush.linearGradient(
                        colors = listOf(p.bgTop, p.bg, p.bgBottom),
                        start = Offset.Zero,
                        end = Offset.Infinite,
                    ),
                ),
        )
        Box(Modifier.fillMaxSize().graphicsLayer { translationY = parallax }) {
            SoftBlob(Alignment.TopStart, offsetX = (-56).dp, offsetY = (-32).dp, size = 300.dp, color = p.blobA, blur = blur)
            SoftBlob(Alignment.TopEnd, offsetX = (-24).dp, offsetY = 84.dp, size = 220.dp, color = p.blobB, blur = blur)
            SoftBlob(Alignment.BottomStart, offsetX = 44.dp, offsetY = (-160).dp, size = 260.dp, color = p.blobC, blur = blur)
        }
    }
}

@Composable
private fun BoxScope.SoftBlob(
    align: Alignment,
    offsetX: Dp,
    offsetY: Dp,
    size: Dp,
    color: Color,
    blur: Dp,
) {
    Box(
        Modifier
            .align(align)
            .offset(x = offsetX, y = offsetY)
            .size(size)
            .softBlur(blur)
            .background(
                Brush.radialGradient(colors = listOf(color, color.copy(alpha = 0f))),
                CircleShape,
            ),
    )
}

/**
 * 软阴影与边缘微光。shadow() 会强制离屏合成，半透玻璃在它里面会被按阴影半径
 * 留出内边距、四角露成直角矩形，所以改成沿形状外圈叠几道递减的描边环，手工逼近模糊衰减。
 */
fun Modifier.glassHalo(radius: Dp, color: Color, shape: Shape): Modifier =
    if (radius <= 0.dp || color.alpha <= 0.002f) this else drawBehind {
        val outline = shape.createOutline(size, layoutDirection, this)
        val box = if (outline is Outline.Rounded) outline.roundRect else RoundRect(0f, 0f, size.width, size.height)
        val cr = box.topLeftCornerRadius
        val bands = 7
        val step = radius.toPx() / bands
        for (i in 1..bands) {
            val t = (i - 0.5f) / bands
            val d = step * (i - 0.5f)
            drawRoundRect(
                // 平方衰减 + 略宽描边让环与环互相叠盖，看不出阶梯
                color = color.copy(alpha = color.alpha * (1f - t) * (1f - t) * 0.34f),
                topLeft = Offset(box.left - d, box.top - d),
                size = Size(box.width + d * 2f, box.height + d * 2f),
                cornerRadius = CornerRadius(cr.x + d, cr.y + d),
                style = Stroke(width = step * 1.9f),
            )
        }
    }

/**
 * 玻璃面：卡片 / 浮层 / 弹窗共用。绘制顺序即层叠顺序：
 * 外阴影 → 半透基底 → 上沿反光 → 按压叠加 → 描边。
 */
@Composable
fun Modifier.bentoSurface(
    shape: Shape = catCardShape(),
    emphasis: Boolean = false,
    strong: Boolean = false,
    pressed: Boolean = false,
    minHeight: Dp? = null,
): Modifier {
    val p = LocalPalette.current
    val spec = LocalSpec.current
    val active = emphasis || pressed

    val tint by animateColorAsState(
        if (active) p.primarySoft else Color.Transparent,
        tween(150),
        label = "glassTint",
    )
    val line by animateColorAsState(
        if (active) p.primary else p.border,
        tween(150),
        label = "glassLine",
    )
    val halo by animateFloatAsState(
        if (active) spec.glowRadius * 1.35f else spec.glowRadius,
        tween(150),
        label = "glassHalo",
    )

    // 亮色是低透明软投影，暗色是鎏金边缘微光：同一通道由色板给值，切换时一起插值
    val haloColor = lerp(p.shadow, p.glow, spec.buttonGlow)
    var m = this
        .glassHalo(halo.dp, haloColor, shape)
        .background(if (strong) p.glassStrong else p.glassCard, shape)
        .background(
            Brush.verticalGradient(
                0f to p.hairline.copy(alpha = if (strong) 0.32f else 0.22f),
                0.18f to Color.Transparent,
            ),
            shape,
        )
        .background(tint, shape)
        .border(spec.stroke.dp, line, shape)
    if (minHeight != null) m = m.heightIn(min = minHeight)
    return m
}

/** 可点玻璃面：按下微缩 scale + MD3 原生水波纹（保留系统触控反馈） */
@Composable
fun Modifier.bentoPress(
    onClick: () -> Unit,
    enabled: Boolean = true,
    shape: Shape = catCardShape(),
    strong: Boolean = false,
    emphasis: Boolean = false,
    minHeight: Dp? = null,
    ripple: Boolean = true,
): Modifier {
    val spec = LocalSpec.current
    val interaction = remember { MutableInteractionSource() }
    val pressed by interaction.collectIsPressedAsState()
    val scale by animateFloatAsState(
        if (enabled && pressed) spec.pressScale else 1f,
        animationSpec = tween(150, easing = FastOutSlowInEasing),
        label = "pressScale",
    )
    return this
        .scale(scale)
        .bentoSurface(
            shape = shape,
            emphasis = emphasis,
            strong = strong,
            pressed = pressed,
            minHeight = minHeight,
        )
        .clickable(
            interactionSource = interaction,
            indication = if (ripple) ripple() else null,
            enabled = enabled,
            onClick = onClick,
        )
}

/** 卡片入场：向上位移 + 淡入 + 模糊逐步收敛，按 index 错距依次进入 */
@Composable
fun Modifier.bentoEnter(index: Int, key: Any = index): Modifier {
    val spec = LocalSpec.current
    if (!spec.motion) return this
    val state = remember(key) { Animatable(0f) }
    LaunchedEffect(key, index, spec.enterMillis, spec.staggerMillis) {
        state.snapTo(0f)
        if (index > 0) delay(index * spec.staggerMillis.toLong())
        state.animateTo(1f, tween(spec.enterMillis, easing = FastOutSlowInEasing))
    }
    val t = state.value
    val entryBlur = (spec.entryBlur * (1f - t)).coerceAtLeast(0f)
    return this
        .graphicsLayer {
            alpha = 0.15f + 0.85f * t
            translationY = (1f - t) * 18.dp.toPx()
            scaleX = 0.985f + 0.015f * t
            scaleY = scaleX
        }
        .let { if (entryBlur > 0.2f) it.blur(entryBlur.dp) else it }
}

// ---------- Bento 栅格 ----------

/**
 * 栅格单元：span = 占用列数（1×1 / 2×1 / 1×2 / 2×2 / 1×3 由 span 与行高组合出来）。
 * 小屏自动把 span 压进列数，超大卡拆成小单元，不出现挤成一团的窄条。
 */
data class BentoCell(val key: Any, val span: Int = 1, val content: @Composable () -> Unit)

@Composable
fun BentoGrid(
    cells: List<BentoCell>,
    modifier: Modifier = Modifier,
    gap: Dp = LocalBento.current.gap.dp,
    columns: Int = LocalBento.current.columns,
) {
    val rows = remember(cells, columns) { packBentoRows(cells, columns) }
    Column(modifier, verticalArrangement = Arrangement.spacedBy(gap)) {
        rows.forEach { row ->
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(gap)) {
                row.forEach { cell ->
                    Box(Modifier.weight(cell.span.toFloat())) { cell.content() }
                }
                // 末行补空位：不补的话残余 span 会把最后一格拉伸成全宽
                val used = row.sumOf { it.span }
                if (used < columns) repeat(columns - used) { Spacer(Modifier.weight(1f)) }
            }
        }
    }
}

private fun packBentoRows(cells: List<BentoCell>, columns: Int): List<List<BentoCell>> {
    val rows = mutableListOf<List<BentoCell>>()
    var row = mutableListOf<BentoCell>()
    var used = 0
    cells.forEach { cell ->
        val span = cell.span.coerceIn(1, columns)
        if (used + span > columns && row.isNotEmpty()) {
            rows.add(row.toList())
            row = mutableListOf()
            used = 0
        }
        row.add(cell.copy(span = span))
        used += span
    }
    if (row.isNotEmpty()) rows.add(row.toList())
    return rows
}

// ---------- 骨架屏 ----------

/** 加载骨架：复用同一栅格与 12dp 圆角玻璃基底，占位块呼吸式提亮 */
@Composable
fun BentoSkeleton(
    rows: Int = 3,
    modifier: Modifier = Modifier,
    cellHeight: Dp = 96.dp,
) {
    val p = LocalPalette.current
    val spec = LocalSpec.current
    val shape = catCardShape()
    val transition = rememberInfiniteTransition(label = "skeleton")
    val pulse by transition.animateFloat(
        initialValue = 0.25f,
        targetValue = 0.6f,
        animationSpec = infiniteRepeatable(tween(1100)),
        label = "pulse",
    )

    Column(modifier, verticalArrangement = Arrangement.spacedBy(spec.gap.dp)) {
        repeat(rows) { i ->
            Column(
                Modifier
                    .fillMaxWidth()
                    .height(cellHeight)
                    .bentoSurface(shape = shape)
                    .bentoEnter(i)
                    .padding(spec.cardPadding.dp),
                verticalArrangement = Arrangement.spacedBy(10.dp),
            ) {
                Box(
                    Modifier
                        .fillMaxWidth(0.42f)
                        .height(12.dp)
                        .background(p.text3.copy(alpha = pulse), RoundedCornerShape(6.dp)),
                )
                Box(
                    Modifier
                        .fillMaxWidth(0.8f)
                        .height(10.dp)
                        .background(p.border.copy(alpha = pulse + 0.2f), RoundedCornerShape(5.dp)),
                )
                Box(
                    Modifier
                        .fillMaxWidth(0.6f)
                        .height(10.dp)
                        .background(p.border.copy(alpha = pulse + 0.1f), RoundedCornerShape(5.dp)),
                )
            }
        }
    }
}

// ---------- 弹窗 ----------

/** 居中、最大 520dp、内部统一 16dp；内容超长时只在内层滚动，不把弹窗撑成全屏 */
@Composable
fun BentoDialog(
    onDismiss: () -> Unit,
    modifier: Modifier = Modifier,
    content: @Composable ColumnScope.() -> Unit,
) {
    val p = LocalPalette.current
    val spec = LocalSpec.current
    Dialog(
        onDismissRequest = onDismiss,
        properties = DialogProperties(usePlatformDefaultWidth = false),
    ) {
        Box(Modifier.fillMaxSize().padding(18.dp), contentAlignment = Alignment.Center) {
            Column(
                modifier
                    .widthIn(max = spec.dialogMaxWidth.dp)
                    // 弹窗底下先垫一层近实色：只靠玻璃基底会透出页面正文，两层文字叠在一起读不了
                    .background(p.dialog, catCardShape())
                    .bentoSurface(shape = catCardShape(), strong = true)
                    .bentoEnter(0)
                    .padding(16.dp),
                verticalArrangement = Arrangement.spacedBy(12.dp),
            ) {
                Column(Modifier.verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                    content()
                }
            }
        }
    }
}

@Composable
fun BentoDialogTitle(text: String, trailing: @Composable (() -> Unit)? = null) {
    val p = LocalPalette.current
    Row(
        Modifier.fillMaxWidth().padding(top = 2.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        Text(text, fontSize = 17.sp, fontWeight = FontWeight.SemiBold, color = p.text, modifier = Modifier.weight(1f))
        trailing?.invoke()
    }
}

/** 标题下的一行说明：弹窗按「标题 → 说明 → 按钮」排布，说明缺失时只剩标题会显得空 */
@Composable
fun BentoDialogBody(text: String) {
    val p = LocalPalette.current
    Text(text, fontSize = 13.sp, lineHeight = 20.sp, color = p.text2, modifier = Modifier.fillMaxWidth())
}

/** 双按钮左右均分；只给确认按钮时底部居中 */
@Composable
fun BentoDialogButtons(
    confirmText: String,
    onConfirm: () -> Unit,
    dismissText: String? = null,
    onDismiss: (() -> Unit)? = null,
    confirmEnabled: Boolean = true,
    confirmVariant: CatButtonVariant = CatButtonVariant.PRIMARY,
) {
    if (dismissText != null && onDismiss != null) {
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            CatButton(dismissText, onDismiss, Modifier.weight(1f), variant = CatButtonVariant.GHOST)
            CatButton(confirmText, onConfirm, Modifier.weight(1f), enabled = confirmEnabled, variant = confirmVariant)
        }
    } else {
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.Center) {
            CatButton(
                confirmText,
                onConfirm,
                Modifier.wrapContentWidth().heightIn(min = LocalSpec.current.minTouch.dp),
                enabled = confirmEnabled,
                variant = confirmVariant,
            )
        }
    }
}

/** 空态：居中独立大 Bento 卡承载提示图文 */
@Composable
fun BentoEmptyState(
    icon: androidx.compose.ui.graphics.vector.ImageVector,
    text: String,
    hint: String? = null,
    modifier: Modifier = Modifier,
    action: @Composable (() -> Unit)? = null,
) {
    val p = LocalPalette.current
    val spec = LocalSpec.current
    Column(
        modifier
            .fillMaxWidth()
            .bentoSurface(shape = catCardShape())
            .bentoEnter(0)
            .padding(spec.cardPadding.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(6.dp),
    ) {
        Icon(icon, contentDescription = null, modifier = Modifier.size(34.dp), tint = p.text3)
        Spacer(Modifier.height(6.dp))
        Text(text, fontSize = 15.sp, color = p.text, fontWeight = FontWeight.Medium, textAlign = TextAlign.Center)
        hint?.let { Text(it, fontSize = 13.sp, color = p.text3, textAlign = TextAlign.Center) }
        action?.invoke()
    }
}
