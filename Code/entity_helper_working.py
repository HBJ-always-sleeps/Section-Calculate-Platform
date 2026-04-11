# -*- coding: utf-8 -*-
# entity_helper_working.py - 实体处理工具集（working版本）
"""
从 engine_cad_working_v3.py 提取的实体处理工具类
包含线段转LineString、文本点获取、文本内容提取等功能

代码位置: D:\断面算量平台\Code\entity_helper_working.py
"""

from shapely.geometry import LineString

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