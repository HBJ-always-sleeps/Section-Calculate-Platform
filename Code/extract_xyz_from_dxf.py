# -*- coding: utf-8 -*-
"""
从DXF文件提取开挖线和超挖线的XYZ坐标
参考engine_cad_working_v3.py的断面提取和标尺解析逻辑

核心逻辑：
1. 断面基准：DMX图层（每个DMX多段线代表一个断面）
2. 标尺解析：RulerDetector.detect_scale方法（块内Y + INSERT_Y）
3. X坐标：相对于断面中心线的偏移
4. Y坐标：CAD坐标Y（用于区分断面内的位置）
5. Z坐标：根据标尺比例插值高程

作者: Cline
日期: 2026-04-10
"""

import ezdxf
import sys
import io
import math
import json
from collections import defaultdict
from typing import List, Tuple, Dict, Optional
from shapely.geometry import LineString, box

# 设置输出编码
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')


# ==================== 标尺检测器（参考engine_cad_working_v3.py第450-517行） ====================

class RulerDetector:
    """标尺检测器 - 使用线性回归拟合高程与Y坐标关系"""
    
    @staticmethod
    def detect_scale(msp, doc, sect_x_min, sect_x_max, sect_y_center, sect_y_min, sect_y_max, l1_y=None):
        """检测标尺比例，返回(elev_to_y, y_to_elev)函数对
        
        Args:
            msp: modelspace
            doc: dxf document
            sect_x_min, sect_x_max: 断面X范围
            sect_y_center: 断面Y中心
            sect_y_min, sect_y_max: 断面Y范围
            l1_y: L1交点Y坐标（用于验证标尺b值）
            
        Returns:
            (elev_to_y_func, y_to_elev_func) 或 None
        """
        ruler_layers = ['标尺', '0-标尺', 'RULER']
        ruler_candidates = []
        
        for layer_name in ruler_layers:
            for e in msp.query(f'*[layer=="{layer_name}"]'):
                try:
                    if e.dxftype() == 'INSERT':
                        insert_x, insert_y = e.dxf.insert.x, e.dxf.insert.y
                        if sect_x_min - 100 <= insert_x <= sect_x_max + 100:
                            y_min, y_max = insert_y, insert_y
                            try:
                                block_name = e.dxf.name
                                if block_name in doc.blocks:
                                    for be in doc.blocks[block_name]:
                                        if be.dxftype() in ('TEXT', 'MTEXT'):
                                            try:
                                                world_y = be.dxf.insert.y + insert_y
                                                y_min, y_max = min(y_min, world_y), max(y_max, world_y)
                                            except: pass
                            except: pass
                            ruler_candidates.append({'x': insert_x, 'y_min': y_min, 'y_max': y_max, 'entity': e})
                except: pass
        
        if not ruler_candidates:
            return None
        
        sect_x_center = (sect_x_min + sect_x_max) / 2
        
        # 先计算所有候选标尺的a和b值
        ruler_params = []
        for ruler in ruler_candidates:
            elevation_points = []
            if ruler.get('entity'):
                insert_y = ruler['entity'].dxf.insert.y
                try:
                    block_name = ruler['entity'].dxf.name
                    if block_name in doc.blocks:
                        for be in doc.blocks[block_name]:
                            if be.dxftype() in ('TEXT', 'MTEXT'):
                                try:
                                    world_y = be.dxf.insert.y + insert_y
                                    text = (be.dxf.text if be.dxftype() == 'TEXT' else be.text).strip()
                                    if text.startswith('-') or (text[0].isdigit() and '高程' not in text):
                                        elevation = float(text.replace('m', '').strip())
                                        elevation_points.append((world_y, elevation))
                                except: pass
                except: pass
            
            if len(elevation_points) >= 2:
                n = len(elevation_points)
                sum_y = sum(p[0] for p in elevation_points)
                sum_e = sum(p[1] for p in elevation_points)
                sum_ye = sum(p[0] * p[1] for p in elevation_points)
                sum_e2 = sum(p[1] ** 2 for p in elevation_points)
                denom = n * sum_e2 - sum_e ** 2
                
                if abs(denom) > 0.001:
                    a = (n * sum_ye - sum_y * sum_e) / denom
                    b = (sum_y - a * sum_e) / n
                    ruler_params.append({'ruler': ruler, 'a': a, 'b': b, 'elevation_points': elevation_points})
        
        if not ruler_params:
            return None
        
        # 选择最佳标尺：优先选择b值与l1_y接近的标尺（如果提供了l1_y）
        best_ruler_param = None
        if l1_y is not None:
            # 优先选择b值最接近l1_y的标尺（因为L1交点通常在高程0处）
            best_ruler_param = min(ruler_params, key=lambda rp: abs(rp['b'] - l1_y))
        else:
            # 没有l1_y，使用Y重叠比例选择
            best_overlap = -1
            for rp in ruler_params:
                ruler = rp['ruler']
                overlap = max(0, min(sect_y_max, ruler['y_max']) - max(sect_y_min, ruler['y_min']))
                overlap_ratio = overlap / (ruler['y_max'] - ruler['y_min']) if ruler['y_max'] > ruler['y_min'] else 0
                if overlap_ratio > best_overlap:
                    best_overlap = overlap_ratio
                    best_ruler_param = rp
            if not best_ruler_param:
                best_ruler_param = ruler_params[0]
        
        a = best_ruler_param['a']
        b = best_ruler_param['b']
        
        # 返回转换函数
        return (lambda elev: a * elev + b, lambda y: (y - b) / a)


# ==================== 断面提取（参考engine_cad_working_v3.py第1726-1743行） ====================

def get_l1_basepoints(msp):
    """获取L1脊梁线交点（断面基点）
    
    参考engine_cad_working_v3.py的autopaste逻辑：
    - L1图层有水平线和垂直线
    - 水平线和垂直线的交点就是断面基点
    - 每个交点对应一个断面
    
    Returns:
        [{'x', 'y'}, ...] 按Y从大到小排序
    """
    horizontal_lines = []
    vertical_lines = []
    
    for e in msp.query('*[layer=="L1"]'):
        try:
            if e.dxftype() == 'LINE':
                x1, y1 = e.dxf.start.x, e.dxf.start.y
                x2, y2 = e.dxf.end.x, e.dxf.end.y
                
                width = abs(x2 - x1)
                height = abs(y2 - y1)
                
                if width > height * 3:  # 水平线
                    horizontal_lines.append({
                        'y': (y1 + y2) / 2,
                        'x_min': min(x1, x2),
                        'x_max': max(x1, x2)
                    })
                elif height > width * 3:  # 垂直线
                    vertical_lines.append({
                        'x': (x1 + x2) / 2,
                        'y_center': (y1 + y2) / 2,
                        'y_min': min(y1, y2),
                        'y_max': max(y1, y2)
                    })
        except: pass
    
    print(f"  L1水平线数量: {len(horizontal_lines)}")
    print(f"  L1垂直线数量: {len(vertical_lines)}")
    
    # 排序
    horizontal_lines.sort(key=lambda l: l['y'], reverse=True)
    vertical_lines.sort(key=lambda l: l['x'])
    
    # 计算交点（一对一匹配）
    basepoints = []
    used_h_indices = set()
    
    for v_line in vertical_lines:
        v_x = v_line['x']
        v_y_center = v_line['y_center']
        
        best_h_idx = -1
        best_y_diff = float('inf')
        
        for h_idx, h_line in enumerate(horizontal_lines):
            if h_idx in used_h_indices:
                continue
            
            y_diff = abs(h_line['y'] - v_y_center)
            if y_diff < best_y_diff:
                best_y_diff = y_diff
                best_h_idx = h_idx
        
        if best_h_idx >= 0 and best_y_diff < 50:
            used_h_indices.add(best_h_idx)
            h_line = horizontal_lines[best_h_idx]
            basepoints.append({
                'x': v_x,
                'y': h_line['y'],
                'v_y_min': v_line['y_min'],
                'v_y_max': v_line['y_max']
            })
    
    print(f"  L1交点数量（断面数）: {len(basepoints)}")
    return basepoints


def get_section_list(msp, layer='DMX'):
    """获取断面线列表
    
    每个DMX多段线代表一个独立断面
    
    Returns:
        [{'x_min', 'x_max', 'y_min', 'y_max', 'y_center', 'pts', 'line', 'x_center'}, ...]
    """
    entity_list = []
    for e in msp.query(f'LWPOLYLINE[layer=="{layer}"]'):
        try:
            pts = [p[:2] for p in e.get_points()]
            if pts:
                x_min = min(p[0] for p in pts)
                x_max = max(p[0] for p in pts)
                y_min = min(p[1] for p in pts)
                y_max = max(p[1] for p in pts)
                entity_list.append({
                    'x_min': x_min, 'x_max': x_max,
                    'y_min': y_min, 'y_max': y_max,
                    'pts': pts,
                    'line': LineString(pts),
                    'y_center': (y_min + y_max) / 2,
                    'x_center': (x_min + x_max) / 2
                })
        except: pass
    
    return entity_list


def get_polylines_as_lines(msp, layer):
    """将多段线转换为LineString列表"""
    lines = []
    for e in msp.query(f'LWPOLYLINE[layer=="{layer}"]'):
        try:
            pts = [p[:2] for p in e.get_points()]
            if len(pts) >= 2:
                lines.append(LineString(pts))
        except: pass
    return lines


# ==================== 主提取函数 ====================

def load_spine_match(spine_match_path: str) -> Dict:
    """加载脊梁点匹配结果
    
    Returns:
        {station_value: {'spine_x', 'spine_y', 'l1_x', 'l1_y', 'tangent_angle'}, ...}
    """
    print(f"\n加载脊梁点匹配结果: {spine_match_path}")
    try:
        with open(spine_match_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception as e:
        print(f"  [ERROR] 加载失败: {e}")
        return {}
    
    matches = data.get('matches', [])
    if not matches:
        matches = [v for k, v in data.items() if isinstance(v, dict) and 'station_value' in v]
    
    spine_data = {}
    for m in matches:
        station_value = m.get('station_value', 0)
        spine_data[station_value] = {
            'spine_x': m.get('spine_x', 0),
            'spine_y': m.get('spine_y', 0),
            'l1_x': m.get('l1_x', 0),
            'l1_y': m.get('l1_y', 0),
            'tangent_angle': m.get('tangent_angle', 0)
        }
    
    print(f"  加载 {len(spine_data)} 个脊梁点")
    return spine_data


def extract_xyz_from_dxf(dxf_path: str, spine_match_path: str = None) -> Dict:
    """从DXF文件提取开挖线和超挖线的XYZ坐标
    
    Args:
        dxf_path: DXF文件路径
        spine_match_path: 脊梁点匹配结果JSON文件路径
    
    Returns:
        {
            'sections': [
                {
                    'section_index': int,
                    'station': str,
                    'station_value': int,
                    'spine_x': float,  # 真实世界坐标X
                    'spine_y': float,  # 真实世界坐标Y
                    'l1_x': float,     # CAD坐标X
                    'l1_y': float,     # CAD坐标Y
                    'scale_factor': (a, b),
                    'kaiwa_xyz': [(x_rel, y_cad, z), ...],
                    'chaowa_xyz': [(x_rel, y_cad, z), ...],
                },
                ...
            ]
        }
    """
    print(f"\n加载DXF文件: {dxf_path}")
    doc = ezdxf.readfile(dxf_path)
    msp = doc.modelspace()
    
    # 加载脊梁点匹配数据
    spine_data = {}
    if spine_match_path:
        spine_data = load_spine_match(spine_match_path)
    
    # 1. 获取L1断面基点（每个交点对应一个断面）
    print("\n提取L1断面基点...")
    l1_basepoints = get_l1_basepoints(msp)
    print(f"  找到 {len(l1_basepoints)} 个断面基点")
    
    # 2. 获取DMX断面线
    print("\n提取DMX断面线...")
    dmx_sections = get_section_list(msp, 'DMX')
    print(f"  找到 {len(dmx_sections)} 个DMX断面")
    
    # 3. 获取开挖线和超挖线
    print("\n提取开挖线和超挖线...")
    kaiwa_lines = get_polylines_as_lines(msp, '开挖线')
    chaowa_lines = get_polylines_as_lines(msp, '超挖线')
    print(f"  开挖线数量: {len(kaiwa_lines)}")
    print(f"  超挖线数量: {len(chaowa_lines)}")
    
    # 3. 获取桩号标注
    print("\n提取桩号...")
    station_texts = []
    import re
    station_pattern = re.compile(r'K(\d+)\+(\d+)', re.IGNORECASE)
    for e in msp.query('TEXT'):
        try:
            text = e.dxf.text
            m = station_pattern.search(text)
            if m:
                station_value = int(m.group(1)) * 1000 + int(m.group(2))
                station_texts.append({
                    'text': text,
                    'station_value': station_value,
                    'x': e.dxf.insert.x,
                    'y': e.dxf.insert.y
                })
        except: pass
    print(f"  桩号数量: {len(station_texts)}")
    
    # 按Y排序桩号
    station_texts.sort(key=lambda s: s['y'], reverse=True)
    used_stations = set()
    
    # 4. 处理每个L1断面基点
    print("\n构建XYZ数据...")
    results = []
    
    for idx, bp in enumerate(l1_basepoints):
        # L1交点坐标（断面中心）
        l1_x = bp['x']
        l1_y = bp['y']
        v_y_min = bp['v_y_min']
        v_y_max = bp['v_y_max']
        
        # 查找对应的DMX断面（用于确定X范围）
        best_dmx = None
        best_dist = float('inf')
        for dmx in dmx_sections:
            # L1交点应该在DMX的Y范围内
            if dmx['y_min'] - 50 <= l1_y <= dmx['y_max'] + 50:
                dist = abs(dmx['x_center'] - l1_x)
                if dist < best_dist:
                    best_dist = dist
                    best_dmx = dmx
        
        if best_dmx:
            sect_x_min = best_dmx['x_min']
            sect_x_max = best_dmx['x_max']
            sect_y_min = best_dmx['y_min']
            sect_y_max = best_dmx['y_max']
            sect_x_center = best_dmx['x_center']
            sect_y_center = best_dmx['y_center']
        else:
            # 没有找到DMX，使用默认范围
            sect_x_min = l1_x - 100
            sect_x_max = l1_x + 100
            sect_y_min = v_y_min
            sect_y_max = v_y_max
            sect_x_center = l1_x
            sect_y_center = l1_y
        
        # 第一步：先用桩号标注获取station_value
        best_station = None
        best_dist = float('inf')
        for st in station_texts:
            if st['text'] in used_stations:
                continue
            dist = math.sqrt((st['x'] - l1_x)**2 + (st['y'] - l1_y)**2)
            if dist < best_dist:
                best_dist = dist
                best_station = st
        
        if best_station and best_dist < 500:
            station = best_station['text']
            station_value = best_station['station_value']
            used_stations.add(station)
        else:
            station = f"S{idx+1}"
            station_value = 999999 + idx
        
        # 第二步：用station_value直接匹配脊梁点
        spine_x = 0
        spine_y = 0
        spine_match = None
        if spine_data and station_value in spine_data:
            spine_info = spine_data[station_value]
            spine_x = spine_info['spine_x']
            spine_y = spine_info['spine_y']
            spine_match = True
        
        # 检测标尺（传入l1_y用于验证标尺b值）
        ruler_scale = RulerDetector.detect_scale(msp, doc, sect_x_min, sect_x_max, sect_y_center, sect_y_min, sect_y_max, l1_y)
        
        if ruler_scale:
            elev_to_y, y_to_elev = ruler_scale
            # 从转换函数提取参数a和b（用于记录）
            # Y = a * elev + b，所以 elev = (Y - b) / a
            y0 = elev_to_y(0)
            y1 = elev_to_y(1)
            a = y1 - y0  # a是每米高程对应的Y坐标变化量
            b = y0  # b是高程0对应的Y坐标
        else:
            # 没有检测到标尺，使用默认值
            a, b = 1.0, 0.0
            y_to_elev = lambda y: (y - b) / a
        
        # 创建边界框用于筛选开挖线/超挖线
        boundary_box = box(sect_x_min - 20, sect_y_min - 50, sect_x_max + 20, sect_y_max + 50)
        
        # 筛选开挖线
        local_kaiwa = [l for l in kaiwa_lines if boundary_box.intersects(l)]
        
        # 筛选超挖线
        local_chaowa = [l for l in chaowa_lines if boundary_box.intersects(l)]
        
        # 获取脊梁点切向角度（用于坐标转换）
        if spine_match and station_value in spine_data:
            tangent_angle = spine_data[station_value]['tangent_angle']
        else:
            tangent_angle = 0
        
        # 计算断面方向角度（垂直于脊梁线切向）
        cross_angle = tangent_angle + math.pi / 2
        cos_a = math.cos(cross_angle)
        sin_a = math.sin(cross_angle)
        
        # 构建XYZ数据（转换到三维大地坐标系）
        kaiwa_xyz = []
        chaowa_xyz = []
        
        # 处理开挖线 - 转换到三维大地坐标系
        for line in local_kaiwa:
            for pt in line.coords:
                x_cad = pt[0]
                y_cad = pt[1]
                dx = x_cad - l1_x  # 相对于L1交点的X偏移（断面方向距离）
                z = y_to_elev(y_cad)
                
                if spine_match:
                    # 转换到三维大地坐标系（参考geology_model_v17.py的transform_to_spine_aligned）
                    eng_x = spine_x + dx * cos_a
                    eng_y = spine_y + dx * sin_a
                else:
                    # 没有脊梁点匹配，使用CAD坐标
                    eng_x = x_cad
                    eng_y = y_cad
                
                kaiwa_xyz.append((eng_x, eng_y, z))
        
        # 处理超挖线 - 转换到三维大地坐标系
        for line in local_chaowa:
            for pt in line.coords:
                x_cad = pt[0]
                y_cad = pt[1]
                dx = x_cad - l1_x  # 相对于L1交点的X偏移
                z = y_to_elev(y_cad)
                
                if spine_match:
                    # 转换到三维大地坐标系
                    eng_x = spine_x + dx * cos_a
                    eng_y = spine_y + dx * sin_a
                else:
                    # 没有脊梁点匹配，使用CAD坐标
                    eng_x = x_cad
                    eng_y = y_cad
                
                chaowa_xyz.append((eng_x, eng_y, z))
        
        # 脊梁点高程（L1交点高程为0）
        spine_z = 0.0
        
        section_data = {
            'section_index': idx + 1,
            'station': station,
            'station_value': station_value,
            'spine_x': spine_x,
            'spine_y': spine_y,
            'spine_z': spine_z,
            'l1_x': l1_x,
            'l1_y': l1_y,
            'x_range': (sect_x_min, sect_x_max),
            'y_range': (sect_y_min, sect_y_max),
            'center_x': l1_x,
            'scale_factor': (a, b),
            'kaiwa_xyz': kaiwa_xyz,
            'chaowa_xyz': chaowa_xyz
        }
        results.append(section_data)
        
        print(f"\n  断面 {idx+1}: 桩号={station} (值={station_value})")
        if spine_match:
            print(f"    脊梁点匹配成功: spine_x={spine_x:.2f}, spine_y={spine_y:.2f}")
        print(f"    L1交点: ({l1_x:.2f}, {l1_y:.2f})")
        print(f"    开挖线点数: {len(kaiwa_xyz)}")
        print(f"    超挖线点数: {len(chaowa_xyz)}")
    
    # 按桩号值排序（从小到大）
    print("\n按桩号排序断面...")
    results.sort(key=lambda s: s['station_value'])
    
    # 排序后重新分配section_index
    for new_idx, section in enumerate(results):
        section['section_index'] = new_idx + 1
    
    print(f"  排序后桩号范围: {results[0]['station']} -> {results[-1]['station']}")
    
    return {'sections': results}


# ==================== 输出XYZ文件 ====================

def write_xyz_file(data: Dict, layer_type: str, output_path: str):
    """将XYZ数据写入文件（三维大地坐标系）- 纯数据格式，无表头，Z值乘-1
    
    注意：只保留水面以下的点（z < 0），删除水面以上的点（z > 0）
    """
    xyz_key = f'{layer_type}_xyz'
    
    with open(output_path, 'w', encoding='utf-8') as f:
        total_points = 0
        skipped_points = 0
        for section in data['sections']:
            points = section[xyz_key]
            for x, y, z in points:
                # 只保留水面以下的点（z < 0），删除水面以上的点（z > 0）
                if z < 0:
                    f.write(f"{x:.6f} {y:.6f} {-z:.6f}\n")
                    total_points += 1
                else:
                    skipped_points += 1
    
    print(f"\nXYZ文件已保存: {output_path}")
    print(f"  总点数: {total_points}")
    print(f"  已删除水面以上点数: {skipped_points}")


def write_center_line_file(data: Dict, output_path: str):
    """将中心线数据写入文件（使用脊梁点真实世界坐标+高程）"""
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write("# 中心线位置数据（脊梁点真实世界坐标+高程）\n")
        f.write("# 格式: 断面序号 桩号 spine_x(真实X) spine_y(真实Y) z(高程)\n\n")
        
        for section in data['sections']:
            # z高程：从L1交点的CAD Y坐标通过标尺转换得到
            a, b = section['scale_factor']
            z = (section['l1_y'] - b) / a  # 转换为高程
            f.write(f"{section['section_index']} {section['station']} ")
            f.write(f"{section['spine_x']:.6f} {section['spine_y']:.6f} ")
            f.write(f"{z:.6f}\n")
    
    print(f"\n中心线文件已保存: {output_path}")


# ==================== 主程序 ====================

if __name__ == "__main__":
    dxf_path = r'D:\断面算量平台\测试文件\内湾段分层图（全航道底图20260318）.dxf'
    spine_match_path = r'D:\断面算量平台\测试文件\脊梁点_L1匹配结果.json'
    
    # 输出路径
    output_dir = r'D:\断面算量平台\测试文件'
    kaiwa_xyz_path = f"{output_dir}\\开挖线_xyz.txt"
    chaowa_xyz_path = f"{output_dir}\\超挖线_xyz.txt"
    center_line_path = f"{output_dir}\\中心线位置.txt"
    json_path = f"{output_dir}\\断面XYZ数据.json"
    
    print("=" * 60)
    print("DXF XYZ坐标提取工具")
    print("=" * 60)
    
    # 提取数据（传入脊梁点匹配文件）
    result = extract_xyz_from_dxf(dxf_path, spine_match_path)
    
    # 输出XYZ文件
    write_xyz_file(result, 'kaiwa', kaiwa_xyz_path)
    write_xyz_file(result, 'chaowa', chaowa_xyz_path)
    write_center_line_file(result, center_line_path)
    
    # 输出JSON文件
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"\nJSON文件已保存: {json_path}")
    
    # 统计
    total_kaiwa = sum(len(s['kaiwa_xyz']) for s in result['sections'])
    total_chaowa = sum(len(s['chaowa_xyz']) for s in result['sections'])
    
    print("\n" + "=" * 60)
    print("提取完成！")
    print("=" * 60)
    print(f"总断面数: {len(result['sections'])}")
    print(f"总开挖线点数: {total_kaiwa}")
    print(f"总超挖线点数: {total_chaowa}")