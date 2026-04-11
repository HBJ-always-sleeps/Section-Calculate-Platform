# -*- coding: utf-8 -*-
# scale_detector_working.py - 缩放比例检测器（working版本）
"""
从 engine_cad_working_v3.py 提取的缩放比例检测器
包含自动检测DXF文件的缩放比例功能

代码位置: D:\断面算量平台\Code\scale_detector_working.py
"""

import re
from shapely.geometry import LineString

class ScaleDetector:
    """缩放比例检测器"""
    
    STATION_PATTERN = re.compile(r'(\d+)\+(\d+)')
    
    def __init__(self, msp):
        self.msp = msp
    
    def detect_scale(self):
        """检测缩放比例"""
        # 获取DMX图层断面线
        dmx_lines = self._get_dmx_lines()
        if not dmx_lines:
            return 1.0, "未找到DMX图层断面线"
        
        # 计算平均长度和间距
        lengths = [l.length for l in dmx_lines]
        avg_length = sum(lengths) / len(lengths)
        
        # 获取断面中心点，计算间距
        centers = []
        for line in dmx_lines:
            mid = line.centroid
            centers.append((mid.x, mid.y))
        
        # 按Y排序计算间距
        centers.sort(key=lambda c: c[1], reverse=True)
        gaps = []
        for i in range(len(centers) - 1):
            gap = abs(centers[i][1] - centers[i+1][1])
            if gap > 1:  # 过滤异常值
                gaps.append(gap)
        
        avg_gap = sum(gaps) / len(gaps) if gaps else 0
        
        # 计算缩放比例
        ref_length = 200.0  # 参考断面线长度
        ref_gap = 35.0      # 参考断面间距
        
        scale_by_length = avg_length / ref_length if avg_length > 0 else 1.0
        scale_by_gap = avg_gap / ref_gap if avg_gap > 0 else 1.0
        
        # 取平均值
        detected_scale = (scale_by_length + scale_by_gap) / 2
        
        msg = f"检测到缩放比例: {detected_scale:.4f} (长度比:{scale_by_length:.4f}, 间距比:{scale_by_gap:.4f})"
        
        return detected_scale, msg
    
    def _get_dmx_lines(self):
        """获取DMX图层的断面线"""
        lines = []
        try:
            for e in self.msp.query('LWPOLYLINE[layer=="DMX"]'):
                try:
                    pts = [(p[0], p[1]) for p in e.get_points()]
                    if len(pts) > 1:
                        lines.append(LineString(pts))
                except: pass
        except: pass
        return lines
    
    def get_stations_info(self):
        """获取桩号信息"""
        stations = []
        for e in self.msp.query('TEXT MTEXT'):
            try:
                txt = e.plain_text() if e.dxftype() == 'MTEXT' else e.dxf.text
                match = self.STATION_PATTERN.search(txt.upper())
                if match:
                    x = e.dxf.insert.x if e.dxftype() == 'TEXT' else e.dxf.insert.x
                    y = e.dxf.insert.y if e.dxftype() == 'TEXT' else e.dxf.insert.y
                    
                    sid = match.group(1) + '+' + match.group(2)
                    value = int(match.group(1)) * 1000 + int(match.group(2))
                    
                    stations.append({
                        'text': sid,
                        'value': value,
                        'x': x,
                        'y': y
                    })
            except: pass
        
        return sorted(stations, key=lambda s: s['y'], reverse=True)