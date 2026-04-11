# -*- coding: utf-8 -*-
"""分析DXF文件图层结构"""
import ezdxf
import sys
import io

# 设置输出编码
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

dxf_path = r'D:\断面算量平台\测试文件\内湾段分层图（全航道底图20260318）.dxf'
doc = ezdxf.readfile(dxf_path)
msp = doc.modelspace()

print("=" * 60)
print("DXF文件图层分析")
print("=" * 60)

# 获取所有图层
layers = [layer.dxf.name for layer in doc.layers]
print(f"\n共有 {len(layers)} 个图层:")
for l in sorted(layers):
    print(f"  - {l}")

# 重点分析关键图层
key_layers = ['DMX', 'HBX', 'L1', '开挖线', '超挖线']
print("\n" + "=" * 60)
print("关键图层实体统计:")
print("=" * 60)

for layer_name in layers:
    # 检查是否是关键图层
    is_key = any(kw in layer_name.upper() or kw in layer_name for kw in ['DMX', 'HBX', 'L1', '开挖', '超挖', '标尺', '刻度'])
    if is_key:
        count = 0
        entity_types = {}
        for e in msp.query(f'*[layer=="{layer_name}"]'):
            count += 1
            et = e.dxftype()
            entity_types[et] = entity_types.get(et, 0) + 1
        if count > 0:
            print(f"\n图层: {layer_name}")
            print(f"  实体数: {count}")
            print(f"  实体类型: {entity_types}")

# 查找包含文本的图层（可能是标尺）
print("\n" + "=" * 60)
print("包含TEXT实体的图层（标尺刻度）:")
print("=" * 60)

text_layers = {}
for e in msp.query('TEXT'):
    layer = e.dxf.layer
    if layer not in text_layers:
        text_layers[layer] = []
    text_content = e.dxf.text
    text_layers[layer].append(text_content)

for layer, texts in sorted(text_layers.items()):
    if len(texts) <= 20:
        print(f"\n图层: {layer}")
        print(f"  文本数: {len(texts)}")
        print(f"  示例: {texts[:5]}")

print("\n完成!")