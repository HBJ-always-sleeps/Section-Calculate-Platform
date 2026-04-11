# -*- coding: utf-8 -*-
# line_utils_working.py - 线段处理工具集（working版本）
"""
从 engine_cad_working_v3.py 提取的线段处理工具类
包含Y坐标获取、线段延长、交点计算等功能

代码位置: D:\断面算量平台\Code\line_utils_working.py
"""

from shapely.geometry import Point

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
        from shapely.geometry import LineString
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