# -*- coding: utf-8 -*-
# layer_extractor_working.py - 图层提取工具集（working版本）
"""
从 engine_cad_working_v3.py 提取的图层提取工具类
包含按名称模式提取图层、获取多段线等功能

代码位置: D:\断面算量平台\Code\layer_extractor_working.py
"""

import re
from shapely.geometry import LineString

class LayerExtractor:
    """图层提取工具集"""
    
    @staticmethod
    def get_layers_by_pattern(doc, pattern):
        """按正则表达式提取图层"""
        return [l for l in doc.layers if re.search(pattern, l.dxf.name, re.I)]
    
    @staticmethod
    def get_polylines(msp, layer_name):
        """获取指定图层的所有多段线"""
        from shapely.geometry import LineString
        result = []
        for e in msp.query(f'LWPOLYLINE[layer=="{layer_name}"]'):
            try:
                pts = [(p[0], p[1]) for p in e.get_points()]
                if len(pts) > 1:
                    result.append(LineString(pts))
            except: pass
        return result