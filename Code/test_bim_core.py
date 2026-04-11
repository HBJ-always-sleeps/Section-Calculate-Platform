# -*- coding: utf-8 -*-
"""
测试BIM核心放样引擎
简化版本，只验证核心算法是否工作
"""

import numpy as np
import sys
import os

# 添加路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

print("="*60)
print("测试BIM核心放样引擎")
print("="*60)

# 测试1: 导入核心模块
print("\n[测试1] 导入核心模块...")
try:
    from bim_lofting_core import (
        BIMLoftingEngine, 
        GeologicalBody, 
        SectionMetadata,
        get_layer_color, 
        get_layer_opacity
    )
    print("  OK: 成功导入 bim_lofting_core")
except Exception as e:
    print(f"  ERROR: 导入失败 - {e}")
    sys.exit(1)

# 测试2: 创建放样引擎
print("\n[测试2] 创建放样引擎...")
try:
    engine = BIMLoftingEngine(num_samples=50)
    print(f"  OK: 创建引擎成功, num_samples={engine.num_samples}")
except Exception as e:
    print(f"  ERROR: 创建引擎失败 - {e}")
    sys.exit(1)

# 测试3: 测试锚点同步算法
print("\n[测试3] 测试锚点同步算法...")
try:
    # 创建一个简单的多边形（矩形）
    coords = np.array([
        [0, 0],
        [10, 0],
        [10, 5],
        [0, 5],
        [0, 0]  # 闭合
    ])
    
    aligned = engine.sync_anchor_points(coords)
    print(f"  OK: 锚点同步成功, 输出形状={aligned.shape}")
    print(f"      第一个点（锚点）: x={aligned[0,0]:.2f}, z={aligned[0,1]:.2f}")
except Exception as e:
    print(f"  ERROR: 锚点同步失败 - {e}")
    sys.exit(1)

# 测试4: 创建Ribbon Mesh
print("\n[测试4] 测试Ribbon Mesh...")
try:
    import pyvista as pv
    
    # 创建两个断面的线条
    mileage_list = [100, 200]
    coords_list = [
        np.array([[0, 0], [5, 1], [10, 0]]),  # 断面1
        np.array([[0, 0], [6, 2], [12, 0]]),  # 断面2
    ]
    
    ribbon = engine.create_ribbon_mesh(mileage_list, coords_list)
    if ribbon:
        print(f"  OK: Ribbon Mesh创建成功, 顶点={ribbon.n_points}, 面={ribbon.n_cells}")
    else:
        print("  WARN: Ribbon Mesh返回None")
except Exception as e:
    print(f"  ERROR: Ribbon Mesh失败 - {e}")

# 测试5: 创建Volume Mesh
print("\n[测试5] 测试Volume Mesh...")
try:
    # 创建两个闭合多边形
    mileage_list = [100, 200]
    coords_list = [
        np.array([[0, 0], [10, 0], [10, 5], [0, 5]]),  # 断面1
        np.array([[0, 0], [12, 0], [12, 6], [0, 6]]),  # 断面2
    ]
    
    volume = engine.create_volume_mesh(mileage_list, coords_list)
    if volume:
        print(f"  OK: Volume Mesh创建成功, 顶点={volume.n_points}, 面={volume.n_cells}")
    else:
        print("  WARN: Volume Mesh返回None")
except Exception as e:
    print(f"  ERROR: Volume Mesh失败 - {e}")

# 测试6: 测试颜色和透明度
print("\n[测试6] 测试颜色映射...")
try:
    color_dmx = get_layer_color('DMX')
    color_sand = get_layer_color('6级砂')
    opacity_dmx = get_layer_opacity('DMX')
    print(f"  OK: DMX颜色={color_dmx}, 透明度={opacity_dmx}")
    print(f"      6级砂颜色={color_sand}")
except Exception as e:
    print(f"  ERROR: 颜色映射失败 - {e}")

# 测试7: 测试数据结构
print("\n[测试7] 测试数据结构...")
try:
    body = GeologicalBody(
        layer_name='测试层',
        points=[(0, 0), (10, 0), (10, 5)],
        centroid=(5, 2.5),
        area=50.0,
        is_closed=False
    )
    print(f"  OK: GeologicalBody创建成功: {body.layer_name}")
    
    section = SectionMetadata(
        station_name='6+742',
        station_value=6742,
        mileage=6742,
        surfaces=[body],
        volumes=[]
    )
    print(f"  OK: SectionMetadata创建成功: {section.station_name}")
except Exception as e:
    print(f"  ERROR: 数据结构测试失败 - {e}")

print("\n" + "="*60)
print("测试完成!")
print("="*60)