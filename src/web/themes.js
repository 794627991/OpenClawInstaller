/* ============================================
   🎨 主题系统 — 配色（11）× 风格（11）= 121 自由搭配
   配色 = 颜色变量；风格 = 形态/图标/质感变量
   ============================================ */
"use strict";

const PALETTES = [
  { id: "default", name: "龙虾粉", icon: "🦞", desc: "深色·龙虾红" },
  { id: "aurora",  name: "深海极光", icon: "🌌", desc: "深蓝黑·青绿" },
  { id: "sunset",  name: "霞光橙", icon: "🌇", desc: "深棕黑·金橙" },
  { id: "matrix",  name: "极客墨绿", icon: "🖥️", desc: "纯黑·矩阵绿" },
  { id: "violet",  name: "紫罗兰之夜", icon: "🪻", desc: "深紫·薰衣草紫" },
  { id: "frost",   name: "霜雪蓝", icon: "❄️", desc: "亮色·冰晶白" },
  { id: "cream",   name: "暖阳米", icon: "☀️", desc: "亮色·米白" },
  { id: "neon",    name: "赛博霓虹", icon: "🌃", desc: "深黑·电光蓝紫" },
  { id: "forest",  name: "晨雾森林", icon: "🌲", desc: "墨绿·苔藓黄绿" },
  { id: "desert",  name: "日落红砂", icon: "🏜️", desc: "红棕·琥珀砂" },
  { id: "sakura",  name: "樱花白", icon: "🌸", desc: "亮色·樱花浅粉" },
];

const PALETTE_VARS = {
  "default": {
    "--bg": "#13131f", "--card": "rgba(45,45,68,.55)", "--card-solid": "#2a2a45",
    "--accent": "#f38ba8", "--accent-deep": "#d96a8a", "--accent-orange": "#f9b17a",
    "--text": "#dfe3f5", "--text-dim": "#8a8fb8", "--input-bg": "rgba(49,50,68,.7)",
    "--border": "rgba(255,255,255,.08)",
    "--glow": "rgba(243,138,168,.38)", "--glow-soft": "rgba(243,138,168,.16)",
    "--accent-border": "rgba(243,138,168,.45)", "--ring": "rgba(243,138,168,.35)",
    "--link": "#89b4fa",
    "--glow1": "rgba(243,138,168,.16)", "--glow2": "rgba(137,180,250,.12)",
    "--glow3": "rgba(249,177,122,.07)",
  },
  "aurora": {
    "--bg": "#0b1220", "--card": "rgba(20,32,52,.55)", "--card-solid": "#16283f",
    "--accent": "#4fd6c2", "--accent-deep": "#2aa89a", "--accent-orange": "#7dd3fc",
    "--text": "#d9e9f5", "--text-dim": "#7489a8", "--input-bg": "rgba(16,30,50,.7)",
    "--border": "rgba(140,200,255,.09)",
    "--glow": "rgba(79,214,194,.35)", "--glow-soft": "rgba(79,214,194,.15)",
    "--accent-border": "rgba(79,214,194,.45)", "--ring": "rgba(79,214,194,.35)",
    "--link": "#7dd3fc",
    "--glow1": "rgba(79,214,194,.14)", "--glow2": "rgba(125,211,252,.10)",
    "--glow3": "rgba(30,64,175,.12)",
  },
  "sunset": {
    "--bg": "#1a1214", "--card": "rgba(58,40,38,.55)", "--card-solid": "#34221f",
    "--accent": "#f97316", "--accent-deep": "#d95f0e", "--accent-orange": "#fbbf24",
    "--text": "#f5e8dc", "--text-dim": "#a88474", "--input-bg": "rgba(48,30,26,.7)",
    "--border": "rgba(255,200,150,.09)",
    "--glow": "rgba(249,115,22,.35)", "--glow-soft": "rgba(249,115,22,.15)",
    "--accent-border": "rgba(249,115,22,.45)", "--ring": "rgba(249,115,22,.35)",
    "--link": "#fbbf24",
    "--glow1": "rgba(249,115,22,.13)", "--glow2": "rgba(251,191,36,.09)",
    "--glow3": "rgba(190,18,60,.10)",
  },
  "matrix": {
    "--bg": "#050a06", "--card": "rgba(14,30,16,.6)", "--card-solid": "#0c1f10",
    "--accent": "#22c55e", "--accent-deep": "#15803d", "--accent-orange": "#a3e635",
    "--text": "#d7f5dd", "--text-dim": "#6a9271", "--input-bg": "rgba(10,24,12,.7)",
    "--border": "rgba(80,220,120,.10)",
    "--glow": "rgba(34,197,94,.32)", "--glow-soft": "rgba(34,197,94,.13)",
    "--accent-border": "rgba(34,197,94,.45)", "--ring": "rgba(34,197,94,.35)",
    "--link": "#a3e635",
    "--glow1": "rgba(34,197,94,.12)", "--glow2": "rgba(163,230,53,.07)",
    "--glow3": "rgba(0,80,40,.14)",
  },
  "violet": {
    "--bg": "#140f1f", "--card": "rgba(50,38,74,.55)", "--card-solid": "#2e2247",
    "--accent": "#a78bfa", "--accent-deep": "#7c5cd6", "--accent-orange": "#f0abfc",
    "--text": "#e8e0f7", "--text-dim": "#9386b5", "--input-bg": "rgba(38,28,60,.7)",
    "--border": "rgba(190,160,255,.10)",
    "--glow": "rgba(167,139,250,.35)", "--glow-soft": "rgba(167,139,250,.15)",
    "--accent-border": "rgba(167,139,250,.45)", "--ring": "rgba(167,139,250,.35)",
    "--link": "#f0abfc",
    "--glow1": "rgba(167,139,250,.14)", "--glow2": "rgba(240,171,252,.08)",
    "--glow3": "rgba(90,60,160,.12)",
  },
  "frost": {
    "--bg": "#eef3f8", "--card": "rgba(255,255,255,.82)", "--card-solid": "#ffffff",
    "--card-hover": "rgba(223,230,240,.9)",
    "--title-color": "#3b4a63", "--success": "#1a7f37", "--warning": "#9a6700", "--error": "#c83f4d",
    "--accent": "#3b82f6", "--accent-deep": "#2563eb", "--accent-orange": "#38bdf8",
    "--text": "#28374d", "--text-dim": "#7588a3", "--input-bg": "rgba(255,255,255,.9)",
    "--border": "rgba(59,130,246,.14)",
    "--glow": "rgba(59,130,246,.30)", "--glow-soft": "rgba(59,130,246,.12)",
    "--accent-border": "rgba(59,130,246,.45)", "--ring": "rgba(59,130,246,.30)",
    "--link": "#2563eb",
    "--glow1": "rgba(59,130,246,.10)", "--glow2": "rgba(56,189,248,.10)",
    "--glow3": "rgba(125,211,252,.12)",
  },
  "cream": {
    "--bg": "#f6f1e8", "--card": "rgba(255,252,245,.88)", "--card-solid": "#fffdf7",
    "--card-hover": "rgba(244,238,225,.95)",
    "--title-color": "#5a4b38", "--success": "#4d7c0f", "--warning": "#92700c", "--error": "#b3382d",
    "--accent": "#e07a3f", "--accent-deep": "#c05a2a", "--accent-orange": "#f2a65a",
    "--text": "#4a3f33", "--text-dim": "#9a8b76", "--input-bg": "rgba(255,255,255,.95)",
    "--border": "rgba(224,122,63,.16)",
    "--glow": "rgba(224,122,63,.30)", "--glow-soft": "rgba(224,122,63,.12)",
    "--accent-border": "rgba(224,122,63,.45)", "--ring": "rgba(224,122,63,.28)",
    "--link": "#c05a2a",
    "--glow1": "rgba(224,122,63,.10)", "--glow2": "rgba(242,166,90,.12)",
    "--glow3": "rgba(200,180,120,.10)",
  },
  "neon": {
    "--bg": "#0a0a14", "--card": "rgba(28,26,54,.58)", "--card-solid": "#1c1a36",
    "--accent": "#ff4fd8", "--accent-deep": "#d633c2", "--accent-orange": "#4dd4ff",
    "--text": "#e8e6ff", "--text-dim": "#8580b8", "--input-bg": "rgba(24,22,46,.75)",
    "--border": "rgba(110,100,255,.14)",
    "--glow": "rgba(255,79,216,.40)", "--glow-soft": "rgba(255,79,216,.16)",
    "--accent-border": "rgba(255,79,216,.50)", "--ring": "rgba(120,90,255,.40)",
    "--link": "#4dd4ff",
    "--glow1": "rgba(255,79,216,.13)", "--glow2": "rgba(77,212,255,.12)",
    "--glow3": "rgba(120,90,255,.12)",
  },
  "forest": {
    "--bg": "#0f1811", "--card": "rgba(32,48,34,.58)", "--card-solid": "#1e3020",
    "--accent": "#84cc16", "--accent-deep": "#5a920d", "--accent-orange": "#d9f99d",
    "--text": "#ddefd2", "--text-dim": "#7e9673", "--input-bg": "rgba(24,40,26,.7)",
    "--border": "rgba(160,220,120,.10)",
    "--glow": "rgba(132,204,22,.32)", "--glow-soft": "rgba(132,204,22,.13)",
    "--accent-border": "rgba(132,204,22,.45)", "--ring": "rgba(132,204,22,.35)",
    "--link": "#d9f99d",
    "--glow1": "rgba(132,204,22,.12)", "--glow2": "rgba(217,249,157,.07)",
    "--glow3": "rgba(16,60,30,.16)",
  },
  "desert": {
    "--bg": "#1c0f0b", "--card": "rgba(62,36,24,.58)", "--card-solid": "#3b2216",
    "--accent": "#ff7a45", "--accent-deep": "#e05524", "--accent-orange": "#ffc46b",
    "--text": "#f7e3d3", "--text-dim": "#a98774", "--input-bg": "rgba(52,30,20,.72)",
    "--border": "rgba(255,150,100,.10)",
    "--glow": "rgba(255,122,69,.35)", "--glow-soft": "rgba(255,122,69,.15)",
    "--accent-border": "rgba(255,122,69,.45)", "--ring": "rgba(255,122,69,.35)",
    "--link": "#ffc46b",
    "--glow1": "rgba(255,122,69,.13)", "--glow2": "rgba(255,196,107,.09)",
    "--glow3": "rgba(120,40,10,.14)",
  },
  "sakura": {
    "--bg": "#fdf3f5", "--card": "rgba(255,255,255,.86)", "--card-solid": "#ffffff",
    "--card-hover": "rgba(252,240,244,.95)",
    "--title-color": "#6f4a5e", "--success": "#3d7a4f", "--warning": "#95601f", "--error": "#c74a66",
    "--accent": "#e26d8f", "--accent-deep": "#c95070", "--accent-orange": "#f5b8c8",
    "--text": "#57384a", "--text-dim": "#a98897", "--input-bg": "rgba(255,255,255,.95)",
    "--border": "rgba(226,109,143,.16)",
    "--glow": "rgba(226,109,143,.32)", "--glow-soft": "rgba(226,109,143,.13)",
    "--accent-border": "rgba(226,109,143,.45)", "--ring": "rgba(226,109,143,.30)",
    "--link": "#c95070",
    "--glow1": "rgba(226,109,143,.11)", "--glow2": "rgba(245,184,200,.14)",
    "--glow3": "rgba(255,220,230,.12)",
  },
};

/* 风格维度：形态/质感/图标（CSS 变量 + body[data-style] 类组件覆盖在 style.css） */
const STYLES = [
  { id: "s1",  name: "玻璃拟态", icon: "🧊", desc: "毛玻璃·圆润胶囊" },
  { id: "s2",  name: "果冻透明", icon: "🍮", desc: "超大圆角·饱满描边" },
  { id: "s3",  name: "锐利商务", icon: "💼", desc: "小圆角·细线方角" },
  { id: "s4",  name: "赛博机能", icon: "🤖", desc: "直角·虚线科技框" },
  { id: "s5",  name: "复古像素", icon: "👾", desc: "方块·硬阴影像素" },
  { id: "s6",  name: "手绘涂鸦", icon: "✏️", desc: "波浪圆·手绘线条" },
  { id: "s7",  name: "雅致细线", icon: "🏛️", desc: "极细线·优雅留白" },
  { id: "s8",  name: "自然有机", icon: "🌿", desc: "饱满曲线·生机感" },
  { id: "s9",  name: "极简黑白", icon: "⬛", desc: "无光晕·扁平克制" },
  { id: "s10", name: "霓虹光效", icon: "💡", desc: "发光描边·光感图标" },
  { id: "s11", name: "模块网格", icon: "🧩", desc: "虚线网格·模块化" },
];

function currentTheme() {
  // 读取必须 try/catch：存储损坏/禁用时抛异常会导致 initThemes 中断，
  // 进而所有按钮绑定失效（界面完全不可操作）
  let pal = "default", sty = "s1";
  try { pal = localStorage.getItem("ocw-palette") || "default"; } catch (e) {}
  try { sty = localStorage.getItem("ocw-style") || "s1"; } catch (e) {}
  return { palette: pal, style: sty };
}

function applyPalette(paletteId) {
  const vars = PALETTE_VARS[paletteId] || PALETTE_VARS["default"];
  const root = document.documentElement;
  // 审计 5.1：先清掉上个调色板的全部变量（亮色→暗色切换残留 --title-color 等导致低对比度）
  Object.values(PALETTE_VARS).forEach(v => Object.keys(v).forEach(k => root.style.removeProperty(k)));
  Object.entries(vars).forEach(([k, v]) => root.style.setProperty(k, v));
  try { localStorage.setItem("ocw-palette", paletteId); } catch (e) {}
}

function applyStyle(styleId) {
  document.body.setAttribute("data-style", styleId);
  try { localStorage.setItem("ocw-style", styleId); } catch (e) {}
  // 图标集跟随风格
  window.ICONS_CUR = iconSetFor(styleId);
  const styleName = (STYLES.find(s => s.id === styleId) || STYLES[0]).name;
  if (window.__onStyleChange) window.__onStyleChange(styleId, styleName);
}

function applyThemeState() {
  const t = currentTheme();
  applyPalette(t.palette);
  applyStyle(t.style);
}
