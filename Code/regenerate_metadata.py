# -*- coding: utf-8 -*-
"""重新生成带L1基准点的元数据文件"""

import sys
import os

os.chdir(r'D:\断面算量平台')

# 使用 os.path.join 构建路径
dxf_file = os.path.join(r'D:\断面算量平台', '测试文件', '内湾段分层图（全航道底图20260331）2018面积比例0.6.dxf')

print(f"DXF文件路径: {dxf_file}")
print(f"文件存在: {os.path.exists(dxf_file)}")

# 导入 BIMModelBuilder
from Code.bim_model_builder import BIMModelBuilder

# 构建模型
builder = BIMModelBuilder(dxf_file)
metadata = builder.build_model()

# 保存元数据
output_path = os.path.join(r'D:\断面算量平台', '测试文件', '内湾段分层图（全航道底图20260331）2018面积比例0.6_bim_metadata_with_l1.json')
builder.save_metadata(output_path)

print(f"\n完成! 输出文件: {output_path}")

# 检查 L1 基准点数量
sections_with_l1 = [s for s in metadata.sections if s.l1_ref_point]
print(f"断面总数: {len(metadata.sections)}")
print(f"有L1基准点的断面: {len(sections_with_l1)}")