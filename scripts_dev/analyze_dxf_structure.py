import ezdxf

dxf_path = r"D:\2026年3月月进度测量段面图北海港铁山港20万吨级航道工程（啄罗作业区至石头埠作业区段）施工Ⅰ标段.dxf"

doc = ezdxf.readfile(dxf_path)
msp = doc.modelspace()

# 收集所有文本
all_texts = []
for entity in msp:
    if hasattr(entity, 'dxf') and entity.dxftype() == 'TEXT':
        layer = entity.dxf.layer
        text = entity.dxf.text
        x = entity.dxf.insert[0]
        y = entity.dxf.insert[1]
        all_texts.append({
            'layer': layer,
            'text': text,
            'x': x,
            'y': y
        })

print(f"共 {len(all_texts)} 个文本实体")

# 统计图层
layers = {}
for t in all_texts:
    layer = t['layer']
    if layer not in layers:
        layers[layer] = 0
    layers[layer] += 1

print("\n图层统计：")
for layer, count in sorted(layers.items(), key=lambda x: -x[1])[:20]:
    print(f"  {layer}: {count} 个")

# 找桩号
pile_texts = [t for t in all_texts if t['layer'] == '桩号']
print(f"\n桩号（共{len(pile_texts)}个）：")
for t in sorted(pile_texts, key=lambda x: x['y'], reverse=True)[:5]:
    print(f"  {t['text']}: X={t['x']:.1f}, Y={t['y']:.1f}")

# 找面积相关文本（图层"0"）
area_texts = [t for t in all_texts if t['layer'] == '0' and ('面积' in t['text'] or '㎡' in t['text'])]
print(f"\n面积相关文本（图层0，共{len(area_texts)}个）：")
for t in sorted(area_texts, key=lambda x: x['y'], reverse=True)[:30]:
    print(f"  '{t['text']}': X={t['x']:.1f}, Y={t['y']:.1f}")

# 找数字文本
import re
number_texts = [t for t in all_texts if t['layer'] == '0' and re.match(r'^[\d.]+$', t['text'].strip())]
print(f"\n纯数字文本（图层0，共{len(number_texts)}个）：")
for t in sorted(number_texts, key=lambda x: x['y'], reverse=True)[:30]:
    print(f"  '{t['text']}': X={t['x']:.1f}, Y={t['y']:.1f}")

# 查看第一个桩号附近的文本
if pile_texts:
    first_pile = sorted(pile_texts, key=lambda x: x['y'], reverse=True)[0]
    print(f"\n第一个桩号 '{first_pile['text']}' (Y={first_pile['y']:.1f}) 附近的文本：")
    nearby = [t for t in all_texts if abs(t['y'] - first_pile['y']) < 200 and t['layer'] == '0']
    for t in sorted(nearby, key=lambda x: x['y'], reverse=True)[:20]:
        print(f"  '{t['text']}': X={t['x']:.1f}, Y={t['y']:.1f}")