"""
更新DXF文件中图层"0"的面积标注
将Excel数据（设计剩余面积、超挖面积）更新到对应的面积标注位置

计算逻辑：总剩余面积 = 设计剩余面积 + 超挖面积
"""
import ezdxf
import pandas as pd
import re
import os

def update_dxf_area_annotations(dxf_path, output_path, excel_data):
    """
    更新DXF文件中的面积标注
    
    excel_data: 字典列表，每个包含 {桩号, 设计剩余面积, 超挖面积}
    """
    try:
        doc = ezdxf.readfile(dxf_path)
        msp = doc.modelspace()
        
        # 面积单位字符 ㎡ (U+33A1)
        AREA_UNIT = '\u33A1'
        
        # 1. 提取所有面积标注和桩号
        area_annotations = []
        pile_numbers = []
        
        # 自动检测桩号图层（包含"桩"字符的图层）
        pile_layer = None
        for entity in msp:
            if hasattr(entity, 'dxf') and entity.dxftype() == 'TEXT':
                if 'K67' in entity.dxf.text or 'K68' in entity.dxf.text:
                    if entity.dxf.layer not in ['0', '面积标注']:
                        pile_layer = entity.dxf.layer
                        break
        
        print(f"检测到桩号图层: {pile_layer}")
        
        for entity in msp:
            if hasattr(entity, 'dxf'):
                # 图层"0"中的面积标注
                if entity.dxf.layer == '0' and entity.dxftype() == 'TEXT':
                    text = entity.dxf.text
                    if '面积' in text or AREA_UNIT in text:
                        area_annotations.append({
                            'entity': entity,
                            'text': text,
                            'x': entity.dxf.insert[0],
                            'y': entity.dxf.insert[1]
                        })
                # 自动检测的桩号图层
                elif pile_layer and entity.dxf.layer == pile_layer and entity.dxftype() == 'TEXT':
                    pile_numbers.append({
                        'entity': entity,
                        'text': entity.dxf.text,
                        'x': entity.dxf.insert[0],
                        'y': entity.dxf.insert[1]
                    })
        
        print(f"找到 {len(pile_numbers)} 个桩号，{len(area_annotations)} 个面积标注")
        
        # 2. 解析面积标注
        descriptions = []  # 描述文本
        values = []  # 数值文本
        
        for ann in area_annotations:
            text = ann['text']
            
            has_总 = '总' in text
            has_剩余 = '剩余' in text
            has_设计 = '设计' in text
            has_超挖 = '超挖' in text
            has_欠挖 = '欠挖' in text
            
            if has_总 and has_剩余 and not has_设计 and not has_超挖:
                ann['type'] = '断面剩余面积'
                descriptions.append(ann)
            elif has_设计 and has_剩余:
                ann['type'] = '超挖面积'  # 实际是设计剩余面积
                descriptions.append(ann)
            elif has_超挖 and has_剩余 and not has_设计:
                ann['type'] = '欠挖面积'  # 实际是超挖剩余面积
                descriptions.append(ann)
            elif has_欠挖 and not has_剩余:
                ann['type'] = '欠挖面积'
                descriptions.append(ann)
            elif AREA_UNIT in text:
                match = re.search(r'(\d+\.?\d*)', text)
                if match:
                    ann['value'] = float(match.group(1))
                    values.append(ann)
        
        print(f"描述文本: {len(descriptions)} 个，数值文本: {len(values)} 个")
        
        # 3. 按桩号Y坐标分组
        pile_y_tolerance = 20.0
        pile_y_groups = {}
        for pile in pile_numbers:
            y = pile['y']
            found_key = None
            for key in pile_y_groups.keys():
                if abs(key - y) < pile_y_tolerance:
                    found_key = key
                    break
            if found_key:
                pile_y_groups[found_key].append(pile)
            else:
                pile_y_groups[y] = [pile]
        
        # 4. 按桩号排序（从大到小，Y坐标从上到下）
        sorted_pile_y = sorted(pile_y_groups.keys(), reverse=True)
        
        # 5. 辅助函数
        # 根据调试：描述文本X约166（左）和361（右），数值文本X约194（左）和389（右）
        # 使用280作为分界点
        def get_x_side(x):
            return 'left' if x < 280 else 'right'
        
        def match_value(desc, values):
            """为描述文本匹配最近的数值文本"""
            best_val = None
            best_dist = float('inf')
            for val in values:
                y_dist = abs(val['y'] - desc['y'])
                if y_dist > 3:  # Y坐标必须相近（同一行）
                    continue
                val_side = get_x_side(val['x'])
                desc_side = get_x_side(desc['x'])
                if val_side != desc_side:  # X必须在同一侧
                    continue
                x_dist = abs(val['x'] - desc['x'])
                if x_dist < best_dist:
                    best_dist = x_dist
                    best_val = val
            return best_val
        
        # 6. 按桩号排序新数据
        def sort_pile_number(pile_text):
            match = re.search(r'K(\d+)\+(\d+)', pile_text)
            if match:
                return int(match.group(1)) * 1000 + int(match.group(2))
            return 0
        
        # 创建桩号映射表：标准化桩号（去掉小数点）作为键
        def normalize_pile(pile_text):
            """标准化桩号，去掉小数部分"""
            return re.sub(r'\.\d+$', '', pile_text)
        
        # 创建Excel数据的映射
        excel_data_map = {}
        for d in excel_data:
            normalized = normalize_pile(d['桩号'])
            excel_data_map[normalized] = d
        
        sorted_excel_data = sorted(excel_data, key=lambda x: sort_pile_number(x['桩号']))
        print(f"\nExcel数据（按桩号排序）:")
        for d in sorted_excel_data[:10]:
            total = d['设计剩余面积'] + d['超挖面积']
            print(f"  {d['桩号']}: 设计剩余={d['设计剩余面积']}, 超挖={d['超挖面积']}, 总剩余={total}")
        
        # 7. 新策略：直接按描述文本Y坐标分组，然后按顺序匹配Excel数据
        # 将描述文本按Y坐标分断面（每断面有3行描述文本）
        
        # 按Y坐标分组描述文本（容差5单位）
        desc_y_groups = {}
        for desc in descriptions:
            y = desc['y']
            found_key = None
            for key in desc_y_groups.keys():
                if abs(key - y) < 5:
                    found_key = key
                    break
            if found_key:
                desc_y_groups[found_key].append(desc)
            else:
                desc_y_groups[y] = [desc]
        
        print(f"\n描述文本按Y坐标分为 {len(desc_y_groups)} 层")
        
        # 每个断面有3个Y层（总剩余、设计剩余、超挖剩余）
        # 将Y层按相近Y坐标组合成断面（每3层为1个断面，每断面左右各1个桩号）
        sorted_desc_y = sorted(desc_y_groups.keys(), reverse=True)  # Y从大到小
        
        # 每3个Y层为1个断面组
        section_groups = []
        i = 0
        while i < len(sorted_desc_y):
            # 取连续的3个Y层作为1个断面组
            group_y_layers = []
            for j in range(3):
                if i + j < len(sorted_desc_y):
                    group_y_layers.append(sorted_desc_y[i + j])
            if len(group_y_layers) == 3:
                section_groups.append(group_y_layers)
            i += 3
        
        print(f"识别到 {len(section_groups)} 个断面组")
        
        # 8. 按断面组更新数据
        update_count = 0
        sections_updated = 0
        
        for group_idx, y_layers in enumerate(section_groups):
            # 收集这个断面组的所有描述文本
            all_descs = []
            for y in y_layers:
                all_descs.extend(desc_y_groups[y])
            
            # 按X坐标分左右
            left_descs = [d for d in all_descs if get_x_side(d['x']) == 'left']
            right_descs = [d for d in all_descs if get_x_side(d['x']) == 'right']
            
            # 计算这个断面对应的Excel数据索引
            # 每个断面组对应2条Excel数据（左+右）
            left_data_idx = group_idx * 2
            right_data_idx = group_idx * 2 + 1
            
            # 更新左侧数据
            if left_data_idx < len(sorted_excel_data):
                pile_data = sorted_excel_data[left_data_idx]
                design_remain = pile_data['设计剩余面积']
                overbreak = pile_data['超挖面积']
                total_remain = round(design_remain + overbreak, 2)
                
                print(f"\n[{group_idx+1}] 更新左侧 {pile_data['桩号']}: 设计剩余={design_remain:.2f}, 超挖={overbreak:.2f}, 总剩余={total_remain:.2f}")
                
                for desc in left_descs:
                    val_entity = match_value(desc, values)
                    if val_entity:
                        entity = val_entity['entity']
                        if desc['type'] == '断面剩余面积':
                            new_text = f"{total_remain:.2f}{AREA_UNIT}"
                            entity.dxf.text = new_text
                            update_count += 1
                            print(f"  更新断面剩余面积: {new_text}")
                        elif desc['type'] == '超挖面积':
                            new_text = f"{design_remain:.2f}{AREA_UNIT}"
                            entity.dxf.text = new_text
                            update_count += 1
                            print(f"  更新设计剩余面积: {new_text}")
                        elif desc['type'] == '欠挖面积':
                            new_text = f"{overbreak:.2f}{AREA_UNIT}"
                            entity.dxf.text = new_text
                            update_count += 1
                            print(f"  更新超挖剩余面积: {new_text}")
                sections_updated += 1
            
            # 更新右侧数据
            if right_data_idx < len(sorted_excel_data):
                pile_data = sorted_excel_data[right_data_idx]
                design_remain = pile_data['设计剩余面积']
                overbreak = pile_data['超挖面积']
                total_remain = round(design_remain + overbreak, 2)
                
                print(f"\n[{group_idx+1}] 更新右侧 {pile_data['桩号']}: 设计剩余={design_remain:.2f}, 超挖={overbreak:.2f}, 总剩余={total_remain:.2f}")
                
                for desc in right_descs:
                    val_entity = match_value(desc, values)
                    if val_entity:
                        entity = val_entity['entity']
                        if desc['type'] == '断面剩余面积':
                            new_text = f"{total_remain:.2f}{AREA_UNIT}"
                            entity.dxf.text = new_text
                            update_count += 1
                            print(f"  更新断面剩余面积: {new_text}")
                        elif desc['type'] == '超挖面积':
                            new_text = f"{design_remain:.2f}{AREA_UNIT}"
                            entity.dxf.text = new_text
                            update_count += 1
                            print(f"  更新设计剩余面积: {new_text}")
                        elif desc['type'] == '欠挖面积':
                            new_text = f"{overbreak:.2f}{AREA_UNIT}"
                            entity.dxf.text = new_text
                            update_count += 1
                            print(f"  更新超挖剩余面积: {new_text}")
        
        # 保存文件
        doc.saveas(output_path)
        print(f"\n共更新 {update_count} 个数值文本")
        print(f"文件已保存到: {output_path}")
        return True
        
    except Exception as e:
        print(f"更新DXF文件时出错: {e}")
        import traceback
        traceback.print_exc()
        return False


def load_excel_data(excel_path):
    """加载Excel数据"""
    df = pd.read_excel(excel_path)
    print(f"Excel列名: {list(df.columns)}")
    
    # 列名：桩号、开挖面积、超挖面积
    # 开挖面积 对应 设计剩余面积
    data = []
    for idx, row in df.iterrows():
        pile = str(row.iloc[0]).strip()
        # 开挖面积 = 设计剩余面积
        design_remain = float(row.iloc[1])
        overbreak = float(row.iloc[2])
        data.append({
            '桩号': pile,
            '设计剩余面积': design_remain,
            '超挖面积': overbreak
        })
    return data


if __name__ == "__main__":
    # 文件路径
    dxf_path = r"D:\2026年3月月进度测量段面图北海港铁山港20万吨级航道工程（啄罗作业区至石头埠作业区段）施工Ⅰ标段.dxf"
    excel_path = r"D:\汇总结果.xlsx"
    output_dir = r"D:\tunnel_build\输出文件"
    
    os.makedirs(output_dir, exist_ok=True)
    output_dxf = os.path.join(output_dir, "更新后_面积标注.dxf")
    
    # 加载Excel数据
    print("正在读取Excel数据...")
    excel_data = load_excel_data(excel_path)
    print(f"读取到 {len(excel_data)} 条数据")
    
    # 更新DXF文件
    print(f"\n正在更新DXF文件面积标注...")
    print("=" * 60)
    success = update_dxf_area_annotations(dxf_path, output_dxf, excel_data)
    
    if success:
        print("\n文件修改完成！")
    else:
        print("\n文件修改失败！")