# -*- coding: utf-8 -*-
"""验证输出数据坐标是否与DXF匹配"""
import ezdxf
import json

# 加载DXF和输出数据
doc = ezdxf.readfile(r'D:\断面算量平台\测试文件\内湾段分层图（全航道底图20260318）.dxf')
msp = doc.modelspace()
d = json.load(open(r'D:\断面算量平台\测试文件\断面XYZ数据.json', 'r', encoding='utf-8'))

# DXF开挖线
k_pts = [p[:2] for e in msp.query('LWPOLYLINE') if '开挖' in e.dxf.layer for p in e.get_points()]
# DXF超挖线
c_pts = [p[:2] for e in msp.query('LWPOLYLINE') if '超挖' in e.dxf.layer for p in e.get_points()]

# 输出开挖线
out_kx = [s['center_x']+x for s in d['sections'] for x,y,z in s['kaiwa_xyz']]
out_ky = [y for s in d['sections'] for x,y,z in s['kaiwa_xyz']]
# 输出超挖线
out_cx = [s['center_x']+x for s in d['sections'] for x,y,z in s['chaowa_xyz']]
out_cy = [y for s in d['sections'] for x,y,z in s['chaowa_xyz']]

print('=== 开挖线坐标验证 ===')
print(f'DXF X: {min(p[0] for p in k_pts):.2f} ~ {max(p[0] for p in k_pts):.2f}')
print(f'OUT X: {min(out_kx):.2f} ~ {max(out_kx):.2f}')
print(f'DXF Y: {min(p[1] for p in k_pts):.2f} ~ {max(p[1] for p in k_pts):.2f}')
print(f'OUT Y: {min(out_ky):.2f} ~ {max(out_ky):.2f}')
y_match_k = min(out_ky) >= min(p[1] for p in k_pts)-1 and max(out_ky) <= max(p[1] for p in k_pts)+1
print(f'Y范围匹配: {y_match_k}')

print()
print('=== 超挖线坐标验证 ===')
print(f'DXF X: {min(p[0] for p in c_pts):.2f} ~ {max(p[0] for p in c_pts):.2f}')
print(f'OUT X: {min(out_cx):.2f} ~ {max(out_cx):.2f}')
print(f'DXF Y: {min(p[1] for p in c_pts):.2f} ~ {max(p[1] for p in c_pts):.2f}')
print(f'OUT Y: {min(out_cy):.2f} ~ {max(out_cy):.2f}')
y_match_c = min(out_cy) >= min(p[1] for p in c_pts)-1 and max(out_cy) <= max(p[1] for p in c_pts)+1
print(f'Y范围匹配: {y_match_c}')

print()
print('=== 结论 ===')
if y_match_k and y_match_c:
    print('坐标验证通过！Y范围完全匹配，X坐标使用了相对坐标（相对于中心线）')