# -*- coding: utf-8 -*-
"""查找源文件桩号文本所在图层"""
import ezdxf
import re

def find_station_layer():
    """查找桩号文本所在图层"""
    
    src_path = r"\\Beihai01\广西北海-测量资料\3、内湾段\2、检测数据\20260325~26检测\20260326duanmian.dxf"
    
    print("="*60)
    print("查找源文件桩号文本所在图层")
    print("="*60)
    
    doc = ezdxf.readfile(src_path)
    msp = doc.modelspace()
    
    # 遍历所有TEXT实体
    layer_texts = {}
    station_pattern = re.compile(r'(\d+)\+(\d+)')
    
    for e in msp.query('TEXT'):
        try:
            text = e.dxf.text.strip()
            layer = e.dxf.layer
            
            # 检查是否是桩号格式
            if station_pattern.search(text):
                if layer not in layer_texts:
                    layer_texts[layer] = []
                layer_texts[layer].append(text)
        except: pass
    
    print(f"\n[找到桩号文本的图层]")
    for layer, texts in layer_texts.items():
        print(f"  图层 '{layer}': {len(texts)}个桩号文本")
        # 显示前5个桩号
        for i, t in enumerate(texts[:5]):
            print(f"    {i+1}. {t}")
    
    # 也检查MTEXT
    print(f"\n[检查MTEXT实体]")
    for e in msp.query('MTEXT'):
        try:
            text = e.text.strip()
            layer = e.dxf.layer
            
            if station_pattern.search(text):
                print(f"  图层 '{layer}': 找到桩号文本")
                print(f"    内容: {text[:50]}...")
        except: pass

if __name__ == '__main__':
    find_station_layer()