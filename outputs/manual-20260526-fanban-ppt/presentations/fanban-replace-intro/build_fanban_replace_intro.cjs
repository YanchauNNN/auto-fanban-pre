const { createRequire } = require("node:module");
const { readFileSync } = require("node:fs");
const { mkdir, writeFile } = require("node:fs/promises");
const path = require("node:path");

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
const OUT = `${ROOT}/output/翻版功能模块介绍-可编辑版.pptx`;
const PREVIEW_DIR = `${ROOT}/preview`;
const LAYOUT_DIR = `${ROOT}/qa/layout`;
const LOGO = `${ROOT}/assets/cnpe-cnnc-logo.png`;
const BUILDING = `${ROOT}/assets/cnpe-building.jpeg`;

const W = 1920;
const H = 1080;

const C = {
  bg: "#F7F8FA",
  white: "#FFFFFF",
  ink: "#172033",
  muted: "#5C667A",
  quiet: "#7B8497",
  blue: "#004EA2",
  blue2: "#1F5EFF",
  deep: "#253682",
  slate: "#2B4A57",
  teal: "#53958D",
  teal2: "#00A88B",
  red: "#C00000",
  risk: "#B42318",
  amber: "#D97706",
  gold: "#FFC000",
  line: "#D9DEE8",
  lightBlue: "#E7F0FB",
  lightTeal: "#EAF5F3",
  lightRed: "#FBEAEA",
  lightGold: "#FFF4D8",
  pale: "#EEF3F8",
};

const FONT = "Microsoft YaHei";
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
        fontSize: 24,
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

function addLogo(slide, mode = "content") {
  if (mode === "cover") {
    img(slide, LOGO, 1420, 6, 360, 190, "contain", "CNPE logo");
  } else {
    img(slide, LOGO, 1500, 16, 360, 190, "contain", "CNPE logo");
  }
}

function addFooter(slide, source = "资料来源：本项目代码与文档；PPT制作规则参考 Microsoft Support、Harvard Catalyst、UCSD、Duarte。") {
  txt(slide, "中国核电工程有限公司河北分公司 | auto-fanban-pre 翻版功能模块介绍", 70, 1018, 780, 30, {
    fontSize: 13,
    color: C.quiet,
  }, "footer-left");
  txt(slide, source, 870, 1018, 980, 30, {
    fontSize: 12,
    color: C.quiet,
    align: "right",
  }, "footer-source");
}

function addHeader(slide, sectionNo, sectionTitle, claim, sub = "", titleSize = 38) {
  rect(slide, 0, 0, W, H, C.bg);
  rect(slide, 0, 0, 16, H, C.blue);
  txt(slide, sectionNo, 70, 42, 80, 52, {
    fontSize: 34,
    bold: true,
    color: C.blue,
  }, "section-no");
  txt(slide, sectionTitle, 160, 42, 460, 52, {
    fontSize: 32,
    bold: true,
    color: C.ink,
  }, "section-title");
  rect(slide, 70, 112, 10, 62, C.blue);
  txt(slide, claim, 96, 102, 1260, 82, {
    fontSize: titleSize,
    bold: true,
    color: C.ink,
  }, "slide-title");
  line(slide, 70, 194, 1110, C.blue, 4);
  if (sub) {
    txt(slide, sub, 70, 220, 1320, 52, {
      fontSize: 24,
      color: C.muted,
    }, "slide-subtitle");
  }
  addLogo(slide);
}

function card(slide, x, y, w, h, title, body, accent = C.blue, fillColor = C.white) {
  rect(slide, x, y, w, h, fillColor, { radius: "rounded-lg" });
  rect(slide, x, y, 12, h, accent);
  txt(slide, title, x + 34, y + 24, w - 68, 44, {
    fontSize: 28,
    bold: true,
    color: accent,
  }, "card-title");
  txt(slide, body, x + 34, y + 84, w - 68, h - 106, {
    fontSize: 22,
    color: C.ink,
  }, "card-body");
}

function metric(slide, x, y, w, h, value, label, accent = C.blue, valueSize = 54) {
  rect(slide, x, y, w, h, C.white, { radius: "rounded-lg" });
  txt(slide, value, x + 26, y + 18, w - 52, 70, {
    fontSize: valueSize,
    bold: true,
    color: accent,
  }, "metric-value");
  txt(slide, label, x + 28, y + 96, w - 56, h - 110, {
    fontSize: 21,
    color: C.muted,
  }, "metric-label");
}

function bullet(slide, x, y, value, color = C.blue, width = 720, fs = 22) {
  rect(slide, x, y + 13, 12, 12, color, { radius: "rounded-full" });
  txt(slide, value, x + 28, y, width, 54, {
    fontSize: fs,
    color: C.ink,
  }, "bullet");
}

function tag(slide, x, y, w, label, fillColor, color = C.blue, fs = 20) {
  rect(slide, x, y, w, 48, fillColor, { radius: "rounded-full" });
  txt(slide, label, x + 18, y + 9, w - 36, 32, {
    fontSize: fs,
    bold: true,
    color,
    align: "center",
  }, "tag");
}

function conclusionBand(slide, x, y, w, h, lead, body, accent = C.blue) {
  rect(slide, x, y, w, h, "#EAF1FA");
  rect(slide, x, y, 12, h, accent);
  txt(slide, lead, x + 28, y + 18, 170, h - 28, {
    fontSize: 22,
    bold: true,
    color: accent,
  }, "band-lead");
  txt(slide, body, x + 210, y + 18, w - 240, h - 28, {
    fontSize: 21,
    bold: true,
    color: C.ink,
  }, "band-body");
}

function arrow(slide, x, y, color = C.blue) {
  txt(slide, "→", x, y, 42, 42, {
    fontSize: 32,
    bold: true,
    color,
    align: "center",
  }, "flow-arrow");
}

function miniStep(slide, x, y, w, h, no, title, body, accent = C.blue, fillColor = C.white) {
  rect(slide, x, y, w, h, fillColor, { radius: "rounded-lg" });
  txt(slide, no, x + 20, y + 18, 54, 44, {
    fontSize: 27,
    bold: true,
    color: accent,
  }, "step-no");
  txt(slide, title, x + 76, y + 22, w - 96, 40, {
    fontSize: 24,
    bold: true,
    color: C.ink,
  }, "step-title");
  txt(slide, body, x + 24, y + 80, w - 48, h - 94, {
    fontSize: 19,
    color: C.muted,
  }, "step-body");
}

function tableRow(slide, x, y, widths, cells, fillColor, emphIndex = -1) {
  let cx = x;
  cells.forEach((cell, index) => {
    rect(slide, cx, y, widths[index], 62, fillColor, {
      line: { color: C.white, weight: 2 },
    });
    txt(slide, cell, cx + 14, y + 16, widths[index] - 28, 32, {
      fontSize: index === emphIndex ? 22 : 20,
      bold: index === emphIndex,
      color: index === emphIndex ? C.blue : C.ink,
      align: index === 0 ? "center" : "left",
    }, "table-cell");
    cx += widths[index];
  });
}

async function build() {
  await mkdir(path.dirname(OUT), { recursive: true });
  await mkdir(PREVIEW_DIR, { recursive: true });
  await mkdir(LAYOUT_DIR, { recursive: true });

  const presentation = Presentation.create({
    slideSize: { width: W, height: H },
  });

  // 1. Cover
  {
    const s = presentation.slides.add();
    rect(s, 0, 0, W, H, C.bg);
    img(s, BUILDING, 1180, 0, 740, H, "cover", "CNPE Hebei Branch building");
    rect(s, 1136, 0, 70, H, C.blue);
    rect(s, 1206, 0, 714, H, "rgba(0,78,162,0.22)");
    rect(s, 0, 0, 16, H, C.blue);
    addLogo(s, "cover");
    txt(s, "翻版功能模块介绍", 118, 220, 780, 74, {
      fontSize: 48,
      bold: true,
      color: C.ink,
    }, "cover-title");
    txt(s, "把既有 DWG 从来源项目口径迁移到目标项目口径", 118, 318, 910, 92, {
      fontSize: 34,
      bold: true,
      color: C.blue,
    }, "cover-subtitle");
    line(s, 118, 444, 820, C.blue, 5);
    txt(s, "基于纠错扫描底座、词库映射、厂房索引图模板和交付出图链路，形成可下载、可追溯、可回归验证的翻版任务。", 118, 500, 850, 120, {
      fontSize: 24,
      color: C.muted,
    }, "cover-copy");
    metric(s, 118, 696, 250, 142, "1 个", "统一任务入口", C.blue, 50);
    metric(s, 406, 696, 250, 142, "2 种", "仅翻版 / 翻版出图", C.teal, 50);
    metric(s, 694, 696, 250, 142, "7 套", "正式索引图模板", C.red, 50);
    txt(s, "汇报对象：项目维护与功能评审 | 日期：2026-05-26", 118, 935, 860, 36, {
      fontSize: 18,
      color: C.quiet,
    }, "cover-date");
  }

  // 2. Problem
  {
    const s = presentation.slides.add();
    addHeader(s, "01", "业务问题", "翻版要解决的不是单词替换，而是批量图纸口径迁移的风险控制", "项目号、厂房码、图签、块内文字和索引图都可能影响最终 DWG 的可交付性", 36);
    card(s, 96, 320, 500, 300, "人工翻版容易漏改", "同一批 DWG 中可能存在项目号、项目名称、内部编码、图签字段和块属性文本；仅靠人工查找难以覆盖嵌套块和属性文本。", C.blue, C.white);
    card(s, 710, 320, 500, 300, "规则不能写死在前端", "来源项目与目标项目不同，2016/1916 还要区分机组或岛号；词库、模板和豁免规则需要随运行期配置调整。", C.teal, C.white);
    card(s, 1324, 320, 500, 300, "翻版后还要能继续出图", "用户可能只需要 replaced.dwg，也可能要求翻版后直接进入交付处理；任务产物和状态必须和原有出图链路兼容。", C.red, C.white);
    conclusionBand(s, 120, 736, 1680, 82, "设计判断", "翻版模块应复用后端 CAD 扫描和任务体系，由后端识别、替换、报告和串联出图，前端只提交清晰的业务意图。", C.blue);
    addFooter(s, "资料来源：documents/翻版模块前端接入指导.md、documents/参数规范.yaml。");
  }

  // 3. Capability baseline
  {
    const s = presentation.slides.add();
    addHeader(s, "02", "能力现状", "现有后端已经具备可运行 MVP，统一接口同时承载纠错与翻版", "接口保持 multipart/form-data，任务详情回传 replaced.dwg、report.xlsx 和替换摘要", 36);
    metric(s, 96, 316, 330, 154, "POST", "/api/jobs/audit-replace", C.blue, 48);
    metric(s, 466, 316, 330, 154, "check", "纠错扫描模式", C.teal, 48);
    metric(s, 836, 316, 330, 154, "replace", "翻版替换模式", C.red, 48);
    metric(s, 1206, 316, 330, 154, "group", "翻版后串联出图", C.amber, 48);
    const rows = [
      ["入参", "source_project_no / target_project_no / run_deliverable", "决定来源列、目标列和是否进入交付主链"],
      ["产物", "replaced.dwg / report.xlsx", "单任务完成后可直接下载翻版 DWG 与替换报告"],
      ["摘要", "replacement_count / affected_drawings_count", "任务详情可展示替换数量、受影响图纸和高频替换文本"],
      ["记录", "2026 -> 2016 后再纠错 findings_count = 0", "前端接入文档记录了真实后端烟测口径"],
    ];
    tableRow(s, 120, 560, [150, 640, 790], ["层面", "当前能力", "说明"], C.lightBlue, 1);
    rows.forEach((row, i) => tableRow(s, 120, 624 + i * 66, [150, 640, 790], row, i % 2 === 0 ? C.white : "#F1F5FA", 1));
    conclusionBand(s, 120, 918, 1680, 66, "交付口径", "这份 PPT 按现有代码和文档说明当前能力，不把未开放的块替换配置 UI 写成已上线交互。", C.red);
    addFooter(s, "资料来源：documents/翻版模块前端接入指导.md、API/app/runtime.py、frontend/src/platform/api/httpAdapter.ts。");
  }

  // 4. Backend mechanism
  {
    const s = presentation.slides.add();
    addHeader(s, "03", "后端机制", "系统先按目标项目发现异源文本，再按词库映射回写 CAD 实体", "翻版不是盲替换；命中、上下文、entity handle 和替换报告都来自后端主链", 36);
    const steps = [
      ["01", "DWG 转 DXF", "通过 ODA 得到可处理 DXF，并提取图框和图签上下文。", C.blue, C.lightBlue],
      ["02", ".NET 扫描", "扫描 TEXT、MTEXT、ATTRIB 等实体，保留 entity handle 与块路径。", C.teal, C.lightTeal],
      ["03", "目标纠错", "用目标项目规则识别来源项目残留文本，获得待处理 findings。", C.red, C.lightRed],
      ["04", "映射回写", "按词库 source 列到 target 列映射，逐 handle 更新 DXF 文本。", C.amber, C.lightGold],
      ["05", "导出产物", "转回 DWG，写 report.json/report.xlsx 和任务 progress 摘要。", C.blue, C.white],
    ];
    steps.forEach((step, i) => {
      const x = 86 + i * 356;
      miniStep(s, x, 332, 288, 240, step[0], step[1], step[2], step[3], step[4]);
      if (i < steps.length - 1) arrow(s, x + 302, 424, step[3]);
    });
    rect(s, 120, 668, 760, 190, C.white, { radius: "rounded-lg" });
    txt(s, "实体级回写边界", 152, 704, 280, 42, { fontSize: 27, bold: true, color: C.blue }, "box-title");
    bullet(s, 156, 766, "只对 TEXT、MTEXT、ATTRIB、ATTDEF 等支持实体执行文本更新。", C.blue, 640, 21);
    bullet(s, 156, 816, "没有 handle、找不到实体、没有目标词条时进入 skipped 状态。", C.red, 640, 21);
    rect(s, 970, 668, 760, 190, C.white, { radius: "rounded-lg" });
    txt(s, "结果可追踪", 1002, 704, 240, 42, { fontSize: 27, bold: true, color: C.teal }, "box-title");
    bullet(s, 1006, 766, "报告记录 matched_text、replacement_text、raw_text、new_text。", C.teal, 640, 21);
    bullet(s, 1006, 816, "摘要保留替换数量、跳过数量、受影响图纸和高频文本。", C.blue, 640, 21);
    conclusionBand(s, 120, 910, 1680, 66, "关键价值", "扫描结果和替换行为共享同一套上下文，后续纠错回归能验证翻版是否真正消除了目标项目下的残留问题。", C.blue);
    addFooter(s, "资料来源：backend/src/audit_replace/executor.py、backend/src/audit_replace/reporting.py。");
  }

  // 5. Configured rules
  {
    const s = presentation.slides.add();
    addHeader(s, "04", "规则配置", "词库和 YAML 让翻版规则可配置，而不是硬编码在替换逻辑里", "项目列、参与行、机组一致性和索引图模板都来自运行期配置", 36);
    rect(s, 110, 316, 620, 420, C.white, { radius: "rounded-lg" });
    txt(s, "词库映射", 146, 352, 220, 44, { fontSize: 30, bold: true, color: C.blue }, "mapping-title");
    tableRow(s, 150, 424, [160, 180, 180], ["行", "来源列", "目标列"], C.lightBlue, 1);
    tableRow(s, 150, 488, [160, 180, 180], ["1", "2026", "2016"], C.white, 1);
    tableRow(s, 150, 552, [160, 180, 180], ["2", "徐圩", "金七门"], "#F1F5FA", 1);
    tableRow(s, 150, 616, [160, 180, 180], ["3+", "XZ", "JD"], C.white, 1);
    txt(s, "同值词条进入 no_op，目标列为空进入 missing_target，报告里可追踪。", 146, 690, 520, 42, { fontSize: 20, color: C.muted }, "mapping-note");
    rect(s, 820, 316, 900, 420, C.white, { radius: "rounded-lg" });
    txt(s, "运行期配置", 856, 352, 220, 44, { fontSize: 30, bold: true, color: C.teal }, "config-title");
    const configs = [
      ["audit_check.lexicon_path", "documents_bin\\词库收集.xlsx"],
      ["include_rows", "[1, 2, \"3+\"]"],
      ["project_column_header_pattern", "^\\d{4}$"],
      ["unit_consistency.project_units", "1916/1907/1418/2026 等项目机组"],
      ["factory_index_maps.template_dir", "documents_bin\\factory_index_maps"],
    ];
    configs.forEach((row, i) => {
      const y = 424 + i * 58;
      txt(s, row[0], 864, y, 360, 34, { fontSize: 20, bold: true, color: C.ink }, "config-key");
      txt(s, row[1], 1240, y, 430, 34, { fontSize: 20, color: C.muted }, "config-val");
      line(s, 856, y + 42, 810, C.line, 1);
    });
    tag(s, 148, 804, 360, "支持空格归一化匹配", C.lightBlue, C.blue);
    tag(s, 548, 804, 360, "支持 no-op 与缺失目标词追踪", C.lightTeal, C.teal);
    tag(s, 948, 804, 360, "支持机组/岛号条件校验", C.lightGold, C.amber);
    tag(s, 1348, 804, 360, "支持模板目录配置", C.lightRed, C.red);
    conclusionBand(s, 120, 918, 1680, 66, "治理方式", "机制参数保留在 YAML 和词库中，方便业务人员扩展项目映射，也避免把可变规则散落到替换代码里。", C.teal);
    addFooter(s, "资料来源：documents/参数规范_运行期.yaml、backend/src/audit_replace/mapping.py、backend/tests/unit/test_audit_replace_executor.py。");
  }

  // 6. Factory index maps
  {
    const s = presentation.slides.add();
    addHeader(s, "05", "索引图替换", "厂房索引图已经从文字替换扩展到块级模板替换", "后端识别源图索引图块，按目标项目模板生成替换计划，再由 .NET Bridge 执行", 36);
    rect(s, 104, 314, 520, 470, C.white, { radius: "rounded-lg" });
    txt(s, "模板覆盖", 142, 350, 220, 44, { fontSize: 30, bold: true, color: C.blue }, "template-title");
    const templateRows = [
      ["1818", "1818项目厂房索引图.dwg"],
      ["1907", "1907项目厂房索引图.dwg"],
      ["2026", "2026项目厂房索引图.dwg"],
      ["1916", "3号岛 / 4号岛模板"],
      ["2016", "1号岛 / 2号岛模板"],
    ];
    templateRows.forEach((row, i) => {
      tag(s, 146, 424 + i * 62, 112, row[0], i < 3 ? C.lightBlue : C.lightGold, i < 3 ? C.blue : C.amber, 19);
      txt(s, row[1], 284, 432 + i * 62, 300, 36, { fontSize: 20, color: C.ink }, "template-file");
    });
    rect(s, 724, 314, 520, 470, C.white, { radius: "rounded-lg" });
    txt(s, "源块识别", 762, 350, 220, 44, { fontSize: 30, bold: true, color: C.teal }, "detect-title");
    bullet(s, 766, 426, "角度文字与圆形罗盘形成候选锚点。", C.teal, 410, 21);
    bullet(s, 766, 488, "候选必须来自可替换块，保留 insert handle 和 bbox。", C.blue, 410, 21);
    bullet(s, 766, 550, "2016 来源按 QF 区分 1/2，1916 来源按 KP 区分 3/4。", C.amber, 410, 21);
    bullet(s, 766, 612, "没有候选、模板缺失、岛号缺失时返回 message。", C.red, 410, 21);
    rect(s, 1344, 314, 420, 470, C.white, { radius: "rounded-lg" });
    txt(s, "执行边界", 1382, 350, 220, 44, { fontSize: 30, bold: true, color: C.red }, "bridge-title");
    miniStep(s, 1386, 424, 300, 122, "A", "生成计划", "source bounds、template bounds、scale 与 action_id。", C.red, C.lightRed);
    miniStep(s, 1386, 578, 300, 122, "B", "Bridge 执行", "AcCoreConsole 加载 .NET Bridge 执行块替换。", C.blue, C.lightBlue);
    conclusionBand(s, 120, 902, 1680, 82, "模块边界", "前端不读取模板、不解析 DWG、不实现块替换；只提交 source_island_no / target_island_no，模板选择与 CAD 执行留在后端。", C.red);
    addFooter(s, "资料来源：documents/厂房索引图替换前端接入指导.md、backend/src/audit_replace/factory_index_maps.py。");
  }

  // 7. User flow
  {
    const s = presentation.slides.add();
    addHeader(s, "06", "用户交互", "前端只提交业务意图，任务体系负责组织翻版、下载和联动出图", "当前实现已经在 HttpAdapter 中按 mode=replace 组装 params_json 并解析任务详情", 35);
    const flow = [
      ["选择来源", "source_project_no\nsource_island_no"],
      ["选择目标", "target_project_no\ntarget_island_no"],
      ["选择方式", "仅翻版\n同步出图和翻版"],
      ["上传 DWG", "files[]"],
      ["下载结果", "replaced.dwg\nreport.xlsx\npackage.zip / IED"],
    ];
    flow.forEach((item, i) => {
      const x = 84 + i * 350;
      miniStep(s, x, 326, 278, 184, String(i + 1).padStart(2, "0"), item[0], item[1], i % 2 ? C.teal : C.blue, i % 2 ? C.lightTeal : C.lightBlue);
      if (i < flow.length - 1) arrow(s, x + 292, 400, i % 2 ? C.teal : C.blue);
    });
    rect(s, 112, 612, 760, 230, C.white, { radius: "rounded-lg" });
    txt(s, "仅翻版任务", 150, 650, 240, 42, { fontSize: 28, bold: true, color: C.blue }, "replace-only");
    bullet(s, 154, 714, "返回单个 audit_replace job，任务详情展示 replaced.dwg 与 report.xlsx。", C.blue, 640, 21);
    bullet(s, 154, 766, "replace_summary 展示替换数量、受影响图纸和高频替换文本。", C.teal, 640, 21);
    rect(s, 1008, 612, 760, 230, C.white, { radius: "rounded-lg" });
    txt(s, "翻版 + 出图任务", 1046, 650, 280, 42, { fontSize: 28, bold: true, color: C.red }, "replace-deliverable");
    bullet(s, 1050, 714, "后端创建 TaskGroup，先执行 audit_replace，再用 replaced.dwg 作为出图输入。", C.red, 640, 21);
    bullet(s, 1050, 766, "group 详情可合并展示 replaced.dwg、package.zip、IED计划和报告。", C.amber, 640, 21);
    conclusionBand(s, 120, 920, 1680, 66, "交互原则", "不要让前端自己推断词库、模板或块规则；业务字段越清晰，后端可追溯性越强。", C.blue);
    addFooter(s, "资料来源：frontend/src/platform/api/httpAdapter.ts、documents/翻版模块前端接入指导.md。");
  }

  // 8. Verification and risk
  {
    const s = presentation.slides.add();
    rect(s, 0, 0, W, H, C.bg);
    img(s, BUILDING, 1320, 0, 600, H, "cover", "CNPE Hebei Branch building");
    rect(s, 1320, 0, 600, H, "rgba(0,78,162,0.32)");
    rect(s, 0, 0, 16, H, C.blue);
    rect(s, 1264, 0, 56, H, C.blue);
    addLogo(s, "cover");
    txt(s, "07", 84, 48, 82, 52, { fontSize: 34, bold: true, color: C.blue }, "section-no");
    txt(s, "验收与风险", 174, 48, 300, 52, { fontSize: 32, bold: true, color: C.ink }, "section-title");
    rect(s, 84, 122, 10, 58, C.blue);
    txt(s, "验收应围绕替换结果、纠错回归、块图替换和出图联动四类证据", 110, 112, 1050, 92, {
      fontSize: 38,
      bold: true,
      color: C.ink,
    }, "closing-title");
    line(s, 84, 218, 980, C.blue, 4);
    const checks = [
      ["替换结果", "replaced.dwg 文件存在，文件名按来源项目号替换或追加目标项目号。", C.blue],
      ["报告追溯", "report.xlsx 可打开，Summary 与 Replacements 能解释替换和跳过原因。", C.teal],
      ["回归纠错", "用目标项目再跑纠错，确认高频错误文本已消除。", C.red],
      ["联动出图", "run_deliverable=true 时，TaskGroup 产物完整且项目号改写为目标项目。", C.amber],
    ];
    checks.forEach((item, i) => {
      const y = 320 + i * 124;
      rect(s, 112, y, 1020, 92, C.white, { radius: "rounded-lg" });
      rect(s, 112, y, 12, 92, item[2]);
      txt(s, item[0], 150, y + 22, 180, 42, { fontSize: 26, bold: true, color: item[2] }, "check-name");
      txt(s, item[1], 350, y + 22, 720, 42, { fontSize: 22, color: C.ink }, "check-body");
    });
    txt(s, "剩余风险", 112, 846, 240, 48, { fontSize: 32, bold: true, color: C.red }, "risk-title");
    bullet(s, 116, 908, "真实 CAD 环境、模板覆盖和缺失目标词条仍决定批量翻版稳定性。", C.red, 880, 22);
    bullet(s, 116, 956, "后续建议用固定样例集做翻版前后差异、纠错回归和出图产物验收。", C.blue, 880, 22);
    addFooter(s, "资料来源：backend/tests/unit/test_audit_replace_executor.py、backend/tests/unit/test_factory_index_maps.py、backend/tests/unit/test_module7_api.py。");
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
