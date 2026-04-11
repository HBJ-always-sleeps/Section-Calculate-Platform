# -*- coding: utf-8 -*-
"""
缩放比例分析器 - 探索最佳参考图层用于自适应比例检测

目的：
1. 分析L1图层和其他图层的特征
2. 找出最能反映断面实际范围的参考对象
3. 对比原比例和0.6比例文件的检测结果
4. 为engine_cad提供更精确的缩放比例检测方法

作者: @黄秉俊
日期: 2026-03-28
"""

import ezdxf
import os
import math
import re
from collections import defaultdict
from shapely.geometry import box, Polygon, LineString

class ScaleAnalyzer:
    """缩放比例分析器"""
    
    STATION_PATTERN = re.compile(r'(\d+\+\d+)')
    
    def __init__(self, dxf_path):
        self.dxf_path = dxf_path
        self.doc = ezdxf.readfile(dxf_path)
        self.msp = self.doc.modelspace()
        self.layers = {l.dxf.name for l in self.doc.layers}
        
    def analyze_all_layers(self):
        """分析所有图层，找出可用于比例检测的参考图层"""
        print("\n=== 分析所有图层 ===")
        print(f"文件: {os.path.basename(self.dxf_path)}")
        print(f"图层总数: {len(self.layers)}")
        
        # 按类型分类图层
        layer_stats = {}
        
        for layer_name in sorted(self.layers):
            stats = self._analyze_layer(layer_name)
            if stats['entity_count'] > 0:
                layer_stats[layer_name] = stats
        
        # 输出有实体的图层
        print("\n有实体的图层：")
        for layer_name, stats in sorted(layer_stats.items(), key=lambda x: -x[1]['entity_count']):
            if stats['entity_count'] > 5:  # 只显示实体数>5的图层
                print(f"  {layer_name}: {stats['entity_count']}个实体, "
                      f"类型: {stats['entity_types']}, "
                      f"X范围: [{stats['x_min']:.1f}, {stats['x_max']:.1f}], "
                      f"Y范围: [{stats['y_min']:.1f}, {stats['y_max']:.1f}]")
        
        return layer_stats
    
    def _analyze_layer(self, layer_name):
        """分析单个图层"""
        stats = {
            'entity_count': 0,
            'entity_types': set(),
            'x_min': float('inf'),
            'x_max': float('-inf'),
            'y_min': float('inf'),
            'y_max': float('-inf'),
            'avg_width': 0,
            'avg_height': 0,
            'entities': []
        }
        
        widths = []
        heights = []
        
        for e in self.msp.query(f'*[layer=="{layer_name}"]'):
            try:
                stats['entity_count'] += 1
                stats['entity_types'].add(e.dxftype())
                
                if e.dxftype() in ('LWPOLYLINE', 'POLYLINE'):
                    pts = [(p[0], p[1]) for p in e.get_points()]
                    if pts:
                        x_min = min(p[0] for p in pts)
                        x_max = max(p[0] for p in pts)
                        y_min = min(p[1] for p in pts)
                        y_max = max(p[1] for p in pts)
                        
                        stats['x_min'] = min(stats['x_min'], x_min)
                        stats['x_max'] = max(stats['x_max'], x_max)
                        stats['y_min'] = min(stats['y_min'], y_min)
                        stats['y_max'] = max(stats['y_max'], y_max)
                        
                        widths.append(x_max - x_min)
                        heights.append(y_max - y_min)
                        
                        stats['entities'].append({
                            'type': e.dxftype(),
                            'x_min': x_min, 'x_max': x_max,
                            'y_min': y_min, 'y_max': y_max,
                            'width': x_max - x_min,
                            'height': y_max - y_min,
                            'y_center': (y_min + y_max) / 2
                        })
                        
                elif e.dxftype() == 'LINE':
                    x_min = min(e.dxf.start.x, e.dxf.end.x)
                    x_max = max(e.dxf.start.x, e.dxf.end.x)
                    y_min = min(e.dxf.start.y, e.dxf.end.y)
                    y_max = max(e.dxf.start.y, e.dxf.end.y)
                    
                    stats['x_min'] = min(stats['x_min'], x_min)
                    stats['x_max'] = max(stats['x_max'], x_max)
                    stats['y_min'] = min(stats['y_min'], y_min)
                    stats['y_max'] = max(stats['y_max'], y_max)
                    
                    widths.append(x_max - x_min)
                    heights.append(y_max - y_min)
                    
                    stats['entities'].append({
                        'type': 'LINE',
                        'x_min': x_min, 'x_max': x_max,
                        'y_min': y_min, 'y_max': y_max,
                        'width': x_max - x_min,
                        'height': y_max - y_min,
                        'y_center': (y_min + y_max) / 2
                    })
                    
                elif e.dxftype() in ('TEXT', 'MTEXT'):
                    # 文本实体
                    try:
                        if e.dxftype() == 'TEXT':
                            insert_x = e.dxf.insert.x
                            insert_y = e.dxf.insert.y
                        else:
                            insert_x = e.dxf.insert.x
                            insert_y = e.dxf.insert.y
                        
                        stats['x_min'] = min(stats['x_min'], insert_x)
                        stats['x_max'] = max(stats['x_max'], insert_x)
                        stats['y_min'] = min(stats['y_min'], insert_y)
                        stats['y_max'] = max(stats['y_max'], insert_y)
                        
                        stats['entities'].append({
                            'type': e.dxftype(),
                            'x': insert_x, 'y': insert_y
                        })
                    except: pass
                        
            except: pass
        
        if widths:
            stats['avg_width'] = sum(widths) / len(widths)
        if heights:
            stats['avg_height'] = sum(heights) / len(heights)
        
        return stats
    
    def analyze_L1_frames(self, reference_gap=None):
        """分析L1图层（断面基准线）的特征
        
        L1图层是航道中心线和航道顶边组成的十字基准
        每个桩号对应一组基准线（横跨整个图纸的水平线）
        
        **关键：航道中心线是BIM三维放样的脊梁线**
        
        Args:
            reference_gap: 参考聚类阈值（如DMX间距），用于正确分组基准线
        
        Returns:
            dict: 包含脊梁线提取结果
        """
        print("\n=== 分析L1图层（断面基准线 - BIM脊梁线） ===")
        
        l1_stats = self._analyze_layer('L1')
        
        if l1_stats['entity_count'] == 0:
            print("  L1图层无实体")
            return None
        
        print(f"  实体数: {l1_stats['entity_count']}")
        print(f"  实体类型: {l1_stats['entity_types']}")
        
        # 分离LINE和TEXT实体
        line_entities = [e for e in l1_stats['entities'] if e.get('type') == 'LINE']
        text_entities = [e for e in l1_stats['entities'] if e.get('type') in ('TEXT', 'MTEXT')]
        
        print(f"  LINE实体数: {len(line_entities)}")
        print(f"  TEXT实体数: {len(text_entities)}")
        
        if not line_entities:
            print("  L1图层无LINE实体，跳过分析")
            return None
        
        # ===== 深度分析：提取航道中心线脊梁线 =====
        print("\n  === 提取航道中心线脊梁线 ===")
        
        # 分析LINE实体的类型分布
        horizontal_lines = []  # 水平线（宽度远大于高度）
        vertical_lines = []    # 垂直线（高度远大于宽度）
        other_lines = []       # 其他线
        
        for line in line_entities:
            width = line.get('width', 0)
            height = line.get('height', 0)
            
            # 判断线段类型：水平线宽度远大于高度
            if width > height * 3:
                horizontal_lines.append(line)
            elif height > width * 3:
                vertical_lines.append(line)
            else:
                other_lines.append(line)
        
        print(f"  水平LINE数: {len(horizontal_lines)}")
        print(f"  垂直LINE数: {len(vertical_lines)}")
        print(f"  其他LINE数: {len(other_lines)}")
        
        # ===== 关键：用标尺图层定位断面位置，提取每个断面的中心线和顶边 =====
        # L1是245组，每组包含：
        # - 最长的垂直LINE = 航道中心线（脊梁线）
        # - 水平LINE = 顶边
        
        # 先获取标尺图层的Y位置作为断面定位参考
        ruler_y_positions = self._get_ruler_positions()
        
        if ruler_y_positions:
            print(f"  标尺位置数: {len(ruler_y_positions)}")
        
        spine_lines = []  # 存储每个断面的脊梁线（垂直线+水平线）
        
        if vertical_lines:
            # 按Y坐标排序垂直线（每条对应一个断面）
            sorted_v = sorted(vertical_lines, key=lambda e: e.get('y_center', 0), reverse=True)
            
            print(f"  垂直线数（中心线）: {len(sorted_v)}")
            
            # 按Y位置排序水平线（用于最近邻匹配）
            sorted_h = sorted(horizontal_lines, key=lambda e: e.get('y_center', 0), reverse=True)
            
            print(f"  水平线数（用于匹配）: {len(sorted_h)}")
            
            # 使用最近邻方法一对一匹配垂直线和水平线
            # 每条垂直线找Y位置最接近的水平线
            used_h_indices = set()  # 记录已使用的水平线
            
            for idx, v_line in enumerate(sorted_v):
                v_y_center = v_line.get('y_center', 0)
                v_x_center = (v_line.get('x_min', 0) + v_line.get('x_max', 0)) / 2
                v_y_max = v_line.get('y_max', 0)  # 垂直线顶部
                v_y_min = v_line.get('y_min', 0)  # 垂直线底部
                
                # 找Y位置最接近的未使用水平线
                best_h_line = None
                best_y_diff = float('inf')
                best_h_idx = -1
                
                for h_idx, h_line in enumerate(sorted_h):
                    if h_idx in used_h_indices:
                        continue  # 跳过已使用的
                    
                    h_y = h_line.get('y_center', 0)
                    y_diff = abs(h_y - v_y_center)
                    
                    if y_diff < best_y_diff:
                        best_y_diff = y_diff
                        best_h_line = h_line
                        best_h_idx = h_idx
                
                # 如果找到最近邻，标记为已使用
                top_line = None
                if best_h_line and best_y_diff < 50:  # Y差距阈值50
                    top_line = best_h_line
                    used_h_indices.add(best_h_idx)
                
                spine_lines.append({
                    'section_index': idx + 1,
                    'y_center': v_y_center,
                    'y_min': v_line.get('y_min', 0),
                    'y_max': v_line.get('y_max', 0),
                    'x_center': v_x_center,  # 垂直线X位置（航道中心）
                    'center_height': v_line.get('height', 0),  # 垂直线高度（航道深度）
                    # 水平线信息（顶边）
                    'top_y': top_line.get('y_center', 0) if top_line else None,
                    'top_x_min': top_line.get('x_min', 0) if top_line else None,
                    'top_x_max': top_line.get('x_max', 0) if top_line else None,
                    'top_width': top_line.get('width', 0) if top_line else None,
                    'has_top_line': top_line is not None
                })
            
            print(f"  提取脊梁线数: {len(spine_lines)}")
            
            # 统计匹配情况
            matched_count = sum(1 for s in spine_lines if s['has_top_line'])
            print(f"  有对应顶边的脊梁线数: {matched_count}")
        
        # 输出脊梁线信息
        if spine_lines:
            # 按Y排序
            spine_lines_sorted = sorted(spine_lines, key=lambda s: s['y_center'], reverse=True)
            
            # 统计垂直线高度（航道深度）
            spine_heights = [s['center_height'] for s in spine_lines_sorted]
            avg_spine_height = sum(spine_heights) / len(spine_heights) if spine_heights else 0
            
            # 统计顶边宽度
            top_widths = [s['top_width'] for s in spine_lines_sorted if s['has_top_line']]
            avg_top_width = sum(top_widths) / len(top_widths) if top_widths else 0
            
            # 计算脊梁线Y间距
            spine_y_centers = [s['y_center'] for s in spine_lines_sorted]
            spine_gaps = []
            for i in range(len(spine_y_centers) - 1):
                spine_gaps.append(abs(spine_y_centers[i] - spine_y_centers[i+1]))
            avg_spine_gap = sum(spine_gaps) / len(spine_gaps) if spine_gaps else 0
            
            print(f"  脊梁线数量: {len(spine_lines)}")
            print(f"  垂直线平均高度（航道深度）: {avg_spine_height:.2f}")
            print(f"  有顶边的脊梁线数: {len(top_widths)}")
            print(f"  顶边平均宽度: {avg_top_width:.2f}")
            print(f"  脊梁线Y间距: {avg_spine_gap:.2f}")
            
            # 输出脊梁线坐标列表（用于BIM三维放样）
            print(f"\n  === 脊梁线坐标列表（BIM三维放样用） ===")
            print(f"  格式: [序号, Y中心, X中心, 垂直高度, 顶边宽度]")
            for i, spine in enumerate(spine_lines_sorted[:10]):  # 只显示前10个
                top_w = spine['top_width'] if spine['has_top_line'] else '无'
                print(f"    [{spine['section_index']}] Y={spine['y_center']:.2f}, X={spine['x_center']:.2f}, H={spine['center_height']:.2f}, TopW={top_w}")
            if len(spine_lines_sorted) > 10:
                print(f"    ... 共{len(spine_lines_sorted)}条脊梁线")
            
            spine_data = {
                'spine_count': len(spine_lines),
                'avg_height': avg_spine_height,
                'avg_top_width': avg_top_width,
                'avg_gap': avg_spine_gap,
                'matched_count': len(top_widths),
                'spines': spine_lines_sorted
            }
        else:
            spine_data = None
            print("  未检测到脊梁线")
        
        # ===== 旧逻辑：按Y坐标聚类（保留） =====
        sorted_lines = sorted(line_entities, key=lambda e: e.get('y_center', 0), reverse=True)
        
        if reference_gap:
            cluster_threshold = reference_gap * 0.6
            print(f"\n  使用参考间距聚类: {cluster_threshold:.2f}")
        else:
            y_centers = [e.get('y_center', 0) for e in sorted_lines]
            if len(y_centers) >= 2:
                gaps = [abs(y_centers[i] - y_centers[i+1]) for i in range(len(y_centers)-1)]
                sorted_gaps = sorted(gaps)
                median_gap = sorted_gaps[len(sorted_gaps)//2]
                cluster_threshold = median_gap * 0.5
            else:
                cluster_threshold = 10
            print(f"\n  使用间距中位数聚类: {cluster_threshold:.2f}")
        
        clusters = [[sorted_lines[0]]]
        for i in range(1, len(sorted_lines)):
            y_gap = abs(sorted_lines[i].get('y_center', 0) - sorted_lines[i-1].get('y_center', 0))
            if y_gap < cluster_threshold:
                clusters[-1].append(sorted_lines[i])
            else:
                clusters.append([sorted_lines[i]])
        
        print(f"  断面基准组数（Y聚类后）: {len(clusters)}")
        
        # 分析每个断面框的宽高
        frame_widths = []
        frame_heights = []
        frame_gaps = []
        
        for i, cluster in enumerate(clusters):
            # 合并聚类内所有实体的范围（只使用有有效范围的实体）
            valid_entities = [e for e in cluster if e.get('x_min', float('inf')) != float('inf')]
            if not valid_entities:
                continue
            
            cluster_x_min = min(e.get('x_min', float('inf')) for e in valid_entities)
            cluster_x_max = max(e.get('x_max', float('-inf')) for e in valid_entities)
            cluster_y_min = min(e.get('y_min', float('inf')) for e in valid_entities)
            cluster_y_max = max(e.get('y_max', float('-inf')) for e in valid_entities)
            
            # 只计算有效范围
            if cluster_x_max > cluster_x_min and cluster_y_max > cluster_y_min:
                frame_width = cluster_x_max - cluster_x_min
                frame_height = cluster_y_max - cluster_y_min
                
                frame_widths.append(frame_width)
                frame_heights.append(frame_height)
            
            if i > 0:
                prev_y_center = clusters[i-1][0].get('y_center', 0)
                curr_y_center = cluster[0].get('y_center', 0)
                frame_gaps.append(abs(prev_y_center - curr_y_center))
        
        avg_frame_width = sum(frame_widths) / len(frame_widths) if frame_widths else 0
        avg_frame_height = sum(frame_heights) / len(frame_heights) if frame_heights else 0
        avg_frame_gap = sum(frame_gaps) / len(frame_gaps) if frame_gaps else 0
        
        print(f"  平均断面框宽度: {avg_frame_width:.2f}")
        print(f"  平均断面框高度: {avg_frame_height:.2f}")
        print(f"  平均断面框间距: {avg_frame_gap:.2f}")
        
        return {
            'frame_count': len(clusters),
            'avg_width': avg_frame_width,
            'avg_height': avg_frame_height,
            'avg_gap': avg_frame_gap,
            'frames': clusters,
            'spine_data': spine_data  # 添加脊梁线数据
        }
    
    def analyze_DMX_sections(self):
        """分析DMX图层（断面线）的特征"""
        print("\n=== 分析DMX图层（断面线） ===")
        
        dmx_stats = self._analyze_layer('DMX')
        
        if dmx_stats['entity_count'] == 0:
            print("  DMX图层无实体")
            return None
        
        print(f"  实体数: {dmx_stats['entity_count']}")
        print(f"  平均宽度: {dmx_stats['avg_width']:.2f}")
        print(f"  平均高度: {dmx_stats['avg_height']:.2f}")
        
        # 计算断面线长度
        lengths = []
        y_centers = []
        
        for e in self.msp.query('LWPOLYLINE[layer=="DMX"]'):
            try:
                pts = [(p[0], p[1]) for p in e.get_points()]
                if len(pts) >= 2:
                    # 计算线段总长度
                    length = sum(math.sqrt((pts[i+1][0]-pts[i][0])**2 + (pts[i+1][1]-pts[i][1])**2) 
                                for i in range(len(pts)-1))
                    lengths.append(length)
                    
                    y_min = min(p[1] for p in pts)
                    y_max = max(p[1] for p in pts)
                    y_centers.append((y_min + y_max) / 2)
            except: pass
        
        avg_length = sum(lengths) / len(lengths) if lengths else 0
        
        # 计算断面间距
        y_centers_sorted = sorted(y_centers, reverse=True)
        gaps = [y_centers_sorted[i] - y_centers_sorted[i+1] 
                for i in range(len(y_centers_sorted)-1)] if len(y_centers_sorted) >= 2 else []
        avg_gap = sum(gaps) / len(gaps) if gaps else 0
        
        print(f"  平均断面线长度: {avg_length:.2f}")
        print(f"  平均断面间距: {avg_gap:.2f}")
        
        return {
            'section_count': dmx_stats['entity_count'],
            'avg_length': avg_length,
            'avg_gap': avg_gap,
            'avg_width': dmx_stats['avg_width'],
            'avg_height': dmx_stats['avg_height']
        }
    
    def analyze_station_texts(self, spine_data=None):
        """分析桩号文本，并合并L1脊梁线数据
        
        Args:
            spine_data: L1脊梁线数据，包含245条脊梁线信息
        """
        print("\n=== 分析桩号文本 ===")
        
        stations = []
        for e in self.msp.query('TEXT MTEXT'):
            try:
                txt = e.plain_text() if e.dxftype() == 'MTEXT' else e.dxf.text
                match = self.STATION_PATTERN.search(txt.upper())
                if match:
                    # 获取插入点
                    if e.dxftype() == 'TEXT':
                        x = e.dxf.insert.x
                        y = e.dxf.insert.y
                    else:
                        x = e.dxf.insert.x
                        y = e.dxf.insert.y
                    
                    sid = match.group(1)
                    nums = re.findall(r'\d+', sid)
                    value = int("".join(nums)) if nums else 0
                    
                    stations.append({
                        'text': sid,
                        'value': value,
                        'x': x,
                        'y': y
                    })
            except: pass
        
        print(f"  桩号文本数: {len(stations)}")
        
        if stations:
            # 按Y排序计算间距
            sorted_stations = sorted(stations, key=lambda s: s['y'], reverse=True)
            gaps = [sorted_stations[i]['y'] - sorted_stations[i+1]['y'] 
                    for i in range(len(sorted_stations)-1)]
            avg_gap = sum(gaps) / len(gaps) if gaps else 0
            
            print(f"  平均桩号文本间距: {avg_gap:.2f}")
            
            # ===== 合并L1脊梁线数据到桩号元数据 =====
            if spine_data and spine_data.get('spines'):
                spines = spine_data['spines']
                print(f"\n  === 合并L1脊梁线到桩号元数据 ===")
                
                # 按Y位置最近邻匹配桩号和脊梁线
                matched_count = 0
                for station in sorted_stations:
                    station_y = station['y']
                    
                    # 找Y位置最接近的脊梁线
                    best_spine = None
                    best_y_diff = float('inf')
                    
                    for spine in spines:
                        spine_y = spine.get('y_center', 0)
                        y_diff = abs(spine_y - station_y)
                        
                        if y_diff < best_y_diff:
                            best_y_diff = y_diff
                            best_spine = spine
                    
                    # 如果找到匹配的脊梁线（Y差距<50）
                    if best_spine and best_y_diff < 50:
                        # 添加L1脊梁线数据到桩号元数据
                        station['l1_spine'] = {
                            'y_center': best_spine.get('y_center'),
                            'x_center': best_spine.get('x_center'),
                            'center_height': best_spine.get('center_height'),  # 垂直高度（航道深度）
                            'top_width': best_spine.get('top_width'),          # 顶边宽度（断面宽度）
                            'y_min': best_spine.get('y_min'),
                            'y_max': best_spine.get('y_max')
                        }
                        matched_count += 1
                
                print(f"  匹配桩号数: {matched_count}/{len(sorted_stations)}")
                
                # 输出示例
                print(f"\n  === 桩号元数据示例（含L1脊梁线） ===")
                for i, station in enumerate(sorted_stations[:5]):
                    if 'l1_spine' in station:
                        spine = station['l1_spine']
                        print(f"    桩号{station['text']}: X={spine['x_center']:.1f}, "
                              f"深度H={spine['center_height']:.1f}, 宽度W={spine['top_width']:.1f}")
            
            return {
                'station_count': len(stations),
                'avg_gap': avg_gap,
                'stations': sorted_stations  # 已按Y排序
            }
        
        return None
    
    def calculate_scale_ratio(self, reference_values):
        """计算缩放比例
        
        Args:
            reference_values: dict containing reference values for comparison
                - frame_width: L1断面框宽度
                - frame_height: L1断面框高度
                - frame_gap: L1断面框间距
                - dmx_length: DMX断面线长度
                - dmx_gap: DMX断面间距
                - station_gap: 桩号文本间距
        
        Returns:
            dict with multiple scale estimates and final recommendation
        """
        print("\n=== 计算缩放比例 ===")
        
        # 参考标准值（根据历史数据确定）
        REF_VALUES = {
            'frame_width': 160.0,    # 标准断面框宽度
            'frame_height': 80.0,    # 标准断面框高度
            'frame_gap': 150.0,      # 标准断面框间距
            'dmx_length': 160.0,     # 标准断面线长度
            'dmx_gap': 150.0,        # 标准断面间距（桩号间距25m，图纸间距约150单位）
            'station_gap': 150.0,    # 标准桩号文本间距
        }
        
        scales = {}
        
        # 计算各种比例估计
        if reference_values.get('frame_width'):
            scales['frame_width'] = reference_values['frame_width'] / REF_VALUES['frame_width']
            print(f"  L1框宽度比例: {scales['frame_width']:.4f}")
        
        if reference_values.get('frame_height'):
            scales['frame_height'] = reference_values['frame_height'] / REF_VALUES['frame_height']
            print(f"  L1框高度比例: {scales['frame_height']:.4f}")
        
        if reference_values.get('frame_gap'):
            scales['frame_gap'] = reference_values['frame_gap'] / REF_VALUES['frame_gap']
            print(f"  L1框间距比例: {scales['frame_gap']:.4f}")
        
        if reference_values.get('dmx_length'):
            scales['dmx_length'] = reference_values['dmx_length'] / REF_VALUES['dmx_length']
            print(f"  DMX长度比例: {scales['dmx_length']:.4f}")
        
        if reference_values.get('dmx_gap'):
            scales['dmx_gap'] = reference_values['dmx_gap'] / REF_VALUES['dmx_gap']
            print(f"  DMX间距比例: {scales['dmx_gap']:.4f}")
        
        if reference_values.get('station_gap'):
            scales['station_gap'] = reference_values['station_gap'] / REF_VALUES['station_gap']
            print(f"  桩号间距比例: {scales['station_gap']:.4f}")
        
        # 综合计算最佳比例
        if scales:
            # 方法1：所有比例的平均值
            avg_scale = sum(scales.values()) / len(scales)
            print(f"\n  方法1（平均）: {avg_scale:.4f}")
            
            # 方法2：加权平均（间距类权重更高，因为更稳定）
            weights = {
                'frame_width': 1.0,
                'frame_height': 0.5,  # 高度变化较大
                'frame_gap': 2.0,     # 间距最稳定
                'dmx_length': 1.0,
                'dmx_gap': 2.0,       # 间距最稳定
                'station_gap': 1.5
            }
            
            total_weight = sum(weights.get(k, 1.0) * v for k, v in scales.items())
            weighted_scale = sum(weights.get(k, 1.0) * v for k, v in scales.items()) / total_weight
            print(f"  方法2（加权）: {weighted_scale:.4f}")
            
            # 方法3：中位数（排除异常值）
            sorted_scales = sorted(scales.values())
            median_scale = sorted_scales[len(sorted_scales)//2]
            print(f"  方法3（中位数）: {median_scale:.4f}")
            
            # 推荐使用加权平均
            recommended = weighted_scale
            
            print(f"\n  推荐: {recommended:.4f}")
            
            # 验证：检查各比例的一致性
            max_deviation = max(abs(v - recommended) for v in scales.values())
            print(f"  最大偏差: {max_deviation:.4f}")
            
            if max_deviation < 0.1:
                print("  结论: 各比例高度一致，检测可靠")
            elif max_deviation < 0.2:
                print("  结论: 各比例基本一致，检测可信")
            else:
                print("  结论: 各比例差异较大，需人工核实")
        
        return scales
    
    def _get_ruler_positions(self):
        """获取标尺图层的Y位置"""
        ruler_y = []
        try:
            for e in self.msp.query('*[layer=="标尺"]'):
                if e.dxftype() == 'LINE':
                    y = (e.dxf.start.y + e.dxf.end.y) / 2
                    ruler_y.append(y)
                elif e.dxftype() in ('LWPOLYLINE', 'POLYLINE'):
                    pts = [(p[0], p[1]) for p in e.get_points()]
                    if pts:
                        y = sum(p[1] for p in pts) / len(pts)
                        ruler_y.append(y)
                elif e.dxftype() == 'TEXT':
                    ruler_y.append(e.dxf.insert.y)
        except:
            pass
        
        return sorted(set(ruler_y), reverse=True) if ruler_y else None
    
    def _cluster_by_y(self, entities):
        """按Y坐标聚类"""
        if not entities:
            return []
        
        # 计算高度中位数作为聚类阈值
        heights = [e.get('height', e.get('y_max', 0) - e.get('y_min', 0)) for e in entities]
        median_height = sorted(heights)[len(heights)//2] if heights else 100
        cluster_threshold = median_height * 1.5
        
        clusters = [[entities[0]]]
        for i in range(1, len(entities)):
            y_gap = abs(entities[i].get('y_center', 0) - entities[i-1].get('y_center', 0))
            if y_gap < cluster_threshold:
                clusters[-1].append(entities[i])
            else:
                clusters.append([entities[i]])
        
        return clusters
    
    def compare_with_DMX(self, l1_data, dmx_data):
        """对比L1框与DMX断面线的匹配情况"""
        print("\n=== 对比L1框与DMX ===")
        
        if not l1_data or not dmx_data:
            print("  缺少数据")
            return
        
        print(f"  L1断面框数: {l1_data['frame_count']}")
        print(f"  DMX断面数: {dmx_data['section_count']}")
        
        # 对比宽度和间距
        print(f"  L1平均宽度: {l1_data['avg_width']:.2f}")
        print(f"  DMX平均宽度: {dmx_data['avg_width']:.2f}")
        print(f"  宽度差异: {abs(l1_data['avg_width'] - dmx_data['avg_width']):.2f}")
        
        print(f"  L1平均间距: {l1_data['avg_gap']:.2f}")
        print(f"  DMX平均间距: {dmx_data['avg_gap']:.2f}")
        print(f"  间距差异: {abs(l1_data['avg_gap'] - dmx_data['avg_gap']):.2f}")
        
        # 判断哪个更适合作为参考
        if l1_data['frame_count'] == dmx_data['section_count']:
            print("  结论: L1框数与DMX数一致，两者均可作为参考")
        else:
            print(f"  结论: L1框数与DMX数不一致，建议使用桩号文本作为主要参考")
        
        return {
            'l1_count': l1_data['frame_count'],
            'dmx_count': dmx_data['section_count'],
            'match': l1_data['frame_count'] == dmx_data['section_count']
        }
    
    def full_analysis(self):
        """完整分析流程"""
        print("\n" + "="*60)
        print(f"完整分析: {os.path.basename(self.dxf_path)}")
        print("="*60)
        
        # 1. 分析所有图层概览
        layer_stats = self.analyze_all_layers()
        
        # 2. 先分析DMX图层（获取参考断面间距）
        dmx_data = self.analyze_DMX_sections()
        
        # 3. 分析L1图层（使用DMX间距作为聚类阈值）
        reference_gap = dmx_data['avg_gap'] if dmx_data else None
        l1_data = self.analyze_L1_frames(reference_gap)
        
        # 4. 分析桩号文本（传入L1脊梁线数据）
        spine_data = l1_data.get('spine_data') if l1_data else None
        station_data = self.analyze_station_texts(spine_data)
        
        # 5. 对比L1与DMX
        self.compare_with_DMX(l1_data, dmx_data)
        
        # 6. 计算缩放比例
        reference_values = {}
        if l1_data:
            reference_values['frame_width'] = l1_data['avg_width']
            reference_values['frame_height'] = l1_data['avg_height']
            reference_values['frame_gap'] = l1_data['avg_gap']
        if dmx_data:
            reference_values['dmx_length'] = dmx_data['avg_length']
            reference_values['dmx_gap'] = dmx_data['avg_gap']
        if station_data:
            reference_values['station_gap'] = station_data['avg_gap']
        
        scales = self.calculate_scale_ratio(reference_values)
        
        return {
            'layer_stats': layer_stats,
            'l1_data': l1_data,
            'dmx_data': dmx_data,
            'station_data': station_data,
            'scales': scales
        }


def compare_two_files(file1, file2):
    """对比两个文件的检测结果"""
    print("\n" + "="*80)
    print("对比分析两个文件")
    print("="*80)
    
    analyzer1 = ScaleAnalyzer(file1)
    analyzer2 = ScaleAnalyzer(file2)
    
    result1 = analyzer1.full_analysis()
    print("\n")
    result2 = analyzer2.full_analysis()
    
    # 对比缩放比例
    print("\n" + "="*80)
    print("缩放比例对比总结")
    print("="*80)
    
    print(f"\n文件1: {os.path.basename(file1)}")
    if result1['scales']:
        for key, value in result1['scales'].items():
            print(f"  {key}: {value:.4f}")
    
    print(f"\n文件2: {os.path.basename(file2)}")
    if result2['scales']:
        for key, value in result2['scales'].items():
            print(f"  {key}: {value:.4f}")
    
    # 计算面积比例
    if result1['scales'] and result2['scales']:
        # 用加权比例计算
        weights = {'frame_width': 2.0, 'frame_gap': 2.0, 'dmx_gap': 2.0}
        
        scale1 = sum(weights.get(k, 1.0) * v for k, v in result1['scales'].items()) / \
                 sum(weights.get(k, 1.0) for k in result1['scales'].keys())
        scale2 = sum(weights.get(k, 1.0) * v for k, v in result2['scales'].items()) / \
                 sum(weights.get(k, 1.0) for k in result2['scales'].keys())
        
        print(f"\n加权缩放比例对比:")
        print(f"  文件1: {scale1:.4f}")
        print(f"  文件2: {scale2:.4f}")
        print(f"  比值: {scale2/scale1:.4f}")
        
        # 验证面积比例0.6
        expected_ratio = math.sqrt(0.6)  # 面积比例0.6对应的坐标比例
        actual_ratio = scale2 / scale1
        
        print(f"\n验证面积比例0.6:")
        print(f"  预期坐标比例 (√0.6): {expected_ratio:.4f}")
        print(f"  实际检测比例: {actual_ratio:.4f}")
        print(f"  偏差: {abs(actual_ratio - expected_ratio):.4f} ({abs(actual_ratio - expected_ratio)/expected_ratio*100:.2f}%)")
        
        if abs(actual_ratio - expected_ratio) < 0.05:
            print("  结论: 检测结果与预期高度吻合！")
        elif abs(actual_ratio - expected_ratio) < 0.1:
            print("  结论: 检测结果与预期基本吻合。")
        else:
            print("  结论: 检测结果存在偏差，需进一步优化。")


if __name__ == '__main__':
    # 测试文件路径
    file1 = r'D:\断面算量平台\测试文件\内湾段分层图（全航道底图20260318）.dxf'
    file2 = r'D:\断面算量平台\测试文件\内湾段分层图（全航道底图20260318）面积比例0.6.dxf'
    
    compare_two_files(file1, file2)