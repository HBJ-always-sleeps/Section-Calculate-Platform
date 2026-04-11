# -*- coding: utf-8 -*-
"""
DXF EXTMIN/EXTMAX修复工具 V2
直接修改DXF文件的文本内容，绕过ezdxf的自动重置机制
"""

import os
import re
import numpy as np
import ezdxf

def fix_dxf_extmin_extmax_direct(dxf_path, output_path=None):
    """直接修改DXF文件的EXTMIN/EXTMAX头变量
    
    Args:
        dxf_path: 输入DXF文件路径
        output_path: 输出DXF文件路径，如不提供则在原文件名后添加'_fixed3'
    """
    print(f"\n=== DXF EXTMIN/EXTMAX Direct Fix Tool ===")
    print(f"Input: {dxf_path}")
    
    if not os.path.exists(dxf_path):
        print(f"ERROR: File not found!")
        return False
    
    if output_path is None:
        base, ext = os.path.splitext(dxf_path)
        output_path = f"{base}_fixed3{ext}"
    
    try:
        # 先用ezdxf读取计算实际坐标范围
        doc = ezdxf.readfile(dxf_path)
        msp = doc.modelspace()
        
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
            elif entity_type in ['POLYLINE3D', 'POLYLINE']:
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
        
        # 直接读取DXF文件文本内容
        print(f"\nReading DXF file as text...")
        with open(dxf_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
        
        # 查找并替换EXTMIN和EXTMAX
        # DXF格式：
        # $EXTMIN
        #  10
        # 1e+20
        #  20
        # 1e+20
        #  30
        # 1e+20
        
        print(f"\nFixing EXTMIN/EXTMAX in DXF text...")
        
        # 替换EXTMIN
        # 查找 $EXTMIN 后面的 10, 20, 30 组
        extmin_pattern = r'(\$EXTMIN\s*\n\s*10\s*\n\s*)([^\n]+)(\s*\n\s*20\s*\n\s*)([^\n]+)(\s*\n\s*30\s*\n\s*)([^\n]+)'
        extmin_replacement = f'$EXTMIN\n  10\n{x_min:.6f}\n  20\n{y_min:.6f}\n  30\n{z_min:.6f}'
        
        content_new = re.sub(extmin_pattern, extmin_replacement, content)
        
        # 替换EXTMAX
        extmax_pattern = r'(\$EXTMAX\s*\n\s*10\s*\n\s*)([^\n]+)(\s*\n\s*20\s*\n\s*)([^\n]+)(\s*\n\s*30\s*\n\s*)([^\n]+)'
        extmax_replacement = f'$EXTMAX\n  10\n{x_max:.6f}\n  20\n{y_max:.6f}\n  30\n{z_max:.6f}'
        
        content_new = re.sub(extmax_pattern, extmax_replacement, content_new)
        
        # 检查是否成功替换
        if '$EXTMIN\n  10\n1e+20' in content or '$EXTMIN\n 10\n1e+20' in content:
            # 尝试另一种格式（单空格）
            extmin_pattern2 = r'(\$EXTMIN\s*\n 10\s*\n\s*)([^\n]+)(\s*\n 20\s*\n\s*)([^\n]+)(\s*\n 30\s*\n\s*)([^\n]+)'
            extmin_replacement2 = f'$EXTMIN\n 10\n{x_min:.6f}\n 20\n{y_min:.6f}\n 30\n{z_min:.6f}'
            content_new = re.sub(extmin_pattern2, extmin_replacement2, content_new)
            
            extmax_pattern2 = r'(\$EXTMAX\s*\n 10\s*\n\s*)([^\n]+)(\s*\n 20\s*\n\s*)([^\n]+)(\s*\n 30\s*\n\s*)([^\n]+)'
            extmax_replacement2 = f'$EXTMAX\n 10\n{x_max:.6f}\n 20\n{y_max:.6f}\n 30\n{z_max:.6f}'
            content_new = re.sub(extmax_pattern2, extmax_replacement2, content_new)
        
        # 写入新文件
        print(f"\nWriting fixed DXF file...")
        with open(output_path, 'w', encoding='utf-8', errors='ignore') as f:
            f.write(content_new)
        
        print(f"Output: {output_path}")
        print(f"File size: {os.path.getsize(output_path) / 1024:.1f} KB")
        
        # 验证修复结果
        print(f"\nVerifying fix...")
        try:
            doc_fixed = ezdxf.readfile(output_path)
            extmin = doc_fixed.header.get('$EXTMIN', None)
            extmax = doc_fixed.header.get('$EXTMAX', None)
            
            if extmin and extmax:
                print(f"  $EXTMIN: ({extmin[0]:.2f}, {extmin[1]:.2f}, {extmin[2]:.2f})")
                print(f"  $EXTMAX: ({extmax[0]:.2f}, {extmax[1]:.2f}, {extmax[2]:.2f})")
                
                if abs(extmin[0]) > 1e10 or abs(extmax[0]) > 1e10:
                    print(f"  [WARN] EXTMIN/EXTMAX still has extreme values - may need different approach")
                    return False
                else:
                    print(f"  [OK] EXTMIN/EXTMAX correctly fixed!")
                    return True
            else:
                print(f"  [ERROR] EXTMIN/EXTMAX not found!")
                return False
        except Exception as e:
            print(f"  [ERROR] Verification failed: {e}")
            return False
        
    except Exception as ex:
        print(f"ERROR: {ex}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--file', type=str, default=r'D:\断面算量平台\测试文件\geology_model_v7_fixed.dxf')
    parser.add_argument('--output', type=str, default=None)
    args = parser.parse_args()
    
    fix_dxf_extmin_extmax_direct(args.file, args.output)