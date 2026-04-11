# -*- coding: utf-8 -*-
# virtual_box_builder_working.py - 虚拟断面框构建器（working版本）
"""
从 engine_cad_working_v3.py 提取的虚拟断面框构建器
包含根据L1脊梁线构建虚拟断面框功能

代码位置: D:\断面算量平台\Code\virtual_box_builder_working.py
"""

from shapely.geometry import box, Polygon, LineString

class VirtualBoxBuilder:
    """虚拟断面框构建器"""
    
    def __init__(self, msp):
        self.msp = msp
    
    def build_from_spine(self, spine_data, margin=10):
        """根据脊梁线数据构建虚拟断面框
        
        Args:
            spine_data: L1脊梁线数据，包含x_center, y_center, center_height等
            margin: 边距
        
        Returns:
            虚拟断面框列表
        """
        boxes = []
        
        if not spine_data or not spine_data.get('spines'):
            return boxes
        
        for spine in spine_data['spines']:
            # 获取脊梁线中心点
            x_center = spine.get('x_center', 0)
            y_center = spine.get('y_center', 0)
            
            # 获取断面宽度（顶边宽度）和高度（垂直线高度）
            width = spine.get('top_width', 200) or 200  # 默认宽度200
            height = spine.get('center_height', 100) or 100  # 默认高度100
            
            # 构建虚拟框
            x_min = x_center - width / 2 - margin
            x_max = x_center + width / 2 + margin
            y_min = y_center - height / 2 - margin
            y_max = y_center + height / 2 + margin
            
            box_geom = box(x_min, y_min, x_max, y_max)
            
            boxes.append({
                'geometry': box_geom,
                'x_center': x_center,
                'y_center': y_center,
                'width': width + 2 * margin,
                'height': height + 2 * margin,
                'section_index': spine.get('section_index', 0)
            })
        
        return boxes
    
    def build_from_dmx(self, margin=20):
        """根据DMX断面线构建虚拟断面框"""
        boxes = []
        
        # 获取DMX图层断面线
        lines = []
        for e in self.msp.query('LWPOLYLINE[layer=="DMX"]'):
            try:
                pts = [(p[0], p[1]) for p in e.get_points()]
                if len(pts) > 1:
                    lines.append(LineString(pts))
            except: pass
        
        for line in lines:
            # 计算断面线边界
            bounds = line.bounds  # (minx, miny, maxx, maxy)
            
            # 添加边距
            x_min = bounds[0] - margin
            x_max = bounds[2] + margin
            y_min = bounds[1] - margin
            y_max = bounds[3] + margin
            
            box_geom = box(x_min, y_min, x_max, y_max)
            
            boxes.append({
                'geometry': box_geom,
                'x_center': (bounds[0] + bounds[2]) / 2,
                'y_center': (bounds[1] + bounds[3]) / 2,
                'width': bounds[2] - bounds[0] + 2 * margin,
                'height': bounds[3] - bounds[1] + 2 * margin
            })
        
        return boxes