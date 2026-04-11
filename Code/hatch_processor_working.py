# -*- coding: utf-8 -*-
# hatch_processor_working.py - 填充处理器（working版本）
"""
从 engine_cad_working_v3.py 提取的填充处理器
包含填充面积计算、图层提取等功能

代码位置: D:\断面算量平台\Code\hatch_processor_working.py
"""

import re

class HatchProcessor:
    """填充处理器"""
    
    # 地层颜色映射
    STRATA_COLORS = {
        '1级淤泥': 11, '1级淤泥质土': 12, '2级淤泥': 31, '3级淤泥': 32,
        '3级粘土': 33, '4级粘土': 41, '4级淤泥': 42, '5级粘土': 51,
        '6级砂': 61, '6级碎石': 62, '7级砂': 71, '8级砂': 81, '9级碎石': 91,
    }
    
    def __init__(self, msp):
        self.msp = msp
    
    def get_hatch_areas(self):
        """获取所有填充区域及其面积"""
        hatches = []
        for e in self.msp.query('HATCH'):
            try:
                area = self._calculate_hatch_area(e)
                layer = e.dxf.layer
                color = e.dxf.color if hasattr(e.dxf, 'color') else 0
                
                hatches.append({
                    'entity': e,
                    'area': area,
                    'layer': layer,
                    'color': color
                })
            except: pass
        return hatches
    
    def _calculate_hatch_area(self, hatch):
        """计算填充区域面积"""
        try:
            # 尝试获取边界路径
            total_area = 0
            for path in hatch.paths:
                if hasattr(path, 'edges'):
                    # 多边形路径
                    pts = []
                    for edge in path.edges:
                        if hasattr(edge, 'vertices'):
                            pts.extend(edge.vertices)
                    if len(pts) >= 3:
                        # 使用Shapely计算面积
                        from shapely.geometry import Polygon
                        try:
                            poly = Polygon(pts)
                            total_area += poly.area
                        except: pass
            return total_area
        except:
            return 0
    
    def get_hatches_by_color(self, color):
        """按颜色获取填充"""
        return [h for h in self.get_hatch_areas() if h['color'] == color]
    
    def get_hatches_by_layer(self, layer_pattern):
        """按图层模式获取填充"""
        import re
        return [h for h in self.get_hatch_areas() 
                if re.search(layer_pattern, h['layer'], re.I)]