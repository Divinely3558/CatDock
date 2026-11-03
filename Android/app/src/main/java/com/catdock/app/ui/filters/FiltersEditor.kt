package com.catdock.app.ui.filters

import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.catdock.app.data.ApiException
import com.catdock.app.data.AppRepository
import com.catdock.app.data.AuthExpiredException
import com.catdock.app.data.DedupRule
import com.catdock.app.data.FilterConfig
import com.catdock.app.ui.ScreenModel
import com.catdock.app.ui.components.BentoSkeleton
import com.catdock.app.ui.components.CatBadge
import com.catdock.app.ui.components.CatButton
import com.catdock.app.ui.components.CatButtonVariant
import com.catdock.app.ui.components.CatCard
import com.catdock.app.ui.components.CatConfirmButton
import com.catdock.app.ui.components.CatField
import com.catdock.app.ui.components.CatSwitch
import com.catdock.app.ui.components.CatTone
import com.catdock.app.ui.components.TrackBentoScroll
import com.catdock.app.ui.components.bentoEnter
import com.catdock.app.ui.components.catTap
import com.catdock.app.ui.rememberScreenModel
import com.catdock.app.ui.theme.LocalPalette
import com.catdock.app.ui.theme.LocalSpec
import com.catdock.app.ui.theme.catBadgeShape
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.launch

/** 过滤规则模型：加载 + 保存（管理员走 /admin/filters，下载用户走 /filters） */
class FiltersModel(private val repo: AppRepository, private val isAdmin: Boolean) : ScreenModel() {

    val config = MutableStateFlow(FilterConfig())
    val loading = MutableStateFlow(true)
    val error = MutableStateFlow<String?>(null)

    init {
        scope.launch {
            try {
                config.value = repo.filters(isAdmin)
            } catch (e: AuthExpiredException) {
                error.value = null
            } catch (e: Exception) {
                error.value = e.message ?: "加载失败"
            } finally {
                loading.value = false
            }
        }
    }

    fun save(onDone: (String) -> Unit, onExpired: (String) -> Unit) {
        error.value = null
        scope.launch {
            try {
                onDone(repo.saveFilters(config.value, isAdmin))
            } catch (e: AuthExpiredException) {
                onExpired(e.message ?: "登录已过期")
            } catch (e: ApiException) {
                error.value = e.message ?: "保存失败"
            } catch (e: Exception) {
                error.value = "网络错误：${e.message ?: ""}"
            }
        }
    }
}

/**
 * 与网页 `.filter-editor` 同构的三段编辑器：
 * 拦截广告关键字 / 文件名过滤 / 文件名去重（按顺序应用正则替换）。
 */
@Composable
fun FiltersEditor(
    isAdmin: Boolean,
    repository: AppRepository,
    onAuthExpired: (String) -> Unit,
) {
    val p = LocalPalette.current
    val spec = LocalSpec.current
    val vm = rememberScreenModel(isAdmin) { FiltersModel(repository, isAdmin) }
    val cfg by vm.config.collectAsState()
    val loading by vm.loading.collectAsState()
    val error by vm.error.collectAsState()
    var notice by remember { mutableStateOf<String?>(null) }

    LaunchedEffect(cfg) { notice = null }

    val listState = rememberLazyListState()
    TrackBentoScroll(listState)

    LazyColumn(
        state = listState,
        modifier = Modifier.fillMaxSize(),
        // 左右不留内缩：外层页面已经给了 spec.screenPadding，这里再缩一次会让卡片贴不进栅格宽度
        contentPadding = PaddingValues(top = 4.dp, bottom = spec.bottomInset.dp + 20.dp),
        verticalArrangement = Arrangement.spacedBy(spec.gap.dp),
    ) {
        if (loading) {
            item { BentoSkeleton(rows = 3, cellHeight = 120.dp) }
            return@LazyColumn
        }

        item {
            ChipSection(
                enterIndex = 0,
                title = "拦截广告关键字",
                hint = "链接或文件名含关键字即拦截",
                enabled = cfg.keywords.enabled,
                items = cfg.keywords.list,
                onToggle = { vm.config.value = cfg.copy(keywords = cfg.keywords.copy(enabled = it)) },
                onAdd = { added ->
                    val merged = (cfg.keywords.list + added).distinct()
                    vm.config.value = cfg.copy(keywords = cfg.keywords.copy(list = merged))
                },
                onRemove = { kw ->
                    vm.config.value = cfg.copy(keywords = cfg.keywords.copy(list = cfg.keywords.list - kw))
                },
            )
        }

        item {
            ChipSection(
                enterIndex = 1,
                title = "文件名过滤",
                hint = "从文件名中删除这些关键字",
                enabled = cfg.filenameFilter.enabled,
                items = cfg.filenameFilter.list,
                onToggle = { vm.config.value = cfg.copy(filenameFilter = cfg.filenameFilter.copy(enabled = it)) },
                onAdd = { added ->
                    val merged = (cfg.filenameFilter.list + added).distinct()
                    vm.config.value = cfg.copy(filenameFilter = cfg.filenameFilter.copy(list = merged))
                },
                onRemove = { kw ->
                    vm.config.value =
                        cfg.copy(filenameFilter = cfg.filenameFilter.copy(list = cfg.filenameFilter.list - kw))
                },
            )
        }

        item {
            CatCard(
                Modifier
                    .fillMaxWidth()
                    .bentoEnter(2),
                verticalArrangement = Arrangement.spacedBy(10.dp),
            ) {
                SectionHead(
                    "文件名去重",
                    "按顺序应用正则替换",
                    cfg.filenameDedup.enabled,
                    cfg.filenameDedup.rules.size,
                ) { vm.config.value = cfg.copy(filenameDedup = cfg.filenameDedup.copy(enabled = it)) }

                cfg.filenameDedup.rules.forEachIndexed { index, rule ->
                    Row(
                        Modifier.fillMaxWidth(),
                        verticalAlignment = Alignment.Bottom,
                        horizontalArrangement = Arrangement.spacedBy(8.dp),
                    ) {
                        CatField(
                            rule.pattern,
                            { v -> setRule(vm, cfg, index) { it.copy(pattern = v) } },
                            "查找（正则）",
                            modifier = Modifier.weight(1f),
                        )
                        CatField(
                            rule.replacement,
                            { v -> setRule(vm, cfg, index) { it.copy(replacement = v) } },
                            "替换为",
                            modifier = Modifier.weight(1f),
                        )
                        CatConfirmButton(
                            text = "删",
                            confirmText = "删除该规则？",
                            detail = "只是从编辑中的列表里移除这条规则，点保存前不会写到服务器。",
                            onConfirm = {
                                vm.config.value = cfg.copy(
                                    filenameDedup = cfg.filenameDedup.copy(
                                        rules = cfg.filenameDedup.rules.toMutableList().also { it.removeAt(index) },
                                    ),
                                )
                            },
                            small = true,
                        )
                    }
                }
                CatButton(
                    "添加规则",
                    {
                        vm.config.value = cfg.copy(
                            filenameDedup = cfg.filenameDedup.copy(rules = cfg.filenameDedup.rules + DedupRule()),
                        )
                    },
                    variant = CatButtonVariant.GHOST,
                    icon = Icons.Filled.Add,
                    small = true,
                )
            }
        }

        item {
            Column(Modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(spec.gap.dp)) {
                error?.let { Text(it, fontSize = 12.sp, color = p.red) }
                notice?.let { Text(it, fontSize = 12.sp, color = p.green) }
            }
        }

        // 主操作固定在底部优先操作区，满宽单手可及
        item {
            CatButton(
                "保存过滤规则",
                onClick = { vm.save(onDone = { notice = it }, onExpired = onAuthExpired) },
                modifier = Modifier.fillMaxWidth(),
            )
        }
    }
}

private fun setRule(
    vm: FiltersModel,
    cfg: FilterConfig,
    index: Int,
    edit: (DedupRule) -> DedupRule,
) {
    val rules = cfg.filenameDedup.rules.toMutableList()
    rules[index] = edit(rules[index])
    vm.config.value = cfg.copy(filenameDedup = cfg.filenameDedup.copy(rules = rules))
}

@Composable
private fun SectionHead(
    title: String,
    hint: String,
    enabled: Boolean,
    count: Int,
    onToggle: (Boolean) -> Unit,
) {
    val p = LocalPalette.current
    Row(
        Modifier.fillMaxWidth(),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        CatSwitch(enabled, onToggle)
        Column(Modifier.weight(1f)) {
            Text(title, fontSize = 15.sp, color = p.text, fontWeight = FontWeight.Medium)
            Text(hint, fontSize = 12.sp, color = p.text3)
        }
        CatBadge("$count", if (enabled) CatTone.GREEN else CatTone.NEUTRAL)
    }
}

@Composable
private fun ChipSection(
    enterIndex: Int,
    title: String,
    hint: String,
    enabled: Boolean,
    items: List<String>,
    onToggle: (Boolean) -> Unit,
    onAdd: (List<String>) -> Unit,
    onRemove: (String) -> Unit,
) {
    val p = LocalPalette.current
    val spec = LocalSpec.current
    var input by remember { mutableStateOf("") }

    CatCard(
        Modifier
            .fillMaxWidth()
            .bentoEnter(enterIndex),
    ) {
        SectionHead(title, hint, enabled, items.size, onToggle)

        if (items.isNotEmpty()) {
            Row(
                Modifier
                    .fillMaxWidth()
                    .heightIn(min = spec.minTouch.dp)
                    .horizontalScroll(rememberScrollState()),
                horizontalArrangement = Arrangement.spacedBy(8.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                items.forEach { kw ->
                    // 点标签即删除：整枚标签都是命中区，玻璃底给足对比
                    CatBadge(
                        text = kw,
                        tone = if (enabled) CatTone.PRIMARY else CatTone.NEUTRAL,
                        modifier = Modifier.catTap(onClick = { onRemove(kw) }, shape = catBadgeShape()),
                    )
                }
            }
            Text("点标签可删除", fontSize = 12.sp, color = p.text3)
        }

        Row(
            Modifier.fillMaxWidth(),
            verticalAlignment = Alignment.Bottom,
            horizontalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            CatField(
                input,
                { input = it },
                "输入关键字，逗号分隔可批量添加",
                modifier = Modifier.weight(1f),
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Text),
            )
            CatButton(
                "添加",
                onClick = {
                    onAdd(input.split(',', '，').map { it.trim() }.filter { it.isNotEmpty() })
                    input = ""
                },
                variant = CatButtonVariant.GHOST,
                icon = Icons.Filled.Add,
                small = true,
                enabled = input.isNotBlank(),
            )
        }
    }
}
