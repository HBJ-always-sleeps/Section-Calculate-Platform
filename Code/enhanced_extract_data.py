import ezdxf
import pandas as pd
import os
import re
import datetime

def extract_pile_area_data(dxf_path):
    """
    从DXF文件中提取桩号和对应的面积数据
    
    关键发现：
    - 三行面积标注对应一个断面
    - 一个断面上可能有两个桩号（左右线）
    - 按Y坐标分断面，按X坐标区分左右桩号
    """
    try:
        doc = ezdxf.readfile(dxf_path)
        msp = doc.modelspace()
        
        # 面积单位字符 ㎡ (U+33A1)
        AREA_UNIT = '\u33A1'
        
        # ===== 1. 提取所有面积标注 =====
        area_annotations = []
        for entity in msp:
            if hasattr(entity, 'dxf') and entity.dxf.layer == '面积标注':
                if entity.dxftype() == 'TEXT':
                    text_content = entity.dxf.text
                    pos = entity.dxf.insert
                    area_annotations.append({
                        'text': text_content,
                        'x': pos[0],
                        'y': pos[1]
                    })
        
        # ===== 2. 提取桩号 =====
        pile_numbers = []
        for entity in msp:
            if hasattr(entity, 'dxf') and entity.dxf.layer == '桩号':
                if entity.dxftype() == 'TEXT':
                    text_content = entity.dxf.text
                    pos = entity.dxf.insert
                    pile_numbers.append({
                        'text': text_content,
                        'x': pos[0],
                        'y': pos[1]
                    })
        
        print(f"找到 {len(pile_numbers)} 个桩号，{len(area_annotations)} 个面积标注")
        
        # 打印桩号坐标用于调试
        print("\n桩号坐标分布：")
        for p in sorted(pile_numbers, key=lambda x: x['y'], reverse=True):
            print(f"  {p['text']}: X={p['x']:.1f}, Y={p['y']:.1f}")
        
        # ===== 3. 解析面积标注 =====
        # 分离描述文本和数值文本
        descriptions = []  # 描述文本（本期总剩余面积=等）
        values = []  # 数值文本（548.15㎡等）
        
        for ann in area_annotations:
            text = ann['text']
            
            # 判断是描述文本还是数值文本
            has_总 = '总' in text
            has_剩余 = '剩余' in text
            has_设计 = '设计' in text
            has_超挖 = '超挖' in text
            has_欠挖 = '欠挖' in text
            
            if has_总 and has_剩余 and not has_设计 and not has_超挖:
                # "本期总剩余面积=" → 断面剩余面积
                ann['type'] = '断面剩余面积'
                descriptions.append(ann)
            elif has_设计 and has_剩余:
                # "本期设计剩余面积=" → 超挖面积
                ann['type'] = '超挖面积'
                descriptions.append(ann)
            elif has_超挖 and has_剩余 and not has_设计:
                # "本期超挖剩余面积=" → 欠挖面积
                ann['type'] = '欠挖面积'
                descriptions.append(ann)
            elif has_欠挖 and not has_剩余:
                # "欠挖面积=" → 欠挖面积
                ann['type'] = '欠挖面积'
                descriptions.append(ann)
            elif AREA_UNIT in text:
                # 数值文本
                match = re.search(r'(\d+\.?\d*)', text)
                if match:
                    ann['value'] = float(match.group(1))
                    values.append(ann)
        
        print(f"描述文本: {len(descriptions)} 个，数值文本: {len(values)} 个")
        
        # 打印描述文本的Y坐标分布
        print("\n描述文本Y坐标分布：")
        for desc in sorted(descriptions, key=lambda x: x['y'], reverse=True):
            print(f"  {desc['type']}: Y={desc['y']:.1f}, X={desc['x']:.1f}")
        
        # ===== 4. 按Y坐标分组描述文本（容差5单位）=====
        y_tolerance = 5.0
        desc_y_groups = {}  # {y_key: [描述列表]}
        
        for desc in descriptions:
            y = desc['y']
            # 找到最近的Y组
            found_key = None
            for key in desc_y_groups.keys():
                if abs(key - y) < y_tolerance:
                    found_key = key
                    break
            
            if found_key:
                desc_y_groups[found_key].append(desc)
            else:
                desc_y_groups[y] = [desc]
        
        print(f"描述文本按Y坐标分为 {len(desc_y_groups)} 层")
        
        # ===== 5. 按Y坐标分组数值文本 =====
        value_y_groups = {}  # {y_key: [数值列表]}
        
        for val in values:
            y = val['y']
            found_key = None
            for key in value_y_groups.keys():
                if abs(key - y) < y_tolerance:
                    found_key = key
                    break
            
            if found_key:
                value_y_groups[found_key].append(val)
            else:
                value_y_groups[y] = [val]
        
        print(f"数值文本按Y坐标分为 {len(value_y_groups)} 层")
        
        # ===== 6. 按X坐标分组（区分左右桩号）=====
        # 观察数据：描述文本X约166和361，数值文本X约194和389
        # 左侧：X < 280，右侧：X >= 280
        
        def get_x_side(x):
            return 'left' if x < 280 else 'right'
        
        # 为每个描述找对应的数值（同一行Y相近，同一侧X相近）
        def match_value(desc, values):
            """为描述文本匹配最近的数值文本"""
            best_val = None
            best_dist = float('inf')
            
            for val in values:
                # Y坐标必须相近（同一行）
                y_dist = abs(val['y'] - desc['y'])
                if y_dist > 3:
                    continue
                
                # X必须在同一侧
                val_side = get_x_side(val['x'])
                desc_side = get_x_side(desc['x'])
                if val_side != desc_side:
                    continue
                
                # X距离
                x_dist = abs(val['x'] - desc['x'])
                
                # 选择X最近的
                if x_dist < best_dist:
                    best_dist = x_dist
                    best_val = val
            
            return best_val
        
        # ===== 7. 按桩号位置分组面积数据 =====
        # 关键思路：以桩号Y坐标为中心，向上搜索面积标注
        # 三行面积标注在桩号下方约0-30单位范围内
        
        results = []
        
        # 按桩号Y坐标分组（相近Y坐标的桩号为一对）
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
        
        print(f"\n桩号按Y坐标分为 {len(pile_y_groups)} 组")
        
        # 按Y坐标排序桩号组（从上到下，Y从大到小）
        sorted_pile_y = sorted(pile_y_groups.keys(), reverse=True)
        
        for group_idx, pile_y in enumerate(sorted_pile_y):
            piles_in_group = pile_y_groups[pile_y]
            print(f"\n=== 桩号组 {group_idx + 1} (Y={pile_y:.1f}) ===")
            print(f"  桩号: {[p['text'] for p in piles_in_group]}")
            
            # 找到这个桩号组对应的面积数据
            # 关键：面积标注在桩号的右上方（Y更大），范围约110-150单位
            # 使用最近匹配：找到Y差值最小的3个Y层
            
            # 计算每个描述文本与桩号的Y差值
            desc_y_diffs = []
            for desc in descriptions:
                y_diff = desc['y'] - pile_y  # 正值表示标注在桩号上方
                if 0 < y_diff < 200:  # 标注在桩号上方
                    desc_y_diffs.append({
                        'desc': desc,
                        'y_diff': y_diff
                    })
            
            # 按Y坐标分组
            y_groups = {}
            for item in desc_y_diffs:
                y = item['desc']['y']
                found_key = None
                for key in y_groups.keys():
                    if abs(key - y) < 5:
                        found_key = key
                        break
                if found_key:
                    y_groups[found_key].append(item)
                else:
                    y_groups[y] = [item]
            
            # 取Y差值最小的3个Y层（最近的3行）
            sorted_y_keys = sorted(y_groups.keys(), key=lambda y: abs(y - pile_y - 125))  # 最优差值约125
            closest_y_keys = sorted_y_keys[:3]  # 取最近的3层
            
            matching_descs = []
            for y_key in closest_y_keys:
                for item in y_groups[y_key]:
                    matching_descs.append(item['desc'])
            
            desc_y_values = sorted(set([d['y'] for d in matching_descs]), reverse=True)
            print(f"  找到 {len(matching_descs)} 个描述文本，{len(desc_y_values)} 个Y层 (最近匹配)")
            
            if len(desc_y_values) < 3:
                print(f"  警告: 描述文本Y层不足3层")
            
            # 按X坐标分左右
            left_descs = [d for d in matching_descs if get_x_side(d['x']) == 'left']
            right_descs = [d for d in matching_descs if get_x_side(d['x']) == 'right']
            
            print(f"  左侧描述: {len(left_descs)} 个, 右侧描述: {len(right_descs)} 个")
            
            # 构建左侧数据
            left_data = {'断面剩余面积': '', '超挖面积': '', '欠挖面积': ''}
            for desc in left_descs:
                val = match_value(desc, values)
                if val:
                    left_data[desc['type']] = str(val['value'])
                    print(f"    左侧: {desc['type']} = {val['value']}")
            
            # 构建右侧数据
            right_data = {'断面剩余面积': '', '超挖面积': '', '欠挖面积': ''}
            for desc in right_descs:
                val = match_value(desc, values)
                if val:
                    right_data[desc['type']] = str(val['value'])
                    print(f"    右侧: {desc['type']} = {val['value']}")
            
            # 按X坐标分左右桩号
            left_piles = [p for p in piles_in_group if get_x_side(p['x']) == 'left']
            right_piles = [p for p in piles_in_group if get_x_side(p['x']) == 'right']
            
            # 输出结果
            for pile in left_piles:
                results.append({
                    '桩号': pile['text'],
                    'X坐标': pile['x'],
                    'Y坐标': pile['y'],
                    '断面剩余面积': left_data['断面剩余面积'],
                    '超挖面积': left_data['超挖面积'],
                    '欠挖面积': left_data['欠挖面积']
                })
            
            for pile in right_piles:
                results.append({
                    '桩号': pile['text'],
                    'X坐标': pile['x'],
                    'Y坐标': pile['y'],
                    '断面剩余面积': right_data['断面剩余面积'],
                    '超挖面积': right_data['超挖面积'],
                    '欠挖面积': right_data['欠挖面积']
                })
        
        return results
        
    except Exception as e:
        print(f"提取DXF数据时出错: {e}")
        import traceback
        traceback.print_exc()
        return []

def save_to_excel(data_list, output_path):
    df = pd.DataFrame(data_list)
    df.to_excel(output_path, index=False)
    print(f"\n数据已保存到: {output_path}")

def sort_pile_number(pile_text):
    """从桩号文本中提取数字用于排序，如 K67+400 -> 67400"""
    match = re.search(r'K(\d+)\+(\d+)', pile_text)
    if match:
        return int(match.group(1)) * 1000 + int(match.group(2))
    return 0

def update_dxf_area_annotations(dxf_path, output_path, new_data):
    """
    更新DXF文件中的面积标注
    
    new_data: 字典列表，每个包含 {桩号, 设计剩余面积, 超挖面积}
    计算逻辑：总剩余面积 = 设计剩余面积 + 超挖面积
    """
    try:
        doc = ezdxf.readfile(dxf_path)
        msp = doc.modelspace()
        
        # 面积单位字符 ㎡ (U+33A1)
        AREA_UNIT = '\u33A1'
        
        # 1. 提取所有面积标注和桩号
        area_annotations = []
        pile_numbers = []
        
        for entity in msp:
            if hasattr(entity, 'dxf'):
                if entity.dxf.layer == '面积标注' and entity.dxftype() == 'TEXT':
                    area_annotations.append({
                        'entity': entity,
                        'text': entity.dxf.text,
                        'x': entity.dxf.insert[0],
                        'y': entity.dxf.insert[1]
                    })
                elif entity.dxf.layer == '桩号' and entity.dxftype() == 'TEXT':
                    pile_numbers.append({
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
                ann['type'] = '超挖面积'
                descriptions.append(ann)
            elif has_超挖 and has_剩余 and not has_设计:
                ann['type'] = '欠挖面积'
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
        
        # 5. 为每个桩号组匹配数值文本
        def get_x_side(x):
            return 'left' if x < 280 else 'right'
        
        def match_value(desc, values):
            best_val = None
            best_dist = float('inf')
            for val in values:
                y_dist = abs(val['y'] - desc['y'])
                if y_dist > 3:
                    continue
                val_side = get_x_side(val['x'])
                desc_side = get_x_side(desc['x'])
                if val_side != desc_side:
                    continue
                x_dist = abs(val['x'] - desc['x'])
                if x_dist < best_dist:
                    best_dist = x_dist
                    best_val = val
            return best_val
        
        # 6. 按桩号顺序排序新数据
        sorted_new_data = sorted(new_data, key=lambda x: sort_pile_number(x['桩号']))
        print(f"\n新数据（按桩号排序）：")
        for d in sorted_new_data:
            print(f"  {d['桩号']}: 设计剩余={d['设计剩余面积']}, 超挖={d['超挖面积']}")
        
        # 7. 更新数值文本
        update_count = 0
        
        for group_idx, pile_y in enumerate(sorted_pile_y):
            piles_in_group = pile_y_groups[pile_y]
            
            # 按X坐标分左右桩号并排序
            left_piles = sorted([p for p in piles_in_group if get_x_side(p['x']) == 'left'], key=lambda p: p['text'])
            right_piles = sorted([p for p in piles_in_group if get_x_side(p['x']) == 'right'], key=lambda p: p['text'])
            
            # 找到对应的面积标注
            desc_y_diffs = []
            for desc in descriptions:
                y_diff = desc['y'] - pile_y
                if 0 < y_diff < 200:
                    desc_y_diffs.append({'desc': desc, 'y_diff': y_diff})
            
            y_groups = {}
            for item in desc_y_diffs:
                y = item['desc']['y']
                found_key = None
                for key in y_groups.keys():
                    if abs(key - y) < 5:
                        found_key = key
                        break
                if found_key:
                    y_groups[found_key].append(item)
                else:
                    y_groups[y] = [item]
            
            sorted_y_keys = sorted(y_groups.keys(), key=lambda y: abs(y - pile_y - 125))
            closest_y_keys = sorted_y_keys[:3]
            
            matching_descs = []
            for y_key in closest_y_keys:
                for item in y_groups[y_key]:
                    matching_descs.append(item['desc'])
            
            left_descs = [d for d in matching_descs if get_x_side(d['x']) == 'left']
            right_descs = [d for d in matching_descs if get_x_side(d['x']) == 'right']
            
            # 更新左侧数据
            if left_piles:
                pile_text = left_piles[0]['text']
                # 找到对应的新数据
                pile_data = None
                for d in sorted_new_data:
                    if d['桩号'] == pile_text:
                        pile_data = d
                        break
                
                if pile_data:
                    # 计算总剩余面积
                    design_remain = pile_data['设计剩余面积']
                    overbreak = pile_data['超挖面积']
                    total_remain = round(design_remain + overbreak, 2)
                    
                    print(f"\n更新 {pile_text}: 设计剩余={design_remain}, 超挖={overbreak}, 总剩余={total_remain}")
                    
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
                                print(f"  更新设计剩余面积(超挖): {new_text}")
                            elif desc['type'] == '欠挖面积':
                                new_text = f"{overbreak:.2f}{AREA_UNIT}"
                                entity.dxf.text = new_text
                                update_count += 1
                                print(f"  更新超挖剩余面积(欠挖): {new_text}")
            
            # 更新右侧数据
            if right_piles:
                pile_text = right_piles[0]['text']
                pile_data = None
                for d in sorted_new_data:
                    if d['桩号'] == pile_text:
                        pile_data = d
                        break
                
                if pile_data:
                    design_remain = pile_data['设计剩余面积']
                    overbreak = pile_data['超挖面积']
                    total_remain = round(design_remain + overbreak, 2)
                    
                    print(f"\n更新 {pile_text}: 设计剩余={design_remain}, 超挖={overbreak}, 总剩余={total_remain}")
                    
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
                                print(f"  更新设计剩余面积(超挖): {new_text}")
                            elif desc['type'] == '欠挖面积':
                                new_text = f"{overbreak:.2f}{AREA_UNIT}"
                                entity.dxf.text = new_text
                                update_count += 1
                                print(f"  更新超挖剩余面积(欠挖): {new_text}")
        
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

if __name__ == "__main__":
    dxf_path = r"D:\tunnel_build\测试文件\自动标注测试.dxf"
    output_dir = r"D:\tunnel_build\测试文件"
    os.makedirs(output_dir, exist_ok=True)
    
    # 测试数据：桩号、设计剩余面积、超挖面积
    # 计算逻辑：总剩余面积 = 设计剩余面积 + 超挖面积
    test_data = [
        {'桩号': 'K67+400', '设计剩余面积': 350.25, '超挖面积': 180.50},
        {'桩号': 'K67+425', '设计剩余面积': 420.75, '超挖面积': 195.30},
        {'桩号': 'K67+450', '设计剩余面积': 380.60, '超挖面积': 188.45},
        {'桩号': 'K67+475', '设计剩余面积': 430.80, '超挖面积': 192.15},
        {'桩号': 'K67+500', '设计剩余面积': 395.40, '超挖面积': 185.90},
        {'桩号': 'K67+525', '设计剩余面积': 410.35, '超挖面积': 178.60},
        {'桩号': 'K67+550', '设计剩余面积': 445.70, '超挖面积': 182.25},
        {'桩号': 'K67+575', '设计剩余面积': 460.15, '超挖面积': 175.80},
    ]
    
    # 输出文件路径
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dxf = os.path.join(output_dir, f"自动标注测试_修改_{timestamp}.dxf")
    
    print(f"正在更新DXF文件面积标注...\n")
    print("="*60)
    print("测试数据（按桩号排序）：")
    print("="*60)
    for d in sorted(test_data, key=lambda x: sort_pile_number(x['桩号'])):
        total = d['设计剩余面积'] + d['超挖面积']
        print(f"  {d['桩号']}: 设计剩余={d['设计剩余面积']:.2f}, 超挖={d['超挖面积']:.2f}, 总剩余={total:.2f}")
    print("="*60)
    
    success = update_dxf_area_annotations(dxf_path, output_dxf, test_data)
    
    if success:
        print("\n文件修改完成！")
    else:
        print("\n文件修改失败！")
