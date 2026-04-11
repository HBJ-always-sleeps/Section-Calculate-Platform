# -*- coding: utf-8 -*-
"""分析标尺块结构和L1图层的中心线"""
import ezdxf
import sys
import io
from collections import defaultdict

# 设置输出编码
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

dxf_path = r'D:\断面算量平台\测试文件\内湾段分层图（全航道底图20260318）.dxf'
doc = ezdxf.readfile(dxf_path)
msp = doc.modelspace()

print("=" * 60)
print("标尺块结构分析")
print("=" * 60)

# 分析标尺图层的INSERT块
scale_inserts = list(msp.query('*[layer=="标尺"]'))
print(f"\n标尺图层INSERT数量: {len(scale_inserts)}")

if scale_inserts:
    # 分析第一个INSERT
    first_insert = scale_inserts[0]
    print(f"\n第一个INSERT信息:")
    print(f"  名称: {first_insert.dxf.name}")
    print(f"  位置: ({first_insert.dxf.insert.x:.2f}, {first_insert.dxf.insert.y:.2f})")
    
    # 获取块定义
    block_name = first_insert.dxf.name
    if block_name in doc.blocks:
        block = doc.blocks[block_name]
        print(f"\n块 '{block_name}' 包含的实体:")
        entity_types = defaultdict(int)
        texts = []
        for e in block:
            entity_types[e.dxftype()] += 1
            if e.dxftype() == 'TEXT':
                texts.append(e.dxf.text)
        print(f"  实体类型统计: {dict(entity_types)}")
        if texts:
            print(f"  文本内容（前10个）: {texts[:10]}")

# 分析L1图层
print("\n" + "=" * 60)
print("L1图层分析")
print("=" * 60)

l1_lines = list(msp.query('LINE[layer=="L1"]'))
l1_texts = list(msp.query('TEXT[layer=="L1"]'))

print(f"\nL1 LINE数量: {len(l1_lines)}")
print(f"L1 TEXT数量: {len(l1_texts)}")

# 分析LINE方向（水平线vs垂直线）
h_lines = []  # 水平线
v_lines = []  # 垂直线
other_lines = []  # 其他

for line in l1_lines:
    x1, y1 = line.dxf.start.x, line.dxf.start.y
    x2, y2 = line.dxf.end.x, line.dxf.end.y
    
    if abs(y2 - y1) < 0.01:  # 水平线
        h_lines.append((min(x1, x2), max(x1, x2), y1))
    elif abs(x2 - x1) < 0.01:  # 垂直线
        v_lines.append((x1, min(y1, y2), max(y1, y2)))
    else:
        other_lines.append((x1, y1, x2, y2))

print(f"\n水平线: {len(h_lines)}")
print(f"垂直线: {len(v_lines)}")
print(f"斜线: {len(other_lines)}")

# 显示一些示例
if h_lines:
    print(f"\n水平线示例（前5条）:")
    for i, (x1, x2, y) in enumerate(h_lines[:5]):
        print(f"  Y={y:.2f}, X范围=[{x1:.2f}, {x2:.2f}]")

if v_lines:
    print(f"\n垂直线示例（前5条）:")
    for i, (x, y1, y2) in enumerate(v_lines[:5]):
        print(f"  X={x:.2f}, Y范围=[{y1:.2f}, {y2:.2f}]")

# 分析L1 TEXT
if l1_texts:
    print(f"\nL1 TEXT示例（前10个）:")
    for i, text in enumerate(l1_texts[:10]):
        print(f"  '{text.dxf.text}' at ({text.dxf.insert.x:.2f}, {text.dxf.insert.y:.2f})")

# 分析开挖线图层
print("\n" + "=" * 60)
print("开挖线图层分析")
print("=" * 60)

kaiwa_polys = list(msp.query('LWPOLYLINE[layer=="开挖线"]'))
print(f"\n开挖线多段线数量: {len(kaiwa_polys)}")

if kaiwa_polys:
    print(f"\n第一条开挖线示例:")
    poly = kaiwa_polys[0]
    pts = [(p[0], p[1]) for p in poly.get_points()]
    print(f"  顶点数: {len(pts)}")
    print(f"  前3个顶点: {pts[:3]}")

# 分析超挖线图层
print("\n" + "=" * 60)
print("超挖线图层分析")
print("=" * 60)

chaowa_polys = list(msp.query('LWPOLYLINE[layer=="超挖线"]'))
print(f"\n超挖线多段线数量: {len(chaowa_polys)}")

if chaowa_polys:
    print(f"\n第一条超挖线示例:")
    poly = chaowa_polys[0]
    pts = [(p[0], p[1]) for p in poly.get_points()]
    print(f"  顶点数: {len(pts)}")
    print(f"  前3个顶点: {pts[:3]}")

print("\n完成!")