# -*- coding: utf-8 -*-
"""
航道地质 BIM 模型构建器 V2 - 集成核心放样引擎
核心改进：
1. DMX/超挖线定义为 Surfaces（非闭合 LineString）-> Ribbon Mesh
2. 地质填充定义为 Volumes（闭合 Polygon）-> Volume Mesh
3. 使用重心追踪匹配相邻断面
4. 地层消失时平滑退化（Tapering）

作者: @黄秉俊
日期: 2026-03-30
"""

import ezdxf
import os
import math
import re
import json
import numpy as np
from typing import List, Dict, Tuple, Optional
from shapely.geometry import Polygon, LineString, Point, box
from shapely.ops import linemerge, unary_union
from dataclasses import dataclass, field, asdict
import pyvista as pv
import matplotlib.pyplot as plt

# 设置非交互式后端（避免GUI渲染问题）
plt.switch_backend('Agg')

# 导入核心放样引擎
from bim_lofting_core import (
    BIMLoftingEngine, 
    LayerMatcher,
    GeologicalBody, 
    SectionMetadata,
    get_layer_color, 
    get_layer_opacity
)


# ==================== DXF数据提取器 ====================

class DXFDataExtractor:
    """DXF数据提取器 - 区分Surface和Volume"""
    
    def __init__(self, dxf_path: str):
        self.dxf_path = dxf_path
        self.doc = ezdxf.readfile(dxf_path)
        self.msp = self.doc.modelspace()
        self.scale_factor = 1.0
    
    def extract_all(self) -> List[SectionMetadata]:
        """提取所有断面数据"""
        print("\n=== 提取断面数据（分类模式）===")
        
        # 1. 提取DMX断面线（Surface类型）
        dmx_list = self._extract_dmx_sections()
        print(f"  DMX断面线: {len(dmx_list)}条")
        
        if not dmx_list:
            return []
        
        # 2. 检测缩放比例
        self.scale_factor = self._detect_scale_factor(dmx_list)
        print(f"  缩放比例: {self.scale_factor:.4f}")
        
        # 3. 提取桩号文本
        station_texts = self._extract_station_texts()
        print(f"  桩号文本: {len(station_texts)}个")
        
        # 4. 提取超挖线（Surface类型）
        overbreak_list = self._extract_overbreak_lines()
        print(f"  超挖线: {len(overbreak_list)}条")
        
        # 5. 提取填充边界（Volume类型）
        fill_data = self._extract_fill_boundaries()
        print(f"  填充图层: {len(fill_data)}个")
        
        # 6. 提取L1基准点
        refs = self._extract_l1_refs()
        print(f"  L1基准点: {len(refs)}个")
        
        # 7. 按桩号分组并匹配基准点
        sections = self._group_and_match(dmx_list, station_texts, overbreak_list, fill_data, refs)
        print(f"  最终断面数: {len(sections)}个")
        
        return sections
    
    def _extract_dmx_sections(self) -> List[Dict]:
        """提取DMX断面线（作为开放线条）"""
        dmx_list = []
        
        for e in self.msp.query('LWPOLYLINE[layer=="DMX"]'):
            try:
                pts = [(p[0], p[1]) for p in e.get_points()]
                if len(pts) >= 2:
                    # 不闭合！作为开放线条处理
                    x_coords = [p[0] for p in pts]
                    y_coords = [p[1] for p in pts]
                    
                    # 合并相邻线段（如果有多条）
                    line = LineString(pts)
                    
                    dmx_list.append({
                        'pts': pts,
                        'line': line,
                        'x_min': min(x_coords),
                        'x_max': max(x_coords),
                        'y_min': min(y_coords),
                        'y_max': max(y_coords),
                        'y_center': (min(y_coords) + max(y_coords)) / 2,
                        'is_closed': False  # 关键：DMX不闭合
                    })
            except: pass
        
        return dmx_list
    
    def _extract_overbreak_lines(self) -> List[Dict]:
        """提取超挖线（作为开放线条）"""
        overbreak_list = []
        
        for e in self.msp.query('LWPOLYLINE[layer=="超挖线"]'):
            try:
                pts = [(p[0], p[1]) for p in e.get_points()]
                if len(pts) >= 2:
                    line = LineString(pts)
                    x_coords = [p[0] for p in pts]
                    y_coords = [p[1] for p in pts]
                    
                    overbreak_list.append({
                        'pts': pts,
                        'line': line,
                        'x_min': min(x_coords),
                        'x_max': max(x_coords),
                        'y_min': min(y_coords),
                        'y_max': max(y_coords),
                        'y_center': (min(y_coords) + max(y_coords)) / 2,
                        'is_closed': False
                    })
            except: pass
        
        return overbreak_list
    
    def _extract_fill_boundaries(self) -> Dict[str, List[Dict]]:
        """提取填充边界（作为闭合多边形）"""
        fill_data = {}
        
        for layer_name in [l.dxf.name for l in self.doc.layers]:
            # 判断是否为地层图层
            is_fill = any(kw in layer_name for kw in ['填充', '淤泥', '黏土', '砂', '碎石', '填土'])
            is_fill = is_fill or layer_name.lower().startswith('nonem')
            
            if is_fill:
                boundaries = []
                
                # 提取HATCH边界
                for h in self.msp.query(f'HATCH[layer=="{layer_name}"]'):
                    pts = self._extract_hatch_boundary(h)
                    if pts and len(pts) >= 3:
                        # 计算重心和面积
                        try:
                            poly = Polygon(pts)
                            centroid = (poly.centroid.x, poly.centroid.y)
                            area = poly.area
                        except:
                            centroid = (sum(p[0] for p in pts)/len(pts), sum(p[1] for p in pts)/len(pts))
                            area = 0
                        
                        boundaries.append({
                            'pts': pts,
                            'centroid': centroid,
                            'area': area,
                            'is_closed': True  # 关键：填充闭合
                        })
                
                # 提取多段线边界
                for e in self.msp.query(f'LWPOLYLINE[layer=="{layer_name}"]'):
                    try:
                        pts = [(p[0], p[1]) for p in e.get_points()]
                        if len(pts) >= 3:
                            # 尝试闭合
                            if not np.allclose(pts[0], pts[-1]):
                                pts.append(pts[0])
                            
                            try:
                                poly = Polygon(pts)
                                centroid = (poly.centroid.x, poly.centroid.y)
                                area = poly.area
                            except:
                                centroid = (sum(p[0] for p in pts)/len(pts), sum(p[1] for p in pts)/len(pts))
                                area = 0
                            
                            boundaries.append({
                                'pts': pts,
                                'centroid': centroid,
                                'area': area,
                                'is_closed': True
                            })
                    except: pass
                
                if boundaries:
                    fill_data[layer_name] = boundaries
        
        return fill_data
    
    def _extract_hatch_boundary(self, hatch) -> Optional[List[Tuple[float, float]]]:
        """提取HATCH边界点"""
        points = []
        try:
            for path in hatch.paths:
                if hasattr(path, 'vertices') and len(path.vertices) > 0:
                    points = [(v[0], v[1]) for v in path.vertices]
                elif hasattr(path, 'edges'):
                    for edge in path.edges:
                        if hasattr(edge, 'start'):
                            points.append((edge.start[0], edge.start[1]))
        except: pass
        return points if len(points) >= 3 else None
    
    def _extract_station_texts(self) -> List[Dict]:
        """提取桩号文本"""
        stations = []
        
        for e in self.msp.query('TEXT MTEXT'):
            try:
                txt = e.plain_text() if e.dxftype() == 'MTEXT' else e.dxf.text
                match = re.search(r'(\d+\+\d+)', txt.upper())
                if match:
                    pt = self._get_text_point(e)
                    sid = match.group(1)
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
    
    def _get_text_point(self, e) -> Tuple[float, float]:
        """获取文本位置"""
        try:
            if e.dxftype() == 'TEXT':
                return (e.dxf.align_point.x, e.dxf.align_point.y) if (e.dxf.halign or e.dxf.valign) else (e.dxf.insert.x, e.dxf.insert.y)
            return (e.dxf.insert.x, e.dxf.insert.y)
        except:
            return (0, 0)
    
    def _detect_scale_factor(self, dmx_list: List[Dict]) -> float:
        """检测缩放比例"""
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
            
            # 参考值
            ref_length = 200.0
            ref_gap = 100.0
            
            length_scale = avg_length / ref_length
            gap_scale = avg_gap / ref_gap
            
            scale = (length_scale + gap_scale) / 2
            scale = max(0.1, min(10.0, scale))
            
            return scale
        except:
            return 1.0
    
    def _extract_l1_refs(self) -> List[Dict]:
        """
        提取L1基准点 V4 - 按DMX断面框独立匹配
        
        核心改进：
        1. 收集所有L1线条（水平和垂直）
        2. 在_group_and_match中按每个DMX断面框独立匹配L1交点
        3. 确保每个断面都有独立的基准点
        """
        self.l1_h_lines = []  # 水平线
        self.l1_v_lines = []  # 垂直线
        
        # 收集所有L1线条
        for e in self.msp.query('*[layer=="L1"]'):
            try:
                if e.dxftype() == 'LINE':
                    x1, y1 = e.dxf.start.x, e.dxf.start.y
                    x2, y2 = e.dxf.end.x, e.dxf.end.y
                    w, h = abs(x2-x1), abs(y2-y1)
                    if w > h * 3:
                        # 水平线（脊梁线）
                        self.l1_h_lines.append({'y': (y1+y2)/2, 'x': (x1+x2)/2, 'x_min': min(x1,x2), 'x_max': max(x1,x2)})
                    elif h > w * 3:
                        # 垂直线（中心线）
                        self.l1_v_lines.append({'x': (x1+x2)/2, 'y': (y1+y2)/2, 'y_min': min(y1,y2), 'y_max': max(y1,y2)})
                elif e.dxftype() in ('LWPOLYLINE', 'POLYLINE'):
                    pts = [(p[0], p[1]) for p in e.get_points()]
                    for i in range(len(pts)-1):
                        x1, y1 = pts[i]
                        x2, y2 = pts[i+1]
                        w, h = abs(x2-x1), abs(y2-y1)
                        if w > h * 3:
                            self.l1_h_lines.append({'y': (y1+y2)/2, 'x': (x1+x2)/2, 'x_min': min(x1,x2), 'x_max': max(x1,x2)})
                        elif h > w * 3:
                            self.l1_v_lines.append({'x': (x1+x2)/2, 'y': (y1+y2)/2, 'y_min': min(y1,y2), 'y_max': max(y1,y2)})
            except: pass
        
        print(f"  L1水平线: {len(self.l1_h_lines)}条, 垂直线: {len(self.l1_v_lines)}条")
        
        # 返回空列表，实际匹配在_group_and_match中按DMX框进行
        return []
    
    def _find_l1_ref_for_dmx(self, dmx: Dict) -> Optional[Dict]:
        """
        为单个DMX断面框查找最佳L1基准点 V4
        
        核心改进：
        1. 扩大搜索范围（考虑缩放比例）
        2. 强制"最高点"原则
        3. L1点定义为3D空间的坐标原点(0,0)
        
        Args:
            dmx: DMX断面数据（包含x_min, x_max, y_min, y_max, y_center）
        
        Returns:
            {'ref_x': x, 'ref_y': y} 或 None
        """
        # 搜索范围（考虑缩放比例，扩大到200）
        search_range = 200 * self.scale_factor
        dmx_y_center = dmx['y_center']
        dmx_x_center = (dmx['x_min'] + dmx['x_max']) / 2
        
        # 1. 找Y坐标在DMX框范围内的水平线（脊梁线）
        candidate_h = [h for h in self.l1_h_lines 
                       if abs(h['y'] - dmx_y_center) < search_range]
        
        # 2. 找Y坐标在DMX框范围内的垂直线（中心线）
        candidate_v = [v for v in self.l1_v_lines 
                       if abs(v['y'] - dmx_y_center) < search_range]
        
        if not candidate_h:
            # 如果没有水平线，尝试扩大搜索
            candidate_h = [h for h in self.l1_h_lines 
                           if abs(h['y'] - dmx_y_center) < search_range * 2]
        
        if not candidate_v:
            # 如果没有垂直线，使用DMX中心X
            candidate_v = [{'x': dmx_x_center, 'y': dmx_y_center}]
        
        # 3. 【核心修复】选择Y坐标最大的水平线（最高点原则）
        # 这确保所有断面对齐到"顶边脊梁线"
        if candidate_h:
            best_h = max(candidate_h, key=lambda h: h['y'])
            best_y = best_h['y']
        else:
            # 没有L1水平线时，使用DMX最高点
            best_y = dmx['y_max']
        
        # 4. 垂直线取平均X（航道中心线）
        if candidate_v and isinstance(candidate_v[0], dict) and 'x' in candidate_v[0]:
            best_x = sum(v['x'] for v in candidate_v) / len(candidate_v)
        else:
            best_x = dmx_x_center
        
        return {'ref_x': best_x, 'ref_y': best_y}
    
    def _group_and_match(self, dmx_list, station_texts, overbreak_list, fill_data, refs) -> List[SectionMetadata]:
        """按桩号分组并匹配基准点"""
        # 匹配容差（考虑缩放比例）
        match_tolerance = 500 * self.scale_factor
        
        # 按Y排序
        sorted_stations = sorted(station_texts, key=lambda s: s['y'], reverse=True)
        sorted_dmx = sorted(dmx_list, key=lambda d: d['y_center'], reverse=True)
        
        groups = []
        used_dmx = set()
        
        # 按桩号匹配DMX
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
                dmx = sorted_dmx[best_dmx_idx]
                
                groups.append({
                    'station_name': station['text'],
                    'station_value': station['value'],
                    'dmx': dmx,
                    'y_center': dmx['y_center']
                })
        
        # 【V4改进】按DMX断面框独立匹配L1基准点
        sections = []
        ref_y_list = []  # 用于检测跳变
        
        for group in groups:
            # 为每个DMX断面独立查找L1基准点
            best_ref = self._find_l1_ref_for_dmx(group['dmx'])
            
            if best_ref:
                # 创建断面元数据
                section = self._create_section_metadata(group, best_ref, overbreak_list, fill_data)
                sections.append(section)
                ref_y_list.append(best_ref['ref_y'])
        
        # 检测ref_y跳变
        ref_y_list.sort(reverse=True)
        for i in range(len(ref_y_list)-1):
            y_diff = abs(ref_y_list[i] - ref_y_list[i+1])
            if y_diff > 200:
                print(f"  [WARNING] L1基准点Y跳变: {ref_y_list[i]:.1f} -> {ref_y_list[i+1]:.1f} (差值={y_diff:.1f})")
        
        # 按桩号排序
        sections.sort(key=lambda s: s.station_value, reverse=True)
        
        return sections
    
    def _create_section_metadata(self, group: Dict, ref: Dict, overbreak_list: List[Dict], fill_data: Dict) -> SectionMetadata:
        """创建断面元数据"""
        station_name = group['station_name']
        station_value = group['station_value']
        mileage = station_value  # Y轴使用桩号数值
        
        dmx = group['dmx']
        
        # 计算相对坐标
        ref_x, ref_y = ref['ref_x'], ref['ref_y']
        
        # 创建Surface（DMX）
        dmx_pts = [(p[0] - ref_x, p[1] - ref_y) for p in dmx['pts']]
        dmx_body = GeologicalBody(
            layer_name='DMX',
            points=dmx_pts,
            centroid=(sum(p[0] for p in dmx_pts)/len(dmx_pts), sum(p[1] for p in dmx_pts)/len(dmx_pts)),
            area=0.0,
            is_closed=False
        )
        
        surfaces = [dmx_body]
        
        # 匹配超挖线
        dmx_box = box(dmx['x_min'] - 10, dmx['y_min'] - 20, dmx['x_max'] + 10, dmx['y_max'] + 10)
        
        for ob in overbreak_list:
            if dmx_box.intersects(ob['line']):
                ob_pts = [(p[0] - ref_x, p[1] - ref_y) for p in ob['pts']]
                ob_body = GeologicalBody(
                    layer_name='超挖线',
                    points=ob_pts,
                    centroid=(sum(p[0] for p in ob_pts)/len(ob_pts), sum(p[1] for p in ob_pts)/len(ob_pts)),
                    area=0.0,
                    is_closed=False
                )
                surfaces.append(ob_body)
        
        # 匹配填充边界（Volume）
        volumes = []
        
        for layer_name, boundaries in fill_data.items():
            for boundary in boundaries:
                # 检查是否在DMX范围内
                try:
                    b_poly = Polygon(boundary['pts'])
                    if dmx_box.intersects(b_poly):
                        # 计算相对坐标
                        rel_pts = [(p[0] - ref_x, p[1] - ref_y) for p in boundary['pts']]
                        rel_centroid = (boundary['centroid'][0] - ref_x, boundary['centroid'][1] - ref_y)
                        
                        vol_body = GeologicalBody(
                            layer_name=layer_name,
                            points=rel_pts,
                            centroid=rel_centroid,
                            area=boundary['area'] * (self.scale_factor ** 2),  # 面积考虑缩放
                            is_closed=True
                        )
                        volumes.append(vol_body)
                except: pass
        
        return SectionMetadata(
            station_name=station_name,
            station_value=station_value,
            mileage=mileage,
            surfaces=surfaces,
            volumes=volumes
        )


# ==================== BIM模型构建器 ====================

class GeologicalBIMBuilderV2:
    """地质BIM模型构建器V2 - 使用核心放样引擎"""
    
    def __init__(self, dxf_path: str):
        self.dxf_path = dxf_path
        self.sections = []
        self.engine = BIMLoftingEngine(num_samples=100)
        self.meshes = {}
    
    def build(self, skip_visualization: bool = True) -> Dict[str, pv.PolyData]:
        """构建BIM模型"""
        print("\n" + "="*60)
        print("航道地质 BIM 模型构建器 V2 - 防穿模/防扭曲版")
        print("="*60, flush=True)
        
        # 1. 提取数据
        print("\n[Step 1] 提取DXF数据...", flush=True)
        extractor = DXFDataExtractor(self.dxf_path)
        self.sections = extractor.extract_all()
        print(f"  提取完成: {len(self.sections)}个断面", flush=True)
        
        if not self.sections:
            print("  [ERROR] 未检测到断面!")
            return {}
        
        # 2. 构建DMX/超挖线Mesh（Ribbon）
        print("\n=== 构建Ribbon Mesh（DMX/超挖线）===")
        
        dmx_mileages = [s.mileage for s in self.sections]
        dmx_coords = [np.array(s.surfaces[0].points) for s in self.sections if s.surfaces]
        
        if len(dmx_mileages) >= 2 and len(dmx_coords) >= 2:
            dmx_mesh = self.engine.create_ribbon_mesh(dmx_mileages, dmx_coords)
            if dmx_mesh:
                self.meshes['DMX'] = dmx_mesh
                print(f"  DMX Ribbon: 顶点={dmx_mesh.n_points}, 面={dmx_mesh.n_cells}")
        
        # 3. 构建地层Mesh（Volume）- 使用全里程扫描V3
        print("\n=== 构建Volume Mesh（地层填充）- V3全里程扫描 ===")
        
        # 使用LayerMatcher V3构建地层链（全里程扫描+退化逻辑）
        matcher = LayerMatcher(self.sections, max_centroid_dist=100.0 * extractor.scale_factor, num_samples=100)
        layer_chains_v3 = matcher.build_layer_chains_v3()
        
        # V3版本直接返回(mileage, coords)对，无需再次处理
        for layer_name, chain_data in layer_chains_v3.items():
            if len(chain_data) >= 2:
                # 解构里程和坐标
                mileages = [item[0] for item in chain_data]
                coords = [item[1] for item in chain_data]
                
                # 创建体积网格
                mesh = self.engine.create_volume_mesh(mileages, coords)
                if mesh:
                    self.meshes[layer_name] = mesh
                    print(f"  {layer_name}: 顶点={mesh.n_points}, 面={mesh.n_cells}, 断面数={len(mileages)}")
        
        print(f"\n总网格数: {len(self.meshes)}")
        
        return self.meshes
    
    def visualize(self, show_gui: bool = True):
        """可视化"""
        print("\n=== 可视化BIM模型 ===")
        
        if not self.meshes:
            print("  [ERROR] 没有网格数据!")
            return
        
        plotter = pv.Plotter(title="航道3D地质BIM展示 - V2防穿模版", window_size=[1600, 900], off_screen=True)
        
        # 添加DMX（绿色，不透明）
        if 'DMX' in self.meshes:
            plotter.add_mesh(
                self.meshes['DMX'],
                name='DMX',
                color='#2ecc71',
                opacity=1.0,
                label='DMX设计线',
                smooth_shading=True
            )
        
        # 添加各地层
        for layer_name, mesh in self.meshes.items():
            if layer_name == 'DMX':
                continue
            
            color = get_layer_color(layer_name)
            opacity = get_layer_opacity(layer_name)
            
            plotter.add_mesh(
                mesh,
                name=layer_name,
                color=color,
                opacity=opacity,
                label=layer_name,
                smooth_shading=True
            )
        
        # 【关键验证】添加红色辅助线（航道里程轴 X=0, Z=0）
        # 如果修复成功，所有断面都应该像"糖葫芦"一样穿在这根红线上
        if self.sections:
            mileages = sorted([s.mileage for s in self.sections])
            # 创建一条贯穿所有桩号的红色线（X=0, Z=0）
            spine_points = np.array([[0, m, 0] for m in mileages])
            spine_line = pv.PolyData(spine_points)
            spine_line.lines = np.array([len(spine_points)] + list(range(len(spine_points))))
            
            plotter.add_mesh(
                spine_line,
                color='red',
                line_width=5,
                label='航道中心线(X=0)',
                name='spine_validation'
            )
            print(f"  红色辅助线: {len(mileages)}个桩号点，里程范围 {mileages[0]}-{mileages[-1]}m")
        
        # 添加图例
        plotter.add_legend(bcolor='white', face='circle', size=[0.15, 0.3])
        
        # 设置视角
        plotter.camera_position = 'iso'
        plotter.camera.elevation = 20
        plotter.camera.azimuth = 45
        
        plotter.show_grid()
        
        if show_gui:
            plotter.show()
        
        # 保存截图
        out_path = os.path.join(os.path.dirname(self.dxf_path), 'geological_bim_v2.png')
        plotter.screenshot(out_path)
        print(f"\n保存截图: {out_path}")
        
        return out_path
    
    def save_metadata(self, output_path: str):
        """保存元数据到JSON"""
        data = {
            'file_name': os.path.basename(self.dxf_path),
            'total_sections': len(self.sections),
            'sections': []
        }
        
        for section in self.sections:
            section_data = {
                'station_name': section.station_name,
                'station_value': section.station_value,
                'mileage': section.mileage,
                'surfaces': [
                    {
                        'layer_name': b.layer_name,
                        'points': b.points,
                        'centroid': b.centroid,
                        'is_closed': b.is_closed
                    }
                    for b in section.surfaces
                ],
                'volumes': [
                    {
                        'layer_name': b.layer_name,
                        'points': b.points,
                        'centroid': b.centroid,
                        'area': b.area,
                        'is_closed': b.is_closed
                    }
                    for b in section.volumes
                ]
            }
            data['sections'].append(section_data)
        
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        print(f"\n元数据已保存: {output_path}")


# ==================== 主程序 ====================

def main():
    """主函数"""
    print("\n" + "="*60)
    print("航道地质 BIM 模型构建器 V2 - 启动")
    print("="*60)
    
    dxf_path = r'D:\断面算量平台\测试文件\内湾段分层图（全航道底图20260318）面积比例0.6.dxf'
    
    print(f"\n输入文件: {dxf_path}")
    print(f"文件存在: {os.path.exists(dxf_path)}")
    
    if not os.path.exists(dxf_path):
        print("[ERROR] 文件不存在!")
        return
    
    # 构建BIM模型
    print("\n开始构建BIM模型...")
    builder = GeologicalBIMBuilderV2(dxf_path)
    meshes = builder.build()
    
    if meshes:
        # 保存元数据
        base_name = os.path.splitext(os.path.basename(dxf_path))[0]
        output_json = os.path.join(os.path.dirname(dxf_path), f'{base_name}_bim_metadata_v2.json')
        builder.save_metadata(output_json)
        
        # 可视化（无GUI模式，直接保存截图）
        builder.visualize(show_gui=False)
    
    print("\n完成!")


if __name__ == '__main__':
    main()