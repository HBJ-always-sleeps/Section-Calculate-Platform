import ezdxf
import pandas as pd
from collections import defaultdict
import os

def debug_extract_pile_area_data(dxf_path):
    """
    调试版本：详细分析DXF文件中的桩号和面积标注数据
    """
    try:
        # 读取DXF文件
        doc = ezdxf.readfile(dxf_path)
        msp = doc.modelspace()
        
        # 提取面积标注数据
        area_annotations = []
        for entity in msp:
            if hasattr(entity, 'dxf') and entity.dxf.layer == '面积标注':
                if entity.dxftype() == 'TEXT':
                    text_content = entity.dxf.text
                    pos = entity.dxf.insert
                    area_annotations.append({
                        'text': text_content,
                        'position': pos,
                        'x': pos[0],
                        'y': pos[1]
                    })
        
        # 提取桩号数据
        pile_numbers = []
        for entity in msp:
            if hasattr(entity, 'dxf') and entity.dxf.layer == '桩号':
                if entity.dxftype() == 'TEXT':
                    text_content = entity.dxf.text
                    pos = entity.dxf.insert
                    pile_numbers.append({
                        'text': text_content,
                        'position': pos,
                        'x': pos[0],
                        'y': pos[1]
                    })
        
        print("=== 桩号数据 ===")
        for pile in pile_numbers:
            print(f"桩号: {pile['text']}, 位置: ({pile['x']}, {pile['y']})")
        
        print("\n=== 面积标注数据 ===")
        for area in area_annotations:
            print(f"文本: '{area['text']}', 位置: ({area['x']}, {area['y']})")
        
        # 按Y坐标分组面积标注
        y_groups = {}
        for ann in area_annotations:
            y_coord = round(ann['y'], 2)
            if y_coord not in y_groups:
                y_groups[y_coord] = []
            y_groups[y_coord].append(ann)
        
        print("\n=== 面积标注按Y坐标分组 ===")
        for y_coord, areas in sorted(y_groups.items(), key=lambda x: x[0], reverse=True):
            print(f"Y={y_coord}:")
            for area in areas:
                print(f"  - '{area['text']}' at ({area['x']}, {area['y']})")
        
        print("\n=== 桩号与面积标注的对应关系分析 ===")
        for pile in pile_numbers:
            print(f"\n桩号 {pile['text']} (Y={pile['y']}):")
            
            # 查找附近的面积标注
            nearby_areas = []
            for y_coord, areas in y_groups.items():
                distance = abs(y_coord - pile['y'])
                if distance <= 150 and y_coord < pile['y']:  # 在桩号下方且距离合理
                    for area in areas:
                        nearby_areas.append((distance, area))
            
            # 按距离排序
            nearby_areas.sort(key=lambda x: x[0])
            
            print(f"  找到 {len(nearby_areas)} 个附近的面积标注:")
            for dist, area in nearby_areas[:10]:  # 显示最近的10个
                print(f"    距离{dist:.2f}: '{area['text']}' at ({area['x']}, {area['y']})")
        
        return pile_numbers, area_annotations, y_groups
        
    except Exception as e:
        print(f"调试提取DXF数据时出错: {e}")
        import traceback
        traceback.print_exc()
        return [], [], {}

def extract_with_debug_logic(pile_numbers, area_annotations, y_groups):
    """
    使用调试后的逻辑进行数据提取
    """
    results = []
    
    for pile in pile_numbers:
        pile_y = pile['y']
        pile_x = pile['x']
        
        # 查找与当前桩号相关的面积标注
        relevant_areas = []
        
        # 查找与当前桩号Y坐标最接近的几个Y坐标组
        y_distances = [(abs(y - pile_y), y) for y in y_groups.keys()]
        y_distances.sort()  # 按距离排序
        
        # 取最近的几个Y坐标组（基于之前的分析，通常是3个Y坐标）
        for dist, y_coord in y_distances[:3]:  # 取最近的3个Y坐标
            if dist <= 120 and y_coord < pile_y:  # 距离阈值且在桩号下方
                relevant_areas.extend(y_groups[y_coord])
        
        # 按X坐标排序相关面积标注
        relevant_areas.sort(key=lambda x: x['x'])
        
        print(f"\n=== 桩号 {pile['text']} 的详细分析 ===")
        print(f"桩号位置: ({pile['x']}, {pile['y']})")
        print(f"找到 {len(relevant_areas)} 个相关面积标注:")
        for area in relevant_areas:
            print(f"  - '{area['text']}' at ({area['x']}, {area['y']})")
        
        # 分析面积数据
        area_data = {
            '桩号': pile['text'],
            'X坐标': pile['x'],
            'Y坐标': pile['y'],
            '断面剩余面积': '',
            '超挖面积': '',
            '欠挖面积': '',
            '面积数值1': '',
            '面积数值2': '',
            '面积数值3': ''
        }
        
        # 收集所有面积数值（带'O'的数字）
        area_values = []
        area_texts_with_coords = {}
        
        for area in relevant_areas:
            text = area['text']
            if 'O' in text and not any(keyword in text for keyword in ['断面剩余面积=', '超挖面积=', '欠挖面积=']):
                # 提取数字部分
                import re
                numbers = re.findall(r'\d+\.?\d+', text.replace('O', '').strip())
                for num in numbers:
                    if num and num != '.':
                        try:
                            float_val = float(num)
                            area_values.append(float_val)
                            area_texts_with_coords[float_val] = {
                                'text': text,
                                'x': area['x'],
                                'y': area['y']
                            }
                        except ValueError:
                            continue
        
        print(f"提取到的面积数值: {sorted(area_values, reverse=True)}")
        
        # 按大小排序面积数值
        area_values_sorted = sorted(set(area_values), reverse=True)
        if len(area_values_sorted) >= 3:
            area_data['面积数值1'] = str(area_values_sorted[2])
            area_data['面积数值2'] = str(area_values_sorted[1])
            area_data['面积数值3'] = str(area_values_sorted[0])
        elif len(area_values_sorted) == 2:
            area_data['面积数值1'] = str(area_values_sorted[1])
            area_data['面积数值2'] = str(area_values_sorted[0])
        elif len(area_values_sorted) == 1:
            area_data['面积数值1'] = str(area_values_sorted[0])
        
        # 查找描述性文本对应的数值
        for area in relevant_areas:
            text = area['text']
            
            if '断面剩余面积=' in text:
                # 查找同一Y坐标附近的面积数值
                target_y = area['y']
                for val, info in area_texts_with_coords.items():
                    if abs(info['y'] - target_y) < 2:  # 非常接近的Y坐标
                        area_data['断面剩余面积'] = str(val)
                        print(f"断面剩余面积匹配: {val} at Y={info['y']}")
                        break
            
            elif '超挖面积=' in text:
                target_y = area['y']
                for val, info in area_texts_with_coords.items():
                    if abs(info['y'] - target_y) < 2:
                        area_data['超挖面积'] = str(val)
                        print(f"超挖面积匹配: {val} at Y={info['y']}")
                        break
            
            elif '欠挖面积=' in text:
                target_y = area['y']
                for val, info in area_texts_with_coords.items():
                    if abs(info['y'] - target_y) < 2:
                        area_data['欠挖面积'] = str(val)
                        print(f"欠挖面积匹配: {val} at Y={info['y']}")
                        break
        
        results.append(area_data)
    
    return results

if __name__ == "__main__":
    # 创建输出目录
    output_dir = r"D:\tunnel_build\Code"
    os.makedirs(output_dir, exist_ok=True)
    
    dxf_path = r"D:\tunnel_build\测试文件\自动标注测试.dxf"
    
    print(f"正在从 {dxf_path} 进行调试分析...")
    
    # 进行调试分析
    pile_numbers, area_annotations, y_groups = debug_extract_pile_area_data(dxf_path)
    
    if pile_numbers and area_annotations:
        # 使用调试后的逻辑进行数据提取
        extracted_data = extract_with_debug_logic(pile_numbers, area_annotations, y_groups)
        
        # 打印最终结果
        print("\n" + "="*80)
        print("最终提取结果")
        print("="*80)
        for data in extracted_data:
            print(f"桩号 {data['桩号']} (X:{data['X坐标']}, Y:{data['Y坐标']}):")
            print(f"  - 断面剩余面积: {data['断面剩余面积']}")
            print(f"  - 超挖面积: {data['超挖面积']}")
            print(f"  - 欠挖面积: {data['欠挖面积']}")
            print(f"  - 面积数值1: {data['面积数值1']}")
            print(f"  - 面积数值2: {data['面积数值2']}")
            print(f"  - 面积数值3: {data['面积数值3']}")
            print()
        
        # 保存到Excel
        if extracted_data:
            df = pd.DataFrame(extracted_data)
            column_order = ['桩号', 'X坐标', 'Y坐标', '断面剩余面积', '超挖面积', '欠挖面积', '面积数值1', '面积数值2', '面积数值3']
            df = df[column_order]
            
            output_excel = os.path.join(output_dir, "调试版桩号面积数据提取结果.xlsx")
            df.to_excel(output_excel, index=False)
            print(f"数据已保存到: {output_excel}")
    else:
        print("未能提取到数据。")