# -*- coding: utf-8 -*-
"""
DXF异常坐标点检测工具
找出不在正常坐标范围内的异常点，这些点会导致AutoCAD zoom extents显示问题
"""

import ezdxf
import sys
import os
import numpy as np
from collections import defaultdict

def find_anomalous_coords(dxf_path, expected_x_range=None, expected_y_range=None, expected_z_range=None):
    """找出DXF文件中的异常坐标点
    
    Args:
        dxf_path: DXF文件路径
        expected_x_range: 期望的X坐标范围 (min, max)，如不提供则自动推断
        expected_y_range: 期望的Y坐标范围 (min, max)
        expected_z_range: 期望的Z坐标范围 (min, max)
    """
    print(f"\n=== DXF Anomalous Coordinates Detection ===")
    print(f"File: {dxf_path}")
    
    if not os.path.exists(dxf_path):
        print(f"ERROR: File not found!")
        return
    
    try:
        doc = ezdxf.readfile(dxf_path)
        msp = doc.modelspace()
        
        # 收集所有坐标点
        all_coords = []  # (x, y, z, entity_type, layer, entity_id)
        layer_coords = defaultdict(list)  # 按图层分组
        
        entities = list(msp.query('*'))
        print(f"\nTotal entities: {len(entities)}")
        
        for i, e in enumerate(entities):
            coords = []
            entity_type = e.dxftype()
            layer = e.dxf.layer if hasattr(e.dxf, 'layer') else 'unknown'
            
            if entity_type == '3DFACE':
                try:
                    for vtx_name in ['vtx0', 'vtx1', 'vtx2', 'vtx3']:
                        vtx = getattr(e, vtx_name, None)
                        if vtx is not None:
                            coords.append((vtx.x, vtx.y, vtx.z))
                except Exception as ex:
                    pass
            elif entity_type == 'POLYLINE3D' or entity_type == 'POLYLINE':
                try:
                    for v in e.vertices:
                        loc = v.dxf.location
                        coords.append((loc.x, loc.y, loc.z))
                except Exception as ex:
                    pass
            elif entity_type == 'LINE':
                try:
                    coords.append((e.dxf.start.x, e.dxf.start.y, e.dxf.start.z))
                    coords.append((e.dxf.end.x, e.dxf.end.y, e.dxf.end.z))
                except Exception as ex:
                    pass
            elif entity_type == 'POINT':
                try:
                    loc = e.dxf.location
                    coords.append((loc.x, loc.y, loc.z))
                except Exception as ex:
                    pass
            
            for coord in coords:
                all_coords.append((coord[0], coord[1], coord[2], entity_type, layer, i))
                layer_coords[layer].append(coord)
        
        if not all_coords:
            print("No coordinates found!")
            return
        
        # 转换为numpy数组便于分析
        coords_array = np.array([(c[0], c[1], c[2]) for c in all_coords])
        
        # 计算坐标范围
        x_min, x_max = coords_array[:, 0].min(), coords_array[:, 0].max()
        y_min, y_max = coords_array[:, 1].min(), coords_array[:, 1].max()
        z_min, z_max = coords_array[:, 2].min(), coords_array[:, 2].max()
        
        print(f"\n=== Overall Coordinate Range ===")
        print(f"X: {x_min:.2f} ~ {x_max:.2f} (span: {x_max - x_min:.2f}m)")
        print(f"Y: {y_min:.2f} ~ {y_max:.2f} (span: {y_max - y_min:.2f}m)")
        print(f"Z: {z_min:.2f} ~ {z_max:.2f} (span: {z_max - z_min:.2f}m)")
        
        # 检查EXTMIN/EXTMAX头变量
        print(f"\n=== Header EXTMIN/EXTMAX ===")
        try:
            extmin = doc.header.get('$EXTMIN', None)
            extmax = doc.header.get('$EXTMAX', None)
            if extmin and extmax:
                print(f"$EXTMIN: ({extmin[0]}, {extmin[1]}, {extmin[2]})")
                print(f"$EXTMAX: ({extmax[0]}, {extmax[1]}, {extmax[2]})")
                
                # 检查是否与实际坐标范围一致
                if abs(extmin[0] - x_min) > 100 or abs(extmax[0] - x_max) > 100:
                    print(f"[WARN] EXTMIN/EXTMAX X range differs from actual coordinates!")
                    print(f"  Header X range: {extmin[0]} ~ {extmax[0]}")
                    print(f"  Actual X range: {x_min:.2f} ~ {x_max:.2f}")
                
                if abs(extmin[1] - y_min) > 100 or abs(extmax[1] - y_max) > 100:
                    print(f"[WARN] EXTMIN/EXTMAX Y range differs from actual coordinates!")
                    print(f"  Header Y range: {extmin[1]} ~ {extmax[1]}")
                    print(f"  Actual Y range: {y_min:.2f} ~ {y_max:.2f}")
            else:
                print(f"$EXTMIN/$EXTMAX: NOT SET!")
        except Exception as e:
            print(f"Error reading EXTMIN/EXTMAX: {e}")
        
        # 按图层分析坐标范围
        print(f"\n=== Layer Coordinate Analysis ===")
        for layer, coords in sorted(layer_coords.items()):
            layer_array = np.array(coords)
            lx_min, lx_max = layer_array[:, 0].min(), layer_array[:, 0].max()
            ly_min, ly_max = layer_array[:, 1].min(), layer_array[:, 1].max()
            lz_min, lz_max = layer_array[:, 2].min(), layer_array[:, 2].max()
            print(f"\nLayer: {layer}")
            print(f"  Points: {len(coords)}")
            print(f"  X: {lx_min:.2f} ~ {lx_max:.2f}")
            print(f"  Y: {ly_min:.2f} ~ {ly_max:.2f}")
            print(f"  Z: {lz_min:.2f} ~ {lz_max:.2f}")
        
        # 找出异常坐标点
        # 使用统计方法：如果坐标偏离主群超过3倍标准差，视为异常
        print(f"\n=== Anomalous Coordinates Detection ===")
        
        # 计算主坐标群的中心（使用中位数更稳健）
        x_median = np.median(coords_array[:, 0])
        y_median = np.median(coords_array[:, 1])
        z_median = np.median(coords_array[:, 2])
        
        # 计算标准差
        x_std = np.std(coords_array[:, 0])
        y_std = np.std(coords_array[:, 1])
        z_std = np.std(coords_array[:, 2])
        
        print(f"Median coordinates:")
        print(f"  X median: {x_median:.2f}, std: {x_std:.2f}")
        print(f"  Y median: {y_median:.2f}, std: {y_std:.2f}")
        print(f"  Z median: {z_median:.2f}, std: {z_std:.2f}")
        
        # 定义正常范围（使用工程坐标的合理范围）
        # 根据之前的测试结果，正常坐标范围应该是：
        # X: 505243 ~ 509486 m
        # Y: 2374772 ~ 2379134 m
        # Z: -71 ~ -15 m
        
        # 自动推断正常范围：使用坐标密度最高的区域
        # 使用百分位数来定义正常范围
        x_q1, x_q99 = np.percentile(coords_array[:, 0], [1, 99])
        y_q1, y_q99 = np.percentile(coords_array[:, 1], [1, 99])
        z_q1, z_q99 = np.percentile(coords_array[:, 2], [1, 99])
        
        print(f"\nCoordinate percentile ranges (1%-99%):")
        print(f"  X: {x_q1:.2f} ~ {x_q99:.2f}")
        print(f"  Y: {y_q1:.2f} ~ {y_q99:.2f}")
        print(f"  Z: {z_q1:.2f} ~ {z_q99:.2f}")
        
        # 找出超出正常范围的异常点
        anomalous_points = []
        
        # 使用更宽松的阈值：超出99百分位数10倍范围视为异常
        x_range = x_q99 - x_q1
        y_range = y_q99 - y_q1
        z_range = z_q99 - z_q1
        
        x_lower = x_q1 - x_range * 0.5
        x_upper = x_q99 + x_range * 0.5
        y_lower = y_q1 - y_range * 0.5
        y_upper = y_q99 + y_range * 0.5
        z_lower = z_q1 - z_range * 0.5
        z_upper = z_q99 + z_range * 0.5
        
        print(f"\nNormal range threshold:")
        print(f"  X: {x_lower:.2f} ~ {x_upper:.2f}")
        print(f"  Y: {y_lower:.2f} ~ {y_upper:.2f}")
        print(f"  Z: {z_lower:.2f} ~ {z_upper:.2f}")
        
        for coord in all_coords:
            x, y, z, entity_type, layer, entity_id = coord
            
            # 检查是否为异常坐标
            is_anomalous = False
            anomaly_reason = []
            
            # 检查极端值（如0, 1e20等）
            if x == 0 or y == 0 or z == 0:
                # 允许Z=0，但X和Y为0通常是异常
                if x == 0 and y == 0:
                    is_anomalous = True
                    anomaly_reason.append("X=0, Y=0")
            
            # 检查超出正常范围
            if x < x_lower or x > x_upper:
                is_anomalous = True
                anomaly_reason.append(f"X={x:.2f} out of range [{x_lower:.2f}, {x_upper:.2f}]")
            
            if y < y_lower or y > y_upper:
                is_anomalous = True
                anomaly_reason.append(f"Y={y:.2f} out of range [{y_lower:.2f}, {y_upper:.2f}]")
            
            if z < z_lower or z > z_upper:
                is_anomalous = True
                anomaly_reason.append(f"Z={z:.2f} out of range [{z_lower:.2f}, {z_upper:.2f}]")
            
            # 检查极端大值（如1e20）
            if abs(x) > 1e10 or abs(y) > 1e10 or abs(z) > 1e10:
                is_anomalous = True
                anomaly_reason.append(f"Extreme value detected")
            
            if is_anomalous:
                anomalous_points.append({
                    'coord': (x, y, z),
                    'entity_type': entity_type,
                    'layer': layer,
                    'entity_id': entity_id,
                    'reason': ', '.join(anomaly_reason)
                })
        
        # 输出异常点统计
        print(f"\n=== Anomalous Points Summary ===")
        print(f"Total anomalous points: {len(anomalous_points)}")
        
        if anomalous_points:
            # 按图层统计异常点
            layer_anomaly_count = defaultdict(int)
            for p in anomalous_points:
                layer_anomaly_count[p['layer']] += 1
            
            print(f"\nAnomalous points by layer:")
            for layer, count in sorted(layer_anomaly_count.items(), key=lambda x: -x[1]):
                print(f"  {layer}: {count} points")
            
            # 输出前20个异常点的详细信息
            print(f"\nFirst 20 anomalous points detail:")
            for i, p in enumerate(anomalous_points[:20]):
                print(f"  [{i}] ({p['coord'][0]:.2f}, {p['coord'][1]:.2f}, {p['coord'][2]:.2f})")
                print(f"      Entity: {p['entity_type']}, Layer: {p['layer']}, ID: {p['entity_id']}")
                print(f"      Reason: {p['reason']}")
            
            # 输出异常坐标的范围
            anomalous_coords = np.array([p['coord'] for p in anomalous_points])
            print(f"\nAnomalous coordinates range:")
            print(f"  X: {anomalous_coords[:, 0].min():.2f} ~ {anomalous_coords[:, 0].max():.2f}")
            print(f"  Y: {anomalous_coords[:, 1].min():.2f} ~ {anomalous_coords[:, 1].max():.2f}")
            print(f"  Z: {anomalous_coords[:, 2].min():.2f} ~ {anomalous_coords[:, 2].max():.2f}")
            
            # 建议修复方案
            print(f"\n=== Recommended Fix ===")
            print(f"1. Filter out entities with anomalous coordinates during DXF export")
            print(f"2. Set EXTMIN/EXTMAX to actual valid coordinate range:")
            print(f"   EXTMIN: ({x_q1:.2f}, {y_q1:.2f}, {z_q1:.2f})")
            print(f"   EXTMAX: ({x_q99:.2f}, {y_q99:.2f}, {z_q99:.2f})")
            print(f"3. Or use tighter bounds based on engineering coordinates:")
            print(f"   EXTMIN: ({x_min:.2f}, {y_min:.2f}, {z_min:.2f})")
            print(f"   EXTMAX: ({x_max:.2f}, {y_max:.2f}, {z_max:.2f})")
        else:
            print(f"\nNo anomalous points detected!")
            print(f"All coordinates are within expected ranges.")
        
        return anomalous_points
        
    except Exception as ex:
        print(f"ERROR reading DXF: {ex}")
        import traceback
        traceback.print_exc()
        return None

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--file', type=str, default=r'D:\断面算量平台\测试文件\geology_model_v7_fixed.dxf')
    args = parser.parse_args()
    find_anomalous_coords(args.file)