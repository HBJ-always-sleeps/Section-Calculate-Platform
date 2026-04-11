# -*- coding: utf-8 -*-
"""
BIM模型构建器 - 从DXF断面图构建3D航道模型

功能：
1. 从DXF提取各断面的填充边界、DMX断面线、超挖线
2. 使用与engine_cad相同的断面检测逻辑（Y坐标聚类、桩号匹配）
3. 生成元数据文件（JSON格式）
4. 2D画廊展示（固定图框位置排列）
5. 3D可视化展示

作者: @黄秉俊
日期: 2026-03-28
"""

import ezdxf
import json
import os
import sys
import numpy as np
from typing import List, Dict, Tuple, Optional, Any
from dataclasses import dataclass, field, asdict
from shapely.geometry import Polygon, LineString, MultiPolygon, box, Point
from shapely.ops import unary_union
import re
import math

# ==================== 数据结构定义 ====================

@dataclass
class SectionMetadata:
    """断面元数据"""
    station_name: str  # 桩号名称
    station_value: float  # 桩号数值（米）
    x_min: float  # X最小值
    x_max: float  # X最大值
    y_min: float  # Y最小值（高程）
    y_max: float  # Y最大值（高程）
    y_center: float  # Y中心（用于排序）
    dmx_points: List[List[float]] = field(default_factory=list)  # DMX断面线点
    overbreak_points: List[List[float]] = field(default_factory=list)  # 超挖线点
    fill_boundaries: Dict[str, List[List[float]]] = field(default_factory=dict)  # 填充边界
    l1_ref_point: Optional[Dict] = None  # L1基准点 {'ref_x', 'ref_y'}
    
@dataclass
class BIMModelMetadata:
    """BIM模型元数据"""
    file_name: str
    total_sections: int = 0
    sections: List[SectionMetadata] = field(default_factory=list)
    global_x_min: float = float('inf')
    global_x_max: float = float('-inf')
    global_y_min: float = float('inf')
    global_y_max: float = float('-inf')


# ==================== 实体处理工具（来自engine_cad） ====================

class EntityHelper:
    """实体处理工具集"""
    
    @staticmethod
    def to_linestring(e):
        """统一处理各种线类型 -> LineString"""
        try:
            if e.dxftype() in ('LWPOLYLINE', 'POLYLINE'):
                pts = [(p[0], p[1]) for p in e.get_points()]
            elif e.dxftype() == 'LINE':
                pts = [(e.dxf.start.x, e.dxf.start.y), (e.dxf.end.x, e.dxf.end.y)]
            else:
                return None
            return LineString(pts) if len(pts) > 1 else None
        except:
            return None
    
    @staticmethod
    def get_best_point(e):
        """获取文本实体的最佳点"""
        try:
            if e.dxftype() == 'TEXT':
                return (e.dxf.align_point.x, e.dxf.align_point.y) if (e.dxf.halign or e.dxf.valign) else (e.dxf.insert.x, e.dxf.insert.y)
            return (e.dxf.insert.x, e.dxf.insert.y)
        except:
            return (0, 0)
    
    @staticmethod
    def get_text(e):
        """获取文本内容"""
        return e.plain_text() if e.dxftype() == 'MTEXT' else e.dxf.text


# ==================== 断面检测器（采用engine_cad逻辑） ====================

class SectionDetector:
    """断面检测器 - 按桩号分组（参考engine_cad逻辑）"""
    
    STATION_PATTERN = re.compile(r'(\d+\+\d+)')
    
    def __init__(self, msp, doc):
        self.msp = msp
        self.doc = doc
        self.scale_factor = 1.0  # 缩放比例因子
        
    def detect_sections(self) -> List[SectionMetadata]:
        """检测所有断面 - 按桩号分组，每个桩号合并所有相关元素"""
        print("  检测断面（按桩号分组模式）...")
        
        # 1. 获取DMX断面线（先获取用于检测缩放比例）
        dmx_list = self._get_dmx_sections()
        print(f"    DMX断面线: {len(dmx_list)}条")
        
        if not dmx_list:
            return []
        
        # 2. 检测缩放比例（参考engine_cad的ScaleDetector）
        self.scale_factor = self._detect_scale_factor(dmx_list)
        print(f"    缩放比例: {self.scale_factor:.4f}")
        
        # 3. 获取桩号文本（优先按桩号分组）
        station_texts = self._get_station_texts()
        print(f"    桩号文本: {len(station_texts)}个")
        
        # 4. 获取超挖线
        overbreak_lines = self._get_overbreak_lines()
        print(f"    超挖线: {len(overbreak_lines)}条")
        
        # 5. 获取填充边界
        fill_data = self._get_fill_boundaries()
        print(f"    填充图层: {len(fill_data)}个")
        
        # 6. 按桩号分组（使用自适应容差）
        station_groups = self._group_by_station(dmx_list, station_texts)
        print(f"    桩号分组数: {len(station_groups)}个")
        
        # 6. 构建断面元数据 - 每个桩号一个断面
        sections = []
        for group_info in station_groups:
            station_name = group_info['station_name']
            station_value = group_info['station_value']
            dmx_group = group_info['dmx_group']
            
            # 合并组内所有DMX的边界和点
            all_x_min = min(d['x_min'] for d in dmx_group)
            all_x_max = max(d['x_max'] for d in dmx_group)
            all_y_min = min(d['y_min'] for d in dmx_group)
            all_y_max = max(d['y_max'] for d in dmx_group)
            y_center = (all_y_min + all_y_max) / 2
            
            # 合并所有DMX点
            all_dmx_pts = []
            for d in dmx_group:
                all_dmx_pts.extend(d['pts'])
            
            # 构建断面
            section = SectionMetadata(
                station_name=station_name,
                station_value=station_value,
                x_min=all_x_min,
                x_max=all_x_max,
                y_min=all_y_min,
                y_max=all_y_max,
                y_center=y_center,
                dmx_points=all_dmx_pts
            )
            
            # 匹配超挖线
            section.overbreak_points = self._match_overbreak(dmx_group, overbreak_lines)
            
            # 匹配填充边界
            section.fill_boundaries = self._match_fills(dmx_group, fill_data)
            
            # 重新计算包含所有元素的完整范围
            section = self._update_bounds(section)
            
            sections.append(section)
        
        # 按桩号数值排序
        sections.sort(key=lambda s: s.station_value, reverse=True)
        
        print(f"    最终断面数: {len(sections)}个")
        return sections
    
    def _group_by_station(self, dmx_list: List[Dict], station_texts: List[Dict]) -> List[Dict]:
        """按桩号分组DMX断面线（使用自适应缩放比例）"""
        # 使用缩放比例调整匹配容差（参考engine_cad的station_match_tolerance = 500 * scale_factor）
        # 标准容差500，乘以缩放比例得到自适应容差
        base_tolerance = 500  # 基础容差
        match_tolerance = base_tolerance * self.scale_factor
        
        # 按Y排序
        sorted_stations = sorted(station_texts, key=lambda s: s['y'], reverse=True)
        sorted_dmx = sorted(dmx_list, key=lambda d: d['y_center'], reverse=True)
        
        groups = []
        used_dmx = set()
        
        print(f"    匹配容差: {match_tolerance:.1f} (缩放比例={self.scale_factor:.4f})")
        
        # 按桩号匹配DMX（一对一匹配）
        for station in sorted_stations:
            station_name = station['text']
            station_value = station['value']
            station_y = station['y']
            station_x = station['x']
            
            # 找最近的DMX
            best_dmx_idx = None
            best_dist = float('inf')
            
            for i, dmx in enumerate(sorted_dmx):
                if i in used_dmx:
                    continue
                
                # Y距离为主，X距离为辅（参考engine_cad的距离计算）
                y_dist = abs(dmx['y_center'] - station_y)
                x_dist = abs((dmx['x_min'] + dmx['x_max']) / 2 - station_x)
                # 使用加权距离（Y权重更高，参考engine_cad的0.5权重）
                total_dist = math.sqrt(y_dist**2 + x_dist**2 * 0.5)
                
                if total_dist < best_dist:
                    best_dist = total_dist
                    best_dmx_idx = i
            
            # 如果找到了最近的DMX且距离在容差范围内
            if best_dmx_idx is not None and best_dist < match_tolerance:
                dmx = sorted_dmx[best_dmx_idx]
                used_dmx.add(best_dmx_idx)
                groups.append({
                    'station_name': station_name,
                    'station_value': station_value,
                    'dmx_group': [dmx]  # 每个桩号对应一条DMX
                })
        
        # 处理未匹配的DMX（按Y聚类生成默认桩号）
        unmatched_dmx = [dmx for i, dmx in enumerate(sorted_dmx) if i not in used_dmx]
        if unmatched_dmx:
            print(f"    未匹配DMX: {len(unmatched_dmx)}条")
            clusters = self._cluster_by_y(unmatched_dmx)
            for cluster in clusters:
                avg_y = sum(d['y_center'] for d in cluster) / len(cluster)
                groups.append({
                    'station_name': f"S{int(avg_y)}",
                    'station_value': int(avg_y),
                    'dmx_group': cluster
                })
        
        return groups
    
    def _detect_scale_factor(self, dmx_list: List[Dict]) -> float:
        """检测缩放比例（参考engine_cad的ScaleDetector）"""
        try:
            if len(dmx_list) < 3:
                return 1.0
            
            # 计算平均长度
            avg_length = sum(d['line'].length for d in dmx_list) / len(dmx_list)
            
            # 计算断面间距
            y_centers = sorted([d['y_center'] for d in dmx_list], reverse=True)
            if len(y_centers) >= 2:
                gaps = [y_centers[i] - y_centers[i+1] for i in range(len(y_centers)-1)]
                avg_gap = sum(gaps) / len(gaps)
            else:
                avg_gap = 100
            
            # 参考值（标准比例下的预期值）
            ref_length = 200.0  # 参考断面线长度
            ref_gap = 100.0     # 参考断面间距
            
            # 通过长度和间距双重推断缩放比例
            length_scale = avg_length / ref_length
            gap_scale = avg_gap / ref_gap
            
            # 取两者平均值
            scale = (length_scale + gap_scale) / 2
            
            # 限制在合理范围内
            scale = max(0.1, min(10.0, scale))
            
            return scale
        except:
            return 1.0
    
    def _get_dmx_sections(self) -> List[Dict]:
        """获取DMX图层断面线"""
        dmx_list = []
        for e in self.msp.query('LWPOLYLINE[layer=="DMX"]'):
            try:
                pts = [(p[0], p[1]) for p in e.get_points()]
                if len(pts) >= 2:
                    x_coords = [p[0] for p in pts]
                    y_coords = [p[1] for p in pts]
                    dmx_list.append({
                        'pts': pts,
                        'line': LineString(pts),
                        'x_min': min(x_coords),
                        'x_max': max(x_coords),
                        'y_min': min(y_coords),
                        'y_max': max(y_coords),
                        'y_center': (min(y_coords) + max(y_coords)) / 2
                    })
            except: pass
        return dmx_list
    
    def _cluster_by_y(self, dmx_list: List[Dict]) -> List[List[Dict]]:
        """按Y坐标聚类分组（核心算法）"""
        if not dmx_list:
            return []
        
        # 按Y中心排序（从上到下）
        sorted_dmx = sorted(dmx_list, key=lambda d: d['y_center'], reverse=True)
        
        # 计算高度中位数作为聚类阈值
        heights = [d['y_max'] - d['y_min'] for d in sorted_dmx]
        median_height = sorted(heights)[len(heights)//2] if heights else 100
        cluster_threshold = median_height * 1.5
        
        # 聚类
        clusters = [[sorted_dmx[0]]]
        for i in range(1, len(sorted_dmx)):
            y_gap = abs(sorted_dmx[i]['y_center'] - sorted_dmx[i-1]['y_center'])
            if y_gap < cluster_threshold:
                clusters[-1].append(sorted_dmx[i])
            else:
                clusters.append([sorted_dmx[i]])
        
        return clusters
    
    def _get_station_texts(self) -> List[Dict]:
        """获取桩号文本"""
        stations = []
        for e in self.msp.query('TEXT MTEXT'):
            try:
                txt = EntityHelper.get_text(e).upper()
                match = self.STATION_PATTERN.search(txt)
                if match:
                    pt = EntityHelper.get_best_point(e)
                    sid = match.group(1)
                    # 解析桩号数值
                    nums = re.findall(r'\d+', sid)
                    value = int("".join(nums)) if nums else 0
                    stations.append({
                        'text': sid,
                        'value': value,
                        'x': pt[0],
                        'y': pt[1]
                    })
            except: pass
        return stations
    
    def _get_overbreak_lines(self) -> List[LineString]:
        """获取超挖线"""
        lines = []
        for e in self.msp.query('LWPOLYLINE[layer=="超挖线"]'):
            ls = EntityHelper.to_linestring(e)
            if ls:
                lines.append(ls)
        return lines
    
    def _get_fill_boundaries(self) -> Dict[str, List[List[List[float]]]]:
        """获取填充边界"""
        fill_data = {}
        
        # 地层图层名称模式
        layer_patterns = [
            r'(\d+)级(.+)',
            r'(.+)淤泥',
            r'(.+)黏土',
            r'(.+)砂',
            r'(.+)碎石',
            r'nonem(.*)',  # 添加nonem开头图层检测
        ]
        
        for layer_name in [l.dxf.name for l in self.doc.layers]:
            is_fill_layer = False
            for pattern in layer_patterns:
                if re.search(pattern, layer_name, re.IGNORECASE):
                    is_fill_layer = True
                    break
            
            if '填充' in layer_name or '淤泥' in layer_name or '黏土' in layer_name or \
               '砂' in layer_name or '碎石' in layer_name or '填土' in layer_name or \
               layer_name.lower().startswith('nonem'):  # 添加nonem开头图层
                is_fill_layer = True
            
            if is_fill_layer:
                boundaries = []
                # 从HATCH提取
                for h in self.msp.query(f'HATCH[layer=="{layer_name}"]'):
                    pts = self._extract_hatch_boundary(h)
                    if pts:
                        boundaries.append(pts)
                # 从LWPOLYLINE提取
                for e in self.msp.query(f'LWPOLYLINE[layer=="{layer_name}"]'):
                    try:
                        pts = [(p[0], p[1]) for p in e.get_points()]
                        if len(pts) >= 3:
                            boundaries.append(pts)
                    except: pass
                
                if boundaries:
                    fill_data[layer_name] = boundaries
        
        return fill_data
    
    def _extract_hatch_boundary(self, hatch) -> Optional[List[List[float]]]:
        """提取填充边界点"""
        points = []
        try:
            for path in hatch.paths:
                if hasattr(path, 'vertices') and len(path.vertices) > 0:
                    points = [(v[0], v[1]) for v in path.vertices]
                elif hasattr(path, 'edges'):
                    for edge in path.edges:
                        if hasattr(edge, 'start'):
                            points.append([edge.start[0], edge.start[1]])
        except: pass
        return points if len(points) >= 3 else None
    
    def _match_station(self, dmx: Dict, stations: List[Dict]) -> Tuple[str, float]:
        """匹配桩号"""
        sect_x_center = (dmx['x_min'] + dmx['x_max']) / 2
        sect_y_center = dmx['y_center']
        
        best_station = None
        best_dist = float('inf')
        
        for st in stations:
            # 距离计算（Y权重更高）
            dist = math.sqrt((st['x'] - sect_x_center)**2 * 0.5 + (st['y'] - sect_y_center)**2)
            if dist < best_dist:
                best_dist = dist
                best_station = st
        
        if best_station and best_dist < 500:  # 容差500
            return best_station['text'], best_station['value']
        
        # 默认桩号
        return f"S{int(sect_y_center)}", sect_y_center
    
    def _match_overbreak(self, dmx_group: List[Dict], overbreak_lines: List[LineString]) -> List[List[float]]:
        """匹配超挖线
        
        关键改进：
        1. Y轴向下扩展范围设置为30单位，平衡底边匹配和避免重复匹配
        2. 增加X坐标重叠验证，确保超挖线只匹配到X范围重叠的断面
        """
        # 计算组的边界框
        all_x = [d['x_min'] for d in dmx_group] + [d['x_max'] for d in dmx_group]
        all_y = [d['y_min'] for d in dmx_group] + [d['y_max'] for d in dmx_group]
        
        dmx_x_min = min(all_x)
        dmx_x_max = max(all_x)
        dmx_y_min = min(all_y)
        dmx_y_max = max(all_y)
        
        # Y轴向下扩展30单位以匹配底边位置较低的超挖线
        group_box = box(dmx_x_min - 10, dmx_y_min - 30, dmx_x_max + 10, dmx_y_max + 10)
        
        matched = []
        for line in overbreak_lines:
            if group_box.intersects(line):
                # 额外验证：超挖线的X范围必须与DMX的X范围有足够重叠
                line_x_coords = [p[0] for p in line.coords]
                line_x_min = min(line_x_coords)
                line_x_max = max(line_x_coords)
                
                # 计算X范围重叠比例
                overlap_x_min = max(dmx_x_min, line_x_min)
                overlap_x_max = min(dmx_x_max, line_x_max)
                
                if overlap_x_max > overlap_x_min:
                    # 有X重叠，计算重叠比例
                    line_width = line_x_max - line_x_min
                    overlap_width = overlap_x_max - overlap_x_min
                    overlap_ratio = overlap_width / line_width if line_width > 0 else 0
                    
                    # 重叠比例超过50%才匹配（避免匹配到相邻断面）
                    if overlap_ratio > 0.5:
                        matched.append([[p[0], p[1]] for p in line.coords])
        
        return matched
    
    def _match_fills(self, dmx_group: List[Dict], fill_data: Dict) -> Dict[str, List[List[float]]]:
        """匹配填充边界
        
        关键改进：Y轴向下扩展范围设置为30单位，与超挖线匹配逻辑一致
        """
        all_x = [d['x_min'] for d in dmx_group] + [d['x_max'] for d in dmx_group]
        all_y = [d['y_min'] for d in dmx_group] + [d['y_max'] for d in dmx_group]
        # Y轴向下扩展30单位以匹配底边位置较低的填充边界
        group_box = box(min(all_x) - 10, min(all_y) - 30, max(all_x) + 10, max(all_y) + 10)
        
        matched = {}
        for layer_name, boundaries in fill_data.items():
            layer_matched = []
            for boundary in boundaries:
                # 改用相交检测（而非中心点包含检测），以匹配部分在范围内的填充边界
                # 特别是贴着底部超挖线的填充，可能部分在范围内但中心点不在
                if len(boundary) >= 3:
                    # 创建边界多边形
                    try:
                        boundary_poly = Polygon(boundary)
                        if group_box.intersects(boundary_poly):
                            layer_matched.append(boundary)
                    except:
                        # 如果多边形无效，退回到中心点检测
                        b_x = [p[0] for p in boundary]
                        b_y = [p[1] for p in boundary]
                        b_center_x = sum(b_x) / len(b_x)
                        b_center_y = sum(b_y) / len(b_y)
                        if group_box.contains(Point(b_center_x, b_center_y)):
                            layer_matched.append(boundary)
            
            if layer_matched:
                matched[layer_name] = layer_matched
        
        return matched
    
    def _match_overbreak_single(self, dmx: Dict, overbreak_lines: List[LineString]) -> List[List[float]]:
        """为单条DMX匹配超挖线"""
        # 单条DMX的边界框
        dmx_box = box(dmx['x_min'] - 50, dmx['y_min'] - 50, 
                      dmx['x_max'] + 50, dmx['y_max'] + 50)
        
        matched = []
        for line in overbreak_lines:
            if dmx_box.intersects(line):
                matched.append([[p[0], p[1]] for p in line.coords])
        
        return matched
    
    def _match_fills_single(self, dmx: Dict, fill_data: Dict) -> Dict[str, List[List[float]]]:
        """为单条DMX匹配填充边界"""
        # 单条DMX的边界框
        dmx_box = box(dmx['x_min'] - 100, dmx['y_min'] - 100,
                      dmx['x_max'] + 100, dmx['y_max'] + 100)
        
        matched = {}
        for layer_name, boundaries in fill_data.items():
            layer_matched = []
            for boundary in boundaries:
                # 检查边界中心是否在DMX范围内
                b_x = [p[0] for p in boundary]
                b_y = [p[1] for p in boundary]
                b_center_x = sum(b_x) / len(b_x)
                b_center_y = sum(b_y) / len(b_y)
                
                if dmx_box.contains(Point(b_center_x, b_center_y)):
                    layer_matched.append(boundary)
            
            if layer_matched:
                matched[layer_name] = layer_matched
        
        return matched
    
    def _update_bounds(self, section: SectionMetadata) -> SectionMetadata:
        """更新断面边界以包含所有元素（DMX、超挖线、填充边界）"""
        # 初始范围来自DMX
        x_min = section.x_min
        x_max = section.x_max
        y_min = section.y_min
        y_max = section.y_max
        
        # 考虑超挖线的范围
        for ob_pts in section.overbreak_points:
            if len(ob_pts) >= 2:
                for p in ob_pts:
                    x_min = min(x_min, p[0])
                    x_max = max(x_max, p[0])
                    y_min = min(y_min, p[1])
                    y_max = max(y_max, p[1])
        
        # 考虑填充边界的范围
        for layer_name, boundaries in section.fill_boundaries.items():
            for boundary in boundaries:
                if len(boundary) >= 3:
                    for p in boundary:
                        x_min = min(x_min, p[0])
                        x_max = max(x_max, p[0])
                        y_min = min(y_min, p[1])
                        y_max = max(y_max, p[1])
        
        # 更新断面边界
        section.x_min = x_min
        section.x_max = x_max
        section.y_min = y_min
        section.y_max = y_max
        section.y_center = (y_min + y_max) / 2
        
        return section


# ==================== L1基准点检测器 ====================

class L1ReferencePointDetector:
    """L1基准点检测器 - 从L1图层提取脊梁线交点"""
    
    def __init__(self, msp, doc):
        self.msp = msp
        self.doc = doc
        
    def detect_reference_points(self) -> List[Dict]:
        """检测L1基准点（水平线与垂直线的交点）"""
        print("\n  === 检测L1基准点 ===")
        
        # 收集L1图层的LINE实体
        lines = []
        for e in self.msp.query('*[layer=="L1"]'):
            try:
                if e.dxftype() == 'LINE':
                    x1, y1 = e.dxf.start.x, e.dxf.start.y
                    x2, y2 = e.dxf.end.x, e.dxf.end.y
                    w, h = abs(x2-x1), abs(y2-y1)
                    # 水平线（宽度远大于高度）
                    if w > h * 3:
                        lines.append({'type': 'h', 'y': (y1+y2)/2, 'x': (x1+x2)/2, 'x_min': min(x1,x2), 'x_max': max(x1,x2)})
                    # 垂直线（高度远大于宽度）
                    elif h > w * 3:
                        lines.append({'type': 'v', 'x': (x1+x2)/2, 'y': (y1+y2)/2, 'y_min': min(y1,y2), 'y_max': max(y1,y2)})
                elif e.dxftype() in ('LWPOLYLINE', 'POLYLINE'):
                    pts = [(p[0], p[1]) for p in e.get_points()]
                    for i in range(len(pts)-1):
                        x1, y1 = pts[i]
                        x2, y2 = pts[i+1]
                        w, h = abs(x2-x1), abs(y2-y1)
                        if w > h * 3:
                            lines.append({'type': 'h', 'y': (y1+y2)/2, 'x': (x1+x2)/2, 'x_min': min(x1,x2), 'x_max': max(x1,x2)})
                        elif h > w * 3:
                            lines.append({'type': 'v', 'x': (x1+x2)/2, 'y': (y1+y2)/2, 'y_min': min(y1,y2), 'y_max': max(y1,y2)})
            except: pass
        
        # 分离水平和垂直线
        h_lines = [l for l in lines if l['type'] == 'h']
        v_lines = [l for l in lines if l['type'] == 'v']
        h_lines.sort(key=lambda l: l['y'], reverse=True)
        v_lines.sort(key=lambda l: l['y'], reverse=True)
        
        print(f"    水平线: {len(h_lines)}, 垂直线: {len(v_lines)}")
        
        # 匹配交点：每条垂直线找最近的水平线
        refs = []
        used_h = set()
        
        for v in v_lines:
            best_h = None
            best_diff = float('inf')
            best_idx = -1
            
            for h_idx, h in enumerate(h_lines):
                if h_idx in used_h:
                    continue
                diff = abs(h['y'] - v['y'])
                if diff < best_diff:
                    best_diff = diff
                    best_h = h
                    best_idx = h_idx
            
            # 容差50单位
            if best_h and best_diff < 50:
                used_h.add(best_idx)
                refs.append({
                    'ref_x': v['x'],  # 垂直线X坐标作为基准点X
                    'ref_y': best_h['y'],  # 水平线Y坐标作为基准点Y
                    'v_line': v,
                    'h_line': best_h
                })
        
        print(f"    匹配基准点: {len(refs)}")
        return refs
    
    def match_to_sections(self, sections: List[SectionMetadata], refs: List[Dict]) -> List[SectionMetadata]:
        """Match L1 reference points to sections - search UPWARD for reference points"""
        print("\n  === Matching L1 Reference Points to Sections (Upward Search) ===")
        
        if not refs:
            print("    No reference points to match")
            return sections
        
        # Sort refs by Y (descending - top to bottom)
        sorted_refs = sorted(refs, key=lambda r: r['ref_y'], reverse=True)
        
        matched_count = 0
        for section in sections:
            # Find the nearest reference point ABOVE or near the section
            best_ref = None
            best_diff = float('inf')
            
            # Section's Y range
            section_y_top = section.y_max
            section_y_center = section.y_center
            section_y_bottom = section.y_min
            
            for ref in sorted_refs:
                ref_y = ref['ref_y']
                ref_x = ref['ref_x']
                
                # Verify: ref X should be within section X range (with tolerance)
                x_tolerance = (section.x_max - section.x_min) * 0.5  # 50% X tolerance
                x_in_range = (section.x_min - x_tolerance) <= ref_x <= (section.x_max + x_tolerance)
                
                if not x_in_range:
                    continue
                
                # Y distance - prefer points ABOVE the section (ref_y > section_y_top)
                # but also allow points within or slightly below the section
                if ref_y >= section_y_top:  # Reference point is above section
                    # Distance from top of section
                    y_diff = ref_y - section_y_top
                elif ref_y >= section_y_bottom:  # Reference point is within section
                    # Distance from center
                    y_diff = abs(ref_y - section_y_center)
                else:  # Reference point is below section
                    # Distance from bottom + penalty
                    y_diff = (section_y_bottom - ref_y) + 100  # Add penalty for below
                
                if y_diff < best_diff:
                    best_diff = y_diff
                    best_ref = ref
            
            # Increased tolerance: 200 units for upward search
            if best_ref and best_diff < 200:
                section.l1_ref_point = {
                    'ref_x': best_ref['ref_x'],
                    'ref_y': best_ref['ref_y']
                }
                matched_count += 1
                print(f"    {section.station_name}: L1 at ({best_ref['ref_x']:.1f}, {best_ref['ref_y']:.1f}), dist={best_diff:.1f}")
        
        print(f"    Matched: {matched_count}/{len(sections)} sections")
        return sections


# ==================== BIM模型构建器 ====================

class BIMModelBuilder:
    """BIM模型构建器"""
    
    def __init__(self, dxf_path: str):
        self.dxf_path = dxf_path
        self.doc = ezdxf.readfile(dxf_path)
        self.msp = self.doc.modelspace()
        self.metadata = BIMModelMetadata(file_name=os.path.basename(dxf_path))
        
    def build_model(self) -> BIMModelMetadata:
        """构建BIM模型元数据"""
        print(f"\n开始构建BIM模型: {os.path.basename(self.dxf_path)}")
        
        # 使用断面检测器
        detector = SectionDetector(self.msp, self.doc)
        sections = detector.detect_sections()
        
        if not sections:
            print("  [警告] 未检测到断面")
            return self.metadata
        
        # 检测L1基准点并匹配到断面
        l1_detector = L1ReferencePointDetector(self.msp, self.doc)
        l1_refs = l1_detector.detect_reference_points()
        if l1_refs:
            sections = l1_detector.match_to_sections(sections, l1_refs)
        
        # 计算全局范围
        for section in sections:
            self.metadata.global_x_min = min(self.metadata.global_x_min, section.x_min)
            self.metadata.global_x_max = max(self.metadata.global_x_max, section.x_max)
            self.metadata.global_y_min = min(self.metadata.global_y_min, section.y_min)
            self.metadata.global_y_max = max(self.metadata.global_y_max, section.y_max)
        
        self.metadata.sections = sections
        self.metadata.total_sections = len(sections)
        
        print(f"\nBIM模型构建完成!")
        print(f"  总断面数: {self.metadata.total_sections}")
        print(f"  全局X范围: [{self.metadata.global_x_min:.2f}, {self.metadata.global_x_max:.2f}]")
        print(f"  全局Y范围: [{self.metadata.global_y_min:.2f}, {self.metadata.global_y_max:.2f}]")
        
        return self.metadata
    
    def save_metadata(self, output_path: str):
        """保存元数据到 JSON 文件"""
        data = {
            'file_name': self.metadata.file_name,
            'total_sections': self.metadata.total_sections,
            'global_bounds': {
                'x_min': self.metadata.global_x_min,
                'x_max': self.metadata.global_x_max,
                'y_min': self.metadata.global_y_min,
                'y_max': self.metadata.global_y_max
            },
            'sections': []
        }
        
        for section in self.metadata.sections:
            section_data = {
                'station_name': section.station_name,
                'station_value': section.station_value,
                'bounds': {
                    'x_min': section.x_min,
                    'x_max': section.x_max,
                    'y_min': section.y_min,
                    'y_max': section.y_max
                },
                'dmx_points': section.dmx_points,
                'overbreak_points': section.overbreak_points,
                'fill_boundaries': section.fill_boundaries,
                'l1_ref_point': section.l1_ref_point  # 保存 L1 基准点
            }
            data['sections'].append(section_data)
        
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        print(f"\n元数据已保存到: {output_path}")


# ==================== 2D画廊展示器（固定图框排列） ====================

class SectionGalleryViewer:
    """断面画廊展示器 - 2D固定图框排列（一幅图一个断面）"""
    
    def __init__(self, metadata: BIMModelMetadata):
        self.metadata = metadata
        self.current_page = 0
        self.sections_per_page = 1  # 每页只显示一个断面
        
    def create_gallery(self):
        """创建画廊式展示窗口"""
        import matplotlib.pyplot as plt
        from matplotlib.widgets import Button
        
        # 计算总页数
        self.total_pages = len(self.metadata.sections)
        
        # 创建图形（更大尺寸以显示单个断面）
        fig = plt.figure(figsize=(14, 10))
        self.fig = fig
        
        # 主标题
        title_ax = fig.add_axes([0.1, 0.92, 0.8, 0.06])
        title_ax.axis('off')
        title_ax.text(0.5, 0.5, 
                     f'Section Gallery - {self.metadata.file_name}\n'
                     f'Total: {self.metadata.total_sections} sections, 1 per page',
                     ha='center', va='center', fontsize=14, fontweight='bold')
        
        # 创建单个主图区域（占据大部分空间）
        self.axes = [fig.add_subplot(1, 1, 1)]
        
        # 导航按钮
        prev_ax = fig.add_axes([0.2, 0.02, 0.15, 0.05])
        next_ax = fig.add_axes([0.65, 0.02, 0.15, 0.05])
        info_ax = fig.add_axes([0.35, 0.02, 0.3, 0.05])
        
        self.prev_btn = Button(prev_ax, '◀ Previous')
        self.next_btn = Button(next_ax, 'Next ▶')
        self.info_ax = info_ax
        info_ax.axis('off')
        
        self.prev_btn.on_clicked(self._prev_page)
        self.next_btn.on_clicked(self._next_page)
        
        # 绘制第一页
        self._draw_page()
        
        return fig
    
    def _prev_page(self, event):
        """上一页"""
        if self.current_page > 0:
            self.current_page -= 1
            self._draw_page()
            self.fig.canvas.draw_idle()
    
    def _next_page(self, event):
        """下一页"""
        if self.current_page < self.total_pages - 1:
            self.current_page += 1
            self._draw_page()
            self.fig.canvas.draw_idle()
    
    def _draw_page(self):
        """绘制当前页的断面"""
        import matplotlib.pyplot as plt
        
        start_idx = self.current_page * self.sections_per_page
        end_idx = min(start_idx + self.sections_per_page, len(self.metadata.sections))
        
        # 更新页码信息
        self.info_ax.clear()
        self.info_ax.axis('off')
        self.info_ax.text(0.5, 0.5, 
                         f'Page {self.current_page + 1}/{self.total_pages} | Sections {start_idx + 1}-{end_idx}',
                         ha='center', va='center', fontsize=12)
        
        # 颜色映射
        colors = plt.cm.tab20.colors
        
        for i, ax in enumerate(self.axes):
            ax.clear()
            idx = start_idx + i
            
            if idx < len(self.metadata.sections):
                section = self.metadata.sections[idx]
                
                # 绘制DMX断面线
                if section.dmx_points:
                    pts = np.array(section.dmx_points)
                    ax.plot(pts[:, 0], pts[:, 1], 'b-', linewidth=2, label='DMX')
                
                # 绘制超挖线
                for ob_pts in section.overbreak_points:
                    if len(ob_pts) >= 2:
                        pts = np.array(ob_pts)
                        ax.plot(pts[:, 0], pts[:, 1], 'r--', linewidth=1.5, label='Overbreak')
                
                # 绘制填充边界
                for layer_name, boundaries in section.fill_boundaries.items():
                    color_idx = hash(layer_name) % len(colors)
                    for boundary in boundaries:
                        if len(boundary) >= 3:
                            pts = np.array(boundary)
                            ax.fill(pts[:, 0], pts[:, 1], alpha=0.4, 
                                   color=colors[color_idx])
                            ax.plot(pts[:, 0], pts[:, 1], color=colors[color_idx], 
                                   linewidth=1, linestyle='--')
                
                # 设置标题
                width = section.x_max - section.x_min
                depth = section.y_max - section.y_min
                ax.set_title(f'{section.station_name}\nW:{width:.1f} D:{depth:.1f}', fontsize=11)
                
                # 设置坐标轴
                ax.set_xlabel('X')
                ax.set_ylabel('Y (Elevation)')
                ax.grid(True, alpha=0.3)
                
                # 设置固定比例（保持原始比例）
                ax.set_aspect('auto')
                
            else:
                ax.axis('off')
                ax.text(0.5, 0.5, 'No Data', ha='center', va='center', fontsize=12)
        
        plt.tight_layout(rect=[0, 0.08, 1, 0.9])


# ==================== 交互式滚动画廊 ====================

class ScrollGalleryViewer:
    """Interactive scroll gallery - supports mouse wheel and button navigation (one section per page)"""
    
    def __init__(self, metadata: BIMModelMetadata, max_sections: int = None, sort_by_station_asc: bool = False):
        self.metadata = metadata
        self.max_sections = max_sections if max_sections else len(metadata.sections)
        
        # Sort sections by station value (ascending = smallest station first)
        if sort_by_station_asc:
            self.sections = sorted(metadata.sections, key=lambda s: s.station_value)[:self.max_sections]
            print(f"    Sorted by station ASC (smallest first), showing {len(self.sections)} sections")
        else:
            self.sections = metadata.sections[:self.max_sections]
        
        self.current_start = 0
        self.sections_per_view = 1  # One section per page
        
        # Use adaptive canvas (each section uses its own bounds)
        print(f"    Using adaptive canvas (each section uses its own bounds)")
        
    def show(self):
        """显示交互式滚动画廊"""
        import matplotlib.pyplot as plt
        from matplotlib.widgets import Button
        
        self.fig = plt.figure(figsize=(14, 10))
        self.fig.canvas.mpl_connect('scroll_event', self._on_scroll)
        self.fig.canvas.mpl_connect('key_press_event', self._on_key)
        
        # 标题
        self.title_ax = self.fig.add_axes([0.1, 0.92, 0.8, 0.06])
        self.title_ax.axis('off')
        
        # 创建单个主图区域（占据大部分空间）
        self.axes = [self.fig.add_subplot(1, 1, 1)]
        
        # 导航按钮
        prev_ax = self.fig.add_axes([0.2, 0.02, 0.15, 0.05])
        next_ax = self.fig.add_axes([0.65, 0.02, 0.15, 0.05])
        info_ax = self.fig.add_axes([0.35, 0.02, 0.3, 0.05])
        
        self.prev_btn = Button(prev_ax, '◀ Previous')
        self.next_btn = Button(next_ax, 'Next ▶')
        self.info_ax = info_ax
        self.info_ax.axis('off')
        
        self.prev_btn.on_clicked(self._prev_page)
        self.next_btn.on_clicked(self._next_page)
        
        # 绘制初始页面
        self._draw_page()
        
        plt.tight_layout(rect=[0, 0.08, 1, 0.9])
        plt.show()
    
    def _on_scroll(self, event):
        """鼠标滚轮事件"""
        if event.button == 'up':
            self._prev_page(None)
        elif event.button == 'down':
            self._next_page(None)
        self.fig.canvas.draw_idle()
    
    def _on_key(self, event):
        """键盘事件"""
        if event.key == 'left' or event.key == 'up':
            self._prev_page(None)
        elif event.key == 'right' or event.key == 'down':
            self._next_page(None)
        elif event.key == 'home':
            self.current_start = 0
            self._draw_page()
        elif event.key == 'end':
            self.current_start = max(0, len(self.sections) - self.sections_per_view)
            self._draw_page()
        self.fig.canvas.draw_idle()
    
    def _prev_page(self, event):
        """上一页"""
        if self.current_start > 0:
            self.current_start = max(0, self.current_start - self.sections_per_view)
            self._draw_page()
    
    def _next_page(self, event):
        """下一页"""
        if self.current_start + self.sections_per_view < len(self.sections):
            self.current_start = min(len(self.sections) - self.sections_per_view, 
                                    self.current_start + self.sections_per_view)
            self._draw_page()
    
    def _draw_page(self):
        """绘制当前页面"""
        import matplotlib.pyplot as plt
        
        # 更新标题
        self.title_ax.clear()
        self.title_ax.axis('off')
        self.title_ax.text(0.5, 0.5, 
                          f'2D Scroll Gallery - {self.metadata.file_name}\n'
                          f'Total: {len(self.sections)} sections | '
                          f'Showing {self.current_start + 1}-{min(self.current_start + self.sections_per_view, len(self.sections))}',
                          ha='center', va='center', fontsize=14, fontweight='bold')
        
        # 更新页码信息
        self.info_ax.clear()
        self.info_ax.axis('off')
        total_pages = (len(self.sections) + self.sections_per_view - 1) // self.sections_per_view
        current_page = self.current_start // self.sections_per_view + 1
        self.info_ax.text(0.5, 0.5, 
                         f'Page {current_page}/{total_pages} | '
                         f'Use ←→ arrows, mouse wheel, or buttons to navigate',
                         ha='center', va='center', fontsize=11, 
                         bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.5))
        
        colors = plt.cm.tab20.colors
        
        for i, ax in enumerate(self.axes):
            ax.clear()
            idx = self.current_start + i
            
            if idx < len(self.sections):
                section = self.sections[idx]
                
                # 绘制DMX断面线
                if section.dmx_points:
                    pts = np.array(section.dmx_points)
                    ax.plot(pts[:, 0], pts[:, 1], 'b-', linewidth=2.5, label='DMX', zorder=3)
                
                # 绘制超挖线
                for ob_pts in section.overbreak_points:
                    if len(ob_pts) >= 2:
                        pts = np.array(ob_pts)
                        ax.plot(pts[:, 0], pts[:, 1], 'r--', linewidth=2, label='Overbreak', zorder=2)
                
                # 绘制填充边界
                for layer_name, boundaries in section.fill_boundaries.items():
                    color_idx = hash(layer_name) % len(colors)
                    for boundary in boundaries:
                        if len(boundary) >= 3:
                            pts = np.array(boundary)
                            ax.fill(pts[:, 0], pts[:, 1], alpha=0.5, 
                                   color=colors[color_idx], zorder=1)
                            ax.plot(pts[:, 0], pts[:, 1], color=colors[color_idx], 
                                   linewidth=1.5, linestyle='-', zorder=1)
                
                # Draw L1 reference point (green dot and crosshair)
                if section.l1_ref_point:
                    ref_x = section.l1_ref_point['ref_x']
                    ref_y = section.l1_ref_point['ref_y']
                    # Green dot (reference point position)
                    ax.plot(ref_x, ref_y, 'go', markersize=12, label='L1 Reference', zorder=5)
                    # Crosshair lines (center lines)
                    ax.axvline(x=ref_x, color='green', linestyle='--', linewidth=1.5, alpha=0.7)
                    ax.axhline(y=ref_y, color='green', linestyle='--', linewidth=1.5, alpha=0.7)
                    # Coordinate label
                    ax.text(ref_x + 5, ref_y + 5, f'L1({ref_x:.1f}, {ref_y:.1f})', 
                           fontsize=10, color='darkgreen', fontweight='bold', zorder=5)
                
                # Set title with L1 reference point info
                width = section.x_max - section.x_min
                depth = section.y_max - section.y_min
                l1_info = f"L1: ({section.l1_ref_point['ref_x']:.1f}, {section.l1_ref_point['ref_y']:.1f})" if section.l1_ref_point else "No L1"
                ax.set_title(f'#{idx+1} {section.station_name} | W:{width:.1f} D:{depth:.1f} | {l1_info}', 
                           fontsize=12, fontweight='bold')
                
                # Calculate canvas bounds - expand to include L1 reference point
                x_min_canvas = section.x_min
                x_max_canvas = section.x_max
                y_min_canvas = section.y_min
                y_max_canvas = section.y_max
                
                # Expand canvas to include L1 reference point if exists
                if section.l1_ref_point:
                    x_min_canvas = min(x_min_canvas, section.l1_ref_point['ref_x'])
                    x_max_canvas = max(x_max_canvas, section.l1_ref_point['ref_x'])
                    y_min_canvas = min(y_min_canvas, section.l1_ref_point['ref_y'])
                    y_max_canvas = max(y_max_canvas, section.l1_ref_point['ref_y'])
                
                # Add margin (15%) to make the plot not touch edges
                width_canvas = x_max_canvas - x_min_canvas
                depth_canvas = y_max_canvas - y_min_canvas
                margin_x = width_canvas * 0.15
                margin_y = depth_canvas * 0.15
                
                ax.set_xlim(x_min_canvas - margin_x, x_max_canvas + margin_x)
                ax.set_ylim(y_min_canvas - margin_y - 10, y_max_canvas + margin_y)
                
                # 设置坐标轴
                ax.set_xlabel('X (m)', fontsize=10)
                ax.set_ylabel('Y - Elevation (m)', fontsize=10)
                ax.grid(True, alpha=0.3, linestyle=':')
                ax.set_aspect('auto')
                
            else:
                ax.axis('off')
                ax.text(0.5, 0.5, 'No Data', ha='center', va='center', fontsize=14, alpha=0.5)


# ==================== 3D可视化器 ====================

class BIMViewer:
    """3D可视化器"""
    
    def __init__(self, metadata: BIMModelMetadata):
        self.metadata = metadata
        
    def create_visualization(self, max_sections: int = 60):
        """创建3D可视化"""
        try:
            import matplotlib.pyplot as plt
            from mpl_toolkits.mplot3d import Axes3D
            from mpl_toolkits.mplot3d.art3d import Poly3DCollection
        except ImportError as e:
            print(f"导入依赖失败: {e}")
            return None
        
        fig = plt.figure(figsize=(14, 10))
        ax = fig.add_subplot(111, projection='3d')
        
        colors = plt.cm.tab20.colors
        display_sections = self.metadata.sections[:max_sections]
        
        # 归一化参数
        all_x = []
        all_y = []
        for section in display_sections:
            if section.dmx_points:
                for p in section.dmx_points:
                    all_x.append(p[0])
                    all_y.append(p[1])
        
        if not all_x:
            print("没有数据可显示")
            return None
        
        ref_x_min, ref_x_max = min(all_x), max(all_x)
        ref_y_min = min(all_y)
        
        # 绘制断面
        for i, section in enumerate(display_sections):
            z = i * 50  # Z轴间隔
            
            if section.dmx_points:
                pts = np.array(section.dmx_points)
                # 归一化X，保持Y原始值
                normalized_x = pts[:, 0] - ref_x_min
                normalized_y = pts[:, 1] - ref_y_min
                ax.plot(normalized_x, normalized_y, [z] * len(pts), 'b-', linewidth=2)
        
        ax.set_xlabel('X (Horizontal)')
        ax.set_ylabel('Y (Elevation)')
        ax.set_zlabel('Z (Station)')
        ax.set_title(f'Channel BIM Model - {self.metadata.file_name}\n'
                    f'Total: {self.metadata.total_sections} sections')
        
        return fig


# ==================== 主程序入口 ====================

def main():
    """主程序"""
    import argparse
    
    parser = argparse.ArgumentParser(description='BIM Model Builder')
    parser.add_argument('--input', '-i', type=str, 
                       default=r'D:\断面算量平台\测试文件\内湾段分层图（全航道底图20260331）2007面积比例0.6.dxf',
                       help='Input DXF file path')
    parser.add_argument('--output', '-o', type=str, default=None,
                       help='Output metadata JSON file path')
    parser.add_argument('--view', '-v', action='store_true',
                       help='Launch 3D visualization viewer')
    parser.add_argument('--gallery', '-g', action='store_true',
                       help='Use 2D gallery mode')
    parser.add_argument('--per-page', '-p', type=int, default=4,
                       help='Sections per page in gallery mode')
    parser.add_argument('--limit', '-l', type=int, default=60,
                       help='Max sections to display in 3D mode')
    parser.add_argument('--text-view', '-t', action='store_true',
                       help='Show 2D text view in console (no image)')
    parser.add_argument('--text-limit', type=int, default=20,
                       help='Number of sections to show in text view')
    parser.add_argument('--scroll', '-s', action='store_true',
                       help='Launch interactive 2D scroll gallery')
    parser.add_argument('--scroll-limit', type=int, default=20,
                       help='Max sections to show in scroll gallery')
    parser.add_argument('--smallest-station', action='store_true',
                       help='Sort by station value ascending (show smallest stations first)')
    parser.add_argument('--export', '-e', action='store_true',
                       help='Export all section images to output directory')
    parser.add_argument('--export-dir', type=str, default=None,
                       help='Output directory for exported section images')
    
    args = parser.parse_args()
    
    # 构建模型
    builder = BIMModelBuilder(args.input)
    metadata = builder.build_model()
    
    # 保存元数据
    if args.output:
        output_path = args.output
    else:
        base_name = os.path.splitext(os.path.basename(args.input))[0]
        output_path = os.path.join(os.path.dirname(args.input), f'{base_name}_bim_metadata.json')
    
    builder.save_metadata(output_path)
    
    # 启动可视化
    if args.view:
        try:
            import matplotlib.pyplot as plt
            
            # 设置非交互式后端，保存为文件
            plt.switch_backend('Agg')
            
            if args.gallery:
                # 2D画廊模式
                gallery_viewer = SectionGalleryViewer(metadata)
                gallery_viewer.sections_per_page = args.per_page
                fig = gallery_viewer.create_gallery()
                if fig:
                    # 保存为图片
                    output_img = os.path.join(os.path.dirname(args.input), 
                                             f'{base_name}_gallery.png')
                    fig.savefig(output_img, dpi=150, bbox_inches='tight')
                    print(f"\n2D画廊已保存到: {output_img}")
                    plt.close(fig)
            else:
                # 3D模式
                viewer = BIMViewer(metadata)
                fig = viewer.create_visualization(args.limit)
                if fig:
                    # 保存为图片
                    output_img = os.path.join(os.path.dirname(args.input), 
                                             f'{base_name}_3d_model.png')
                    fig.savefig(output_img, dpi=150, bbox_inches='tight')
                    print(f"\n3D模型已保存到: {output_img}")
                    plt.close(fig)
        except Exception as e:
            print(f"Cannot launch visualization: {e}")
            import traceback
            traceback.print_exc()
    
    # 文本模式二维展示（不生成图片）
    if args.text_view:
        print("\n" + "="*80)
        print("二维断面展示（文本模式）")
        print("="*80)
        
        # 显示前20个断面的详细信息
        display_count = min(args.text_limit, len(metadata.sections))
        print(f"\n显示前{display_count}个断面（共{len(metadata.sections)}个）：\n")
        
        for i, section in enumerate(metadata.sections[:display_count]):
            width = section.x_max - section.x_min
            depth = section.y_max - section.y_min
            dmx_pts_count = len(section.dmx_points) if section.dmx_points else 0
            overbreak_count = len(section.overbreak_points)
            fill_layer_count = len(section.fill_boundaries)
            
            print(f"断面 #{i+1:3d} | 桩号: {section.station_name:>10s} | "
                  f"Y中心: {section.y_center:>8.2f} | "
                  f"宽度: {width:>6.1f} | 深度: {depth:>6.1f} | "
                  f"DMX点: {dmx_pts_count:>3d} | 超挖线: {overbreak_count:>2d} | 填充层: {fill_layer_count:>2d}")
            
            # 显示填充层详情
            if section.fill_boundaries:
                fill_info = ", ".join([f"{name}({len(pts)}个)" for name, pts in list(section.fill_boundaries.items())[:3]])
                if len(section.fill_boundaries) > 3:
                    fill_info += f" ...等{len(section.fill_boundaries)}层"
                print(f"         └─ 填充: {fill_info}")
        
        if display_count < len(metadata.sections):
            print(f"\n... 还有 {len(metadata.sections) - display_count} 个断面未显示 ...")
        
        print("\n" + "="*80)
    
    # 交互式二维滚动画廊
    if args.scroll:
        print("\n启动交互式二维滚动画廊...")
        try:
            import matplotlib.pyplot as plt
            from matplotlib.widgets import Button, Slider
            
            # 设置交互式后端（尝试多个选项）
            try:
                plt.switch_backend('TkAgg')
            except:
                try:
                    plt.switch_backend('Qt5Agg')
                except:
                    plt.switch_backend('wxAgg')
            
            # Create scroll gallery with station sorting option
            gallery = ScrollGalleryViewer(metadata, args.scroll_limit, sort_by_station_asc=args.smallest_station)
            gallery.show()
            
        except Exception as e:
            print(f"无法启动交互式画廊: {e}")
            print("尝试使用非交互式后端保存图片...")
            import traceback
            traceback.print_exc()
    
    # 批量导出所有断面图片
    if args.export:
        print("\n" + "="*80)
        print("批量导出所有断面图片...")
        print("="*80)
        
        try:
            import matplotlib.pyplot as plt
            plt.switch_backend('Agg')  # 使用非交互式后端
            
            # 确定输出目录
            if args.export_dir:
                export_dir = args.export_dir
            else:
                # 默认输出到输入文件同目录下的_sections子目录
                base_name = os.path.splitext(os.path.basename(args.input))[0]
                export_dir = os.path.join(os.path.dirname(args.input), f'{base_name}_sections')
            
            # 创建输出目录（如果不存在则创建，如果存在则覆盖）
            if not os.path.exists(export_dir):
                os.makedirs(export_dir)
                print(f"创建输出目录: {export_dir}")
            else:
                print(f"输出目录已存在: {export_dir} (将覆盖原有文件)")
            
            # 按桩号升序排序（从小到大）
            sorted_sections = sorted(metadata.sections, key=lambda s: s.station_value)
            total_count = len(sorted_sections)
            print(f"总断面数: {total_count}")
            
            colors = plt.cm.tab20.colors
            success_count = 0
            
            for i, section in enumerate(sorted_sections):
                # 创建图形
                fig, ax = plt.subplots(figsize=(12, 8))
                
                # 绘制DMX断面线
                if section.dmx_points:
                    pts = np.array(section.dmx_points)
                    ax.plot(pts[:, 0], pts[:, 1], 'b-', linewidth=2.5, label='DMX', zorder=3)
                
                # 绘制超挖线
                for ob_pts in section.overbreak_points:
                    if len(ob_pts) >= 2:
                        pts = np.array(ob_pts)
                        ax.plot(pts[:, 0], pts[:, 1], 'r--', linewidth=2, label='Overbreak', zorder=2)
                
                # 绘制填充边界
                for layer_name, boundaries in section.fill_boundaries.items():
                    color_idx = hash(layer_name) % len(colors)
                    for boundary in boundaries:
                        if len(boundary) >= 3:
                            pts = np.array(boundary)
                            ax.fill(pts[:, 0], pts[:, 1], alpha=0.5, 
                                   color=colors[color_idx], zorder=1)
                            ax.plot(pts[:, 0], pts[:, 1], color=colors[color_idx], 
                                   linewidth=1.5, linestyle='-', zorder=1)
                
                # 绘制L1基准点
                if section.l1_ref_point:
                    ref_x = section.l1_ref_point['ref_x']
                    ref_y = section.l1_ref_point['ref_y']
                    ax.plot(ref_x, ref_y, 'go', markersize=12, label='L1 Reference', zorder=5)
                    ax.axvline(x=ref_x, color='green', linestyle='--', linewidth=1.5, alpha=0.7)
                    ax.axhline(y=ref_y, color='green', linestyle='--', linewidth=1.5, alpha=0.7)
                    ax.text(ref_x + 5, ref_y + 5, f'L1({ref_x:.1f}, {ref_y:.1f})', 
                           fontsize=10, color='darkgreen', fontweight='bold', zorder=5)
                
                # 设置标题（英文版本，避免中文字体问题）
                width = section.x_max - section.x_min
                depth = section.y_max - section.y_min
                l1_info = f"L1: ({section.l1_ref_point['ref_x']:.1f}, {section.l1_ref_point['ref_y']:.1f})" if section.l1_ref_point else "No L1"
                ax.set_title(f'Section {section.station_name} | Width:{width:.1f} Depth:{depth:.1f} | {l1_info}', 
                           fontsize=12, fontweight='bold')
                
                # 设置坐标轴范围
                x_min_canvas = section.x_min
                x_max_canvas = section.x_max
                y_min_canvas = section.y_min
                y_max_canvas = section.y_max
                
                if section.l1_ref_point:
                    x_min_canvas = min(x_min_canvas, section.l1_ref_point['ref_x'])
                    x_max_canvas = max(x_max_canvas, section.l1_ref_point['ref_x'])
                    y_min_canvas = min(y_min_canvas, section.l1_ref_point['ref_y'])
                    y_max_canvas = max(y_max_canvas, section.l1_ref_point['ref_y'])
                
                width_canvas = x_max_canvas - x_min_canvas
                depth_canvas = y_max_canvas - y_min_canvas
                margin_x = width_canvas * 0.15
                margin_y = depth_canvas * 0.15
                
                ax.set_xlim(x_min_canvas - margin_x, x_max_canvas + margin_x)
                ax.set_ylim(y_min_canvas - margin_y - 10, y_max_canvas + margin_y)
                
                ax.set_xlabel('X (m)', fontsize=10)
                ax.set_ylabel('Y - Elevation (m)', fontsize=10)
                ax.grid(True, alpha=0.3, linestyle=':')
                ax.set_aspect('auto')
                
                # 生成文件名：序号_桩号.png（如001_67_400.png）
                station_str = section.station_name.replace('+', '_')
                filename = f'{i+1:03d}_{station_str}.png'
                output_path = os.path.join(export_dir, filename)
                
                # 保存图片
                fig.savefig(output_path, dpi=150, bbox_inches='tight')
                plt.close(fig)
                success_count += 1
                
                # 进度显示
                if (i + 1) % 50 == 0 or (i + 1) == total_count:
                    print(f"  已导出: {i+1}/{total_count} 个断面...")
            
            print(f"\n导出完成!")
            print(f"  成功导出: {success_count}/{total_count} 个断面")
            print(f"  输出位置: {export_dir}")
            
        except Exception as e:
            print(f"导出失败: {e}")
            import traceback
            traceback.print_exc()
    
    return metadata


if __name__ == '__main__':
    main()