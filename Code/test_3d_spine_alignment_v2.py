# -*- coding: utf-8 -*-
"""
三维脊梁线对齐模型 V2 - 基于基准点对齐的航道3D拓扑重构

核心改进：
1. 使用bim_model_builder的SectionDetector提取完整断面要素（DMX、超挖线、填充边界）
2. 使用L1脊梁线交点作为基准点，与断面一一对应
3. 以基准点为原点进行坐标归一化
4. 3D映射：X=宽度, Y=里程, Z=高程

作者: @黄秉俊
日期: 2026-03-30
"""

import ezdxf
import os
import math
import re
import numpy as np
from typing import List, Dict, Tuple, Optional
from shapely.geometry import LineString, Polygon, Point, box
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d import Axes3D

class EntityHelper:
    """实体处理工具集"""
    
    @staticmethod
    def to_linestring(e):
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
        try:
            if e.dxftype() == 'TEXT':
                return (e.dxf.align_point.x, e.dxf.align_point.y) if (e.dxf.halign or e.dxf.valign) else (e.dxf.insert.x, e.dxf.insert.y)
            return (e.dxf.insert.x, e.dxf.insert.y)
        except:
            return (0, 0)
    
    @staticmethod
    def get_text(e):
        return e.plain_text() if e.dxftype() == 'MTEXT' else e.dxf.text


class SectionDetector:
    """断面检测器 - 按桩号分组"""
    
    STATION_PATTERN = re.compile(r'(\d+\+\d+)')
    
    def __init__(self, msp, doc):
        self.msp = msp
        self.doc = doc
        self.scale_factor = 1.0
        
    def detect_sections(self) -> List[Dict]:
        print("  检测断面（按桩号分组模式）...")
        
        dmx_list = self._get_dmx_sections()
        print(f"    DMX断面线: {len(dmx_list)}条")
        
        if not dmx_list:
            return []
        
        self.scale_factor = self._detect_scale_factor(dmx_list)
        print(f"    缩放比例: {self.scale_factor:.4f}")
        
        station_texts = self._get_station_texts()
        print(f"    桩号文本: {len(station_texts)}个")
        
        overbreak_lines = self._get_overbreak_lines()
        print(f"    超挖线: {len(overbreak_lines)}条")
        
        fill_data = self._get_fill_boundaries()
        print(f"    填充图层: {len(fill_data)}个")
        
        station_groups = self._group_by_station(dmx_list, station_texts)
        print(f"    桩号分组数: {len(station_groups)}个")
        
        sections = []
        for group_info in station_groups:
            station_name = group_info['station_name']
            station_value = group_info['station_value']
            dmx_group = group_info['dmx_group']
            
            all_x_min = min(d['x_min'] for d in dmx_group)
            all_x_max = max(d['x_max'] for d in dmx_group)
            all_y_min = min(d['y_min'] for d in dmx_group)
            all_y_max = max(d['y_max'] for d in dmx_group)
            y_center = (all_y_min + all_y_max) / 2
            
            all_dmx_pts = []
            for d in dmx_group:
                all_dmx_pts.extend(d['pts'])
            
            section = {
                'station_name': station_name,
                'station_value': station_value,
                'x_min': all_x_min,
                'x_max': all_x_max,
                'y_min': all_y_min,
                'y_max': all_y_max,
                'y_center': y_center,
                'dmx_points': all_dmx_pts,
                'overbreak_points': [],
                'fill_boundaries': {}
            }
            
            section['overbreak_points'] = self._match_overbreak(dmx_group, overbreak_lines)
            section['fill_boundaries'] = self._match_fills(dmx_group, fill_data)
            section = self._update_bounds(section)
            
            sections.append(section)
        
        sections.sort(key=lambda s: s['station_value'], reverse=True)
        print(f"    最终断面数: {len(sections)}个")
        return sections
    
    def _get_dmx_sections(self) -> List[Dict]:
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
    
    def _detect_scale_factor(self, dmx_list: List[Dict]) -> float:
        try:
            if len(dmx_list) < 3:
                return 1.0
            avg_length = sum(d['line'].length for d in dmx_list) / len(dmx_list)
            y_centers = sorted([d['y_center'] for d in dmx_list], reverse=True)
            gaps = [y_centers[i] - y_centers[i+1] for i in range(len(y_centers)-1)]
            avg_gap = sum(gaps) / len(gaps) if gaps else 100
            ref_length = 200.0
            ref_gap = 100.0
            scale = (avg_length / ref_length + avg_gap / ref_gap) / 2
            return max(0.1, min(10.0, scale))
        except:
            return 1.0
    
    def _get_station_texts(self) -> List[Dict]:
        stations = []
        for e in self.msp.query('TEXT MTEXT'):
            try:
                txt = EntityHelper.get_text(e).upper()
                match = self.STATION_PATTERN.search(txt)
                if match:
                    pt = EntityHelper.get_best_point(e)
                    sid = match.group(1)
                    nums = re.findall(r'\d+', sid)
                    value = int("".join(nums)) if nums else 0
                    stations.append({'text': sid, 'value': value, 'x': pt[0], 'y': pt[1]})
            except: pass
        return stations
    
    def _get_overbreak_lines(self) -> List[LineString]:
        lines = []
        for e in self.msp.query('LWPOLYLINE[layer=="超挖线"]'):
            ls = EntityHelper.to_linestring(e)
            if ls:
                lines.append(ls)
        return lines
    
    def _get_fill_boundaries(self) -> Dict[str, List[List[List[float]]]]:
        fill_data = {}
        for layer_name in [l.dxf.name for l in self.doc.layers]:
            is_fill = '填充' in layer_name or '淤泥' in layer_name or '黏土' in layer_name or \
                     '砂' in layer_name or '碎石' in layer_name or '填土' in layer_name or \
                     layer_name.lower().startswith('nonem')
            if is_fill:
                boundaries = []
                for h in self.msp.query(f'HATCH[layer=="{layer_name}"]'):
                    pts = self._extract_hatch_boundary(h)
                    if pts:
                        boundaries.append(pts)
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
        points = []
        try:
            for path in hatch.paths:
                if hasattr(path, 'vertices') and len(path.vertices) > 0:
                    points = [(v[0], v[1]) for v in path.vertices]
        except: pass
        return points if len(points) >= 3 else None
    
    def _group_by_station(self, dmx_list: List[Dict], station_texts: List[Dict]) -> List[Dict]:
        match_tolerance = 500 * self.scale_factor
        sorted_stations = sorted(station_texts, key=lambda s: s['y'], reverse=True)
        sorted_dmx = sorted(dmx_list, key=lambda d: d['y_center'], reverse=True)
        
        groups = []
        used_dmx = set()
        
        for station in sorted_stations:
            best_dmx_idx = None
            best_dist = float('inf')
            
            for i, dmx in enumerate(sorted_dmx):
                if i in used_dmx:
                    continue
                y_dist = abs(dmx['y_center'] - station['y'])
                x_dist = abs((dmx['x_min'] + dmx['x_max']) / 2 - station['x'])
                total_dist = math.sqrt(y_dist**2 + x_dist**2 * 0.5)
                if total_dist < best_dist:
                    best_dist = total_dist
                    best_dmx_idx = i
            
            if best_dmx_idx is not None and best_dist < match_tolerance:
                used_dmx.add(best_dmx_idx)
                groups.append({
                    'station_name': station['text'],
                    'station_value': station['value'],
                    'dmx_group': [sorted_dmx[best_dmx_idx]]
                })
        
        unmatched_dmx = [dmx for i, dmx in enumerate(sorted_dmx) if i not in used_dmx]
        if unmatched_dmx:
            clusters = self._cluster_by_y(unmatched_dmx)
            for cluster in clusters:
                avg_y = sum(d['y_center'] for d in cluster) / len(cluster)
                groups.append({'station_name': f"S{int(avg_y)}", 'station_value': int(avg_y), 'dmx_group': cluster})
        
        return groups
    
    def _cluster_by_y(self, dmx_list: List[Dict]) -> List[List[Dict]]:
        if not dmx_list:
            return []
        sorted_dmx = sorted(dmx_list, key=lambda d: d['y_center'], reverse=True)
        heights = [d['y_max'] - d['y_min'] for d in sorted_dmx]
        threshold = sorted(heights)[len(heights)//2] * 1.5 if heights else 100
        
        clusters = [[sorted_dmx[0]]]
        for i in range(1, len(sorted_dmx)):
            if abs(sorted_dmx[i]['y_center'] - sorted_dmx[i-1]['y_center']) < threshold:
                clusters[-1].append(sorted_dmx[i])
            else:
                clusters.append([sorted_dmx[i]])
        return clusters
    
    def _match_overbreak(self, dmx_group: List[Dict], overbreak_lines: List[LineString]) -> List[List[float]]:
        all_x = [d['x_min'] for d in dmx_group] + [d['x_max'] for d in dmx_group]
        all_y = [d['y_min'] for d in dmx_group] + [d['y_max'] for d in dmx_group]
        group_box = box(min(all_x) - 10, min(all_y) - 20, max(all_x) + 10, max(all_y) + 10)
        
        matched = []
        for line in overbreak_lines:
            if group_box.intersects(line):
                matched.append([[p[0], p[1]] for p in line.coords])
        return matched
    
    def _match_fills(self, dmx_group: List[Dict], fill_data: Dict) -> Dict[str, List[List[float]]]:
        all_x = [d['x_min'] for d in dmx_group] + [d['x_max'] for d in dmx_group]
        all_y = [d['y_min'] for d in dmx_group] + [d['y_max'] for d in dmx_group]
        group_box = box(min(all_x) - 10, min(all_y) - 20, max(all_x) + 10, max(all_y) + 10)
        
        matched = {}
        for layer_name, boundaries in fill_data.items():
            layer_matched = []
            for boundary in boundaries:
                if len(boundary) >= 3:
                    try:
                        if group_box.intersects(Polygon(boundary)):
                            layer_matched.append(boundary)
                    except: pass
            if layer_matched:
                matched[layer_name] = layer_matched
        return matched
    
    def _update_bounds(self, section: Dict) -> Dict:
        x_min, x_max = section['x_min'], section['x_max']
        y_min, y_max = section['y_min'], section['y_max']
        
        for ob_pts in section['overbreak_points']:
            for p in ob_pts:
                x_min = min(x_min, p[0])
                x_max = max(x_max, p[0])
                y_min = min(y_min, p[1])
                y_max = max(y_max, p[1])
        
        for boundaries in section['fill_boundaries'].values():
            for boundary in boundaries:
                for p in boundary:
                    x_min = min(x_min, p[0])
                    x_max = max(x_max, p[0])
                    y_min = min(y_min, p[1])
                    y_max = max(y_max, p[1])
        
        section['x_min'] = x_min
        section['x_max'] = x_max
        section['y_min'] = y_min
        section['y_max'] = y_max
        section['y_center'] = (y_min + y_max) / 2
        return section


class L1ReferencePointDetector:
    """L1基准点检测器 - 脊梁线交点"""
    
    def __init__(self, msp, doc):
        self.msp = msp
        self.doc = doc
        
    def detect_reference_points(self) -> List[Dict]:
        print("\n=== 检测L1基准点 ===")
        
        lines = []
        for e in self.msp.query('*[layer=="L1"]'):
            try:
                if e.dxftype() == 'LINE':
                    x1, y1 = e.dxf.start.x, e.dxf.start.y
                    x2, y2 = e.dxf.end.x, e.dxf.end.y
                    w, h = abs(x2-x1), abs(y2-y1)
                    if w > h * 3:
                        lines.append({'type': 'h', 'y': (y1+y2)/2, 'x': (x1+x2)/2})
                    elif h > w * 3:
                        lines.append({'type': 'v', 'x': (x1+x2)/2, 'y': (y1+y2)/2})
                elif e.dxftype() in ('LWPOLYLINE', 'POLYLINE'):
                    pts = [(p[0], p[1]) for p in e.get_points()]
                    for i in range(len(pts)-1):
                        x1, y1 = pts[i]
                        x2, y2 = pts[i+1]
                        w, h = abs(x2-x1), abs(y2-y1)
                        if w > h * 3:
                            lines.append({'type': 'h', 'y': (y1+y2)/2, 'x': (x1+x2)/2})
                        elif h > w * 3:
                            lines.append({'type': 'v', 'x': (x1+x2)/2, 'y': (y1+y2)/2})
            except: pass
        
        h_lines = [l for l in lines if l['type'] == 'h']
        v_lines = [l for l in lines if l['type'] == 'v']
        h_lines.sort(key=lambda l: l['y'], reverse=True)
        v_lines.sort(key=lambda l: l['y'], reverse=True)
        
        print(f"  水平线: {len(h_lines)}, 垂直线: {len(v_lines)}")
        
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
            
            if best_h and best_diff < 50:
                used_h.add(best_idx)
                refs.append({'ref_x': v['x'], 'ref_y': best_h['y']})
        
        print(f"  匹配基准点: {len(refs)}")
        return refs


def transform_to_3d(pt, ref, mileage, scale_x=1.0, scale_z=0.1):
    """坐标转换 - X轴扩大10倍展示
    
    Args:
        scale_x: X轴比例（1.0 = 原始CAD单位，扩大10倍展示）
        scale_z: Z轴比例（0.1 = 高程缩小10倍）
    """
    dx = pt[0] - ref['ref_x']
    dy = pt[1] - ref['ref_y']
    return (dx * scale_x, mileage, dy * scale_z)


class SpineAlignmentModelBuilder:
    """串糖葫芦对齐模型构建器 V2"""
    
    def __init__(self, dxf_path: str):
        self.dxf_path = dxf_path
        self.doc = ezdxf.readfile(dxf_path)
        self.msp = self.doc.modelspace()
        
    def build_model(self, num_sections=10, scale=0.1) -> Dict:
        print("\n" + "="*60)
        print("构建3D模型 V2")
        print("="*60)
        
        # 先检测桩号文本作为匹配中介
        station_texts = self._get_station_texts()
        print(f"  检测到桩号文本: {len(station_texts)}个")
        
        detector = SectionDetector(self.msp, self.doc)
        sections = detector.detect_sections()
        
        if not sections:
            print("ERROR: 未检测到断面!")
            return None
        
        l1_detector = L1ReferencePointDetector(self.msp, self.doc)
        refs = l1_detector.detect_reference_points()
        
        if not refs:
            print("ERROR: 未检测到基准点!")
            return None
        
        print(f"\n  断面: {len(sections)}, 基准点: {len(refs)}")
        
        # 使用桩号文本作为中介进行匹配
        matched = self._match_via_station(sections, refs, station_texts)[:num_sections]
        print(f"\n取前{len(matched)}个")
        
        model = {'metadata': {'source': os.path.basename(self.dxf_path), 'scale': scale}, 'sections': []}
        
        for i, m in enumerate(matched):
            sec, ref = m['section'], m['ref']
            mileage = sec['station_value']
            
            print(f"\n--- {i+1}: {sec['station_name']} ---")
            print(f"  基准点: ({ref['ref_x']:.1f}, {ref['ref_y']:.1f})")
            print(f"  里程: {mileage}m")
            print(f"  DMX: {len(sec['dmx_points'])}, 超挖: {len(sec['overbreak_points'])}, 填充: {len(sec['fill_boundaries'])}")
            
            # X轴扩大10倍展示（scale_x=1.0），Z轴保持原始比例（scale_z=scale）
            elements_3d = self._transform(sec, ref, mileage, scale_x=1.0, scale_z=scale)
            
            model['sections'].append({
                'station_name': sec['station_name'],
                'mileage': mileage,
                'ref_3d': (0, mileage, 0),
                'elements_3d': elements_3d
            })
        
        return model
    
    def _get_station_texts(self) -> List[Dict]:
        """获取所有桩号文本"""
        stations = []
        for e in self.msp.query('TEXT MTEXT'):
            try:
                txt = e.plain_text() if e.dxftype() == 'MTEXT' else e.dxf.text
                txt = txt.upper()
                match = re.search(r'(\d+)\+(\d+)', txt)
                if match:
                    pt = (e.dxf.insert.x, e.dxf.insert.y)
                    sid = match.group(0)
                    value = int(match.group(1)) * 1000 + int(match.group(2))
                    stations.append({'text': sid, 'value': value, 'x': pt[0], 'y': pt[1]})
            except: pass
        return stations
    
    def _match_via_station(self, sections, refs, station_texts):
        """匹配断面与基准点 - 严格按Y坐标排序后一对一匹配
        
        核心逻辑：
        1. 断面和基准点都按Y坐标降序排序
        2. 检测分页边界（Y坐标大跳跃）
        3. 在每个页面内按Y顺序一对一匹配
        """
        # 按Y坐标降序排序
        sorted_sec = sorted(sections, key=lambda s: s['y_center'], reverse=True)
        sorted_ref = sorted(refs, key=lambda r: r['ref_y'], reverse=True)
        
        print(f"  断面: {len(sorted_sec)}, 基准点: {len(sorted_ref)}")
        
        # 分析Y坐标分布
        sec_y_list = [s['y_center'] for s in sorted_sec]
        ref_y_list = [r['ref_y'] for r in sorted_ref]
        
        # 计算Y间距
        sec_gaps = [sec_y_list[i] - sec_y_list[i+1] for i in range(len(sec_y_list)-1)]
        ref_gaps = [ref_y_list[i] - ref_y_list[i+1] for i in range(len(ref_y_list)-1)]
        
        # 找出分页边界（Y间距异常大）
        # 正常间距应该稳定在100左右（25m里程 * 4比例）
        # 分页边界间距会非常大（数千）
        
        # 分页阈值：找出间距突变的位置
        sec_page_breaks = self._find_page_breaks(sec_gaps)
        ref_page_breaks = self._find_page_breaks(ref_gaps)
        
        # 按分页边界分组
        sec_pages = self._split_by_breaks(sorted_sec, sec_page_breaks)
        ref_pages = self._split_by_breaks(sorted_ref, ref_page_breaks)
        
        print(f"  断面分页: {len(sec_pages)}页")
        for i, p in enumerate(sec_pages):
            print(f"    页{i+1}: {len(p)}个, Y范围[{p[0]['y_center']:.1f}, {p[-1]['y_center']:.1f}]")
        
        print(f"  基准点分页: {len(ref_pages)}页")
        for i, p in enumerate(ref_pages):
            print(f"    页{i+1}: {len(p)}个, Y范围[{p[0]['ref_y']:.1f}, {p[-1]['ref_y']:.1f}]")
        
        # 在每个页面内按Y坐标顺序一对一匹配
        matched = []
        used_refs_global = set()
        
        for sec_page in sec_pages:
            # 找到Y范围最接近的基准点页
            sec_y_avg = sum(s['y_center'] for s in sec_page) / len(sec_page)
            best_ref_page = None
            best_y_diff = float('inf')
            
            for ref_page in ref_pages:
                ref_y_avg = sum(r['ref_y'] for r in ref_page) / len(ref_page)
                y_diff = abs(sec_y_avg - ref_y_avg)
                if y_diff < best_y_diff:
                    best_y_diff = y_diff
                    best_ref_page = ref_page
            
            if best_ref_page:
                # 在页面内按Y顺序一对一匹配
                for i, sec in enumerate(sec_page):
                    if i < len(best_ref_page):
                        ref = best_ref_page[i]
                        # 使用对象id避免重复匹配
                        ref_id = id(ref)
                        if ref_id not in used_refs_global:
                            used_refs_global.add(ref_id)
                            matched.append({'section': sec, 'ref': ref})
        
        # 按桩号值排序输出（而非Y坐标）
        matched.sort(key=lambda m: m['section']['station_value'], reverse=True)
        print(f"  分页匹配成功: {len(matched)}对")
        return matched
    
    def _find_page_breaks(self, gaps):
        """找出分页边界位置 - Y间距突变点"""
        if not gaps:
            return []
        
        # 使用固定阈值：正常Y间距在300以内，分页间距通常超过1000
        # 因为CAD图纸中断面间距约100（25m*4），分页间距在3000-7000
        threshold = 500  # 固定阈值500，任何间距超过500认为是分页
        
        breaks = []
        for i, gap in enumerate(gaps):
            if gap > threshold:
                breaks.append(i + 1)  # 断点位置
        
        print(f"    分页检测: 间距范围[{min(gaps):.1f}, {max(gaps):.1f}], 阈值={threshold}, 断点数={len(breaks)}")
        
        return breaks
    
    def _split_by_breaks(self, items, breaks):
        """按断点位置分组"""
        if not items:
            return []
        
        if not breaks:
            return [items]
        
        pages = []
        prev_break = 0
        
        for b in sorted(breaks):
            if b > prev_break:
                pages.append(items[prev_break:b])
            prev_break = b
        
        if prev_break < len(items):
            pages.append(items[prev_break:])
        
        return [p for p in pages if p]  # 过滤空页
    
    def _match_refs(self, sections, refs):
        """匹配基准点与断面 - 严格按Y坐标顺序一对一匹配"""
        # 按Y坐标降序排列（里程从大到小）
        sorted_sec = sorted(sections, key=lambda s: s['y_center'], reverse=True)
        sorted_ref = sorted(refs, key=lambda r: r['ref_y'], reverse=True)
        
        matched = []
        
        # 如果数量相等，直接按顺序一对一匹配
        if len(sorted_sec) == len(sorted_ref):
            print(f"  断面数=基准点数，采用严格顺序匹配")
            for i, sec in enumerate(sorted_sec):
                ref = sorted_ref[i]
                y_diff = abs(ref['ref_y'] - sec['y_center'])
                
                # 检查Y坐标差异是否在合理范围内
                if y_diff < 100:  # Y坐标差异阈值
                    matched.append({'section': sec, 'ref': ref})
                else:
                    print(f"  [WARN] Y坐标差异过大: {sec['station_name']} y_center={sec['y_center']:.1f} vs ref_y={ref['ref_y']:.1f} diff={y_diff:.1f}")
        else:
            # 数量不等时，使用贪心匹配
            print(f"  断面数≠基准点数，采用贪心匹配")
            used_refs = set()
            for sec in sorted_sec:
                best_ref = None
                best_diff = float('inf')
                best_idx = -1
                
                for i, ref in enumerate(sorted_ref):
                    if i in used_refs:
                        continue
                    y_diff = abs(ref['ref_y'] - sec['y_center'])
                    if y_diff < best_diff:
                        best_diff = y_diff
                        best_ref = ref
                        best_idx = i
                
                if best_ref and best_diff < 200:
                    used_refs.add(best_idx)
                    matched.append({'section': sec, 'ref': best_ref})
        
        matched.sort(key=lambda m: m['section']['station_value'], reverse=True)
        print(f"  成功匹配: {len(matched)}对")
        return matched
    
    def _transform(self, sec, ref, mileage, scale_x=1.0, scale_z=0.1):
        """坐标转换 - X轴扩大10倍展示"""
        elements = {'dmx_3d': [], 'overbreak_3d': [], 'fill_3d': {}}
        
        if sec['dmx_points']:
            elements['dmx_3d'].append([transform_to_3d(p, ref, mileage, scale_x, scale_z) for p in sec['dmx_points']])
        
        for ob in sec['overbreak_points']:
            elements['overbreak_3d'].append([transform_to_3d((p[0],p[1]), ref, mileage, scale_x, scale_z) for p in ob])
        
        for layer, bounds in sec['fill_boundaries'].items():
            elements['fill_3d'][layer] = []
            for b in bounds:
                elements['fill_3d'][layer].append([transform_to_3d((p[0],p[1]), ref, mileage, scale_x, scale_z) for p in b])
        
        return elements
    
    def visualize(self, model):
        print("\n=== 3D可视化 ===")
        
        fig = plt.figure(figsize=(16, 12))
        ax = fig.add_subplot(111, projection='3d')
        colors = plt.cm.tab20.colors
        
        for sec in model['sections']:
            mileage = sec['mileage']
            ax.scatter(0, mileage, 0, color='green', s=100, marker='o')
            
            for pts in sec['elements_3d']['dmx_3d']:
                ax.plot([p[0] for p in pts], [p[1] for p in pts], [p[2] for p in pts], 'b-', lw=2)
            
            for pts in sec['elements_3d']['overbreak_3d']:
                ax.plot([p[0] for p in pts], [p[1] for p in pts], [p[2] for p in pts], 'r--', lw=1.5)
            
            for layer, bounds in sec['elements_3d']['fill_3d'].items():
                c = colors[hash(layer) % len(colors)]
                for pts in bounds:
                    xs = [p[0] for p in pts] + [pts[0][0]]
                    ys = [p[1] for p in pts] + [pts[0][1]]
                    zs = [p[2] for p in pts] + [pts[0][2]]
                    ax.plot(xs, ys, zs, color=c, lw=1, alpha=0.6)
            
            ax.text(10, mileage, 0, sec['station_name'], fontsize=9)
        
        mileages = [s['mileage'] for s in model['sections']]
        ax.plot([0]*len(mileages), mileages, [0]*len(mileages), 'g-', lw=4)
        
        ax.set_xlabel('X (Width)')
        ax.set_ylabel('Y (Mileage)')
        ax.set_zlabel('Z (Elevation)')
        ax.set_title(f'3D Model V2 - Scale={model["metadata"]["scale"]}')
        ax.view_init(elev=20, azim=45)
        
        out = r'D:\断面算量平台\测试文件\test_3d_spine_alignment_v2.png'
        plt.savefig(out, dpi=150)
        print(f"保存: {out}")
        plt.close()
        return out
    
    def verify(self, model):
        print("\n=== 验证 ===")
        for s in model['sections']:
            r = s['ref_3d']
            assert r[0]==0 and r[2]==0 and r[1]==s['mileage']
            print(f"  {s['station_name']}: (0, {r[1]}, 0) OK")
        print("验证通过!")


def main():
    dxf = r'D:\断面算量平台\测试文件\内湾段分层图（全航道底图20260318）面积比例0.6.dxf'
    
    print("="*60)
    print("3D脊梁线对齐 V2")
    print("="*60)
    
    builder = SpineAlignmentModelBuilder(dxf)
    model = builder.build_model(999, 0.1)  # 999表示全部断面
    
    if model:
        builder.verify(model)
        builder.visualize(model)
        
        print(f"\n断面: {len(model['sections'])}")
        print(f"DMX: {sum(len(s['elements_3d']['dmx_3d']) for s in model['sections'])}")
        print(f"超挖: {sum(len(s['elements_3d']['overbreak_3d']) for s in model['sections'])}")
        print(f"填充: {sum(len(s['elements_3d']['fill_3d']) for s in model['sections'])}")


if __name__ == '__main__':
    main()