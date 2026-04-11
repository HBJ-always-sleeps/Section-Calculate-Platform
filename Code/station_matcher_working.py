# -*- coding: utf-8 -*-
# station_matcher_working.py - 桩号匹配工具集（working版本）
"""
从 engine_cad_working_v3.py 提取的桩号匹配工具类
包含桩号解析、桩号匹配等功能

代码位置: D:\断面算量平台\Code\station_matcher_working.py
"""

import re

class StationMatcher:
    """桩号匹配工具集"""
    
    STATION_PATTERN = re.compile(r'(\d+)\+(\d+)')
    
    @staticmethod
    def parse_station(text):
        """解析桩号文本，返回数值"""
        match = StationMatcher.STATION_PATTERN.search(text.upper())
        if match:
            return int(match.group(1)) * 1000 + int(match.group(2))
        return None
    
    @staticmethod
    def format_station(value):
        """将数值格式化为桩号文本"""
        km = int(value // 1000)
        m = int(value % 1000)
        return f"{km}+{m:03d}"
    
    @staticmethod
    def find_nearest_station(stations, target_value, max_diff=100):
        """在桩号列表中找到最接近目标值的桩号"""
        nearest = None
        min_diff = float('inf')
        
        for station in stations:
            diff = abs(station.get('value', 0) - target_value)
            if diff < min_diff:
                min_diff = diff
                nearest = station
        
        if min_diff <= max_diff:
            return nearest
        return None