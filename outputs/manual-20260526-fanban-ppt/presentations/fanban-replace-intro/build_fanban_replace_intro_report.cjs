const { createRequire } = require("node:module");
const { readFileSync } = require("node:fs");
const { mkdir, writeFile } = require("node:fs/promises");

const requireFromHere = createRequire(__filename);
const {
  Presentation,
  PresentationFile,
  shape,
  text,
  image,
  rule,
  fill,
} = requireFromHere("@oai/artifact-tool");

const ROOT = "E:/project/auto-fanban-pre/outputs/manual-20260526-fanban-ppt/presentations/fanban-replace-intro";
const OUT = process.env.FANBAN_PPT_OUT || `${ROOT}/output/翻版功能模块介绍-最终自检版.pptx`;
const PREVIEW_DIR = `${ROOT}/preview-report`;
const LAYOUT_DIR = `${ROOT}/qa/layout-report`;
const LOGO = `${ROOT}/assets/cnpe-cnnc-logo.png`;
const BUILDING = `${ROOT}/assets/cnpe-building.jpeg`;
const HOME = `${ROOT}/assets/screenshots/frontend-home.png`;
const CONFIG = `${ROOT}/assets/screenshots/frontend-replace-modal-natural.png`;
const REPLACE_TOP = `${ROOT}/assets/screenshots/frontend-replace-job-detail.png`;
const REPLACE_SUMMARY = `${ROOT}/assets/screenshots/frontend-replace-job-summary.png`;
const PACKAGE_TOP = `${ROOT}/assets/screenshots/frontend-task-package-top-crop.png`;
const PDF_PREVIEW = `${ROOT}/assets/screenshots/frontend-pdf-preview-crop.png`;
const TITLE_BLOCK_ROI = `${ROOT}/assets/title-block-roi-user-original.png`;

const W = 1920;
const H = 1080;
const FONT = "Microsoft YaHei";

const C = {
  bg: "#F7F8FA",
  white: "#FFFFFF",
  ink: "#172033",
  muted: "#5C667A",
  quiet: "#7B8497",
  blue: "#004EA2",
  teal: "#53958D",
  red: "#C00000",
  amber: "#D97706",
  line: "#D9DEE8",
  lightBlue: "#E7F0FB",
  lightTeal: "#EAF5F3",
  lightRed: "#FBEAEA",
  lightGold: "#FFF4D8",
};

const imageCache = new Map();

function mimeFor(filePath) {
  const lower = filePath.toLowerCase();
  if (lower.endsWith(".png")) return "image/png";
  if (lower.endsWith(".jpg") || lower.endsWith(".jpeg")) return "image/jpeg";
  return "application/octet-stream";
}

function imageSource(filePath) {
  if (!imageCache.has(filePath)) {
    const mime = mimeFor(filePath);
    const bytes = readFileSync(filePath);
    imageCache.set(filePath, {
      dataUrl: `data:${mime};base64,${bytes.toString("base64")}`,
      contentType: mime,
    });
  }
  return imageCache.get(filePath);
}

function frame(slide, node, left, top, width, height) {
  if (width <= 0 || height <= 0) {
    throw new Error(`Invalid frame ${left},${top},${width},${height}`);
  }
  slide.compose(node, { frame: { left, top, width, height }, baseUnit: 8 });
}

function rect(slide, left, top, width, height, fillColor, opts = {}) {
  frame(
    slide,
    shape({
      name: opts.name || "shape",
      width: fill,
      height: fill,
      fill: fillColor,
      borderRadius: opts.radius,
      line: opts.line,
    }),
    left,
    top,
    width,
    height,
  );
}

function line(slide, left, top, width, color = C.line, weight = 2) {
  frame(
    slide,
    rule({ name: "rule", width: fill, stroke: color, weight }),
    left,
    top,
    width,
    8,
  );
}

function txt(slide, value, left, top, width, height, style = {}, name = "text") {
  frame(
    slide,
    text(value, {
      name,
      width: fill,
      height: fill,
      style: {
        fontFamily: FONT,
        fontSize: 34,
        color: C.ink,
        ...style,
      },
    }),
    left,
    top,
    width,
    height,
  );
}

function img(slide, filePath, left, top, width, height, fit = "contain", alt = "") {
  frame(
    slide,
    image({
      name: "image",
      ...imageSource(filePath),
      width: fill,
      height: fill,
      fit,
      alt,
    }),
    left,
    top,
    width,
    height,
  );
}

function addLogo(slide, cover = false) {
  img(slide, LOGO, cover ? 1410 : 1494, cover ? 8 : 16, 360, 190, "contain", "CNPE logo");
}

function addFooter(slide, _source = "", color = C.quiet) {
  txt(slide, "开发者：王任超", 1620, 1018, 230, 28, {
    fontSize: 18,
    color,
    textAlign: "right",
  }, "footer-developer");
}

function sectionHeader(slide, no, section, claim, sub = "") {
  txt(slide, no, 70, 48, 90, 60, { fontSize: 42, bold: true, color: C.blue }, "section-no");
  txt(slide, section, 170, 48, 500, 60, { fontSize: 40, bold: true, color: C.ink }, "section-title");
  rect(slide, 70, 128, 12, 82, C.blue);
  txt(slide, claim, 100, 112, 1380, 100, { fontSize: 48, bold: true, color: C.ink }, "claim");
  line(slide, 70, 250, 1080, C.blue, 5);
  if (sub) {
    txt(slide, sub, 70, 274, 1280, 58, { fontSize: 28, color: C.muted }, "subtitle");
  }
  addLogo(slide);
}

function card(slide, x, y, w, h, title, body, accent = C.blue, fillColor = C.white) {
  rect(slide, x, y, w, h, fillColor, { radius: "rounded-lg" });
  rect(slide, x, y, 12, h, accent);
  const compact = h <= 170;
  const bodyTop = compact ? (h <= 130 ? 68 : 78) : 98;
  txt(slide, title, x + 34, y + (compact ? 16 : 28), w - 68, compact ? 34 : 50, {
    fontSize: compact ? 28 : 34,
    bold: true,
    color: accent,
  }, "card-title");
  txt(slide, body, x + 34, y + bodyTop, w - 68, Math.max(24, h - bodyTop - 14), {
    fontSize: compact ? 18 : 26,
    color: C.ink,
  }, "card-body");
}

function note(slide, x, y, w, h, label, body, accent = C.blue) {
  rect(slide, x, y, w, h, C.lightBlue, { radius: "rounded-lg" });
  txt(slide, label, x + 28, y + 20, 160, 44, { fontSize: 28, bold: true, color: accent }, "note-label");
  txt(slide, body, x + 196, y + 20, w - 224, h - 34, { fontSize: 25, bold: true, color: C.ink }, "note-body");
}

function metric(slide, x, y, w, h, value, label, accent = C.blue, valueSize = 70) {
  rect(slide, x, y, w, h, C.white, { radius: "rounded-lg" });
  txt(slide, value, x + 28, y + 20, w - 56, 80, { fontSize: valueSize, bold: true, color: accent }, "metric-value");
  txt(slide, label, x + 30, y + 104, w - 60, h - 116, { fontSize: 27, color: C.muted }, "metric-label");
}

function mini(slide, x, y, w, h, title, body, accent = C.blue, fillColor = C.white) {
  rect(slide, x, y, w, h, fillColor, { radius: "rounded-lg" });
  rect(slide, x, y, 10, h, accent);
  txt(slide, title, x + 30, y + 20, w - 54, 34, { fontSize: 25, bold: true, color: accent }, "mini-title");
  txt(slide, body, x + 30, y + 78, w - 54, h - 92, { fontSize: 20, color: C.muted }, "mini-body");
}

function step(slide, x, y, w, h, no, title, body, accent = C.blue, fillColor = C.white) {
  rect(slide, x, y, w, h, fillColor, { radius: "rounded-lg" });
  txt(slide, no, x + 24, y + 24, 58, 44, { fontSize: 32, bold: true, color: accent }, "step-no");
  txt(slide, title, x + 82, y + 28, w - 104, 40, { fontSize: 27, bold: true, color: C.ink }, "step-title");
  txt(slide, body, x + 30, y + 122, w - 60, h - 144, { fontSize: 22, color: C.muted }, "step-body");
}

function arrow(slide, x, y, color = C.blue) {
  txt(slide, "→", x, y, 72, 64, { fontSize: 54, bold: true, color }, "arrow");
}

function screenshot(slide, filePath, x, y, w, h, alt, fit = "cover") {
  rect(slide, x - 10, y - 10, w + 20, h + 20, C.white, { radius: "rounded-lg" });
  rect(slide, x - 10, y - 10, w + 20, h + 20, "transparent", {
    radius: "rounded-lg",
    line: { color: C.line, weight: 2 },
  });
  img(slide, filePath, x, y, w, h, fit, alt);
}

function pill(slide, x, y, label, accent = C.blue, fillColor = C.lightBlue) {
  rect(slide, x, y, 184, 50, fillColor, { radius: "rounded-lg" });
  txt(slide, label, x + 16, y + 12, 152, 28, { fontSize: 22, bold: true, color: accent }, "pill");
}

function table(slide, x, y, cols, rows, colWidths) {
  const rowH = 58;
  const tableW = colWidths.reduce((sum, v) => sum + v, 0);
  rect(slide, x, y, tableW, rowH, C.lightBlue);
  let cx = x;
  cols.forEach((col, i) => {
    txt(slide, col, cx + 18, y + 14, colWidths[i] - 36, 28, { fontSize: 22, bold: true, color: C.blue }, "th");
    cx += colWidths[i];
  });
  rows.forEach((row, r) => {
    const yy = y + rowH * (r + 1);
    rect(slide, x, yy, tableW, rowH, r % 2 === 0 ? C.white : "#F1F5F9");
    let xx = x;
    row.forEach((cell, c) => {
      txt(slide, cell, xx + 18, yy + 12, colWidths[c] - 36, 34, { fontSize: 21, color: c === 0 ? C.ink : C.muted, bold: c === 0 }, "td");
      xx += colWidths[c];
    });
  });
}

async function build() {
  await mkdir(PREVIEW_DIR, { recursive: true });
  await mkdir(LAYOUT_DIR, { recursive: true });
  await mkdir(`${ROOT}/output`, { recursive: true });

  const presentation = Presentation.create({ slideSize: { width: W, height: H } });

  // 01
  {
    const s = presentation.slides.add();
    rect(s, 0, 0, W, H, C.bg);
    rect(s, 0, 0, 18, H, C.blue);
    img(s, BUILDING, 1320, 0, 600, H, "cover", "CNPE Hebei Branch building");
    rect(s, 1320, 0, 600, H, "rgba(0,78,162,0.34)");
    addLogo(s, true);
    txt(s, "翻版功能模块介绍", 96, 150, 920, 96, { fontSize: 72, bold: true, color: C.ink }, "cover-title");
    txt(s, "旧项目 DWG 到目标项目 DWG 的批量翻版链路", 96, 264, 1000, 64, { fontSize: 36, bold: true, color: C.blue }, "cover-subtitle");
    line(s, 96, 350, 760, C.blue, 5);
    txt(s, "目录", 96, 402, 220, 54, { fontSize: 40, bold: true, color: C.ink }, "toc-heading");
    const toc = [
      ["01", "模块定位"],
      ["02", "配置窗口"],
      ["03", "接口设计"],
      ["04", "后端流程"],
      ["05", "图签 ROI"],
      ["06", "规则配置"],
      ["07", "执行证据"],
      ["08", "替换摘要"],
      ["09", "出图联动"],
      ["10", "验收方式"],
    ];
    toc.forEach(([no, label], i) => {
      const col = i < 5 ? 0 : 1;
      const row = i % 5;
      const x = 96 + col * 500;
      const y = 486 + row * 78;
      const accent = [C.blue, C.teal, C.red, C.amber, C.blue][row];
      rect(s, x, y, 360, 58, "rgba(255,255,255,0.86)", { radius: "rounded-lg" });
      rect(s, x, y, 8, 58, accent);
      txt(s, no, x + 22, y + 10, 58, 34, { fontSize: 25, bold: true, color: accent }, "toc-no");
      txt(s, label, x + 86, y + 10, 240, 34, { fontSize: 25, bold: true, color: accent }, "toc-label");
    });
    txt(s, "汇报版 | 2026-05-26", 96, 928, 420, 34, { fontSize: 20, color: C.quiet }, "date");
    addFooter(s, "", C.white);
  }

  // 02
  {
    const s = presentation.slides.add();
    rect(s, 0, 0, W, H, C.bg);
    sectionHeader(s, "01", "模块定位", "翻版入口进入业务工作台，运行状态前置校验", "业务人员从同一入口选择出图、纠错和翻版，系统状态在提交前可见。");
    screenshot(s, HOME, 82, 372, 900, 512, "业务首页与新建任务入口");
    card(s, 1040, 360, 360, 170, "入口位置", "业务模块 / 新建任务 / 翻版。入口与出图、纠错并列，减少跨模块切换。", C.blue);
    card(s, 1430, 360, 360, 170, "运行前置", "服务、存储、队列、CAD 与办公组件状态在首页展示，降低提交前不确定性。", C.teal);
    card(s, 1040, 562, 360, 170, "任务承接", "可独立生成 replaced.dwg、report.xlsx，也可进入交付链路", C.red);
    card(s, 1430, 562, 360, 170, "后续流转", "翻版完成后进入任务详情、下载区和出图链路，保持同一套任务模型。", C.amber);
    note(s, 1040, 760, 750, 94, "定位", "翻版不是单独工具页，而是 CAD 批处理平台中的项目迁移子能力。", C.blue);
    addFooter(s);
  }

  // 03
  {
    const s = presentation.slides.add();
    rect(s, 0, 0, W, H, C.bg);
    sectionHeader(s, "02", "配置窗口", "源项目、目标项目和 DWG 文件组设计", "窗口保留可执行字段，项目号、岛号、执行模式和 DWG 文件组直接对应后端参数。");
    screenshot(s, CONFIG, 80, 360, 1120, 630, "翻版配置窗口");
    card(s, 1260, 350, 520, 136, "文件组", "支持批量 DWG；当前配置上限为 50 个文件、总大小 2048 MB。", C.blue);
    card(s, 1260, 504, 520, 136, "执行模式", "仅翻版：直接生成替换后 DWG 与报告。同步出图和翻版：先翻版，再进入交付配置。", C.teal);
    card(s, 1260, 658, 520, 136, "项目映射", "原始项目与目标项目明确表达迁移方向；机组/岛号用于项目内分支。", C.red);
    card(s, 1260, 812, 520, 136, "推荐选项", "项目号列表来自运行期配置，避免前端固化业务词表。", C.amber);
    addFooter(s);
  }

  // 04
  {
    const s = presentation.slides.add();
    rect(s, 0, 0, W, H, C.bg);
    sectionHeader(s, "03", "接口设计", "一次提交同时表达翻版方向、文件组和后续联动", "前端只组织参数和文件，词库、扫描和 CAD 写回均由后端流程处理。");
    mini(s, 86, 366, 410, 172, "创建接口", "以表单方式提交 DWG 文件组、原始项目、目标项目和机组/岛号。", C.blue, C.white);
    mini(s, 530, 366, 410, 172, "仅翻版", "创建独立翻版任务，结果产物为替换后 DWG、报告表与摘要数据。", C.teal, C.white);
    mini(s, 974, 366, 410, 172, "翻版后出图", "翻版配置进入出图草稿；联动标志进入任务包和交付配置。", C.red, C.white);
    mini(s, 1418, 366, 410, 172, "统一返回", "创建结果回到批次或任务包结构，任务卡片、详情页、下载区复用同一模型。", C.amber, C.white);
    table(s, 110, 600, ["提交内容", "业务含义", "后端处理"], [
      ["DWG 文件组", "待翻版图纸", "批处理输入"],
      ["原始项目号", "被迁移的项目口径", "词库原始值列"],
      ["原始机组/岛号", "源项目内分支", "索引图与项目分支"],
      ["目标项目号", "迁移后的项目口径", "词库目标值列"],
      ["目标机组/岛号", "目标项目内分支", "索引图与交付联动"],
    ], [300, 610, 620]);
    rect(s, 110, 958, 1420, 50, C.lightBlue, { radius: "rounded-lg" });
    txt(s, "分工：前端不推断替换词、不展开 CAD 块规则，只负责提交完整的业务参数和文件组。", 136, 970, 1360, 28, {
      fontSize: 24,
      bold: true,
      color: C.ink,
    }, "contract-boundary");
    addFooter(s);
  }

  // 05
  {
    const s = presentation.slides.add();
    rect(s, 0, 0, W, H, C.bg);
    sectionHeader(s, "04", "后端流程", "翻版先扫描残留，再按映射回写；不是简单字符串替换", "扫描上下文、实体定位标识和替换报告来自同一条处理流程。");
    const flow = [
      ["01", "DWG 转换", "ODA 转 DXF，提取图框、图签、布局上下文。", C.blue, C.lightBlue],
      ["02", ".NET 扫描", "识别普通文字、属性文字和块内文字，保留实体定位标识。", C.teal, C.lightTeal],
      ["03", "命中归类", "按目标项目规则找源项目残留，形成可追溯命中列表。", C.red, C.lightRed],
      ["04", "映射回写", "按词库目标值写回实体文本，并记录跳过原因。", C.amber, C.lightGold],
      ["05", "索引图", "厂房索引图按项目/岛号规则替换专项字段。", C.blue, C.white],
      ["06", "输出报告", "生成替换后 DWG、报告表和摘要数据。", C.teal, C.white],
    ];
    flow.forEach((item, i) => {
      const x = 70 + i * 298;
      step(s, x, 380, 250, 300, item[0], item[1], item[2], item[3], item[4]);
      if (i < flow.length - 1) arrow(s, x + 258, 500, item[3]);
    });
    note(s, 100, 760, 1680, 88, "关键机制", "扫描、匹配、写回和报告使用同一实体上下文，后续纠错可验证目标项目残留是否已经消除。", C.teal);
    mini(s, 100, 862, 520, 120, "匹配", "空白归一化覆盖项目名断字、空格和机组号间隔不一致的情况。", C.blue, C.white);
    mini(s, 700, 862, 520, 120, "跳过", "未命中、无目标词、不可写实体等情况写入报告，便于人工复核。", C.amber, C.white);
    mini(s, 1300, 862, 480, 120, "失败", ".NET 扫描失败需要向 Python 链路传播，不能返回伪零错误。", C.red, C.white);
    addFooter(s);
  }

  // 06
  {
    const s = presentation.slides.add();
    rect(s, 0, 0, W, H, C.bg);
    sectionHeader(s, "05", "图签 ROI", "直接在图签原图上标注可替换字段和日期跳过区域", "");
    screenshot(s, TITLE_BLOCK_ROI, 76, 292, 1050, 768, "图签 ROI 可替换区域与日期排除区域", "contain");
    card(s, 1200, 330, 590, 140, "绿色标注", "项目名称、工程号、图号、图纸编号等业务字段参与翻版。", C.teal);
    card(s, 1200, 500, 590, 140, "红色标注", "版次日期、出版日期和日期型标注保持原值。", C.red);
    card(s, 1200, 670, 590, 140, "替换样例", "业务字段按来源项目到目标项目迁移；日期字段不跟随项目号变化。", C.blue);
    card(s, 1200, 840, 590, 118, "验收重点", "抽查绿色区域已迁移，红色日期仍与原图一致。", C.amber);
    addFooter(s);
  }

  // 06
  {
    const s = presentation.slides.add();
    rect(s, 0, 0, W, H, C.bg);
    sectionHeader(s, "06", "规则配置", "词库、范围和索引图规则统一配置", "YAML 与索引图规则共同决定可替换范围，前后端只读取配置结果。");
    table(s, 128, 370, ["配置内容", "当前职责", "使用位置"], [
      ["词库映射", "原始词条与目标词条映射", "文本替换与摘要统计"],
      ["扫描范围", "图纸号、专业、阶段过滤", "扫描前置过滤"],
      ["机组/岛号规则", "项目号与岛号/机组号规则", "索引图与迁移方向"],
      ["报告模板目录", "报告与产物模板目录", "输出包与报告表"],
      ["厂房索引图规则", "厂房索引图特殊替换", "索引图替换桥接"],
      ["前端项目号选项", "前端可选项目号", "翻版配置窗口"],
    ], [360, 560, 620]);
    card(s, 128, 798, 490, 142, "空白归一化", "项目名、机组号、岛号在 DWG 中可能被拆字或插入空格，匹配前需要归一化。", C.blue);
    card(s, 700, 798, 490, 142, "块内文字", "扫描和替换必须覆盖块文本与嵌套块文本，否则图签与索引图容易漏替。", C.teal);
    card(s, 1272, 798, 490, 142, "配置优先", "新增项目、词条和索引图规则应进入 YAML/规则表，而不是散落在前端或业务代码。", C.red);
    addFooter(s);
  }

  // 07
  {
    const s = presentation.slides.add();
    rect(s, 0, 0, W, H, C.bg);
    sectionHeader(s, "07", "执行证据", "真实翻版任务已经产出 report.xlsx 与替换后 DWG", "任务详情页呈现任务类型、进度、完成时间和可下载产物。");
    screenshot(s, REPLACE_TOP, 80, 350, 980, 556, "翻版任务详情页");
    metric(s, 1120, 350, 250, 150, "100%", "翻版任务进度", C.blue, 58);
    metric(s, 1410, 350, 250, 150, "2", "核心下载项", C.teal, 58);
    card(s, 1120, 526, 540, 146, "下载项", "下载 report.xlsx；下载替换后 DWG。两个按钮来自真实任务详情页。", C.blue);
    card(s, 1120, 700, 540, 146, "任务状态", "任务类型为翻版，当前阶段为翻版完成，状态说明为翻版任务已完成。", C.teal);
    card(s, 1120, 874, 540, 108, "样例任务", "20162KA-JGS03-A.dwg：2016 源项目迁移到 2026 目标项目。", C.red);
    addFooter(s);
  }

  // 08
  {
    const s = presentation.slides.add();
    rect(s, 0, 0, W, H, C.bg);
    sectionHeader(s, "08", "替换摘要", "摘要页集中呈现替换数量、图纸影响和复核重点", "报告之外，详情页直接展示高频替换文本和关键图纸编码。");
    screenshot(s, REPLACE_SUMMARY, 80, 350, 1080, 608, "翻版摘要与高频替换文本");
    metric(s, 1220, 350, 250, 150, "95", "替换数量", C.blue, 62);
    metric(s, 1510, 350, 250, 150, "15", "受影响图纸数", C.red, 62);
    metric(s, 1220, 540, 250, 150, "2016", "源项目号", C.teal, 62);
    metric(s, 1510, 540, 250, 150, "2026", "目标项目号", C.amber, 62);
    card(s, 1220, 720, 540, 138, "复核重点", "高频文本包含项目号、厂名、设计参数编号和图纸编码，适合作为人工抽检入口。", C.blue);
    card(s, 1220, 882, 540, 100, "索引图", "厂房索引图替换在同一任务中记录执行结果。", C.teal);
    addFooter(s);
  }

  // 09
  {
    const s = presentation.slides.add();
    rect(s, 0, 0, W, H, C.bg);
    sectionHeader(s, "09", "出图联动", "同一工作台承接任务包、下载区和后续复核动作", "翻版与交付共享任务详情页模式，便于把替换结果继续送入出图链路。");
    screenshot(s, PACKAGE_TOP, 70, 354, 860, 456, "任务包详情与快捷下载");
    screenshot(s, PDF_PREVIEW, 990, 354, 820, 456, "纠错标注 PDF 预览窗口");
    card(s, 92, 858, 520, 118, "任务包下载", "下载任务包、IED、report.xlsx，形成完整交付物。", C.blue);
    card(s, 702, 858, 520, 118, "预览复核", "PDF 预览支持纠错标注查看，便于确认残留文本位置。", C.red);
    card(s, 1312, 858, 470, 118, "联动方式", "翻版独立产物进入交付后沿用任务包下载区。", C.teal);
    addFooter(s);
  }

  // 10
  {
    const s = presentation.slides.add();
    rect(s, 0, 0, W, H, C.bg);
    img(s, BUILDING, 1320, 0, 600, H, "cover", "CNPE Hebei Branch building");
    rect(s, 1320, 0, 600, H, "rgba(0,78,162,0.34)");
    rect(s, 0, 0, 18, H, C.blue);
    rect(s, 1260, 0, 60, H, C.blue);
    addLogo(s, true);
    txt(s, "10", 84, 48, 90, 60, { fontSize: 42, bold: true, color: C.blue }, "section-no");
    txt(s, "验收方式", 184, 48, 360, 60, { fontSize: 40, bold: true, color: C.ink }, "section-title");
    rect(s, 84, 128, 12, 82, C.blue);
    txt(s, "四类证据完成验收：DWG、报告、产物、回归", 112, 112, 1080, 100, {
      fontSize: 48,
      bold: true,
      color: C.ink,
    }, "closing-title");
    line(s, 84, 254, 980, C.blue, 5);
    card(s, 112, 344, 1020, 110, "替换后 DWG", "replaced.dwg 可下载，文件名与任务记录口径一致。", C.blue);
    card(s, 112, 474, 1020, 110, "报告摘要", "report.xlsx 与详情页摘要能说明替换数量、受影响图纸和跳过原因。", C.teal);
    card(s, 112, 604, 1020, 110, "详情页产物", "任务详情页展示阶段、进度、完成时间和下载入口。", C.amber);
    card(s, 112, 734, 1020, 110, "回归纠错", "用目标项目口径再跑纠错，确认源项目残留文本已经消除。", C.red);
    card(s, 112, 864, 1020, 110, "主要风险", "真实 CAD 环境、模板覆盖、缺失目标词条和块内特殊实体仍决定批量稳定性。", C.red);
    addFooter(s);
  }

  const pptx = await PresentationFile.exportPptx(presentation);
  await pptx.save(OUT);

  for (let i = 0; i < presentation.slides.count; i += 1) {
    const slide = presentation.slides.getItem(i);
    const png = await slide.export({ format: "png" });
    await writeFile(
      `${PREVIEW_DIR}/preview-${String(i + 1).padStart(2, "0")}.png`,
      new Uint8Array(await png.arrayBuffer()),
    );
    const layout = await slide.export({ format: "layout" });
    await writeFile(
      `${LAYOUT_DIR}/layout-${String(i + 1).padStart(2, "0")}.json`,
      new Uint8Array(await layout.arrayBuffer()),
    );
  }

  console.log(JSON.stringify({
    pptx: OUT,
    slides: presentation.slides.count,
    previews: `${PREVIEW_DIR}/preview-*.png`,
    layouts: `${LAYOUT_DIR}/layout-*.json`,
  }, null, 2));
}

build().catch((error) => {
  console.error(error);
  process.exit(1);
});
