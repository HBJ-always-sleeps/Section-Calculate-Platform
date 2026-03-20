# -*- coding: utf-8 -*-
"""测试按地层+类型分图层功能"""
import sys
import os
sys.path.insert(0, 'Code')

from engine_cad import run_autoclassify

test_file = 'D:/tunnel_build/测试文件/内湾段分层图（全航道）.bak'
print(f'文件存在: {os.path.exists(test_file)}')

params = {
    'files': [test_file],
    '断面线图层': 'DMX',
    '桩号图层': '0-桩号',
    '合并断面线': True
}

def LOG(msg):
    print(msg)

print('开始执行 autoclassify...')
run_autoclassify(params, LOG)
print('执行完毕')