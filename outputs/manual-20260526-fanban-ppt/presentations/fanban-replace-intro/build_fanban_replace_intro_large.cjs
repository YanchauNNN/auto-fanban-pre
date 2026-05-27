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
const OUT = `${ROOT}/output/翻版功能模块介绍-大字版.pptx`;
const PREVIEW_DIR = `${ROOT}/preview-large`;
const LAYOUT_DIR = `${ROOT}/qa/layout-large`;
const LOGO = `${ROOT}/assets/cnpe-cnnc-logo.png`;
const BUILDING = `${ROOT}/assets/cnpe-building.jpeg`;

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
        fontSize: 36,
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

function addFooter(slide, source = "") {
  txt(slide, "中国核电工程有限公司河北分公司 | auto-fanban-pre 翻版功能模块介绍", 70, 1014, 780, 36, {
    fontSize: 17,
    color: C.quiet,
  }, "footer-left");
  if (source) {
    txt(slide, source, 850, 1014, 1000, 36, {
      fontSize: 16,
      color: C.quiet,
      align: "right",
    }, "footer-source");
  }
}

function addHeader(slide, no, section, claim, sub = "", titleSize = 52) {
  rect(slide, 0, 0, W, H, C.bg);
  rect(slide, 0, 0, 18, H, C.blue);
  txt(slide, no, 70, 44, 90, 60, {
    fontSize: 42,
    bold: true,
    color: C.blue,
  }, "section-no");
  txt(slide, section, 170, 44, 480, 60, {
    fontSize: 40,
    bold: true,
    color: C.ink,
  }, "section-title");
  rect(slide, 70, 122, 12, 82, C.blue);
  txt(slide, claim, 100, 110, 1280, 110, {
    fontSize: titleSize,
    bold: true,
    color: C.ink,
  }, "slide-title");
  line(slide, 70, 232, 1080, C.blue, 5);
  if (sub) {
    txt(slide, sub, 70, 258, 1320, 60, {
      fontSize: 31,
      color: C.muted,
    }, "slide-subtitle");
  }
  addLogo(slide);
}

function bigCard(slide, x, y, w, h, title, body, accent = C.blue, fillColor = C.white) {
  rect(slide, x, y, w, h, fillColor, { radius: "rounded-lg" });
  rect(slide, x, y, 14, h, accent);
  txt(slide, title, x + 40, y + 32, w - 80, 60, {
    fontSize: 38,
    bold: true,
    color: accent,
  }, "card-title");
  txt(slide, body, x + 40, y + 112, w - 80, h - 134, {
    fontSize: 31,
    color: C.ink,
  }, "card-body");
}

function wideCheck(slide, x, y, w, h, title, body, accent = C.blue) {
  rect(slide, x, y, w, h, C.white, { radius: "rounded-lg" });
  rect(slide, x, y, 14, h, accent);
  txt(slide, title, x + 40, y + 34, 230, h - 48, {
    fontSize: 36,
    bold: true,
    color: accent,
  }, "wide-check-title");
  txt(slide, body, x + 320, y + 34, w - 360, h - 48, {
    fontSize: 30,
    color: C.ink,
  }, "wide-check-body");
}

function metric(slide, x, y, w, h, value, label, accent = C.blue, valueSize = 76) {
  rect(slide, x, y, w, h, C.white, { radius: "rounded-lg" });
  txt(slide, value, x + 34, y + 26, w - 68, 88, {
    fontSize: valueSize,
    bold: true,
    color: accent,
  }, "metric-value");
  txt(slide, label, x + 36, y + 126, w - 72, h - 144, {
    fontSize: 30,
    color: C.muted,
  }, "metric-label");
}

function step(slide, x, y, w, h, no, title, body, accent = C.blue, fillColor = C.white) {
  rect(slide, x, y, w, h, fillColor, { radius: "rounded-lg" });
  txt(slide, no, x + 28, y + 24, 70, 58, {
    fontSize: 38,
    bold: true,
    color: accent,
  }, "step-no");
  txt(slide, title, x + 108, y + 30, w - 132, 58, {
    fontSize: 35,
    bold: true,
    color: C.ink,
  }, "step-title");
  txt(slide, body, x + 34, y + 112, w - 68, h - 134, {
    fontSize: 28,
    color: C.muted,
  }, "step-body");
}

function bullet(slide, x, y, body, color = C.blue, width = 900) {
  rect(slide, x, y + 17, 16, 16, color, { radius: "rounded-full" });
  txt(slide, body, x + 34, y, width, 76, {
    fontSize: 30,
    color: C.ink,
  }, "bullet");
}

function band(slide, x, y, w, h, lead, body, accent = C.blue) {
  rect(slide, x, y, w, h, "#EAF1FA");
  rect(slide, x, y, 14, h, accent);
  txt(slide, lead, x + 34, y + 24, 220, h - 36, {
    fontSize: 30,
    bold: true,
    color: accent,
  }, "band-lead");
  txt(slide, body, x + 270, y + 24, w - 310, h - 36, {
    fontSize: 30,
    bold: true,
    color: C.ink,
  }, "band-body");
}

function arrow(slide, x, y, color = C.blue) {
  txt(slide, "→", x, y, 54, 54, {
    fontSize: 44,
    bold: true,
    align: "center",
    color,
  }, "arrow");
}

function row(slide, x, y, widths, values, fillColor, emph = -1) {
  let cx = x;
  values.forEach((value, index) => {
    rect(slide, cx, y, widths[index], 78, fillColor, {
      line: { color: C.white, weight: 2 },
    });
    txt(slide, value, cx + 18, y + 20, widths[index] - 36, 42, {
      fontSize: index === emph ? 29 : 27,
      bold: index === emph,
      color: index === emph ? C.blue : C.ink,
      align: index === 0 ? "center" : "left",
    }, "table-cell");
    cx += widths[index];
  });
}

async function build() {
  await mkdir(path.dirname(OUT), { recursive: true });
  await mkdir(PREVIEW_DIR, { recursive: true });
  await mkdir(LAYOUT_DIR, { recursive: true });

  const presentation = Presentation.create({ slideSize: { width: W, height: H } });

  // 1
  {
    const s = presentation.slides.add();
    rect(s, 0, 0, W, H, C.bg);
    img(s, BUILDING, 1190, 0, 730, H, "cover", "CNPE Hebei Branch building");
    rect(s, 1138, 0, 70, H, C.blue);
    rect(s, 1208, 0, 712, H, "rgba(0,78,162,0.24)");
    rect(s, 0, 0, 18, H, C.blue);
    addLogo(s, true);
    txt(s, "翻版功能模块介绍", 118, 210, 850, 92, {
      fontSize: 70,
      bold: true,
      color: C.ink,
    }, "cover-title");
    txt(s, "把既有 DWG 迁移到目标项目口径", 118, 330, 920, 80, {
      fontSize: 46,
      bold: true,
      color: C.blue,
    }, "cover-subtitle");
    line(s, 118, 456, 860, C.blue, 6);
    txt(s, "后端负责识别、替换、报告和串联出图；前端只提交清晰的翻版意图。", 118, 520, 880, 120, {
      fontSize: 34,
      color: C.muted,
    }, "cover-copy");
    metric(s, 118, 724, 270, 160, "1 个", "统一入口", C.blue, 76);
    metric(s, 438, 724, 270, 160, "2 种", "运行方式", C.teal, 76);
    metric(s, 758, 724, 270, 160, "7 套", "索引图模板", C.red, 76);
    txt(s, "日期：2026-05-26", 118, 950, 520, 42, {
      fontSize: 24,
      color: C.quiet,
    }, "cover-date");
  }

  // 2
  {
    const s = presentation.slides.add();
    addHeader(s, "01", "总览", "翻版主链已经成型，核心是“纠错底座 + 映射回写 + 出图联动”", "本次调整后的页面按大字汇报模式重排，减少说明密度。", 50);
    bigCard(s, 96, 360, 510, 300, "纠错底座", "先按目标项目规则发现来源项目残留文本，避免盲目查找。", C.blue);
    bigCard(s, 704, 360, 510, 300, "映射回写", "按词库 source 列到 target 列映射，并通过 entity handle 更新 CAD 文本。", C.teal);
    bigCard(s, 1312, 360, 510, 300, "出图联动", "可只交付 replaced.dwg，也可继续进入交付出图任务组。", C.red);
    band(s, 120, 812, 1680, 94, "一句话", "翻版不是前端开关，而是一条可追溯的 CAD 处理链。", C.blue);
    addFooter(s, "资料来源：项目文档、YAML、后端与前端代码。");
  }

  // 3
  {
    const s = presentation.slides.add();
    addHeader(s, "02", "业务问题", "人工翻版容易漏改，尤其是图签、块属性和索引图", "风险来自对象分散、规则变化和交付链路衔接。", 52);
    bigCard(s, 118, 360, 520, 340, "对象分散", "项目号、项目名称、内部编码、图签字段和块内文字都可能出现。", C.blue);
    bigCard(s, 700, 360, 520, 340, "规则变化", "2016 / 1916 需要区分机组或岛号，映射不能写死。", C.teal);
    bigCard(s, 1282, 360, 520, 340, "交付衔接", "翻版后的 DWG 还可能继续用于 PDF、IED 和打包出图。", C.red);
    band(s, 120, 834, 1680, 94, "判断", "应让后端承担识别和替换，前端只提交业务参数。", C.blue);
    addFooter(s, "资料来源：documents/翻版模块前端接入指导.md。");
  }

  // 4
  {
    const s = presentation.slides.add();
    addHeader(s, "03", "接口现状", "同一个接口已经同时承载纠错和翻版", "POST /api/jobs/audit-replace 保持 multipart/form-data。", 54);
    metric(s, 118, 356, 360, 176, "check", "纠错扫描模式", C.teal, 72);
    metric(s, 548, 356, 360, 176, "replace", "翻版替换模式", C.red, 72);
    metric(s, 978, 356, 360, 176, "group", "翻版后继续出图", C.amber, 72);
    metric(s, 1408, 356, 360, 176, "xlsx", "替换报告下载", C.blue, 72);
    row(s, 150, 650, [260, 560, 760], ["字段", "示例", "作用"], C.lightBlue, 1);
    row(s, 150, 730, [260, 560, 760], ["source", "source_project_no", "决定来源词库列"], C.white, 1);
    row(s, 150, 810, [260, 560, 760], ["target", "target_project_no", "决定目标词库列"], "#F1F5FA", 1);
    band(s, 120, 920, 1680, 82, "输出", "任务详情返回 replaced.dwg、report.xlsx 和 replace_summary。", C.blue);
    addFooter(s, "资料来源：documents/参数规范.yaml、API/app/runtime.py。");
  }

  // 5
  {
    const s = presentation.slides.add();
    addHeader(s, "04", "后端主链", "翻版先扫描，再回写；不是简单字符串替换", "扫描上下文、entity handle 和替换报告都来自同一条主链。", 52);
    const steps = [
      ["01", "DWG 转 DXF", "ODA 转换，并提取图框、图签上下文。", C.blue, C.lightBlue],
      ["02", ".NET 扫描", "扫描 TEXT、MTEXT、ATTRIB，保留 handle。", C.teal, C.lightTeal],
      ["03", "目标纠错", "按目标项目规则找出来源残留。", C.red, C.lightRed],
      ["04", "映射回写", "按词库映射逐实体更新文本。", C.amber, C.lightGold],
      ["05", "导出报告", "生成 DWG、JSON、XLSX 和摘要。", C.blue, C.white],
    ];
    steps.forEach((item, i) => {
      const x = 80 + i * 362;
      step(s, x, 384, 300, 300, item[0], item[1], item[2], item[3], item[4]);
      if (i < steps.length - 1) arrow(s, x + 310, 500, item[3]);
    });
    band(s, 120, 842, 1680, 94, "价值", "后续再跑纠错，可以验证翻版是否真正消除了目标项目下的残留。", C.teal);
    addFooter(s, "资料来源：backend/src/audit_replace/executor.py。");
  }

  // 6
  {
    const s = presentation.slides.add();
    addHeader(s, "05", "替换边界", "替换行为有明确边界，跳过原因会进入报告", "这页把原来小字说明拆成两个大卡片。", 52);
    bigCard(s, 120, 360, 780, 350, "哪些对象会改", "TEXT、MTEXT、ATTRIB、ATTDEF 等支持文本实体会按 handle 回写。", C.blue);
    bigCard(s, 1020, 360, 780, 350, "哪些情况会跳过", "没有 handle、找不到实体、缺少目标词条或替换无变化，都会记录为 skipped。", C.red);
    band(s, 120, 840, 1680, 94, "报告", "report.xlsx 记录 matched_text、replacement_text、raw_text、new_text 和 message。", C.blue);
    addFooter(s, "资料来源：backend/src/audit_replace/reporting.py。");
  }

  // 7
  {
    const s = presentation.slides.add();
    addHeader(s, "06", "规则治理", "词库和 YAML 是翻版规则的来源，不应散落在代码里", "项目列、参与行、机组一致性和模板目录都可由配置控制。", 52);
    row(s, 130, 360, [380, 520, 720], ["配置项", "当前口径", "作用"], C.lightBlue, 1);
    row(s, 130, 450, [380, 520, 720], ["lexicon_path", "词库收集.xlsx", "提供来源列与目标列"], C.white, 1);
    row(s, 130, 540, [380, 520, 720], ["include_rows", "1、2、3+", "项目号、别名、词条都参与"], "#F1F5FA", 1);
    row(s, 130, 630, [380, 520, 720], ["unit rules", "2016 / 1916 等", "校验来源与目标机组或岛号"], C.white, 1);
    row(s, 130, 720, [380, 520, 720], ["template_dir", "factory_index_maps", "选择厂房索引图模板"], "#F1F5FA", 1);
    band(s, 120, 884, 1680, 82, "治理", "业务变化优先改 YAML 和词库，替换代码只保留机制。", C.teal);
    addFooter(s, "资料来源：documents/参数规范_运行期.yaml。");
  }

  // 8
  {
    const s = presentation.slides.add();
    addHeader(s, "07", "索引图替换", "厂房索引图已经接入翻版主链", "它不是普通文字替换，而是块级模板替换。", 54);
    bigCard(s, 110, 358, 520, 360, "模板覆盖", "1818、1907、2026 以及 1916/2016 的分岛号模板。", C.blue);
    bigCard(s, 700, 358, 520, 360, "源块识别", "通过角度文字、罗盘圆、块名、insert handle 和 bbox 形成候选。", C.teal);
    bigCard(s, 1290, 358, 520, 360, "Bridge 执行", "生成计划后交给 AcCoreConsole 和 .NET Bridge 替换。", C.red);
    band(s, 120, 848, 1680, 94, "边界", "前端不读模板、不解析 DWG，只提交 source_island_no / target_island_no。", C.red);
    addFooter(s, "资料来源：documents/厂房索引图替换前端接入指导.md、factory_index_maps.py。");
  }

  // 9
  {
    const s = presentation.slides.add();
    addHeader(s, "08", "用户交互", "前端表单只需要把业务意图传清楚", "复杂规则留在后端，界面避免出现重复控制。", 54);
    const flow = [
      ["01", "选择来源", "source_project_no\nsource_island_no", C.blue, C.lightBlue],
      ["02", "选择目标", "target_project_no\ntarget_island_no", C.teal, C.lightTeal],
      ["03", "选择方式", "仅翻版\n同步出图", C.red, C.lightRed],
      ["04", "下载结果", "replaced.dwg\nreport.xlsx", C.amber, C.lightGold],
    ];
    flow.forEach((item, i) => {
      const x = 120 + i * 432;
      step(s, x, 388, 340, 310, item[0], item[1], item[2], item[3], item[4]);
      if (i < flow.length - 1) arrow(s, x + 354, 510, item[3]);
    });
    band(s, 120, 852, 1680, 94, "交互原则", "前端不推断词库、模板或块规则，只负责参数完整性。", C.blue);
    addFooter(s, "资料来源：frontend/src/platform/api/httpAdapter.ts。");
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
    txt(s, "09", 84, 48, 90, 60, { fontSize: 42, bold: true, color: C.blue }, "section-no");
    txt(s, "验收与风险", 184, 48, 360, 60, { fontSize: 40, bold: true, color: C.ink }, "section-title");
    rect(s, 84, 128, 12, 82, C.blue);
    txt(s, "验收看四类证据：结果、报告、纠错回归、出图联动", 112, 112, 1080, 124, {
      fontSize: 54,
      bold: true,
      color: C.ink,
    }, "closing-title");
    line(s, 84, 254, 980, C.blue, 5);
    wideCheck(s, 112, 344, 1020, 120, "替换结果", "replaced.dwg 存在，文件名口径正确。", C.blue);
    wideCheck(s, 112, 496, 1020, 120, "报告追溯", "report.xlsx 可打开，跳过原因可解释。", C.teal);
    wideCheck(s, 112, 648, 1020, 120, "回归验证", "用目标项目再跑纠错，确认残留已消除。", C.red);
    txt(s, "剩余风险", 112, 824, 260, 52, { fontSize: 42, bold: true, color: C.red }, "risk-title");
    bullet(s, 116, 894, "真实 CAD 环境、模板覆盖、缺失目标词条仍决定批量稳定性。", C.red, 980);
    addFooter(s, "资料来源：backend/tests/unit/test_audit_replace_executor.py、test_module7_api.py。");
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
