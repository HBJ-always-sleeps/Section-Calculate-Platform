# -*- coding: utf-8 -*-
"""比较新旧脊梁点数据"""
import json

# 加载旧版脊梁点
old_path = r'D:\断面算量平台\测试文件\内湾底图_脊梁点.json'
new_path = r'D:\断面算量平台\测试文件\内湾背景原始_脊梁点.json'

with open(old_path, encoding='utf-8') as f:
    old_data = json.load(f)

with open(new_path, encoding='utf-8') as f:
    new_data = json.load(f)

print("=" * 60)
print("脊梁点数据比较")
print("=" * 60)

print("\n旧版数据:")
print(f"  来源: {old_data.get('source', 'N/A')}")
print(f"  总数: {old_data['total_spine_points']}")
old_points = old_data['spine_points']
old_stations = sorted([p['station_value'] for p in old_points])
print(f"  桩号范围: K{old_stations[0]//1000}+{old_stations[0]%1000:03d} ~ K{old_stations[-1]//1000}+{old_stations[-1]%1000:03d}")
print(f"  桩号数量: {len(old_stations)}")

print("\n新版数据:")
print(f"  来源: {new_data.get('source', 'N/A')}")
print(f"  总数: {new_data['total_spine_points']}")
new_points = new_data['spine_points']
new_stations = sorted([p['station_value'] for p in new_points])
print(f"  桩号范围: K{new_stations[0]//1000}+{new_stations[0]%1000:03d} ~ K{new_stations[-1]//1000}+{new_stations[-1]%1000:03d}")
print(f"  桩号数量: {len(new_stations)}")

# 比较相同桩号的坐标差异
print("\n相同桩号坐标比较:")
old_dict = {p['station_value']: p for p in old_points}
new_dict = {p['station_value']: p for p in new_points}

common_stations = set(old_stations) & set(new_stations)
print(f"  共同桩号数: {len(common_stations)}")

if common_stations:
    max_diff_x = 0
    max_diff_y = 0
    max_diff_station = None
    
    for station in sorted(common_stations)[:10]:  # 先看前10个
        old_p = old_dict[station]
        new_p = new_dict[station]
        diff_x = abs(old_p['x'] - new_p['x'])
        diff_y = abs(old_p['y'] - new_p['y'])
        print(f"  K{station//1000}+{station%1000:03d}: 旧({old_p['x']:.2f}, {old_p['y']:.2f}) 新({new_p['x']:.2f}, {new_p['y']:.2f}) 差({diff_x:.2f}, {diff_y:.2f})")
        
        if diff_x > max_diff_x or diff_y > max_diff_y:
            max_diff_x = max(max_diff_x, diff_x)
            max_diff_y = max(max_diff_y, diff_y)
            max_diff_station = station
    
    print(f"\n  最大坐标差异: X={max_diff_x:.2f}m, Y={max_diff_y:.2f}m (桩号K{max_diff_station//1000}+{max_diff_station%1000:03d})")

# 检查新版独有的桩号
new_only = set(new_stations) - set(old_stations)
old_only = set(old_stations) - set(new_stations)

print(f"\n新版独有桩号: {len(new_only)}个")
if new_only:
    new_only_sorted = sorted(new_only)[:20]
    print(f"  前20个: {[f'K{s//1000}+{s%1000:03d}' for s in new_only_sorted]}")

print(f"\n旧版独有桩号: {len(old_only)}个")
if old_only:
    old_only_sorted = sorted(old_only)[:20]
    print(f"  前20个: {[f'K{s//1000}+{s%1000:03d}' for s in old_only_sorted]}")