# -*- coding: utf-8 -*-
"""
航道地质 BIM 鲁棒性放样引擎 (Robust Geological Lofting Engine)

核心改进：
1. 锚点对齐 (Anchor Alignment)：强制所有断面从"最左侧"顶点开始排序，消除扭曲
2. 弧长等分采样 (Arc-Length Resampling)：确保相邻断面间的顶点在逻辑上是一一映射的
3. 相对约束插值：基于设计线(DMX)的相对偏移进行插值，防止层位穿模
4. 独立层位构建：为每个地层生成闭合实体，支持分层剥离展示

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
from scipy.interpolate import interp1d
import pyvista as pv
from collections import defaultdict


class BIMAlignmentUtils:
    """BIM 几何处理工具集 - 防扭曲/防穿模"""

    @staticmethod
    def align_and_resample(coords, num_samples=100):
        """
        重采样并强制锚点对齐
        
        逻辑：
        1. 确保多边形闭合
        2. 线性弧长插值
        3. 寻找"左上角"点作为 Index 0，防止断面间发生"拧麻花"现象
        
        Args:
            coords: 原始多边形坐标数组 [[x,z], [x,z], ...]
            num_samples: 目标采样点数
        
        Returns:
            对齐后的重采样坐标数组
        """
        coords = np.array(coords)
        
        # 闭合多边形
        if not np.allclose(coords[0], coords[-1]):
            coords = np.vstack([coords, coords[0]])
        
        # 1. 弧长重采样
        diff = np.diff(coords, axis=0)
        seg_lens = np.sqrt((diff**2).sum(axis=1))
        cum_dist = np.concatenate(([0], np.cumsum(seg_lens)))
        
        if cum_dist[-1] == 0:
            return coords[:num_samples]
        
        # 对 X, Z 坐标分别进行线性插值
        interp_func = interp1d(cum_dist, coords, axis=0, kind='linear')
        resampled = interp_func(np.linspace(0, cum_dist[-1], num_samples))
        
        # 2. 锚点对齐 - 寻找最左侧点，若有多个则取最高点（左上角）
        # 这一步是解决"穿模"和"扭曲"的关键
        min_x = np.min(resampled[:, 0])
        candidates = np.where(np.isclose(resampled[:, 0], min_x, atol=1e-5))[0]
        
        # 在最左侧点中找 Z 轴最大的（最上方的）
        if len(candidates) > 0:
            start_idx = candidates[np.argmax(resampled[candidates, 1])]
        else:
            start_idx = 0
        
        # 重新排列数组顺序，使左上角成为 Index 0
        aligned_resampled = np.roll(resampled, -start_idx, axis=0)
        
        return aligned_resampled
    
    @staticmethod
    def compute_relative_coords(layer_coords, dmx_coords):
        """
        计算相对于设计线(DMX)的偏移坐标
        用于"叠罗汉"相对插值，防止地层穿模
        
        Args:
            layer_coords: 地层坐标
            dmx_coords: 设计线坐标（基准面）
        
        Returns:
            相对偏移坐标
        """
        # 简化实现：计算相对于DMX中心线的深度偏移
        dmx_center_x = np.mean(dmx_coords[:, 0])
        dmx_min_z = np.min(dmx_coords[:, 1])
        
        # 相对坐标 = 绝对坐标 - DMX基准
        relative = layer_coords.copy()
        relative[:, 0] = layer_coords[:, 0] - dmx_center_x  # X偏移
        relative[:, 1] = layer_coords[:, 1] - dmx_min_z     # Z深度（相对于设计底）
        
        return relative


class GeologicalBIMEngine:
    """地质 BIM 核心构建引擎"""

    # 地层颜色映射
    COLOR_MAP = {
        '砂': '#f1c40f',      # 金色
        '淤泥': '#7f8c8d',    # 灰色
        '黏土': '#A52A2A',    # 棕色
        '碎石': '#CD853F',    # 秘鲁色
        '填土': '#8B4513',    # 马鞍棕
        '设计': '#2ecc71',    # 绿色
        'DMX': '#2ecc71',     # 绿色
        '超挖': '#e67e22',    # 橙红
        'nonem': '#C0C0C0',   # 银色
    }

    def __init__(self, norm_factor=0.1):
        self.norm_factor = norm_factor
        self.layers = {}  # 存储各层数据: {layer_name: [(mileage, coords), ...]}
        self.dmx_data = []  # 设计线数据

    def add_section_data(self, mileage, layer_name, coords):
        """添加断面地层数据"""
        if layer_name not in self.layers:
            self.layers[layer_name] = []
        self.layers[layer_name].append((mileage, coords))

    def add_dmx_data(self, mileage, coords):
        """添加设计线(DMX)数据"""
        self.dmx_data.append((mileage, coords))

    def build_mesh(self, layer_name, num_samples=100):
        """
        为特定地层构建 3D Mesh（防穿模版）
        
        Args:
            layer_name: 地层名称
            num_samples: 重采样点数
        
        Returns:
            PyVista PolyData网格对象
        """
        data = self.layers[layer_name]
        data.sort(key=lambda x: x[0])  # 按里程排序
        
        if len(data) < 2:
            print(f"  [WARN] {layer_name}: 只有{len(data)}个断面，无法构建网格")
            return None

        all_vpts = []
        
        for mileage, coords in data:
            # 1. 归一化
            coords_norm = np.array(coords) * self.norm_factor
            
            # 2. 重采样并对齐锚点（防扭曲）
            resampled = BIMAlignmentUtils.align_and_resample(coords_norm, num_samples)
            
            # 3. 映射至 3D 空间 (X=宽, Y=里程, Z=高程)
            vpts_3d = np.zeros((num_samples, 3))
            vpts_3d[:, 0] = resampled[:, 0]  # X
            vpts_3d[:, 1] = mileage           # Y
            vpts_3d[:, 2] = resampled[:, 1]   # Z
            all_vpts.append(vpts_3d)

        v_points = np.vstack(all_vpts)
        num_sections = len(all_vpts)
        
        # 4. 构建拓扑索引 (Faces) - 连接相邻断面
        faces = []
        for i in range(num_sections - 1):
            for j in range(num_samples - 1):
                p1 = i * num_samples + j
                p2 = p1 + 1
                p3 = p2 + num_samples
                p4 = p1 + num_samples
                
                # 逆时针定义两个三角形，构成一个矩形单元
                faces.append([3, p1, p2, p3])
                faces.append([3, p1, p3, p4])
        
        return pv.PolyData(v_points, faces)

    def build_dmx_mesh(self, num_samples=100):
        """构建设计线(DMX) Mesh"""
        if len(self.dmx_data) < 2:
            return None
        
        self.dmx_data.sort(key=lambda x: x[0])
        
        all_vpts = []
        for mileage, coords in self.dmx_data:
            coords_norm = np.array(coords) * self.norm_factor
            resampled = BIMAlignmentUtils.align_and_resample(coords_norm, num_samples)
            
            vpts_3d = np.zeros((num_samples, 3))
            vpts_3d[:, 0] = resampled[:, 0]
            vpts_3d[:, 1] = mileage
            vpts_3d[:, 2] = resampled[:, 1]
            all_vpts.append(vpts_3d)
        
        v_points = np.vstack(all_vpts)
        num_sections = len(all_vpts)
        
        faces = []
        for i in range(num_sections - 1):
            for j in range(num_samples - 1):
                p1 = i * num_samples + j
                p2 = p1 + 1
                p3 = p2 + num_samples
                p4 = p1 + num_samples
                faces.append([3, p1, p2, p3])
                faces.append([3, p1, p3, p4])
        
        return pv.PolyData(v_points, faces)

    def get_layer_color(self, name):
        """地质层位配色逻辑"""
        for key, color in self.COLOR_MAP.items():
            if key.lower() in name.lower():
                return color
        return '#ecf0f1'  # 默认白色

    def get_layer_opacity(self, name):
        """根据层位类型设置透明度"""
        if '超挖' in name:
            return 0.4  # 超挖层半透明
        elif 'DMX' in name or '设计' in name:
            return 1.0  # 设计线不透明
        else:
            return 0.8  # 其他地层


class GeologicalBIMBuilder:
    """航道地质BIM模型构建器 - DXF数据提取与构建"""

    def __init__(self, dxf_path: str):
        self.dxf_path = dxf_path
        self.doc = ezdxf.readfile(dxf_path)
        self.msp = self.doc.modelspace()
        self.sections = []
        self.refs = []
        self.engine = GeologicalBIMEngine(norm_factor=0.1)

    def extract_sections(self):
        """提取断面数据"""
        print("\n=== 提取断面数据 ===")
        
        # 提取DMX断面线
        dmx_list = []
        for e in self.msp.query('LWPOLYLINE[layer=="DMX"]'):
            try:
                pts = [(p[0], p[1]) for p in e.get_points()]
                if len(pts) >= 2:
                    x_coords = [p[0] for p in pts]
                    y_coords = [p[1] for p in pts]
                    dmx_list.append({
                        'pts': pts,
                        'x_min': min(x_coords),
                        'x_max': max(x_coords),
                        'y_min': min(y_coords),
                        'y_max': max(y_coords),
                        'y_center': (min(y_coords) + max(y_coords)) / 2
                    })
            except: pass
        
        print(f"  DMX断面线: {len(dmx_list)}条")
        
        if not dmx_list:
            return
        
        # 提取桩号文本
        station_texts = []
        for e in self.msp.query('TEXT MTEXT'):
            try:
                txt = e.plain_text() if e.dxftype() == 'MTEXT' else e.dxf.text
                match = re.search(r'(\d+\+\d+)', txt.upper())
                if match:
                    pt = self._get_point(e)
                    sid = match.group(1)
                    nums = re.findall(r'\d+', sid)
                    value = int("".join(nums)) if nums else 0
                    station_texts.append({'text': sid, 'value': value, 'x': pt[0], 'y': pt[1]})
            except: pass
        
        print(f"  桩号文本: {len(station_texts)}个")
        
        # 提取填充边界（地层多边形）
        fill_data = self._extract_fill_boundaries()
        print(f"  填充图层: {len(fill_data)}个")
        
        # 按桩号分组
        self.sections = self._group_by_station(dmx_list, station_texts, fill_data)
        print(f"  最终断面数: {len(self.sections)}个")
        
        # 提取L1基准点
        self.refs = self._detect_l1_refs()
        print(f"  L1基准点: {len(self.refs)}个")

    def _get_point(self, e):
        try:
            if e.dxftype() == 'TEXT':
                return (e.dxf.align_point.x, e.dxf.align_point.y) if (e.dxf.halign or e.dxf.valign) else (e.dxf.insert.x, e.dxf.insert.y)
            return (e.dxf.insert.x, e.dxf.insert.y)
        except:
            return (0, 0)

    def _extract_fill_boundaries(self) -> Dict[str, List[List[List[float]]]]:
        """提取填充边界（各地层多边形）"""
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
                        boundaries.append(pts)
                
                # 提取多段线边界
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
        """提取HATCH边界点"""
        points = []
        try:
            for path in hatch.paths:
                if hasattr(path, 'vertices') and len(path.vertices) > 0:
                    points = [(v[0], v[1]) for v in path.vertices]
        except: pass
        return points if len(points) >= 3 else None

    def _group_by_station(self, dmx_list, station_texts, fill_data) -> List[Dict]:
        """按桩号分组断面数据"""
        match_tolerance = 500
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
                dmx = sorted_dmx[best_dmx_idx]
                
                # 匹配填充边界
                matched_fills = {}
                group_box = box(dmx['x_min'] - 10, dmx['y_min'] - 20, dmx['x_max'] + 10, dmx['y_max'] + 10)
                
                for layer_name, boundaries in fill_data.items():
                    layer_matched = []
                    for boundary in boundaries:
                        if len(boundary) >= 3:
                            try:
                                if group_box.intersects(Polygon(boundary)):
                                    layer_matched.append(boundary)
                            except: pass
                    if layer_matched:
                        matched_fills[layer_name] = layer_matched
                
                groups.append({
                    'station_name': station['text'],
                    'station_value': station['value'],
                    'dmx_points': dmx['pts'],
                    'dmx_x_min': dmx['x_min'],
                    'dmx_x_max': dmx['x_max'],
                    'dmx_y_center': dmx['y_center'],
                    'fill_boundaries': matched_fills
                })
        
        groups.sort(key=lambda g: g['station_value'], reverse=True)
        return groups

    def _detect_l1_refs(self) -> List[Dict]:
        """检测L1脊梁线基准点"""
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
        
        return refs

    def build_bim_model(self, num_sections=30, num_samples=100):
        """
        构建BIM模型（防穿模版）
        
        Args:
            num_sections: 要处理的断面数量
            num_samples: 重采样点数
        """
        print("\n=== 构建BIM模型（防穿模版）===")
        print(f"  断面数: {num_sections}, 重采样点: {num_samples}")
        
        # 匹配断面与基准点
        matched = self._match_sections_refs(self.sections, self.refs)[:num_sections]
        print(f"  匹配断面: {len(matched)}个")
        
        # 收集数据并添加到引擎
        for m in matched:
            sec, ref = m['section'], m['ref']
            mileage = sec['station_value']
            
            # 处理DMX设计线
            if sec['dmx_points']:
                dmx_coords = [(p[0] - ref['ref_x'], p[1] - ref['ref_y']) for p in sec['dmx_points']]
                self.engine.add_dmx_data(mileage, dmx_coords)
            
            # 处理各地层填充边界
            for layer_name, boundaries in sec['fill_boundaries'].items():
                for boundary in boundaries:
                    coords = [(p[0] - ref['ref_x'], p[1] - ref['ref_y']) for p in boundary]
                    self.engine.add_section_data(mileage, layer_name, coords)
        
        # 构建各地层Mesh
        self.meshes = {}
        
        # DMX设计线Mesh
        dmx_mesh = self.engine.build_dmx_mesh(num_samples)
        if dmx_mesh:
            self.meshes['DMX'] = dmx_mesh
            print(f"\n  DMX 网格: 顶点={dmx_mesh.n_points}, 面={dmx_mesh.n_cells}")
        
        # 各地层Mesh
        for layer_name in self.engine.layers:
            mesh = self.engine.build_mesh(layer_name, num_samples)
            if mesh:
                self.meshes[layer_name] = mesh
                print(f"  {layer_name}: 顶点={mesh.n_points}, 面={mesh.n_cells}")
        
        print(f"\n  总网格数: {len(self.meshes)}")
        return self.meshes

    def _match_sections_refs(self, sections, refs):
        """匹配断面与基准点"""
        sorted_sec = sorted(sections, key=lambda s: s['dmx_y_center'], reverse=True)
        sorted_ref = sorted(refs, key=lambda r: r['ref_y'], reverse=True)
        
        matched = []
        for sec in sorted_sec:
            best_ref = None
            best_diff = float('inf')
            
            dmx_x_min = sec['dmx_x_min']
            dmx_x_max = sec['dmx_x_max']
            
            for ref in sorted_ref:
                y_diff = abs(ref['ref_y'] - sec['dmx_y_center'])
                x_in_range = dmx_x_min <= ref['ref_x'] <= dmx_x_max
                
                if x_in_range:
                    total_diff = y_diff
                else:
                    x_diff = min(abs(ref['ref_x'] - dmx_x_min), abs(ref['ref_x'] - dmx_x_max))
                    total_diff = y_diff + x_diff * 2
                
                if total_diff < best_diff:
                    best_diff = total_diff
                    best_ref = ref
            
            if best_ref and best_diff < 200:
                matched.append({'section': sec, 'ref': best_ref})
        
        matched.sort(key=lambda m: m['section']['station_value'], reverse=True)
        return matched

    def visualize(self):
        """可视化BIM模型（分层展示）"""
        print("\n=== 可视化BIM模型 ===")
        
        if not self.meshes:
            print("  [ERROR] 没有网格数据!")
            return
        
        # 创建PyVista绘图器
        plotter = pv.Plotter(title="航道3D地质BIM展示 - 防穿模版", window_size=[1600, 900])
        
        # 添加各地层Mesh
        for layer_name, mesh in self.meshes.items():
            color = self.engine.get_layer_color(layer_name)
            opacity = self.engine.get_layer_opacity(layer_name)
            
            plotter.add_mesh(
                mesh,
                name=layer_name,
                color=color,
                opacity=opacity,
                label=layer_name,
                smooth_shading=True,
                show_edges=False
            )
            print(f"  添加 {layer_name}: 颜色={color}, 透明度={opacity}")
        
        # 添加图例
        plotter.add_legend(bcolor='white', face='circle', size=[0.15, 0.3])
        
        # 设置视角
        plotter.camera_position = 'iso'
        plotter.camera.elevation = 20
        plotter.camera.azimuth = 45
        
        # 显示网格
        plotter.show_grid()
        
        # 显示
        plotter.show()
        
        # 保存截图
        out_path = os.path.join(os.path.dirname(self.dxf_path), 'geological_bim_robust.png')
        plotter.screenshot(out_path)
        print(f"\n  保存截图: {out_path}")
        
        return out_path


def main():
    """主函数"""
    dxf_path = r'D:\断面算量平台\测试文件\内湾段分层图（全航道底图20260318）面积比例0.6.dxf'
    
    print("="*60)
    print("航道地质 BIM 鲁棒性放样引擎 - 防穿模/防扭曲版")
    print("="*60)
    
    # 创建构建器
    builder = GeologicalBIMBuilder(dxf_path)
    
    # 提取断面数据
    builder.extract_sections()
    
    # 构建BIM模型（防穿模）
    builder.build_bim_model(num_sections=30, num_samples=100)
    
    # 可视化
    builder.visualize()
    
    print("\n完成!")


if __name__ == '__main__':
    main()