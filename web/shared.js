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

/* ===== 共享工具区：window.CD =====
 * 三页（login/user/admin）原先各自重复定义的 HTML 转义、提示条、Toast、
 * 通用弹层、API 封装与过滤规则编辑器统一收敛到 window.CD，供页面脚本调用：
 *   CD.esc / CD.showAlert / CD.hideAlert / CD.toast /
 *   CD.openModal / CD.closeModal / CD.apiGet / CD.apiPost /
 *   CD.onUnauthorized（可选，页面赋值为凭证失效回调，如跳转登录页）/
 *   CD.initFilterEditor({ basePath: "filters" | "admin/filters" })
 * API 令牌统一直读 localStorage 的 catdock_token。
 */
(function () {
  "use strict";

  var TOKEN_KEY = "catdock_token";
  // 与各页原 API 封装相同的网络错误文案
  var NET_ERROR =
    "无法连接服务器：连接被拒绝。可能 IP 已被封禁（服务器执行 banip show 查看并 banip del 解封），或地址前缀有误";
  // 页面均由服务端托管在 /{prefix}/xxx.html，去掉末段即得 API 前缀
  var BASE = location.pathname.replace(/[^/]*$/, "");

  function $(id) {
    return document.getElementById(id);
  }

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return {
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&#39;",
      }[c];
    });
  }

  function showAlert(el, msg, ok) {
    el.textContent = msg;
    el.className = "alert show " + (ok ? "alert-success" : "alert-error");
  }
  function hideAlert(el) {
    el.className = "alert";
  }

  // ---------- Toast（user/admin 共用 #toast 元素） ----------
  var toastTimer = null;
  function toast(msg, isErr) {
    var el = $("toast");
    el.textContent = msg;
    el.className = "toast show" + (isErr ? " err" : "");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () {
      el.className = "toast" + (isErr ? " err" : "");
    }, 2600);
  }

  // ---------- 通用弹层（以 admin 版本为超集：支持 titleExtra 与 checkbox 字段） ----------
  function openModal(spec) {
    $("modalTitle").textContent = spec.title || "提示";
    // 标题右侧附加内容（如复选框），可选；user 页无此元素则跳过
    var extraEl = $("modalTitleExtra");
    if (extraEl) extraEl.innerHTML = spec.titleExtra || "";
    $("modalMsg").innerHTML = spec.msg || "";
    var form = $("modalForm");
    form.innerHTML = "";
    (spec.fields || []).forEach(function (f) {
      var lab = document.createElement("label");
      lab.className = "field";
      if (f.type === "checkbox") {
        // 复选框：勾选框与文字同行排列
        lab.style.display = "flex";
        lab.style.alignItems = "center";
        lab.style.gap = "8px";
        var inp = document.createElement("input");
        inp.type = "checkbox";
        inp.id = "mf_" + f.id;
        inp.style.width = "auto";
        inp.style.cursor = "pointer";
        if (f.checked) inp.checked = true;
        var cspan = document.createElement("span");
        cspan.textContent = f.label;
        cspan.style.marginBottom = "0";
        lab.appendChild(inp);
        lab.appendChild(cspan);
      } else {
        var span = document.createElement("span");
        span.textContent = f.label;
        if (f.required) span.innerHTML += '<span class="req">*</span>';
        var input = document.createElement("input");
        input.type = f.type || "text";
        input.id = "mf_" + f.id;
        input.placeholder = f.placeholder || "";
        // 统一 autocomplete="off"：避免移动端唤起密码管理器/自动填充条
        input.autocomplete = "off";
        lab.appendChild(span);
        lab.appendChild(input);
      }
      form.appendChild(lab);
    });
    var okBtn = $("modalOk");
    okBtn.textContent = spec.okText || "确定";
    okBtn.className = "btn " + (spec.danger ? "btn-danger" : "btn-primary");
    $("mask").classList.add("show");
    setTimeout(function () {
      var first = form.querySelector("input");
      if (first) first.focus();
    }, 50);
    okBtn.onclick = function () {
      var values = {};
      for (var i = 0; i < (spec.fields || []).length; i++) {
        var f = spec.fields[i];
        var inp = $("mf_" + f.id);
        values[f.id] =
          f.type === "checkbox" ? inp.checked : inp.value.trim();
      }
      if (spec.onOk && spec.onOk(values) === false) return;
      closeModal();
    };
    $("modalCancel").onclick = closeModal;
  }
  function closeModal() {
    $("mask").classList.remove("show");
  }

  // ---------- API 封装（令牌直读 localStorage，403 交给 CD.onUnauthorized） ----------
  function handleResp(resp) {
    return resp
      .json()
      .catch(function () {
        throw new Error("服务器响应格式错误");
      })
      .then(function (data) {
        if (resp.status === 403) {
          // 凭证失效：调用页面注册的回调（如清理凭证并跳转登录页）
          if (typeof CD.onUnauthorized === "function") CD.onUnauthorized();
          throw new Error(data.message || "认证失败");
        }
        if (!resp.ok || data.success === false) {
          throw new Error(
            data.message || "请求失败 (HTTP " + resp.status + ")",
          );
        }
        return data;
      });
  }

  function authHeaders() {
    var h = {};
    var token = localStorage.getItem(TOKEN_KEY);
    if (token) h["Authorization"] = "Bearer " + token;
    return h;
  }

  function apiGet(path) {
    return fetch(BASE + path, { method: "GET", headers: authHeaders() })
      .catch(function () {
        throw new Error(NET_ERROR);
      })
      .then(handleResp);
  }

  function apiPost(path, body) {
    var headers = Object.assign(
      { "Content-Type": "application/json" },
      authHeaders(),
    );
    return fetch(BASE + path, {
      method: "POST",
      headers: headers,
      body: JSON.stringify(body),
    })
      .catch(function () {
        throw new Error(NET_ERROR);
      })
      .then(handleResp);
  }

  // ---------- 过滤规则编辑器（user「我的过滤规则」/ admin「过滤规则模板」共用） ----------
  // options.basePath：加载/保存的 API 路径，user 传 "filters"，admin 传 "admin/filters"
  function initFilterEditor(options) {
    var basePath = options && options.basePath ? options.basePath : "filters";

    var filterState = {
      keywords: { enabled: false, list: [] },
      filename_filter: { enabled: false, list: [] },
      filename_dedup: { enabled: false, rules: [] },
    };

    function renderChips(key, listId, inputId) {
      var wrap = $(listId);
      wrap.innerHTML = "";
      var list = filterState[key].list;
      if (!list.length) {
        var tip = document.createElement("span");
        tip.className = "empty-tip";
        tip.textContent = "暂无关键字";
        wrap.appendChild(tip);
        return;
      }
      list.forEach(function (item, idx) {
        var chip = document.createElement("span");
        chip.className = "chip";
        var text = document.createElement("span");
        text.textContent = item;
        var del = document.createElement("button");
        del.type = "button";
        del.textContent = "✕";
        del.title = "删除";
        del.onclick = function () {
          filterState[key].list.splice(idx, 1);
          renderChips(key, listId, inputId);
        };
        chip.appendChild(text);
        chip.appendChild(del);
        wrap.appendChild(chip);
      });
    }

    function addKeywords(key, listId, inputId) {
      var raw = $(inputId).value.trim();
      if (!raw) return;
      raw
        .split(/[,，\n]/)
        .map(function (s) {
          return s.trim();
        })
        .filter(function (s) {
          return s;
        })
        .forEach(function (s) {
          if (filterState[key].list.indexOf(s) === -1)
            filterState[key].list.push(s);
        });
      $(inputId).value = "";
      renderChips(key, listId, inputId);
    }

    function renderDdRules() {
      var wrap = $("ddRules");
      wrap.innerHTML = "";
      var rules = filterState.filename_dedup.rules;
      rules.forEach(function (rule, idx) {
        var row = document.createElement("div");
        row.className = "dd-rule";
        var p = document.createElement("input");
        p.type = "text";
        p.placeholder = "正则 pattern";
        p.value = rule.pattern || "";
        p.oninput = function () {
          rules[idx].pattern = p.value;
        };
        var arrow = document.createElement("span");
        arrow.className = "dd-arrow";
        arrow.textContent = "→";
        var r = document.createElement("input");
        r.type = "text";
        r.placeholder = "替换为";
        r.value = rule.replacement || "";
        r.oninput = function () {
          rules[idx].replacement = r.value;
        };
        var del = document.createElement("button");
        del.type = "button";
        del.className = "btn";
        del.textContent = "✕";
        del.title = "删除规则";
        del.onclick = function () {
          rules.splice(idx, 1);
          renderDdRules();
        };
        row.appendChild(p);
        row.appendChild(arrow);
        row.appendChild(r);
        row.appendChild(del);
        wrap.appendChild(row);
      });
    }

    function loadFilters() {
      apiGet(basePath)
        .then(function (data) {
          filterState = {
            keywords: {
              enabled: !!data.data.keywords.enabled,
              list: data.data.keywords.list || [],
            },
            filename_filter: {
              enabled: !!data.data.filename_filter.enabled,
              list: data.data.filename_filter.list || [],
            },
            filename_dedup: {
              enabled: !!data.data.filename_dedup.enabled,
              rules: data.data.filename_dedup.rules || [],
            },
          };
          $("kwEnabled").checked = filterState.keywords.enabled;
          $("ffEnabled").checked = filterState.filename_filter.enabled;
          $("ddEnabled").checked = filterState.filename_dedup.enabled;
          renderChips("keywords", "kwChips", "kwInput");
          renderChips("filename_filter", "ffChips", "ffInput");
          renderDdRules();
          hideAlert($("filterAlert"));
        })
        .catch(function (e) {
          showAlert($("filterAlert"), e.message, false);
        });
    }

    $("menuFilters").addEventListener("click", function () {
      $("userMenu").classList.remove("show");
      $("filterMask").classList.add("show");
      loadFilters();
    });
    // 点击弹窗外部不再关闭，仅可通过「取消」按钮关闭
    $("filterCancel").addEventListener("click", function () {
      $("filterMask").classList.remove("show");
      hideAlert($("filterAlert"));
    });
    $("kwAdd").addEventListener("click", function () {
      addKeywords("keywords", "kwChips", "kwInput");
    });
    $("kwInput").addEventListener("keydown", function (e) {
      if (e.key === "Enter") {
        e.preventDefault();
        addKeywords("keywords", "kwChips", "kwInput");
      }
    });
    $("ffAdd").addEventListener("click", function () {
      addKeywords("filename_filter", "ffChips", "ffInput");
    });
    $("ffInput").addEventListener("keydown", function (e) {
      if (e.key === "Enter") {
        e.preventDefault();
        addKeywords("filename_filter", "ffChips", "ffInput");
      }
    });
    $("ddAdd").addEventListener("click", function () {
      filterState.filename_dedup.rules.push({
        pattern: "",
        replacement: "",
      });
      renderDdRules();
    });
    $("filterSave").addEventListener("click", function () {
      filterState.keywords.enabled = $("kwEnabled").checked;
      filterState.filename_filter.enabled = $("ffEnabled").checked;
      filterState.filename_dedup.enabled = $("ddEnabled").checked;
      // 前端正则预校验，避免提交后被后端拒绝
      try {
        filterState.filename_dedup.rules.forEach(function (rule) {
          if ((rule.pattern || "").trim()) new RegExp(rule.pattern.trim());
        });
      } catch (err) {
        showAlert($("filterAlert"), "正则表达式不合法: " + err.message, false);
        return;
      }
      var btn = $("filterSave");
      btn.disabled = true;
      apiPost(basePath, filterState)
        .then(function (data) {
          showAlert($("filterAlert"), data.message || "已保存", true);
          setTimeout(function () {
            $("filterMask").classList.remove("show");
          }, 1200);
        })
        .catch(function (e) {
          showAlert($("filterAlert"), e.message, false);
        })
        .finally(function () {
          btn.disabled = false;
        });
    });
  }

  window.CD = {
    esc: esc,
    showAlert: showAlert,
    hideAlert: hideAlert,
    toast: toast,
    openModal: openModal,
    closeModal: closeModal,
    apiGet: apiGet,
    apiPost: apiPost,
    initFilterEditor: initFilterEditor,
    onUnauthorized: null,
  };
})();
