# -*- coding: utf-8 -*-
"""列出文件中所有图层及其内容"""
import ezdxf
import os

def list_all_layers(dxf_path):
    """列出所有图层及其实体数量"""
    print(f"\n{'='*60}")
    print(f"文件: {os.path.basename(dxf_path)}")
    print(f"{'='*60}")
    
    doc = ezdxf.readfile(dxf_path)
    msp = doc.modelspace()
    
    # 收集所有图层及其内容
    layer_stats = {}
    for e in msp:
        layer = e.dxf.layer
        if layer not in layer_stats:
            layer_stats[layer] = {'count': 0, 'types': {}, 'colors': {}}
        layer_stats[layer]['count'] += 1
        
        # 统计类型
        etype = e.dxftype()
        if etype not in layer_stats[layer]['types']:
            layer_stats[layer]['types'][etype] = 0
        layer_stats[layer]['types'][etype] += 1
        
        # 统计颜色（仅线/多段线）
        if etype in ('LWPOLYLINE', 'LINE'):
            try:
                color = e.dxf.color
                if color not in layer_stats[layer]['colors']:
                    layer_stats[layer]['colors'][color] = 0
                layer_stats[layer]['colors'][color] += 1
            except: pass
    
    print(f"\n图层总数: {len(layer_stats)}")
    print(f"\n按图层名排序:")
    
    # 按图层名排序显示
    for layer in sorted(layer_stats.keys()):
        stats = layer_stats[layer]
        print(f"\n[{layer}]")
        print(f"  实体总数: {stats['count']}")
        print(f"  类型分布: {stats['types']}")
        if stats['colors']:
            print(f"  颜色分布: {stats['colors']}")
    
    # 特别显示包含"20260326"的图层
    print(f"\n{'='*60}")
    print(f"包含'20260326'的图层:")
    for layer in sorted(layer_stats.keys()):
        if '20260326' in layer or '20260317' in layer or '已粘贴' in layer:
            stats = layer_stats[layer]
            print(f"\n[{layer}]")
            print(f"  实体总数: {stats['count']}")
            print(f"  类型分布: {stats['types']}")
            if stats['colors']:
                print(f"  颜色分布: {stats['colors']}")

if __name__ == '__main__':
    dxf_path = r"\\Beihai01\广西北海-测量资料\3、内湾段\2、检测数据\20260325~26检测\20260317断面比对图_已粘贴断面_20260326_195309_已粘贴断面_20260415_144412.dxf"
    
    if os.path.exists(dxf_path):
        list_all_layers(dxf_path)
    else:
        print(f"[ERROR] 文件不存在: {dxf_path}")