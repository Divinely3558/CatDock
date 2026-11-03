package com.catdock.app.ui.components

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.animateColorAsState
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.slideInVertically
import androidx.compose.animation.slideOutVertically
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.interaction.collectIsPressedAsState
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Check
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Text
import androidx.compose.material3.ripple
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.scale
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Shape
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.graphics.lerp
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.catdock.app.ui.theme.LocalPalette
import com.catdock.app.ui.theme.LocalSpec
import com.catdock.app.ui.theme.catBadgeShape
import com.catdock.app.ui.theme.catCardShape
import com.catdock.app.ui.theme.catControlShape
import kotlinx.coroutines.delay

/**
 * 基础组件集：卡片 / 按钮 / 徽章 / 输入 / 进度 / 开关 / 状态灯 / 空态 / 提示条。
 * 一律从 LocalPalette + LocalSpec 取色取形，页面不写死色值与圆角；
 * 玻璃感、微光、按压微缩都走 bentoSurface / bentoPress，保证全站反馈一致。
 */

// ---------- 按压反馈 ----------

/**
 * 轻量按压层：给开关、标签这类非卡片可点件用。
 * 默认不加水波纹（避免小控件泛一大片灰圈），需要系统反馈时传 ripple = true。
 */
@Composable
fun Modifier.catTap(
    onClick: () -> Unit,
    enabled: Boolean = true,
    tint: Color = LocalPalette.current.ghostHover,
    shape: Shape = catControlShape(),
    ripple: Boolean = false,
): Modifier {
    val interaction = remember { MutableInteractionSource() }
    val pressed by interaction.collectIsPressedAsState()
    val overlay by animateColorAsState(
        if (enabled && pressed && !ripple) tint else Color.Transparent,
        animationSpec = tween(150),
        label = "catTap",
    )
    return this
        .background(overlay, shape)
        .clickable(
            interactionSource = interaction,
            indication = if (ripple) ripple() else null,
            enabled = enabled,
            onClick = onClick,
        )
}

// ---------- 卡片 ----------

/** 玻璃卡片面：12dp 圆角 + 半透基底 + 上沿反光 + 软阴影/边缘微光 */
@Composable
fun Modifier.catCard(
    selected: Boolean = false,
    onClick: (() -> Unit)? = null,
): Modifier =
    if (onClick != null) {
        bentoPress(onClick = onClick, emphasis = selected, shape = catCardShape())
    } else {
        bentoSurface(shape = catCardShape(), emphasis = selected)
    }

@Composable
fun CatCard(
    modifier: Modifier = Modifier,
    selected: Boolean = false,
    contentPadding: Dp? = null,
    verticalArrangement: Arrangement.Vertical = Arrangement.spacedBy(10.dp),
    enterIndex: Int? = null,
    onClick: (() -> Unit)? = null,
    content: @Composable ColumnScope.() -> Unit,
) {
    val spec = LocalSpec.current
    val pad = contentPadding ?: spec.cardPadding.dp
    Column(
        modifier = modifier
            .catCard(selected = selected, onClick = onClick)
            .padding(pad),
        verticalArrangement = verticalArrangement,
        content = {
            // 标题区块顶部留白 8dp：与说明、标签之间用留白分层，不画分割线
            Spacer(Modifier.height(2.dp))
            content()
        },
    )
}

// ---------- 按钮 ----------

enum class CatButtonVariant { PRIMARY, GHOST, DANGER }

/**
 * 玻璃拟态按钮：
 *   PRIMARY 主色磨砂底 + 细描边；亮色用炭黑描边且关闭发光通道，暗色用同色鎏金描边并打开外发光
 *   GHOST   半透玻璃底 + 描边 + 正文色文字
 *   DANGER  红底，用于删除 / 全员下线
 * 按下：微缩 + 水波纹 + 暗色光晕短暂提亮。
 */
@Composable
fun CatButton(
    text: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    variant: CatButtonVariant = CatButtonVariant.PRIMARY,
    enabled: Boolean = true,
    icon: androidx.compose.ui.graphics.vector.ImageVector? = null,
    small: Boolean = false,
) {
    val p = LocalPalette.current
    val spec = LocalSpec.current
    val shape = catControlShape()
    val interaction = remember { MutableInteractionSource() }
    val pressed by interaction.collectIsPressedAsState()
    val scale by animateFloatAsState(
        if (pressed && enabled) spec.pressScale else 1f,
        tween(150),
        label = "btnPress",
    )

    // 只有主按钮铺实心色块；危险按钮用色槽底 + 红字红边，免得整屏多一块饱和色
    val solid = variant == CatButtonVariant.PRIMARY
    val baseColor = when (variant) {
        CatButtonVariant.PRIMARY -> p.primary
        CatButtonVariant.DANGER -> p.redSoft
        CatButtonVariant.GHOST -> p.glassCard
    }
    val fill by animateColorAsState(
        when {
            // 禁用主按钮换中性浅底：实心主色打折后是淡粉，白字直接糊住读不了
            !enabled && solid -> p.text.copy(alpha = 0.07f)
            !enabled -> baseColor.copy(alpha = baseColor.alpha * 0.55f)
            pressed && solid -> p.primaryHover.copy(alpha = 0.95f)
            pressed -> baseColor.copy(alpha = baseColor.alpha + 0.18f)
            else -> if (solid) baseColor.copy(alpha = 0.94f) else baseColor
        },
        tween(150),
        label = "btnFill",
    )
    val fg = when {
        !enabled && solid -> p.text3
        variant == CatButtonVariant.PRIMARY -> p.onPrimary
        variant == CatButtonVariant.DANGER -> p.red
        else -> if (enabled) p.text else p.text3
    }
    val lineColor = when {
        !enabled -> p.border
        variant == CatButtonVariant.PRIMARY -> p.buttonStroke
        variant == CatButtonVariant.DANGER -> p.red
        else -> p.border
    }
    val glowColor = if (variant == CatButtonVariant.DANGER) p.red.copy(alpha = 0.28f) else p.glow
    // 只有主/危险按钮走发光通道，次级按钮留中性投影，免得满屏光晕
    val glowing = variant != CatButtonVariant.GHOST
    // 亮色 buttonGlow=0（只有炭黑细描边），暗色打开；按下再短暂提亮
    val glow by animateFloatAsState(
        if (!enabled || !glowing) 0f
        else spec.buttonGlow * (spec.glowRadius + if (pressed) 6f else 2f),
        tween(150),
        label = "btnGlow",
    )
    val haloColor = if (glowing) lerp(p.shadow, glowColor, spec.buttonGlow) else p.shadow

    Box(
        modifier = modifier
            .scale(scale)
            // 阴影走 glassHalo 而非 shadow()：后者强制离屏合成，半透底会被挤出直角边
            .glassHalo((spec.elevation / 2f + glow).dp, haloColor, shape)
            .background(fill, shape)
            // 悬浮/常态表面高光：只在实心按钮上出现，玻璃按钮靠卡片层的反光
            .then(
                if (solid && enabled) {
                    Modifier.background(
                        Brush.verticalGradient(0f to Color.White.copy(alpha = 0.16f), 0.5f to Color.Transparent),
                        shape,
                    )
                } else {
                    Modifier
                },
            )
            .border(spec.buttonStroke.dp, lineColor.copy(alpha = if (solid) 0.85f else 1f), shape)
            .clickable(
                interactionSource = interaction,
                indication = ripple(),
                enabled = enabled,
                onClick = onClick,
            )
            // 主按钮铺满 48dp 触控热区；行内小按钮视觉收一档，靠行间距补足可点区域
            .heightIn(min = if (small) 40.dp else spec.minTouch.dp)
            .widthIn(min = spec.minTouch.dp)
            .padding(horizontal = if (small) 12.dp else 18.dp, vertical = if (small) 6.dp else 10.dp),
        contentAlignment = Alignment.Center,
    ) {
        Row(
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(6.dp),
        ) {
            icon?.let {
                Icon(it, contentDescription = null, modifier = Modifier.size(if (small) 15.dp else 17.dp), tint = fg)
            }
            Text(text, color = fg, fontSize = if (small) 13.sp else 14.sp, fontWeight = FontWeight.Medium)
        }
    }
}

// ---------- 徽章 ----------

enum class CatTone { PRIMARY, GREEN, AMBER, RED, BLUE, NEUTRAL }

@Composable
fun CatTone.colors(): Pair<Color, Color> {
    val p = LocalPalette.current
    return when (this) {
        CatTone.PRIMARY -> p.primary to p.primarySoft
        CatTone.GREEN -> p.green to p.greenSoft
        CatTone.AMBER -> p.amber to p.amberSoft
        CatTone.RED -> p.red to p.redSoft
        CatTone.BLUE -> p.blue to p.blueSoft
        CatTone.NEUTRAL -> p.text2 to p.border
    }
}

/** 玻璃胶囊徽章：soft 底 + 同色描边 + 同色字 */
@Composable
fun CatBadge(text: String, tone: CatTone, modifier: Modifier = Modifier) {
    val (fg, bg) = tone.colors()
    Box(
        modifier = modifier
            .background(bg, catBadgeShape())
            .border(1.dp, fg.copy(alpha = 0.28f), catBadgeShape())
            .padding(horizontal = 10.dp, vertical = 3.dp),
    ) {
        Text(text, color = fg, fontSize = 12.sp, fontWeight = FontWeight.Medium, maxLines = 1)
    }
}

/**
 * 数字用等宽字形（tabular-nums）：进度、排队位、端口号轮询刷新时字宽不等会让整行左右跳。
 */
@Composable
fun catNumeric(size: Int, color: Color, weight: FontWeight = FontWeight.Normal): TextStyle =
    TextStyle(
        fontSize = size.sp,
        color = color,
        fontWeight = weight,
        fontFeatureSettings = "tnum",
        textAlign = TextAlign.End,
    )

// ---------- 输入框 ----------

@Composable
fun CatField(
    value: String,
    onValueChange: (String) -> Unit,
    label: String,
    modifier: Modifier = Modifier,
    singleLine: Boolean = true,
    minLines: Int = 1,
    helper: String? = null,
    error: String? = null,
    icon: androidx.compose.ui.graphics.vector.ImageVector? = null,
    keyboardOptions: KeyboardOptions = KeyboardOptions.Default,
    visualTransformation: androidx.compose.ui.text.input.VisualTransformation =
        androidx.compose.ui.text.input.VisualTransformation.None,
    trailingIcon: @Composable (() -> Unit)? = null,
    enabled: Boolean = true,
) {
    val p = LocalPalette.current
    Column(modifier = modifier) {
        Text(
            label,
            fontSize = 13.sp,
            color = p.text,
            fontWeight = FontWeight.Medium,
            modifier = Modifier.padding(bottom = 6.dp, start = 2.dp),
        )
        OutlinedTextField(
            value = value,
            onValueChange = onValueChange,
            singleLine = singleLine,
            minLines = minLines,
            enabled = enabled,
            isError = error != null,
            keyboardOptions = keyboardOptions,
            visualTransformation = visualTransformation,
            trailingIcon = trailingIcon,
            // 移动端输入统一 16sp：保证触控手感，也避免系统按小字号缩出行高
            textStyle = TextStyle(fontSize = 16.sp, color = p.text),
            shape = catControlShape(),
            colors = OutlinedTextFieldDefaults.colors(
                focusedTextColor = p.text,
                unfocusedTextColor = p.text,
                disabledTextColor = p.text3,
                focusedContainerColor = p.inputBg,
                unfocusedContainerColor = p.inputBg.copy(alpha = p.inputBg.alpha * 0.75f),
                disabledContainerColor = p.codeBg,
                errorContainerColor = p.inputBg,
                cursorColor = p.primary,
                focusedBorderColor = p.primary,
                unfocusedBorderColor = p.border,
                errorBorderColor = p.red,
                focusedLabelColor = p.primary,
            ),
            modifier = Modifier.fillMaxWidth().heightIn(min = 52.dp),
        )
        helper?.let {
            Text(it, fontSize = 12.sp, color = p.text3, modifier = Modifier.padding(top = 5.dp, start = 2.dp))
        }
        error?.let {
            Text(it, fontSize = 12.sp, color = p.red, modifier = Modifier.padding(top = 5.dp, start = 2.dp))
        }
    }
}

// ---------- 进度条 ----------

/** 半透玻璃轨道 + 主色进度条；宽度按 400ms 缓动过渡，不吃轮询的瞬跳值 */
@Composable
fun CatProgress(fraction: Float, modifier: Modifier = Modifier) {
    val p = LocalPalette.current
    val height = 8.dp
    val shape = CircleShape
    val width by animateFloatAsState(
        targetValue = if (fraction.isNaN()) 0f else fraction.coerceIn(0f, 1f),
        animationSpec = tween(400, easing = androidx.compose.animation.core.FastOutSlowInEasing),
        label = "progress",
    )
    Box(
        modifier = modifier
            .height(height)
            .fillMaxWidth()
            .background(p.border.copy(alpha = 0.55f), shape)
            .border(1.dp, p.border, shape),
    ) {
        Box(
            modifier = Modifier
                .fillMaxWidth(width)
                .height(height)
                .background(
                    Brush.horizontalGradient(listOf(p.primary.copy(alpha = 0.75f), p.primary)),
                    shape,
                ),
        )
    }
}

// ---------- 开关与选择 ----------

/** 玻璃开关：6dp 缓冲边距把触控热区抬到 48dp，滑块位移用弹簧感缓动 */
@Composable
fun CatSwitch(checked: Boolean, onCheckedChange: (Boolean) -> Unit, modifier: Modifier = Modifier) {
    val p = LocalPalette.current
    val spec = LocalSpec.current
    val pill = RoundedCornerShape(50)
    val shift by animateFloatAsState(if (checked) 20f else 0f, tween(220), label = "knob")
    val track by animateColorAsState(
        if (checked) p.primary.copy(alpha = 0.9f) else p.ghostHover,
        tween(150),
        label = "track",
    )
    Box(
        modifier = modifier
            .heightIn(min = spec.minTouch.dp)
            .widthIn(min = spec.minTouch.dp)
            .catTap(onClick = { onCheckedChange(!checked) }, shape = CircleShape, ripple = true)
            // 缓冲：可见轨道比热区小一圈，避免相邻行误触
            .padding(6.dp),
        contentAlignment = Alignment.CenterStart,
    ) {
        Box(
            Modifier
                .size(width = 46.dp, height = 26.dp)
                .background(track, pill)
                .border(spec.stroke.dp, p.border, pill),
            contentAlignment = Alignment.CenterStart,
        ) {
            Box(
                modifier = Modifier
                    .padding(3.dp)
                    .size(20.dp)
                    .graphicsLayer { translationX = shift.dp.toPx() }
                    .shadow(2.dp, CircleShape, ambientColor = p.shadow, spotColor = p.shadow)
                    .background(p.knob, CircleShape),
            )
        }
    }
}

@Composable
fun CatChoice(label: String, selected: Boolean, onClick: () -> Unit, modifier: Modifier = Modifier) {
    val p = LocalPalette.current
    Row(
        modifier = modifier
            .bentoPress(onClick = onClick, emphasis = selected, shape = catControlShape(), minHeight = 44.dp)
            .padding(horizontal = 14.dp, vertical = 10.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        if (selected) {
            Icon(Icons.Filled.Check, contentDescription = null, modifier = Modifier.size(16.dp), tint = p.primary)
        }
        Text(label, fontSize = 13.sp, color = if (selected) p.primary else p.text2)
    }
}

/** 顶栏状态灯：检测中=灰 / 正常=绿 / 异常=红 / 有新消息=蓝，外圈是同色微光 */
@Composable
fun HealthDot(state: HealthState, modifier: Modifier = Modifier) {
    val p = LocalPalette.current
    val color = when (state) {
        HealthState.CHECKING -> p.text3
        HealthState.OK -> p.green
        HealthState.BAD -> p.red
        HealthState.NEW_MESSAGE -> p.blue
    }
    Box(modifier = modifier.size(12.dp).background(color.copy(alpha = 0.22f), CircleShape),
        contentAlignment = Alignment.Center) {
        Box(
            Modifier
                .size(7.dp)
                .shadow(3.dp, CircleShape, clip = false, ambientColor = color.copy(alpha = 0.6f), spotColor = color.copy(alpha = 0.6f))
                .background(color, CircleShape),
        )
    }
}

enum class HealthState { CHECKING, OK, BAD, NEW_MESSAGE }

@Composable
fun catSectionTitle(): TextStyle = MaterialTheme.typography.titleMedium

/** 卡片小标题：层级靠字重，标题区顶部留白，用留白代替分割线 */
@Composable
fun CatCardTitle(text: String, modifier: Modifier = Modifier, trailing: @Composable (() -> Unit)? = null) {
    val p = LocalPalette.current
    Row(
        modifier = modifier.fillMaxWidth().padding(top = 4.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        Text(
            text,
            style = catSectionTitle(),
            color = p.text,
            fontWeight = FontWeight.SemiBold,
            modifier = Modifier.weight(1f),
        )
        trailing?.invoke()
    }
}

/** 破坏性操作「点一下先确认」：折叠态是普通按钮，展开后原地出确认气泡 */
@Composable
fun CatConfirmButton(
    text: String,
    confirmText: String,
    onConfirm: () -> Unit,
    modifier: Modifier = Modifier,
    icon: androidx.compose.ui.graphics.vector.ImageVector? = null,
    small: Boolean = false,
    detail: String? = null,
) {
    val p = LocalPalette.current
    var pending by remember { mutableStateOf(false) }
    if (!pending) {
        CatButton(
            text = text,
            onClick = { pending = true },
            modifier = modifier,
            variant = CatButtonVariant.DANGER,
            icon = icon,
            small = small,
        )
    } else {
        // 二次确认走居中玻璃弹窗：内联气泡在标题行里会把同行按钮挤成一团
        BentoDialog(onDismiss = { pending = false }) {
            BentoDialogTitle(confirmText)
            if (detail != null) BentoDialogBody(detail)
            BentoDialogButtons(
                confirmText = "确认",
                onConfirm = {
                    pending = false
                    onConfirm()
                },
                dismissText = "取消",
                onDismiss = { pending = false },
                confirmVariant = CatButtonVariant.DANGER,
            )
        }
    }
}

// ---------- 空态 ----------

/** 空态走独立大 Bento 卡，不再是一行飘在页面中间的小字 */
@Composable
fun CatEmptyState(
    icon: androidx.compose.ui.graphics.vector.ImageVector,
    text: String,
    hint: String? = null,
    modifier: Modifier = Modifier,
) {
    BentoEmptyState(icon = icon, text = text, hint = hint, modifier = modifier)
}

// ---------- 提示条 ----------

/** 一条提示：error 走红边红字，模型层直接发这个类型 */
data class CatToast(val text: String, val error: Boolean = false)

/** 系统 Toast 吃不了配色（暗色弹一块亮胶囊）、后台还会限流丢消息，改自绘 */
class CatToastState {
    var message by mutableStateOf<CatToast?>(null)
        private set
    var nonce by mutableStateOf(0L)
        private set

    fun show(toast: CatToast) {
        message = toast
        nonce = System.nanoTime()
    }

    fun dismiss() {
        message = null
    }
}

@Composable
fun rememberCatToastState(): CatToastState = remember { CatToastState() }

/** 玻璃提示条：贴底部安全区，离手势导航栏 ≥12dp，不贴边、不遮关键按钮 */
@Composable
fun CatToastHost(state: CatToastState, modifier: Modifier = Modifier) {
    val current = state.message
    val nonce = state.nonce
    var last by remember { mutableStateOf(CatToast("", false)) }
    // 退场动画期间 current 已置空，留住最后一条文案，避免气泡先清空再消失
    if (current != null) last = current

    LaunchedEffect(nonce) {
        if (current != null) {
            delay(if (current.error) 4200L else 2600L)
            if (state.nonce == nonce) state.dismiss()
        }
    }

    Box(
        modifier = modifier
            .fillMaxSize()
            .navigationBarsPadding()
            .padding(horizontal = 28.dp, vertical = 12.dp),
        contentAlignment = Alignment.BottomCenter,
    ) {
        AnimatedVisibility(
            visible = current != null,
            enter = fadeIn(tween(220)) + slideInVertically(tween(220)) { it / 2 },
            exit = fadeOut(tween(180)) + slideOutVertically(tween(180)) { it / 2 },
        ) {
            val p = LocalPalette.current
            Box(
                modifier = Modifier
                    .bentoSurface(shape = catCardShape(), strong = true)
                    .padding(horizontal = 18.dp, vertical = 11.dp),
            ) {
                Text(
                    last.text,
                    fontSize = 13.sp,
                    color = if (last.error) p.red else p.text,
                    textAlign = TextAlign.Center,
                    maxLines = 4,
                )
            }
        }
    }
}
