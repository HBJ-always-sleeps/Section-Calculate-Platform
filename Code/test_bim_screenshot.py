# -*- coding: utf-8 -*-
"""
BIM模型截图生成 - 使用PyVista截图模式（非交互）
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

print("="*60, flush=True)
print("BIM模型截图生成", flush=True)
print("="*60, flush=True)

print("\nStep 1: 导入模块...", flush=True)
import ezdxf
import numpy as np
import re
import json
from shapely.geometry import Polygon, LineString, Point, box
print("  OK: 基础模块", flush=True)

from bim_lofting_core import (
    BIMLoftingEngine, 
    LayerMatcher,
    GeologicalBody, 
    SectionMetadata,
    get_layer_color, 
    get_layer_opacity
)
print("  OK: 核心放样引擎", flush=True)

import matplotlib
matplotlib.use('Agg')  # 非交互式后端
print("  OK: matplotlib Agg后端", flush=True)

import pyvista as pv
pv.OFF_SCREEN = True  # 强制离屏渲染
print("  OK: pyvista离屏模式", flush=True)

dxf_path = r'D:\断面算量平台\测试文件\内湾段分层图（全航道底图20260318）面积比例0.6.dxf'
output_dir = os.path.dirname(dxf_path)
base_name = os.path.splitext(os.path.basename(dxf_path))[0]
output_png = os.path.join(output_dir, f'{base_name}_bim_v2.png')
output_json = os.path.join(output_dir, f'{base_name}_bim_v2_metadata.json')

print(f"\nStep 2: 检查文件...", flush=True)
print(f"  输入: {dxf_path}", flush=True)
print(f"  输出: {output_png}", flush=True)

if not os.path.exists(dxf_path):
    print("[ERROR] 文件不存在!", flush=True)
    sys.exit(1)

print("\nStep 3: 读取DXF...", flush=True)
doc = ezdxf.readfile(dxf_path)
msp = doc.modelspace()
print(f"  OK: 实体数 {len(list(msp))}", flush=True)

print("\nStep 4: 提取DMX...", flush=True)
dmx_list = []
for e in msp.query('LWPOLYLINE[layer=="DMX"]'):
    try:
        pts = [(p[0], p[1]) for p in e.get_points()]
        if len(pts) >= 2:
            line = LineString(pts)
            x_coords = [p[0] for p in pts]
            y_coords = [p[1] for p in pts]
            dmx_list.append({
                'pts': pts,
                'line': line,
                'x_min': min(x_coords),
                'x_max': max(x_coords),
                'y_center': (min(y_coords) + max(y_coords)) / 2
            })
    except: pass
print(f"  OK: DMX断面线 {len(dmx_list)}条", flush=True)

print("\nStep 5: 提取桩号...", flush=True)
stations = []
for e in msp.query('TEXT MTEXT'):
    try:
        txt = e.plain_text() if e.dxftype() == 'MTEXT' else e.dxf.text
        match = re.search(r'(\d+\+\d+)', txt.upper())
        if match:
            pt = (e.dxf.insert.x, e.dxf.insert.y)
            sid = match.group(1)
            nums = re.findall(r'\d+', sid)
            value = int("".join(nums)) if nums else 0
            stations.append({'text': sid, 'value': value, 'x': pt[0], 'y': pt[1]})
    except: pass
print(f"  OK: 桩号 {len(stations)}个", flush=True)

print("\nStep 6: 提取L1基准点...", flush=True)
lines = []
for e in msp.query('*[layer=="L1"]'):
    try:
        if e.dxftype() == 'LINE':
            x1, y1 = e.dxf.start.x, e.dxf.start.y
            x2, y2 = e.dxf.end.x, e.dxf.end.y
            w, h = abs(x2-x1), abs(y2-y1)
            if w > h * 3:
                lines.append({'type': 'h', 'y': (y1+y2)/2, 'x': (x1+x2)/2})
            elif h > w * 3:
                lines.append({'type': 'v', 'x': (x1+x2)/2, 'y': (y1+y2)/2})
    except: pass

h_lines = sorted([l for l in lines if l['type'] == 'h'], key=lambda l: l['y'], reverse=True)
v_lines = sorted([l for l in lines if l['type'] == 'v'], key=lambda l: l['y'], reverse=True)

refs = []
used_h = set()
for v in v_lines:
    best_h = None
    best_diff = float('inf')
    best_idx = -1
    for h_idx, h in enumerate(h_lines):
        if h_idx in used_h:
            continue
        diff = abs(h['y'] - v['y'])
        if diff < best_diff:
            best_diff = diff
            best_h = h
            best_idx = h_idx
    if best_h and best_diff < 50:
        used_h.add(best_idx)
        refs.append({'ref_x': v['x'], 'ref_y': best_h['y']})
print(f"  OK: L1基准点 {len(refs)}个", flush=True)

print("\nStep 7: 匹配并创建断面...", flush=True)
sorted_stations = sorted(stations, key=lambda s: s['y'], reverse=True)
sorted_dmx = sorted(dmx_list, key=lambda d: d['y_center'], reverse=True)

matched = []
used_dmx = set()
for station in sorted_stations:
    best_idx = None
    best_dist = float('inf')
    for i, dmx in enumerate(sorted_dmx):
        if i in used_dmx:
            continue
        y_dist = abs(dmx['y_center'] - station['y'])
        if y_dist < best_dist:
            best_dist = y_dist
            best_idx = i
    if best_idx is not None and best_dist < 500:
        used_dmx.add(best_idx)
        matched.append({'station': station, 'dmx': sorted_dmx[best_idx]})
print(f"  OK: 匹配 {len(matched)}对", flush=True)

# 创建断面元数据
sections = []
for m in matched:
    best_ref = None
    best_dist = float('inf')
    for ref in refs:
        y_diff = abs(ref['ref_y'] - m['dmx']['y_center'])
        if y_diff < best_dist:
            best_dist = y_diff
            best_ref = ref
    
    if best_ref and best_dist < 200:
        ref_x, ref_y = best_ref['ref_x'], best_ref['ref_y']
        dmx_pts = [(p[0] - ref_x, p[1] - ref_y) for p in m['dmx']['pts']]
        
        body = GeologicalBody(
            layer_name='DMX',
            points=dmx_pts,
            centroid=(sum(p[0] for p in dmx_pts)/len(dmx_pts), sum(p[1] for p in dmx_pts)/len(dmx_pts)),
            area=0.0,
            is_closed=False
        )
        
        section = SectionMetadata(
            station_name=m['station']['text'],
            station_value=m['station']['value'],
            mileage=m['station']['value'],
            surfaces=[body],
            volumes=[]
        )
        sections.append(section)

sections.sort(key=lambda s: s.station_value, reverse=True)
print(f"  OK: 创建 {len(sections)}个断面", flush=True)

print("\nStep 8: 构建放样网格...", flush=True)
engine = BIMLoftingEngine(num_samples=50)

# 取前10个断面测试（避免太慢）
test_sections = sections[:10]
mileages = [s.mileage for s in test_sections]
coords = [np.array(s.surfaces[0].points) for s in test_sections]

print(f"  断面数: {len(mileages)}", flush=True)

mesh = engine.create_ribbon_mesh(mileages, coords)
if mesh:
    print(f"  OK: Ribbon Mesh成功", flush=True)
    print(f"      顶点: {mesh.n_points}", flush=True)
    print(f"      面: {mesh.n_cells}", flush=True)
else:
    print("  ERROR: Mesh构建失败", flush=True)
    sys.exit(1)

print("\nStep 9: 创建Plotter并截图...", flush=True)
try:
    plotter = pv.Plotter(off_screen=True, window_size=[1600, 900])
    plotter.set_background('white')
    
    # 添加DMX网格
    plotter.add_mesh(
        mesh,
        color='#2ecc71',  # 绿色
        opacity=1.0,
        smooth_shading=True,
        show_edges=False
    )
    
    # 设置视角
    plotter.camera_position = 'iso'
    plotter.camera.elevation = 25
    plotter.camera.azimuth = 45
    
    plotter.show_grid(color='gray', font_size=10)
    
    # 截图
    plotter.screenshot(output_png)
    print(f"  OK: 截图已保存", flush=True)
    print(f"      路径: {output_png}", flush=True)
    
except Exception as e:
    print(f"  ERROR: 截图失败 - {e}", flush=True)
    sys.exit(1)

print("\nStep 10: 保存元数据...", flush=True)
try:
    data = {
        'file_name': os.path.basename(dxf_path),
        'total_sections': len(sections),
        'mesh_vertices': mesh.n_points,
        'mesh_faces': mesh.n_cells,
        'sample_sections': [
            {
                'station_name': s.station_name,
                'station_value': s.station_value,
                'mileage': s.mileage,
                'points_count': len(s.surfaces[0].points)
            }
            for s in test_sections
        ]
    }
    
    with open(output_json, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    
    print(f"  OK: 元数据已保存", flush=True)
    print(f"      路径: {output_json}", flush=True)
except Exception as e:
    print(f"  WARN: 元数据保存失败 - {e}", flush=True)

print("\n" + "="*60, flush=True)
print("截图生成完成!", flush=True)
print("="*60, flush=True)