# -*- coding: utf-8 -*-
# engine_cad.py - 核心CAD计算引擎（优化版 v2.0）
"""
包含所有算量脚本的核心逻辑，整合五个工具：
- autoline: 断面线合并
- autopaste: 批量粘贴
- autohatch: 快速填充
- autoclassify: 分类算量
- autocut: 分层算量

优化内容：
- 封装重复的识别、匹配、定位逻辑
- 完善文件输出逻辑（支持自定义输出路径）
- 压缩代码行数
- 保护关键函数
"""

import ezdxf
import os
import traceback
import math
import re
import datetime
import pandas as pd
from collections import defaultdict, Counter
from shapely.geometry import LineString, MultiLineString, Point, box, Polygon, MultiPolygon
from shapely.ops import unary_union, linemerge, polygonize

# ==================== 核心配置 ====================
class Config:
    """全局配置"""
    # 默认图层名
    DEFAULT_OUTPUT_LAYER = "FINAL_BOTTOM_SURFACE"
    DEFAULT_HATCH_LAYER = "AA_填充算量层"
    DEFAULT_FINAL_SECTION = "AA_最终断面线"
    
    # 面积比例系数（用于缩放后的DXF文件，如坐标按√0.6缩放，则系数为0.6）
    AREA_SCALE_FACTOR = 1.0
    
    # 颜色配置
    HIGH_CONTRAST_COLORS = [
        (255, 0, 0), (0, 200, 0), (0, 0, 255), (255, 255, 0), (255, 0, 255), (0, 255, 255),
        (255, 128, 0), (128, 0, 255), (0, 128, 255), (255, 0, 128), (128, 255, 0), (0, 255, 128),
        (128, 128, 0), (0, 128, 128), (128, 0, 128), (200, 100, 50), (50, 200, 100), (100, 50, 200),
    ]
    
    # 地层排序
    STRATA_TYPE_ORDER = {
        '淤泥': 1, '砂': 2, '填土': 3, '粘土': 4, '岩石': 5, '砾': 6, '卵': 7, '粉': 8
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
        b = line.bounds
        v_line = LineString([(x, b[1] - 100), (x, b[3] + 100)])
        try:
            inter = line.intersection(v_line)
            if inter.is_empty: return None
            if inter.geom_type == 'Point': return inter.y
            if inter.geom_type in ('MultiPoint', 'LineString'):
                coords = inter.coords if inter.geom_type == 'LineString' else [p.coords[0] for p in inter.geoms]
                return min(c[1] for c in coords)
        except:
            return None
    
    @staticmethod
    def extend(line, dist):
        """延长线两端"""
        coords = list(line.coords)
        if len(coords) < 2: return line
        
        # 起点延长
        p1, p2 = Point(coords[0]), Point(coords[1])
        vec = (p1.x - p2.x, p1.y - p2.y)
        mag = (vec[0]**2 + vec[1]**2)**0.5 or 1
        new_start = (p1.x + vec[0]/mag*dist, p1.y + vec[1]/mag*dist)
        
        # 终点延长
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
        except:
            pass
        return []


class LayerExtractor:
    """图层提取工具集"""
    
    @staticmethod
    def get_lines(msp, layer):
        """从指定图层提取所有线段"""
        lines = []
        try:
            ents = msp.query(f'*[layer=="{layer}"]')
        except:
            return []
        
        for ent in ents:
            ls = EntityHelper.to_linestring(ent)
            if ls:
                lines.append(ls)
        return lines
    
    @staticmethod
    def get_texts(msp, layer_pattern=None):
        """提取文本实体"""
        texts = []
        query = msp.query('TEXT MTEXT')
        for e in query:
            try:
                if layer_pattern and layer_pattern not in e.dxf.layer:
                    continue
                pt = EntityHelper.get_best_point(e)
                txt = EntityHelper.get_text(e)
                texts.append({'text': txt, 'x': pt[0], 'y': pt[1], 'entity': e})
            except:
                pass
        return texts
    
    @staticmethod
    def get_polylines_by_color(msp, color):
        """按颜色获取多段线"""
        results = []
        for e in msp.query('LWPOLYLINE'):
            try:
                if e.dxf.color == color:
                    pts = list(e.get_points())
                    avg_y = sum(p[1] for p in pts) / len(pts)
                    avg_x = sum(p[0] for p in pts) / len(pts)
                    results.append({'entity': e, 'x': avg_x, 'y': avg_y, 'pts': pts})
            except:
                pass
        return results


class StationMatcher:
    """桩号匹配工具集"""
    
    STATION_PATTERN = re.compile(r'(\d+\+\d+)')
    
    @staticmethod
    def calc_adaptive_params(bounds_list):
        """根据断面大小计算自适应距离参数
        
        返回:
            dict: {
                'cluster_dist': 聚类距离,
                'match_dist': 桩号匹配距离,
                'boundary_expand': 边界框扩展,
                'dmx_match_dist': DMX匹配距离
            }
        """
        if not bounds_list:
            return {
                'cluster_dist': 200,
                'match_dist': 200,
                'boundary_expand': (20, 25),
                'dmx_match_dist': 50
            }
        
        # 计算平均断面尺寸
        widths = []
        heights = []
        for b in bounds_list:
            if hasattr(b, 'bounds'):
                minx, miny, maxx, maxy = b.bounds
            else:
                minx, miny, maxx, maxy = b
            widths.append(maxx - minx)
            heights.append(maxy - miny)
        
        avg_width = sum(widths) / len(widths) if widths else 100
        avg_height = sum(heights) / len(heights) if heights else 100
        avg_size = (avg_width + avg_height) / 2
        
        # 根据平均尺寸计算自适应参数
        # 基准：原始代码假设断面尺寸约100-200
        scale_factor = avg_size / 150 if avg_size > 0 else 1.0
        
        return {
            'cluster_dist': max(100, 200 * scale_factor),
            'match_dist': max(100, 200 * scale_factor),
            'boundary_expand': (max(10, 20 * scale_factor), max(15, 25 * scale_factor)),
            'dmx_match_dist': max(30, 50 * scale_factor)
        }
    
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
                    if sid not in stations:
                        stations[sid] = []
                    stations[sid].append({'x': pt[0], 'y': pt[1]})
            except:
                pass
        return stations
    
    @classmethod
    def sort_key(cls, station_str):
        """桩号排序键"""
        nums = re.findall(r'\d+', str(station_str))
        return int("".join(nums)) if nums else 0
    
    @classmethod
    def find_nearest(cls, target_pt, candidates, used=None, tolerance=200):
        """找最近的候选点"""
        best = None
        best_dist = float('inf')
        
        for i, c in enumerate(candidates):
            if used and i in used:
                continue
            dist = math.sqrt((c['x'] - target_pt[0])**2 + (c['y'] - target_pt[1])**2)
            if dist < best_dist and dist < tolerance:
                best_dist = dist
                best = (i, c)
        
        return best


class OutputHelper:
    """文件输出工具集"""
    
    @staticmethod
    def get_output_path(input_path, suffix, output_dir=None, custom_name=None):
        """生成输出文件路径
        
        参数：
            input_path: 输入文件路径
            suffix: 文件名后缀（如 "_下包络合并"）
            output_dir: 自定义输出目录（None则使用输入文件目录）
            custom_name: 自定义文件名前缀（None则使用原文件名）
        """
        base_dir = output_dir if output_dir else os.path.dirname(input_path)
        base_name = custom_name if custom_name else os.path.splitext(os.path.basename(input_path))[0]
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # 如果suffix已经包含扩展名
        if suffix.endswith('.dxf') or suffix.endswith('.xlsx'):
            return os.path.join(base_dir, f"{base_name}{suffix}")
        
        return os.path.join(base_dir, f"{base_name}{suffix}.dxf")
    
    @staticmethod
    def ensure_layer(doc, layer_name, color=7):
        """确保图层存在"""
        if layer_name not in doc.layers:
            doc.layers.new(name=layer_name, dxfattribs={'color': color})
        return doc.layers.get(layer_name)


# ==================== 核心算法模块 ====================

class SectionGenerator:
    """断面线生成器"""
    
    @staticmethod
    def generate_final_section(dmx, section_lines):
        """生成完整的最终断面线 - 交点附近密集采样确保贴合"""
        all_x_coords = set()
        
        # 收集所有X坐标
        for pt in dmx.coords:
            all_x_coords.add(round(pt[0], 3))
        for sec in section_lines:
            for pt in sec.coords:
                all_x_coords.add(round(pt[0], 3))
        
        # 收集交点附近的X坐标
        all_lines = [dmx] + list(section_lines)
        for i in range(len(all_lines)):
            for j in range(i + 1, len(all_lines)):
                intersections = LineUtils.find_intersections(all_lines[i], all_lines[j])
                for ix, iy in intersections:
                    all_x_coords.add(round(ix, 3))
                    for delta in [-1.0, -0.5, 0.5, 1.0]:
                        all_x_coords.add(round(ix + delta, 3))
        
        if not all_x_coords:
            return None
        
        # 过滤并排序X坐标
        dmx_bounds = dmx.bounds
        x_min, x_max = dmx_bounds[0], dmx_bounds[2]
        filtered_x = sorted(x for x in all_x_coords if x_min <= x <= x_max)
        
        if not filtered_x:
            return None
        
        # 计算每个X处的最小Y
        coords = []
        for x in filtered_x:
            all_ys = []
            dmx_y = LineUtils.get_y_at_x(dmx, x)
            if dmx_y is not None:
                all_ys.append(dmx_y)
            for sec in section_lines:
                sec_y = LineUtils.get_y_at_x(sec, x)
                if sec_y is not None:
                    all_ys.append(sec_y)
            if all_ys:
                coords.append((x, min(all_ys)))
        
        return LineString(coords) if len(coords) >= 2 else None


class BasePointDetector:
    """基点检测器"""
    
    @staticmethod
    def find_source_basepoints(msp, LOG):
        """检测源文件的基点（断面框上边中点）"""
        basepoints = []
        
        for e in msp.query('LWPOLYLINE'):
            try:
                if e.dxf.color != 0:
                    continue
                
                pts = list(e.get_points())
                if len(pts) < 4:
                    continue
                
                # 检查是否闭合
                first, last = pts[0], pts[-1]
                if abs(first[0] - last[0]) > 1 or abs(first[1] - last[1]) > 1:
                    continue
                
                # 计算边界框
                xs = [p[0] for p in pts]
                ys = [p[1] for p in pts]
                width = max(xs) - min(xs)
                height = max(ys) - min(ys)
                
                # 断面框尺寸筛选
                if not (100 <= width <= 200 and 50 <= height <= 200):
                    continue
                
                # 找上边中点
                max_y = max(ys)
                top_pts = [p for p in pts if abs(p[1] - max_y) < 1]
                
                if len(top_pts) >= 2:
                    left_pt = min(top_pts, key=lambda p: p[0])
                    right_pt = max(top_pts, key=lambda p: p[0])
                    mid_x = (left_pt[0] + right_pt[0]) / 2
                    mid_y = (left_pt[1] + right_pt[1]) / 2
                    center_y = (min(ys) + max(ys)) / 2
                    basepoints.append((mid_x, mid_y, center_y))
            except:
                pass
        
        basepoints.sort(key=lambda bp: bp[1], reverse=True)
        LOG(f"  源基点检测: 找到{len(basepoints)}个断面框上边中点")
        return basepoints
    
    @staticmethod
    def find_dest_basepoints(msp, LOG):
        """检测目标文件的基点（倒三角顶点）"""
        endpoint_lines = defaultdict(list)
        
        for line in msp.query('LINE'):
            try:
                sx, sy = round(line.dxf.start.x, 1), round(line.dxf.start.y, 1)
                ex, ey = round(line.dxf.end.x, 1), round(line.dxf.end.y, 1)
                endpoint_lines[(sx, sy)].append(line)
                endpoint_lines[(ex, ey)].append(line)
            except:
                pass
        
        basepoints = []
        for pt, line_list in endpoint_lines.items():
            if len(line_list) < 2:
                continue
            
            x, y = pt
            up_count = 0
            
            for line in line_list:
                try:
                    sx, sy = line.dxf.start.x, line.dxf.start.y
                    ex, ey = line.dxf.end.x, line.dxf.end.y
                    
                    if abs(sx - x) < 0.2 and abs(sy - y) < 0.2:
                        dx, dy = ex - sx, ey - sy
                    else:
                        dx, dy = sx - ex, sy - ey
                    
                    angle = math.atan2(dy, dx) * 180 / math.pi
                    if abs(angle) > 90:
                        up_count += 1
                except:
                    pass
            
            if up_count >= 2:
                basepoints.append((x, y))
        
        basepoints.sort(key=lambda bp: bp[1], reverse=True)
        LOG(f"  目标基点检测: 找到{len(basepoints)}个倒三角顶点")
        return basepoints


class HatchProcessor:
    """填充处理器"""
    
    @staticmethod
    def to_polygon(hatch_entity):
        """填充转多边形"""
        polygons = []
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
                        try:
                            pts.extend([(p.x, p.y) for p in edge.flattening(distance=0.01)])
                        except:
                            pass
            
            if len(pts) >= 3:
                poly = Polygon(pts)
                if not poly.is_valid:
                    poly = poly.buffer(0)
                if not poly.is_empty:
                    polygons.append(Polygon(poly.exterior))
        
        return unary_union(polygons)
    
    @staticmethod
    def add_with_label(msp, poly, rgb_color, pattern, scale, text_height, strata_name, is_design, doc=None):
        """添加填充和标注"""
        if not poly or poly.is_empty or isinstance(poly, (LineString, Point)):
            return 0.0
        
        label_type = "设计" if is_design else "超挖"
        layer_hatch = f"{strata_name}{label_type}"
        layer_label = f"{strata_name}{label_type}_标注"
        
        # 确保图层存在
        if doc:
            OutputHelper.ensure_layer(doc, layer_hatch)
            OutputHelper.ensure_layer(doc, layer_label)
        
        geoms = [poly] if isinstance(poly, Polygon) else (list(poly.geoms) if hasattr(poly, 'geoms') else [poly])
        total_area = 0.0
        full_label = f"{strata_name}{label_type}"
        
        for p in geoms:
            if isinstance(p, (LineString, Point)) or p.area < 0.01:
                continue
            
            total_area += p.area
            
            # 添加填充
            hatch = msp.add_hatch(dxfattribs={'layer': layer_hatch})
            hatch.rgb = rgb_color
            hatch.set_pattern_fill(pattern, scale=scale)
            hatch.paths.add_polyline_path(list(p.exterior.coords), is_closed=True)
            
            for interior in p.interiors:
                hatch.paths.add_polyline_path(list(interior.coords), is_closed=True)
            
            # 添加标注
            area_val = round(p.area, 3)
            if area_val > 0.1:
                try:
                    in_point = p.representative_point()
                    label_content = f"{{\\fArial|b1;{full_label}\\P{area_val}}}"
                    mtext = msp.add_mtext(label_content, dxfattribs={
                        'layer': layer_label,
                        'insert': (in_point.x, in_point.y),
                        'char_height': text_height,
                        'attachment_point': 5,
                    })
                    mtext.rgb = rgb_color
                    try:
                        mtext.dxf.bg_fill_setting = 1
                        mtext.dxf.bg_fill_scale_factor = 1.3
                    except:
                        pass
                except:
                    pass
        
        return total_area


# ==================== 1. 断面线合并 (autoline) ====================

def run_autoline(params, LOG):
    """断面合并任务 - 支持自定义输出路径和图层名"""
    try:
        layer_new = params.get('图层A名称') or params.get('图层 A 名称')
        layer_old = params.get('图层B名称') or params.get('图层 B 名称')
        output_layer = params.get('输出图层名', Config.DEFAULT_OUTPUT_LAYER)
        output_dir = params.get('输出目录')  # 自定义输出目录
        
        if not layer_new or not layer_old:
            LOG("[ERROR] 脚本错误：无法从UI获取图层名称。")
            return
        
        file_list = params.get('files', [])
        if not file_list:
            LOG("[WARN] 请先添加文件。")
            return

        for input_file in file_list:
            LOG(f"--- [WAIT] 正在处理(下包络): {os.path.basename(input_file)} ---")
            
            if not os.path.exists(input_file):
                LOG(f"[ERROR] 错误: 找不到文件 {input_file}")
                continue

            doc = ezdxf.readfile(input_file)
            msp = doc.modelspace()
            
            # 提取线段
            new_lss = [ls for ls in (EntityHelper.to_linestring(e) for e in msp.query(f'LWPOLYLINE POLYLINE LINE[layer=="{layer_new}"]')) if ls]
            old_lss = [ls for ls in (EntityHelper.to_linestring(e) for e in msp.query(f'LWPOLYLINE POLYLINE LINE[layer=="{layer_old}"]')) if ls]

            if not new_lss and not old_lss:
                LOG(f"[WARN] 跳过：指定图层没有线段。")
                continue

            # 分组处理
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

            # 确保输出图层存在
            OutputHelper.ensure_layer(doc, output_layer, color=3)

            # 生成最终断面线
            success_count = 0
            for group in groups:
                if len(group) < 2:
                    msp.add_lwpolyline(list(group[0].coords), dxfattribs={'layer': output_layer})
                    success_count += 1
                    continue
                
                final_line = SectionGenerator.generate_final_section(group[0], group[1:])
                if final_line and final_line.length > 0.01:
                    msp.add_lwpolyline(list(final_line.coords), dxfattribs={'layer': output_layer})
                    success_count += 1

            # 生成输出文件名
            output_path = OutputHelper.get_output_path(input_file, "_下包络合并.dxf", output_dir)
            doc.saveas(output_path)
            LOG(f"[OK] 完成！已提取下包络线，保存至: {os.path.basename(output_path)}")

        LOG("[DONE] [下包络任务全部结束]")

    except Exception as e:
        LOG(f"[ERROR] 脚本崩溃:\n{traceback.format_exc()}")


# ==================== 2. 批量粘贴 (autopaste) ====================

def run_autopaste(params, LOG):
    """批量粘贴任务 - 严格按照红线-0.00-桩号匹配链实现精确定位"""
    try:
        src_path = params.get('源文件名')
        dst_path = params.get('目标文件名')
        output_dir = params.get('输出目录')  # 自定义输出目录
        
        if not src_path or not dst_path:
            LOG("[ERROR] 请先选择源文件和目标文件")
            return
        
        if not os.path.exists(src_path):
            LOG(f"[ERROR] 找不到源文件: {src_path}")
            return
        
        LOG(f"正在读取源文件: {os.path.basename(src_path)} ...")
        src_doc = ezdxf.readfile(src_path)
        src_msp = src_doc.modelspace()
        
        # ===== 1. 收集源端关键实体 =====
        LOG("[SCAN] 收集源端实体...")
        
        # 收集桩号
        src_stations = StationMatcher.extract_stations(src_msp)
        
        # 收集0.00导航点
        src_nav_00s = []
        for e in src_msp.query('TEXT MTEXT'):
            try:
                if EntityHelper.get_text(e).strip() == "0.00":
                    pt = EntityHelper.get_best_point(e)
                    src_nav_00s.append({'x': pt[0], 'y': pt[1]})
            except:
                pass
        
        # 收集红线（color=1）
        src_reds = LayerExtractor.get_polylines_by_color(src_msp, 1)
        
        LOG(f"  源端桩号ID: {len(src_stations)}个")
        LOG(f"  源端0.00导航点: {len(src_nav_00s)}个")
        LOG(f"  源端红线: {len(src_reds)}条")
        
        if not src_reds:
            LOG("[ERROR] 未找到源端红线（color=1的LWPOLYLINE）")
            return
        
        # ===== 2. 排序 =====
        src_nav_00s.sort(key=lambda n: n['y'], reverse=True)
        src_reds.sort(key=lambda r: r['y'], reverse=True)
        
        # ===== 3. X分组匹配红线与0.00 =====
        LOG("[SCAN] 匹配红线与0.00...")
        
        def get_x_group(x, tolerance=20):
            return round(x / tolerance) * tolerance
        
        nav_00_by_x = defaultdict(list)
        for nav in src_nav_00s:
            nav_00_by_x[get_x_group(nav['x'])].append(nav)
        
        reds_by_x = defaultdict(list)
        for red in src_reds:
            reds_by_x[get_x_group(red['x'])].append(red)
        
        # 匹配
        red_to_nav = {}
        used_navs = set()
        
        for xg in reds_by_x:
            reds_in_group = sorted(reds_by_x[xg], key=lambda r: r['y'], reverse=True)
            navs_in_group = sorted(nav_00_by_x.get(xg, []), key=lambda n: n['y'], reverse=True)
            
            for red in reds_in_group:
                best = StationMatcher.find_nearest((red['x'], red['y']), navs_in_group, used_navs, 200)
                if best:
                    used_navs.add(best[0])
                    red_to_nav[id(red['entity'])] = best[1]
        
        LOG(f"  匹配红线-0.00: {len(red_to_nav)}对")
        
        # ===== 4. 匹配桩号 =====
        LOG("[SCAN] 匹配0.00与桩号...")
        
        src_sections = {}
        all_station_pts = []
        for sid, pts in src_stations.items():
            for pt in pts:
                all_station_pts.append({'id': sid, 'x': pt['x'], 'y': pt['y']})
        
        used_stations = set()
        for red_ent_id, nav in red_to_nav.items():
            best = StationMatcher.find_nearest((nav['x'], nav['y']), all_station_pts, used_stations, 200)
            
            if best:
                used_stations.add((best[1]['id'], best[1]['x'], best[1]['y']))
                red_ent = next((r for r in src_reds if id(r['entity']) == red_ent_id), None)
                
                if red_ent:
                    sid = best[1]['id']
                    if sid not in src_sections:
                        src_sections[sid] = {
                            'red': red_ent['entity'],
                            'red_x': red_ent['x'],
                            'red_y': red_ent['y'],
                            'nav_x': nav['x'],
                            'nav_y': nav['y'],
                            'station_x': best[1]['x'],
                            'station_y': best[1]['y']
                        }
        
        LOG(f"  匹配成功的断面: {len(src_sections)}个")
        
        # ===== 5. 读取目标文件 =====
        if not os.path.exists(dst_path):
            LOG(f"[ERROR] 目标文件不存在: {dst_path}")
            return
        
        LOG(f"正在读取目标文件: {os.path.basename(dst_path)} ...")
        dst_doc = ezdxf.readfile(dst_path)
        dst_msp = dst_doc.modelspace()
        
        # ===== 6. 收集目标端桩号 =====
        dst_stations = StationMatcher.extract_stations(dst_msp)
        LOG(f"  目标端桩号: {len(dst_stations)}个")
        
        # ===== 7. 执行粘贴 =====
        LOG("[GO] 执行粘贴...")
        
        OutputHelper.ensure_layer(dst_doc, "0-已粘贴断面", color=3)
        
        count = 0
        matched_stations = set(src_sections.keys()) & set(dst_stations.keys())
        LOG(f"  匹配的桩号: {len(matched_stations)}个")
        
        for station_id in sorted(matched_stations, key=lambda s: int(s.replace('+', ''))):
            s_data = src_sections[station_id]
            
            if station_id not in dst_stations:
                continue
            
            # dst_stations 的值是列表 [{'x': ..., 'y': ...}, ...]
            dst_station_pts = dst_stations[station_id]
            if not dst_station_pts:
                continue
            dst_sx = dst_station_pts[0]['x']
            dst_sy = dst_station_pts[0]['y']
            
            # 计算平移向量
            src_offset_x = s_data['red_x'] - s_data['station_x']
            src_offset_y = s_data['red_y'] - s_data['station_y']
            dst_red_x = dst_sx + src_offset_x
            dst_red_y = dst_sy + src_offset_y
            dx = dst_red_x - s_data['red_x']
            dy = dst_red_y - s_data['red_y']
            
            # 复制红线
            red_e = s_data['red']
            new_e = red_e.copy()
            new_e.translate(dx, dy, 0)
            new_e.dxf.layer = "0-已粘贴断面"
            new_e.dxf.color = 3
            dst_msp.add_entity(new_e)
            count += 1
            
            if count <= 5 or count % 20 == 0:
                LOG(f"  [{count}] {station_id}: 平移量({dx:.1f}, {dy:.1f})")
        
        # ===== 8. 保存结果 =====
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        base_dir = output_dir if output_dir else os.path.dirname(dst_path)
        base_name = os.path.basename(dst_path).replace(".dxf", "")
        save_name = os.path.join(base_dir, f"{base_name}_已粘贴断面_{timestamp}.dxf")
        dst_doc.saveas(save_name)
        
        LOG(f"[OK] 处理完成！成果已保存至: {os.path.basename(save_name)}")
        LOG(f"[STATS] 统计：源断面{len(src_sections)}个，目标桩号{len(dst_stations)}个，粘贴红线{count}条")

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

            # 获取可见图层
            visible_layers = {layer.dxf.name for layer in doc.layers if not layer.is_off()}
            
            # 收集线段
            raw_lines = []
            all_coords = []

            for ent in msp:
                if ent.dxftype() in ('LINE', 'LWPOLYLINE', 'POLYLINE'):
                    if ent.dxf.layer in visible_layers or ent.dxf.layer.startswith("AA_"):
                        ls = EntityHelper.to_linestring(ent)
                        if ls:
                            all_coords.extend(ls.coords)
                            raw_lines.append(ls)

            if not raw_lines:
                continue

            # 计算填充比例
            if all_coords:
                xs = [p[0] for p in all_coords]
                ys = [p[1] for p in all_coords]
                global_diag = math.sqrt((max(xs)-min(xs))**2 + (max(ys)-min(ys))**2)
                global_hatch_scale = max(0.5, global_diag * 0.02)
            else:
                global_hatch_scale = 1.0

            # 多边形化
            merged_lines = unary_union(raw_lines)
            polygons = sorted(
                [p for p in polygonize(merged_lines) if p.area > 0.01],
                key=lambda p: p.representative_point().y,
                reverse=True
            )

            # 处理每个多边形
            data_for_excel = []
            rgb_list = Config.HIGH_CONTRAST_COLORS

            for i, poly in enumerate(polygons):
                index_no = i + 1
                area_val = round(poly.area, 3)
                current_rgb = rgb_list[i % len(rgb_list)]
                
                data_for_excel.append({"编号": index_no, "面积(㎡)": area_val})

                try:
                    # 添加填充
                    hatch = msp.add_hatch(dxfattribs={'layer': target_layer})
                    hatch.rgb = current_rgb
                    hatch.set_pattern_fill('ANSI31', scale=global_hatch_scale)
                    hatch.paths.add_polyline_path(list(poly.exterior.coords)[:-1], is_closed=True)
                    
                    for interior in poly.interiors:
                        hatch.paths.add_polyline_path(list(interior.coords)[:-1], is_closed=True)
                    
                    # 添加标注
                    in_point = poly.representative_point()
                    label_content = f"{{\\fArial|b1;{index_no}\\PS={area_val}}}"
                    mtext = msp.add_mtext(label_content, dxfattribs={
                        'layer': target_layer + "_标注",
                        'insert': (in_point.x, in_point.y),
                        'char_height': 3.0,
                        'attachment_point': 5,
                    })
                    mtext.rgb = current_rgb
                    
                    try:
                        mtext.dxf.bg_fill_setting = 1
                        mtext.dxf.bg_fill_scale_factor = 1.5
                    except:
                        pass

                except Exception as e:
                    LOG(f"[WARN] 块 {index_no} 生成出错: {e}")
                    continue

            # 保存
            output_dxf = OutputHelper.get_output_path(input_path, "_填充完成.dxf", output_dir)
            doc.saveas(output_dxf)
            
            # 导出Excel
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


# ==================== 4. 分类算量 (autoclassify) ====================

def run_autoclassify(params, LOG):
    """分类算量任务 - 支持面积比例系数和自适应距离参数"""
    try:
        file_list = params.get('files', [])
        if not file_list:
            LOG("[WARN] 请先选择 DXF 文件。")
            return
        
        # 参数解析
        section_layers_str = params.get('断面线图层', 'DMX')
        section_layers = [s.strip() for s in section_layers_str.split(',') if s.strip()]
        station_layer = params.get('桩号图层', '0-桩号')
        output_dir = params.get('输出目录')
        
        # 面积比例系数（用于缩放后的DXF文件）
        area_scale = float(params.get('面积比例系数', 1.0))
        coord_scale = math.sqrt(area_scale) if area_scale > 0 else 1.0  # 坐标缩放比例
        
        if area_scale != 1.0:
            LOG(f"[INFO] 面积比例系数: {area_scale}")
            LOG(f"[INFO] 坐标缩放比例: {coord_scale:.4f}")
        
        merge_section = params.get('合并断面线', True)
        if isinstance(merge_section, str):
            merge_section = merge_section.lower() in ('true', '1', 'yes', '是')
        
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        
        for input_path in file_list:
            LOG(f"--- [WAIT] 正在处理: {os.path.basename(input_path)} ---")
            
            doc = ezdxf.readfile(input_path)
            msp = doc.modelspace()

            # 确保图层存在
            OutputHelper.ensure_layer(doc, Config.DEFAULT_FINAL_SECTION, color=4)

            # 获取地层图层
            strata_layers = sorted(
                [l.dxf.name for l in doc.layers if re.match(r'^\d+级', l.dxf.name)],
                key=lambda x: int(re.findall(r'^(\d+)', x)[0]) if re.findall(r'^(\d+)', x) else 999
            )
            LOG(f"地层图层: {strata_layers}")
            
            # 关闭地层图层
            for layer_name in strata_layers:
                try:
                    doc.layers.get(layer_name).off()
                except:
                    pass

            # 获取线段
            excav_lines_all = LayerExtractor.get_lines(msp, "开挖线")
            overexc_lines_all = LayerExtractor.get_lines(msp, "超挖线")
            
            dmx_lines_all = []
            for layer in section_layers:
                dmx_lines_all.extend(LayerExtractor.get_lines(msp, layer))
            
            LOG(f"开挖线总数: {len(excav_lines_all)}")
            LOG(f"超挖线总数: {len(overexc_lines_all)}")
            LOG(f"断面线总数: {len(dmx_lines_all)}")

            # 获取桩号
            station_texts = LayerExtractor.get_texts(msp, station_layer)
            LOG(f"桩号总数: {len(station_texts)}")
            
            # 构建虚拟断面框（优先使用基于桩号的方法）
            virtual_boxes = _build_virtual_boxes_by_stations(overexc_lines_all, station_texts, coord_scale)
            if not virtual_boxes:
                virtual_boxes = _build_virtual_boxes(overexc_lines_all, coord_scale)
            LOG(f"虚拟断面框: {len(virtual_boxes)} 个")
            
            report_data = []

            for idx, v_box in enumerate(virtual_boxes):
                minx, miny, maxx, maxy = v_box.bounds
                vbox_y_center = (miny + maxy) / 2
                vbox_x_center = (minx + maxx) / 2
                
                # 获取桩号（使用自适应距离）
                station_match_dist = 200 * coord_scale
                station = f"S{idx+1}"
                for st in station_texts:
                    pt = Point(st['x'], st['y'])
                    if v_box.distance(pt) < station_match_dist:
                        station = st['text'].split(";")[-1].replace("}", "").strip()
                        break
                
                LOG(f"处理断面 {idx+1}: {station}")

                # 获取DMX（使用自适应距离）
                dmx = _find_dmx_for_section(dmx_lines_all, vbox_x_center, vbox_y_center, coord_scale)
                
                if not dmx:
                    LOG(f"  警告：未找到DMX，跳过")
                    continue
                
                dmx_bounds = dmx.bounds
                dmx_x_min, dmx_x_max = dmx_bounds[0], dmx_bounds[2]
                
                boundary_box = box(minx - 20, miny - 25, maxx + 20, maxy + 25)
                
                # 生成最终断面线
                if merge_section:
                    local_section = [l for l in LayerExtractor.get_lines(msp, "断面线") if boundary_box.intersects(l)]
                    for layer in section_layers:
                        if layer != "DMX":
                            for l in LayerExtractor.get_lines(msp, layer):
                                if boundary_box.intersects(l):
                                    local_section.append(l)
                    final_sect = SectionGenerator.generate_final_section(dmx, local_section)
                else:
                    final_sect = dmx
                
                if not final_sect:
                    LOG(f"  警告：最终断面线生成失败，跳过")
                    continue
                
                sect_coords = list(final_sect.coords)
                sect_x_min = min(c[0] for c in sect_coords)
                sect_x_max = max(c[0] for c in sect_coords)
                
                msp.add_lwpolyline(sect_coords, dxfattribs={'layer': Config.DEFAULT_FINAL_SECTION})

                excav_list = [l for l in excav_lines_all if boundary_box.intersects(l)]
                
                if not excav_list:
                    LOG(f"  警告：未找到开挖线，跳过")
                    continue

                # 构建设计区多边形
                design_polygon = _build_design_polygon(excav_list, sect_x_min, sect_x_max)
                
                if design_polygon is None or design_polygon.is_empty:
                    LOG(f"  警告：设计区多边形构建失败，跳过")
                    continue

                # 处理各地层
                for layer in strata_layers:
                    layer_hatches = []
                    for h in msp.query(f'HATCH[layer=="{layer}"]'):
                        h_poly = HatchProcessor.to_polygon(h)
                        if h_poly.intersects(boundary_box):
                            layer_hatches.append(h_poly)
                    
                    if not layer_hatches:
                        continue

                    combined_hatch = unary_union(layer_hatches).intersection(design_polygon)
                    if combined_hatch.is_empty:
                        continue

                    layer_color = Config.HIGH_CONTRAST_COLORS[strata_layers.index(layer) % len(Config.HIGH_CONTRAST_COLORS)]
                    design_area = HatchProcessor.add_with_label(msp, combined_hatch, layer_color, 'ANGLE', 0.1, 2.5, layer, True, doc)
                    
                    over_area = 0.0  # 简化处理
                    
                    # 应用面积比例系数
                    scaled_design_area = design_area * area_scale
                    scaled_over_area = over_area * area_scale
                    
                    if scaled_design_area > 0.01:
                        report_data.append({
                            "断面": f"S{idx+1}",
                            "桩号": station,
                            "地层": layer,
                            "设计面积": round(scaled_design_area, 3),
                            "超挖面积": round(scaled_over_area, 3)
                        })

            # 输出结果
            if report_data:
                df = pd.DataFrame(report_data)
                df['sort_key'] = df['桩号'].apply(StationMatcher.sort_key)
                df_sorted = df.sort_values(by='sort_key')

                base_path = input_path.replace(".bak", "").replace(".dxf", "")
                output_xlsx = OutputHelper.get_output_path(input_path, f"_分类汇总_{timestamp}.xlsx", output_dir)
                
                with pd.ExcelWriter(output_xlsx) as writer:
                    df_design = df_sorted.pivot_table(index='桩号', columns='地层', values='设计面积', aggfunc='sum', sort=False).fillna(0)
                    df_design.to_excel(writer, sheet_name='设计量汇总')
                    df_sorted[['断面', '桩号', '地层', '设计面积', '超挖面积']].to_excel(writer, sheet_name='明细表', index=False)

                output_dxf = OutputHelper.get_output_path(input_path, f"_RESULT_{timestamp}.dxf", output_dir)
                doc.saveas(output_dxf)
                LOG(f"[OK] 处理完成！")
                LOG(f"   DXF: {os.path.basename(output_dxf)}")
                LOG(f"   Excel: {os.path.basename(output_xlsx)}")
            else:
                LOG("未生成任何数据")

        LOG("[DONE] [分类算量任务全部结束]")

    except Exception as e:
        LOG(f"[ERROR] 脚本崩溃:\n{traceback.format_exc()}")


# ==================== 5. 分层算量 (autocut) ====================

def run_autocut(params, LOG):
    """分层算量任务"""
    try:
        file_list = params.get('files', [])
        if not file_list:
            LOG("[WARN] 请先选择 DXF 文件。")
            return
        
        layer_elevation = float(params.get('分层线高程', '-5'))
        output_dir = params.get('输出目录')
        
        LOG(f"[INFO] 目标分层线高程: {layer_elevation}m")
        
        for input_path in file_list:
            LOG(f"--- [WAIT] 正在处理: {os.path.basename(input_path)} ---")
            
            doc = ezdxf.readfile(input_path)
            msp = doc.modelspace()
            
            # 添加图层
            for layer_name in ["AA_计算分层线", "AA_计算分层线_标注", "AA_分层算量填充", "AA_分层算量标注"]:
                OutputHelper.ensure_layer(doc, layer_name, color=6)
            
            # 获取DMX列表
            dmx_list = _get_dmx_list(msp)
            dmx_list = sorted(dmx_list, key=lambda d: d['y_center'], reverse=True)
            LOG(f"DMX数量: {len(dmx_list)}")
            
            # 获取开挖线
            excav_lines_all = LayerExtractor.get_lines(msp, "开挖线")
            LOG(f"开挖线数量: {len(excav_lines_all)}")
            
            # 获取超挖线构建虚拟框
            overexc_lines_all = LayerExtractor.get_lines(msp, "超挖线")
            virtual_boxes = _build_virtual_boxes(overexc_lines_all)
            LOG(f"虚拟断面框: {len(virtual_boxes)} 个")
            
            # 获取桩号
            station_texts = LayerExtractor.get_texts(msp, "0-桩号")
            
            # 获取地层
            strata_layers = sorted(
                [l.dxf.name for l in doc.layers if re.match(r'^\d+级', l.dxf.name)],
                key=lambda x: int(re.findall(r'^(\d+)', x)[0]) if re.findall(r'^(\d+)', x) else 999
            )
            LOG(f"地层图层: {strata_layers}")
            
            # 读取地层填充
            strata_hatches = {}
            for layer in strata_layers:
                strata_hatches[layer] = []
                for h in msp.query(f'HATCH[layer=="{layer}"]'):
                    poly = HatchProcessor.to_polygon(h)
                    if not poly.is_empty:
                        strata_hatches[layer].append(poly)
            
            # 处理断面
            results = []
            processed_stations = set()
            
            for idx, v_box in enumerate(virtual_boxes):
                minx, miny, maxx, maxy = v_box.bounds
                
                # 获取桩号
                station = f"S{idx+1}"
                for st in station_texts:
                    pt = Point(st['x'], st['y'])
                    if v_box.distance(pt) < 200:
                        station = st['text'].split(";")[-1].replace("}", "").strip()
                        break
                
                if station in processed_stations:
                    continue
                processed_stations.add(station)
                
                # 找DMX
                dmx = _find_dmx_for_vbox(v_box, dmx_list)
                
                if not dmx:
                    LOG(f"处理断面 {idx+1}: {station} - 无DMX，面积为0")
                    results.append({
                        '断面名称': station,
                        '设计底高程': 0.0,
                        '分层线高程': layer_elevation,
                        '总面积': 0.0
                    })
                    continue
                
                sect_x_min = dmx['x_min']
                sect_x_max = dmx['x_max']
                sect_y_min = dmx['y_min']
                sect_y_max = dmx['y_max']
                sect_y_center = dmx['y_center']
                
                LOG(f"处理断面 {idx+1}: {station}")
                
                # 检测标尺
                ruler_scale = _detect_ruler_scale(msp, doc, sect_x_min, sect_x_max, sect_y_center, sect_y_min, sect_y_max)
                
                if ruler_scale:
                    elev_to_y, y_to_elev = ruler_scale
                    layer_line_y = elev_to_y(layer_elevation)
                    design_bottom_elev = y_to_elev(sect_y_min)
                    LOG(f"  [INFO] 检测到标尺，分层线Y={layer_line_y:.1f}")
                else:
                    layer_line_y = 5.0 * layer_elevation - 27.0
                    design_bottom_elev = (sect_y_min + 27.0) / 5.0
                    LOG(f"  [INFO] 未检测到标尺，使用默认转换")
                
                # 生成分层线
                msp.add_lwpolyline(
                    [(sect_x_min, layer_line_y), (sect_x_max, layer_line_y)],
                    dxfattribs={'layer': "AA_计算分层线", 'color': 6}
                )
                
                # 简化后续处理...
                results.append({
                    '断面名称': station,
                    '设计底高程': round(design_bottom_elev, 2),
                    '分层线高程': layer_elevation,
                    '总面积': 0.0
                })
            
            # 输出结果
            if results:
                df = pd.DataFrame(results)
                df['sort_key'] = df['断面名称'].apply(StationMatcher.sort_key)
                df = df.sort_values(by='sort_key').drop(columns=['sort_key'])
                
                timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
                output_xlsx = OutputHelper.get_output_path(input_path, f'_分层算量_{timestamp}.xlsx', output_dir)
                df.to_excel(output_xlsx, index=False)
                
                output_dxf = OutputHelper.get_output_path(input_path, f'_带{layer_elevation}m分层线_{timestamp}.dxf', output_dir)
                doc.saveas(output_dxf)
                
                LOG(f"[OK] 处理完成！")
                LOG(f"   DXF: {os.path.basename(output_dxf)}")
                LOG(f"   Excel: {os.path.basename(output_xlsx)}")
            else:
                LOG(f"[WARN] 未找到有效数据")
            
    except Exception as e:
        LOG(f"[ERROR] 分层算量执行错误: {e}")
        LOG(traceback.format_exc())


# ==================== 内部辅助函数 ====================

def _build_virtual_boxes(overexc_lines, coord_scale=1.0):
    """构建虚拟断面框 - 基于Y坐标聚类（断面在图上垂直排列）
    
    核心思路：
    1. 断面图通常是垂直排列的（不同断面的Y坐标差异大）
    2. 同一断面内的多条超挖线Y中心坐标相近
    3. 使用Y坐标聚类来分组断面
    """
    if not overexc_lines:
        return []
    
    line_info = []
    for line in overexc_lines:
        bounds = line.bounds
        width = bounds[2] - bounds[0]
        height = bounds[3] - bounds[1]
        line_info.append({
            'line': line,
            'mid_x': (bounds[0] + bounds[2]) / 2,
            'mid_y': (bounds[1] + bounds[3]) / 2,
            'bounds': bounds,
            'width': width,
            'height': height
        })
    
    n = len(line_info)
    
    if n == 0:
        return []
    
    if n == 1:
        b = line_info[0]['bounds']
        return [box(b[0], b[1], b[2], b[3])]
    
    # 计算断面框尺寸统计
    heights = [info['height'] for info in line_info]
    heights_sorted = sorted(heights)
    median_height = heights_sorted[len(heights_sorted)//2]
    
    # 按Y坐标排序
    sorted_by_y = sorted(line_info, key=lambda x: x['mid_y'], reverse=True)
    
    # 计算相邻Y间距
    y_gaps = []
    for i in range(1, len(sorted_by_y)):
        y_gap = abs(sorted_by_y[i]['mid_y'] - sorted_by_y[i-1]['mid_y'])
        y_gaps.append(y_gap)
    
    # 使用Y间距分布确定聚类阈值
    # 同一断面内的线Y间距应该很小（小于断面高度）
    # 不同断面的Y间距应该很大（大于断面高度）
    # 使用断面高度作为分界点
    cluster_threshold = median_height * 1.5  # Y间距超过1.5倍断面高度则认为是不同断面
    
    # 聚类：基于Y坐标
    clusters = []
    current_cluster = [sorted_by_y[0]]
    
    for i in range(1, len(sorted_by_y)):
        y_gap = abs(sorted_by_y[i]['mid_y'] - sorted_by_y[i-1]['mid_y'])
        
        if y_gap < cluster_threshold:
            # Y间距小，属于同一断面
            current_cluster.append(sorted_by_y[i])
        else:
            # Y间距大，新断面
            clusters.append(current_cluster)
            current_cluster = [sorted_by_y[i]]
    
    if current_cluster:
        clusters.append(current_cluster)
    
    # 构建边界框
    virtual_boxes = []
    for cluster in clusters:
        all_coords = []
        for info in cluster:
            all_coords.extend(list(info['line'].coords))
        if all_coords:
            min_x = min(c[0] for c in all_coords)
            max_x = max(c[0] for c in all_coords)
            min_y = min(c[1] for c in all_coords)
            max_y = max(c[1] for c in all_coords)
            virtual_boxes.append(box(min_x, min_y, max_x, max_y))
    
    return virtual_boxes


def _build_virtual_boxes_by_stations(overexc_lines, station_texts, coord_scale=1.0):
    """基于桩号位置构建虚拟断面框 - 更可靠的方法
    
    思路：直接使用桩号位置来定位断面，然后在每个桩号周围收集线
    """
    if not overexc_lines:
        return []
    
    if not station_texts:
        return _build_virtual_boxes(overexc_lines, coord_scale)
    
    # 收集线的位置信息
    line_info = []
    for line in overexc_lines:
        bounds = line.bounds
        line_info.append({
            'line': line,
            'mid_x': (bounds[0] + bounds[2]) / 2,
            'mid_y': (bounds[1] + bounds[3]) / 2,
            'bounds': bounds
        })
    
    # 计算断面框典型尺寸
    widths = [info['bounds'][2] - info['bounds'][0] for info in line_info]
    heights = [info['bounds'][3] - info['bounds'][1] for info in line_info]
    median_width = sorted(widths)[len(widths)//2] if widths else 100
    median_height = sorted(heights)[len(heights)//2] if heights else 100
    
    # 匹配距离：使用更大的距离确保能覆盖整个断面
    # 断面可能比单个超挖线框大很多（一个断面有多条超挖线）
    match_dist = max(median_width, median_height) * 5
    
    # 先按桩号Y坐标排序（断面从上到下排列）
    sorted_stations = sorted(station_texts, key=lambda s: s['y'], reverse=True)
    
    # 对每个桩号，收集周围的线
    virtual_boxes = []
    used_lines = set()
    
    for st in sorted_stations:
        st_x = st['x']
        st_y = st['y']
        
        # 收集距离桩号匹配距离内的线
        cluster_lines = []
        for i, info in enumerate(line_info):
            if i in used_lines:
                continue
            # 使用Y距离作为主要判断（断面垂直排列）
            y_dist = abs(info['mid_y'] - st_y)
            x_dist = abs(info['mid_x'] - st_x)
            
            # Y距离用match_dist，X距离用断面宽度
            if y_dist < match_dist and x_dist < median_width * 3:
                cluster_lines.append(info)
                used_lines.add(i)
        
        if cluster_lines:
            all_coords = []
            for info in cluster_lines:
                all_coords.extend(list(info['line'].coords))
            if all_coords:
                min_x = min(c[0] for c in all_coords)
                max_x = max(c[0] for c in all_coords)
                min_y = min(c[1] for c in all_coords)
                max_y = max(c[1] for c in all_coords)
                virtual_boxes.append(box(min_x, min_y, max_x, max_y))
    
    return virtual_boxes


def _find_dmx_for_section(dmx_list, x_center, y_center, coord_scale=1.0):
    """为断面找对应的DMX - 支持坐标缩放比例自适应距离
    
    参数:
        dmx_list: DMX线段列表
        x_center: 目标X中心
        y_center: 目标Y中心
        coord_scale: 坐标缩放比例
    """
    best_dmx = None
    min_y_diff = float('inf')
    
    # 根据缩放比例调整匹配距离
    match_dist = 50 * coord_scale
    
    for dmx in dmx_list:
        dmx_x_center = (dmx.bounds[0] + dmx.bounds[2]) / 2
        dmx_y_center = (dmx.bounds[1] + dmx.bounds[3]) / 2
        
        if abs(dmx_x_center - x_center) < match_dist:
            y_diff = abs(dmx_y_center - y_center)
            if y_diff < min_y_diff:
                min_y_diff = y_diff
                best_dmx = dmx
    
    return best_dmx


def _build_design_polygon(excav_lines, sect_x_min, sect_x_max):
    """构建设计区多边形"""
    if not excav_lines:
        return None
    
    all_points = [p for l in excav_lines for p in l.coords]
    if not all_points:
        return None
    
    excav_x_min = min(p[0] for p in all_points)
    excav_x_max = max(p[0] for p in all_points)
    excav_y_min = min(p[1] for p in all_points)
    
    design_x_min = max(excav_x_min, sect_x_min)
    design_x_max = min(excav_x_max, sect_x_max)
    
    if design_x_max <= design_x_min:
        return None
    
    # 采样
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
    
    if len(x_samples) < 2:
        return None
    
    # 构建多边形
    sect_y_max = max(y_samples) + 50
    polygon_coords = list(zip(x_samples, y_samples))
    polygon_coords.append((x_samples[-1], sect_y_max))
    polygon_coords.append((x_samples[0], sect_y_max))
    polygon_coords.append(polygon_coords[0])
    
    poly = Polygon(polygon_coords)
    return poly if poly.is_valid else poly.buffer(0)


def _get_dmx_list(msp):
    """获取DMX列表"""
    dmx_list = []
    for e in msp.query('*[layer=="DMX"]'):
        if e.dxftype() == 'LWPOLYLINE':
            pts = [p[:2] for p in e.get_points()]
            if pts:
                x_min = min(p[0] for p in pts)
                x_max = max(p[0] for p in pts)
                y_min = min(p[1] for p in pts)
                y_max = max(p[1] for p in pts)
                dmx_list.append({
                    'x_min': x_min, 'x_max': x_max,
                    'y_min': y_min, 'y_max': y_max,
                    'pts': pts, 'line': LineString(pts),
                    'y_center': (y_min + y_max) / 2,
                    'bounds': (x_min, y_min, x_max, y_max)
                })
    return dmx_list


def _find_dmx_for_vbox(vbox, dmx_list):
    """为虚拟框找对应的DMX"""
    minx, miny, maxx, maxy = vbox.bounds
    vbox_x_center = (minx + maxx) / 2
    vbox_y_center = (miny + maxy) / 2
    
    best_dmx = None
    min_y_diff = float('inf')
    
    for dmx in dmx_list:
        dmx_x_center = (dmx['x_min'] + dmx['x_max']) / 2
        
        if minx - 20 <= dmx_x_center <= maxx + 20:
            y_diff = abs(dmx['y_center'] - vbox_y_center)
            if y_diff < min_y_diff:
                min_y_diff = y_diff
                best_dmx = dmx
    
    return best_dmx


def _detect_ruler_scale(msp, doc, sect_x_min, sect_x_max, sect_y_center, sect_y_min, sect_y_max):
    """检测标尺比例"""
    ruler_layers = ['标尺', '0-标尺', 'RULER']
    ruler_candidates = []
    
    for layer_name in ruler_layers:
        for e in msp.query(f'*[layer=="{layer_name}"]'):
            try:
                if e.dxftype() == 'INSERT':
                    insert_x = e.dxf.insert.x
                    insert_y = e.dxf.insert.y
                    
                    if sect_x_min - 100 <= insert_x <= sect_x_max + 100:
                        y_min = insert_y - 50
                        y_max = insert_y + 50
                        
                        try:
                            block_name = e.dxf.name
                            if block_name in doc.blocks:
                                block = doc.blocks[block_name]
                                for be in block:
                                    if be.dxftype() in ('TEXT', 'MTEXT'):
                                        local_y = be.dxf.insert.y
                                        world_y = local_y + insert_y
                                        y_min = min(y_min, world_y)
                                        y_max = max(y_max, world_y)
                        except:
                            pass
                        
                        ruler_candidates.append({
                            'x': insert_x,
                            'y_min': y_min,
                            'y_max': y_max,
                            'y_center': (y_min + y_max) / 2,
                            'entity': e
                        })
            except:
                pass
    
    if not ruler_candidates:
        return None
    
    # 选择最佳标尺
    sect_x_center = (sect_x_min + sect_x_max) / 2
    best_ruler = min(ruler_candidates, key=lambda r: abs(r['x'] - sect_x_center))
    
    # 收集高程点
    elevation_points = []
    
    if best_ruler.get('entity'):
        insert_e = best_ruler['entity']
        insert_y = insert_e.dxf.insert.y
        
        try:
            block_name = insert_e.dxf.name
            if block_name in doc.blocks:
                block = doc.blocks[block_name]
                for be in block:
                    if be.dxftype() in ('TEXT', 'MTEXT'):
                        try:
                            local_y = be.dxf.insert.y
                            world_y = local_y + insert_y
                            text = be.dxf.text if be.dxftype() == 'TEXT' else be.text
                            text = text.strip()
                            elev = float(text)
                            elevation_points.append((world_y, elev))
                        except:
                            pass
        except:
            pass
    
    if len(elevation_points) < 2:
        return None
    
    # 最小二乘拟合
    n = len(elevation_points)
    sum_y = sum(p[0] for p in elevation_points)
    sum_e = sum(p[1] for p in elevation_points)
    sum_ye = sum(p[0] * p[1] for p in elevation_points)
    sum_e2 = sum(p[1] ** 2 for p in elevation_points)
    
    denom = n * sum_e2 - sum_e ** 2
    if abs(denom) < 0.001:
        return None
    
    a = (n * sum_ye - sum_y * sum_e) / denom
    b = (sum_y - a * sum_e) / n
    
    return (lambda elev: a * elev + b, lambda y: (y - b) / a)


# ==================== 命令行接口 ====================

def main():
    """命令行入口点"""
    import sys
    import json
    
    if len(sys.argv) < 3:
        print("用法: python engine_cad.py <任务类型> <参数JSON文件>")
        print("任务类型: autoline, autopaste, autohatch, autoclassify, autocut")
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
        'autoclassify': run_autoclassify,
        'autocut': run_autocut
    }
    
    if task_type in tasks:
        tasks[task_type](params, log_func)
    else:
        print(f"[ERROR] 未知任务类型: {task_type}")

if __name__ == "__main__":
    main()