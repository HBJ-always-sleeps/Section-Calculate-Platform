# -*- coding: utf-8 -*-
"""检查填充实体所在的图层"""
import ezdxf

doc = ezdxf.readfile('测试文件/内湾段分层图（全航道）_RESULT_20260310_194057.dxf')
msp = doc.modelspace()

# 统计填充所在的图层
hatch_layers = {}
for e in msp.query('HATCH'):
    layer = e.dxf.layer
    if layer not in hatch_layers:
        hatch_layers[layer] = 0
    hatch_layers[layer] += 1

print('填充实体所在图层:')
for layer, count in sorted(hatch_layers.items()):
    print(f'  {layer}: {count}个')

# 统计MTEXT所在的图层
mtext_layers = {}
for e in msp.query('MTEXT'):
    layer = e.dxf.layer
    if layer not in mtext_layers:
        mtext_layers[layer] = 0
    mtext_layers[layer] += 1

print('\nMTEXT实体所在图层:')
for layer, count in sorted(mtext_layers.items()):
    print(f'  {layer}: {count}个')