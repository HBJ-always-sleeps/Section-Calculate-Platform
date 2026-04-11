# -*- coding: utf-8 -*-
"""
航道地质 BIM 鲁棒性放样引擎 (Robust Lofting Engine)
核心逻辑：
1. 锚点同步 (Anchor Sync): 强制所有断面从物理最左侧顶点开始编号，解决扭曲
2. 弧长重采样 (Arc-length Resampling): 确保顶点在逻辑上等距一一映射
3. 相对偏移插值 (Relative Offset): 防止不同地层之间发生纵向穿模
4. 重心追踪 (Centroid Tracking): 解决地层消失和穿模问题
5. Tapering退化: 地层平滑消失而非截断

作者: @黄秉俊
日期: 2026-03-30
"""

import numpy as np
import pyvista as pv
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass
from shapely.geometry import Polygon, LineString, Point
from shapely.ops import linemerge
import math


# ==================== 数据结构定义 ====================

@dataclass
class GeologicalBody:
    """单个地质体的元数据"""
    layer_name: str                      # 层名（如"6级砂"、"淤泥"）
    points: List[Tuple[float, float]]   # 局部坐标
    centroid: Tuple[float, float]        # 重心（用于相邻断面匹配）
    area: float                          # 面积
    is_closed: bool                      # 关键：地质层为True，DMX/超挖线为False

@dataclass
class SectionMetadata:
    """断面元数据（分类存储）"""
    station_name: str                    # 桩号名称
    station_value: float                 # 桩号数值（米）
    mileage: float                       # 里程（用于3D Y轴）
    surfaces: List[GeologicalBody]       # DMX, 超挖线 (视为只有顶/底的面，非闭合)
    volumes: List[GeologicalBody]        # 砂层、淤泥等填充层 (视为实心体，闭合)


# ==================== 核心放样引擎 ====================

class BIMLoftingEngine:
    """BIM鲁棒性放样引擎"""
    
    def __init__(self, num_samples: int = 100):
        """
        Args:
            num_samples: 重采样点数（统一所有断面的顶点数）
        """
        self.num_samples = num_samples
        self.meshes = {}  # 存储生成的网格
    
    def sync_anchor_points(self, coords: np.ndarray, is_closed: bool = True) -> np.ndarray:
        """
        核心对齐算法 V5 - 废弃min_x，改用"正上方"锚点
        
        核心改进：
        1. 废弃min_x/max_x对齐逻辑（防止宽度变化导致漂移）
        2. L1点定义为(0,0)，所有坐标已相对L1归一化
        3. 寻找"正上方"（角度≈90°）的点作为Index 0
        4. 防止"拧麻花"现象
        
        Args:
            coords: 原始坐标数组 [[x,z], [x,z], ...]（已归一化到L1为原点）
            is_closed: 是否为闭合多边形（地层闭合，DMX不闭合）
        
        Returns:
            对齐后的重采样坐标数组
        """
        coords = np.array(coords)
        
        # 对于非闭合线条（如DMX），直接重采样，不寻找起始点
        if not is_closed or len(coords) < 3:
            return self._resample_open_line(coords)
        
        # 1. 闭合多边形
        if not np.allclose(coords[0], coords[-1]):
            coords = np.vstack([coords, coords[0]])
        
        # 2. 弧长重采样，确保点数一致
        diff = np.diff(coords, axis=0)
        dist = np.sqrt((diff**2).sum(axis=1))
        u = np.concatenate(([0], np.cumsum(dist)))
        
        if u[-1] == 0:
            return coords[:self.num_samples] if len(coords) >= self.num_samples else coords
        
        # 线性插值重采样
        try:
            target_u = np.linspace(0, u[-1], self.num_samples)
            resampled = np.zeros((self.num_samples, 2))
            for k in range(len(u) - 1):
                mask = (target_u >= u[k]) & (target_u <= u[k+1])
                if np.any(mask):
                    t = (target_u[mask] - u[k]) / (u[k+1] - u[k] + 1e-10)
                    resampled[mask] = coords[k] + t[:, None] * (coords[k+1] - coords[k])
            if target_u[-1] > u[-1]:
                resampled[-1] = coords[-1]
        except Exception:
            resampled = coords[:self.num_samples] if len(coords) >= self.num_samples else np.vstack([coords, coords[-1]] * (self.num_samples - len(coords)))
        
        # 3. 【核心修复】废弃min_x，改用"正上方"锚点
        # L1点是(0,0)，我们寻找相对于(0,0)角度最接近90°（正上方）的点
        # 这样无论断面多宽，起始点永远在L1点的正上方
        
        # 计算每个点相对于原点(0,0)的角度
        dx = resampled[:, 0] - 0  # X坐标（已归一化，L1在X=0）
        dy = resampled[:, 1] - 0  # Z坐标（已归一化，L1在Z=0）
        angles = np.arctan2(dy, dx)  # 角度（弧度）
        
        # 寻找角度最接近90°（π/2）的点
        # 这确保起始点永远在"正上方"，防止拧麻花
        target_angle = np.pi / 2  # 90°
        angle_diffs = np.abs(angles - target_angle)
        start_idx = np.argmin(angle_diffs)
        
        # 重新排序顶点（不包含闭合点）
        aligned = np.roll(resampled[:-1], -start_idx, axis=0)
        
        return aligned
    
    def _resample_open_line(self, coords: np.ndarray) -> np.ndarray:
        """重采样开放线条（如DMX）- 不寻找起始点"""
        coords = np.array(coords)
        
        if len(coords) < 2:
            return coords
        
        # 弧长重采样
        diff = np.diff(coords, axis=0)
        dist = np.sqrt((diff**2).sum(axis=1))
        u = np.concatenate(([0], np.cumsum(dist)))
        
        if u[-1] == 0:
            return coords[:self.num_samples] if len(coords) >= self.num_samples else coords
        
        try:
            target_u = np.linspace(0, u[-1], self.num_samples)
            resampled = np.zeros((self.num_samples, 2))
            for k in range(len(u) - 1):
                mask = (target_u >= u[k]) & (target_u <= u[k+1])
                if np.any(mask):
                    t = (target_u[mask] - u[k]) / (u[k+1] - u[k] + 1e-10)
                    resampled[mask] = coords[k] + t[:, None] * (coords[k+1] - coords[k])
            if target_u[-1] > u[-1]:
                resampled[-1] = coords[-1]
        except Exception:
            resampled = coords[:self.num_samples] if len(coords) >= self.num_samples else coords
        
        return resampled
    
    def create_ribbon_mesh(self, mileage_list: List[float], coords_list: List[np.ndarray], 
                           ribbon_width: float = 2.0) -> pv.PolyData:
        """
        创建带状面（Ribbon）- 用于DMX/超挖线等开放线条
        不会形成闭合回路，避免"讨厌的顶面"
        
        Args:
            mileage_list: 里程列表 [Y1, Y2, ...]
            coords_list: 坐标列表 [coords1, coords2, ...]
            ribbon_width: 带状面的宽度（Z方向偏移）
        
        Returns:
            PyVista PolyData网格
        """
        if len(mileage_list) < 2:
            return None
        
        sections_3d = []
        for mileage, coords in zip(mileage_list, coords_list):
            coords = np.array(coords)
            
            # 对于开放线条，不需要闭合处理
            # 直接弧长重采样
            if len(coords) >= 2:
                diff = np.diff(coords, axis=0)
                dist = np.sqrt((diff**2).sum(axis=1))
                u = np.concatenate(([0], np.cumsum(dist)))
                
                if u[-1] > 0:
                    # 使用纯numpy插值（避免scipy崩溃）
                    try:
                        target_u = np.linspace(0, u[-1], self.num_samples)
                        resampled = np.zeros((self.num_samples, 2))
                        for k in range(len(u) - 1):
                            mask = (target_u >= u[k]) & (target_u <= u[k+1])
                            if np.any(mask):
                                t = (target_u[mask] - u[k]) / (u[k+1] - u[k] + 1e-10)
                                resampled[mask] = coords[k] + t[:, None] * (coords[k+1] - coords[k])
                        if target_u[-1] > u[-1]:
                            resampled[-1] = coords[-1]
                    except Exception:
                        resampled = coords[:self.num_samples] if len(coords) >= self.num_samples else coords
                else:
                    resampled = coords
            else:
                resampled = coords
            
            # 映射到3D (X:宽度, Y:里程, Z:高程)
            vpts = np.zeros((len(resampled), 3))
            vpts[:, 0] = resampled[:, 0]    # X
            vpts[:, 1] = mileage             # Y
            vpts[:, 2] = resampled[:, 1]     # Z
            sections_3d.append(vpts)
        
        # 构建顶点和面索引（只连接相邻断面，不封顶）
        all_points = np.vstack(sections_3d)
        num_sects = len(sections_3d)
        num_pts = len(sections_3d[0])
        
        faces = []
        for i in range(num_sects - 1):
            for j in range(num_pts - 1):
                # 定义四个顶点
                p1 = i * num_pts + j
                p2 = p1 + 1
                p3 = (i + 1) * num_pts + j + 1
                p4 = (i + 1) * num_pts + j
                
                # 两个三角形组成一个四边形面
                faces.append([3, p1, p2, p3])
                faces.append([3, p1, p3, p4])
        
        return pv.PolyData(all_points, faces)
    
    def create_volume_mesh(self, mileage_list: List[float], coords_list: List[np.ndarray],
                           taper_on_missing: bool = True) -> pv.PolyData:
        """
        创建体积网格（Volume）- 用于地质填充等闭合多边形
        使用锚点同步确保拓扑一致性
        
        Args:
            mileage_list: 里程列表 [Y1, Y2, ...]
            coords_list: 坐标列表 [coords1, coords2, ...]
            taper_on_missing: 是否在缺失断面处平滑退化
        
        Returns:
            PyVista PolyData网格
        """
        if len(mileage_list) < 2:
            return None
        
        # 执行锚点同步对齐
        aligned_coords_list = []
        for coords in coords_list:
            aligned = self.sync_anchor_points(coords)
            aligned_coords_list.append(aligned)
        
        # 映射到3D
        sections_3d = []
        for mileage, coords in zip(mileage_list, aligned_coords_list):
            vpts = np.zeros((len(coords), 3))
            vpts[:, 0] = coords[:, 0]    # X
            vpts[:, 1] = mileage          # Y
            vpts[:, 2] = coords[:, 1]     # Z
            sections_3d.append(vpts)
        
        # 构建顶点和面索引
        all_points = np.vstack(sections_3d)
        num_sects = len(sections_3d)
        num_pts = len(sections_3d[0])
        
        faces = []
        for i in range(num_sects - 1):
            for j in range(num_pts):
                # 处理闭合逻辑（首尾相连）
                next_j = (j + 1) % num_pts
                
                p1 = i * num_pts + j
                p2 = i * num_pts + next_j
                p3 = (i + 1) * num_pts + next_j
                p4 = (i + 1) * num_pts + j
                
                # 两个三角形组成一个四边形面
                faces.append([3, p1, p2, p3])
                faces.append([3, p1, p3, p4])
        
        return pv.PolyData(all_points, faces)
    
    def match_by_centroid(self, body_a: GeologicalBody, bodies_b: List[GeologicalBody],
                          max_dist: float = 100.0) -> Optional[GeologicalBody]:
        """
        重心追踪匹配：在下一断面寻找同层且重心最近的地质体
        防止跨桩号连接导致穿模
        
        Args:
            body_a: 当前断面的地质体
            bodies_b: 下一断面的地质体列表
            max_dist: 最大重心距离阈值
        
        Returns:
            匹配的地质体，如果没有则返回None
        """
        best_match = None
        best_dist = float('inf')
        
        for body_b in bodies_b:
            # 1. 同层名匹配
            if body_b.layer_name != body_a.layer_name:
                continue
            
            # 2. 重心距离计算
            dist = math.sqrt((body_b.centroid[0] - body_a.centroid[0])**2 +
                            (body_b.centroid[1] - body_a.centroid[1])**2)
            
            if dist < best_dist:
                best_dist = dist
                best_match = body_b
        
        # 3. 阈值检查（防止跨越连接）
        if best_match and best_dist < max_dist:
            return best_match
        
        return None
    
    def create_taper_point(self, body: GeologicalBody, dmx_z: float) -> np.ndarray:
        """
        创建退化点（Tapering）：地层消失时平滑收缩
        
        Args:
            body: 消失的地质体
            dmx_z: 设计底线高程
        
        Returns:
            退化点坐标（所有点重合在重心垂直投影处）
        """
        # 使用重心位置，但高程取设计底线
        taper_x = body.centroid[0]
        taper_z = dmx_z
        
        # 创建一个"零厚度"多边形（所有点重合）
        taper_coords = np.array([[taper_x, taper_z]] * self.num_samples)
        
        return taper_coords


# ==================== 地层匹配与构建器 ====================

class LayerMatcher:
    """地层匹配器 - 使用重心追踪算法 V3"""
    
    def __init__(self, sections: List[SectionMetadata], max_centroid_dist: float = 100.0, num_samples: int = 100):
        self.sections = sections
        self.max_centroid_dist = max_centroid_dist
        self.num_samples = num_samples  # 添加采样点数属性
    
    def build_layer_chains(self) -> Dict[str, List[GeologicalBody]]:
        """
        构建地层链（旧版）：按重心追踪匹配相邻断面的地质体
        
        Returns:
            {layer_name: [body1, body2, ...]} 每个地层是一条连续链
        """
        chains = {}
        
        # 按桩号排序
        sorted_sections = sorted(self.sections, key=lambda s: s.station_value, reverse=True)
        
        for layer_name in self._get_all_layer_names():
            chain = []
            
            for i, section in enumerate(sorted_sections):
                # 在当前断面找该层
                matching_bodies = [b for b in section.volumes if b.layer_name == layer_name]
                
                if not matching_bodies:
                    # 该层在此断面消失
                    # 使用退化逻辑：向上一断面的重心位置收缩
                    if chain:
                        last_body = chain[-1]
                        taper = self._create_taper(last_body, section)
                        if taper:
                            chain.append(taper)
                    continue
                
                # 如果链为空，直接添加第一个
                if not chain:
                    chain.append(matching_bodies[0])
                    continue
                
                # 使用重心追踪匹配
                last_body = chain[-1]
                match = self._find_best_match(last_body, matching_bodies)
                
                if match:
                    chain.append(match)
                else:
                    # 没有匹配，创建退化点
                    taper = self._create_taper(last_body, section)
                    if taper:
                        chain.append(taper)
            
            if chain:
                chains[layer_name] = chain
        
        return chains
    
    def build_layer_chains_v3(self) -> Dict[str, List[Tuple[float, np.ndarray]]]:
        """
        构建地层链 V3 - 全里程扫描 + Single Mesh
        
        核心改进：
        1. 扫描整个项目的所有里程（不仅是存在该地层的里程）
        2. 在缺失里程处创建"零厚度"退化断面（坍缩到DMX）
        3. 确保每个地层是Single Mesh（一个完整的PolyData）
        
        Returns:
            {layer_name: [(mileage, coords), ...]} 每个地层是里程-坐标对的列表
        """
        chains = {}
        
        # 【关键】获取全局里程列表（所有断面的桩号）
        sorted_sections = sorted(self.sections, key=lambda s: s.station_value, reverse=True)
        global_mileages = [s.mileage for s in sorted_sections]
        
        # 构建DMX字典（用于退化时坍缩）
        dmx_dict = {}
        for section in sorted_sections:
            for surface in section.surfaces:
                if 'DMX' in surface.layer_name:
                    dmx_dict[section.mileage] = np.array(surface.points)
                    break
        
        for layer_name in self._get_all_layer_names():
            chain = []
            is_started = False  # 标记该地层是否已开始出现
            taper_count = 0     # 连续退化计数（防止无限延伸）
            last_valid_coords = None  # 上一个有效断面的坐标
            
            for i, section in enumerate(sorted_sections):
                mileage = section.mileage
                
                # 在当前断面找该层
                matching_bodies = [b for b in section.volumes if b.layer_name == layer_name]
                
                if matching_bodies:
                    # 该层存在，正常添加
                    body = matching_bodies[0]
                    coords = np.array(body.points)
                    chain.append((mileage, coords))
                    is_started = True
                    taper_count = 0
                    last_valid_coords = coords
                else:
                    # 该层在此断面缺失
                    if is_started and taper_count < 3:  # 最多连续退化3个断面
                        # 创建退化断面（坍缩到DMX）
                        dmx_coords = dmx_dict.get(mileage)
                        if dmx_coords is not None:
                            # 找DMX中心点作为坍缩位置
                            dist_to_center = np.abs(dmx_coords[:, 0])
                            center_idx = np.argmin(dist_to_center)
                            taper_x = dmx_coords[center_idx, 0]
                            taper_z = dmx_coords[center_idx, 1]
                        elif last_valid_coords is not None:
                            # 使用上一个有效断面的重心
                            taper_x = np.mean(last_valid_coords[:, 0])
                            taper_z = np.mean(last_valid_coords[:, 1])
                        else:
                            continue
                        
                        # 创建"零厚度"退化断面（num_samples个点重合）
                        taper_coords = np.array([[taper_x, taper_z]] * self.num_samples)
                        chain.append((mileage, taper_coords))
                        taper_count += 1
            
            if chain and len(chain) >= 2:
                chains[layer_name] = chain
        
        return chains
    
    def _get_all_layer_names(self) -> List[str]:
        """获取所有地层名称"""
        names = set()
        for section in self.sections:
            for body in section.volumes:
                names.add(body.layer_name)
        return sorted(names)
    
    def _find_best_match(self, body_a: GeologicalBody, candidates: List[GeologicalBody]) -> Optional[GeologicalBody]:
        """重心追踪匹配"""
        best = None
        best_dist = float('inf')
        
        for body_b in candidates:
            dist = math.sqrt((body_b.centroid[0] - body_a.centroid[0])**2 +
                            (body_b.centroid[1] - body_a.centroid[1])**2)
            
            if dist < best_dist:
                best_dist = dist
                best = body_b
        
        return best if best_dist < self.max_centroid_dist else None
    
    def _create_taper(self, prev_body: GeologicalBody, section: SectionMetadata, 
                      dmx_coords: Optional[np.ndarray] = None) -> Optional[GeologicalBody]:
        """
        创建退化地质体 V3 - 坍缩到DMX设计线
        
        核心改进：地层消失时，将所有采样点坍缩到当前断面的DMX线位置
        而非上一断面的重心，确保拓扑一致性
        """
        # 找当前断面的DMX线作为坍缩基准
        dmx_surface = None
        for surface in section.surfaces:
            if 'DMX' in surface.layer_name or '设计' in surface.layer_name:
                dmx_surface = surface
                break
        
        if dmx_surface:
            # 坍缩到DMX线的平均位置（中心线锚点）
            dmx_pts = np.array(dmx_surface.points)
            # 找DMX线的中心点（X接近0）
            dist_to_center = np.abs(dmx_pts[:, 0])
            center_idx = np.argmin(dist_to_center)
            taper_x = dmx_pts[center_idx, 0]  # 使用DMX中心点X
            taper_z = dmx_pts[center_idx, 1]  # 使用DMX中心点Z
        elif dmx_coords is not None:
            # 使用传入的DMX坐标
            dist_to_center = np.abs(dmx_coords[:, 0])
            center_idx = np.argmin(dist_to_center)
            taper_x = dmx_coords[center_idx, 0]
            taper_z = dmx_coords[center_idx, 1]
        else:
            # 兜底：使用上一断面的重心
            taper_x = prev_body.centroid[0]
            taper_z = prev_body.centroid[1]
        
        # 【关键】创建num_samples个退化点（保持顶点数一致）
        taper_points = [(taper_x, taper_z)] * self.num_samples
        
        return GeologicalBody(
            layer_name=prev_body.layer_name,
            points=taper_points,
            centroid=(taper_x, taper_z),  # 退化后的重心
            area=0.0,  # 零面积（已坍缩成点）
            is_closed=True
        )


# ==================== 颜色映射 ====================

LAYER_COLORS = {
    '砂': '#f1c40f',       # 金色
    '淤泥': '#7f8c8d',     # 灰色
    '黏土': '#A52A2A',     # 棕色
    '碎石': '#CD853F',     # 秘鲁色
    '填土': '#8B4513',     # 马鞍棕
    'DMX': '#2ecc71',      # 绿色（设计线）
    '设计': '#2ecc71',     # 绿色
    '超挖': '#e67e22',     # 橙红
    'nonem': '#C0C0C0',    # 银色
    'default': '#ecf0f1'   # 默认白色
}

def get_layer_color(layer_name: str) -> str:
    """获取地层颜色"""
    for key, color in LAYER_COLORS.items():
        if key.lower() in layer_name.lower():
            return color
    return LAYER_COLORS['default']

def get_layer_opacity(layer_name: str) -> float:
    """获取地层透明度"""
    if '超挖' in layer_name:
        return 0.4
    elif 'DMX' in layer_name or '设计' in layer_name:
        return 1.0
    else:
        return 0.8