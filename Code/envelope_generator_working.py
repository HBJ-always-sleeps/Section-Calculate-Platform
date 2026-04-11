# -*- coding: utf-8 -*-
# envelope_generator_working.py - 包络线生成器（working版本）
"""
从 engine_cad_working_v3.py 提取的包络线生成器
包含生成断面包络线功能

代码位置: D:\断面算量平台\Code\envelope_generator_working.py
"""

from shapely.geometry import LineString, MultiLineString
from shapely.ops import unary_union, linemerge

class EnvelopeGenerator:
    """包络线生成器"""
    
    def __init__(self, msp):
        self.msp = msp
    
    def generate_envelope(self, lines, tolerance=0.5):
        """生成包络线"""
        if not lines:
            return None
        
        # 合并所有线
        merged = linemerge(MultiLineString(lines))
        
        if merged.is_empty:
            return None
        
        # 创建缓冲区并提取边界
        buffered = merged.buffer(tolerance)
        boundary = buffered.boundary
        
        return boundary
    
    def get_section_envelope(self, section_line, top_line, bottom_line):
        """获取断面包络"""
        lines = []
        if section_line:
            lines.append(section_line)
        if top_line:
            lines.append(top_line)
        if bottom_line:
            lines.append(bottom_line)
        
        return self.generate_envelope(lines)