# -*- coding: utf-8 -*-
"""
最小化DXF读取测试 - 诊断卡住位置
"""

import sys
import os

print("Step 1: 导入sys和os", flush=True)

print("Step 2: 导入ezdxf...", flush=True)
import ezdxf
print("  OK: ezdxf导入成功", flush=True)

print("Step 3: 导入numpy...", flush=True)
import numpy as np
print("  OK: numpy导入成功", flush=True)

print("Step 4: 导入pyvista...", flush=True)
import pyvista as pv
print("  OK: pyvista导入成功", flush=True)

print("Step 5: 设置matplotlib后端...", flush=True)
import matplotlib
matplotlib.use('Agg')
print("  OK: matplotlib后端设置成功", flush=True)

dxf_path = r'D:\断面算量平台\测试文件\内湾段分层图（全航道底图20260318）面积比例0.6.dxf'

print(f"\nStep 6: 检查文件...", flush=True)
print(f"  路径: {dxf_path}", flush=True)
print(f"  存在: {os.path.exists(dxf_path)}", flush=True)

if not os.path.exists(dxf_path):
    print("[ERROR] 文件不存在!", flush=True)
    sys.exit(1)

print("\nStep 7: 读取DXF文件...", flush=True)
try:
    doc = ezdxf.readfile(dxf_path)
    print("  OK: DXF文件读取成功", flush=True)
except Exception as e:
    print(f"  ERROR: 读取失败 - {e}", flush=True)
    sys.exit(1)

print("\nStep 8: 获取模型空间...", flush=True)
msp = doc.modelspace()
print(f"  OK: 模型空间获取成功", flush=True)

print("\nStep 9: 统计实体数量...", flush=True)
layers = {}
for e in msp:
    layer = e.dxf.layer if hasattr(e.dxf, 'layer') else 'Unknown'
    if layer not in layers:
        layers[layer] = 0
    layers[layer] += 1

print(f"  总实体数: {sum(layers.values())}", flush=True)
print(f"  图层数: {len(layers)}", flush=True)

print("\n图层列表:", flush=True)
for layer, count in sorted(layers.items(), key=lambda x: -x[1])[:20]:
    print(f"  {layer}: {count}", flush=True)

print("\n测试完成!", flush=True)