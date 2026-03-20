import ezdxf
import pandas as pd
from collections import defaultdict
import os

def extract_pile_area_data(dxf_path):
    """
    从DXF文件中提取桩号和对应的面积数据
    返回按桩号组织的面积数据表
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
        
        # 按Y坐标对面积标注进行分组
        y_groups = {}
        for ann in area_annotations:
            y_coord = round(ann['y'], 2)
            if y_coord not in y_groups:
                y_groups[y_coord] = []
            y_groups[y_coord].append(ann)
        
        # 按Y坐标排序桩号
        pile_numbers.sort(key=lambda x: x['y'], reverse=True)
        
        # 为每个桩号找到对应的面积数据
        results = []
        
        for pile in pile_numbers:
            pile_y = pile['y']
            pile_x = pile['x']
            
            # 根据前面的分析，我们需要找到与桩号Y坐标相近的3行面积标注
            # 这些面积标注通常在桩号下方一定距离范围内
            relevant_areas = []
            
            # 分析之前的结果，面积标注通常出现在桩号Y坐标下方约8-110单位的位置
            # 对于每个桩号，我们查找特定范围内的面积标注
            for y_coord, areas in y_groups.items():
                # 计算面积标注Y坐标与桩号Y坐标的距离
                distance = abs(y_coord - pile_y)
                
                # 根据之前的分析，有效的面积标注通常在这些距离范围内：
                # - 较近的距离：约8-15单位（靠近桩号）
                # - 较远的距离：约110单位（稍远一些）
                if 5 <= distance <= 120:  # 合理的距离范围
                    # 但还要考虑面积标注的Y坐标应该小于桩号Y坐标（在下方）
                    if y_coord < pile_y:  # 面积标注在桩号下方
                        relevant_areas.extend(areas)
            
            # 如果上述方法没找到足够的面积标注，尝试更宽松的条件
            if len(relevant_areas) < 3:
                for y_coord, areas in y_groups.items():
                    distance = abs(y_coord - pile_y)
                    if distance <= 150 and y_coord < pile_y:  # 更宽松的范围
                        relevant_areas.extend(areas)
            
            # 按X坐标排序相关面积标注，以便识别不同类型
            relevant_areas.sort(key=lambda x: x['x'])
            
            # 分析面积数据
            area_data = {
                '桩号': pile['text'],
                'X坐标': pile['x'],
                'Y坐标': pile['y'],
                '断面剩余面积': '',
                '超挖面积': '',
                '欠挖面积': '',
                '面积数值1': '',  # 通常是较小的面积值
                '面积数值2': '',  # 通常是中间的面积值
                '面积数值3': ''   # 通常是最大的面积值
            }
            
            # 首先收集所有面积数值（带'O'的数字）
            area_values = []
            area_value_dict = {}  # 存储面积值及其坐标信息
            
            for area in relevant_areas:
                text = area['text']
                if 'O' in text and not any(keyword in text for keyword in ['断面剩余面积=', '超挖面积=', '欠挖面积=']):
                    # 提取数字部分 - 处理可能的空格和其他字符
                    import re
                    # 匹配数字（包括小数），后面跟着'O'
                    pattern = r'(\d+\.?\d*)\s*O'
                    matches = re.findall(pattern, text)
                    for match in matches:
                        if match and match != '.':
                            try:
                                float_val = float(match)
                                area_values.append(float_val)
                                # 记录数值的坐标信息
                                area_value_dict[float_val] = {'x': area['x'], 'y': area['y']}
                            except ValueError:
                                continue
            
            # 按大小排序面积数值
            area_values_sorted = sorted(set(area_values), reverse=True)  # 去重并从大到小排序
            if len(area_values_sorted) >= 3:
                area_data['面积数值1'] = str(area_values_sorted[2])  # 最小值
                area_data['面积数值2'] = str(area_values_sorted[1])  # 中间值
                area_data['面积数值3'] = str(area_values_sorted[0])  # 最大值
            elif len(area_values_sorted) == 2:
                area_data['面积数值1'] = str(area_values_sorted[1])
                area_data['面积数值2'] = str(area_values_sorted[0])
            elif len(area_values_sorted) == 1:
                area_data['面积数值1'] = str(area_values_sorted[0])
            
            # 查找描述性文本对应的数值 - 更精确的匹配
            for area in relevant_areas:
                text = area['text']
                
                if '断面剩余面积=' in text:
                    # 在相同Y坐标附近的面积数值中查找
                    target_y = area['y']
                    for val, coords in area_value_dict.items():
                        if abs(coords['y'] - target_y) < 2:  # 非常接近的Y坐标
                            area_data['断面剩余面积'] = str(val)
                            break
                
                elif '超挖面积=' in text:
                    target_y = area['y']
                    for val, coords in area_value_dict.items():
                        if abs(coords['y'] - target_y) < 2:
                            area_data['超挖面积'] = str(val)
                            break
                
                elif '欠挖面积=' in text:
                    target_y = area['y']
                    for val, coords in area_value_dict.items():
                        if abs(coords['y'] - target_y) < 2:
                            area_data['欠挖面积'] = str(val)
                            break
            
            results.append(area_data)
        
        return results
        
    except Exception as e:
        print(f"提取DXF数据时出错: {e}")
        return []

def save_to_excel(data_list, output_path):
    """将数据保存到Excel文件"""
    df = pd.DataFrame(data_list)
    
    # 重新排列列的顺序
    column_order = ['桩号', 'X坐标', 'Y坐标', '断面剩余面积', '超挖面积', '欠挖面积', '面积数值1', '面积数值2', '面积数值3']
    df = df[column_order]
    
    df.to_excel(output_path, index=False)
    print(f"数据已保存到: {output_path}")

def print_analysis_summary(data_list):
    """打印分析摘要"""
    print("=" * 80)
    print("DXF文件面积数据提取分析报告")
    print("=" * 80)
    print(f"共提取到 {len(data_list)} 个桩号的数据")
    print()
    
    for i, data in enumerate(data_list):
        print(f"桩号 {data['桩号']} (X:{data['X坐标']}, Y:{data['Y坐标']}):")
        print(f"  - 断面剩余面积: {data['断面剩余面积']}")
        print(f"  - 超挖面积: {data['超挖面积']}")
        print(f"  - 欠挖面积: {data['欠挖面积']}")
        print(f"  - 面积数值1: {data['面积数值1']}")
        print(f"  - 面积数值2: {data['面积数值2']}")
        print(f"  - 面积数值3: {data['面积数值3']}")
        print()

if __name__ == "__main__":
    # 创建输出目录 - 输出到测试文件目录
    output_dir = r"D:\tunnel_build\测试文件"
    os.makedirs(output_dir, exist_ok=True)
    
    dxf_path = r"D:\tunnel_build\测试文件\自动标注测试.dxf"
    output_excel = os.path.join(output_dir, "桩号面积数据提取结果.xlsx")
    
    print(f"正在从 {dxf_path} 提取桩号和面积数据...")
    
    # 提取数据
    extracted_data = extract_pile_area_data(dxf_path)
    
    if extracted_data:
        # 打印分析摘要
        print_analysis_summary(extracted_data)
        
        # 保存到Excel
        save_to_excel(extracted_data, output_excel)
        
        print("数据提取完成！")
        print(f"提取的数据已保存到: {output_excel}")
    else:
        print("未能提取到任何数据，请检查DXF文件和图层设置。")