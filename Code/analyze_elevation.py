# -*- coding: utf-8 -*-
import json
import ezdxf

# 1. 分析JSON中的高程分布
with open(r'D:\断面算量平台\测试文件\断面XYZ数据.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

# 2. 检查DXF中开挖线的Y坐标范围
doc = ezdxf.readfile(r'D:\断面算量平台\测试文件\内湾段分层图（全航道底图20260318）.dxf')
msp = doc.modelspace()

kaiwa_lines = [e for e in msp if e.dxftype() == 'LINE' and '开挖线' in e.dxf.layer]
print(f'开挖线LINE数量: {len(kaiwa_lines)}')

if kaiwa_lines:
    y_values = []
    for line in kaiwa_lines[:50]:
        y_values.extend([line.dxf.start.y, line.dxf.end.y])
    print(f'前50条开挖线Y范围: {min(y_values):.2f} ~ {max(y_values):.2f}')

positive_kaiwa = []
negative_kaiwa = []
positive_chaowa = []
negative_chaowa = []

for sec in data['sections']:
    for pt in sec['kaiwa_xyz']:
        if pt[2] > 0:
            positive_kaiwa.append((sec['station'], pt[2], sec['scale_factor']))
        else:
            negative_kaiwa.append((sec['station'], pt[2]))
    for pt in sec['chaowa_xyz']:
        if pt[2] > 0:
            positive_chaowa.append((sec['station'], pt[2], sec['scale_factor']))
        else:
            negative_chaowa.append((sec['station'], pt[2]))

print('=== 高程分析 ===')
print(f'开挖线: 正高程点数={len(positive_kaiwa)}, 负高程点数={len(negative_kaiwa)}')
print(f'超挖线: 正高程点数={len(positive_chaowa)}, 负高程点数={len(negative_chaowa)}')

if positive_kaiwa:
    print(f'\n开挖线正高程范围: {min(p[1] for p in positive_kaiwa):.2f} ~ {max(p[1] for p in positive_kaiwa):.2f}')
if negative_kaiwa:
    print(f'开挖线负高程范围: {min(p[1] for p in negative_kaiwa):.2f} ~ {max(p[1] for p in negative_kaiwa):.2f}')

print('\n=== 标尺参数分析 ===')
for sec in data['sections'][:10]:
    a, b = sec['scale_factor']
    print(f'{sec["station"]}: a={a:.2f}, b={b:.2f} (水面Y={b:.2f})')

print('\n=== 正高程点示例（开挖线）===')
for p in positive_kaiwa[:5]:
    station, z, (a, b) = p
    # Y = a * z + b, 所以原Y坐标是多少?
    original_y = a * z + b
    print(f'{station}: z={z:.2f}m (高于水面), 标尺a={a:.2f}, b={b:.2f}, 对应CAD Y={original_y:.2f}')