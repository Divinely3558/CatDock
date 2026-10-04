/* ===== CatDock 共享前端脚本（login/user/admin 三端共用，
   由 core/webui.py 注入到各页面脚本的占位符处） =====
 *
 * 主题规则：
 *  - 色板（墨绿/像素/科技/莫兰迪）：每个浏览器会话首次访问时随机选定，
 *    存 sessionStorage，同一会话内三页保持同色；关闭浏览器后重新随机。
 *    手动点「主题色」在四色板间循环切换，仅当次会话有效。
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

  /* 四主题 SVG 图标（只允许改大小，不允许改其他） */
  var SVG_DEFAULT = '<svg class="icon" viewBox="0 0 1024 1024" xmlns="http://www.w3.org/2000/svg"><path d="M170.666667 410.602667V127.893333c0-19.349333 24.106667-28.501333 37.184-14.122666l112.064 123.2a344.490667 344.490667 0 0 1 384.149333 0l112.085333-123.2C829.226667 99.392 853.333333 108.544 853.333333 127.893333v768.192H170.666667V410.602667z" fill="#FFFFFF"/><path d="M853.333333 128.106667V650.730667c-74.666667-21.333333-196.608-92.202667-266.666666-202.666667-28.906667-45.568-55.338667-108.8-74.666667-161.002667-19.328 52.224-45.76 115.434667-74.666667 161.002667-70.058667 110.464-192 181.333333-266.666666 202.666667V128.128c0-19.562667 24.106667-28.8 37.184-14.293333l112.064 124.522666a341.354667 341.354667 0 0 1 61.461333-33.173333c32.661333-13.546667 87.082667-13.866667 130.602667-13.418667 43.52-0.448 97.984-0.128 130.645333 13.397334 21.610667 8.96 42.197333 20.096 61.44 33.194666l112.085333-124.501333C829.226667 99.306667 853.333333 108.565333 853.333333 128.106667z" fill="#FBCA82"/><path d="M584.533333 187.818667l-15.808 96.64c-1.92 11.584 13.653333 17.28 19.669334 7.189333l49.706666-83.072-53.546666-20.757333z m-84.330666 98.56l-20.096-95.829334 57.429333 0.042667-16.384 95.381333c-2.005333 11.605333-18.56 11.904-20.949333 0.384z m-61.888 8.490666L384 213.418667l53.333333-21.333334 20.266667 94.634667c2.474667 11.52-12.757333 17.941333-19.285333 8.149333z" fill="#CE613E"/><path d="M362.666667 458.730667a32 32 0 1 1-64 0 32 32 0 0 1 64 0zM725.333333 458.730667a32 32 0 1 1-64 0 32 32 0 0 1 64 0zM524.928 673.6a10.666667 10.666667 0 0 0-11.264-12.608 10.666667 10.666667 0 0 0-11.242667 12.565333c-5.12 10.453333-17.109333 15.978667-32.341333 17.088a72.042667 72.042667 0 0 1-22.933333-1.962666 34.218667 34.218667 0 0 1-7.36-2.752c-1.109333-0.597333-1.6-1.024-1.706667-1.130667h-0.021333a10.666667 10.666667 0 0 0-18.048 11.370667c2.432 3.989333 6.250667 6.698667 9.6 8.533333 3.562667 1.92 7.722667 3.434667 12.074666 4.608 8.725333 2.304 19.306667 3.392 29.952 2.602667 14.229333-1.024 30.72-5.76 41.941334-17.386667 10.858667 11.562667 26.773333 16.341333 40.853333 17.386667 10.474667 0.789333 20.970667-0.32 29.781333-2.602667 8.234667-2.133333 17.024-5.824 22.122667-11.733333a10.666667 10.666667 0 0 0-16.192-13.930667c-0.682667 0.832-4.138667 3.157333-11.306667 5.013333-6.613333 1.706667-14.72 2.602667-22.826666 1.984-14.592-1.088-26.048-6.485333-31.082667-17.045333z" fill="#000000"/><path d="M316.544 264.96l15.296-10.304a323.2 323.2 0 0 1 360.32 0l15.296 10.304L832 128.042667v471.68l-74.752 18.346666a10.666667 10.666667 0 0 0 5.077333 20.693334L832 621.696v39.744h-74.666667a10.666667 10.666667 0 1 0 0 21.333333H832v40.682667l-71.658667-12.245333a10.666667 10.666667 0 1 0-3.584 21.034666l75.242667 12.842667v151.018667H192v-150.976l75.264-12.501334a10.666667 10.666667 0 1 0-3.498667-21.056L192 723.498667v-40.746667h74.666667a10.666667 10.666667 0 0 0 0-21.333333H192v-40.533334l71.338667 13.077334a10.666667 10.666667 0 1 0 3.84-20.970667L192 599.189333V128.042667l124.544 136.917333zM853.333333 594.474667V128.042667c0-19.498667-24-28.778667-37.12-14.357334l-112.128 123.285334a344.512 344.512 0 0 0-384.149333 0L207.786667 113.685333C194.666667 99.264 170.666667 108.586667 170.666667 128.042667v467.221333l-71.338667-13.077333a10.666667 10.666667 0 0 0-3.84 20.970666L170.666667 616.96v44.437333H96a10.666667 10.666667 0 1 0 0 21.333334H170.666667v44.309333l-75.264 12.501333a10.666667 10.666667 0 0 0 3.498666 21.056L170.666667 748.650667v147.413333h682.666666v-147.349333l71.658667 12.245333a10.666667 10.666667 0 1 0 3.584-21.034667L853.333333 727.082667v-44.330667h74.666667a10.666667 10.666667 0 0 0 0-21.333333H853.333333v-44.970667l74.752-18.346667a10.666667 10.666667 0 0 0-5.077333-20.736L853.333333 594.474667z" fill="#000000"/></svg>';
  var SVG_PIXEL = '<svg class="icon" viewBox="0 0 1024 1024" xmlns="http://www.w3.org/2000/svg"><path d="M170.666667 410.538667V127.786667c0-19.328 24.106667-28.48 37.184-14.101334l112.064 123.178667a344.490667 344.490667 0 0 1 384.149333 0l112.085333-123.178667C829.226667 99.328 853.333333 108.48 853.333333 127.786667V896H170.666667V410.538667z" fill="#FFFFFF"/><path d="M170.666667 413.781333V128.042667c0-19.541333 24.106667-28.8 37.184-14.272l112.064 124.522666a341.205333 341.205333 0 0 1 61.461333-33.194666C422.784 187.946667 499.2 192 544 192c0 0-48.298667 163.968-106.666667 256-70.058667 110.464-192 181.333333-266.666666 202.666667V413.781333z" fill="#B8B8B8"/><path d="M853.333333 413.781333V128.042667c0-19.541333-24.106667-28.8-37.184-14.272l-112.064 124.522666a341.184 341.184 0 0 0-61.461333-33.194666C601.216 187.946667 524.8 192 480 192c0 0 48.298667 163.968 106.666667 256 70.058667 110.442667 192 181.333333 266.666666 202.666667V413.781333z" fill="#B8B8B8"/><path d="M362.666667 458.666667a32 32 0 1 1-64 0 32 32 0 0 1 64 0zM725.333333 458.666667a32 32 0 1 1-64 0 32 32 0 0 1 64 0zM524.928 673.536a10.666667 10.666667 0 0 0-11.242667-12.629333 10.688 10.688 0 0 0-11.264 12.586666c-5.12 10.453333-17.109333 15.957333-32.341333 17.066667a72.042667 72.042667 0 0 1-22.933333-1.941333 34.218667 34.218667 0 0 1-7.36-2.773334 9.109333 9.109333 0 0 1-1.728-1.130666 10.666667 10.666667 0 0 0-18.048 11.370666c2.432 3.989333 6.250667 6.698667 9.6 8.533334 3.562667 1.92 7.722667 3.456 12.074666 4.608 8.725333 2.304 19.306667 3.413333 29.952 2.624 14.229333-1.045333 30.72-5.76 41.941334-17.408 10.837333 11.562667 26.773333 16.362667 40.853333 17.408 10.474667 0.789333 20.949333-0.32 29.781333-2.602667 8.234667-2.133333 17.024-5.845333 22.122667-11.754667a10.666667 10.666667 0 0 0-16.192-13.909333c-0.682667 0.810667-4.138667 3.157333-11.306667 5.013333-6.613333 1.706667-14.72 2.581333-22.826666 1.984-14.592-1.109333-26.048-6.506667-31.082667-17.066666z" fill="#000000"/><path d="M316.544 264.896l15.296-10.304a323.157333 323.157333 0 0 1 360.32 0l15.296 10.304L832 127.978667v471.658666l-74.752 18.346667a10.666667 10.666667 0 1 0 5.077333 20.714667L832 621.589333V661.333333h-74.666667a10.666667 10.666667 0 0 0 0 21.333334H832v40.682666l-71.658667-12.224a10.666667 10.666667 0 0 0-3.584 21.013334l75.242667 12.864V896H192v-150.954667l75.264-12.522666a10.666667 10.666667 0 1 0-3.498667-21.034667L192 723.413333V682.666667h74.666667a10.666667 10.666667 0 0 0 0-21.333334H192v-40.533333l71.338667 13.098667a10.666667 10.666667 0 1 0 3.84-20.992L192 599.104V128l124.544 136.917333zM853.333333 594.389333V128c0-19.498667-24-28.8-37.12-14.357333l-112.128 123.285333a344.512 344.512 0 0 0-384.149333 0L207.786667 113.578667C194.666667 99.2 170.666667 108.501333 170.666667 128v467.2l-71.338667-13.077333a10.666667 10.666667 0 0 0-3.84 20.992L170.666667 616.896V661.333333H96a10.666667 10.666667 0 0 0 0 21.333334H170.666667v44.288l-75.264 12.522666a10.666667 10.666667 0 1 0 3.498666 21.034667L170.666667 748.586667V896h682.666666v-147.349333l71.658667 12.224a10.666667 10.666667 0 1 0 3.584-21.013334L853.333333 726.997333V682.666667h74.666667a10.666667 10.666667 0 0 0 0-21.333334H853.333333v-44.970666l74.752-18.346667a10.666667 10.666667 0 0 0-5.077333-20.714667L853.333333 594.389333z" fill="#000000"/></svg>';
  var SVG_TECH = '<svg class="icon" viewBox="0 0 1024 1024" xmlns="http://www.w3.org/2000/svg"><path d="M170.666667 410.538667V127.786667c0-19.328 24.106667-28.48 37.184-14.101334l112.064 123.178667a344.490667 344.490667 0 0 1 384.149333 0l112.085333-123.178667C829.226667 99.328 853.333333 108.48 853.333333 127.786667V896H170.666667V410.538667z" fill="#FFFFFF"/><path d="M853.333333 413.781333c-41.450667-198.677333-167.786667-122.325333-266.666666 34.218667-69.845333 110.592 192 117.333333 266.666666 138.666667v-172.885334z" fill="#7E4C27"/><path d="M170.666667 413.781333V128.042667c0-19.541333 24.106667-28.8 37.184-14.272l112.064 124.522666a341.184 341.184 0 0 1 61.461333-33.194666C422.784 187.946667 413.866667 192 458.666667 192c0 0 37.034667 163.968-21.333334 256-70.058667 110.442667-192 181.333333-266.666666 202.666667V413.781333z" fill="#FBCA82"/><path d="M362.666667 458.666667a32 32 0 1 1-64 0 32 32 0 0 1 64 0zM725.333333 458.666667a32 32 0 1 1-64 0 32 32 0 0 1 64 0zM524.928 673.536a10.666667 10.666667 0 0 0-11.242667-12.629333 10.688 10.688 0 0 0-11.264 12.586666c-5.12 10.453333-17.109333 15.957333-32.341333 17.066667a72.042667 72.042667 0 0 1-22.933333-1.941333 34.218667 34.218667 0 0 1-7.36-2.773334 9.109333 9.109333 0 0 1-1.728-1.130666 10.666667 10.666667 0 0 0-18.048 11.370666c2.432 3.989333 6.250667 6.698667 9.6 8.533334 3.562667 1.92 7.722667 3.456 12.074666 4.608 8.725333 2.304 19.306667 3.413333 29.952 2.624 14.229333-1.045333 30.72-5.76 41.941334-17.408 10.837333 11.562667 26.773333 16.362667 40.853333 17.408 10.474667 0.789333 20.949333-0.32 29.781333-2.602667 8.234667-2.133333 17.024-5.845333 22.122667-11.754667a10.666667 10.666667 0 0 0-16.192-13.909333c-0.682667 0.810667-4.138667 3.157333-11.306667 5.013333-6.613333 1.706667-14.72 2.581333-22.826666 1.984-14.592-1.109333-26.048-6.506667-31.082667-17.066666z" fill="#000000"/><path d="M316.544 264.896l15.296-10.304a323.157333 323.157333 0 0 1 360.32 0l15.296 10.304L832 127.978667v471.658666l-74.752 18.346667a10.666667 10.666667 0 1 0 5.077333 20.714667L832 621.589333V661.333333h-74.666667a10.666667 10.666667 0 0 0 0 21.333334H832v40.682666l-71.658667-12.224a10.666667 10.666667 0 0 0-3.584 21.013334l75.242667 12.864V896H192v-150.954667l75.264-12.522666a10.666667 10.666667 0 1 0-3.498667-21.034667L192 723.413333V682.666667h74.666667a10.666667 10.666667 0 0 0 0-21.333334H192v-40.533333l71.338667 13.098667a10.666667 10.666667 0 1 0 3.84-20.992L192 599.104V128l124.544 136.917333zM853.333333 594.389333V128c0-19.498667-24-28.8-37.12-14.357333l-112.128 123.285333a344.512 344.512 0 0 0-384.149333 0L207.786667 113.578667C194.666667 99.2 170.666667 108.501333 170.666667 128v467.2l-71.338667-13.077333a10.666667 10.666667 0 0 0-3.84 20.992L170.666667 616.896V661.333333H96a10.666667 10.666667 0 0 0 0 21.333334H170.666667v44.288l-75.264 12.522666a10.666667 10.666667 0 1 0 3.498666 21.034667L170.666667 748.586667V896h682.666666v-147.349333l71.658667 12.224a10.666667 10.666667 0 1 0 3.584-21.013334L853.333333 726.997333V682.666667h74.666667a10.666667 10.666667 0 0 0 0-21.333334H853.333333v-44.970666l74.752-18.346667a10.666667 10.666667 0 0 0-5.077333-20.714667L853.333333 594.389333z" fill="#000000"/></svg>';
  var SVG_MORANDI = '<svg class="icon" viewBox="0 0 1024 1024" xmlns="http://www.w3.org/2000/svg"><path d="M170.666667 410.538667V127.786667c0-19.328 24.106667-28.48 37.184-14.101334l112.064 123.178667a344.490667 344.490667 0 0 1 384.149333 0l112.085333-123.178667C829.226667 99.328 853.333333 108.48 853.333333 127.786667V896H170.666667V410.538667z" fill="#888074"/><path d="M438.314667 294.805333L384 213.333333l53.333333-21.333333 20.266667 94.656c2.474667 11.498667-12.757333 17.92-19.285333 8.149333zM500.202667 286.293333l-20.096-95.829333 57.429333 0.042667-16.384 95.402666c-2.005333 11.605333-18.56 11.904-20.949333 0.384zM568.725333 284.373333L584.533333 187.733333l53.546667 20.778667-49.706667 83.050667c-6.037333 10.090667-21.568 4.416-19.669333-7.189334z" fill="#4A4A4A"/><path d="M362.666667 458.666667a32 32 0 1 1-64 0 32 32 0 0 1 64 0zM725.333333 458.666667a32 32 0 1 1-64 0 32 32 0 0 1 64 0zM510.186667 661.248a10.666667 10.666667 0 0 0-7.594667 13.034667c7.04 26.645333 31.36 36.053333 51.84 37.546666 10.474667 0.810667 20.949333-0.298667 29.781333-2.581333 8.234667-2.133333 17.024-5.845333 22.122667-11.754667a10.666667 10.666667 0 0 0-16.192-13.909333c-0.682667 0.810667-4.138667 3.157333-11.306667 5.013333-6.613333 1.706667-14.72 2.581333-22.826666 1.984-16.618667-1.258667-29.184-8.085333-32.789334-21.76a10.666667 10.666667 0 0 0-13.034666-7.573333z" fill="#000000"/><path d="M517.184 661.248a10.666667 10.666667 0 0 1 7.573333 13.034667c-7.104 26.837333-32.512 36.053333-53.12 37.568a93.354667 93.354667 0 0 1-29.952-2.624 55.168 55.168 0 0 1-12.074666-4.608 24.96 24.96 0 0 1-9.6-8.533334 10.666667 10.666667 0 0 1 18.048-11.370666c0.106667 0.085333 0.576 0.512 1.728 1.152 1.706667 0.917333 4.16 1.898667 7.36 2.752 6.4 1.685333 14.613333 2.56 22.933333 1.962666 17.344-1.28 30.506667-8.277333 34.048-21.76a10.666667 10.666667 0 0 1 13.056-7.573333z" fill="#000000"/><path d="M316.544 264.896l15.296-10.304a323.157333 323.157333 0 0 1 360.32 0l15.296 10.304L832 127.978667v471.658666l-74.752 18.346667a10.666667 10.666667 0 1 0 5.077333 20.714667L832 621.589333V661.333333h-74.666667a10.666667 10.666667 0 0 0 0 21.333334H832v40.682666l-71.658667-12.224a10.666667 10.666667 0 0 0-3.584 21.013334l75.242667 12.864V896H192v-150.954667l75.264-12.522666a10.666667 10.666667 0 1 0-3.498667-21.034667L192 723.413333V682.666667h74.666667a10.666667 10.666667 0 0 0 0-21.333334H192v-40.533333l71.338667 13.098667a10.666667 10.666667 0 1 0 3.84-20.992L192 599.104V128l124.544 136.917333zM853.333333 594.389333V128c0-19.498667-24-28.8-37.12-14.357333l-112.128 123.285333a344.512 344.512 0 0 0-384.149333 0L207.786667 113.578667C194.666667 99.2 170.666667 108.501333 170.666667 128v467.2l-71.338667-13.077333a10.666667 10.666667 0 0 0-3.84 20.992L170.666667 616.896V661.333333H96a10.666667 10.666667 0 0 0 0 21.333334H170.666667v44.288l-75.264 12.522666a10.666667 10.666667 0 1 0 3.498666 21.034667L170.666667 748.586667V896h682.666666v-147.349333l71.658667 12.224a10.666667 10.666667 0 1 0 3.584-21.013334L853.333333 726.997333V682.666667h74.666667a10.666667 10.666667 0 0 0 0-21.333334H853.333333v-44.970666l74.752-18.346667a10.666667 10.666667 0 0 0-5.077333-20.714667L853.333333 594.389333z" fill="#000000"/></svg>';

  var PALETTES = [
    { id: "default", icon: SVG_DEFAULT, name: "墨绿风" },
    { id: "pixel", icon: SVG_PIXEL, name: "像素风" },
    { id: "tech", icon: SVG_TECH, name: "科技风" },
    { id: "morandi", icon: SVG_MORANDI, name: "莫兰迪风" },
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

  function setButtonIcon(btn, svgHtml) {
    var icon = btn.querySelector(".btn-icon");
    if (icon) icon.innerHTML = svgHtml;
    else btn.innerHTML = svgHtml;
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
