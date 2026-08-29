/* ============================================
   🎨 图标系统 — 参数化构建器
   同一套语义图形，按风格参数生成差异化画法：
   描边粗细 / 端帽 / 转角 / 虚线 / 填充 / 圆角
   ============================================ */
"use strict";

// 语义图形模板（占位符：{w}描边宽 {cap} {join} {rx}圆角 {dash}虚线 {fill}填充色 {fillf}填充样式）
const ICON_TMPL = {
  lobster: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="{w}" stroke-linecap="{cap}" stroke-linejoin="{join}" {dash}>
    <path d="M12 4.5 C10.5 2.5 6.5 1.5 4.5 2.5"/>
    <path d="M12 4.5 C13.5 2.5 17.5 1.5 19.5 2.5"/>
    <path d="M3 9.5 C1 11.5 1.8 14.5 4 14.5 C6 14.5 6.6 12.3 5 10.9 C4.2 10.2 3 9.8 3 9.5 Z" {fillf}/>
    <path d="M21 9.5 C23 11.5 22.2 14.5 20 14.5 C18 14.5 17.4 12.3 19 10.9 C19.8 10.2 21 9.8 21 9.5 Z" {fillf}/>
    <path d="M6.8 12.2 C6.5 15.5 8.5 18.5 12 18.5 C15.5 18.5 17.5 15.5 17.2 12.2" {fillf}/>
    <circle cx="9.6" cy="14.8" r="0.9" fill="currentColor" stroke="none"/>
    <circle cx="14.4" cy="14.8" r="0.9" fill="currentColor" stroke="none"/>
    <path d="M6.8 12.2 L5.4 13.4" />
    <path d="M17.2 12.2 L18.6 13.4" />
  </svg>`,
  globe: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="{w}" stroke-linecap="{cap}" stroke-linejoin="{join}" {dash}>
    <circle cx="12" cy="12" r="9"/>
    <path d="M3 12 H21"/>
    <path d="M12 3 C8.5 6.5 8.5 17.5 12 21 C15.5 17.5 15.5 6.5 12 3 Z"/>
  </svg>`,
  box: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="{w}" stroke-linecap="{cap}" stroke-linejoin="{join}" {dash}>
    <path d="M12 3 L21 7.5 V16.5 L12 21 L3 16.5 V7.5 Z" {fillf}/>
    <path d="M3 7.5 L12 12 L21 7.5"/>
    <path d="M12 12 V21"/>
  </svg>`,
  code: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="{w}" stroke-linecap="{cap}" stroke-linejoin="{join}" {dash}>
    <path d="M8 6 L2.5 12 L8 18"/>
    <path d="M16 6 L21.5 12 L16 18"/>
  </svg>`,
  chip: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="{w}" stroke-linecap="{cap}" stroke-linejoin="{join}" {dash}>
    <rect x="6" y="6" width="12" height="12" rx="{rx}"/>
    <rect x="10" y="10" width="4" height="4" rx="{rx1}"/>
    <path d="M9 3 V6 M15 3 V6 M9 18 V21 M15 18 V21 M3 9 H6 M3 15 H6 M18 9 H21 M18 15 H21"/>
  </svg>`,
  monitor: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="{w}" stroke-linecap="{cap}" stroke-linejoin="{join}" {dash}>
    <rect x="3" y="4" width="18" height="13" rx="{rx}"/>
    <path d="M8 21 H16 M12 17 V21"/>
  </svg>`,
  key: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="{w}" stroke-linecap="{cap}" stroke-linejoin="{join}" {dash}>
    <circle cx="8" cy="8" r="4.5"/>
    <path d="M11.5 11.5 L20 20 M16.5 16.5 L19 14 M13.5 13.5 L16 11"/>
  </svg>`,
  check: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="{wc}" stroke-linecap="{cap}" stroke-linejoin="{join}">
    <path d="M4.5 12.5 L10 18 L19.5 6.5"/>
  </svg>`,
  wrench: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="{w}" stroke-linecap="{cap}" stroke-linejoin="{join}" {dash}>
    <path d="M14.5 6.5 a3.5 3.5 0 0 0 -4.8 3.8 L4 16 L8 20 L13.7 14.3 a3.5 3.5 0 0 0 3.8 -4.8 L14.5 12.5 L11.5 9.5 Z"/>
  </svg>`,
  refresh: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="{w}" stroke-linecap="{cap}" stroke-linejoin="{join}" {dash}>
    <path d="M20 12 a8 8 0 1 1 -2.3 -5.6"/>
    <path d="M20 4 V8.5 H15.5"/>
  </svg>`,
  play: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="{w}" stroke-linecap="{cap}" stroke-linejoin="{join}" {dash}>
    <rect x="2.5" y="4" width="19" height="16" rx="{rx}"/>
    <path d="M10 8.5 L16 12 L10 15.5 Z" fill="currentColor" stroke="none"/>
  </svg>`,
  folder: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="{w}" stroke-linecap="{cap}" stroke-linejoin="{join}" {dash}>
    <path d="M3 7 a2 2 0 0 1 2 -2 h4 l2.5 2.5 H19 a2 2 0 0 1 2 2 V17 a2 2 0 0 1 -2 2 H5 a2 2 0 0 1 -2 -2 Z" {fillf}/>
  </svg>`,
  eye: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="{w}" stroke-linecap="{cap}" stroke-linejoin="{join}" {dash}>
    <path d="M2.5 12 C5.5 7 8.5 4.8 12 4.8 C15.5 4.8 18.5 7 21.5 12 C18.5 17 15.5 19.2 12 19.2 C8.5 19.2 5.5 17 2.5 12 Z"/>
    <circle cx="12" cy="12" r="2.8"/>
  </svg>`,
};

// 11 套风格参数：w=描边宽 cap=端帽 join=转角 rx=圆角 rc=强圆角 dash=虚线 fillf=内部填充
const ICON_STYLES = {
  s1:  { w: 1.8, cap: "round", join: "round", rx: 2, rc: 3, dash: "", fillf: "" },                        // 玻璃圆润（默认）
  s2:  { w: 3,   cap: "round", join: "round", rx: 5, rc: 9, dash: "", fillf: 'fill="currentColor" fill-opacity="0.18"' }, // 果冻
  s3:  { w: 1.5, cap: "butt",  join: "miter",  rx: 1, rc: 1, dash: "", fillf: "" },                      // 锐利商务
  s4:  { w: 2,   cap: "square",join: "miter",  rx: 0, rc: 0, dash: 'stroke-dasharray="1.6 1.2"', fillf: "" }, // 赛博机能
  s5:  { w: 3.2, cap: "square",join: "miter",  rx: 0, rc: 0, dash: "", fillf: "" },                      // 复古像素
  s6:  { w: 2.2, cap: "round", join: "round", rx: 7, rc: 12, dash: "", fillf: 'fill="currentColor" fill-opacity="0.10"' }, // 手绘涂鸦
  s7:  { w: 1.2, cap: "round", join: "miter",  rx: 1, rc: 2, dash: "", fillf: "" },                      // 高级商务细线
  s8:  { w: 2.6, cap: "round", join: "round", rx: 4, rc: 7, dash: "", fillf: 'fill="currentColor" fill-opacity="0.15"' }, // 自然有机饱满
  s9:  { w: 1.5, cap: "butt",  join: "miter",  rx: 0, rc: 0, dash: "", fillf: "" },                      // 极简黑白
  s10: { w: 2,   cap: "round", join: "round", rx: 3, rc: 5, dash: "", fillf: 'fill="currentColor" fill-opacity="0.22"' }, // 霓虹光感
  s11: { w: 1.6, cap: "butt",  join: "miter",  rx: 0, rc: 0, dash: 'stroke-dasharray="2.5 1.5"', fillf: "" }, // 模块网格
};

const _cache = {};
function iconSetFor(styleId) {
  if (_cache[styleId]) return _cache[styleId];
  const p = ICON_STYLES[styleId] || ICON_STYLES.s1;
  const set = {};
  const fillattr = p.fillf ? ` fill="${p.fillf.split('"')[1]}" fill-opacity="${p.fillf.split('"')[3]}"` : "";
  Object.entries(ICON_TMPL).forEach(([name, tmpl]) => {
    set[name] = tmpl
      .replaceAll("{w}", p.w)
      .replaceAll("{wc}", (p.w + 0.4).toFixed(1))
      .replaceAll("{cap}", p.cap)
      .replaceAll("{join}", p.join)
      .replaceAll("{rx}", p.rx)
      .replaceAll("{rx1}", p.rc)
      .replaceAll("{dash}", p.dash)
      .replaceAll("{fillf}", fillattr);
  });
  _cache[styleId] = set;
  return set;
}

function icon(name, cls) {
  return `<span class="icon ${cls || ""}">${(ICONS_CUR[name] || "")}</span>`;
}
