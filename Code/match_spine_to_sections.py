# -*- coding: utf-8 -*-
"""
脊梁点与断面L1基准点坐标匹配对齐

功能：
1. 读取脊梁点JSON（从内湾底图提取）
2. 读取断面JSON元数据（含L1基准点）
3. 通过桩号值匹配
4. 计算坐标偏差
5. 生成对齐报告

作者: @黄秉俊
日期: 2026-04-02
"""

import json
import math
from typing import Dict, List, Tuple, Optional

def load_json(path: str) -> Dict:
    """加载JSON文件"""
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)

def parse_station_value(station_name: str) -> Optional[int]:
    """解析桩号名称，返回桩号值（米）"""
    try:
        name = station_name.strip().replace('K', '').replace('k', '')
        if '+' in name:
            parts = name.split('+')
            if len(parts) == 2:
                km = int(parts[0])
                m = int(parts[1])
                return km * 1000 + m
    except:
        pass
    return None

def calculate_distance(p1: Tuple[float, float], p2: Tuple[float, float]) -> float:
    """计算两点间距离"""
    return math.sqrt((p1[0] - p2[0])**2 + (p1[1] - p2[1])**2)

def match_spine_to_sections(spine_data: Dict, section_data: Dict) -> List[Dict]:
    """
    匹配脊梁点与断面L1基准点
    
    Args:
        spine_data: 脊梁点数据
        section_data: 断面元数据
    
    Returns:
        匹配结果列表
    """
    # 构建脊梁点桩号索引
    spine_index = {}
    for sp in spine_data['spine_points']:
        station_val = sp['station_value']
        spine_index[station_val] = sp
    
    # 构建断面桩号索引
    section_index = {}
    for sec in section_data['sections']:
        station_val = sec.get('station_value')
        if station_val:
            section_index[station_val] = sec
    
    # 匹配
    matches = []
    for station_val, spine_pt in spine_index.items():
        if station_val in section_index:
            section = section_index[station_val]
            l1_ref = section.get('l1_ref_point')
            
            if l1_ref:
                # 脊梁点坐标（真实工程坐标）
                spine_x = spine_pt['x']
                spine_y = spine_pt['y']
                
                # L1基准点坐标（断面局部坐标）
                l1_x = l1_ref['ref_x']
                l1_y = l1_ref['ref_y']
                
                # 注意：L1基准点是断面局部坐标，脊梁点是工程坐标
                # 需要通过断面bounds计算偏移
                
                # 获取断面边界
                bounds = section.get('bounds', {})
                if bounds:
                    # 断面中心坐标（工程坐标）
                    section_center_x = (bounds['x_min'] + bounds['x_max']) / 2
                    section_center_y = (bounds['y_min'] + bounds['y_max']) / 2
                    
                    # L1在断面局部坐标中的位置
                    # L1相对于断面中心的偏移
                    l1_offset_x = l1_x - section_center_x
                    l1_offset_y = l1_y - section_center_y
                    
                    matches.append({
                        'station_name': spine_pt['station_name'],
                        'station_value': station_val,
                        'spine_x': spine_x,
                        'spine_y': spine_y,
                        'l1_x': l1_x,
                        'l1_y': l1_y,
                        'section_center_x': section_center_x,
                        'section_center_y': section_center_y,
                        'tangent_angle': spine_pt['tangent_angle']
                    })
    
    return matches

def analyze_coordinate_system(matches: List[Dict]) -> Dict:
    """
    分析坐标系关系
    
    断面JSON中的坐标是CAD局部坐标
    脊梁点坐标是真实工程坐标
    
    需要找到转换关系
    """
    if not matches:
        return {}
    
    # 计算断面中心与脊梁点的偏移
    offsets = []
    for m in matches:
        # 断面中心到脊梁点的向量
        dx = m['spine_x'] - m['section_center_x']
        dy = m['spine_y'] - m['section_center_y']
        offsets.append((dx, dy))
    
    # 计算平均偏移
    avg_dx = sum(o[0] for o in offsets) / len(offsets)
    avg_dy = sum(o[1] for o in offsets) / len(offsets)
    
    # 计算标准差
    std_dx = math.sqrt(sum((o[0] - avg_dx)**2 for o in offsets) / len(offsets))
    std_dy = math.sqrt(sum((o[1] - avg_dy)**2 for o in offsets) / len(offsets))
    
    return {
        'avg_offset_x': avg_dx,
        'avg_offset_y': avg_dy,
        'std_offset_x': std_dx,
        'std_offset_y': std_dy,
        'sample_count': len(matches)
    }

def main():
    spine_json = r'D:\断面算量平台\测试文件\内湾底图_脊梁点.json'
    section_json = r'D:\断面算量平台\测试文件\内湾段分层图（全航道底图20260331）2018面积比例0.6_bim_metadata.json'
    output_json = r'D:\断面算量平台\测试文件\脊梁点_L1匹配结果.json'
    
    print("=" * 60)
    print("脊梁点与L1基准点坐标匹配")
    print("=" * 60)
    
    # 1. 加载数据
    print("\n[1] 加载数据...")
    spine_data = load_json(spine_json)
    section_data = load_json(section_json)
    print(f"  脊梁点数量: {spine_data['total_spine_points']}")
    print(f"  断面数量: {section_data['total_sections']}")
    
    # 2. 匹配
    print("\n[2] 匹配脊梁点与断面...")
    matches = match_spine_to_sections(spine_data, section_data)
    print(f"  成功匹配: {len(matches)}对")
    
    # 3. 分析坐标系
    print("\n[3] 分析坐标系关系...")
    analysis = analyze_coordinate_system(matches)
    print(f"  样本数: {analysis['sample_count']}")
    print(f"  平均偏移 X: {analysis['avg_offset_x']:.2f} ± {analysis['std_offset_x']:.2f}")
    print(f"  平均偏移 Y: {analysis['avg_offset_y']:.2f} ± {analysis['std_offset_y']:.2f}")
    
    # 4. 显示匹配示例
    print("\n[4] 匹配示例（前5个）:")
    for i, m in enumerate(matches[:5]):
        print(f"  [{i+1}] {m['station_name']}")
        print(f"      脊梁点: ({m['spine_x']:.2f}, {m['spine_y']:.2f})")
        print(f"      断面中心: ({m['section_center_x']:.2f}, {m['section_center_y']:.2f})")
        print(f"      L1基准点: ({m['l1_x']:.2f}, {m['l1_y']:.2f})")
    
    # 5. 保存结果
    print(f"\n[5] 保存到: {output_json}")
    output_data = {
        'spine_source': spine_json,
        'section_source': section_json,
        'total_matches': len(matches),
        'coordinate_analysis': analysis,
        'matches': matches
    }
    with open(output_json, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)
    
    print("\n" + "=" * 60)
    print("完成!")
    print("=" * 60)

if __name__ == '__main__':
    main()