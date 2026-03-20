# -*- coding: utf-8 -*-
"""检查生成的图层"""
import ezdxf

doc = ezdxf.readfile('测试文件/内湾段部分_RESULT_20260316_120518.dxf')
layers = [l.dxf.name for l in doc.layers]
print('所有图层:')
for l in sorted(layers):
    print(f'  {l}')

# 检查新增的图层
new_layers = [l for l in layers if '设计' in l or '超挖' in l]
print(f'\n按地层+类型分层的图层 ({len(new_layers)}个):')
for l in sorted(new_layers):
    print(f'  {l}')