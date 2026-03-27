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
    """批量粘贴任务 - 通过红线-0.00-桩号的匹配链实现精确定位"""
    try:
        # 获取参数
        src_path = params.get('源文件名')
        dst_path = params.get('目标文件名')
        
        # 参考点参数（关键定位参数）
        s00x = float(params.get('源端0点X', 86.854))
        s00y_first = float(params.get('源端0点Y', -15.062))
        sbx_ref = float(params.get('源端基点X', 86.003))
        sby_first = float(params.get('源端基点Y', -35.298))
        step_y = float(params.get('断面间距', -148.476))
        
        dty_ref = float(params.get('目标桩号Y', -1470.529))
        dby_ref = float(params.get('目标基点Y', -1363.500))
        
        if not src_path or not dst_path:
            LOG("[ERROR] 请先选择源文件和目标文件")
            return
        
        if not os.path.exists(src_path):
            LOG(f"[ERROR] 找不到源文件: {src_path}")
            return
        
        LOG(f"正在读取源文件: {os.path.basename(src_path)} ...")
        src_doc = ezdxf.readfile(src_path)
        src_msp = src_doc.modelspace()
        
        # 计算源端基点偏移量
        src_dx = sbx_ref - s00x
        src_dy = sby_first - s00y_first
        
        # 计算目标端Y偏移量（目标基点Y - 目标桩号Y）
        dist_y = dby_ref - dty_ref
        
        LOG(f"[INFO] 源端偏移: dx={src_dx:.3f}, dy={src_dy:.3f}")
        LOG(f"[INFO] 目标端Y偏移: dist_y={dist_y:.3f}")
        
        station_pattern = re.compile(r'(\d+\+\d+)')
        
        # ===== 第一步：探测源端断面 =====
        LOG("[SCAN] 探测源端断面...")
        all_src_texts = list(src_msp.query('TEXT MTEXT'))
        sections = {}
        
        for i in range(1000):  # 最多探测1000个断面
            curr_y_limit = s00y_first + (i * step_y)
            m_id, nav_00 = None, None
            
            for t in all_src_texts:
                try:
                    p = EntityHelper.get_best_point(t)
                    if abs(p[1] - curr_y_limit) < 60:  # Y坐标容差60
                        content = EntityHelper.get_text(t).strip()
                        # 匹配桩号ID (.TIN文本)
                        if ".TIN" in content.upper() and abs(p[0] - 75.5) < 40:  # X坐标约75.5
                            m = station_pattern.search(content)
                            if m:
                                m_id = m.group(1)
                        # 匹配0.00导航点
                        if content == "0.00" and abs(p[0] - s00x) < 20:  # X坐标容差20
                            nav_00 = p
                except: pass
            
            if nav_00 is None:
                LOG(f"[INFO] 探测结束，共找到 {len(sections)} 个断面潜在区域")
                break
            
            if m_id:
                sections[m_id] = {
                    "bx": nav_00[0] + src_dx,  # 基点X = 0.00 X + 偏移
                    "by": nav_00[1] + src_dy,  # 基点Y = 0.00 Y + 偏移
                    "ents": []
                }
        
        LOG(f"  源端断面: {len(sections)}个")
        
        # ===== 第二步：实体分配（分配红线到各断面） =====
        LOG("[SCAN] 提取红线实体 (Color 1)...")
        red_lines = [e for e in src_msp.query('LWPOLYLINE') if e.dxf.color == 1]
        LOG(f"  红线数量: {len(red_lines)}条")
        
        if not red_lines:
            LOG("[ERROR] 未找到源端红线（color=1的LWPOLYLINE）")
            return
        
        # 按Y坐标排序断面（从上到下）
        sorted_mids = sorted(sections.keys(), key=lambda k: sections[k]["by"], reverse=True)
        
        # 将红线分配到最近的断面
        for red in red_lines:
            pts = list(red.get_points())
            avg_y = sum(p[1] for p in pts) / len(pts)
            
            best_mid = None
            min_dist = 100  # 距离容差100
            
            for mid in sorted_mids:
                # 红线应该在断面基点下方约40单位处
                d = abs(avg_y - (sections[mid]["by"] - 40))
                if d < min_dist:
                    min_dist = d
                    best_mid = mid
                # 如果红线Y已经超过当前断面太多，停止搜索
                if avg_y > sections[mid]["by"] + 100:
                    break
            
            if best_mid:
                sections[best_mid]["ents"].append(red)
        
        # 统计分配结果
        assigned_count = sum(1 for s in sections.values() if s["ents"])
        LOG(f"  分配红线到断面: {assigned_count}个断面有红线")
        
        # ===== 第三步：读取目标文件 =====
        if not os.path.exists(dst_path):
            LOG(f"[WARN] 目标文件不存在，将创建新文件: {dst_path}")
            dst_doc = ezdxf.new()
        else:
            LOG(f"正在读取目标文件: {os.path.basename(dst_path)} ...")
            dst_doc = ezdxf.readfile(dst_path)
        dst_msp = dst_doc.modelspace()
        
        # ===== 第四步：收集目标端桩号 =====
        LOG("[SCAN] 收集目标端桩号...")
        dst_index = {}  # {桩号ID: (x, y)}
        for lb in dst_msp.query('TEXT MTEXT'):
            try:
                txt = EntityHelper.get_text(lb).upper()
                m = station_pattern.search(txt)
                if m:
                    pt = EntityHelper.get_best_point(lb)
                    dst_index[m.group(1)] = pt
            except: pass
        
        LOG(f"  目标端桩号: {len(dst_index)}个")
        
        # ===== 第五步：匹配并粘贴 =====
        LOG("[GO] 执行粘贴...")
        
        if "0-已粘贴断面" not in dst_doc.layers:
            dst_doc.layers.new(name="0-已粘贴断面", dxfattribs={'color': 3})
        
        count = 0
        
        for mid, s_data in sections.items():
            if mid in dst_index and s_data["ents"]:
                p_dst = dst_index[mid]
                # 目标红线位置：X保持桩号X，Y = 桩号Y + dist_y
                tx = p_dst[0]
                ty = p_dst[1] + dist_y
                
                # 计算平移向量
                dx = tx - s_data["bx"]
                dy = ty - s_data["by"]
                
                # 复制所有红线实体到目标位置
                for e in s_data["ents"]:
                    new_e = e.copy()
                    new_e.translate(dx, dy, 0)
                    new_e.dxf.layer = "0-已粘贴断面"
                    new_e.dxf.color = 3
                    dst_msp.add_entity(new_e)
                
                count += 1
                if count <= 5 or count % 20 == 0:
                    LOG(f"  [{count}] {mid}: 平移量({dx:.1f}, {dy:.1f})")
        
        # ===== 第六步：保存结果 =====
        dst_dir = os.path.dirname(dst_path) or "."
        dst_basename = os.path.basename(dst_path).replace(".dxf", "")
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        save_name = os.path.join(dst_dir, f"{dst_basename}_已粘贴断面_{timestamp}.dxf")
        dst_doc.saveas(save_name)
        
        LOG(f"[OK] 处理完成！成果已保存至: {os.path.basename(save_name)}")
        LOG(f"[STATS] 统计：共匹配并粘贴 {count} 个断面")

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
            '辅助断面图层': 辅助断面线图层列表，
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
        section_layer = params.get('断面线图层', 'DMX')
        aux_layers_str = params.get('辅助断面图层', '')
        calc_mode = params.get('计算模式', 'below')  # 'below'高程线以下或'above'高程线以上
        distinguish_design = params.get('区分设计超挖', False)
        if isinstance(distinguish_design, str):
            distinguish_design = distinguish_design.lower() in ('true', '1', 'yes', '是')
        output_dir = params.get('输出目录')
        
        aux_layers = [s.strip() for s in aux_layers_str.split(',') if s.strip()]
        
        LOG(f"[INFO] 目标高程: {target_elevation}m")
        LOG(f"[INFO] 断面线图层: {section_layer}")
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
            
            # 获取桩号
            station_texts = LayerExtractor.get_texts(msp, "0-桩号")
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
                
                # 生成最终断面线（合并辅助断面线，固定使用下包络线）
                if aux_lines_all:
                    boundary_box = box(sect_x_min - 20, sect_y_min - 50, sect_x_max + 20, sect_y_max + 50)
                    local_aux = [l for l in aux_lines_all if boundary_box.intersects(l)]
                    if local_aux:
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
                
                # 判断分层线位置（全算量模式直接使用整个断面区域）
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
                elif calc_mode == 'above':
                    # 高程线以上模式
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
                else:
                    # 默认使用高程线以下模式
                    layer_open = total_open_poly
                
                if layer_open.is_empty:
                    result = {'断面名称': station, '分层线高程': target_elevation, '总面积': 0.0}
                    for layer in strata_layers:
                        if distinguish_design:
                            result[f'{layer}_设计'] = 0.0
                            result[f'{layer}_超挖'] = 0.0
                        else:
                            result[layer] = 0.0
                    results.append(result)
                    continue
                
                # 绘制高程线（仅在有目标高程时绘制）
                if target_line_y is not None and target_line_y > sect_y_min_actual:
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
            mode_suffix = "以上" if calc_mode == 'above' else "以下"
            output_dxf = os.path.join(output_dxf_dir, f"{base_name}_{target_elevation}m分层_{timestamp}.dxf")
            output_doc.saveas(output_dxf)
            LOG(f"[INFO] DXF文件已保存: {output_dxf}")
            
            # 生成Excel
            if results:
                df = pd.DataFrame(results)
                output_xlsx = os.path.join(output_dxf_dir, f"{base_name}_{target_elevation}m{mode_suffix}面积_{timestamp}.xlsx")
                
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
                    total_data = {'统计项': ['总断面数', f'{target_elevation}m{mode_suffix}总面积'], '数值': [len(results), df['总面积'].sum()]}
                    pd.DataFrame(total_data).to_excel(writer, sheet_name='汇总', index=False)
                
                LOG(f"[OK] 处理完成！")
                LOG(f"   DXF: {os.path.basename(output_dxf)}")
                LOG(f"   Excel: {os.path.basename(output_xlsx)}")
                LOG(f"   总断面数: {len(results)}")
                LOG(f"   {target_elevation}m{mode_suffix}总面积: {df['总面积'].sum():.3f} ㎡")
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
        print("任务类型: autoline, autopaste, autohatch, autosection, backfill")
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
        'backfill': run_backfill
    }
    
    if task_type in tasks:
        tasks[task_type](params, log_func)
    else:
        print(f"[ERROR] 未知任务类型: {task_type}")

if __name__ == "__main__":
    main()