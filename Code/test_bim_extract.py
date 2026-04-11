# -*- coding: utf-8 -*-
"""
测试BIM数据提取 - 不涉及可视化
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

print("="*60, flush=True)
print("测试BIM数据提取（无可视化）", flush=True)
print("="*60, flush=True)

print("\nStep 1: 导入模块...", flush=True)
import ezdxf
import numpy as np
from shapely.geometry import Polygon, LineString, Point, box
print("  OK: ezdxf, numpy, shapely", flush=True)

from bim_lofting_core import (
    BIMLoftingEngine, 
    GeologicalBody, 
    SectionMetadata
)
print("  OK: bim_lofting_core", flush=True)

dxf_path = r'D:\断面算量平台\测试文件\内湾段分层图（全航道底图20260318）面积比例0.6.dxf'

print(f"\nStep 2: 检查文件...", flush=True)
print(f"  路径: {dxf_path}", flush=True)
print(f"  存在: {os.path.exists(dxf_path)}", flush=True)

if not os.path.exists(dxf_path):
    print("[ERROR] 文件不存在!", flush=True)
    sys.exit(1)

print("\nStep 3: 读取DXF...", flush=True)
try:
    doc = ezdxf.readfile(dxf_path)
    msp = doc.modelspace()
    print(f"  OK: 读取成功", flush=True)
except Exception as e:
    print(f"  ERROR: {e}", flush=True)
    sys.exit(1)

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

print("\nStep 5: 提取桩号文本...", flush=True)
import re
stations = []
for e in msp.query('TEXT MTEXT'):
    try:
        txt = e.plain_text() if e.dxftype() == 'MTEXT' else e.dxf.text
        match = re.search(r'(\d+\+\d+)', txt.upper())
        if match:
            if e.dxftype() == 'TEXT':
                pt = (e.dxf.insert.x, e.dxf.insert.y)
            else:
                pt = (e.dxf.insert.x, e.dxf.insert.y)
            sid = match.group(1)
            nums = re.findall(r'\d+', sid)
            value = int("".join(nums)) if nums else 0
            stations.append({'text': sid, 'value': value, 'x': pt[0], 'y': pt[1]})
    except: pass
print(f"  OK: 桩号文本 {len(stations)}个", flush=True)

print("\nStep 6: 匹配DMX与桩号...", flush=True)
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
        matched.append({
            'station': station['text'],
            'value': station['value'],
            'dmx': sorted_dmx[best_idx]
        })
print(f"  OK: 匹配成功 {len(matched)}对", flush=True)

print("\nStep 7: 提取L1基准点...", flush=True)
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

h_lines = [l for l in lines if l['type'] == 'h']
v_lines = [l for l in lines if l['type'] == 'v']
h_lines.sort(key=lambda l: l['y'], reverse=True)
v_lines.sort(key=lambda l: l['y'], reverse=True)

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

print("\nStep 8: 创建断面元数据...", flush=True)
sections = []
for m in matched:
    # 找最近的基准点
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
            station_name=m['station'],
            station_value=m['value'],
            mileage=m['value'],
            surfaces=[body],
            volumes=[]
        )
        sections.append(section)

sections.sort(key=lambda s: s.station_value, reverse=True)
print(f"  OK: 创建 {len(sections)}个断面元数据", flush=True)

print("\nStep 9: 测试放样引擎...", flush=True)
engine = BIMLoftingEngine(num_samples=50)

if len(sections) >= 2:
    mileages = [s.mileage for s in sections[:5]]  # 只取前5个测试
    coords = [np.array(s.surfaces[0].points) for s in sections[:5]]
    
    print(f"  测试断面数: {len(mileages)}", flush=True)
    
    try:
        ribbon = engine.create_ribbon_mesh(mileages, coords)
        if ribbon:
            print(f"  OK: Ribbon Mesh成功, 顶点={ribbon.n_points}, 面={ribbon.n_cells}", flush=True)
        else:
            print("  WARN: Ribbon Mesh返回None", flush=True)
    except Exception as e:
        print(f"  ERROR: Ribbon Mesh失败 - {e}", flush=True)

print("\n" + "="*60, flush=True)
print("测试完成!", flush=True)
print("="*60, flush=True)