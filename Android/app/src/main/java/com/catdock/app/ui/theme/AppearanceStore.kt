package com.catdock.app.ui.theme

import android.content.Context
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.map

private val Context.appearanceStore by preferencesDataStore(name = "catdock_appearance")

/** 外观偏好：仅亮暗模式，本地持久化（对应网页 data-mode） */
data class Appearance(
    val mode: ModePreference = ModePreference.SYSTEM,
)

class AppearanceStore(private val context: Context) {

    private object Keys {
        val MODE = stringPreferencesKey("mode")
    }

    val appearance: Flow<Appearance> = context.appearanceStore.data.map { p ->
        Appearance(
            mode = ModePreference.entries.firstOrNull { it.name == p[Keys.MODE] }
                ?: ModePreference.SYSTEM,
        )
    }

    suspend fun current(): Appearance = appearance.first()

    suspend fun setMode(mode: ModePreference) {
        context.appearanceStore.edit { it[Keys.MODE] = mode.name }
    }
}
