"""
DXF断面数据提取 - 3D建模准备（坐标归一化版）
核心改进：将绝对坐标转换为以航道底中心为原点的相对坐标
"""
import ezdxf
from collections import defaultdict
import re
import sys
import io
import json
import numpy as np

# 设置控制台编码
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

def extract_station_number(text):
    """从文本中提取桩号"""
    patterns = [
        r'K(\d+)\+(\d+\.?\d*)',
        r'(\d+)\+(\d+\.?\d*)',
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            km = float(match.group(1))
            m = float(match.group(2))
            return km * 1000 + m
    return None

def get_hatch_polygon(hatch):
    """提取Hatch的边界多边形"""
    polygons = []
    try:
        for path in hatch.paths:
            if hasattr(path, 'vertices'):
                vertices = [(v[0], v[1]) for v in path.vertices]
                if len(vertices) >= 3:
                    polygons.append(vertices)
    except:
        pass
    return polygons

def get_bbox(vertices):
    """计算顶点列表的边界框"""
    if not vertices:
        return None
    xs = [v[0] for v in vertices]
    ys = [v[1] for v in vertices]
    return (min(xs), min(ys), max(xs), max(ys))

def find_channel_bottom_center(section_line_vertices, tolerance=0.5):
    """
    找到航道底中心参考点
    
    逻辑：
    1. 找到断面线中Y值最小（海拔最低）的顶点
    2. 在最低点附近找水平段（Y变化小于容差）
    3. 计算水平段的中心点作为参考点
    
    返回：(x_base, y_base) 参考点坐标
    """
    if not section_line_vertices or len(section_line_vertices) < 2:
        return None, None
    
    vertices = np.array(section_line_vertices)
    
    # 方法1：找Y值最小的顶点区间（航道底）
    y_min = vertices[:, 1].min()
    
    # 找所有接近最低Y值的点（容差范围内）
    bottom_mask = np.abs(vertices[:, 1] - y_min) < tolerance
    bottom_points = vertices[bottom_mask]
    
    if len(bottom_points) >= 2:
        # 找到连续的底部水平段
        bottom_indices = np.where(bottom_mask)[0]
        
        # 找最长的连续水平段
        if len(bottom_indices) >= 2:
            # 计算该段的X中心
            x_center = bottom_points[:, 0].mean()
            y_center = y_min
            return x_center, y_center
    
    # 方法2：如果没有明显的水平段，使用最低Y值点的X坐标
    min_y_idx = np.argmin(vertices[:, 1])
    x_base = vertices[min_y_idx, 0]
    y_base = vertices[min_y_idx, 1]
    
    return x_base, y_base

def find_channel_bottom_center_v2(section_line_vertices):
    """
    改进版：找到航道底线（倒梯形底部）的中心点
    
    航道断面特征：
    - 倒梯形结构：两侧斜坡 + 底部水平段
    - 航道底是最低的水平段
    
    算法：
    1. 找最低Y值
    2. 找所有最低Y附近的连续顶点（形成水平段）
    3. 取水平段的中点
    """
    if not section_line_vertices or len(section_line_vertices) < 2:
        return None, None
    
    vertices = list(section_line_vertices)
    
    # 找Y最小值
    y_values = [v[1] for v in vertices]
    y_min = min(y_values)
    
    # 找所有Y接近最小的点索引
    tolerance = 0.3  # Y容差
    bottom_indices = [i for i, v in enumerate(vertices) if abs(v[1] - y_min) < tolerance]
    
    if not bottom_indices:
        # 退回到最低点
        min_idx = y_values.index(y_min)
        return vertices[min_idx][0], y_min
    
    # 检查是否形成连续的水平段
    bottom_points = [vertices[i] for i in bottom_indices]
    
    # 计算X的范围
    x_values = [p[0] for p in bottom_points]
    x_min = min(x_values)
    x_max = max(x_values)
    x_center = (x_min + x_max) / 2
    
    return x_center, y_min

def normalize_polygon(polygon, x_base, y_base):
    """
    将多边形坐标转换为相对坐标
    
    x_rel = x - x_base
    y_rel = y - y_base  (注意：断面图Y向上，3D中Z向下)
    """
    if polygon is None:
        return None
    
    normalized = []
    for x, y in polygon:
        x_rel = x - x_base
        y_rel = y - y_base
        normalized.append((x_rel, y_rel))
    
    return normalized

def analyze_dxf_for_3d(filepath):
    """分析DXF并提取3D建模所需数据（带坐标归一化）"""
    print(f"正在分析文件: {filepath}")
    print("=" * 80)
    
    doc = ezdxf.readfile(filepath)
    msp = doc.modelspace()
    
    # 1. 提取最终断面线 - 作为断面的主要定位依据
    print("\n【1. 提取最终断面线】")
    final_section_lines = list(msp.query('LWPOLYLINE[layer=="AA_最终断面线"]'))
    print(f"找到 {len(final_section_lines)} 条最终断面线")
    
    # 获取每条断面线的详细信息
    section_frames = []
    for i, pline in enumerate(final_section_lines):
        try:
            vertices = list(pline.vertices())
            if vertices:
                bbox = get_bbox(vertices)
                
                # 找航道底中心参考点
                x_base, y_base = find_channel_bottom_center_v2(vertices)
                
                section_frames.append({
                    'index': i,
                    'min_x': bbox[0],
                    'min_y': bbox[1],
                    'max_x': bbox[2],
                    'max_y': bbox[3],
                    'center_x': (bbox[0] + bbox[2]) / 2,
                    'center_y': (bbox[1] + bbox[3]) / 2,
                    'vertices': vertices,
                    'x_base': x_base,  # 参考点X
                    'y_base': y_base   # 参考点Y（航道底高程）
                })
        except Exception as e:
            print(f"处理断面线 {i} 时出错: {e}")
    
    print(f"解析到 {len(section_frames)} 个断面边界")
    
    # 显示参考点信息
    print("\n参考点信息（前5个）:")
    for frame in section_frames[:5]:
        print(f"  断面 {frame['index']}: 参考点 ({frame['x_base']:.2f}, {frame['y_base']:.2f})")
    
    # 2. 通过Hatch的X坐标范围补充断面分组
    print("\n【2. 通过Hatch补充断面分组】")
    hatches = list(msp.query('HATCH'))
    
    # 按X坐标分组Hatch
    hatch_groups = defaultdict(list)
    for hatch in hatches:
        layer = hatch.dxf.layer
        if 'AA_' in layer or '填充算量' in layer:
            continue
        
        polygons = get_hatch_polygon(hatch)
        if polygons:
            all_vertices = []
            for poly in polygons:
                all_vertices.extend(poly)
            bbox = get_bbox(all_vertices)
            if bbox:
                hatch_groups[(round(bbox[0] / 200) * 200, round(bbox[2] / 200) * 200)].append({
                    'layer': layer,
                    'bbox': bbox,
                    'polygon': polygons[0],
                    'center_x': (bbox[0] + bbox[2]) / 2,
                    'center_y': (bbox[1] + bbox[3]) / 2
                })
    
    print(f"Hatch分组数: {len(hatch_groups)}")
    
    # 3. 提取桩号文字
    print("\n【3. 提取桩号文字】")
    texts = list(msp.query('TEXT'))
    stations = []
    
    for text in texts:
        content = text.text if hasattr(text, 'text') else str(text.dxf.text)
        station_m = extract_station_number(content)
        if station_m is not None:
            x = text.dxf.insert.x
            y = text.dxf.insert.y
            stations.append({
                'station_m': station_m,
                'text': content,
                'x': x,
                'y': y
            })
    
    # 按桩号数值排序
    stations.sort(key=lambda s: s['station_m'])
    print(f"找到 {len(stations)} 个桩号文字")
    
    if stations:
        print(f"桩号范围: K{int(stations[0]['station_m']//1000)}+{stations[0]['station_m']%1000:.0f} ~ K{int(stations[-1]['station_m']//1000)}+{stations[-1]['station_m']%1000:.0f}")
    
    # 4. 建立断面数据结构
    print("\n【4. 关联桩号与断面】")
    
    # 建立断面数据结构
    section_data = {}  # {桩号米数: {图层: [多边形]}}
    section_lines = {}  # {桩号米数: 相对坐标顶点列表}
    reference_points = {}  # {桩号米数: (x_base, y_base)} 参考点记录
    station_frame_map = {}
    
    # 对于每个桩号，找到对应X位置的断面数据
    for station in stations:
        station_m = station['station_m']
        station_x = station['x']
        
        # 找同X位置的断面线
        matched_frame = None
        for frame in section_frames:
            if abs(frame['center_x'] - station_x) < 100:  # 100像素容差
                matched_frame = frame
                break
        
        if matched_frame is None:
            continue
        
        station_frame_map[station_m] = matched_frame
        x_base = matched_frame['x_base']
        y_base = matched_frame['y_base']
        
        # 记录参考点
        reference_points[station_m] = (x_base, y_base)
        
        # 归一化断面线坐标
        if matched_frame['vertices']:
            normalized_line = normalize_polygon(
                [(v[0], v[1]) for v in matched_frame['vertices']], 
                x_base, y_base
            )
            section_lines[station_m] = normalized_line
        
        # 找同X位置的Hatch数据并归一化
        for (min_x, max_x), hatch_list in hatch_groups.items():
            for hatch_info in hatch_list:
                # 检查Hatch是否在断面框的X范围内
                if (hatch_info['bbox'][0] >= matched_frame['min_x'] - 50 and 
                    hatch_info['bbox'][2] <= matched_frame['max_x'] + 50):
                    
                    layer = hatch_info['layer']
                    
                    if station_m not in section_data:
                        section_data[station_m] = {}
                    
                    # 归一化Hatch坐标
                    normalized_polygon = normalize_polygon(hatch_info['polygon'], x_base, y_base)
                    
                    if layer not in section_data[station_m]:
                        section_data[station_m][layer] = []
                    
                    section_data[station_m][layer].append({
                        'polygon': normalized_polygon,
                        'original_bbox': hatch_info['bbox']
                    })
    
    print(f"成功关联 {len(section_data)} 个桩号与Hatch数据")
    print(f"成功关联 {len(section_lines)} 个桩号与断面线")
    
    # 5. 验证归一化效果
    print("\n【5. 归一化验证】")
    if section_lines:
        sample_stations = list(section_lines.keys())[:3]
        for station_m in sample_stations:
            line = section_lines[station_m]
            if line:
                xs = [p[0] for p in line]
                ys = [p[1] for p in line]
                print(f"  K{int(station_m//1000)}+{station_m%1000:.0f}: X范围 [{min(xs):.2f}, {max(xs):.2f}], Y范围 [{min(ys):.2f}, {max(ys):.2f}]")
                print(f"    参考点: ({reference_points[station_m][0]:.2f}, {reference_points[station_m][1]:.2f})")
    
    # 6. 汇总统计
    print("\n【6. 数据汇总】")
    print(f"总桩号数: {len(station_frame_map)}")
    print(f"有Hatch数据的断面数: {len(section_data)}")
    print(f"有断面线的断面数: {len(section_lines)}")
    
    # 统计各图层的出现频率
    layer_count = defaultdict(int)
    for station_m, layers in section_data.items():
        for layer in layers:
            layer_count[layer] += 1
    
    print(f"\n图层出现频率（按频率排序）:")
    for layer, count in sorted(layer_count.items(), key=lambda x: -x[1])[:15]:
        print(f"  {layer}: {count} 个断面")
    
    return {
        'stations': stations,
        'frames': section_frames,
        'station_frame_map': {k: v for k, v in station_frame_map.items()},
        'section_data': section_data,
        'section_lines': section_lines,
        'reference_points': reference_points,
        'layer_types': list(set(l.replace('设计', '').replace('超挖', '') for l in layer_count.keys()))
    }

def export_for_3d(data, output_file):
    """导出3D建模数据为JSON格式（带归一化坐标）"""
    export_data = {
        'coordinate_system': 'relative',  # 标记为相对坐标
        'origin_description': '航道底中心点',
        'stations': [],
        'sections': {},
        'reference_points': {}  # 记录每个断面的参考点（用于调试）
    }
    
    # 桩号列表（按里程排序）
    for station in data['stations']:
        export_data['stations'].append({
            'station_m': station['station_m'],
            'station_text': station['text']
        })
    
    # 每个断面的数据（已归一化）
    for station_m, layers in data['section_data'].items():
        station_str = f"K{int(station_m//1000)}+{station_m%1000:.0f}"
        export_data['sections'][station_str] = {
            'station_m': station_m,
            'layers': {},
            'section_line': data['section_lines'].get(station_m, [])
        }
        
        for layer, polys in layers.items():
            export_data['sections'][station_str]['layers'][layer] = [
                poly['polygon'] for poly in polys
            ]
        
        # 记录参考点
        if station_m in data.get('reference_points', {}):
            export_data['reference_points'][station_str] = data['reference_points'][station_m]
    
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(export_data, f, ensure_ascii=False, indent=2)
    
    print(f"\n数据已导出到: {output_file}")
    
    # 打印验证信息
    print("\n归一化验证:")
    sections = export_data['sections']
    if sections:
        # 检查所有断面的X范围
        x_mins = []
        x_maxs = []
        for station_str, sec in sections.items():
            line = sec.get('section_line', [])
            if line:
                xs = [p[0] for p in line]
                x_mins.append(min(xs))
                x_maxs.append(max(xs))
        
        if x_mins:
            print(f"  所有断面X范围: [{min(x_mins):.2f}, {max(x_maxs):.2f}]")
            print(f"  归一化后，航道底中心应在 X=0 附近")

if __name__ == '__main__':
    filepath = r"D:\tunnel_build\测试文件\内湾段部分_RESULT_20260316_154309.dxf"
    result = analyze_dxf_for_3d(filepath)
    
    # 导出数据
    output_file = r"D:\tunnel_build\测试文件\断面3D数据_归一化.json"
    export_for_3d(result, output_file)
    
    print("\n" + "=" * 80)
    print("【3D建模数据结构说明】")
    print("=" * 80)
    print("""
导出的数据结构（坐标已归一化）:
{
  "coordinate_system": "relative",
  "origin_description": "航道底中心点",
  "stations": [...],
  "sections": {
    "K68+725": {
      "station_m": 68725,
      "layers": {
        "1级淤泥设计": [[(x_rel, y_rel), ...]],  // 相对坐标
        ...
      },
      "section_line": [(x_rel, y_rel), ...]  // 相对坐标
    },
    ...
  },
  "reference_points": {
    "K68+725": [x_base, y_base],  // 原始参考点坐标（用于调试）
    ...
  }
}

3D建模坐标映射:
- 3D_X = x_rel（断面内的横向相对位置，航道中心为0）
- 3D_Y = station_m（里程轴）
- 3D_Z = -y_rel（高程，断面Y向上为正，3D中向下为正）

归一化效果验证:
- 俯视图：所有断面对齐，航道笔直
- 侧视图：航道底连成平滑坡度线
""")