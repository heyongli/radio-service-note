# svg_glyph_decode — SVG 描边字形(位号)解码工具

## 解决什么问题
Icom 维修手册 PCB 视图/电路图 PDF 中,大量文字(元件位号、功能块标签)不是
文本对象,而是矢量描边字形。`pdftotext` 几乎无输出,tesseract OCR 在
300/600dpi 渲染、二值化、膨胀后均失败(字形为 hairline 描边,像素特征与印刷体差异大)。

`pdftocairo -svg` 把每个字形导出为精确 path 数据 —— 本工具解析这些 path,
把字母/数字重组为位号字符串,并输出像素坐标。

## 流程
1. `svgelements` 解析 SVG,保留描边 `<path>` 元素(可按 stroke 宽度/变换过滤)
2. path → 子路径(字母外轮廓 + 内孔),按 bbox 包含关系把孔并回字母
3. 按页坐标从左到右聚类成串(间距阈值 max_gap × 字高)
4. 字形去重(路径数据 md5),cairosvg 以 evenodd 填充渲染 → 与
   matplotlib TextPath(Liberation Sans,Helvetica 度量)渲染模板做 IoU 匹配
5. 输出 JSON:文本 + 置信度 + 页面像素坐标(cx_px/cy_px/bbox_px)

## 用法
```bash
# 先导出 svg
pdftocairo -svg IC-2200H-bot.pdf /tmp/opencode/bot.svg
# 解码(--dpi 必须与后续用于标注的 PNG 渲染 dpi 一致)
python3 tools/svg_glyph_decode/svg_glyph_decode.py /tmp/opencode/bot.svg \
    --dpi 300 --out extract/bot_glyphs.json
```

## 当前状态 / 已知问题(诚实记录)
- 已跑通管线并输出字符串,但**分类准确率还不达标**(大量 M/W/J/I 误判),
  原因待排查:模板渲染(填充)与源字形(描边)的笔画粗细不一致、
  字形分组把图形线条混入字母串。
- 页面里的 path 元素混合了"字母轮廓"与"图形线条"两种内容,
  需要更强的过滤条件(曲线命令占比、笔画宽度一致性、位号前缀白名单
  R/C/L/D/Q/IC/FL/J/T…)。
- 改进方向见 BEST_PRACTICES.md §5:此路不通时,直接放大裁剪人工读数。
