# -*- coding: utf-8 -*-
import ezdxf

# 内湾背景.dxf
doc1 = ezdxf.readfile(r'D:\断面算量平台\测试文件\内湾背景.dxf')
m1 = doc1.modelspace()

# 内湾段分层图
doc2 = ezdxf.readfile(r'D:\断面算量平台\测试文件\内湾段分层图（全航道底图20260318）.dxf')
m2 = doc2.modelspace()

# 背景图桩号坐标
station_pts = []
for e in m1.query('TEXT'):
    try:
        text = e.dxf.text
        if 'K' in text:
            station_pts.append((e.dxf.insert.x, e.dxf.insert.y, text))
    except:
        pass

print("=== 内湾背景.dxf 桩号坐标 ===")
if station_pts:
    xs = [p[0] for p in station_pts]
    ys = [p[1] for p in station_pts]
    print(f"桩号数量: {len(station_pts)}")
    print(f"X范围: {min(xs):.1f} - {max(xs):.1f}")
    print(f"Y范围: {min(ys):.1f} - {max(ys):.1f}")
    print(f"示例桩号: {station_pts[:3]}")

# 分层图开挖线坐标
excav_pts = []
layers = [l.dxf.name for l in doc2.layers if '开挖线' in l.dxf.name]
print(f"\n=== 分层图开挖线图层: {layers} ===")

for layer in layers:
    for e in m2.query(f'*[layer=="{layer}"]'):
        try:
            if e.dxftype() == 'LWPOLYLINE':
                pts = [p[:2] for p in e.get_points()]
                excav_pts.extend(pts)
            elif e.dxftype() == 'LINE':
                excav_pts.append((e.dxf.start.x, e.dxf.start.y))
                excav_pts.append((e.dxf.end.x, e.dxf.end.y))
        except:
            pass

print(f"\n=== 分层图开挖线坐标 ===")
if excav_pts:
    xs = [p[0] for p in excav_pts]
    ys = [p[1] for p in excav_pts]
    print(f"点数量: {len(excav_pts)}")
    print(f"X范围: {min(xs):.1f} - {max(xs):.1f}")
    print(f"Y范围: {min(ys):.1f} - {max(ys):.1f}")
    print(f"示例点: {excav_pts[:3]}")