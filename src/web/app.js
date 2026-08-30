/* ============================================
   🦞 OpenClaw 工作台 — 安装器 + 启动器
   ============================================ */
"use strict";

// pywebview 桥接在页面加载完成后才注入（pywebviewready 事件）
let api = null;
let pendingApis = [];   // api 未就绪时挂起的任务（队列，不丢点击）
window.addEventListener("pywebviewready", () => {
  api = window.pywebview ? window.pywebview.api : null;
  initMeta();
  initProviders();
  const q = pendingApis; pendingApis = [];
  q.forEach(fn => { try { fn(); } catch (e) {} });
});

// api 未就绪时先排队，就绪后依次执行（消除点击早于桥接注入的竞态）
function waitApi(fn) {
  if (api) { fn(); } else { pendingApis.push(fn); }
}

const $ = (id) => document.getElementById(id);
let PROVIDERS = [];
let providers = [];
let selected = null;
let envOk = {};
let installDir = "";
let statusData = null;

/* ---------- SVG 图标注入（data-icon 占位符 → 当前风格图标集） ---------- */
function injectIcons() {
  document.querySelectorAll("[data-icon]").forEach(el => {
    if (el.id === "hero-logo") return;  // hero 龙虾由 initHeroLogo 处理
    const svg = (window.ICONS_CUR || {})[el.dataset.icon];
    if (svg) el.innerHTML = svg;
  });
}

function initHeroLogo() {
  // hero 龙虾：直接显示品牌图标 PNG（icon.png）——跨系统 100% 稳定，
  // 不再依赖 emoji 渲染（VM/字体缺失时 emoji 显示为方框）
  // 图标已放在 index.html 的 <img src="icon.png">，无需 JS 处理。
}

/* ---------- 鼠标跟随毛玻璃波纹 ---------- */
function initMouseTrail() {
  const cx = innerWidth / 2, cy = innerHeight / 2;
  let tx = cx, ty = cy;
  const dots = [...document.querySelectorAll(".trail-dot")].map(d => {
    const size = parseFloat(getComputedStyle(d).width);
    return {
      el: d,
      x: cx, y: cy,
      speed: parseFloat(d.dataset.speed || "0.12"),
      scale: parseFloat(d.dataset.scale || "1"),
      size: size,
    };
  });
  // 只有鼠标移动时才运行动画（静止即停，省 CPU）
  let running = false, rafId = null;
  function frame() {
    if (document.hidden) { running = false; rafId = null; return; }  // 隐藏即停（CPU 降载）
    let moved = false;
    dots.forEach(t => {
      const nx = t.x + (tx - t.x) * t.speed;
      const ny = t.y + (ty - t.y) * t.speed;
      if (Math.abs(nx - t.x) > 0.3 || Math.abs(ny - t.y) > 0.3) moved = true;
      t.x = nx; t.y = ny;
      const off = t.size / 2;
      t.el.style.transform =
        `translate(${t.x - off}px, ${t.y - off}px) scale(${t.scale})`;
    });
    if (moved) {
      rafId = requestAnimationFrame(frame);   // 还在追鼠标，继续
    } else {
      running = false;                        // 已追上鼠标，停
      rafId = null;
    }
  }
  function start() {
    if (!running) { running = true; rafId = requestAnimationFrame(frame); }
  }
  document.addEventListener("mousemove", e => { tx = e.clientX; ty = e.clientY; start(); });
}

/* ---------- 性能：窗口失焦/隐藏时降载 ----------
   WebView2 软件渲染下：无限 CSS 动画 + 卡片 backdrop-filter 毛玻璃 都是 CPU 大头。
   失焦（后台/被任务管理器遮挡）即冻结全部动画、隐藏光斑、关闭毛玻璃——聚焦即时恢复 */
function initIdleDetect() {
  const set = idle => document.body.classList.toggle("idle", idle);
  document.addEventListener("visibilitychange", () => set(document.hidden));
  window.addEventListener("blur", () => set(true));
  window.addEventListener("focus", () => set(false));
}

/* ---------- 页面切换 ---------- */
function showPage(name) {
  document.querySelectorAll(".page").forEach(p => p.style.display = "none");
  $("page-" + name).style.display = "flex";
}

/* ---------- 轻提示（Toast） ---------- */
let toastTimer = null;
function toast(text, ok) {
  const el = $("toast");
  el.textContent = text;
  el.style.display = "block";
  // ok 为 true/false 表示完成态（3.5s）；undefined 表示进行中（8s）
  el.className = "toast " + (ok === false ? "toast-bad" : "toast-ok");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { el.style.display = "none"; }, ok == null ? 8000 : 3500);
}

/* ---------- 启动器首页 ---------- */
function renderHome() {
  const meta = window.__meta;
  if (!meta) {
    // meta 未加载时给出提示（避免静默卡死在当前页无任何反馈）
    toast("⚠️ 信息加载中，请稍候…", false);
    waitApi(initMeta);
    return;
  }
  showPage("home");
  if (meta.installed) {
    $("home-install").style.display = "none";
    $("home-usage").style.display = "flex";
    refreshStatus();
    startStatusPolling();
  } else {
    $("home-install").style.display = "flex";
    $("home-usage").style.display = "none";
  }
}

/* 网关状态实时轮询（进入首页已安装态时启动，每 15s 一次） */
let statusTimer = null;
function startStatusPolling() {
  if (statusTimer) return;
  statusTimer = setInterval(() => {
    if (api && $("page-home").style.display !== "none") refreshStatus();
  }, 15000);
}

let _refreshWait = 0;
function refreshStatus() {
  if (api) { api.get_status(); _refreshWait = 0; }
  else if (_refreshWait < 20) {   // 最多重试 20 次（约 6s），防无限自旋
    _refreshWait++;
    setTimeout(refreshStatus, 300);
  }
}

function renderStatus(st) {
  statusData = st;
  const set = (id, text, ok) => {
    const el = $(id);
    el.textContent = text;
    el.className = "status-val " + (ok ? "ok" : "bad");
  };
  const meta = window.__meta || {};
  set("st-version", meta.openclaw_version || "已安装", true);
  // 三级状态：运行中(绿) / 启动中…(黄) / 未运行(红)
  const gwText = st.gateway.text || "";
  if (gwText.includes("启动中")) {
    const el = $("st-gateway");
    el.textContent = gwText;
    el.className = "status-val wait";   // 黄色脉冲
  } else {
    set("st-gateway", gwText, st.gateway.running);
  }
  const cnt = st.model.count > 1 ? `（共${st.model.count}个）` : "";
  set("st-model", st.model.has ? st.model.title + cnt : "未配置", st.model.has);
}

/* ---------- 初始元数据/服务商 ---------- */
function initMeta() {
  if (!api) return;
  api.get_meta().then(meta => {
    window.__meta = meta;
    $("ver").textContent = "v" + meta.version;
    installDir = meta.install_dir;
    $("dir-input").value = installDir;
    if (meta.dry_run) {
      const tip = document.createElement("div");
      tip.style.cssText = "position:fixed;bottom:10px;left:50%;transform:translateX(-50%);background:rgba(199,120,155,.9);color:#fff;border-radius:999px;padding:5px 18px;font-size:12px;z-index:999;backdrop-filter:blur(8px);pointer-events:none;";
      tip.textContent = "🧪 演练模式：仅安装动作不执行（模型/服务功能为真实）";
      document.body.appendChild(tip);
    }
    renderHome();
  }).catch(() => {});
}

function initProviders() {
  if (!api) return;
  api.get_providers().then(list => {
    PROVIDERS = list;
    providers = list.slice();
    renderProviders(providers);
  }).catch(() => {});
}

/* ---------- 后端事件分发 ---------- */
window.__pyEvent = function (msg) {
  switch (msg.type) {
    case "log": appendLog(msg.line); break;
    case "progress":
      $("progress-bar").style.width = msg.value + "%";
      $("progress-label").textContent = msg.label;
      break;
    case "env": renderEnv(msg.results); break;
    case "status": renderStatus(msg.status); break;
    case "toast": toast(msg.text, msg.ok); break;
    case "home": window.__homeUrl = msg.url || ""; break;
    case "done":
      if (msg.kind === "install") {
        if (msg.ok) {
          $("progress-bar").style.width = "100%";
          $("progress-label").textContent = "✅ 安装完成！";
          goConfig("install");   // 安装完成 → 配置 API Key（必需步骤）
        } else {
          $("progress-label").textContent = "❌ 安装失败";
          appendLog("❌ " + msg.info);
          showRetryBar(msg.info);
        }
      } else if (msg.kind === "verify") {
        // 竞态防护：token 指纹不匹配 = 过期结果（用户已换服务商/改 Key），丢弃
        if (msg.token !== undefined && msg.token !== verifyToken) break;
        keyVerified = msg.ok;
        renderVerify(msg.ok, msg.info);
      } else if (msg.kind === "config") {
        // 配置完成 → 回启动器首页，状态刷新
        window.__meta.installed = true;
        renderHome();
      } else if (msg.kind === "launch") {
        refreshStatus();
        enableBtn("btn-fix", true);   // 修复流程结束恢复按钮
        // 模型相关操作完成后：刷新下拉框 + 管理列表
        if ($("model-card") && $("model-card").style.display !== "none") loadModels();
      }
      break;
  }
};

/* ---------- 日志 ---------- */
function appendLog(line) {
  const box = $("log-box");
  if (!box) return;
  box.textContent += line + "\n";
  box.scrollTop = box.scrollHeight;
}

/* ---------- 环境检测页 ---------- */
function renderEnv(results) {
  envOk = results;
  Object.keys(results).forEach(k => {
    const el = document.querySelector(`.env-item[data-key="${k}"] .env-status`);
    el.textContent = results[k].text;
    el.className = "env-status " + (results[k].ok ? "ok" : "bad");
  });
  enableBtn("btn-env-next", true);
}

/* ---------- 服务商列表 ---------- */
function renderProviders(list) {
  const box = $("provider-list");
  if (!box) return;
  box.innerHTML = "";
  let lastGroup = "";
  list.forEach(p => {
    if (p.group !== lastGroup) {
      const g = document.createElement("div");
      g.className = "provider-group";
      g.textContent = `── ${p.group} ──`;
      box.appendChild(g);
      lastGroup = p.group;
    }
    const d = document.createElement("div");
    d.className = "provider-item" + (selected && selected.id === p.id ? " sel" : "");
    d.textContent = "  " + p.name;
    d.onclick = () => selectProvider(p);
    box.appendChild(d);
  });
}

function selectProvider(p) {
  selected = p;
  keyVerified = false;   // 换服务商 → 需重新验证
  verifyToken = "";      // 作废进行中的验证请求结果
  renderProviders(providers);
  $("key-format").textContent = p.needs_key ? "格式：" + p.key_format : "";
  $("guide-title").textContent = "📖 " + p.name + " — 获取 API Key 步骤";
  $("guide-url").textContent = p.url ? "🔗 " + p.url : "";
  $("guide-steps").innerHTML = (p.steps || []).map(s =>
    "<div>• " + escapeHtml(s) + "</div>").join("") ||
    (p.needs_key ? "" : "ℹ️ 此服务商无需 API Key，本地运行，安装后即可直接使用。");
  $("key-card").style.display = p.needs_key ? "" : "none";
  $("verify-result").textContent = "";
  $("verify-result").className = "verify-result";
}

function escapeHtml(s) {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

/* ---------- 验证 Key ---------- */
function renderVerify(ok, info) {
  const el = $("verify-result");
  el.textContent = ok ? "✅ " + info : "❌ " + info;
  el.className = "verify-result " + (ok ? "ok" : "bad");
}

/* ---------- 重试条 ---------- */
function showRetryBar(err) {
  const bar = document.createElement("div");
  bar.id = "retry-bar";
  bar.style.cssText = "max-width:640px;width:100%;background:var(--card);border-radius:14px;padding:12px 16px;margin-bottom:10px;display:flex;gap:10px;align-items:center;";
  const txt = document.createElement("span");
  txt.style.cssText = "flex:1;font-size:12px;color:var(--text);";
  txt.textContent = "安装失败：" + err;
  const btn = document.createElement("button");
  btn.className = "btn-secondary btn-sm";
  btn.textContent = "🔄 重试";
  btn.onclick = () => { $("page-install").removeChild(bar); startInstall(); };
  bar.appendChild(txt); bar.appendChild(btn);
  $("page-install").appendChild(bar);
}

/* ---------- 流程 ---------- */
function startInstall() {
  if (!api) { appendLog("⚠️ 界面初始化中，请稍候再点击"); return; }
  $("log-box").textContent = "";
  $("progress-bar").style.width = "0%";
  api.start_install($("dir-input").value || installDir);
}

let configMode = "install";   // install=安装流程（无返回） / reconfig=启动器更换模型（有返回）
let keyVerified = false;      // API Key 验证是否通过（通过才允许下一步）
let verifyToken = "init" + Math.random().toString(36).slice(2);  // 验证请求指纹（审计：空串会被 token="" 的伪造 done 匹配）

function goConfig(mode) {
  configMode = mode || "install";
  // 重置跨流程状态：清掉上一次配置残留（selected/key/验证态），防串号
  keyVerified = false;
  verifyToken = "";
  selected = null;
  $("key-input").value = "";
  $("key-format").textContent = "";
  $("verify-result").textContent = "";
  $("verify-result").className = "verify-result";
  showPage("config");
  renderProviders(PROVIDERS);
  // 更换模型场景：显示返回按钮 + 已配置模型下拉
  const isRe = configMode === "reconfig";
  $("btn-config-back").style.display = isRe ? "" : "none";
  $("model-card").style.display = isRe ? "" : "none";
  $("btn-config-next").style.display = "";
  const btn = $("btn-config-next");
  btn.textContent = isRe ? "添加新模型 ▶" : "下一步 ▶";
  enableBtn(btn, true);
  if (isRe) loadModels();
}

function loadModels() {
  waitApi(() => {
    api.get_models().then(data => {
      renderModelSelect(data);
    }).catch(() => toast("⚠️ 模型列表加载失败", false));
  });
}

function renderModelSelect(data) {
  const sel = $("model-select");
  sel.innerHTML = "";
  (data.models || []).forEach(m => {
    const opt = document.createElement("option");
    // 显示友好名 + 完整 id
    opt.value = m.id;
    opt.textContent = m.name !== m.id.split("/").pop() ? `${m.name}（${m.id}）` : m.id;
    sel.appendChild(opt);
  });
  $("model-current").textContent = data.current || "未设置";
  if (data.models && data.models.length) {
    // 自动选中当前激活的模型
    for (const m of data.models) {
      if (m.id === data.current) { sel.value = m.id; break; }
    }
  }
  // 管理区 provider 下拉（已配置模型涉及的 provider）
  const pp = $("manage-provider");
  if (pp) {
    const provs = [...new Set((data.models || []).map(m => m.id.split("/")[0]))];
    const cur = pp.value;
    pp.innerHTML = "";
    provs.forEach(pid => {
      const o = document.createElement("option");
      o.value = pid;
      o.textContent = pid;
      pp.appendChild(o);
    });
    if (cur && provs.includes(cur)) pp.value = cur;
    if (provs.length) loadProviderModels(pp.value);
  }
}

function loadProviderModels(providerId) {
  if (!providerId) return;
  waitApi(() => {
    api.list_provider_models(providerId).then(data => {
      renderManageList(data);
    }).catch(() => {
      $("manage-list").innerHTML = "<div class='manage-empty'>加载失败</div>";
    });
  });
}

function renderManageList(data) {
  const box = $("manage-list");
  box.innerHTML = "";
  if (data.error) {
    box.innerHTML = "<div class='manage-empty'>" + escapeHtml(data.error) + "</div>";
    return;
  }
  const rows = {};
  (data.models || []).forEach(m => {
    const row = document.createElement("div");
    row.className = "manage-row";
    const name = m.id.split("/").pop();
    const left = document.createElement("span");
    left.className = "manage-name";
    left.textContent = name + (m.ctx ? " · " + m.ctx : "");
    if (m.configured) left.innerHTML += " <span class='manage-badge'>已配置</span>";
    if (m.default) left.innerHTML += " <span class='manage-badge def'>默认</span>";
    const btn = document.createElement("button");
    btn.className = "btn-secondary btn-sm";
    if (m.configured) {
      btn.textContent = "移除";
      btn.onclick = () => { toast("⏳ 正在移除 " + name + "…"); waitApi(() => api.remove_model(m.id)); };
    } else {
      btn.textContent = "添加";
      btn.onclick = () => { toast("⏳ 正在添加 " + name + "…"); waitApi(() => api.add_model(m.id)); };
    }
    row.appendChild(left);
    row.appendChild(btn);
    box.appendChild(row);
  });
  if (!(data.models || []).length) {
    box.innerHTML = "<div class='manage-empty'>该服务商下没有发现模型</div>";
  }
}

function enableBtn(id, on) {
  const el = typeof id === "string" ? $(id) : id;
  el.disabled = !on;
  el.style.opacity = on ? "" : ".5";
}

/* ---------- 事件绑定 ---------- */
/* ---------- 主题系统（配色 11 × 风格 11 = 121 组合） ---------- */
let _styleBox = null, _paletteBox = null;
function initThemes() {
  applyThemeState();
  const btn = $("theme-btn");
  const panel = $("theme-panel");
  _paletteBox = $("theme-grid");
  _styleBox = $("style-grid");
  // 配色行
  PALETTES.forEach(t => {
    const c = document.createElement("div");
    c.className = "theme-item";
    c.dataset.group = "palette";
    c.dataset.id = t.id;
    const sw = document.createElement("div");
    sw.className = "theme-swatch";
    const v = PALETTE_VARS[t.id] || {};
    sw.style.cssText = `background:${v["--bg"] || "#000"};border-bottom:7px solid ${v["--accent"]}`;
    const info = document.createElement("div");
    info.className = "theme-info";
    info.innerHTML = `<div class="theme-name">${t.icon} ${t.name}</div><div class="theme-desc">${t.desc}</div>`;
    c.appendChild(sw);
    c.appendChild(info);
    c.onclick = () => {
      applyPalette(t.id);
      refreshThemeSel();
      toast(`🎨 配色已切换为「${t.name}」`);
    };
    _paletteBox.appendChild(c);
  });
  // 风格行（演示图标随风格变化）
  STYLES.forEach(s => {
    const c = document.createElement("div");
    c.className = "theme-item";
    c.dataset.group = "style";
    c.dataset.id = s.id;
    const sw = document.createElement("div");
    sw.className = "theme-swatch style-swatch";
    const icoTmp = iconSetFor(s.id);
    sw.innerHTML = `<span class="style-ico">${icoTmp.lobster || ""}</span>`;
    const info = document.createElement("div");
    info.className = "theme-info";
    info.innerHTML = `<div class="theme-name">${s.icon} ${s.name}</div><div class="theme-desc">${s.desc}</div>`;
    c.appendChild(sw);
    c.appendChild(info);
    c.onclick = () => {
      applyStyle(s.id);
      injectIcons();
      refreshThemeSel();
      toast(`✨ 风格已切换为「${s.name}」`);
    };
    _styleBox.appendChild(c);
  });
  function refreshThemeSel() {
    const cur = currentTheme();
    panel.querySelectorAll(".theme-item").forEach(el => {
      const key = el.dataset.group === "style" ? cur.style : cur.palette;
      el.classList.toggle("cur", el.dataset.id === key);
    });
  }
  refreshThemeSel();
  btn.onclick = (e) => {
    e.stopPropagation();
    panel.style.display = panel.style.display === "none" ? "block" : "none";
    refreshThemeSel();
  };
  $("theme-close").onclick = () => { panel.style.display = "none"; };
  document.addEventListener("click", (e) => {
    if (!panel.contains(e.target) && e.target !== btn) panel.style.display = "none";
  });
}

/* ---------- 调试日志弹层 ---------- */
function initLogModal() {
  const modal = $("log-modal");
  const body = $("log-content");
  function open() {
    modal.classList.add("show");
    refresh();
  }
  function refresh() {
    body.textContent = "加载中…";
    waitApi(() => {
      api.get_logs().then(t => {
        body.textContent = t || "（空）";
        body.scrollTop = body.scrollHeight;
      }).catch(() => { body.textContent = "日志读取失败"; });
    });
  }
  $("log-btn").onclick = open;
  $("log-close").onclick = () => modal.classList.remove("show");
  $("log-refresh").onclick = refresh;
  $("log-copy").onclick = () => {
    const t = body.textContent;
    try {
      navigator.clipboard.writeText(t).then(() => toast("✅ 日志已复制到剪贴板"));
    } catch (e) {
      toast("⚠️ 复制失败", false);
    }
  };
  modal.onclick = (e) => { if (e.target === modal) modal.classList.remove("show"); };
}

document.addEventListener("DOMContentLoaded", () => {
  initThemes();     // 先应用主题（设置 ICONS_CUR 与 body[data-style]）
  injectIcons();    // 注入普通图标
  initHeroLogo();   // hero 龙虾（emoji 优先，系统不支持才 SVG）
  initMouseTrail();
  initIdleDetect(); // 失焦/隐藏降载（WebView2 软渲染 CPU 大头）
  initLogModal();
  // 首页：未安装 → 开始检测
  $("btn-start").onclick = () => {
    showPage("env");
    $("btn-env-next").disabled = true;
    waitApi(() => api.check_env());
  };
  // 首页：已安装 → 开始使用 / 修复 / 更换模型 / 重装
  $("btn-use").onclick = () => {
    toast("⏳ 正在启动控制面板…");
    // 传当前配色主色，仪表盘标题栏/关闭按钮跟随主题
    const accent = getComputedStyle(document.documentElement)
      .getPropertyValue("--accent").trim();
    waitApi(() => api.launch_usage(accent));
  };
  $("btn-fix").onclick = () => {
    toast("⏳ 正在修复 Gateway…");
    enableBtn("btn-fix", false);            // 防重复点击
    waitApi(() => api.fix_gateway());
  };
  $("btn-reconfig").onclick = () => waitApi(() => goConfig("reconfig"));
  $("btn-reinstall").onclick = () => {
    showPage("env");
    $("btn-env-next").disabled = true;
    waitApi(() => api.check_env());
  };
  $("btn-config-back").onclick = () => renderHome();
  // 下拉选中即自动切换（无需额外按钮）
  $("model-select").onchange = () => {
    const v = $("model-select").value;
    if (!v) return;
    toast("⏳ 正在切换激活模型…");
    waitApi(() => api.switch_model(v));
  };
  // 模型管理区
  $("btn-manage-models").onclick = () => {
    const box = $("manage-models");
    const show = box.style.display === "none";
    box.style.display = show ? "" : "none";
    if (show) loadModels();
  };
  $("manage-provider").onchange = () => loadProviderModels($("manage-provider").value);

  $("btn-env-next").onclick = () => {
    if (!envOk.network || !envOk.network.ok) {
      if (!confirm("网络连接失败，将无法下载安装包，安装几乎必然失败。\n\n仍然继续吗？")) return;
    }
    showPage("dir");
    $("dir-input").value = installDir;
    $("dir-data").textContent = window.__meta ? window.__meta.data_dir : "";
    renderSpaces();
  };
  $("btn-browse").onclick = async () => {
    if (!api) return;
    const d = await api.browse_dir();
    if (d) $("dir-input").value = d;
  };
  $("btn-install-go").onclick = () => {
    installDir = $("dir-input").value.trim() || installDir;
    showPage("install");
    startInstall();
  };
  // 配置页：API Key 强制 —— 未选服务商 / 无 Key / 未验证通过，一律不允许下一步
  $("btn-config-next").onclick = () => {
    if (!selected) {
      alert("请先选择 AI 服务商后再继续");
      return;
    }
    const key = $("key-input").value.trim();
    if (selected.needs_key && !key) {
      alert("请先填入 API Key（必填，没有 Key 无法使用 AI 对话）\n\n" +
            "获取方法就在左侧指引里，跟着步骤操作即可");
      return;
    }
    if (selected.needs_key && !keyVerified) {
      alert("⚠️ API Key 尚未验证通过\n\n" +
            "请先点击「验证 Key」，确认 Key 有效后再继续。\n" +
            "（官方接口验证，只读不会保存 Key）");
      return;
    }
    $("log-box").textContent = "";
    $("progress-bar").style.width = "0%";
    $("progress-label").textContent = "配置中...";
    showPage("install");
    $("btn-config-next").style.display = "none";
    if (!api) return;
    api.apply_config(selected.id, key, configMode);
  };
  // Key 内容变化 → 验证结果作废（需重新验证）
  $("key-input").addEventListener("input", () => {
    // 改 Key：验证立即作废（含进行中的请求——token 已置空，晚到的结果被丢弃）
    verifyToken = "";
    if (keyVerified) {
      keyVerified = false;
      const el = $("verify-result");
      el.textContent = "修改后请重新验证";
      el.className = "verify-result wait";
    }
  });
  $("btn-toggle-key").onclick = () => {
    const inp = $("key-input");
    inp.type = inp.type === "password" ? "text" : "password";
    $("btn-toggle-key").textContent = inp.type === "password" ? "👁 显示" : "🙈 隐藏";
  };
  $("btn-verify").onclick = () => {
    if (!api) return;
    const key = $("key-input").value.trim();
    if (!selected) { renderVerify(false, "请先选择服务商"); return; }
    if (!key) { renderVerify(false, "请先填入 API Key"); return; }
    keyVerified = false;   // 重新验证期间不可通过
    verifyToken = "v" + Date.now() + Math.random().toString(36).slice(2);
    const el = $("verify-result");
    el.textContent = "⏳ 验证中...";
    el.className = "verify-result wait";
    api.verify_key(selected.id, key, verifyToken);
  };
  $("guide-url").onclick = () => { if (selected && selected.url && api) api.open_url(selected.url); };
  $("provider-search").oninput = () => {
    const q = $("provider-search").value.trim().toLowerCase();
    providers = q ? PROVIDERS.filter(p =>
      p.name.toLowerCase().includes(q) || p.id.toLowerCase().includes(q) || p.group.includes(q))
      : PROVIDERS.slice();
    renderProviders(providers);
  };
});

/* ---------- 磁盘空间 ---------- */
function renderSpaces() {
  const meta = window.__meta;
  if (!meta || !meta.spaces) return;
  [["space-c", "C:"], ["space-d", "D:"]].forEach(([id, d]) => {
    const el = $(id);
    const gb = meta.spaces[d];
    if (gb === null || gb === undefined) { el.textContent = `💾 ${d} 盘：无`; return; }
    el.textContent = `💾 ${d} 盘：${gb.toFixed(1)} GB`;
    el.className = "space-chip " + (gb < 1 ? "low" : "ok");
  });
}
