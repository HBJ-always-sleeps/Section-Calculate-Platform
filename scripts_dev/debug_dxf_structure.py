"""调试DXF文件结构，分析图层"0"中的面积标注坐标分布"""
import ezdxf
import re

def debug_dxf_structure(dxf_path):
    """分析DXF文件中面积标注的坐标分布"""
    doc = ezdxf.readfile(dxf_path)
    msp = doc.modelspace()
    
    AREA_UNIT = '\u33A1'
    
    # 收集面积标注
    area_annotations = []
    for entity in msp:
        if hasattr(entity, 'dxf') and entity.dxf.layer == '0' and entity.dxftype() == 'TEXT':
            text = entity.dxf.text
            if '面积' in text or AREA_UNIT in text:
                area_annotations.append({
                    'text': text,
                    'x': entity.dxf.insert[0],
                    'y': entity.dxf.insert[1]
                })
    
    print(f"图层'0'中共有 {len(area_annotations)} 个面积相关文本")
    
    # 分离描述和数值
    descriptions = []
    values = []
    for ann in area_annotations:
        text = ann['text']
        if '面积' in text and '=' in text:
            descriptions.append(ann)
        elif AREA_UNIT in text:
            match = re.search(r'(\d+\.?\d*)', text)
            if match:
                ann['value'] = float(match.group(1))
                values.append(ann)
    
    print(f"\n描述文本: {len(descriptions)} 个")
    print(f"数值文本: {len(values)} 个")
    
    # 打印前20个描述文本的坐标
    print("\n描述文本样本（前20个）：")
    for i, desc in enumerate(descriptions[:20]):
        print(f"  [{i+1}] {desc['text']}: X={desc['x']:.1f}, Y={desc['y']:.1f}")
    
    # 打印前20个数值文本的坐标
    print("\n数值文本样本（前20个）：")
    for i, val in enumerate(values[:20]):
        print(f"  [{i+1}] {val['value']:.2f}㎡: X={val['x']:.1f}, Y={val['y']:.1f}")
    
    # 统计X坐标分布
    x_coords = [ann['x'] for ann in area_annotations]
    if x_coords:
        print(f"\nX坐标范围: {min(x_coords):.1f} ~ {max(x_coords):.1f}")
        print(f"X坐标中位数: {sorted(x_coords)[len(x_coords)//2]:.1f}")
    
    # 统计Y坐标分布
    y_coords = [ann['y'] for ann in area_annotations]
    if y_coords:
        print(f"Y坐标范围: {min(y_coords):.1f} ~ {max(y_coords):.1f}")
    
    # 分析桩号图层
    pile_layer = None
    pile_numbers = []
    for entity in msp:
        if hasattr(entity, 'dxf') and entity.dxftype() == 'TEXT':
            text = entity.dxf.text
            if 'K67' in text or 'K68' in text or 'K69' in text or 'K70' in text:
                if entity.dxf.layer not in ['0', '面积标注']:
                    pile_layer = entity.dxf.layer
                    pile_numbers.append({
                        'text': text,
                        'x': entity.dxf.insert[0],
                        'y': entity.dxf.insert[1],
                        'layer': entity.dxf.layer
                    })
    
    print(f"\n检测到桩号图层: {pile_layer}")
    print(f"找到 {len(pile_numbers)} 个桩号")
    
    # 打印前10个桩号
    print("\n桩号样本（前10个）：")
    for i, pile in enumerate(pile_numbers[:10]):
        print(f"  [{i+1}] {pile['text']}: X={pile['x']:.1f}, Y={pile['y']:.1f}, 图层={pile['layer']}")
    
    # 分析桩号X坐标分布
    pile_x_coords = [p['x'] for p in pile_numbers]
    if pile_x_coords:
        print(f"\n桩号X坐标范围: {min(pile_x_coords):.1f} ~ {max(pile_x_coords):.1f}")
        print(f"桩号X坐标中位数: {sorted(pile_x_coords)[len(pile_x_coords)//2]:.1f}")
    
    # 分析描述文本与数值文本的坐标关系
    print("\n分析描述文本与数值文本的坐标匹配关系：")
    # 取第一个描述文本，找最近的数值文本
    if descriptions and values:
        desc = descriptions[0]
        print(f"\n示例描述文本: '{desc['text']}' at X={desc['x']:.1f}, Y={desc['y']:.1f}")
        
        # 找Y相近的数值文本
        y_close = [v for v in values if abs(v['y'] - desc['y']) < 5]
        print(f"Y相近(±5)的数值文本: {len(y_close)} 个")
        for v in y_close[:5]:
            print(f"  {v['value']:.2f}㎡: X={v['x']:.1f}, Y={v['y']:.1f}, X差距={abs(v['x'] - desc['x']):.1f}")

if __name__ == "__main__":
    dxf_path = r"D:\2026年3月月进度测量段面图北海港铁山港20万吨级航道工程（啄罗作业区至石头埠作业区段）施工Ⅰ标段.dxf"
    debug_dxf_structure(dxf_path)