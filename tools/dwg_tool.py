r"""dwg_tool.py —— 本地 DWG 解析工具（基于 Aspose.CAD 内核）

用法（必须用 .cadenv 里的 Python）:
  .cadenv\Scripts\python.exe dwg_tool.py info  <file.dwg>          # 图层 / 实体 / 范围
  .cadenv\Scripts\python.exe dwg_tool.py dxf   <file.dwg> [out.dxf]
  .cavenv\Scripts\python.exe dwg_tool.py png   <file.dwg> [out.png] [宽] [高]

注意：Aspose.CAD 是商业内核，未授权版本会在导出的 DXF/PNG 上加 “Evaluation only”
水印（叠加的矢量文字），几何数据本身是完整的。
"""
import os
import sys

import aspose.cad as cad
from aspose.cad.imageoptions import (
    CadRasterizationOptions,
    DxfOptions,
    PngOptions,
)


def load(path):
    return cad.Image.load(path)


def cmd_info(path):
    img = load(path)
    print("文件      :", os.path.basename(path), f"{os.path.getsize(path):,} bytes")
    print("渲染尺寸  :", img.width, "x", img.height, "px")
    print("格式      :", os.path.splitext(path)[1].upper())
    for attr in ("layers", "entities", "layouts", "blocks"):
        print(f"{attr:10s}:", "有" if hasattr(img, attr) else "该内核未暴露")


def cmd_dxf(path, out=None):
    out = out or (os.path.splitext(path)[0] + ".dxf")
    img = load(path)
    img.save(out, DxfOptions())
    print("已导出 DXF:", out, f"{os.path.getsize(out):,} bytes")


def cmd_png(path, out=None, w=3200.0, h=None):
    out = out or (os.path.splitext(path)[0] + ".png")
    img = load(path)
    r = CadRasterizationOptions()
    r.page_width = float(w)
    r.page_height = float(h) if h else float(w) * img.height / max(1, img.width)
    r.automatic_layouts_scaling = True
    o = PngOptions()
    o.vector_rasterization_options = r
    img.save(out, o)
    print("已导出 PNG:", out, f"{os.path.getsize(out):,} bytes")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    cmd, path = sys.argv[1], sys.argv[2]
    if cmd == "info":
        cmd_info(path)
    elif cmd == "dxf":
        cmd_dxf(path, sys.argv[3] if len(sys.argv) > 3 else None)
    elif cmd == "png":
        cmd_png(path,
                sys.argv[3] if len(sys.argv) > 3 else None,
                sys.argv[4] if len(sys.argv) > 4 else 3200.0,
                sys.argv[5] if len(sys.argv) > 5 else None)
    else:
        print(__doc__)
