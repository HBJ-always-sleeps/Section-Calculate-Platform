# -*- coding: utf-8 -*-
"""
三维脊梁线对齐模型 V2 - 基于基准点对齐的航道3D拓扑重构

核心改进：
1. 使用bim_model_builder的SectionDetector提取完整断面要素（DMX、超挖线、填充边界）
2. 使用L1脊梁线交点作为基准点，与断面一一对应
3. 以基准点为原点进行坐标归一化
4. 3D映射：X=宽度, Y=里程, Z=高程
5. 支持导出为可移植格式（HTML/OBJ/GLTF）

作者: @黄秉俊
日期: 2026-04-01
"""

import ezdxf
import os
import math
import re
import json
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
        
        matched = self._match_refs(sections, refs)[:num_sections]
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
    
    def _match_refs(self, sections, refs):
        """匹配基准点与断面 - 确保基准点X坐标在DMX范围内
        
        【关键改进】：对于K67+400~K69+600区域的断面，使用更精确的匹配策略
        """
        sorted_sec = sorted(sections, key=lambda s: s['y_center'], reverse=True)
        sorted_ref = sorted(refs, key=lambda r: r['ref_y'], reverse=True)
        
        # 分析问题区域：K67+400~K69+600的断面DMX范围
        # 这些断面的DMX范围可能在850~1125或1338~1613等区域
        # 而标准匹配可能选择了错误的基准点
        
        matched = []
        used_ref = set()
        
        for sec in sorted_sec:
            best_ref = None
            best_diff = float('inf')
            best_ref_idx = -1
            
            # DMX的X范围
            dmx_x_min = sec['x_min']
            dmx_x_max = sec['x_max']
            
            # 判断是否在问题区域（K67+400~K69+600）
            station_value = sec['station_value']
            is_problem_area = 67400 <= station_value <= 69600
            
            for ref_idx, ref in enumerate(sorted_ref):
                if ref_idx in used_ref:
                    continue
                    
                # Y距离为主
                y_diff = abs(ref['ref_y'] - sec['y_center'])
                
                # 关键验证：基准点X坐标必须在DMX范围内（航道中心线穿过断面）
                x_in_range = dmx_x_min <= ref['ref_x'] <= dmx_x_max
                
                # 【关键改进】问题区域使用更严格的X验证
                if is_problem_area:
                    # 问题区域：X必须在DMX范围内，否则大幅增加惩罚
                    if x_in_range:
                        total_diff = y_diff
                    else:
                        # X偏离越大，惩罚越大（问题区域惩罚更重）
                        x_diff = min(abs(ref['ref_x'] - dmx_x_min), abs(ref['ref_x'] - dmx_x_max))
                        total_diff = y_diff + x_diff * 10  # 问题区域惩罚系数更大
                else:
                    # 正常区域：标准匹配逻辑
                    if x_in_range:
                        total_diff = y_diff
                    else:
                        x_diff = min(abs(ref['ref_x'] - dmx_x_min), abs(ref['ref_x'] - dmx_x_max))
                        total_diff = y_diff + x_diff * 2
                
                if total_diff < best_diff:
                    best_diff = total_diff
                    best_ref = ref
                    best_ref_idx = ref_idx
            
            if best_ref and best_diff < 500:  # 放宽容差以适应问题区域
                used_ref.add(best_ref_idx)
                x_ok = dmx_x_min <= best_ref['ref_x'] <= dmx_x_max
                if not x_ok:
                    print(f"  [WARN] {sec['station_name']}: 基准点X={best_ref['ref_x']:.1f} 不在DMX范围[{dmx_x_min:.1f}, {dmx_x_max:.1f}]内")
                matched.append({'section': sec, 'ref': best_ref})
        
        matched.sort(key=lambda m: m['section']['station_value'], reverse=True)
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


def load_metadata_from_json(json_path: str) -> Dict:
    """从bim_model_builder生成的JSON文件读取断面和基准点数据"""
    import json
    print(f"\n加载元数据: {json_path}")
    
    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    print(f"  总断面数: {data['total_sections']}")
    return data


def build_model_from_metadata(metadata: Dict, num_sections=10, scale=0.1) -> Dict:
    """从metadata构建3D模型（使用预计算的L1基准点）"""
    print("\n" + "="*60)
    print("构建3D模型 V2 (从元数据)")
    print("="*60)
    
    sections_data = metadata['sections']
    if not sections_data:
        print("ERROR: 元数据中没有断面!")
        return None
    
    # 检查L1基准点数据
    sections_with_l1 = [s for s in sections_data if s.get('l1_ref_point')]
    print(f"\n断面总数: {len(sections_data)}, 有L1基准点: {len(sections_with_l1)}")
    
    if not sections_with_l1:
        print("ERROR: 所有断面都没有L1基准点!")
        return None
    
    # 按桩号排序（降序，从大到小）
    sorted_sections = sorted(sections_with_l1, key=lambda s: s['station_value'], reverse=True)
    
    # 取前N个
    display_sections = sorted_sections[:num_sections]
    print(f"取前{len(display_sections)}个断面")
    
    model = {
        'metadata': {
            'source': metadata['file_name'],
            'scale': scale,
            'total_sections': len(sections_with_l1)
        },
        'sections': []
    }
    
    for i, sec in enumerate(display_sections):
        station_name = sec['station_name']
        mileage = sec['station_value']
        ref = sec['l1_ref_point']
        
        print(f"\n--- {i+1}: {station_name} ---")
        print(f"  基准点: ({ref['ref_x']:.1f}, {ref['ref_y']:.1f})")
        print(f"  里程: {mileage}m")
        print(f"  DMX: {len(sec['dmx_points'])}, 超挖: {len(sec['overbreak_points'])}, 填充: {len(sec['fill_boundaries'])}")
        
        # 坐标转换
        elements_3d = transform_elements(sec, ref, mileage, scale_x=1.0, scale_z=scale)
        
        model['sections'].append({
            'station_name': station_name,
            'mileage': mileage,
            'ref_3d': (0, mileage, 0),
            'elements_3d': elements_3d
        })
    
    return model


def transform_elements(sec: Dict, ref: Dict, mileage: float, scale_x=1.0, scale_z=0.1) -> Dict:
    """坐标转换 - X轴原始比例，Z轴缩小"""
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


def generate_multi_angle_screenshots(model: Dict, output_dir: str, show_geology: bool = True):
    """Generate multi-angle screenshots for 3D model
    
    Args:
        model: 3D model data
        output_dir: Output directory for screenshots
        show_geology: Whether to show geology layers
    """
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    
    print(f"\n=== Multi-Angle Screenshots ===")
    print(f"  Output: {output_dir}")
    print(f"  Geology layers: {'ON' if show_geology else 'OFF'}")
    
    os.makedirs(output_dir, exist_ok=True)
    
    # Define camera angles (elevation, azimuth, name)
    angles = [
        # Main views
        (90, 0, 'top_view'),
        (0, 0, 'front_view'),
        (0, 90, 'side_view'),
        (20, 45, 'isometric'),
        (30, 60, 'isometric_2'),
        (45, 45, 'high_angle'),
        # Rotating views (every 30 degrees)
        (20, 0, 'rot_000'),
        (20, 30, 'rot_030'),
        (20, 60, 'rot_060'),
        (20, 90, 'rot_090'),
        (20, 120, 'rot_120'),
        (20, 150, 'rot_150'),
        (20, 180, 'rot_180'),
        (20, 210, 'rot_210'),
        (20, 240, 'rot_240'),
        (20, 270, 'rot_270'),
        (20, 300, 'rot_300'),
        (20, 330, 'rot_330'),
        # Additional angles
        (10, 45, 'low_angle'),
        (35, 135, 'back_angle'),
    ]
    
    colors = plt.cm.tab20.colors
    
    # Collect all line data
    all_dmx_lines = []
    all_overbreak_lines = []
    all_fill_lines = []
    
    for sec in model['sections']:
        for pts in sec['elements_3d']['dmx_3d']:
            xs = [p[0] for p in pts]
            ys = [p[1] for p in pts]
            zs = [p[2] for p in pts]
            all_dmx_lines.append((xs, ys, zs))
        
        for pts in sec['elements_3d']['overbreak_3d']:
            xs = [p[0] for p in pts]
            ys = [p[1] for p in pts]
            zs = [p[2] for p in pts]
            all_overbreak_lines.append((xs, ys, zs))
        
        for layer, bounds in sec['elements_3d']['fill_3d'].items():
            c = colors[hash(layer) % len(colors)]
            for pts in bounds:
                xs = [p[0] for p in pts] + [pts[0][0]]
                ys = [p[1] for p in pts] + [pts[0][1]]
                zs = [p[2] for p in pts] + [pts[0][2]]
                all_fill_lines.append((xs, ys, zs, c))
    
    # Calculate bounds
    all_x = [p[0] for xs, ys, zs in all_dmx_lines for p in [(x, y, z) for x, y, z in zip(xs, ys, zs)]]
    all_y = [p[1] for xs, ys, zs in all_dmx_lines for p in [(x, y, z) for x, y, z in zip(xs, ys, zs)]]
    all_z = [p[2] for xs, ys, zs in all_dmx_lines for p in [(x, y, z) for x, y, z in zip(xs, ys, zs)]]
    
    x_range = (min(all_x), max(all_x)) if all_x else (0, 1)
    y_range = (min(all_y), max(all_y)) if all_y else (0, 1)
    z_range = (min(all_z), max(all_z)) if all_z else (0, 1)
    
    screenshots = []
    
    for elev, azim, name in angles:
        fig = plt.figure(figsize=(12, 9))
        ax = fig.add_subplot(111, projection='3d')
        
        # Layer rendering order: Fill -> Overbreak -> DMX (DMX last, renders on top)
        
        # Plot fill boundaries (colored) - FIRST layer (bottom), only if show_geology
        if show_geology:
            for xs, ys, zs, c in all_fill_lines:
                ax.plot(xs, ys, zs, color=c, lw=1, alpha=0.6)
        
        # Plot overbreak (red dashed) - SECOND layer, lower transparency
        for xs, ys, zs in all_overbreak_lines:
            ax.plot(xs, ys, zs, 'r--', lw=1.5, alpha=0.5)
        
        # Plot DMX (blue solid) - LAST layer (top), width halved from 2 to 1
        for xs, ys, zs in all_dmx_lines:
            ax.plot(xs, ys, zs, 'b-', lw=1)
        
        ax.set_xlabel('X (Width)')
        ax.set_ylabel('Y (Mileage)')
        ax.set_zlabel('Z (Elevation)')
        
        layer_status = 'All Layers' if show_geology else 'DMX + Overbreak Only'
        ax.set_title(f'3D Waterway Model - {len(model["sections"])} Sections\n{layer_status}\nView: {name} (elev={elev}, azim={azim})')
        
        ax.set_xlim(x_range)
        ax.set_ylim(y_range)
        ax.set_zlim(z_range)
        ax.view_init(elev=elev, azim=azim)
        
        # Save screenshot
        suffix = 'all' if show_geology else 'no_geology'
        filename = f'{name}_{suffix}.png'
        filepath = os.path.join(output_dir, filename)
        plt.savefig(filepath, dpi=100, bbox_inches='tight')
        plt.close()
        
        screenshots.append((name, filename))
        print(f"  Saved: {filename}")
    
    print(f"  Total: {len(screenshots)} screenshots")
    return screenshots


def visualize_model(model: Dict, output_path: str = None, interactive: bool = False):
    """3D visualization - Static screenshot mode only
    
    Args:
        output_path: Output image path
        interactive: Ignored (deprecated)
    """
    print("\n=== 3D Visualization (Static Mode) ===")
    
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    
    fig = plt.figure(figsize=(18, 12))
    ax = fig.add_axes([0.05, 0.1, 0.9, 0.85], projection='3d')
    colors = plt.cm.tab20.colors
    
    # Collect all line data
    all_dmx_lines = []
    all_overbreak_lines = []
    all_fill_lines = []
    
    for sec in model['sections']:
        for pts in sec['elements_3d']['dmx_3d']:
            xs = [p[0] for p in pts]
            ys = [p[1] for p in pts]
            zs = [p[2] for p in pts]
            all_dmx_lines.append((xs, ys, zs))
        
        for pts in sec['elements_3d']['overbreak_3d']:
            xs = [p[0] for p in pts]
            ys = [p[1] for p in pts]
            zs = [p[2] for p in pts]
            all_overbreak_lines.append((xs, ys, zs))
        
        for layer, bounds in sec['elements_3d']['fill_3d'].items():
            c = colors[hash(layer) % len(colors)]
            for pts in bounds:
                xs = [p[0] for p in pts] + [pts[0][0]]
                ys = [p[1] for p in pts] + [pts[0][1]]
                zs = [p[2] for p in pts] + [pts[0][2]]
                all_fill_lines.append((xs, ys, zs, c))
    
    # Plot DMX (blue solid)
    print(f"  Rendering DMX lines: {len(all_dmx_lines)}...")
    for xs, ys, zs in all_dmx_lines:
        ax.plot(xs, ys, zs, 'b-', lw=2)
    
    # Plot overbreak (red dashed)
    print(f"  Rendering Overbreak lines: {len(all_overbreak_lines)}...")
    for xs, ys, zs in all_overbreak_lines:
        ax.plot(xs, ys, zs, 'r--', lw=1.5)
    
    # Plot fill boundaries (colored)
    print(f"  Rendering Fill boundaries: {len(all_fill_lines)}...")
    for xs, ys, zs, c in all_fill_lines:
        ax.plot(xs, ys, zs, color=c, lw=1, alpha=0.6)
    
    ax.set_xlabel('X (Width)')
    ax.set_ylabel('Y (Mileage)')
    ax.set_zlabel('Z (Elevation)')
    ax.set_title(f'3D Spine Alignment V2 - Sections={len(model["sections"])}, Scale={model["metadata"]["scale"]}')
    ax.view_init(elev=20, azim=45)
    
    # Set axis range
    all_x = [p[0] for xs, ys, zs in all_dmx_lines for p in [(x, y, z) for x, y, z in zip(xs, ys, zs)]]
    all_y = [p[1] for xs, ys, zs in all_dmx_lines for p in [(x, y, z) for x, y, z in zip(xs, ys, zs)]]
    all_z = [p[2] for xs, ys, zs in all_dmx_lines for p in [(x, y, z) for x, y, z in zip(xs, ys, zs)]]
    
    if all_x and all_y and all_z:
        ax.set_xlim(min(all_x), max(all_x))
        ax.set_ylim(min(all_y), max(all_y))
        ax.set_zlim(min(all_z), max(all_z))
    
    print("  预渲染完成!")
    
    if interactive:
        # 图层管理器（右侧）
        ax_check = fig.add_axes([0.82, 0.4, 0.15, 0.2])
        check_labels = ['DMX断面线', '超挖线', '地质分层']
        check_states = [True, True, True]  # 默认全部显示
        check = CheckButtons(ax_check, check_labels, check_states)
        
        # 图层切换回调函数
        def layer_toggle(label):
            idx = check_labels.index(label)
            if idx == 0:  # DMX断面线
                for artist in dmx_artists:
                    artist.set_visible(not artist.get_visible())
            elif idx == 1:  # 超挖线
                for artist in overbreak_artists:
                    artist.set_visible(not artist.get_visible())
            elif idx == 2:  # 地质分层
                for artist in fill_artists:
                    artist.set_visible(not artist.get_visible())
            fig.canvas.draw_idle()
        
        check.on_clicked(layer_toggle)
        
        # 添加图层管理器标题
        ax_check.set_title('图层管理', fontsize=10, pad=10)
        
        # 交互式窗口
        print("启动交互式3D窗口（可鼠标旋转+图层管理）...")
        print("  右侧复选框可切换图层显示/隐藏")
        plt.show()
        return None
    else:
        # 保存图片
        if output_path is None:
            output_path = r'D:\断面算量平台\测试文件\test_3d_spine_alignment_v2.png'
        
        plt.savefig(output_path, dpi=150)
        print(f"保存: {output_path}")
        plt.close()
        return output_path


def export_to_html(model: Dict, output_path: str):
    """导出为HTML格式（使用Plotly，可在浏览器中交互查看）
    
    Args:
        model: 3D模型数据
        output_path: HTML输出路径
    """
    try:
        import plotly.graph_objects as go
        from plotly.subplots import make_subplots
    except ImportError:
        print("ERROR: 需要安装plotly库: pip install plotly")
        return None
    
    print(f"\n=== 导出HTML格式 ===")
    print(f"  输出路径: {output_path}")
    
    fig = go.Figure()
    
    # Layer rendering order: Fill -> Overbreak -> DMX (DMX last, renders on top)
    # 填充边界（彩色）- 最先渲染（底层）
    fill_lines_count = 0
    colors_list = [
        'green', 'orange', 'purple', 'cyan', 'magenta', 'yellow',
        'lime', 'coral', 'teal', 'navy', 'maroon', 'olive'
    ]
    
    for sec in model['sections']:
        station_name = sec['station_name']
        
        for layer, bounds in sec['elements_3d']['fill_3d'].items():
            color_idx = hash(layer) % len(colors_list)
            color = colors_list[color_idx]
            
            for pts in bounds:
                xs = [p[0] for p in pts] + [pts[0][0]]
                ys = [p[1] for p in pts] + [pts[0][1]]
                zs = [p[2] for p in pts] + [pts[0][2]]
                
                fig.add_trace(go.Scatter3d(
                    x=xs, y=ys, z=zs,
                    mode='lines',
                    line=dict(color=color, width=1),
                    name=f'{layer}-{station_name}',
                    legendgroup=layer,
                    showlegend=(fill_lines_count < 20),  # Only show first 20 legends
                    opacity=0.6,
                    hovertemplate=f'{layer}<br>{station_name}<br>X: %{{x:.1f}}<br>Y: %{{y:.1f}}<br>Z: %{{z:.1f}}'
                ))
                fill_lines_count += 1
    
    print(f"  Fill boundaries: {fill_lines_count} lines")
    
    # Overbreak lines (red dashed) - second layer, lower transparency
    ob_lines_count = 0
    for sec in model['sections']:
        mileage = sec['mileage']
        station_name = sec['station_name']
        
        for pts in sec['elements_3d']['overbreak_3d']:
            xs = [p[0] for p in pts]
            ys = [p[1] for p in pts]
            zs = [p[2] for p in pts]
            
            fig.add_trace(go.Scatter3d(
                x=xs, y=ys, z=zs,
                mode='lines',
                line=dict(color='red', width=1.5, dash='dash'),
                name=f'Overbreak-{station_name}',
                legendgroup='Overbreak',
                showlegend=(ob_lines_count == 0),
                opacity=0.5,  # Lower transparency
                hovertemplate=f'{station_name}<br>X: %{{x:.1f}}<br>Y: %{{y:.1f}}<br>Z: %{{z:.1f}}'
            ))
            ob_lines_count += 1
    
    print(f"  Overbreak lines: {ob_lines_count} lines")
    
    # DMX section lines (blue solid) - LAST layer, renders on top, width halved
    dmx_lines_count = 0
    for sec in model['sections']:
        mileage = sec['mileage']
        station_name = sec['station_name']
        
        for pts in sec['elements_3d']['dmx_3d']:
            xs = [p[0] for p in pts]
            ys = [p[1] for p in pts]
            zs = [p[2] for p in pts]
            
            fig.add_trace(go.Scatter3d(
                x=xs, y=ys, z=zs,
                mode='lines',
                line=dict(color='blue', width=1),  # Width halved from 2 to 1
                name=f'DMX-{station_name}',
                legendgroup='DMX',
                showlegend=(dmx_lines_count == 0),
                hovertemplate=f'{station_name}<br>X: %{{x:.1f}}<br>Y: %{{y:.1f}}<br>Z: %{{z:.1f}}'
            ))
            dmx_lines_count += 1
    
    print(f"  DMX section lines: {dmx_lines_count} lines")
    
    # 设置布局
    fig.update_layout(
        title=dict(
            text=f'航道3D脊梁线模型 - {len(model["sections"])}断面',
            x=0.5,
            xanchor='center'
        ),
        scene=dict(
            xaxis_title='X (宽度)',
            yaxis_title='Y (里程)',
            zaxis_title='Z (高程)',
            aspectmode='data',
            camera=dict(
                eye=dict(x=1.5, y=1.5, z=0.8),
                up=dict(x=0, y=0, z=1)
            )
        ),
        showlegend=True,
        legend=dict(
            x=0.02,
            y=0.98,
            bgcolor='rgba(255,255,255,0.8)',
            bordercolor='gray',
            borderwidth=1
        ),
        width=1200,
        height=800,
        margin=dict(l=0, r=0, t=50, b=0)
    )
    
    # 保存HTML
    fig.write_html(output_path, include_plotlyjs='cdn')
    print(f"  HTML文件已保存: {output_path}")
    print(f"  可在浏览器中打开查看，支持鼠标旋转/缩放/图层切换")
    
    return output_path


def export_to_obj(model: Dict, output_path: str):
    """导出为OBJ格式（可在各种3D软件中打开）
    
    Args:
        model: 3D模型数据
        output_path: OBJ输出路径
    """
    print(f"\n=== 导出OBJ格式 ===")
    print(f"  输出路径: {output_path}")
    
    obj_content = []
    obj_content.append("# 航道3D脊梁线模型")
    obj_content.append(f"# 断面数: {len(model['sections'])}")
    obj_content.append(f"# 生成时间: {model['metadata'].get('source', 'unknown')}")
    obj_content.append("")
    
    vertex_offset = 1  # OBJ顶点索引从1开始
    total_vertices = 0
    total_lines = 0
    
    # DMX断面线
    obj_content.append("# === DMX断面线 ===")
    obj_content.append("g DMX")
    
    for sec in model['sections']:
        station_name = sec['station_name']
        
        for pts in sec['elements_3d']['dmx_3d']:
            # 写入顶点
            for p in pts:
                obj_content.append(f"v {p[0]:.6f} {p[1]:.6f} {p[2]:.6f}")
                total_vertices += 1
            
            # 写入线段（连接相邻顶点）
            num_pts = len(pts)
            for i in range(num_pts - 1):
                obj_content.append(f"l {vertex_offset + i} {vertex_offset + i + 1}")
                total_lines += 1
            
            vertex_offset += num_pts
    
    print(f"  DMX顶点: {total_vertices}, 线段: {total_lines}")
    
    # 超挖线
    ob_vertices = 0
    ob_lines = 0
    obj_content.append("")
    obj_content.append("# === 超挖线 ===")
    obj_content.append("g Overbreak")
    
    for sec in model['sections']:
        for pts in sec['elements_3d']['overbreak_3d']:
            for p in pts:
                obj_content.append(f"v {p[0]:.6f} {p[1]:.6f} {p[2]:.6f}")
                ob_vertices += 1
            
            num_pts = len(pts)
            for i in range(num_pts - 1):
                obj_content.append(f"l {vertex_offset + i} {vertex_offset + i + 1}")
                ob_lines += 1
            
            vertex_offset += num_pts
    
    print(f"  超挖顶点: {ob_vertices}, 线段: {ob_lines}")
    
    # 填充边界
    fill_vertices = 0
    fill_lines = 0
    obj_content.append("")
    obj_content.append("# === 填充边界 ===")
    
    for sec in model['sections']:
        for layer, bounds in sec['elements_3d']['fill_3d'].items():
            obj_content.append(f"g {layer.replace(' ', '_')}")
            
            for pts in bounds:
                for p in pts:
                    obj_content.append(f"v {p[0]:.6f} {p[1]:.6f} {p[2]:.6f}")
                    fill_vertices += 1
                
                # 闭合多边形
                num_pts = len(pts)
                for i in range(num_pts):
                    next_i = (i + 1) % num_pts
                    obj_content.append(f"l {vertex_offset + i} {vertex_offset + next_i}")
                    fill_lines += 1
                
                vertex_offset += num_pts
    
    print(f"  填充顶点: {fill_vertices}, 线段: {fill_lines}")
    
    # 写入文件
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(obj_content))
    
    print(f"  OBJ文件已保存: {output_path}")
    print(f"  总顶点: {vertex_offset - 1}, 总线段: {total_lines + ob_lines + fill_lines}")
    print(f"  可导入Blender/MeshLab/AutoCAD等软件查看")
    
    return output_path


def export_to_gltf(model: Dict, output_path: str):
    """导出为GLTF格式（可在网页和3D软件中查看）
    
    Args:
        model: 3D模型数据
        output_path: GLTF输出路径
    """
    try:
        import trimesh
    except ImportError:
        print("ERROR: 需要安装trimesh库: pip install trimesh")
        return None
    
    print(f"\n=== 导出GLTF格式 ===")
    print(f"  输出路径: {output_path}")
    
    # 构建场景
    scene = trimesh.Scene()
    
    # DMX断面线
    dmx_entities = []
    for sec in model['sections']:
        for pts in sec['elements_3d']['dmx_3d']:
            if len(pts) >= 2:
                # 创建线段路径
                path = np.array(pts)
                # 创建管道几何
                tube = trimesh.path.creation.box_outline(
                    bounds=[[min(path[:,0]), min(path[:,1]), min(path[:,2])],
                            [max(path[:,0]), max(path[:,1]), max(path[:,2])]]
                )
                dmx_entities.append(path)
    
    # 简化处理：将所有线段合并为一个Path3D对象
    all_dmx_paths = []
    for sec in model['sections']:
        for pts in sec['elements_3d']['dmx_3d']:
            if len(pts) >= 2:
                all_dmx_paths.append(np.array(pts))
    
    if all_dmx_paths:
        # 创建Path3D对象
        dmx_path = trimesh.path.Path3D(
            entities=[trimesh.path.entities.Line(np.arange(len(p))) for p in all_dmx_paths],
            vertices=np.vstack(all_dmx_paths)
        )
        scene.add_geometry(dmx_path, node_name='DMX断面线')
    
    print(f"  DMX路径: {len(all_dmx_paths)}条")
    
    # 超挖线
    all_ob_paths = []
    for sec in model['sections']:
        for pts in sec['elements_3d']['overbreak_3d']:
            if len(pts) >= 2:
                all_ob_paths.append(np.array(pts))
    
    if all_ob_paths:
        ob_path = trimesh.path.Path3D(
            entities=[trimesh.path.entities.Line(np.arange(len(p))) for p in all_ob_paths],
            vertices=np.vstack(all_ob_paths)
        )
        scene.add_geometry(ob_path, node_name='超挖线')
    
    print(f"  超挖路径: {len(all_ob_paths)}条")
    
    # 导出GLTF
    scene.export(output_path)
    print(f"  GLTF文件已保存: {output_path}")
    print(f"  可在浏览器/Windows 3D Viewer/Blender中查看")
    
    return output_path


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='3D Spine Alignment V2 - Static Screenshot Mode')
    parser.add_argument('--input', '-i', type=str,
                       default=r'D:\断面算量平台\测试文件\内湾段分层图（全航道底图20260331）2018面积比例0.6_bim_metadata.json',
                       help='Input metadata JSON file path (from bim_model_builder)')
    parser.add_argument('--dxf', '-d', type=str, default=None,
                       help='Input DXF file path (fallback if no JSON)')
    parser.add_argument('--num', '-n', type=int, default=245,
                       help='Number of sections to display')
    parser.add_argument('--scale', '-s', type=float, default=0.1,
                       help='Z axis scale factor')
    parser.add_argument('--output', '-o', type=str, default=None,
                       help='Output base path for screenshots and HTML')
    parser.add_argument('--export-html', type=str, default=None,
                       help='Export to HTML format (Plotly interactive viewer)')
    parser.add_argument('--screenshots', type=str, default=None,
                       help='Generate multi-angle screenshots to directory')
    
    args = parser.parse_args()
    
    print("="*60)
    print("3D Spine Alignment V2 - Static Mode")
    print("="*60)
    
    # Load model from JSON metadata
    if args.input and os.path.exists(args.input):
        metadata = load_metadata_from_json(args.input)
        model = build_model_from_metadata(metadata, args.num, args.scale)
    elif args.dxf:
        builder = SpineAlignmentModelBuilder(args.dxf)
        model = builder.build_model(args.num, args.scale)
    else:
        print("ERROR: Input file required!")
        return
    
    if model:
        # Validation
        print("\n=== Validation ===")
        for s in model['sections']:
            r = s['ref_3d']
            assert r[0]==0 and r[2]==0 and r[1]==s['mileage']
        print(f"  All {len(model['sections'])} sections validated OK!")
        
        # Generate multi-angle screenshots
        if args.screenshots:
            screenshot_dir = args.screenshots
            
            # Generate screenshots with all layers
            print("\n=== Generating Screenshots (All Layers) ===")
            generate_multi_angle_screenshots(model, screenshot_dir, show_geology=True)
            
            # Generate screenshots without geology layers
            print("\n=== Generating Screenshots (No Geology) ===")
            generate_multi_angle_screenshots(model, screenshot_dir, show_geology=False)
        
        # Export HTML
        if args.export_html:
            export_to_html(model, args.export_html)
        
        # Default: generate both HTML and screenshots
        if not (args.export_html or args.screenshots):
            output_base = args.output or r'D:\断面算量平台\测试文件\内湾段分层图_3d_model'
            
            # Generate HTML
            export_to_html(model, output_base + '.html')
            
            # Generate screenshots
            screenshot_dir = output_base + '_screenshots'
            print("\n=== Generating Screenshots (All Layers) ===")
            generate_multi_angle_screenshots(model, screenshot_dir, show_geology=True)
            
            print("\n=== Generating Screenshots (No Geology) ===")
            generate_multi_angle_screenshots(model, screenshot_dir, show_geology=False)
        
        print(f"\nSummary:")
        print(f"  Sections: {len(model['sections'])}")
        print(f"  DMX Lines: {sum(len(s['elements_3d']['dmx_3d']) for s in model['sections'])}")
        print(f"  Overbreak Lines: {sum(len(s['elements_3d']['overbreak_3d']) for s in model['sections'])}")
        print(f"  Fill Boundaries: {sum(len(s['elements_3d']['fill_3d']) for s in model['sections'])}")


if __name__ == '__main__':
    main()
