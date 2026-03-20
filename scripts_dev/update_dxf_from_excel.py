import ezdxf
import pandas as pd
import os
import re
import datetime

def sort_pile_number(pile_text):
    match = re.search(r'K(\d+)\+(\d+)', pile_text)
    if match:
        return int(match.group(1)) * 1000 + int(match.group(2))
    return 0

def update_dxf_from_excel(dxf_path, excel_path, output_path, area_layer='0', pile_layer='桩号'):
    try:
        # 1. 读取Excel
        print(f"读取Excel: {excel_path}")
        df = pd.read_excel(excel_path)
        print(f"列名: {df.columns.tolist()}")
        
        new_data = []
        for _, row in df.iterrows():
            pile_text = str(row['桩号']).strip()
            design_remain = float(row['开挖面积']) if '开挖面积' in df.columns else 0.0
            overbreak = float(row['超挖面积']) if '超挖面积' in df.columns else 0.0
            new_data.append({
                '桩号': pile_text,
                '设计剩余面积': design_remain,
                '超挖面积': overbreak
            })
        new_data = sorted(new_data, key=lambda x: sort_pile_number(x['桩号']))
        
        # 2. 读取DXF
        print(f"读取DXF: {dxf_path}")
        doc = ezdxf.readfile(dxf_path)
        msp = doc.modelspace()
        AREA_UNIT = '\u33A1'
        
        # 3. 提取所有文本
        all_texts = []
        for entity in msp:
            if hasattr(entity, 'dxf') and entity.dxftype() == 'TEXT':
                all_texts.append({
                    'entity': entity,
                    'text': entity.dxf.text,
                    'layer': entity.dxf.layer,
                    'x': entity.dxf.insert[0],
                    'y': entity.dxf.insert[1]
                })
        
        piles = [t for t in all_texts if t['layer'] == pile_layer]
        area_texts = [t for t in all_texts if t['layer'] == area_layer]
        print(f"桩号: {len(piles)}, 面积标注: {len(area_texts)}")
        
        # 4. 解析面积标注
        # 描述文本：本期总剩余面积=、本期设计剩余面积=、本期超挖剩余面积=
        # 数值文本：数字+O
        
        descriptions = []  # 描述文本
        values = []        # 数值文本
        
        for t in area_texts:
            text = t['text']
            match = re.search(r'(\d+\.?\d*)', text)
            
            if '本期总剩余面积=' in text:
                t['type'] = '总剩余'
                descriptions.append(t)
            elif '本期设计剩余面积=' in text:
                t['type'] = '设计'
                descriptions.append(t)
            elif '本期超挖剩余面积=' in text:
                t['type'] = '超挖'
                descriptions.append(t)
            elif match and ('O' in text or AREA_UNIT in text):
                t['value'] = float(match.group(1))
                values.append(t)
        
        print(f"描述文本: {len(descriptions)}, 数值文本: {len(values)}")
        
        # 5. 关键：为每个数值文本找到同一行的描述文本（确定类型）
        # 同一行：Y相近（差值<3），X在描述文本右边约30单位
        
        for val in values:
            # 找同一行最近的描述文本
            best_desc = None
            best_x_dist = float('inf')
            
            for desc in descriptions:
                y_diff = abs(val['y'] - desc['y'])
                if y_diff < 3:  # 同一行
                    x_dist = val['x'] - desc['x']  # 数值应该在描述右边
                    if 0 < x_dist < 100 and x_dist < best_x_dist:
                        best_x_dist = x_dist
                        best_desc = desc
            
            if best_desc:
                val['type'] = best_desc['type']
                val['desc_x'] = best_desc['x']
        
        # 6. 按Y坐标分组桩号
        pile_y_groups = {}
        y_tolerance = 30.0
        for pile in piles:
            y = pile['y']
            found_key = None
            for key in pile_y_groups.keys():
                if abs(key - y) < y_tolerance:
                    found_key = key
                    break
            if found_key:
                pile_y_groups[found_key].append(pile)
            else:
                pile_y_groups[y] = [pile]
        
        print(f"桩号Y组: {len(pile_y_groups)}")
        
        # 7. 按Y坐标分组数值文本
        value_y_groups = {}
        for val in values:
            y = val['y']
            found_key = None
            for key in value_y_groups.keys():
                if abs(key - y) < 3:
                    found_key = key
                    break
            if found_key:
                value_y_groups[found_key].append(val)
            else:
                value_y_groups[y] = [val]
        
        print(f"数值Y组: {len(value_y_groups)}")
        
        # 8. 建立桩号和数值文本的对应关系
        # 关键：数值文本在桩号上方（Y更大），每3行对应一个桩号组
        
        sorted_pile_y = sorted(pile_y_groups.keys(), reverse=True)  # Y从大到小
        sorted_value_y = sorted(value_y_groups.keys(), reverse=True)
        
        # 每个桩号组对应最近的3个数值Y层
        update_count = 0
        verify_data = []
        
        for pile_y in sorted_pile_y:
            piles_in_group = pile_y_groups[pile_y]
            
            # 找桩号上方的数值Y层（Y > 桩号Y）
            above_value_y = [y for y in sorted_value_y if y > pile_y]
            if len(above_value_y) < 3:
                continue
            
            # 取最近的3层
            closest_3_y = sorted(above_value_y, key=lambda y: y - pile_y)[:3]
            
            # 按X坐标分左右
            piles_by_x = {}
            for pile in piles_in_group:
                x = pile['x']
                found = False
                for key in piles_by_x:
                    if abs(key - x) < 100:
                        piles_by_x[key].append(pile)
                        found = True
                        break
                if not found:
                    piles_by_x[x] = [pile]
            
            # 对每个X位置的桩号
            for pile_x_key, pile_list in piles_by_x.items():
                pile = pile_list[0]
                pile_text = pile['text']
                
                # 找对应的数据
                pile_data = None
                for d in new_data:
                    if d['桩号'] == pile_text:
                        pile_data = d
                        break
                
                if not pile_data:
                    continue
                
                design = pile_data['设计剩余面积']
                overbreak = pile_data['超挖面积']
                total = round(design + overbreak, 2)
                
                # 找这个X位置的数值文本
                # X范围：基于桩号X，但数值文本X可能在描述文本右边
                # 从数值文本中找X相近的
                
                # 先找所有相关Y层的数值文本
                related_values = []
                for y in closest_3_y:
                    for val in value_y_groups[y]:
                        # X匹配：桩号X附近（考虑描述文本偏移）
                        # 桩号X=123.9 -> 描述X=166.2 -> 数值X=197.7
                        # 所以范围应该是桩号X到桩号X+100左右
                        if pile['x'] - 30 <= val['x'] <= pile['x'] + 150:
                            if 'type' in val:
                                related_values.append(val)
                
                if len(related_values) < 3:
                    continue
                
                # 更新
                updated = {'总剩余': None, '设计': None, '超挖': None}
                for val in related_values:
                    if 'type' not in val:
                        continue
                    entity = val['entity']
                    old_val = val['value']
                    
                    if val['type'] == '总剩余':
                        new_text = f"{total:.2f}{AREA_UNIT}"
                        entity.dxf.text = new_text
                        updated['总剩余'] = {'old': old_val, 'new': total}
                        update_count += 1
                    elif val['type'] == '设计':
                        new_text = f"{design:.2f}{AREA_UNIT}"
                        entity.dxf.text = new_text
                        updated['设计'] = {'old': old_val, 'new': design}
                        update_count += 1
                    elif val['type'] == '超挖':
                        new_text = f"{overbreak:.2f}{AREA_UNIT}"
                        entity.dxf.text = new_text
                        updated['超挖'] = {'old': old_val, 'new': overbreak}
                        update_count += 1
                
                verify_data.append({
                    '桩号': pile_text,
                    '期望': {'总': total, '设计': design, '超挖': overbreak},
                    '更新': updated
                })
        
        # 保存
        doc.saveas(output_path)
        print(f"\n更新了 {update_count} 个数值")
        
        # ===== 验证 =====
        print("\n" + "="*60)
        print("验证结果")
        print("="*60)
        
        # 重新读取验证
        doc2 = ezdxf.readfile(output_path)
        msp2 = doc2.modelspace()
        
        verify_values = []
        for entity in msp2:
            if hasattr(entity, 'dxf') and entity.dxftype() == 'TEXT':
                if entity.dxf.layer == area_layer:
                    text = entity.dxf.text
                    match = re.search(r'(\d+\.?\d*)', text)
                    if match and (AREA_UNIT in text or 'O' in text):
                        verify_values.append({
                            'value': float(match.group(1)),
                            'x': entity.dxf.insert[0],
                            'y': entity.dxf.insert[1]
                        })
        
        success = 0
        fail = 0
        for v in verify_data[:20]:
            pile = v['桩号']
            exp = v['期望']
            upd = v['更新']
            
            print(f"\n{pile}:")
            print(f"  期望: 总={exp['总']:.2f}, 设计={exp['设计']:.2f}, 超挖={exp['超挖']:.2f}")
            if upd['总剩余']:
                print(f"  总剩余: {upd['总剩余']['old']:.2f} -> {upd['总剩余']['new']:.2f}")
            if upd['设计']:
                print(f"  设计: {upd['设计']['old']:.2f} -> {upd['设计']['new']:.2f}")
            if upd['超挖']:
                print(f"  超挖: {upd['超挖']['old']:.2f} -> {upd['超挖']['new']:.2f}")
            
            # 检查是否更新成功
            if upd['总剩余'] and upd['设计'] and upd['超挖']:
                success += 1
            else:
                fail += 1
        
        print(f"\n成功: {success}, 失败: {fail}")
        print(f"文件: {output_path}")
        return True
        
    except Exception as e:
        print(f"错误: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    dxf_path = r"D:\2026年3月月进度测量段面图北海港铁山港20万吨级航道工程（啄罗作业区至石头埠作业区段）施工Ⅰ标段.dxf"
    excel_path = r"D:\汇总结果.xlsx"
    output_dir = "D:\\"
    
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dxf = os.path.join(output_dir, f"面积标注更新_{timestamp}.dxf")
    
    print("="*60)
    print("DXF面积标注更新")
    print("="*60)
    
    success = update_dxf_from_excel(
        dxf_path=dxf_path,
        excel_path=excel_path,
        output_path=output_dxf,
        area_layer='0',
        pile_layer='桩号'
    )
    
    print("\n[OK]" if success else "\n[FAIL]")