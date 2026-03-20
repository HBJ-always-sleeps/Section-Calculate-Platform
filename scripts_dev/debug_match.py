import ezdxf
import re

dxf_path = r"D:\2026年3月月进度测量段面图北海港铁山港20万吨级航道工程（啄罗作业区至石头埠作业区段）施工Ⅰ标段.dxf"

doc = ezdxf.readfile(dxf_path)
msp = doc.modelspace()

AREA_UNIT = '\u33A1'

# 提取所有文本
all_texts = []
for entity in msp:
    if hasattr(entity, 'dxf') and entity.dxftype() == 'TEXT':
        all_texts.append({
            'text': entity.dxf.text,
            'layer': entity.dxf.layer,
            'x': entity.dxf.insert[0],
            'y': entity.dxf.insert[1]
        })

# 桩号
piles = [t for t in all_texts if t['layer'] == '桩号']
print(f"桩号: {len(piles)}")

# 面积标注
areas = [t for t in all_texts if t['layer'] == '0']
print(f"图层0文本: {len(areas)}")

# 描述文本
descs = [t for t in areas if '面积=' in t['text']]
print(f"描述文本: {len(descs)}")

# 数值文本
values = []
for t in areas:
    match = re.search(r'(\d+\.?\d*)', t['text'])
    if match and ('O' in t['text'] or AREA_UNIT in t['text']):
        values.append({'text': t['text'], 'x': t['x'], 'y': t['y'], 'value': float(match.group(1))})
print(f"数值文本: {len(values)}")

# 分析第一个桩号
print("\n" + "="*60)
print("分析第一个桩号 K67+400")
print("="*60)

# 找K67+400
k67_400 = [p for p in piles if 'K67+400' in p['text']]
if k67_400:
    pile = k67_400[0]
    print(f"桩号位置: X={pile['x']:.1f}, Y={pile['y']:.1f}")
    
    # 找上方的数值文本
    print(f"\n桩号上方的数值文本（Y > {pile['y']:.1f}）：")
    above_values = [v for v in values if v['y'] > pile['y'] and v['y'] < pile['y'] + 200]
    for v in sorted(above_values, key=lambda x: x['y'])[:10]:
        print(f"  X={v['x']:.1f}, Y={v['y']:.1f}, 值={v['value']}, 文本='{v['text']}'")
    
    # 找附近的描述文本
    print(f"\n附近的描述文本：")
    nearby_descs = [d for d in descs if abs(d['y'] - pile['y']) < 200]
    for d in sorted(nearby_descs, key=lambda x: x['y'])[:10]:
        print(f"  X={d['x']:.1f}, Y={d['y']:.1f}, 文本='{d['text']}'")

# 分析X坐标分布
print("\n" + "="*60)
print("X坐标分析")
print("="*60)

pile_x_values = sorted(set([p['x'] for p in piles]))
print(f"桩号X值: {pile_x_values}")

value_x_values = sorted(set([v['x'] for v in values]))
print(f"数值X值（前20）: {value_x_values[:20]}")

desc_x_values = sorted(set([d['x'] for d in descs]))
print(f"描述X值: {desc_x_values}")

# 分析描述文本和数值文本的X关系
print("\n" + "="*60)
print("描述文本与数值文本X坐标对应关系")
print("="*60)

# 同一Y层的描述和数值
for y in sorted(set([d['y'] for d in descs]))[:5]:
    y_descs = [d for d in descs if abs(d['y'] - y) < 3]
    y_values = [v for v in values if abs(v['y'] - y) < 3]
    print(f"\nY={y:.1f}层：")
    for d in y_descs:
        print(f"  描述: X={d['x']:.1f}, '{d['text']}'")
    for v in y_values[:6]:
        print(f"  数值: X={v['x']:.1f}, {v['value']}")