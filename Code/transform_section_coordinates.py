# -*- coding: utf-8 -*-
"""
断面坐标转换与方向对齐

功能：
1. 建立CAD局部坐标到工程坐标的转换关系
2. 将断面所有点转换到工程坐标系
3. 计算断面法线方向（与中心线切线垂直）
4. 更新JSON元数据

坐标转换原理：
- 断面CAD局部坐标：以断面自身为原点
- 工程坐标：真实地理坐标
- 转换：平移 + 旋转
  - 平移：L1基准点在CAD坐标中的位置 → 脊梁点工程坐标
  - 旋转：断面方向与中心线切线垂直

作者: @黄秉俊
日期: 2026-04-02
"""

import json
import math
from typing import Dict, List, Tuple, Optional
import numpy as np

def load_json(path: str) -> Dict:
    """加载JSON文件"""
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)

def save_json(path: str, data: Dict):
    """保存JSON文件"""
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def transform_point(x: float, y: float, 
                    ref_x: float, ref_y: float,
                    spine_x: float, spine_y: float,
                    rotation_angle: float) -> Tuple[float, float]:
    """
    坐标转换：CAD局部坐标 → 工程坐标
    
    Args:
        x, y: CAD局部坐标
        ref_x, ref_y: L1基准点在CAD坐标中的位置
        spine_x, spine_y: 脊梁点工程坐标
        rotation_angle: 旋转角度（弧度），使断面与切线垂直
    
    Returns:
        工程坐标 (eng_x, eng_y)
    """
    # 1. 相对于L1基准点的偏移
    dx = x - ref_x
    dy = y - ref_y
    
    # 2. 旋转（使断面与切线垂直）
    # 断面原本是垂直的（X方向），需要旋转到与切线垂直
    cos_a = math.cos(rotation_angle)
    sin_a = math.sin(rotation_angle)
    rotated_dx = dx * cos_a - dy * sin_a
    rotated_dy = dx * sin_a + dy * cos_a
    
    # 3. 平移到脊梁点位置
    eng_x = spine_x + rotated_dx
    eng_y = spine_y + rotated_dy
    
    return eng_x, eng_y

def calculate_normal_angle(tangent_angle: float) -> float:
    """
    计算法线方向角（与切线垂直）
    
    断面方向应与航道中心线切线垂直
    法线方向 = 切线方向 + 90°
    """
    return tangent_angle + math.pi / 2

def transform_section(section: Dict, spine_match: Dict) -> Dict:
    """
    转换单个断面的所有坐标
    
    Args:
        section: 断面数据
        spine_match: 匹配的脊梁点数据
    
    Returns:
        转换后的断面数据
    """
    # 获取转换参数
    l1_ref = section.get('l1_ref_point', {})
    ref_x = l1_ref.get('ref_x', 0)
    ref_y = l1_ref.get('ref_y', 0)
    
    # 脊梁点字段名是'x'和'y'
    spine_x = spine_match['x']
    spine_y = spine_match['y']
    tangent_angle = spine_match['tangent_angle']
    
    # 计算断面法线方向（与切线垂直）
    normal_angle = calculate_normal_angle(tangent_angle)
    
    # 旋转角度：使断面垂直方向对齐法线方向
    # 断面原本Y轴向上，需要旋转到法线方向
    rotation_angle = normal_angle - math.pi / 2  # 减去原始Y轴方向
    
    # 创建转换后的断面副本
    transformed = section.copy()
    
    # 添加工程坐标信息
    transformed['engineering_coords'] = {
        'spine_x': spine_x,
        'spine_y': spine_y,
        'tangent_angle': tangent_angle,
        'normal_angle': normal_angle,
        'rotation_angle': rotation_angle
    }
    
    # 转换L1基准点工程坐标
    eng_l1_x, eng_l1_y = transform_point(
        ref_x, ref_y,
        ref_x, ref_y,
        spine_x, spine_y,
        rotation_angle
    )
    transformed['engineering_coords']['l1_eng_x'] = eng_l1_x
    transformed['engineering_coords']['l1_eng_y'] = eng_l1_y
    
    # 转换DMX点
    dmx_points = section.get('dmx_points', [])
    if dmx_points:
        transformed_dmx = []
        for pt in dmx_points:
            eng_x, eng_y = transform_point(
                pt[0], pt[1],
                ref_x, ref_y,
                spine_x, spine_y,
                rotation_angle
            )
            transformed_dmx.append([eng_x, eng_y])
        transformed['dmx_points_eng'] = transformed_dmx
    
    # 转换超挖线
    overbreak_points = section.get('overbreak_points', [])
    if overbreak_points:
        transformed_ob = []
        for line in overbreak_points:
            transformed_line = []
            for pt in line:
                eng_x, eng_y = transform_point(
                    pt[0], pt[1],
                    ref_x, ref_y,
                    spine_x, spine_y,
                    rotation_angle
                )
                transformed_line.append([eng_x, eng_y])
            transformed_ob.append(transformed_line)
        transformed['overbreak_points_eng'] = transformed_ob
    
    # 转换填充边界
    fill_boundaries = section.get('fill_boundaries', {})
    if fill_boundaries:
        transformed_fill = {}
        for layer_name, boundaries in fill_boundaries.items():
            transformed_bounds = []
            for boundary in boundaries:
                transformed_b = []
                for pt in boundary:
                    eng_x, eng_y = transform_point(
                        pt[0], pt[1],
                        ref_x, ref_y,
                        spine_x, spine_y,
                        rotation_angle
                    )
                    transformed_b.append([eng_x, eng_y])
                transformed_bounds.append(transformed_b)
            transformed_fill[layer_name] = transformed_bounds
        transformed['fill_boundaries_eng'] = transformed_fill
    
    return transformed

def main():
    spine_json = r'D:\断面算量平台\测试文件\内湾底图_脊梁点.json'
    section_json = r'D:\断面算量平台\测试文件\内湾段分层图（全航道底图20260331）2018面积比例0.6_bim_metadata.json'
    output_json = r'D:\断面算量平台\测试文件\断面元数据_工程坐标.json'
    
    print("=" * 60)
    print("断面坐标转换与方向对齐")
    print("=" * 60)
    
    # 1. 加载数据
    print("\n[1] 加载数据...")
    spine_data = load_json(spine_json)
    section_data = load_json(section_json)
    
    # 构建脊梁点索引
    spine_index = {}
    for sp in spine_data['spine_points']:
        spine_index[sp['station_value']] = sp
    
    print(f"  脊梁点: {len(spine_index)}个")
    print(f"  断面: {section_data['total_sections']}个")
    
    # 2. 转换断面坐标
    print("\n[2] 转换断面坐标...")
    transformed_sections = []
    match_count = 0
    
    for section in section_data['sections']:
        station_val = section.get('station_value')
        if station_val and station_val in spine_index:
            spine_match = spine_index[station_val]
            transformed = transform_section(section, spine_match)
            transformed_sections.append(transformed)
            match_count += 1
        else:
            # 未匹配的断面保留原样
            transformed_sections.append(section)
    
    print(f"  成功转换: {match_count}个断面")
    
    # 3. 创建输出数据
    print("\n[3] 创建输出数据...")
    output_data = section_data.copy()
    output_data['sections'] = transformed_sections
    output_data['coordinate_transformation'] = {
        'source_crs': 'CAD局部坐标',
        'target_crs': '工程坐标',
        'transformed_sections': match_count,
        'spine_source': spine_json
    }
    
    # 4. 保存结果
    print(f"\n[4] 保存到: {output_json}")
    save_json(output_json, output_data)
    
    # 5. 显示转换示例
    print("\n[5] 转换示例（前3个断面）:")
    for i, sec in enumerate(transformed_sections[:3]):
        if 'engineering_coords' in sec:
            ec = sec['engineering_coords']
            print(f"  [{i+1}] {sec['station_name']}")
            print(f"      脊梁点: ({ec['spine_x']:.2f}, {ec['spine_y']:.2f})")
            print(f"      切线角: {math.degrees(ec['tangent_angle']):.1f}°")
            print(f"      法线角: {math.degrees(ec['normal_angle']):.1f}°")
            print(f"      旋转角: {math.degrees(ec['rotation_angle']):.1f}°")
    
    print("\n" + "=" * 60)
    print("完成!")
    print("=" * 60)

if __name__ == '__main__':
    main()