package com.catdock.app

import android.app.Application
import com.catdock.app.data.ApiClient
import com.catdock.app.data.AppRepository
import com.catdock.app.data.SessionStore
import com.catdock.app.ui.theme.AppearanceStore

/** 应用级依赖容器（轻量手写，避免引入 HILT/Koin） */
class CatdockApp : Application() {

    lateinit var sessionStore: SessionStore
        private set
    lateinit var repository: AppRepository
        private set
    lateinit var appearanceStore: AppearanceStore
        private set

    override fun onCreate() {
        super.onCreate()
        CrashHandler.install(this)
        sessionStore = SessionStore(this)
        repository = AppRepository(sessionStore, ApiClient(sessionStore))
        appearanceStore = AppearanceStore(this)
    }
}
