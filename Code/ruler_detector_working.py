# -*- coding: utf-8 -*-
# ruler_detector_working.py - 标尺检测器（working版本）
"""
从 engine_cad_working_v3.py 提取的标尺检测器
包含检测标尺图层、获取标尺位置等功能

代码位置: D:\断面算量平台\Code\ruler_detector_working.py
"""

class RulerDetector:
    """标尺检测器"""
    
    def __init__(self, msp):
        self.msp = msp
    
    def get_ruler_positions(self):
        """获取标尺图层的Y位置"""
        ruler_y = []
        try:
            for e in self.msp.query('*[layer=="标尺"]'):
                if e.dxftype() == 'LINE':
                    y = (e.dxf.start.y + e.dxf.end.y) / 2
                    ruler_y.append(y)
                elif e.dxftype() in ('LWPOLYLINE', 'POLYLINE'):
                    pts = [(p[0], p[1]) for p in e.get_points()]
                    if pts:
                        y = sum(p[1] for p in pts) / len(pts)
                        ruler_y.append(y)
                elif e.dxftype() == 'TEXT':
                    ruler_y.append(e.dxf.insert.y)
        except:
            pass
        
        return sorted(set(ruler_y), reverse=True) if ruler_y else None
    
    def get_ruler_scale(self):
        """获取标尺的刻度单位"""
        # 查找标尺文字，解析刻度
        texts = []
        for e in self.msp.query('TEXT[layer=="标尺"]'):
            try:
                txt = e.dxf.text
                if txt and any(c.isdigit() for c in txt):
                    texts.append({
                        'text': txt,
                        'y': e.dxf.insert.y
                    })
            except: pass
        
        # 分析刻度间距
        if len(texts) >= 2:
            texts.sort(key=lambda t: t['y'], reverse=True)
            gaps = []
            for i in range(len(texts) - 1):
                gap = abs(texts[i]['y'] - texts[i+1]['y'])
                if gap > 1:
                    gaps.append(gap)
            
            if gaps:
                avg_gap = sum(gaps) / len(gaps)
                return avg_gap
        
        return None