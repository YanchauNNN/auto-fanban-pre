# -*- coding: utf-8 -*-
import os
import re
import sys
from datetime import date
from concurrent.futures import as_completed, ThreadPoolExecutor

from docxtpl import DocxTemplate, InlineImage
from docx.shared import Mm
from PIL import Image
import pytesseract

from tkinter import Tk, filedialog, messagebox, StringVar, Canvas
from tkinter import ttk


CURRENT_CHAPTER = "7.1"

# ========================
# 模板选项
# ========================
TEMPLATE_OPTIONS = [
    "内部结构计算书",
    "核岛厂房计算书"
]

TEMPLATE_FILE_MAP = {
    "内部结构计算书": "内部结构计算书.docx",
    "核岛厂房计算书": "核岛厂房计算书.docx"
}

# ========================
# 厂房列表
# ========================
ALL_PLANTS = ["RX", "NH", "SD", "SU", "KA"]

# ========================
# 下拉选项
# ========================
PROJECT_NAME_OPTIONS = [
    "漳州核电厂3、4号机组",
    "浙江金七门核电厂1、2号机组",
    "巴基斯坦恰希玛核电厂五号机组"
]

SUBPROJECT_CODE_OPTIONS = [
    "RX", "KA", "NH", "SD", "SU", "DA", "DB"
]

SUBPROJECT_NAME_OPTIONS = [
    "内部结构",
    "燃料厂房",
    "核辅助厂房",
    "安全厂房SD区",
    "安全厂房SU区",
    "DA应急柴油机发电厂房",
    "DB应急柴油机发电厂房"
]

DESIGN_PHASE_OPTIONS = [
    "施工图设计"
]

# ========================
# ========================
# 获取资源路径（适配源码运行 / EXE运行 / onefile临时解压）
# ========================
def resource_path(relative_path):
    if getattr(sys, 'frozen', False):
        # PyInstaller --onefile 运行时，资源会被释放到 sys._MEIPASS
        base_path = sys._MEIPASS
    else:
        base_path = os.path.abspath(".")

    return os.path.join(base_path, relative_path)


# ========================
# 获取程序所在目录，用于输出文件
# ========================
def get_app_dir():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.abspath(".")

# ========================
# 获取程序所在目录
# ========================
def get_app_dir():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.abspath(".")

# ========================

# 根据界面选择获取模板路径
# ========================
def get_selected_template_path(template_type):
    filename = TEMPLATE_FILE_MAP.get(template_type)

    if not filename:
        return ""

    # 优先读取打包进 EXE 的模板
    bundled_path = resource_path(filename)
    if os.path.exists(bundled_path):
        return bundled_path

    # 源码调试时，读取 main.py 同目录模板
    local_path = os.path.join(os.path.abspath("."), filename)
    if os.path.exists(local_path):
        return local_path

    return bundled_path


# ========================
# 配置 Tesseract-OCR 路径
# ========================
def get_tesseract_path():
    # 优先使用打包进 EXE 的 Tesseract
    bundled_path = resource_path(os.path.join("Tesseract-OCR", "tesseract.exe"))
    if os.path.exists(bundled_path):
        return bundled_path

    # 源码调试时，使用项目目录下的 Tesseract-OCR
    local_path = os.path.join(os.path.abspath("."), "Tesseract-OCR", "tesseract.exe")
    if os.path.exists(local_path):
        return local_path

    # 兜底使用系统安装路径
    return r"D:\Program Files\Tesseract-OCR\tesseract.exe"


pytesseract.pytesseract.tesseract_cmd = get_tesseract_path()

# 设置 tessdata 路径，避免打包后找不到语言库
tessdata_dir = resource_path(os.path.join("Tesseract-OCR", "tessdata"))
if os.path.exists(tessdata_dir):
    os.environ["TESSDATA_PREFIX"] = tessdata_dir

print("OCR路径:", pytesseract.pytesseract.tesseract_cmd)


pytesseract.pytesseract.tesseract_cmd = get_tesseract_path()
print("OCR路径:", pytesseract.pytesseract.tesseract_cmd)

IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.bmp'}
DIRECTION_MAP = {"X": "水平向", "Y": "竖向", "Z": "拉筋"}

# ========================
# 字段
# ========================
FIELD_LABELS = {
    "internal_code": "内部编码",
    "project_name": "项目名称",
    "version": "版本",
    "subproject_code": "子项号或系统号",
    "subproject_name": "子项或系统名称",
    "design_phase": "设计阶段",
    "document_name": "图册（文件）名称",
    "workshop_length": "厂房外轮廓长度",
    "workshop_width": "厂房外轮廓宽度",
    "raft_slab_top_elevation": "筏板顶标高",
    "roof_top_elevation": "屋顶标高",
    "factory_extreme_min_temperature": "厂址的极端最低温度",
    "factory_extreme_max_temperature": "厂址的极端最高温度",
    "site_soil_temperature": "场地土壤温度"
}

FIELD_UNITS = {
    "document_name": "配筋计算书",
    "workshop_length": "m",
    "workshop_width": "m",
    "raft_slab_top_elevation": "m",
    "roof_top_elevation": "m",
    "factory_extreme_min_temperature": "℃",
    "factory_extreme_max_temperature": "℃",
    "site_soil_temperature": "℃"
}

COMBOBOX_FIELDS = {
    "project_name": PROJECT_NAME_OPTIONS,
    "subproject_code": SUBPROJECT_CODE_OPTIONS,
    "subproject_name": SUBPROJECT_NAME_OPTIONS,
    "design_phase": DESIGN_PHASE_OPTIONS
}

BASIC_INFO_FIELDS = [
    "internal_code",
    "project_name",
    "version",
    "subproject_code",
    "subproject_name",
    "design_phase",
    "document_name"
]

WORKSHOP_INFO_FIELDS = [
    "workshop_length",
    "workshop_width",
    "raft_slab_top_elevation",
    "roof_top_elevation",
    "factory_extreme_min_temperature",
    "factory_extreme_max_temperature",
    "site_soil_temperature"
]

# ========================
# OCR
# ========================
def extract_sm_value_from_image(image_path):
    try:
        img = Image.open(image_path)
        width, height = img.size
        img = img.resize((int(width * 0.8), int(height * 0.8)))
        crop = img.crop((0, 0, int(width * 0.5), int(height * 0.4)))
        crop = crop.convert('L')
        crop = crop.point(lambda x: 0 if x < 160 else 255)
        config = r'--oem 3 --psm 6 -c tessedit_char_whitelist=SMX=0123456789'
        text = pytesseract.image_to_string(crop, config=config)
        match = re.search(r'SM[Xx][^0-9]{0,3}(\d+)', text)
        value = match.group(1) if match else "0"
        if not value.isdigit():
            value = "0"
        return value
    except:
        return "0"

# ========================
# 排序
# ========================
def extract_sort_key(filename):
    base = os.path.splitext(filename)[0].upper()
    match = re.match(r'^([A-Za-z]+)(\d+)-([XYZ])$', base)
    if not match:
        return None

    prefix, num_str, direction = match.groups()
    num = int(num_str)
    dir_order = {"X": 0, "Y": 1, "Z": 2}.get(direction, 99)
    return (num, dir_order, prefix, direction, filename)

# ========================
# 并行加载配筋图
# ========================
def load_reinforcement_figures_parallel(picture_dir):
    files = [
        f for f in os.listdir(picture_dir)
        if os.path.isfile(os.path.join(picture_dir, f))
        and f.lower().endswith(tuple(IMAGE_EXTENSIONS))
    ]

    results = []

    with ThreadPoolExecutor(max_workers=4) as executor:
        future_map = {}

        for f in files:
            key = extract_sort_key(f)
            if key:
                num, dir_order, prefix, direction, filename = key
                full_path = os.path.join(picture_dir, filename)

                future = executor.submit(extract_sm_value_from_image, full_path)

                future_map[future] = {
                    "wall_id": f"{prefix}{num}",
                    "direction": direction,
                    "full_path": full_path,
                    "sort_key": (num, dir_order)
                }

        for future in as_completed(future_map):
            info = future_map[future]
            try:
                sm_value = future.result()
            except:
                sm_value = "0"

            info["sm_value"] = sm_value
            results.append(info)

    results.sort(key=lambda x: x["sort_key"])
    return results

# ========================
# 表格
# ========================
def generate_table_rows_from_figures(figures):
    wall_dict = {}

    for fig in figures:
        wid = fig["wall_id"]
        direction = fig["direction"]
        sm_value = fig["sm_value"]

        if wid not in wall_dict:
            wall_dict[wid] = {
                "id": wid,
                "x_calc": "0", "x_actual": "", "x_margin": "",
                "y_calc": "0", "y_actual": "", "y_margin": "",
                "z_calc": "0", "z_actual": "", "z_margin": ""
            }

        if direction == "X":
            wall_dict[wid]["x_calc"] = sm_value
        elif direction == "Y":
            wall_dict[wid]["y_calc"] = sm_value
        elif direction == "Z":
            wall_dict[wid]["z_calc"] = sm_value

    return sorted(
        wall_dict.values(),
        key=lambda x: int(re.match(r'[A-Za-z]+(\d+)', x["id"]).group(1))
    )

# ========================
# 获取首图
# ========================
def get_first_image_from_folder(folder_path):
    files = [
        f for f in os.listdir(folder_path)
        if os.path.isfile(os.path.join(folder_path, f))
        and f.lower().endswith(tuple(IMAGE_EXTENSIONS))
    ]

    if not files:
        raise FileNotFoundError(f"文件夹中未找到图片：{folder_path}")

    files.sort()
    return os.path.join(folder_path, files[0])

# ========================
# 根据当前厂房获取其他厂房
# ========================
def get_other_plants(subproject_code):
    current_plant = subproject_code.strip().upper()
    return [plant for plant in ALL_PLANTS if plant.upper() != current_plant]

# ========================
# 获取可用输出路径，避免同名文件被占用
# ========================
def get_available_output_path(output_path):
    if not os.path.exists(output_path):
        return output_path

    folder = os.path.dirname(output_path)
    filename = os.path.basename(output_path)
    name, ext = os.path.splitext(filename)

    index = 1
    while True:
        new_path = os.path.join(folder, f"{name}_{index}{ext}")
        if not os.path.exists(new_path):
            return new_path
        index += 1

# ========================
# GUI 样式
# ========================
def setup_style(root):
    style = ttk.Style(root)

    try:
        style.theme_use("clam")
    except:
        pass

    root.configure(bg="#eef2f7")

    style.configure("App.TFrame", background="#eef2f7")
    style.configure("Header.TFrame", background="#1f4e79")
    style.configure("Card.TFrame", background="#ffffff")
    style.configure("Footer.TFrame", background="#eef2f7")

    style.configure(
        "HeaderTitle.TLabel",
        background="#1f4e79",
        foreground="#ffffff",
        font=("Microsoft YaHei UI", 20, "bold")
    )

    style.configure(
        "HeaderSubTitle.TLabel",
        background="#1f4e79",
        foreground="#dbeafe",
        font=("Microsoft YaHei UI", 10)
    )

    style.configure(
        "Section.TLabelframe",
        background="#ffffff",
        foreground="#111827",
        borderwidth=1,
        relief="solid"
    )

    style.configure(
        "Section.TLabelframe.Label",
        background="#ffffff",
        foreground="#1f2937",
        font=("Microsoft YaHei UI", 11, "bold")
    )

    style.configure(
        "Form.TLabel",
        background="#ffffff",
        foreground="#374151",
        font=("Microsoft YaHei UI", 10)
    )

    style.configure(
        "Unit.TLabel",
        background="#ffffff",
        foreground="#6b7280",
        font=("Microsoft YaHei UI", 9)
    )

    style.configure(
        "Tip.TLabel",
        background="#eef2f7",
        foreground="#6b7280",
        font=("Microsoft YaHei UI", 9)
    )

    style.configure(
        "Status.TLabel",
        background="#eef2f7",
        foreground="#374151",
        font=("Microsoft YaHei UI", 10, "bold")
    )

    style.configure(
        "TEntry",
        padding=6,
        font=("Microsoft YaHei UI", 10)
    )

    style.configure(
        "TCombobox",
        padding=6,
        font=("Microsoft YaHei UI", 10)
    )

    style.configure(
        "Primary.TButton",
        font=("Microsoft YaHei UI", 12, "bold"),
        padding=(24, 10)
    )

    style.configure(
        "Secondary.TButton",
        font=("Microsoft YaHei UI", 10),
        padding=(12, 6)
    )

# ========================
# 鼠标滚轮绑定
# ========================
def bind_mousewheel(widget, canvas):
    def _on_mousewheel(event):
        canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    widget.bind_all("<MouseWheel>", _on_mousewheel)

# ========================
# 普通单列输入区
# ========================
def create_form_rows(parent, fields, entries):
    for row_index, field in enumerate(fields):
        label = ttk.Label(
            parent,
            text=FIELD_LABELS[field],
            style="Form.TLabel",
            width=22,
            anchor="w"
        )
        label.grid(row=row_index, column=0, sticky="w", padx=(0, 10), pady=6)

        if field in COMBOBOX_FIELDS:
            widget = ttk.Combobox(
                parent,
                width=42,
                values=COMBOBOX_FIELDS[field],
                state="readonly"
            )
            widget.set("")
        else:
            widget = ttk.Entry(parent, width=45)

        widget.grid(row=row_index, column=1, sticky="ew", pady=6)
        entries[field] = widget

        if field in FIELD_UNITS:
            unit_label = ttk.Label(
                parent,
                text=FIELD_UNITS[field],
                style="Unit.TLabel",
                anchor="w"
            )
            unit_label.grid(row=row_index, column=2, sticky="w", padx=(8, 0), pady=6)

    parent.columnconfigure(1, weight=1)

# ========================
# 厂房信息双列紧凑输入区
# ========================
def create_compact_workshop_rows(parent, fields, entries):
    for index, field in enumerate(fields):
        row = index // 2
        group_col = index % 2
        base_col = group_col * 3

        label = ttk.Label(
            parent,
            text=FIELD_LABELS[field],
            style="Form.TLabel",
            width=18,
            anchor="w"
        )
        label.grid(row=row, column=base_col, sticky="w", padx=(0, 6), pady=4)

        widget = ttk.Entry(parent, width=20)
        widget.grid(row=row, column=base_col + 1, sticky="ew", pady=4)
        entries[field] = widget

        unit_label = ttk.Label(
            parent,
            text=FIELD_UNITS.get(field, ""),
            style="Unit.TLabel",
            anchor="w"
        )
        unit_label.grid(row=row, column=base_col + 2, sticky="w", padx=(5, 18), pady=4)

    parent.columnconfigure(1, weight=1)
    parent.columnconfigure(4, weight=1)

# ========================
# 必填校验
# ========================
def validate_required_fields(context, picture_dir, template_type):
    required_fields = [
        "internal_code",
        "project_name",
        "subproject_code",
        "subproject_name",
        "design_phase",
        "document_name"
    ]

    missing = []

    if not template_type.strip():
        missing.append("计算书模板类型")

    for field in required_fields:
        if not context.get(field, "").strip():
            missing.append(FIELD_LABELS[field])

    if not picture_dir.strip():
        missing.append("配筋图文件夹")

    if missing:
        messagebox.showerror(
            "信息不完整",
            "请补充以下必填信息：\n\n" + "\n".join(f"· {item}" for item in missing)
        )
        return False

    return True

# ========================
# GUI
# ========================
def create_gui():
    root = Tk()
    root.title("核岛厂房计算书自动生成工具")
    root.geometry("820x810")
    root.minsize(760, 700)

    setup_style(root)

    # 外层滚动容器
    outer_frame = ttk.Frame(root, style="App.TFrame")
    outer_frame.pack(fill="both", expand=True)

    canvas = Canvas(
        outer_frame,
        background="#eef2f7",
        highlightthickness=0
    )
    scrollbar = ttk.Scrollbar(
        outer_frame,
        orient="vertical",
        command=canvas.yview
    )

    canvas.configure(yscrollcommand=scrollbar.set)

    scrollbar.pack(side="right", fill="y")
    canvas.pack(side="left", fill="both", expand=True)

    content_frame = ttk.Frame(canvas, style="App.TFrame", padding=(24, 18, 24, 18))
    canvas_window = canvas.create_window((0, 0), window=content_frame, anchor="nw")

    def on_content_configure(event):
        canvas.configure(scrollregion=canvas.bbox("all"))

    def on_canvas_configure(event):
        canvas.itemconfig(canvas_window, width=event.width)

    content_frame.bind("<Configure>", on_content_configure)
    canvas.bind("<Configure>", on_canvas_configure)
    bind_mousewheel(root, canvas)

    # 顶部标题卡片
    header_frame = ttk.Frame(content_frame, style="Header.TFrame", padding=(24, 20, 24, 20))
    header_frame.pack(fill="x", pady=(0, 16))

    title_label = ttk.Label(
        header_frame,
        text="核岛厂房计算书自动生成工具",
        style="HeaderTitle.TLabel"
    )
    title_label.pack(anchor="w")

    subtitle_label = ttk.Label(
        header_frame,
        text="选择模板类型，填写工程信息、厂房信息并选择配筋图文件夹后，自动生成配筋计算书 Word 文件",
        style="HeaderSubTitle.TLabel"
    )
    subtitle_label.pack(anchor="w", pady=(6, 0))

    entries = {}

    # ========================
    # 一、模板选择
    # ========================
    template_frame = ttk.LabelFrame(
        content_frame,
        text="一、模板选择",
        style="Section.TLabelframe",
        padding=(20, 14, 20, 14)
    )
    template_frame.pack(fill="x", pady=(0, 12))

    template_label = ttk.Label(
        template_frame,
        text="计算书模板类型",
        style="Form.TLabel",
        width=22,
        anchor="w"
    )
    template_label.grid(row=0, column=0, sticky="w", padx=(0, 10), pady=6)

    template_combo = ttk.Combobox(
        template_frame,
        width=42,
        values=TEMPLATE_OPTIONS,
        state="readonly"
    )
    template_combo.set("")
    template_combo.grid(row=0, column=1, sticky="ew", pady=6)

    template_tip = ttk.Label(
        template_frame,
        text="对应文件：内部结构计算书.docx / 核岛厂房计算书.docx",
        style="Unit.TLabel",
        anchor="w"
    )
    template_tip.grid(row=0, column=2, sticky="w", padx=(8, 0), pady=6)

    template_frame.columnconfigure(1, weight=1)

    # ========================
    # 二、工程基本信息
    # ========================
    form_frame = ttk.LabelFrame(
        content_frame,
        text="二、工程基本信息",
        style="Section.TLabelframe",
        padding=(20, 14, 20, 14)
    )
    form_frame.pack(fill="x", pady=(0, 12))

    create_form_rows(form_frame, BASIC_INFO_FIELDS, entries)

    # ========================
    # 三、厂房信息
    # ========================
    workshop_frame = ttk.LabelFrame(
        content_frame,
        text="三、厂房信息",
        style="Section.TLabelframe",
        padding=(20, 10, 12, 10)
    )
    workshop_frame.pack(fill="x", pady=(0, 12))

    create_compact_workshop_rows(workshop_frame, WORKSHOP_INFO_FIELDS, entries)

    # ========================
    # 四、图片文件夹
    # ========================
    folder_frame = ttk.LabelFrame(
        content_frame,
        text="四、图片文件夹",
        style="Section.TLabelframe",
        padding=(20, 14, 20, 14)
    )
    folder_frame.pack(fill="x", pady=(0, 12))

    folder_label = ttk.Label(
        folder_frame,
        text="配筋图文件夹",
        style="Form.TLabel",
        width=22,
        anchor="w"
    )
    folder_label.grid(row=0, column=0, sticky="w", padx=(0, 10), pady=6)

    picture_entry = ttk.Entry(folder_frame, width=45)
    picture_entry.grid(row=0, column=1, sticky="ew", pady=6)

    def select_picture_folder():
        path = filedialog.askdirectory(title="选择配筋图文件夹")
        if path:
            picture_entry.delete(0, 'end')
            picture_entry.insert(0, path)

    select_button = ttk.Button(
        folder_frame,
        text="选择文件夹",
        style="Secondary.TButton",
        command=select_picture_folder
    )
    select_button.grid(row=0, column=2, sticky="e", padx=(10, 0), pady=6)

    folder_frame.columnconfigure(1, weight=1)

    # 底部状态区
    footer_frame = ttk.Frame(content_frame, style="Footer.TFrame", padding=(2, 4, 2, 0))
    footer_frame.pack(fill="x", pady=(0, 0))

    tip_label = ttk.Label(
        footer_frame,
        text="提示：两个 Word 模板应与程序位于同一目录；图片文件夹中应包含 01、02 子文件夹，以及配筋云图文件。",
        style="Tip.TLabel"
    )
    tip_label.pack(anchor="w", pady=(0, 8))

    status_var = StringVar()
    status_var.set("准备就绪")

    status_label = ttk.Label(
        footer_frame,
        textvariable=status_var,
        style="Status.TLabel"
    )
    status_label.pack(anchor="w", pady=(0, 8))

    progress = ttk.Progressbar(
        footer_frame,
        mode="indeterminate",
        length=260
    )
    progress.pack(anchor="w", pady=(0, 12))

    button_frame = ttk.Frame(footer_frame, style="Footer.TFrame")
    button_frame.pack(fill="x", pady=(0, 8))

    # ========================
    # 生成
    # ========================
    def generate_doc():
        context = {f: entries[f].get().strip() for f in FIELD_LABELS}
        picture_dir = picture_entry.get().strip()
        template_type = template_combo.get().strip()

        if not validate_required_fields(context, picture_dir, template_type):
            return

        template_path = get_selected_template_path(template_type)

        if not os.path.exists(template_path):
            messagebox.showerror(
                "错误",
                f"未找到所选模板文件：\n\n{template_path}\n\n"
                f"请确认文件名是否为：\n{TEMPLATE_FILE_MAP.get(template_type, '')}"
            )
            return

        if not os.path.isdir(picture_dir):
            messagebox.showerror("错误", "配筋图文件夹不存在")
            return

        folder_01 = os.path.join(picture_dir, "01")
        folder_02 = os.path.join(picture_dir, "02")

        if not os.path.isdir(folder_01):
            messagebox.showerror("错误", "配筋图文件夹中未找到 01 子文件夹")
            return

        if not os.path.isdir(folder_02):
            messagebox.showerror("错误", "配筋图文件夹中未找到 02 子文件夹")
            return

        try:
            progress.start(10)
            status_var.set("正在整理输入信息……")
            root.update_idletasks()

            internal_code = context["internal_code"]
            context["project_number"] = internal_code[:4]
            context["document_serial_number"] = internal_code[-2:]
            context["record_1_version"] = context.get("version", "A")
            context["record_1_date"] = date.today().strftime("%Y-%m-%d")

            # 根据当前厂房自动生成 other_plants
            context["other_plants"] = get_other_plants(context["subproject_code"])

            match = re.search(r'\d+(?:\.\d+)?m~\d+(?:\.\d+)?m', context["document_name"])
            context["plant_elevation_range"] = match.group() if match else "未识别"

            os.makedirs("output", exist_ok=True)

            safe_template_name = template_type.replace(" ", "")
            OUTPUT_PATH = os.path.join(
                "output",
                f"{context['project_number']}{context['document_name']}{safe_template_name}.docx"
            )

            status_var.set(f"正在读取模板：{template_type}……")
            root.update_idletasks()

            doc = DocxTemplate(template_path)

            status_var.set("正在读取图片，请稍候……")
            root.update_idletasks()

            image_plant = get_first_image_from_folder(folder_01)
            image_wall = get_first_image_from_folder(folder_02)

            raw_figures = load_reinforcement_figures_parallel(picture_dir)
            table_rows = generate_table_rows_from_figures(raw_figures)

            context["image_plant_elevation_layout"] = InlineImage(doc, image_plant, width=Mm(150))
            context["image_wall_fem_calculation_model"] = InlineImage(doc, image_wall, width=Mm(160))
            context["wall_table_rows"] = table_rows

            context["reinforcement_figures"] = []

            for i, fig in enumerate(raw_figures, start=1):
                context["reinforcement_figures"].append({
                    "figure_number": f"{CURRENT_CHAPTER}-{i}",
                    "image": InlineImage(doc, fig["full_path"], width=Mm(140)),
                    "caption": f"{fig['wall_id']}-{DIRECTION_MAP[fig['direction']]}",
                    "sm_value": fig["sm_value"]
                })

            status_var.set("正在渲染 Word 模板……")
            root.update_idletasks()

            doc.render(context)

            SAVE_PATH = get_available_output_path(OUTPUT_PATH)

            try:
                doc.save(SAVE_PATH)
            except PermissionError:
                SAVE_PATH = get_available_output_path(OUTPUT_PATH)
                doc.save(SAVE_PATH)

            status_var.set(f"生成完成：{SAVE_PATH}")
            messagebox.showinfo("完成", f"生成成功:\n{SAVE_PATH}")
            os.startfile(SAVE_PATH)

        except Exception as e:
            status_var.set("生成失败")
            messagebox.showerror("错误", f"生成失败：\n{e}")

        finally:
            progress.stop()

    generate_button = ttk.Button(
        button_frame,
        text="生成计算书",
        style="Primary.TButton",
        command=generate_doc
    )
    generate_button.pack(anchor="center", ipadx=40, ipady=4)

    root.mainloop()


if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()
    create_gui()