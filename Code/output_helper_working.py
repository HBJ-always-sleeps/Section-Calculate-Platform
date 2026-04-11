# -*- coding: utf-8 -*-
# output_helper_working.py - 文件输出工具集（working版本）
"""
从 engine_cad_working_v3.py 提取的文件输出工具类
包含保存DXF、导出图层等功能

代码位置: D:\断面算量平台\Code\output_helper_working.py
"""

import os
from datetime import datetime

class OutputHelper:
    """文件输出工具集"""
    
    @staticmethod
    def save_with_timestamp(doc, base_path, suffix="output"):
        """带时间戳保存文件"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        dir_path = os.path.dirname(base_path)
        name = os.path.splitext(os.path.basename(base_path))[0]
        ext = os.path.splitext(base_path)[1] or '.dxf'
        
        output_path = os.path.join(dir_path, f"{name}_{suffix}_{timestamp}{ext}")
        doc.saveas(output_path)
        return output_path
    
    @staticmethod
    def save_to_layer(doc, entities, layer_name):
        """将实体保存到指定图层"""
        # 确保图层存在
        if layer_name not in doc.layers:
            doc.layers.new(name=layer_name)
        
        # 设置实体图层
        for e in entities:
            e.dxf.layer = layer_name
    
    @staticmethod
    def get_output_path(input_path, suffix="output"):
        """生成输出文件路径"""
        dir_path = os.path.dirname(input_path)
        name = os.path.splitext(os.path.basename(input_path))[0]
        ext = os.path.splitext(input_path)[1] or '.dxf'
        
        return os.path.join(dir_path, f"{name}_{suffix}{ext}")