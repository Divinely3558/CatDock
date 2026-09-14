/* ===== CatDock 共享前端脚本（login/user/admin 三端共用，
   由 core/webui.py 注入到各页面脚本的占位符处） =====
 *
 * 主题规则：
 *  - 色板（墨绿/暖橙/紫罗兰）：每个浏览器会话首次访问时随机选定，
 *    存 sessionStorage，同一会话内三页保持同色；关闭浏览器后重新随机。
 *    手动点「主题色」在三色板间循环切换，仅当次会话有效。
 *  - 亮/暗色：默认亮色；手动切换后写入 localStorage 长期记忆。
 *
 * 按钮约定：带 data-theme-palette / data-theme-mode 属性的元素即主题按钮；
 * 顶栏外观菜单（#brandBtn/#brandMenu）与账号菜单（#userChip/#userMenu）
 * 的展开/互斥/点外关闭也由本脚本统一接管。
 */
(function () {
  "use strict";

  var SESSION_PALETTE_KEY = "catdock_palette_session";
  var MODE_KEY = "catdock_mode";

  var PALETTES = [
    { id: "default", icon: "🟢", name: "墨绿" },
    { id: "orange", icon: "🟠", name: "暖橙" },
    { id: "violet", icon: "🟣", name: "紫罗兰" },
  ];

  function isValidPalette(id) {
    for (var i = 0; i < PALETTES.length; i++) {
      if (PALETTES[i].id === id) return true;
    }
    return false;
  }

  function randomPaletteId() {
    return PALETTES[Math.floor(Math.random() * PALETTES.length)].id;
  }

  /* 当前会话色板：首次读取时随机并固定到 sessionStorage */
  function getPalette() {
    var id = sessionStorage.getItem(SESSION_PALETTE_KEY);
    if (!isValidPalette(id)) {
      id = randomPaletteId();
      sessionStorage.setItem(SESSION_PALETTE_KEY, id);
    }
    return id;
  }

  function paletteMeta(id) {
    for (var i = 0; i < PALETTES.length; i++) {
      if (PALETTES[i].id === id) return PALETTES[i];
    }
    return PALETTES[0];
  }

  /* 亮暗模式：默认亮色，手动切换后记忆 */
  function getMode() {
    return localStorage.getItem(MODE_KEY) === "dark" ? "dark" : "light";
  }

  function setButtonIcon(btn, emoji) {
    var icon = btn.querySelector(".btn-icon");
    if (icon) icon.textContent = emoji;
    else btn.textContent = emoji;
  }

  function applyPalette() {
    var p = paletteMeta(getPalette());
    document.documentElement.setAttribute("data-palette", p.id);
    var btns = document.querySelectorAll("[data-theme-palette]");
    for (var i = 0; i < btns.length; i++) {
      setButtonIcon(btns[i], p.icon);
      btns[i].title = "主题色：" + p.name + "（点击切换）";
    }
  }

  function applyMode() {
    var m = getMode();
    document.documentElement.setAttribute("data-mode", m);
    var btns = document.querySelectorAll("[data-theme-mode]");
    for (var i = 0; i < btns.length; i++) {
      setButtonIcon(btns[i], m === "dark" ? "☀️" : "🌙");
      btns[i].title = m === "dark" ? "切换为亮色" : "切换为暗色";
    }
  }

  function togglePalette() {
    var ids = [];
    for (var i = 0; i < PALETTES.length; i++) ids.push(PALETTES[i].id);
    var idx = ids.indexOf(getPalette());
    var next = PALETTES[(idx + 1) % PALETTES.length];
    sessionStorage.setItem(SESSION_PALETTE_KEY, next.id);
    applyPalette();
  }

  function toggleMode() {
    localStorage.setItem(MODE_KEY, getMode() === "dark" ? "light" : "dark");
    applyMode();
  }

  /* 顶栏两个下拉菜单：各自开关、互斥、点击菜单外部关闭 */
  function initMenus() {
    var pairs = [
      { btnId: "brandBtn", menuId: "brandMenu" },
      { btnId: "userChip", menuId: "userMenu" },
    ];
    var resolved = [];
    pairs.forEach(function (pair) {
      var btn = document.getElementById(pair.btnId);
      var menu = document.getElementById(pair.menuId);
      if (!btn || !menu) return;
      resolved.push({ btn: btn, menu: menu });
      btn.addEventListener("click", function (ev) {
        ev.stopPropagation();
        resolved.forEach(function (other) {
          if (other.menu !== menu) other.menu.classList.remove("show");
        });
        menu.classList.toggle("show");
      });
    });
    if (resolved.length) {
      document.addEventListener("click", function () {
        resolved.forEach(function (p) {
          p.menu.classList.remove("show");
        });
      });
    }
  }

  function init() {
    // 刷新按钮图标/标题（head 阶段执行时按钮可能尚未解析，这里再来一次）
    applyPalette();
    applyMode();
    var paletteBtns = document.querySelectorAll("[data-theme-palette]");
    for (var i = 0; i < paletteBtns.length; i++) {
      paletteBtns[i].addEventListener("click", function (ev) {
        ev.stopPropagation();
        togglePalette();
      });
    }
    var modeBtns = document.querySelectorAll("[data-theme-mode]");
    for (var j = 0; j < modeBtns.length; j++) {
      modeBtns[j].addEventListener("click", function (ev) {
        ev.stopPropagation();
        toggleMode();
      });
    }
    initMenus();
  }

  /* 尽早把色板/亮暗写到 <html>，避免首屏先闪默认主题（FOUC） */
  applyPalette();
  applyMode();

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
