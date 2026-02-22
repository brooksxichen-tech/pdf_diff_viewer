# VisualAlign for PDF

基于**图像特征点配准算法（OpenCV）**的 PDF 差异比对工具。通过将两份 PDF 对应页面渲染为高分辨率图像并做像素级对齐与对比，精确定位页面中的变动区域。
VisualAlign for PDF is a specialized utility designed for legal professionals, auditors, and researchers who need to identify subtle changes between two versions of a document. Unlike traditional text-based diff tools that parse characters, VisualAlign treats each page as a high-resolution image, ensuring that even layout shifts, font changes, and non-textual modifications are captured with pixel-perfect accuracy.

---

## 核心功能

- **极简纯图标 UI**：顶部单行工具栏全图标化，无文字标签；路径框支持点击选文件与长路径省略显示，拖放与互换逻辑完整。
- **单屏叠加与多屏并排同步视图**：支持「基准原图」「叠加差异图」「对比原图」三种视图的任意组合；可仅显示叠加差异，也可多窗格并排显示，滚动与缩放在各窗格间同步。
- **多种视觉对比模式**：护眼白底、标准黑底、仿纸阅读、柔和暗黑等色彩方案，基准差异与对比差异采用不同色系（蓝/青与红）便于区分。
- **页面目录与手动映射**：解析基准 PDF 书签（TOC）并在侧边栏展示；支持手动设置「页面映射」，解决两 PDF 页码不对应的情况。
- **自动配准**：使用 OpenCV 特征匹配与 RANSAC/ECC 对对比页进行平移、旋转、缩放对齐，再行像素级差异计算。

---

## 环境要求与安装

- **Python**：3.10 或以上
- **操作系统**：Windows / macOS / Linux

建议在项目目录下使用虚拟环境：

```bash
cd pdf_diff_viewer
python -m venv venv
# Windows:
venv\Scripts\activate
# macOS / Linux:
# source venv/bin/activate
pip install -r requirements.txt
```

---

## 运行指南

在已激活的虚拟环境中执行：

```bash
python main.py
```

启动后可通过顶部路径框点击或拖放加载两个 PDF，使用视图图标切换显示方式，使用色彩图标选择对比模式。

---

## 打包说明

使用 PyInstaller 可打包为不依赖本地 Python 环境的独立可执行程序：

```bash
pip install pyinstaller
pyinstaller --onefile --windowed --name "VisualAlign-for-PDF" main.py
```

生成的可执行文件位于 `dist/` 目录。若需将 `src` 作为包参与打包，可先编写 `.spec` 并在其中指定 `pathex` 与 `hiddenimports`，再执行：

```bash
pyinstaller VisualAlign-for-PDF.spec
```

---

## 项目结构

```
pdf_diff_viewer/
├── main.py              # 程序入口
├── requirements.txt    # 依赖列表
├── README.md
├── .gitignore
└── src/
    ├── __init__.py
    ├── app.py           # 主窗口、布局、拖放、视图与色彩、加载进度
    ├── pdf_loader.py    # PDF 转灰度图与书签 (PyMuPDF)
    ├── load_worker.py   # 后台 PDF 加载与进度信号 (QThread)
    ├── registration.py  # 图像配准 (OpenCV ORB+RANSAC/ECC)
    ├── diff_render.py   # 多色彩模式差异图合成
    ├── canvas.py        # 可缩放平移画布与多视图同步
    ├── sidebar.py       # 目录与差异率侧边栏
    └── page_mapping_dialog.py  # 页面映射设置对话框
```

依赖详见 `requirements.txt`（PyQt6、PyMuPDF、opencv-python、numpy、qtawesome）。
