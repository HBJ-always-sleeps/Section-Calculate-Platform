# -*- coding: utf-8 -*-
"""
DXF文件诊断工具
检查DXF文件中的实体数量、图层、坐标范围等
"""

import ezdxf
import sys
import os

def diagnose_dxf(dxf_path):
    """诊断DXF文件"""
    print(f"\n=== DXF Diagnosis ===")
    print(f"File: {dxf_path}")
    
    if not os.path.exists(dxf_path):
        print(f"ERROR: File not found!")
        return
    
    try:
        doc = ezdxf.readfile(dxf_path)
        msp = doc.modelspace()
        
        # 统计实体
        entities = list(msp.query('*'))
        print(f"\nTotal entities: {len(entities)}")
        
        # 按类型统计
        type_counts = {}
        for e in entities:
            t = e.dxftype()
            type_counts[t] = type_counts.get(t, 0) + 1
        
        print(f"\nEntity types:")
        for t, count in sorted(type_counts.items()):
            print(f"  {t}: {count}")
        
        # 图层列表
        print(f"\nLayers defined:")
        for layer in doc.layers:
            print(f"  {layer.dxf.name}: color={layer.dxf.color}")
        
        # 检查坐标范围
        x_coords = []
        y_coords = []
        z_coords = []
        
        for e in entities:
            if e.dxftype() == '3DFACE':
                # 3DFACE has 4 vertices: vtx0, vtx1, vtx2, vtx3
                try:
                    # Use correct ezdxf API for 3DFACE vertices
                    for vtx_name in ['vtx0', 'vtx1', 'vtx2', 'vtx3']:
                        vtx = getattr(e, vtx_name, None)
                        if vtx is not None:
                            x_coords.append(vtx.x)
                            y_coords.append(vtx.y)
                            z_coords.append(vtx.z)
                except Exception as ex:
                    pass
            elif e.dxftype() == 'POLYLINE3D':
                for v in e.vertices:
                    x_coords.append(v.dxf.location.x)
                    y_coords.append(v.dxf.location.y)
                    z_coords.append(v.dxf.location.z)
            elif e.dxftype() == 'LINE':
                x_coords.extend([e.dxf.start.x, e.dxf.end.x])
                y_coords.extend([e.dxf.start.y, e.dxf.end.y])
                z_coords.extend([e.dxf.start.z, e.dxf.end.z])
            elif e.dxftype() == 'POINT':
                x_coords.append(e.dxf.location.x)
                y_coords.append(e.dxf.location.y)
                z_coords.append(e.dxf.location.z)
        
        if x_coords:
            print(f"\nCoordinate ranges:")
            print(f"  X: {min(x_coords):.2f} ~ {max(x_coords):.2f}")
            print(f"  Y: {min(y_coords):.2f} ~ {max(y_coords):.2f}")
            print(f"  Z: {min(z_coords):.2f} ~ {max(z_coords):.2f}")
            
            # 检查是否坐标异常（如全为0或范围极小）
            x_range = max(x_coords) - min(x_coords)
            y_range = max(y_coords) - min(y_coords)
            z_range = max(z_coords) - min(z_coords)
            
            if x_range < 1 and y_range < 1 and z_range < 1:
                print(f"\nWARNING: Coordinate range is very small (<1)")
                print(f"  This may indicate coordinate transformation issues!")
        else:
            print(f"\nWARNING: No coordinates found in entities!")
        
        # 检查前几个实体的详细信息
        print(f"\nFirst 5 entities detail:")
        for i, e in enumerate(entities[:5]):
            print(f"  Entity {i}: {e.dxftype()}, layer={e.dxf.layer}")
            if e.dxftype() == '3DFACE':
                try:
                    vtx0 = e.vtx0
                    vtx1 = e.vtx1
                    print(f"    vtx0: ({vtx0.x:.2f}, {vtx0.y:.2f}, {vtx0.z:.2f})")
                    print(f"    vtx1: ({vtx1.x:.2f}, {vtx1.y:.2f}, {vtx1.z:.2f})")
                except Exception as ex:
                    print(f"    Error reading vertices: {ex}")
            elif e.dxftype() == 'POLYLINE':
                try:
                    pts = [(v.dxf.location.x, v.dxf.location.y, v.dxf.location.z) for v in e.vertices[:3]]
                    print(f"    First 3 points: {pts}")
                except Exception as ex:
                    print(f"    Error reading polyline: {ex}")
                print(f"    First 3 points: {pts}")
        
        # 检查DXF版本
        print(f"\nDXF version: {doc.dxfversion}")
        
        # 检查EXTMIN/EXTMAX头变量
        print(f"\nHeader variables:")
        try:
            extmin = doc.header.get('$EXTMIN', None)
            extmax = doc.header.get('$EXTMAX', None)
            if extmin and extmax:
                print(f"  $EXTMIN: ({extmin[0]:.2f}, {extmin[1]:.2f}, {extmin[2]:.2f})")
                print(f"  $EXTMAX: ({extmax[0]:.2f}, {extmax[1]:.2f}, {extmax[2]:.2f})")
            else:
                print(f"  $EXTMIN/$EXTMAX: NOT SET!")
                print(f"  This is why AutoCAD shows nothing - need ZOOM Extents!")
        except Exception as e:
            print(f"  Error reading EXTMIN/EXTMAX: {e}")
        
    except Exception as ex:
        print(f"ERROR reading DXF: {ex}")

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--file', type=str, default=r'D:\断面算量平台\测试文件\geology_model_v7_fixed.dxf')
    args = parser.parse_args()
    diagnose_dxf(args.file)