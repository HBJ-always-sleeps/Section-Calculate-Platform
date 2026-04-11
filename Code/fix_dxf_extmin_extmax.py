# -*- coding: utf-8 -*-
"""
DXF EXTMIN/EXTMAX修复工具
直接修改DXF文件的EXTMIN/EXTMAX头变量，解决AutoCAD zoom extents问题
"""

import ezdxf
from ezdxf.math import Vec3
import sys
import os
import numpy as np

def fix_dxf_extmin_extmax(dxf_path, output_path=None):
    """修复DXF文件的EXTMIN/EXTMAX头变量
    
    Args:
        dxf_path: 输入DXF文件路径
        output_path: 输出DXF文件路径，如不提供则在原文件名后添加'_fixed2'
    """
    print(f"\n=== DXF EXTMIN/EXTMAX Fix Tool ===")
    print(f"Input: {dxf_path}")
    
    if not os.path.exists(dxf_path):
        print(f"ERROR: File not found!")
        return False
    
    if output_path is None:
        base, ext = os.path.splitext(dxf_path)
        output_path = f"{base}_fixed2{ext}"
    
    try:
        # 读取DXF文件
        doc = ezdxf.readfile(dxf_path)
        msp = doc.modelspace()
        
        # 收集所有坐标点，计算实际范围
        x_coords = []
        y_coords = []
        z_coords = []
        
        entities = list(msp.query('*'))
        print(f"Total entities: {len(entities)}")
        
        for e in entities:
            entity_type = e.dxftype()
            
            if entity_type == '3DFACE':
                try:
                    for vtx_name in ['vtx0', 'vtx1', 'vtx2', 'vtx3']:
                        vtx = getattr(e, vtx_name, None)
                        if vtx is not None:
                            x_coords.append(vtx.x)
                            y_coords.append(vtx.y)
                            z_coords.append(vtx.z)
                except Exception:
                    pass
            elif entity_type == 'POLYLINE3D' or entity_type == 'POLYLINE':
                try:
                    for v in e.vertices:
                        loc = v.dxf.location
                        x_coords.append(loc.x)
                        y_coords.append(loc.y)
                        z_coords.append(loc.z)
                except Exception:
                    pass
            elif entity_type == 'LINE':
                try:
                    x_coords.extend([e.dxf.start.x, e.dxf.end.x])
                    y_coords.extend([e.dxf.start.y, e.dxf.end.y])
                    z_coords.extend([e.dxf.start.z, e.dxf.end.z])
                except Exception:
                    pass
            elif entity_type == 'POINT':
                try:
                    loc = e.dxf.location
                    x_coords.append(loc.x)
                    y_coords.append(loc.y)
                    z_coords.append(loc.z)
                except Exception:
                    pass
        
        if not x_coords:
            print("ERROR: No coordinates found!")
            return False
        
        # 计算实际坐标范围
        x_min, x_max = min(x_coords), max(x_coords)
        y_min, y_max = min(y_coords), max(y_coords)
        z_min, z_max = min(z_coords), max(z_coords)
        
        print(f"\nActual coordinate range:")
        print(f"  X: {x_min:.2f} ~ {x_max:.2f}")
        print(f"  Y: {y_min:.2f} ~ {y_max:.2f}")
        print(f"  Z: {z_min:.2f} ~ {z_max:.2f}")
        
        # 检查当前EXTMIN/EXTMAX
        print(f"\nCurrent header EXTMIN/EXTMAX:")
        try:
            extmin = doc.header.get('$EXTMIN', None)
            extmax = doc.header.get('$EXTMAX', None)
            if extmin and extmax:
                print(f"  $EXTMIN: ({extmin[0]}, {extmin[1]}, {extmin[2]})")
                print(f"  $EXTMAX: ({extmax[0]}, {extmax[1]}, {extmax[2]})")
        except Exception as e:
            print(f"  Error reading: {e}")
        
        # 关键修复：使用正确的方法设置EXTMIN/EXTMAX
        # ezdxf的正确API是直接赋值Vec3对象
        print(f"\nFixing EXTMIN/EXTMAX...")
        
        # 方法1：使用Vec3直接赋值
        try:
            doc.header['$EXTMIN'] = Vec3(x_min, y_min, z_min)
            doc.header['$EXTMAX'] = Vec3(x_max, y_max, z_max)
            print(f"  Method 1 (Vec3 assignment): SUCCESS")
        except Exception as e:
            print(f"  Method 1 failed: {e}")
            
            # 方法2：使用tuple赋值
            try:
                doc.header['$EXTMIN'] = (x_min, y_min, z_min)
                doc.header['$EXTMAX'] = (x_max, y_max, z_max)
                print(f"  Method 2 (tuple assignment): SUCCESS")
            except Exception as e2:
                print(f"  Method 2 failed: {e2}")
                
                # 方法3：直接修改内部字典
                try:
                    # ezdxf内部使用_custom_attributes存储头变量
                    if hasattr(doc.header, '_custom_attributes'):
                        doc.header._custom_attributes['$EXTMIN'] = Vec3(x_min, y_min, z_min)
                        doc.header._custom_attributes['$EXTMAX'] = Vec3(x_max, y_max, z_max)
                        print(f"  Method 3 (direct dict): SUCCESS")
                except Exception as e3:
                    print(f"  Method 3 failed: {e3}")
        
        # 验证设置是否成功
        print(f"\nVerifying EXTMIN/EXTMAX after fix:")
        try:
            extmin = doc.header.get('$EXTMIN', None)
            extmax = doc.header.get('$EXTMAX', None)
            if extmin and extmax:
                print(f"  $EXTMIN: ({extmin[0]:.2f}, {extmin[1]:.2f}, {extmin[2]:.2f})")
                print(f"  $EXTMAX: ({extmax[0]:.2f}, {extmax[1]:.2f}, {extmax[2]:.2f})")
                
                # 检查是否与实际范围一致
                if abs(extmin[0] - x_min) < 0.01 and abs(extmax[0] - x_max) < 0.01:
                    print(f"  [OK] EXTMIN/EXTMAX correctly set!")
                else:
                    print(f"  [WARN] EXTMIN/EXTMAX may not be correctly set")
            else:
                print(f"  [ERROR] EXTMIN/EXTMAX still not set!")
        except Exception as e:
            print(f"  Error verifying: {e}")
        
        # 保存修复后的文件
        doc.saveas(output_path)
        print(f"\nOutput: {output_path}")
        print(f"File size: {os.path.getsize(output_path) / 1024:.1f} KB")
        
        return True
        
    except Exception as ex:
        print(f"ERROR: {ex}")
        import traceback
        traceback.print_exc()
        return False

def verify_fix(dxf_path):
    """验证修复后的DXF文件"""
    print(f"\n=== Verifying Fixed DXF ===")
    print(f"File: {dxf_path}")
    
    if not os.path.exists(dxf_path):
        print(f"ERROR: File not found!")
        return False
    
    try:
        doc = ezdxf.readfile(dxf_path)
        
        # 检查EXTMIN/EXTMAX
        extmin = doc.header.get('$EXTMIN', None)
        extmax = doc.header.get('$EXTMAX', None)
        
        if extmin and extmax:
            print(f"$EXTMIN: ({extmin[0]:.2f}, {extmin[1]:.2f}, {extmin[2]:.2f})")
            print(f"$EXTMAX: ({extmax[0]:.2f}, {extmax[1]:.2f}, {extmax[2]:.2f})")
            
            # 检查是否为极端值
            if abs(extmin[0]) > 1e10 or abs(extmax[0]) > 1e10:
                print(f"[ERROR] EXTMIN/EXTMAX still has extreme values!")
                return False
            else:
                print(f"[OK] EXTMIN/EXTMAX correctly set!")
                return True
        else:
            print(f"[ERROR] EXTMIN/EXTMAX not found!")
            return False
            
    except Exception as e:
        print(f"ERROR: {e}")
        return False

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--file', type=str, default=r'D:\断面算量平台\测试文件\geology_model_v7_fixed.dxf')
    parser.add_argument('--output', type=str, default=None)
    parser.add_argument('--verify', type=str, default=None, help='Verify a fixed DXF file')
    args = parser.parse_args()
    
    if args.verify:
        verify_fix(args.verify)
    else:
        success = fix_dxf_extmin_extmax(args.file, args.output)
        if success:
            # 验证修复后的文件
            output = args.output if args.output else args.file.replace('.dxf', '_fixed2.dxf')
            verify_fix(output)