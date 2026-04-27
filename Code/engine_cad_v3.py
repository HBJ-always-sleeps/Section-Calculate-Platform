# -*- coding: utf-8 -*-
# engine_cad.py - 核心CAD计算引擎（优化版 v3.0）
"""
包含五个核心工具：
- autoline: 断面线合并（支持上/下包络线）
- autopaste: 批量粘贴
- autohatch: 快速填充
- autosection: 分层算量（替代原autoclassify，支持区分/不区分设计超挖）
- backfill: 回淤计算（新增）

v3.0更新：
- autoline支持上/下包络线选择
- autosection替换原autoclassify，支持区分/不区分设计超挖选项
- 新增backfill回淤计算模块
- 复用封装函数，减少代码量
"""

import ezdxf
import os
import traceback
import math
import re
import datetime
import pandas as pd
from collections import defaultdict
from shapely.geometry import LineString, MultiLineString, Point, box, Polygon, MultiPolygon
from shapely.ops import unary_union, linemerge, polygonize

# ==================== 核心配置 ====================
class Config:
    """全局配置"""
    DEFAULT_OUTPUT_LAYER = "FINAL_BOTTOM_SURFACE"
    DEFAULT_HATCH_LAYER = "AA_填充算量层"
    DEFAULT_FINAL_SECTION = "AA_最终断面线"
    AREA_SCALE_FACTOR = 1.0
    
    HIGH_CONTRAST_COLORS = [
        (255, 0, 0), (0, 200, 0), (0, 0, 255), (255, 255, 0), (255, 0, 255), (0, 255, 255),
        (255, 128, 0), (128, 0, 255), (0, 128, 255), (255, 0, 128), (128, 255, 0), (0, 255, 128),
    ]
    
    # 地层颜色映射
    STRATA_COLORS = {
        '1级淤泥': 11, '1级淤泥质土': 12, '2级淤泥': 31, '3级淤泥': 32,
        '3级粘土': 33, '4级粘土': 41, '4级淤泥': 42, '5级粘土': 51,
        '6级砂': 61, '6级碎石': 62, '7级砂': 71, '8级砂': 81, '9级碎石': 91,
    }

# ==================== 通用辅助函数模块 ====================

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


class LineUtils:
    """线段处理工具集"""
    
    @staticmethod
    def get_y_at_x(line, x):
        """获取指定 X 处的 Y 值"""
        coords = list(line.coords)
        for i in range(len(coords) - 1):
            x1, y1 = coords[i]
            x2, y2 = coords[i + 1]
            if (x1 <= x <= x2) or (x2 <= x <= x1):
                if abs(x2 - x1) < 0.001:
                    return y1
                t = (x - x1) / (x2 - x1)
                return y1 + t * (y2 - y1)
        return None
    
    @staticmethod
    def extend(line, dist):
        """延长线两端"""
        coords = list(line.coords)
        if len(coords) < 2: return line
        p1, p2 = Point(coords[0]), Point(coords[1])
        vec = (p1.x - p2.x, p1.y - p2.y)
        mag = (vec[0]**2 + vec[1]**2)**0.5 or 1
        new_start = (p1.x + vec[0]/mag*dist, p1.y + vec[1]/mag*dist)
        p_n1, p_n = Point(coords[-2]), Point(coords[-1])
        vec = (p_n.x - p_n1.x, p_n.y - p_n1.y)
        mag = (vec[0]**2 + vec[1]**2)**0.5 or 1
        new_end = (p_n.x + vec[0]/mag*dist, p_n.y + vec[1]/mag*dist)
        return LineString([new_start] + coords + [new_end])
    
    @staticmethod
    def find_intersections(line1, line2):
        """找出两条线的所有交点"""
        try:
            inter = line1.intersection(line2)
            if inter.is_empty: return []
            if inter.geom_type == 'Point': return [(inter.x, inter.y)]
            if inter.geom_type == 'MultiPoint': return [(p.x, p.y) for p in inter.geoms]
            if inter.geom_type == 'LineString': return list(inter.coords)
            if inter.geom_type == 'GeometryCollection':
                return [(g.x, g.y) for g in inter.geoms if g.geom_type == 'Point']
        except: pass
        return []


class LayerExtractor:
    """图层提取工具集"""
    
    @staticmethod
    def get_lines(msp, layer):
        """从指定图层提取所有线段"""
        lines = []
        try:
            for e in msp.query(f'*[layer=="{layer}"]'):
                ls = EntityHelper.to_linestring(e)
                if ls: lines.append(ls)
        except: pass
        return lines
    
    @staticmethod
    def get_texts(msp, layer_pattern=None):
        """提取文本实体"""
        texts = []
        for e in msp.query('TEXT MTEXT'):
            try:
                if layer_pattern and layer_pattern not in e.dxf.layer:
                    continue
                pt = EntityHelper.get_best_point(e)
                txt = EntityHelper.get_text(e)
                texts.append({'text': txt, 'x': pt[0], 'y': pt[1], 'entity': e})
            except: pass
        return texts
    
    @staticmethod
    def get_polylines_by_color(msp, color):
        """按颜色获取多段线"""
        results = []
        for e in msp.query('LWPOLYLINE'):
            try:
                if e.dxf.color == color:
                    pts = list(e.get_points())
                    results.append({'entity': e, 'x': sum(p[0] for p in pts)/len(pts), 'y': sum(p[1] for p in pts)/len(pts)})
            except: pass
        return results


class StationMatcher:
    """桩号匹配工具集"""
    
    STATION_PATTERN = re.compile(r'(\d+\+\d+)')
    
    @classmethod
    def extract_stations(cls, msp, layer=None):
        """提取桩号文本"""
        stations = {}
        for e in msp.query('TEXT MTEXT'):
            try:
                txt = EntityHelper.get_text(e).upper()
                match = cls.STATION_PATTERN.search(txt)
                if match:
                    pt = EntityHelper.get_best_point(e)
                    sid = match.group(1)
                    if sid not in stations: stations[sid] = []
                    stations[sid].append({'x': pt[0], 'y': pt[1]})
            except: pass
        return stations
    
    @staticmethod
    def sort_key(station_str):
        """桩号排序键"""
        nums = re.findall(r'\d+', str(station_str))
        return int("".join(nums)) if nums else 0
    
    @staticmethod
    def strata_sort_key(name):
        """地层排序键"""
        nums = re.findall(r'^(\d+)', name)
        return int(nums[0]) if nums else 999
    
    @staticmethod
    def find_nearest(target_pt, candidates, used=None, tolerance=200):
        """找最近的候选点"""
        best = None
        best_dist = float('inf')
        for i, c in enumerate(candidates):
            if used and i in used: continue
            dist = math.sqrt((c['x'] - target_pt[0])**2 + (c['y'] - target_pt[1])**2)
            if dist < best_dist and dist < tolerance:
                best_dist = dist
                best = (i, c)
        return best


class OutputHelper:
    """文件输出工具集"""
    
    @staticmethod
    def get_output_path(input_path, suffix, output_dir=None):
        """生成输出文件路径"""
        base_dir = output_dir if output_dir else os.path.dirname(input_path)
        base_name = os.path.splitext(os.path.basename(input_path))[0]
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        if suffix.endswith('.dxf') or suffix.endswith('.xlsx'):
            return os.path.join(base_dir, f"{base_name}{suffix}")
        return os.path.join(base_dir, f"{base_name}{suffix}.dxf")
    
    @staticmethod
    def ensure_layer(doc, layer_name, color=7):
        """确保图层存在"""
        if layer_name not in doc.layers:
            doc.layers.new(name=layer_name, dxfattribs={'color': color})
        return doc.layers.get(layer_name)


class HatchProcessor:
    """填充处理器"""
    
    @staticmethod
    def to_polygon(hatch_entity):
        """填充转多边形"""
        polygons = []
        try:
            for path in hatch_entity.paths:
                pts = []
                if hasattr(path, 'vertices') and len(path.vertices) > 0:
                    pts = [(v[0], v[1]) for v in path.vertices]
                elif hasattr(path, 'edges'):
                    for edge in path.edges:
                        edge_type = type(edge).__name__
                        if edge_type == 'LineEdge':
                            pts.extend([(edge.start[0], edge.start[1]), (edge.end[0], edge.end[1])])
                        elif edge_type in ('ArcEdge', 'EllipseEdge'):
                            try: pts.extend([(p.x, p.y) for p in edge.flattening(distance=0.01)])
                            except: pass
                if len(pts) >= 3:
                    poly = Polygon(pts)
                    if not poly.is_valid: poly = poly.buffer(0)
                    if not poly.is_empty: polygons.append(Polygon(poly.exterior))
        except: pass
        return unary_union(polygons) if polygons else None
    
    @staticmethod
    def add_with_label(msp, poly, rgb_color, pattern, scale, text_height, strata_name, is_design, doc=None):
        """添加填充和标注"""
        if not poly or poly.is_empty or isinstance(poly, (LineString, Point)):
            return 0.0
        
        label_type = "设计" if is_design else "超挖"
        layer_hatch = f"{strata_name}{label_type}"
        layer_label = f"{strata_name}{label_type}_标注"
        
        if doc:
            OutputHelper.ensure_layer(doc, layer_hatch)
            OutputHelper.ensure_layer(doc, layer_label)
        
        geoms = [poly] if isinstance(poly, Polygon) else (list(poly.geoms) if hasattr(poly, 'geoms') else [poly])
        total_area = 0.0
        full_label = f"{strata_name}{label_type}"
        
        for p in geoms:
            if isinstance(p, (LineString, Point)) or p.area < 0.01: continue
            total_area += p.area
            
            hatch = msp.add_hatch(dxfattribs={'layer': layer_hatch})
            hatch.rgb = rgb_color
            hatch.set_pattern_fill(pattern, scale=scale)
            hatch.paths.add_polyline_path(list(p.exterior.coords), is_closed=True)
            for interior in p.interiors:
                hatch.paths.add_polyline_path(list(interior.coords), is_closed=True)
            
            area_val = round(p.area, 3)
            if area_val > 0.1:
                try:
                    in_point = p.representative_point()
                    label_content = f"{{\\fArial|b1;{full_label}\\P{area_val}}}"
                    mtext = msp.add_mtext(label_content, dxfattribs={
                        'layer': layer_label, 'insert': (in_point.x, in_point.y),
                        'char_height': text_height, 'attachment_point': 5,
                    })
                    mtext.rgb = rgb_color
                    try: mtext.dxf.bg_fill_setting = 1; mtext.dxf.bg_fill_scale_factor = 1.3
                    except: pass
                except: pass
        return total_area
    
    @staticmethod
    def add_simple(msp, poly, layer_name, color_index=7, rgb_color=None):
        """添加简单填充（无标注）"""
        if poly is None or poly.is_empty: return
        if hasattr(poly, 'exterior'):
            boundaries = [list(poly.exterior.coords)]
            for interior in poly.interiors:
                boundaries.append(list(interior.coords))
        elif isinstance(poly, MultiPolygon):
            boundaries = []
            for p in poly.geoms:
                boundaries.append(list(p.exterior.coords))
                for interior in p.interiors:
                    boundaries.append(list(interior.coords))
        else:
            return
        
        for boundary_pts in boundaries:
            if len(boundary_pts) >= 3:
                hatch = msp.add_hatch(dxfattribs={'layer': layer_name, 'color': color_index})
                hatch.set_pattern_fill('SOLID', scale=1.0)
                if rgb_color: hatch.rgb = rgb_color
                hatch.paths.add_polyline_path(boundary_pts, is_closed=True)


class EnvelopeGenerator:
    """包络线生成器"""
    
    @staticmethod
    def generate(base_line, section_lines, envelope_type='lower'):
        """生成包络线
        
        Args:
            base_line: 基准线
            section_lines: 其他断面线列表
            envelope_type: 'lower' 下包络线（取最小Y）或 'upper' 上包络线（取最大Y）
        """
        all_x_coords = set()
        for pt in base_line.coords:
            all_x_coords.add(round(pt[0], 3))
        for sec in section_lines:
            for pt in sec.coords:
                all_x_coords.add(round(pt[0], 3))
        
        # 收集交点附近的X坐标
        all_lines = [base_line] + list(section_lines)
        for i in range(len(all_lines)):
            for j in range(i + 1, len(all_lines)):
                for ix, iy in LineUtils.find_intersections(all_lines[i], all_lines[j]):
                    all_x_coords.add(round(ix, 3))
                    for delta in [-1.0, -0.5, 0.5, 1.0]:
                        all_x_coords.add(round(ix + delta, 3))
        
        if not all_x_coords: return None
        
        base_bounds = base_line.bounds
        x_min, x_max = base_bounds[0], base_bounds[2]
        filtered_x = sorted(x for x in all_x_coords if x_min <= x <= x_max)
        
        if not filtered_x: return None
        
        coords = []
        for x in filtered_x:
            all_ys = []
            base_y = LineUtils.get_y_at_x(base_line, x)
            if base_y is not None: all_ys.append(base_y)
            for sec in section_lines:
                sec_y = LineUtils.get_y_at_x(sec, x)
                if sec_y is not None: all_ys.append(sec_y)
            
            if all_ys:
                target_y = min(all_ys) if envelope_type == 'lower' else max(all_ys)
                coords.append((x, target_y))
        
        return LineString(coords) if len(coords) >= 2 else None


class RulerDetector:
    """标尺检测器"""
    
    @staticmethod
    def detect_scale(msp, doc, sect_x_min, sect_x_max, sect_y_center, sect_y_min, sect_y_max):
        """检测标尺比例，返回(elev_to_y, y_to_elev)函数对"""
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
        
        if not ruler_candidates: return None
        
        sect_x_center = (sect_x_min + sect_x_max) / 2
        best_ruler, best_overlap = None, -1
        for ruler in ruler_candidates:
            overlap = max(0, min(sect_y_max, ruler['y_max']) - max(sect_y_min, ruler['y_min']))
            overlap_ratio = overlap / (ruler['y_max'] - ruler['y_min']) if ruler['y_max'] > ruler['y_min'] else 0
            if overlap_ratio > best_overlap: best_overlap, best_ruler = overlap_ratio, ruler
        
        if not best_ruler: best_ruler = min(ruler_candidates, key=lambda r: abs(r['x'] - sect_x_center))
        
        elevation_points = []
        if best_ruler.get('entity'):
            insert_y = best_ruler['entity'].dxf.insert.y
            try:
                block_name = best_ruler['entity'].dxf.name
                if block_name in doc.blocks:
                    for be in doc.blocks[block_name]:
                        if be.dxftype() in ('TEXT', 'MTEXT'):
                            try:
                                world_y = be.dxf.insert.y + insert_y
                                text = (be.dxf.text if be.dxftype() == 'TEXT' else be.text).strip()
                                elevation_points.append((world_y, float(text)))
                            except: pass
            except: pass
        
        if len(elevation_points) < 2: return None
        
        n = len(elevation_points)
        sum_y = sum(p[0] for p in elevation_points)
        sum_e = sum(p[1] for p in elevation_points)
        sum_ye = sum(p[0] * p[1] for p in elevation_points)
        sum_e2 = sum(p[1] ** 2 for p in elevation_points)
        denom = n * sum_e2 - sum_e ** 2
        if abs(denom) < 0.001: return None
        
        a = (n * sum_ye - sum_y * sum_e) / denom
        b = (sum_y - a * sum_e) / n
        return (lambda elev: a * elev + b, lambda y: (y - b) / a)


class VirtualBoxBuilder:
    """虚拟断面框构建器"""
    
    @staticmethod
    def build_from_overexcav(overexc_lines):
        """从超挖线构建虚拟断面框"""
        if not overexc_lines: return []
        
        line_info = []
        for line in overexc_lines:
            bounds = line.bounds
            line_info.append({
                'line': line,
                'mid_x': (bounds[0] + bounds[2]) / 2,
                'mid_y': (bounds[1] + bounds[3]) / 2,
                'bounds': bounds
            })
        
        n = len(line_info)
        if n == 0: return []
        if n == 1:
            b = line_info[0]['bounds']
            return [box(b[0], b[1], b[2], b[3])]
        
        # 按Y坐标聚类
        heights = [info['bounds'][3] - info['bounds'][1] for info in line_info]
        median_height = sorted(heights)[len(heights)//2]
        cluster_threshold = median_height * 1.5
        
        sorted_by_y = sorted(line_info, key=lambda x: x['mid_y'], reverse=True)
        clusters = [[sorted_by_y[0]]]
        
        for i in range(1, len(sorted_by_y)):
            y_gap = abs(sorted_by_y[i]['mid_y'] - sorted_by_y[i-1]['mid_y'])
            if y_gap < cluster_threshold:
                clusters[-1].append(sorted_by_y[i])
            else:
                clusters.append([sorted_by_y[i]])
        
        virtual_boxes = []
        for cluster in clusters:
            all_coords = [pt for info in cluster for pt in list(info['line'].coords)]
            if all_coords:
                min_x = min(c[0] for c in all_coords)
                max_x = max(c[0] for c in all_coords)
                min_y = min(c[1] for c in all_coords)
                max_y = max(c[1] for c in all_coords)
                virtual_boxes.append(box(min_x, min_y, max_x, max_y))
        
        return virtual_boxes


# ==================== 1. 断面线合并 (autoline) ====================

def run_autoline(params, LOG):
    """断面合并任务 - 支持上/下包络线选择"""
    try:
        layer_new = params.get('图层A名称') or params.get('图层 A 名称')
        layer_old = params.get('图层B名称') or params.get('图层 B 名称')
        envelope_type = params.get('包络线类型', 'lower')  # 'lower' 或 'upper'
        output_layer = params.get('输出图层名', Config.DEFAULT_OUTPUT_LAYER)
        output_dir = params.get('输出目录')
        
        if not layer_new or not layer_old:
            LOG("[ERROR] 脚本错误：无法从UI获取图层名称。")
            return
        
        file_list = params.get('files', [])
        if not file_list:
            LOG("[WARN] 请先添加文件。")
            return
        
        type_name = "下包络" if envelope_type == 'lower' else "上包络"
        LOG(f"[INFO] 包络线类型: {type_name}")

        for input_file in file_list:
            LOG(f"--- [WAIT] 正在处理({type_name}): {os.path.basename(input_file)} ---")
            
            if not os.path.exists(input_file):
                LOG(f"[ERROR] 错误: 找不到文件 {input_file}")
                continue

            doc = ezdxf.readfile(input_file)
            msp = doc.modelspace()
            
            new_lss = [ls for ls in (EntityHelper.to_linestring(e) for e in msp.query(f'LWPOLYLINE POLYLINE LINE[layer=="{layer_new}"]')) if ls]
            old_lss = [ls for ls in (EntityHelper.to_linestring(e) for e in msp.query(f'LWPOLYLINE POLYLINE LINE[layer=="{layer_old}"]')) if ls]

            if not new_lss and not old_lss:
                LOG(f"[WARN] 跳过：指定图层没有线段。")
                continue

            groups = []
            used_old = set()
            for n_ls in new_lss:
                current_group = [n_ls]
                for idx, o_ls in enumerate(old_lss):
                    if n_ls.intersects(o_ls) or n_ls.distance(o_ls) < 0.5:
                        current_group.append(o_ls)
                        used_old.add(idx)
                groups.append(current_group)
            
            for idx, o_ls in enumerate(old_lss):
                if idx not in used_old:
                    groups.append([o_ls])

            OutputHelper.ensure_layer(doc, output_layer, color=3)

            success_count = 0
            for group in groups:
                if len(group) < 2:
                    msp.add_lwpolyline(list(group[0].coords), dxfattribs={'layer': output_layer})
                    success_count += 1
                    continue
                
                final_line = EnvelopeGenerator.generate(group[0], group[1:], envelope_type)
                if final_line and final_line.length > 0.01:
                    msp.add_lwpolyline(list(final_line.coords), dxfattribs={'layer': output_layer})
                    success_count += 1

            output_path = OutputHelper.get_output_path(input_file, f"_{type_name}合并.dxf", output_dir)
            doc.saveas(output_path)
            LOG(f"[OK] 完成！已提取{type_name}线，保存至: {os.path.basename(output_path)}")

        LOG(f"[DONE] [{type_name}任务全部结束]")

    except Exception as e:
        LOG(f"[ERROR] 脚本崩溃:\n{traceback.format_exc()}")


# ==================== 2. 批量粘贴 (autopaste) ====================

def run_autopaste(params, LOG):
    """批量粘贴任务 v2 - 基于桩号值顺序匹配
    
    核心改进（来自autopaste_with_station_v2.py）：
    1. 源端：小矩形检测 + 断面曲线匹配 + 桩号排序匹配
    2. 目标端：L1脊梁线交点检测 + 桩号分组匹配
    3. 通过桩号值精确匹配源套组 <-> 目标套组
    """
    try:
        # 获取参数
        src_path = params.get('源文件名')
        dst_path = params.get('目标文件名')
        
        if not src_path or not dst_path:
            LOG("[ERROR] 请先选择源文件和目标文件")
            return
        
        if not os.path.exists(src_path):
            LOG(f"[ERROR] 找不到源文件: {src_path}")
            return
        
        LOG(f"\n{'='*60}")
        LOG("[成套对应粘贴 v2] 开始")
        LOG(f"{'='*60}")
        LOG(f"源文件: {os.path.basename(src_path)}")
        LOG(f"目标文件: {os.path.basename(dst_path)}")
        
        src_doc = ezdxf.readfile(src_path)
        dst_doc = ezdxf.readfile(dst_path)
        
        src_msp = src_doc.modelspace()
        dst_msp = dst_doc.modelspace()
        
        # ===== 第一步：检测源文件成套数据 v2 =====
        LOG("\n[检测源文件成套数据 v2]")
        
        # 1. 检测小矩形（XSECTION图层，宽130~200，高95~140）
        small_rects = []
        for e in src_msp.query('LWPOLYLINE[layer=="XSECTION"]'):
            try:
                pts = [(p[0], p[1]) for p in e.get_points()]
                if len(pts) >= 4:
                    xs = [pt[0] for pt in pts]
                    ys = [pt[1] for pt in pts]
                    bbox = (min(xs), min(ys), max(xs), max(ys))
                    width = bbox[2] - bbox[0]
                    height = bbox[3] - bbox[1]
                    if 130 < width < 200 and 95 <= height < 140:
                        center_x = (bbox[0] + bbox[2]) / 2
                        top_y = bbox[3]
                        center_y = (bbox[1] + bbox[3]) / 2
                        small_rects.append({
                            'entity': e,
                            'bbox': bbox,
                            'basepoint': (center_x, top_y),
                            'center_y': center_y
                        })
            except: pass
        
        LOG(f"  小矩形数量: {len(small_rects)}")
        
        # 按Y从上到下排序（Y越大越靠上）
        small_rects.sort(key=lambda r: r['center_y'], reverse=True)
        for i, rect in enumerate(small_rects):
            rect['index'] = i + 1
        
        # 2. 检测断面曲线（>50顶点）
        curves = []
        for e in src_msp.query('LWPOLYLINE[layer=="XSECTION"]'):
            try:
                pts = [(p[0], p[1]) for p in e.get_points()]
                if len(pts) > 50:
                    xs = [pt[0] for pt in pts]
                    ys = [pt[1] for pt in pts]
                    bbox = (min(xs), min(ys), max(xs), max(ys))
                    center_x = (bbox[0] + bbox[2]) / 2
                    center_y = (bbox[1] + bbox[3]) / 2
                    curves.append({
                        'entity': e,
                        'bbox': bbox,
                        'center': (center_x, center_y),
                        'vertex_count': len(pts)
                    })
            except: pass
        
        LOG(f"  断面曲线数量: {len(curves)}")
        
        # 3. 检测桩号标注并按值排序
        def parse_source_station(text):
            """解析源文件桩号格式：00+000.TIN 或 00+000"""
            text = text.upper()
            # 先尝试 .TIN 格式
            match = re.search(r'(\d+)\+(\d+)\.TIN', text)
            if match:
                return int(match.group(1)) * 1000 + int(match.group(2))
            # 再尝试纯格式
            match = re.search(r'(\d+)\+(\d+)', text)
            if match:
                return int(match.group(1)) * 1000 + int(match.group(2))
            return None
        
        station_values = set()
        for e in src_msp.query('TEXT'):
            try:
                text = e.dxf.text
                station_value = parse_source_station(text)
                if station_value is not None:
                    station_values.add(station_value)
            except: pass
        
        # 按桩号值排序（从小到大）
        sorted_station_values = sorted(station_values)
        LOG(f"  不同桩号值数量: {len(sorted_station_values)}")
        
        # 4. 匹配：小矩形按Y顺序 ↔ 桩号值按值顺序（一对一）
        source_sets = []
        
        for i, rect in enumerate(small_rects):
            rect_bbox = rect['bbox']
            
            # 匹配断面曲线（曲线中心在小矩形内）
            best_curve = None
            for curve in curves:
                if (rect_bbox[0] < curve['center'][0] < rect_bbox[2] and
                    rect_bbox[1] < curve['center'][1] < rect_bbox[3]):
                    best_curve = curve
                    break
            
            # 匹配桩号（按顺序一对一）
            if i < len(sorted_station_values):
                station_value = sorted_station_values[i]
            else:
                station_value = None
            
            # 格式化桩号
            def format_station(value):
                if value is None:
                    return None
                km = int(value // 1000)
                m = int(value % 1000)
                return f"K{km:02d}+{m:03d}"
            
            source_set = {
                'index': rect['index'],
                'rect_bbox': rect_bbox,
                'basepoint': rect['basepoint'],
                'center_y': rect['center_y'],
                'curve': best_curve,
                'curve_entity': best_curve['entity'] if best_curve else None,
                'station': station_value,
                'station_text': format_station(station_value) if station_value else None
            }
            source_sets.append(source_set)
        
        with_curve = [s for s in source_sets if s['curve'] is not None]
        with_station = [s for s in source_sets if s['station'] is not None]
        
        LOG(f"  成套数量: {len(source_sets)}")
        LOG(f"  有断面线: {len(with_curve)}")
        LOG(f"  有桩号: {len(with_station)}")
        
        # ===== 第二步：检测目标文件成套数据 v2 =====
        LOG("\n[检测目标文件成套数据 v2]")
        
        # 1. 检测L1脊梁线
        horizontal_lines = []
        vertical_lines = []
        
        for e in dst_msp.query('*[layer=="L1"]'):
            try:
                if e.dxftype() == 'LINE':
                    x1, y1 = e.dxf.start.x, e.dxf.start.y
                    x2, y2 = e.dxf.end.x, e.dxf.end.y
                    
                    width = abs(x2 - x1)
                    height = abs(y2 - y1)
                    
                    if width > height * 3:
                        horizontal_lines.append({
                            'entity': e,
                            'y': (y1 + y2) / 2,
                            'x_min': min(x1, x2),
                            'x_max': max(x1, x2)
                        })
                    elif height > width * 3:
                        vertical_lines.append({
                            'entity': e,
                            'x': (x1 + x2) / 2,
                            'y_min': min(y1, y2),
                            'y_max': max(y1, y2),
                            'y_center': (y1 + y2) / 2
                        })
            except: pass
        
        LOG(f"  水平线数量: {len(horizontal_lines)}")
        LOG(f"  垂直线数量: {len(vertical_lines)}")
        
        # 排序
        horizontal_lines.sort(key=lambda l: l['y'], reverse=True)
        vertical_lines.sort(key=lambda l: l['x'])
        
        # 2. 计算交点（一对一匹配）
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
                    'v_line': v_line,
                    'h_line': h_line
                })
        
        LOG(f"  基点数量: {len(basepoints)}")
        
        # 3. 检测桩号标注
        def parse_target_station(text):
            """解析目标文件桩号格式：K00+000 或 00+000"""
            text = text.upper()
            match = re.search(r'K(\d+)\+(\d+)', text)
            if match:
                return int(match.group(1)) * 1000 + int(match.group(2))
            match = re.search(r'(\d+)\+(\d+)', text)
            if match:
                return int(match.group(1)) * 1000 + int(match.group(2))
            return None
        
        station_texts = []
        for e in dst_msp.query('TEXT'):
            try:
                text = e.dxf.text
                station_value = parse_target_station(text)
                if station_value is not None:
                    station_texts.append({
                        'entity': e,
                        'text': text,
                        'value': station_value,
                        'x': e.dxf.insert.x,
                        'y': e.dxf.insert.y
                    })
            except: pass
        
        LOG(f"  桩号标注数量: {len(station_texts)}")
        
        # 4. 匹配基点与桩号 - 按X坐标分组匹配
        target_sets = []
        
        # 按X坐标分组基点（容差50）
        bp_groups = {}
        for bp in basepoints:
            bp_x = bp['x']
            assigned = False
            for group_x in bp_groups:
                if abs(bp_x - group_x) < 50:
                    bp_groups[group_x].append(bp)
                    assigned = True
                    break
            if not assigned:
                bp_groups[bp_x] = [bp]
        
        # 按X坐标分组桩号（容差50）
        station_groups = {}
        for station in station_texts:
            st_x = station['x']
            assigned = False
            for group_x in station_groups:
                if abs(st_x - group_x) < 50:
                    station_groups[group_x].append(station)
                    assigned = True
                    break
            if not assigned:
                station_groups[st_x] = [station]
        
        # 按分组匹配：基点X组 <-> 桩号X组
        matched_bp_stations = {}
        
        for bp_group_x, bp_list in bp_groups.items():
            best_station_group_x = None
            best_x_diff = float('inf')
            
            for station_group_x in station_groups:
                x_diff = abs(bp_group_x - station_group_x)
                if x_diff < best_x_diff:
                    best_x_diff = x_diff
                    best_station_group_x = station_group_x
            
            if best_station_group_x is not None and best_x_diff < 50:
                station_list = station_groups[best_station_group_x]
                
                # 按Y排序（从大到小）
                bp_list.sort(key=lambda b: b['y'], reverse=True)
                station_list.sort(key=lambda s: s['y'], reverse=True)
                
                # 一对一匹配
                for i, bp in enumerate(bp_list):
                    if i < len(station_list):
                        matched_bp_stations[(bp['x'], bp['y'])] = station_list[i]
        
        # 构建target_sets
        for bp in basepoints:
            station = matched_bp_stations.get((bp['x'], bp['y']))
            target_set = {
                'basepoint': (bp['x'], bp['y']),
                'station': station['value'] if station else None,
                'station_text': station['text'] if station else None
            }
            target_sets.append(target_set)
        
        with_station_target = [t for t in target_sets if t['station'] is not None]
        LOG(f"  有桩号: {len(with_station_target)}")
        
        # ===== 第三步：桩号匹配 v2 =====
        LOG("\n[桩号匹配 v2]")
        
        # 构建桩号索引
        source_by_station = {}
        for s in source_sets:
            if s['station'] is not None:
                source_by_station[s['station']] = s
        
        target_by_station = {}
        for t in target_sets:
            if t['station'] is not None:
                target_by_station[t['station']] = t
        
        LOG(f"  源桩号索引: {len(source_by_station)}")
        LOG(f"  目标桩号索引: {len(target_by_station)}")
        
        # 匹配
        matched_pairs = []
        matched_stations = set()
        
        for station_value in sorted(source_by_station.keys()):
            if station_value in target_by_station:
                source_set = source_by_station[station_value]
                target_set = target_by_station[station_value]
                
                if source_set['curve_entity'] is not None:
                    matched_pairs.append({
                        'source': source_set,
                        'target': target_set,
                        'station': station_value
                    })
                    matched_stations.add(station_value)
        
        unmatched_source = [s for s in source_sets if s['station'] not in matched_stations]
        unmatched_target = [t for t in target_sets if t['station'] not in matched_stations]
        
        LOG(f"  匹配成功: {len(matched_pairs)}对")
        LOG(f"  源未匹配: {len(unmatched_source)}")
        LOG(f"  目标未匹配: {len(unmatched_target)}")
        
        # ===== 第四步：复制粘贴 =====
        LOG("\n[执行粘贴]")
        
        # 创建输出图层
        if "0-已粘贴断面" not in dst_doc.layers:
            dst_doc.layers.new(name="0-已粘贴断面", dxfattribs={'color': 3})
        
        pasted_count = 0
        failed_count = 0
        
        for pair in matched_pairs:
            source_set = pair['source']
            target_set = pair['target']
            
            curve_entity = source_set['curve_entity']
            source_bp = source_set['basepoint']
            target_bp = target_set['basepoint']
            
            try:
                # 计算偏移
                offset_x = target_bp[0] - source_bp[0]
                offset_y = target_bp[1] - source_bp[1]
                
                # 复制断面曲线
                pts = [(p[0], p[1]) for p in curve_entity.get_points()]
                new_pts = [(p[0] + offset_x, p[1] + offset_y) for p in pts]
                
                dst_msp.add_lwpolyline(
                    new_pts,
                    dxfattribs={
                        'layer': "0-已粘贴断面",
                        'color': 3
                    }
                )
                pasted_count += 1
            except Exception as e:
                failed_count += 1
        
        LOG(f"  成功粘贴: {pasted_count}")
        LOG(f"  失败: {failed_count}")
        
        # ===== 第五步：保存结果 =====
        dst_dir = os.path.dirname(dst_path) or "."
        dst_basename = os.path.basename(dst_path).replace(".dxf", "")
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        save_name = os.path.join(dst_dir, f"{dst_basename}_成套粘贴v2_{timestamp}.dxf")
        
        dst_doc.saveas(save_name)
        
        LOG(f"\n[输出文件]: {os.path.basename(save_name)}")
        LOG(f"[STATS] 统计：源套组 {len(source_sets)}，目标套组 {len(target_sets)}，匹配 {len(matched_pairs)}，粘贴 {pasted_count}")

    except Exception as e:
        LOG(f"[ERROR] 脚本执行崩溃:\n{traceback.format_exc()}")


# ==================== 3. 快速填充 (autohatch) ====================

def run_autohatch(params, LOG):
    """快速填充任务"""
    try:
        target_layer = params.get('填充层名称', Config.DEFAULT_HATCH_LAYER)
        output_dir = params.get('输出目录')
        file_list = params.get('files', [])

        if not file_list:
            LOG("[WARN] 请先选择 DXF 文件。")
            return

        for input_path in file_list:
            LOG(f"--- [WAIT] 正在处理: {os.path.basename(input_path)} ---")
            
            try:
                doc = ezdxf.readfile(input_path)
                msp = doc.modelspace()
            except Exception as e:
                LOG(f"[ERROR] 读取失败: {e}")
                continue

            visible_layers = {layer.dxf.name for layer in doc.layers if not layer.is_off()}
            raw_lines = []
            all_coords = []

            for ent in msp:
                if ent.dxftype() in ('LINE', 'LWPOLYLINE', 'POLYLINE'):
                    if ent.dxf.layer in visible_layers or ent.dxf.layer.startswith("AA_"):
                        ls = EntityHelper.to_linestring(ent)
                        if ls:
                            all_coords.extend(ls.coords)
                            raw_lines.append(ls)

            if not raw_lines: continue

            if all_coords:
                xs = [p[0] for p in all_coords]
                ys = [p[1] for p in all_coords]
                global_diag = math.sqrt((max(xs)-min(xs))**2 + (max(ys)-min(ys))**2)
                global_hatch_scale = max(0.5, global_diag * 0.02)
            else:
                global_hatch_scale = 1.0

            merged_lines = unary_union(raw_lines)
            polygons = sorted([p for p in polygonize(merged_lines) if p.area > 0.01], key=lambda p: p.representative_point().y, reverse=True)

            data_for_excel = []
            rgb_list = Config.HIGH_CONTRAST_COLORS

            for i, poly in enumerate(polygons):
                index_no = i + 1
                area_val = round(poly.area, 3)
                current_rgb = rgb_list[i % len(rgb_list)]
                
                data_for_excel.append({"编号": index_no, "面积(㎡)": area_val})

                try:
                    hatch = msp.add_hatch(dxfattribs={'layer': target_layer})
                    hatch.rgb = current_rgb
                    hatch.set_pattern_fill('ANSI31', scale=global_hatch_scale)
                    hatch.paths.add_polyline_path(list(poly.exterior.coords)[:-1], is_closed=True)
                    for interior in poly.interiors:
                        hatch.paths.add_polyline_path(list(interior.coords)[:-1], is_closed=True)
                    
                    in_point = poly.representative_point()
                    label_content = f"{{\\fArial|b1;{index_no}\\PS={area_val}}}"
                    mtext = msp.add_mtext(label_content, dxfattribs={
                        'layer': target_layer + "_标注", 'insert': (in_point.x, in_point.y),
                        'char_height': 3.0, 'attachment_point': 5,
                    })
                    mtext.rgb = current_rgb
                    try: mtext.dxf.bg_fill_setting = 1; mtext.dxf.bg_fill_scale_factor = 1.5
                    except: pass
                except Exception as e:
                    LOG(f"[WARN] 块 {index_no} 生成出错: {e}")
                    continue

            output_dxf = OutputHelper.get_output_path(input_path, "_填充完成.dxf", output_dir)
            doc.saveas(output_dxf)
            
            if data_for_excel:
                try:
                    df = pd.DataFrame(data_for_excel)
                    output_xlsx = OutputHelper.get_output_path(input_path, "_面积明细表.xlsx", output_dir)
                    df.to_excel(output_xlsx, index=False)
                    LOG(f"[STATS] 面积表已生成: {os.path.basename(output_xlsx)}")
                except Exception as ex:
                    LOG(f"[ERROR] Excel 导出失败: {ex}")

            LOG(f"[OK] 处理完成！总数量: {len(data_for_excel)}")

        LOG("[DONE] [全任务圆满结束]")

    except Exception as e:
        LOG(f"[ERROR] 脚本崩溃:\n{traceback.format_exc()}")


# ==================== 4. 分层算量 (autosection) ====================

def run_autosection(params, LOG):
    """分层算量任务 - 支持区分/不区分设计超挖，支持高程线上下算量切换
    
    Args:
        params: {
            'files': [文件列表],
            '目标高程': 高程值（如-10.0），
            '断面线图层': 断面线图层名（默认DMX），
            '桩号图层': 桩号图层名（默认0-桩号），
            '辅助断面图层': 辅助断面线图层列表，
            '合并断面线': True/False（是否合并辅助断面线，使用下包络线），
            '计算模式': 'below'高程线以下或'above'高程线以上，
            '区分设计超挖': True/False，
            '输出目录': 输出路径
        }
    """
    try:
        file_list = params.get('files', [])
        if not file_list:
            LOG("[WARN] 请先选择 DXF 文件。")
            return
        
        elevation_str = params.get('目标高程', '').strip()
        if elevation_str:
            try:
                target_elevation = float(elevation_str)
            except ValueError:
                LOG("[WARN] 目标高程格式错误，将使用全算量模式")
                target_elevation = None
        else:
            target_elevation = None  # 全算量模式
        
        if target_elevation is not None:
            LOG(f"[INFO] 目标高程: {target_elevation}m")
        else:
            LOG(f"[INFO] 全算量模式（未指定目标高程）")
        section_layer = params.get('断面线图层', '') or 'DMX'  # 空字符串时使用默认值DMX
        pile_layer = params.get('桩号图层', '') or '0-桩号'  # 空字符串时使用默认值
        merge_section = params.get('合并断面线', True)  # 新增合并断面线参数
        aux_layers_str = params.get('辅助断面图层', '')
        calc_mode = params.get('计算模式', 'below')  # 'below'=高程线以下, 'above'=高程线以上
        distinguish_design = params.get('区分设计超挖', False)
        if isinstance(distinguish_design, str):
            distinguish_design = distinguish_design.lower() in ('true', '1', 'yes', '是')
        if isinstance(merge_section, str):
            merge_section = merge_section.lower() in ('true', '1', 'yes', '是')
        output_dir = params.get('输出目录')
        
        aux_layers = [s.strip() for s in aux_layers_str.split(',') if s.strip()]
        
        LOG(f"[INFO] 目标高程: {target_elevation}m")
        LOG(f"[INFO] 断面线图层: {section_layer}")
        LOG(f"[INFO] 桩号图层: {pile_layer}")
        LOG(f"[INFO] 合并断面线: {'是' if merge_section else '否'}")
        LOG(f"[INFO] 辅助断面图层: {aux_layers}")
        LOG(f"[INFO] 计算模式: {'高程线以下' if calc_mode == 'below' else '高程线以上'}")
        LOG(f"[INFO] 区分设计/超挖: {'是' if distinguish_design else '否'}")
        
        for input_path in file_list:
            LOG(f"--- [WAIT] 正在处理: {os.path.basename(input_path)} ---")
            
            doc = ezdxf.readfile(input_path)
            msp = doc.modelspace()
            
            all_layers = [l.dxf.name for l in doc.layers]
            LOG(f"[INFO] 图层总数: {len(all_layers)}")
            
            # 获取地层图层
            strata_layers = sorted(
                [l for l in all_layers if re.match(r'^\d+级', l)],
                key=StationMatcher.strata_sort_key
            )
            LOG(f"[INFO] 地层图层: {strata_layers}")
            
            # 获取DMX列表
            dmx_list = _get_entity_list(msp, section_layer)
            dmx_list = sorted(dmx_list, key=lambda d: d['y_center'], reverse=True)
            LOG(f"[INFO] {section_layer}数量: {len(dmx_list)}")
            
            # 获取辅助断面线
            aux_lines_all = []
            for layer in aux_layers:
                aux_lines_all.extend(LayerExtractor.get_lines(msp, layer))
            LOG(f"[INFO] 辅助断面线数量: {len(aux_lines_all)}")
            
            # 获取开挖线和超挖线
            excav_lines_all = LayerExtractor.get_lines(msp, "开挖线")
            overexc_lines_all = LayerExtractor.get_lines(msp, "超挖线")
            LOG(f"[INFO] 开挖线数量: {len(excav_lines_all)}")
            LOG(f"[INFO] 超挖线数量: {len(overexc_lines_all)}")
            
            # 获取桩号（使用参数传入的桩号图层）
            station_texts = LayerExtractor.get_texts(msp, pile_layer)
            LOG(f"[INFO] 桩号数量: {len(station_texts)}")
            
            # 构建虚拟断面框
            virtual_boxes = VirtualBoxBuilder.build_from_overexcav(overexc_lines_all)
            LOG(f"[INFO] 虚拟断面框: {len(virtual_boxes)}个")
            
            # 读取地层填充
            strata_hatches = {}
            for layer in strata_layers:
                strata_hatches[layer] = []
                for h in msp.query(f'HATCH[layer=="{layer}"]'):
                    poly = HatchProcessor.to_polygon(h)
                    if poly and not poly.is_empty:
                        strata_hatches[layer].append(poly)
                if strata_hatches[layer]:
                    LOG(f"  {layer}: {len(strata_hatches[layer])}个填充")
            
            # 创建输出文档
            output_doc = ezdxf.readfile(input_path)
            output_msp = output_doc.modelspace()
            
            # 创建图层
            layer_name_elev = f"分层线_{target_elevation}m"
            OutputHelper.ensure_layer(output_doc, layer_name_elev, color=1)
            
            # 结果列表
            results = []
            processed_stations = set()
            station_texts_sorted = sorted(station_texts, key=lambda s: s['y'], reverse=True)
            
            def find_nearest_station(sect_x_center, sect_y_center, used_stations):
                best_station, best_dist = None, float('inf')
                for st in station_texts_sorted:
                    if st['text'] in used_stations: continue
                    dist = ((st['x'] - sect_x_center)**2 * 0.5 + (st['y'] - sect_y_center)**2)**0.5
                    if dist < best_dist:
                        best_dist = dist
                        best_station = st
                return best_station, best_dist
            
            for idx, dmx_data in enumerate(dmx_list):
                sect_x_min = dmx_data['x_min']
                sect_x_max = dmx_data['x_max']
                sect_y_min = dmx_data['y_min']
                sect_y_max = dmx_data['y_max']
                sect_y_center = dmx_data['y_center']
                sect_x_center = (sect_x_min + sect_x_max) / 2
                
                # 桩号匹配
                nearest_st, dist = find_nearest_station(sect_x_center, sect_y_center, processed_stations)
                if nearest_st and dist < 500:
                    station = nearest_st['text'].split(";")[-1].replace("}", "").strip()
                    processed_stations.add(station)
                else:
                    station = f"S{idx+1}"
                
                # 检测标尺并计算分层线Y坐标
                target_line_y = None
                if target_elevation is not None:
                    ruler_scale = RulerDetector.detect_scale(msp, doc, sect_x_min, sect_x_max, sect_y_center, sect_y_min, sect_y_max)
                    
                    if ruler_scale:
                        elev_to_y, y_to_elev = ruler_scale
                        target_line_y = elev_to_y(target_elevation)
                    else:
                        target_line_y = 5.0 * target_elevation - 27.0
                
                # 生成最终断面线（合并辅助断面线）
                if merge_section and aux_lines_all:
                    boundary_box = box(sect_x_min - 20, sect_y_min - 50, sect_x_max + 20, sect_y_max + 50)
                    local_aux = [l for l in aux_lines_all if boundary_box.intersects(l)]
                    if local_aux:
                        # 使用下包络线合并（固定使用lower，不再使用envelope_type参数）
                        final_section = EnvelopeGenerator.generate(dmx_data['line'], local_aux, 'lower')
                    else:
                        final_section = dmx_data['line']
                else:
                    final_section = dmx_data['line']
                
                if final_section is None:
                    final_section = dmx_data['line']
                
                # 构建开挖区域多边形
                sect_coords = list(final_section.coords)
                sect_x_min_actual = min(c[0] for c in sect_coords)
                sect_x_max_actual = max(c[0] for c in sect_coords)
                sect_y_min_actual = min(c[1] for c in sect_coords)
                sect_y_max_actual = max(c[1] for c in sect_coords)
                
                bottom_y = sect_y_min_actual - 50
                total_open_poly = Polygon(sect_coords + [(sect_x_max_actual, bottom_y), (sect_x_min_actual, bottom_y)]).buffer(0)
                
                if total_open_poly.is_empty:
                    result = {'断面名称': station, '分层线高程': target_elevation, '总面积': 0.0}
                    for layer in strata_layers:
                        if distinguish_design:
                            result[f'{layer}_设计'] = 0.0
                            result[f'{layer}_超挖'] = 0.0
                        else:
                            result[layer] = 0.0
                    results.append(result)
                    continue
                
                # 判断分层线位置（根据calc_mode选择计算区域）
                layer_open = None  # 用于存储计算区域
                if target_line_y is None:
                    # 全算量模式：计算整个开挖区域
                    layer_open = total_open_poly
                elif calc_mode == 'below':
                    # 高程线以下模式
                    if target_line_y < sect_y_min_actual:
                        # 分层线在断面底部以下，无面积
                        result = {'断面名称': station, '分层线高程': target_elevation, '总面积': 0.0}
                        for layer in strata_layers:
                            if distinguish_design:
                                result[f'{layer}_设计'] = 0.0
                                result[f'{layer}_超挖'] = 0.0
                            else:
                                result[layer] = 0.0
                        results.append(result)
                        continue
                    elif target_line_y >= sect_y_max_actual:
                        # 分层线在断面顶部以上，计算整个开挖区域
                        layer_open = total_open_poly
                    else:
                        # 正常分层计算：取分层线以下的区域
                        below_layer_poly = box(sect_x_min_actual - 10, sect_y_min_actual - 100, sect_x_max_actual + 10, target_line_y)
                        layer_open = total_open_poly.intersection(below_layer_poly)
                else:
                    # 高程线以上模式 (calc_mode == 'above')
                    if target_line_y > sect_y_max_actual:
                        # 分层线在断面顶部以上，无面积
                        result = {'断面名称': station, '分层线高程': target_elevation, '总面积': 0.0}
                        for layer in strata_layers:
                            if distinguish_design:
                                result[f'{layer}_设计'] = 0.0
                                result[f'{layer}_超挖'] = 0.0
                            else:
                                result[layer] = 0.0
                        results.append(result)
                        continue
                    elif target_line_y <= sect_y_min_actual:
                        # 分层线在断面底部以下，计算整个开挖区域
                        layer_open = total_open_poly
                    else:
                        # 正常分层计算：取分层线以上的区域
                        above_layer_poly = box(sect_x_min_actual - 10, target_line_y, sect_x_max_actual + 10, sect_y_max_actual + 100)
                        layer_open = total_open_poly.intersection(above_layer_poly)
                
                if layer_open is None or layer_open.is_empty:
                    result = {'断面名称': station, '分层线高程': target_elevation, '总面积': 0.0}
                    for layer in strata_layers:
                        if distinguish_design:
                            result[f'{layer}_设计'] = 0.0
                            result[f'{layer}_超挖'] = 0.0
                        else:
                            result[layer] = 0.0
                    results.append(result)
                    continue
                
                if layer_open is None:
                    layer_open = total_open_poly  # 默认使用整个开挖区域
                
                # 绘制高程线（仅在有目标高程时绘制）
                if target_line_y is not None:
                    # 根据calc_mode决定绘制位置
                    if calc_mode == 'below' and target_line_y > sect_y_min_actual:
                        line_pts = [(sect_x_min_actual - 5, target_line_y), (sect_x_max_actual + 5, target_line_y)]
                        output_msp.add_lwpolyline(line_pts, dxfattribs={'layer': layer_name_elev, 'color': 1})
                    elif calc_mode == 'above' and target_line_y < sect_y_max_actual:
                        line_pts = [(sect_x_min_actual - 5, target_line_y), (sect_x_max_actual + 5, target_line_y)]
                        output_msp.add_lwpolyline(line_pts, dxfattribs={'layer': layer_name_elev, 'color': 1})
                
                # 构建设计区多边形
                design_polygon = None
                if distinguish_design:
                    boundary_box = box(sect_x_min_actual - 20, sect_y_min_actual - 50, sect_x_max_actual + 20, sect_y_max_actual + 50)
                    excav_in_section = [l for l in excav_lines_all if boundary_box.intersects(l)]
                    if excav_in_section:
                        design_polygon = _build_design_polygon(excav_in_section, sect_x_min_actual, sect_x_max_actual)
                
                # 统计各地层面积
                boundary_box = box(sect_x_min_actual - 20, sect_y_min_actual - 50, sect_x_max_actual + 20, sect_y_max_actual + 50)
                strata_areas = {}
                total_area = 0.0
                
                for layer in strata_layers:
                    design_area = 0.0
                    over_area = 0.0
                    total_layer_area = 0.0
                    
                    design_polys = []
                    over_polys = []
                    
                    for h_poly in strata_hatches[layer]:
                        try:
                            if not boundary_box.intersects(h_poly): continue
                            
                            inter = h_poly.intersection(layer_open)
                            if inter.is_empty: continue
                            
                            if distinguish_design and design_polygon:
                                design_part = inter.intersection(design_polygon)
                                over_part = inter.difference(design_polygon)
                                
                                if not design_part.is_empty:
                                    if isinstance(design_part, Polygon):
                                        design_area += design_part.area
                                        design_polys.append(design_part)
                                    elif hasattr(design_part, 'geoms'):
                                        for g in design_part.geoms:
                                            if isinstance(g, Polygon):
                                                design_area += g.area
                                                design_polys.append(g)
                                
                                if not over_part.is_empty:
                                    if isinstance(over_part, Polygon):
                                        over_area += over_part.area
                                        over_polys.append(over_part)
                                    elif hasattr(over_part, 'geoms'):
                                        for g in over_part.geoms:
                                            if isinstance(g, Polygon):
                                                over_area += g.area
                                                over_polys.append(g)
                            else:
                                if isinstance(inter, Polygon):
                                    total_layer_area += inter.area
                                    design_polys.append(inter)
                                elif hasattr(inter, 'geoms'):
                                    for g in inter.geoms:
                                        if isinstance(g, Polygon):
                                            total_layer_area += g.area
                                            design_polys.append(g)
                        except: pass
                    
                    if distinguish_design:
                        strata_areas[f'{layer}_设计'] = round(design_area, 3)
                        strata_areas[f'{layer}_超挖'] = round(over_area, 3)
                        total_area += design_area + over_area
                        
                        # 输出填充
                        color_idx = Config.STRATA_COLORS.get(layer, 7)
                        rgb_color = Config.HIGH_CONTRAST_COLORS[strata_layers.index(layer) % len(Config.HIGH_CONTRAST_COLORS)]
                        
                        for poly in design_polys:
                            HatchProcessor.add_simple(output_msp, poly, f"{target_elevation}m_{layer}_设计", color_idx, rgb_color)
                        for poly in over_polys:
                            HatchProcessor.add_simple(output_msp, poly, f"{target_elevation}m_{layer}_超挖", color_idx, rgb_color)
                    else:
                        strata_areas[layer] = round(total_layer_area, 3)
                        total_area += total_layer_area
                        
                        if total_layer_area > 0.01:
                            color_idx = Config.STRATA_COLORS.get(layer, 7)
                            for poly in design_polys:
                                HatchProcessor.add_simple(output_msp, poly, f"{target_elevation}m_{layer}", color_idx)
                
                result = {
                    '断面名称': station,
                    '分层线高程': target_elevation,
                    **strata_areas,
                    '总面积': round(total_area, 3)
                }
                results.append(result)
                
                if (idx + 1) % 50 == 0:
                    LOG(f"  已处理 {idx+1}/{len(dmx_list)} 个断面...")
            
            # 排序结果
            results.sort(key=lambda x: StationMatcher.sort_key(x['断面名称']))
            
            # 保存DXF
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            base_name = os.path.basename(input_path).replace('.dxf', '')
            output_dxf_dir = output_dir if output_dir else os.path.dirname(input_path)
            output_dxf = os.path.join(output_dxf_dir, f"{base_name}_{target_elevation}m分层_{timestamp}.dxf")
            output_doc.saveas(output_dxf)
            LOG(f"[INFO] DXF文件已保存: {output_dxf}")
            
            # 生成Excel
            if results:
                df = pd.DataFrame(results)
                # 根据calc_mode决定文件名
                mode_suffix = "以下面积" if calc_mode == 'below' else "以上面积"
                if target_elevation is not None:
                    output_xlsx = os.path.join(output_dxf_dir, f"{base_name}_{target_elevation}m{mode_suffix}_{timestamp}.xlsx")
                else:
                    output_xlsx = os.path.join(output_dxf_dir, f"{base_name}_全算量_{timestamp}.xlsx")
                
                with pd.ExcelWriter(output_xlsx, engine='openpyxl') as writer:
                    if distinguish_design:
                        # 设计量sheet
                        design_cols = ['断面名称'] + [c for c in df.columns if c.endswith('_设计')]
                        df_design = df[design_cols].copy()
                        df_design.columns = ['断面名称'] + [c.replace('_设计', '') for c in df.columns if c.endswith('_设计')]
                        df_design.to_excel(writer, sheet_name='设计量', index=False)
                        
                        # 超挖量sheet
                        over_cols = ['断面名称'] + [c for c in df.columns if c.endswith('_超挖')]
                        df_over = df[over_cols].copy()
                        df_over.columns = ['断面名称'] + [c.replace('_超挖', '') for c in df.columns if c.endswith('_超挖')]
                        df_over.to_excel(writer, sheet_name='超挖量', index=False)
                        
                        # 总量sheet
                        df_total = df[['断面名称']].copy()
                        for layer in strata_layers:
                            design_col = f'{layer}_设计'
                            over_col = f'{layer}_超挖'
                            total_val = 0.0
                            if design_col in df.columns: total_val = total_val + df[design_col].fillna(0)
                            if over_col in df.columns: total_val = total_val + df[over_col].fillna(0)
                            df_total[layer] = total_val
                        df_total.to_excel(writer, sheet_name='总量', index=False)
                    else:
                        df.to_excel(writer, sheet_name='明细表', index=False)
                    
                    # 地层汇总
                    if distinguish_design:
                        summary_data = {'地层': [], '设计面积(㎡)': [], '超挖面积(㎡)': []}
                        for layer in strata_layers:
                            summary_data['地层'].append(layer)
                            design_col = f'{layer}_设计'
                            over_col = f'{layer}_超挖'
                            summary_data['设计面积(㎡)'].append(df[design_col].sum() if design_col in df.columns else 0.0)
                            summary_data['超挖面积(㎡)'].append(df[over_col].sum() if over_col in df.columns else 0.0)
                        df_summary = pd.DataFrame(summary_data)
                        df_summary['总面积(㎡)'] = df_summary['设计面积(㎡)'] + df_summary['超挖面积(㎡)']
                    else:
                        strata_cols = [c for c in df.columns if '级' in c]
                        summary_data = {'地层': strata_cols, '面积(㎡)': [df[c].sum() for c in strata_cols]}
                        df_summary = pd.DataFrame(summary_data)
                    df_summary.to_excel(writer, sheet_name='地层汇总', index=False)
                    
                    # 汇总
                    mode_text = "以下" if calc_mode == 'below' else "以上"
                    total_data = {'统计项': ['总断面数', f'{target_elevation}m{mode_text}总面积'], '数值': [len(results), df['总面积'].sum()]}
                    pd.DataFrame(total_data).to_excel(writer, sheet_name='汇总', index=False)
                
                LOG(f"[OK] 处理完成！")
                LOG(f"   DXF: {os.path.basename(output_dxf)}")
                LOG(f"   Excel: {os.path.basename(output_xlsx)}")
                LOG(f"   总断面数: {len(results)}")
                LOG(f"   {target_elevation}m{mode_text}总面积: {df['总面积'].sum():.3f} ㎡")
            else:
                LOG("[WARN] 未生成任何数据")
    
    except Exception as e:
        LOG(f"[ERROR] 分层算量执行错误: {e}")
        LOG(traceback.format_exc())


# ==================== 5. 回淤计算 (backfill) ====================

def run_backfill(params, LOG):
    """回淤计算任务
    
    计算DMX与设计断面线之间的回淤面积（上包络线与DMX之间的区域）
    
    Args:
        params: {
            'files': [文件列表],
            '断面线图层': 断面线图层名（默认DMX），
            '设计断面线图层': 设计断面线图层（如20260317），
            '输出目录': 输出路径
        }
    """
    try:
        file_list = params.get('files', [])
        if not file_list:
            LOG("[WARN] 请先选择 DXF 文件。")
            return
        
        # 参数互换：前端第一个输入框是设计断面线图层，第二个是断面线图层
        design_layer = params.get('断面线图层', '')  # 前端第一个输入
        section_layer = params.get('设计断面线图层', 'DMX')  # 前端第二个输入
        output_dir = params.get('输出目录')
        
        if not design_layer:
            LOG("[ERROR] 请指定设计断面线图层名称")
            return
        
        LOG(f"[INFO] 设计断面线图层: {design_layer}")
        LOG(f"[INFO] 断面线图层: {section_layer}")
        
        for input_path in file_list:
            LOG(f"--- [WAIT] 正在处理: {os.path.basename(input_path)} ---")
            
            doc = ezdxf.readfile(input_path)
            msp = doc.modelspace()
            
            # 获取设计断面线（用于生成上包络线）
            design_lines_all = LayerExtractor.get_lines(msp, design_layer)
            design_lines_all = sorted(design_lines_all, key=lambda l: l.bounds[1], reverse=True)
            LOG(f"[INFO] 设计断面线数量: {len(design_lines_all)}")
            
            # 获取DMX断面线
            dmx_list = _get_entity_list(msp, section_layer)
            dmx_list = sorted(dmx_list, key=lambda d: d['y_center'], reverse=True)
            LOG(f"[INFO] {section_layer}数量: {len(dmx_list)}")
            
            # 获取超挖线构建虚拟框
            overexc_lines_all = LayerExtractor.get_lines(msp, "超挖线")
            virtual_boxes = VirtualBoxBuilder.build_from_overexcav(overexc_lines_all)
            LOG(f"[INFO] 虚拟断面框: {len(virtual_boxes)}个")
            
            # 获取桩号
            station_texts = LayerExtractor.get_texts(msp, "0-桩号")
            LOG(f"[INFO] 桩号数量: {len(station_texts)}")
            
            # 创建输出文档
            output_doc = ezdxf.readfile(input_path)
            output_msp = output_doc.modelspace()
            
            # 创建回淤填充图层
            backfill_layer = "回淤面积填充"
            OutputHelper.ensure_layer(output_doc, backfill_layer, color=1)
            
            results = []
            processed_stations = set()
            station_texts_sorted = sorted(station_texts, key=lambda s: s['y'], reverse=True)
            
            def find_nearest_station(sect_x_center, sect_y_center, used_stations):
                best_station, best_dist = None, float('inf')
                for st in station_texts_sorted:
                    if st['text'] in used_stations: continue
                    dist = ((st['x'] - sect_x_center)**2 * 0.5 + (st['y'] - sect_y_center)**2)**0.5
                    if dist < best_dist:
                        best_dist = dist
                        best_station = st
                return best_station, best_dist
            
            for idx, dmx_data in enumerate(dmx_list):
                sect_x_min = dmx_data['x_min']
                sect_x_max = dmx_data['x_max']
                sect_y_min = dmx_data['y_min']
                sect_y_max = dmx_data['y_max']
                sect_y_center = dmx_data['y_center']
                sect_x_center = (sect_x_min + sect_x_max) / 2
                
                # 桩号匹配
                nearest_st, dist = find_nearest_station(sect_x_center, sect_y_center, processed_stations)
                if nearest_st and dist < 500:
                    station = nearest_st['text'].split(";")[-1].replace("}", "").strip()
                    processed_stations.add(station)
                else:
                    station = f"S{idx+1}"
                
                LOG(f"处理断面 {idx+1}/{len(dmx_list)}: {station}")
                
                # 获取局部设计断面线
                boundary_box = box(sect_x_min - 20, sect_y_min - 50, sect_x_max + 20, sect_y_max + 50)
                local_design_lines = [l for l in design_lines_all if boundary_box.intersects(l)]
                
                if not local_design_lines:
                    LOG(f"  警告：未找到设计断面线，跳过")
                    results.append({'桩号': station, '回淤面积': 0.0})
                    continue
                
                # 生成上包络线（取最大Y值）
                upper_envelope = EnvelopeGenerator.generate(dmx_data['line'], local_design_lines, 'upper')
                
                if upper_envelope is None:
                    LOG(f"  警告：上包络线生成失败，跳过")
                    results.append({'桩号': station, '回淤面积': 0.0})
                    continue
                
                # 获取范围
                dmx_coords = list(dmx_data['line'].coords)
                envelope_coords = list(upper_envelope.coords)
                
                dmx_x_min = min(c[0] for c in dmx_coords)
                dmx_x_max = max(c[0] for c in dmx_coords)
                envelope_x_min = min(c[0] for c in envelope_coords)
                envelope_x_max = max(c[0] for c in envelope_coords)
                
                common_x_min = max(dmx_x_min, envelope_x_min)
                common_x_max = min(dmx_x_max, envelope_x_max)
                
                if common_x_max <= common_x_min:
                    LOG(f"  警告：DMX与上包络线X范围无交集，跳过")
                    results.append({'桩号': station, '回淤面积': 0.0})
                    continue
                
                # 采样计算回淤区域 - 使用更精细的采样步长
                # 根据X范围动态计算采样点数，确保精度
                x_range = common_x_max - common_x_min
                num_samples = max(int(x_range / 0.5) + 1, 50)  # 每0.5单位一个采样点，最少50个点
                
                x_samples = []
                envelope_y_samples = []
                dmx_y_samples = []
                
                for i in range(num_samples + 1):
                    x_current = common_x_min + (common_x_max - common_x_min) * i / num_samples
                    
                    envelope_y = LineUtils.get_y_at_x(upper_envelope, x_current)
                    dmx_y = LineUtils.get_y_at_x(dmx_data['line'], x_current)
                    
                    if envelope_y is not None and dmx_y is not None:
                        x_samples.append(x_current)
                        envelope_y_samples.append(envelope_y)
                        dmx_y_samples.append(dmx_y)
                
                if len(x_samples) < 2:
                    LOG(f"  警告：采样点不足，跳过")
                    results.append({'桩号': station, '回淤面积': 0.0})
                    continue
                
                # 构建回淤区域多边形
                # 上边界：上包络线（从左到右）
                # 下边界：DMX（从右到左）
                polygon_coords = []
                for x, y in zip(x_samples, envelope_y_samples):
                    polygon_coords.append((x, y))
                for i in range(len(x_samples) - 1, -1, -1):
                    polygon_coords.append((x_samples[i], dmx_y_samples[i]))
                
                if len(polygon_coords) >= 3:
                    backfill_polygon = Polygon(polygon_coords)
                    if not backfill_polygon.is_valid:
                        backfill_polygon = backfill_polygon.buffer(0)
                    
                    backfill_area = backfill_polygon.area
                    
                    # 添加填充到输出
                    HatchProcessor.add_simple(output_msp, backfill_polygon, backfill_layer, color_index=1, rgb_color=(255, 0, 0))
                else:
                    backfill_area = 0.0
                
                LOG(f"  回淤面积: {backfill_area:.2f}")
                results.append({'桩号': station, '回淤面积': round(backfill_area, 2)})
            
            # 排序结果
            results.sort(key=lambda x: StationMatcher.sort_key(x['桩号']))
            
            # 保存DXF
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            base_name = os.path.basename(input_path).replace('.dxf', '')
            output_dxf_dir = output_dir if output_dir else os.path.dirname(input_path)
            output_dxf = os.path.join(output_dxf_dir, f"{base_name}_回淤_{timestamp}.dxf")
            output_doc.saveas(output_dxf)
            LOG(f"[INFO] DXF文件已保存: {output_dxf}")
            
            # 生成Excel
            if results:
                df = pd.DataFrame(results)
                output_xlsx = os.path.join(output_dxf_dir, f"{base_name}_回淤面积_{timestamp}.xlsx")
                
                with pd.ExcelWriter(output_xlsx, engine='openpyxl') as writer:
                    df.to_excel(writer, sheet_name='回淤面积汇总', index=False)
                    
                    # 带合计
                    summary_row = pd.DataFrame([{'桩号': '合计', '回淤面积': df['回淤面积'].sum()}])
                    pd.concat([df, summary_row], ignore_index=True).to_excel(writer, sheet_name='带合计', index=False)
                
                LOG(f"[OK] 处理完成！")
                LOG(f"   DXF: {os.path.basename(output_dxf)}")
                LOG(f"   Excel: {os.path.basename(output_xlsx)}")
                LOG(f"   总回淤面积: {df['回淤面积'].sum():.2f} ㎡")
            else:
                LOG("[WARN] 未生成任何数据")
    
    except Exception as e:
        LOG(f"[ERROR] 回淤计算执行错误: {e}")
        LOG(traceback.format_exc())


# ==================== 6. 分层算量+回淤计算合并 (autosection_backfill) ====================

def run_autosection_backfill(params, LOG):
    """分层算量与回淤计算合并任务
    
    在同一次运行中完成：
    1. 分层算量：计算各地层在目标高程以下/以上的面积（基于更新断面线）
    2. 回淤计算：计算DMX与更新断面线之间的回淤面积（DMX在下，更新断面线在上）
    
    Args:
        params: {
            'files': [文件列表],
            '目标高程': 高程值（如-10.0），
            '桩号图层': 桩号图层名，
            '设计断面线图层': DMX图层名（原始断面线，回淤下边界），
            '更新断面线图层': 更新断面线图层名（分层算量断面线，回淤上边界），
            '合并断面线': True/False（是否合并设计断面线与更新断面线，使用下包络线），
            '计算模式': 'below'高程线以下或'above'高程线以上，
            '区分设计超挖': True/False，
            '输出目录': 输出路径
        }
    """
    try:
        file_list = params.get('files', [])
        if not file_list:
            LOG("[WARN] 请先选择 DXF 文件。")
            return
        
        # ========== 分层算量参数 ==========
        elevation_str = params.get('目标高程', '').strip()
        if elevation_str:
            try:
                target_elevation = float(elevation_str)
            except ValueError:
                LOG("[WARN] 目标高程格式错误，将使用全算量模式")
                target_elevation = None
        else:
            target_elevation = None  # 全算量模式
        
        # 桩号图层
        pile_layer = params.get('桩号图层', '0-桩号')
        
        # DMX图层（原始断面线）- 回淤的下边界
        dmx_layer = params.get('设计断面线图层', 'DMX')
        
        # 更新断面线图层 - 分层算量的断面线，回淤的上边界
        update_layer = params.get('更新断面线图层', '')
        
        # 合并断面线：是否使用下包络线合并设计断面线与更新断面线
        merge_section = params.get('合并断面线', False)
        if isinstance(merge_section, str):
            merge_section = merge_section.lower() in ('true', '1', 'yes', '是')
        
        # 计算模式：高程线以下或以上
        calc_mode = params.get('计算模式', 'below')  # 'below'或'above'
        
        distinguish_design = params.get('区分设计超挖', False)
        if isinstance(distinguish_design, str):
            distinguish_design = distinguish_design.lower() in ('true', '1', 'yes', '是')
        
        output_dir = params.get('输出目录')
        
        # 检查必要参数
        if not update_layer:
            LOG("[ERROR] 请指定更新断面线图层名称")
            return
        
        # 日志输出参数
        LOG("=" * 60)
        LOG("[INFO] 合并任务：分层算量 + 回淤计算")
        LOG("=" * 60)
        if target_elevation is not None:
            LOG(f"[INFO] 目标高程: {target_elevation}m")
        else:
            LOG(f"[INFO] 全算量模式（未指定目标高程）")
        LOG(f"[INFO] 桩号图层: {pile_layer}")
        LOG(f"[INFO] 设计断面线图层（DMX）: {dmx_layer}")
        LOG(f"[INFO] 更新断面线图层: {update_layer}")
        LOG(f"[INFO] 合并断面线: {'是' if merge_section else '否'}")
        LOG(f"[INFO] 计算模式: {'高程线以下' if calc_mode == 'below' else '高程线以上'}")
        LOG(f"[INFO] 区分设计/超挖: {'是' if distinguish_design else '否'}")
        LOG("=" * 60)
        
        for input_path in file_list:
            LOG(f"\n--- [WAIT] 正在处理: {os.path.basename(input_path)} ---")
            
            doc = ezdxf.readfile(input_path)
            msp = doc.modelspace()
            
            all_layers = [l.dxf.name for l in doc.layers]
            LOG(f"[INFO] 图层总数: {len(all_layers)}")
            
            # ========== 数据准备（共用） ==========
            # 获取地层图层
            strata_layers = sorted(
                [l for l in all_layers if re.match(r'^\d+级', l)],
                key=StationMatcher.strata_sort_key
            )
            LOG(f"[INFO] 地层图层: {strata_layers}")
            
            # 获取DMX列表（原始断面线，回淤的下边界）
            dmx_list = _get_entity_list(msp, dmx_layer)
            dmx_list = sorted(dmx_list, key=lambda d: d['y_center'], reverse=True)
            LOG(f"[INFO] {dmx_layer}数量（原始断面线）: {len(dmx_list)}")
            
            # 获取更新断面线（分层算量的断面线，回淤的上边界）
            update_lines_all = LayerExtractor.get_lines(msp, update_layer)
            update_lines_all = sorted(update_lines_all, key=lambda l: l.bounds[1], reverse=True)
            LOG(f"[INFO] {update_layer}数量（更新断面线）: {len(update_lines_all)}")
            
            # 获取开挖线和超挖线
            excav_lines_all = LayerExtractor.get_lines(msp, "开挖线")
            overexc_lines_all = LayerExtractor.get_lines(msp, "超挖线")
            LOG(f"[INFO] 开挖线数量: {len(excav_lines_all)}")
            LOG(f"[INFO] 超挖线数量: {len(overexc_lines_all)}")
            
            # 获取桩号（使用参数传入的桩号图层）
            station_texts = LayerExtractor.get_texts(msp, pile_layer)
            LOG(f"[INFO] 桩号数量: {len(station_texts)}")
            
            # 构建虚拟断面框
            virtual_boxes = VirtualBoxBuilder.build_from_overexcav(overexc_lines_all)
            LOG(f"[INFO] 虚拟断面框: {len(virtual_boxes)}个")
            
            # 读取地层填充
            strata_hatches = {}
            for layer in strata_layers:
                strata_hatches[layer] = []
                for h in msp.query(f'HATCH[layer=="{layer}"]'):
                    poly = HatchProcessor.to_polygon(h)
                    if poly and not poly.is_empty:
                        strata_hatches[layer].append(poly)
                if strata_hatches[layer]:
                    LOG(f"  {layer}: {len(strata_hatches[layer])}个填充")
            
            # 创建输出文档
            output_doc = ezdxf.readfile(input_path)
            output_msp = output_doc.modelspace()
            
            # 创建图层
            layer_name_elev = f"分层线_{target_elevation}m" if target_elevation else "全算量"
            OutputHelper.ensure_layer(output_doc, layer_name_elev, color=1)
            
            # 回淤填充图层
            backfill_layer = "回淤面积填充"
            OutputHelper.ensure_layer(output_doc, backfill_layer, color=1)
            
            # ========== 结果列表 ==========
            section_results = []  # 分层算量结果
            backfill_results = []  # 回淤计算结果
            processed_stations = set()
            station_texts_sorted = sorted(station_texts, key=lambda s: s['y'], reverse=True)
            
            def find_nearest_station(sect_x_center, sect_y_center, used_stations):
                best_station, best_dist = None, float('inf')
                for st in station_texts_sorted:
                    if st['text'] in used_stations: continue
                    dist = ((st['x'] - sect_x_center)**2 * 0.5 + (st['y'] - sect_y_center)**2)**0.5
                    if dist < best_dist:
                        best_dist = dist
                        best_station = st
                return best_station, best_dist
            
            # ========== 逐断面处理 ==========
            LOG("\n[INFO] ===== 开始逐断面处理 =====")
            
            for idx, dmx_data in enumerate(dmx_list):
                sect_x_min = dmx_data['x_min']
                sect_x_max = dmx_data['x_max']
                sect_y_min = dmx_data['y_min']
                sect_y_max = dmx_data['y_max']
                sect_y_center = dmx_data['y_center']
                sect_x_center = (sect_x_min + sect_x_max) / 2
                
                # 桩号匹配
                nearest_st, dist = find_nearest_station(sect_x_center, sect_y_center, processed_stations)
                if nearest_st and dist < 500:
                    station = nearest_st['text'].split(";")[-1].replace("}", "").strip()
                    processed_stations.add(station)
                else:
                    station = f"S{idx+1}"
                
                # ========== 分层算量部分（基于更新断面线） ==========
                # 检测标尺并计算分层线Y坐标
                target_line_y = None
                if target_elevation is not None:
                    ruler_scale = RulerDetector.detect_scale(msp, doc, sect_x_min, sect_x_max, sect_y_center, sect_y_min, sect_y_max)
                    
                    if ruler_scale:
                        elev_to_y, y_to_elev = ruler_scale
                        target_line_y = elev_to_y(target_elevation)
                    else:
                        target_line_y = 5.0 * target_elevation - 27.0
                
                # 获取局部更新断面线（用于分层算量）
                boundary_box = box(sect_x_min - 20, sect_y_min - 50, sect_x_max + 20, sect_y_max + 50)
                local_update_lines = [l for l in update_lines_all if boundary_box.intersects(l)]
                
                # 生成最终断面线（根据merge_section参数决定是否合并）
                if merge_section and local_update_lines:
                    # 合并模式：使用下包络线合并设计断面线与更新断面线
                    final_section = EnvelopeGenerator.generate(dmx_data['line'], local_update_lines, 'lower')
                elif local_update_lines:
                    # 不合并模式：只使用更新断面线（取第一条）
                    final_section = local_update_lines[0]
                else:
                    final_section = dmx_data['line']
                
                if final_section is None:
                    final_section = dmx_data['line']
                
                # 构建开挖区域多边形
                sect_coords = list(final_section.coords)
                sect_x_min_actual = min(c[0] for c in sect_coords)
                sect_x_max_actual = max(c[0] for c in sect_coords)
                sect_y_min_actual = min(c[1] for c in sect_coords)
                sect_y_max_actual = max(c[1] for c in sect_coords)
                
                bottom_y = sect_y_min_actual - 50
                total_open_poly = Polygon(sect_coords + [(sect_x_max_actual, bottom_y), (sect_x_min_actual, bottom_y)]).buffer(0)
                
                # 分层算量计算（根据calc_mode选择计算区域）
                layer_open = None
                if total_open_poly.is_empty:
                    strata_areas = {}
                    total_section_area = 0.0
                    for layer in strata_layers:
                        if distinguish_design:
                            strata_areas[f'{layer}_设计'] = 0.0
                            strata_areas[f'{layer}_超挖'] = 0.0
                        else:
                            strata_areas[layer] = 0.0
                elif target_line_y is None:
                    # 全算量模式：计算整个开挖区域
                    layer_open = total_open_poly
                elif calc_mode == 'below':
                    # 高程线以下模式
                    if target_line_y < sect_y_min_actual:
                        # 分层线在断面底部以下，无面积
                        strata_areas = {}
                        total_section_area = 0.0
                        for layer in strata_layers:
                            if distinguish_design:
                                strata_areas[f'{layer}_设计'] = 0.0
                                strata_areas[f'{layer}_超挖'] = 0.0
                            else:
                                strata_areas[layer] = 0.0
                    elif target_line_y >= sect_y_max_actual:
                        # 分层线在断面顶部以上，计算整个开挖区域
                        layer_open = total_open_poly
                    else:
                        # 正常分层计算：取分层线以下的区域
                        below_layer_poly = box(sect_x_min_actual - 10, sect_y_min_actual - 100, sect_x_max_actual + 10, target_line_y)
                        layer_open = total_open_poly.intersection(below_layer_poly)
                else:
                    # 高程线以上模式 (calc_mode == 'above')
                    if target_line_y > sect_y_max_actual:
                        # 分层线在断面顶部以上，无面积
                        strata_areas = {}
                        total_section_area = 0.0
                        for layer in strata_layers:
                            if distinguish_design:
                                strata_areas[f'{layer}_设计'] = 0.0
                                strata_areas[f'{layer}_超挖'] = 0.0
                            else:
                                strata_areas[layer] = 0.0
                    elif target_line_y <= sect_y_min_actual:
                        # 分层线在断面底部以下，计算整个开挖区域
                        layer_open = total_open_poly
                    else:
                        # 正常分层计算：取分层线以上的区域
                        above_layer_poly = box(sect_x_min_actual - 10, target_line_y, sect_x_max_actual + 10, sect_y_max_actual + 100)
                        layer_open = total_open_poly.intersection(above_layer_poly)
                
                # 计算地层面积
                if layer_open is not None and not layer_open.is_empty:
                    # 绘制高程线（仅在有目标高程时绘制）
                    if target_line_y is not None:
                        # 根据calc_mode决定绘制位置
                        if calc_mode == 'below' and target_line_y > sect_y_min_actual:
                            line_pts = [(sect_x_min_actual - 5, target_line_y), (sect_x_max_actual + 5, target_line_y)]
                            output_msp.add_lwpolyline(line_pts, dxfattribs={'layer': layer_name_elev, 'color': 1})
                        elif calc_mode == 'above' and target_line_y < sect_y_max_actual:
                            line_pts = [(sect_x_min_actual - 5, target_line_y), (sect_x_max_actual + 5, target_line_y)]
                            output_msp.add_lwpolyline(line_pts, dxfattribs={'layer': layer_name_elev, 'color': 1})
                    
                    # 构建设计区多边形
                    design_polygon = None
                    if distinguish_design:
                        boundary_box = box(sect_x_min_actual - 20, sect_y_min_actual - 50, sect_x_max_actual + 20, sect_y_max_actual + 50)
                        excav_in_section = [l for l in excav_lines_all if boundary_box.intersects(l)]
                        if excav_in_section:
                            design_polygon = _build_design_polygon(excav_in_section, sect_x_min_actual, sect_x_max_actual)
                    
                    # 统计各地层面积
                    boundary_box = box(sect_x_min_actual - 20, sect_y_min_actual - 50, sect_x_max_actual + 20, sect_y_max_actual + 50)
                    strata_areas = {}
                    total_section_area = 0.0
                    
                    for layer in strata_layers:
                        design_area = 0.0
                        over_area = 0.0
                        total_layer_area = 0.0
                        
                        design_polys = []
                        over_polys = []
                        
                        for h_poly in strata_hatches[layer]:
                            try:
                                if not boundary_box.intersects(h_poly): continue
                                
                                inter = h_poly.intersection(layer_open)
                                if inter.is_empty: continue
                                
                                if distinguish_design and design_polygon:
                                    design_part = inter.intersection(design_polygon)
                                    over_part = inter.difference(design_polygon)
                                    
                                    if not design_part.is_empty:
                                        if isinstance(design_part, Polygon):
                                            design_area += design_part.area
                                            design_polys.append(design_part)
                                        elif hasattr(design_part, 'geoms'):
                                            for g in design_part.geoms:
                                                if isinstance(g, Polygon):
                                                    design_area += g.area
                                                    design_polys.append(g)
                                    
                                    if not over_part.is_empty:
                                        if isinstance(over_part, Polygon):
                                            over_area += over_part.area
                                            over_polys.append(over_part)
                                        elif hasattr(over_part, 'geoms'):
                                            for g in over_part.geoms:
                                                if isinstance(g, Polygon):
                                                    over_area += g.area
                                                    over_polys.append(g)
                                else:
                                    if isinstance(inter, Polygon):
                                        total_layer_area += inter.area
                                        design_polys.append(inter)
                                    elif hasattr(inter, 'geoms'):
                                        for g in inter.geoms:
                                            if isinstance(g, Polygon):
                                                total_layer_area += g.area
                                                design_polys.append(g)
                            except: pass
                        
                        if distinguish_design:
                            strata_areas[f'{layer}_设计'] = round(design_area, 3)
                            strata_areas[f'{layer}_超挖'] = round(over_area, 3)
                            total_section_area += design_area + over_area
                            
                            # 输出填充
                            color_idx = Config.STRATA_COLORS.get(layer, 7)
                            rgb_color = Config.HIGH_CONTRAST_COLORS[strata_layers.index(layer) % len(Config.HIGH_CONTRAST_COLORS)]
                            
                            for poly in design_polys:
                                HatchProcessor.add_simple(output_msp, poly, f"{target_elevation}m_{layer}_设计", color_idx, rgb_color)
                            for poly in over_polys:
                                HatchProcessor.add_simple(output_msp, poly, f"{target_elevation}m_{layer}_超挖", color_idx, rgb_color)
                        else:
                            strata_areas[layer] = round(total_layer_area, 3)
                            total_section_area += total_layer_area
                            
                            if total_layer_area > 0.01:
                                color_idx = Config.STRATA_COLORS.get(layer, 7)
                                for poly in design_polys:
                                    HatchProcessor.add_simple(output_msp, poly, f"{target_elevation}m_{layer}", color_idx)
                else:
                    strata_areas = {}
                    total_section_area = 0.0
                    for layer in strata_layers:
                        if distinguish_design:
                            strata_areas[f'{layer}_设计'] = 0.0
                            strata_areas[f'{layer}_超挖'] = 0.0
                        else:
                            strata_areas[layer] = 0.0
                
                section_result = {
                    '断面名称': station,
                    '分层线高程': target_elevation,
                    **strata_areas,
                    '总面积': round(total_section_area, 3)
                }
                section_results.append(section_result)
                
                # ========== 回淤计算部分（DMX在下，更新断面线在上） ==========
                backfill_area = 0.0
                if local_update_lines:
                    # 生成上包络线（更新断面线在上，取最大Y值）
                    # 回淤区域：DMX（下边界）与更新断面线（上边界）之间的区域
                    upper_envelope = EnvelopeGenerator.generate(dmx_data['line'], local_update_lines, 'upper')
                    
                    if upper_envelope:
                        # 获取范围
                        dmx_coords = list(dmx_data['line'].coords)
                        envelope_coords = list(upper_envelope.coords)
                        
                        dmx_x_min = min(c[0] for c in dmx_coords)
                        dmx_x_max = max(c[0] for c in dmx_coords)
                        envelope_x_min = min(c[0] for c in envelope_coords)
                        envelope_x_max = max(c[0] for c in envelope_coords)
                        
                        common_x_min = max(dmx_x_min, envelope_x_min)
                        common_x_max = min(dmx_x_max, envelope_x_max)
                        
                        if common_x_max > common_x_min:
                            # 采样计算回淤区域
                            x_range = common_x_max - common_x_min
                            num_samples = max(int(x_range / 0.5) + 1, 50)
                            
                            x_samples = []
                            envelope_y_samples = []
                            dmx_y_samples = []
                            
                            for i in range(num_samples + 1):
                                x_current = common_x_min + (common_x_max - common_x_min) * i / num_samples
                                
                                # 上边界：更新断面线（上包络线，Y值较大）
                                envelope_y = LineUtils.get_y_at_x(upper_envelope, x_current)
                                # 下边界：DMX（原始断面线，Y值较小）
                                dmx_y = LineUtils.get_y_at_x(dmx_data['line'], x_current)
                                
                                if envelope_y is not None and dmx_y is not None:
                                    x_samples.append(x_current)
                                    envelope_y_samples.append(envelope_y)
                                    dmx_y_samples.append(dmx_y)
                            
                            if len(x_samples) >= 2:
                                # 构建回淤区域多边形
                                # 上边界：更新断面线（从左到右）
                                # 下边界：DMX（从右到左）
                                polygon_coords = []
                                for x, y in zip(x_samples, envelope_y_samples):
                                    polygon_coords.append((x, y))
                                for i in range(len(x_samples) - 1, -1, -1):
                                    polygon_coords.append((x_samples[i], dmx_y_samples[i]))
                                
                                if len(polygon_coords) >= 3:
                                    backfill_polygon = Polygon(polygon_coords)
                                    if not backfill_polygon.is_valid:
                                        backfill_polygon = backfill_polygon.buffer(0)
                                    
                                    # 根据calc_mode限制回淤面积计算范围
                                    if target_line_y is not None and not backfill_polygon.is_empty:
                                        # 创建高程线裁剪区域
                                        if calc_mode == 'below':
                                            # 高程线以下：裁剪到高程线以下的区域
                                            clip_poly = box(common_x_min - 10, sect_y_min_actual - 100, common_x_max + 10, target_line_y)
                                            backfill_polygon = backfill_polygon.intersection(clip_poly)
                                        else:
                                            # 高程线以上：裁剪到高程线以上的区域
                                            clip_poly = box(common_x_min - 10, target_line_y, common_x_max + 10, sect_y_max_actual + 100)
                                            backfill_polygon = backfill_polygon.intersection(clip_poly)
                                        
                                        if backfill_polygon.is_empty:
                                            backfill_area = 0.0
                                        else:
                                            backfill_area = backfill_polygon.area
                                    else:
                                        backfill_area = backfill_polygon.area
                                    
                                    # 添加填充到输出（仅在有面积时）
                                    if backfill_area > 0.01 and not backfill_polygon.is_empty:
                                        HatchProcessor.add_simple(output_msp, backfill_polygon, backfill_layer, color_index=1, rgb_color=(255, 0, 0))
                
                backfill_results.append({'桩号': station, '回淤面积': round(backfill_area, 2)})
                
                # 进度日志
                if (idx + 1) % 50 == 0:
                    LOG(f"  已处理 {idx+1}/{len(dmx_list)} 个断面...")
            
            # ========== 结果排序 ==========
            section_results.sort(key=lambda x: StationMatcher.sort_key(x['断面名称']))
            backfill_results.sort(key=lambda x: StationMatcher.sort_key(x['桩号']))
            
            # ========== 合并结果（同一桩号的分层算量和回淤面积） ==========
            combined_results = []
            for sec_r in section_results:
                station_name = sec_r['断面名称']
                # 查找对应的回淤结果
                backfill_val = 0.0
                for bf_r in backfill_results:
                    if bf_r['桩号'] == station_name:
                        backfill_val = bf_r['回淤面积']
                        break
                
                combined_result = {
                    '断面名称': station_name,
                    '分层线高程': target_elevation,
                    **{k: v for k, v in sec_r.items() if k not in ['断面名称', '分层线高程']},
                    '回淤面积': backfill_val
                }
                combined_results.append(combined_result)
            
            # ========== 保存输出 ==========
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            base_name = os.path.basename(input_path).replace('.dxf', '')
            output_dxf_dir = output_dir if output_dir else os.path.dirname(input_path)
            
            # 保存DXF
            output_dxf = os.path.join(output_dxf_dir, f"{base_name}_分层回淤合并_{timestamp}.dxf")
            output_doc.saveas(output_dxf)
            LOG(f"\n[INFO] DXF文件已保存: {output_dxf}")
            
            # 生成Excel
            if combined_results:
                # 根据calc_mode决定文件名
                mode_suffix = "以下" if calc_mode == 'below' else "以上"
                if target_elevation is not None:
                    output_xlsx = os.path.join(output_dxf_dir, f"{base_name}_{target_elevation}m{mode_suffix}分层回淤_{timestamp}.xlsx")
                else:
                    output_xlsx = os.path.join(output_dxf_dir, f"{base_name}_全算量分层回淤_{timestamp}.xlsx")
                
                with pd.ExcelWriter(output_xlsx, engine='openpyxl') as writer:
                    # Sheet1: 合并明细表
                    df_combined = pd.DataFrame(combined_results)
                    df_combined.to_excel(writer, sheet_name='合并明细表', index=False)
                    
                    # Sheet2: 分层算量明细
                    df_section = pd.DataFrame(section_results)
                    if distinguish_design:
                        # 设计量sheet
                        design_cols = ['断面名称'] + [c for c in df_section.columns if c.endswith('_设计')]
                        df_design = df_section[design_cols].copy()
                        df_design.columns = ['断面名称'] + [c.replace('_设计', '') for c in df_section.columns if c.endswith('_设计')]
                        df_design.to_excel(writer, sheet_name='设计量', index=False)
                        
                        # 超挖量sheet
                        over_cols = ['断面名称'] + [c for c in df_section.columns if c.endswith('_超挖')]
                        df_over = df_section[over_cols].copy()
                        df_over.columns = ['断面名称'] + [c.replace('_超挖', '') for c in df_section.columns if c.endswith('_超挖')]
                        df_over.to_excel(writer, sheet_name='超挖量', index=False)
                        
                        # 总量sheet
                        df_total = df_section[['断面名称']].copy()
                        for layer in strata_layers:
                            design_col = f'{layer}_设计'
                            over_col = f'{layer}_超挖'
                            total_val = 0.0
                            if design_col in df_section.columns: total_val = total_val + df_section[design_col].fillna(0)
                            if over_col in df_section.columns: total_val = total_val + df_section[over_col].fillna(0)
                            df_total[layer] = total_val
                        df_total.to_excel(writer, sheet_name='分层总量', index=False)
                    else:
                        df_section.to_excel(writer, sheet_name='分层算量明细', index=False)
                    
                    # Sheet3: 回淤面积明细
                    df_backfill = pd.DataFrame(backfill_results)
                    df_backfill.to_excel(writer, sheet_name='回淤面积明细', index=False)
                    
                    # 带合计的回淤
                    summary_row = pd.DataFrame([{'桩号': '合计', '回淤面积': df_backfill['回淤面积'].sum()}])
                    pd.concat([df_backfill, summary_row], ignore_index=True).to_excel(writer, sheet_name='回淤带合计', index=False)
                    
                    # Sheet4: 地层汇总
                    if distinguish_design:
                        summary_data = {'地层': [], '设计面积(㎡)': [], '超挖面积(㎡)': []}
                        for layer in strata_layers:
                            summary_data['地层'].append(layer)
                            design_col = f'{layer}_设计'
                            over_col = f'{layer}_超挖'
                            summary_data['设计面积(㎡)'].append(df_section[design_col].sum() if design_col in df_section.columns else 0.0)
                            summary_data['超挖面积(㎡)'].append(df_section[over_col].sum() if over_col in df_section.columns else 0.0)
                        df_summary = pd.DataFrame(summary_data)
                        df_summary['总面积(㎡)'] = df_summary['设计面积(㎡)'] + df_summary['超挖面积(㎡)']
                    else:
                        strata_cols = [c for c in df_section.columns if '级' in c]
                        summary_data = {'地层': strata_cols, '面积(㎡)': [df_section[c].sum() for c in strata_cols]}
                        df_summary = pd.DataFrame(summary_data)
                    df_summary.to_excel(writer, sheet_name='地层汇总', index=False)
                    
                    # Sheet5: 总汇总
                    mode_text = "以下" if calc_mode == 'below' else "以上"
                    total_data = {
                        '统计项': [
                            '总断面数',
                            f'{target_elevation}m{mode_text}总面积' if target_elevation else '开挖总面积',
                            '总回淤面积'
                        ],
                        '数值': [
                            len(combined_results),
                            df_section['总面积'].sum(),
                            df_backfill['回淤面积'].sum()
                        ]
                    }
                    pd.DataFrame(total_data).to_excel(writer, sheet_name='总汇总', index=False)
                
                LOG(f"\n[OK] 处理完成！")
                LOG(f"   DXF: {os.path.basename(output_dxf)}")
                LOG(f"   Excel: {os.path.basename(output_xlsx)}")
                LOG(f"   总断面数: {len(combined_results)}")
                if target_elevation:
                    LOG(f"   {target_elevation}m{mode_text}总面积: {df_section['总面积'].sum():.3f} ㎡")
                else:
                    LOG(f"   开挖总面积: {df_section['总面积'].sum():.3f} ㎡")
                LOG(f"   总回淤面积: {df_backfill['回淤面积'].sum():.2f} ㎡")
            else:
                LOG("[WARN] 未生成任何数据")
        
        LOG("\n[DONE] [分层算量+回淤计算 任务全部结束]")

    except Exception as e:
        LOG(f"[ERROR] 合并任务执行错误: {e}")
        LOG(traceback.format_exc())


# ==================== 内部辅助函数 ====================

def _get_entity_list(msp, layer):
    """获取图层实体列表"""
    entity_list = []
    for e in msp.query(f'*[layer=="{layer}"]'):
        if e.dxftype() == 'LWPOLYLINE':
            pts = [p[:2] for p in e.get_points()]
            if pts:
                x_min = min(p[0] for p in pts)
                x_max = max(p[0] for p in pts)
                y_min = min(p[1] for p in pts)
                y_max = max(p[1] for p in pts)
                entity_list.append({
                    'x_min': x_min, 'x_max': x_max,
                    'y_min': y_min, 'y_max': y_max,
                    'pts': pts, 'line': LineString(pts),
                    'y_center': (y_min + y_max) / 2
                })
    return entity_list


def _build_design_polygon(excav_lines, sect_x_min, sect_x_max):
    """构建设计区多边形"""
    if not excav_lines: return None
    
    all_points = [p for l in excav_lines for p in l.coords]
    if not all_points: return None
    
    excav_x_min = min(p[0] for p in all_points)
    excav_x_max = max(p[0] for p in all_points)
    excav_y_min = min(p[1] for p in all_points)
    
    design_x_min = max(excav_x_min, sect_x_min)
    design_x_max = min(excav_x_max, sect_x_max)
    
    if design_x_max <= design_x_min: return None
    
    x_samples = []
    y_samples = []
    x_current = design_x_min
    
    while x_current <= design_x_max:
        min_y = None
        for line in excav_lines:
            y = LineUtils.get_y_at_x(line, x_current)
            if y is not None and (min_y is None or y < min_y):
                min_y = y
        if min_y is not None:
            x_samples.append(x_current)
            y_samples.append(min_y)
        x_current += 1.0
    
    if len(x_samples) < 2: return None
    
    sect_y_max = max(y_samples) + 50
    polygon_coords = list(zip(x_samples, y_samples))
    polygon_coords.append((x_samples[-1], sect_y_max))
    polygon_coords.append((x_samples[0], sect_y_max))
    polygon_coords.append(polygon_coords[0])
    
    poly = Polygon(polygon_coords)
    return poly if poly.is_valid else poly.buffer(0)


# ==================== 命令行接口 ====================

def main():
    """命令行入口点"""
    import sys
    import json
    
    if len(sys.argv) < 3:
        print("用法: python engine_cad.py <任务类型> <参数JSON文件>")
        print("任务类型: autoline, autopaste, autohatch, autosection, backfill, autosection_backfill")
        return
    
    task_type = sys.argv[1]
    param_file = sys.argv[2]
    
    try:
        with open(param_file, 'r', encoding='utf-8') as f:
            params = json.load(f)
    except Exception as e:
        print(f"[ERROR] 无法读取参数文件: {e}")
        return
    
    def log_func(msg):
        msg = msg.replace('✅', '[OK]').replace('❌', '[ERROR]').replace('⚠️', '[WARN]')
        msg = msg.replace('⏳', '[WAIT]').replace('✨', '[DONE]').replace('🔍', '[SCAN]')
        msg = msg.replace('🎨', '[PAINT]').replace('🚀', '[GO]').replace('📊', '[STATS]')
        print(msg)
    
    tasks = {
        'autoline': run_autoline,
        'autopaste': run_autopaste,
        'autohatch': run_autohatch,
        'autosection': run_autosection,
        'backfill': run_backfill,
        'autosection_backfill': run_autosection_backfill
    }
    
    if task_type in tasks:
        tasks[task_type](params, log_func)
    else:
        print(f"[ERROR] 未知任务类型: {task_type}")

if __name__ == "__main__":
    main()