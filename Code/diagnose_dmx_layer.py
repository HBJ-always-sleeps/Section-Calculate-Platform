# -*- coding: utf-8 -*-
"""诊断DMX图层实体结构"""
import ezdxf
import os

# DXF文件路径
dxf_path = r"测试文件/内湾段分层图（全航道底图20260331）2018.dxf"
if not os.path.exists(dxf_path):
    print(f"文件不存在: {dxf_path}")
    exit(1)

print(f"正在分析: {dxf_path}")
doc = ezdxf.readfile(dxf_path)
msp = doc.modelspace()

# 查询DMX图层实体
dmx_lines = list(msp.query('*[layer=="DMX"]'))
print(f"\nDMX图层所有实体数量: {len(dmx_lines)}")

# 按类型分类
from collections import Counter
type_counts = Counter(e.dxftype() for e in dmx_lines)
print(f"实体类型分布: {dict(type_counts)}")

# 查看前几个LINE实体的属性
dmx_only_lines = [e for e in dmx_lines if e.dxftype() == 'LINE']
print(f"\nLINE实体数量: {len(dmx_only_lines)}")

if dmx_only_lines:
    print("\n第一个LINE实体的DXF属性:")
    line = dmx_only_lines[0]
    for attr, val in line.dxfattribs().items():
        print(f"  {attr}: {val}")

# 查看原始DXF组码
print("\n\n查看第一个LINE实体的原始组码顺序:")
if dmx_only_lines:
    line = dmx_only_lines[0]
    # 打印实体的标签
    tags = list(line.tags)
    for group_code, value in tags[:20]:
        print(f"  组码{group_code}: {value}")

# 检查图层名是否有空格或特殊字符
print("\n\n检查所有图层名:")
all_layers = list(doc.layers.names())
dmx_like = [l for l in all_layers if 'DMX' in l.upper()]
print(f"包含DMX的图层: {dmx_like}")