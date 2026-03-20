# -*- coding: utf-8 -*-
"""后台运行全航道测试"""
import sys
import os
import time
sys.path.insert(0, 'Code')

from engine_cad import run_autoclassify

test_file = 'D:/tunnel_build/测试文件/内湾段分层图（全航道）.bak'
print(f'文件存在: {os.path.exists(test_file)}')
print(f'文件大小: {os.path.getsize(test_file) / 1024 / 1024:.1f} MB')

params = {
    'files': [test_file],
    '断面线图层': 'DMX',
    '桩号图层': '0-桩号',
    '合并断面线': True
}

def LOG(msg):
    print(f'[{time.strftime("%H:%M:%S")}] {msg}')
    sys.stdout.flush()

print('开始执行 autoclassify...')
start_time = time.time()
try:
    run_autoclassify(params, LOG)
    elapsed = time.time() - start_time
    print(f'执行完毕，耗时 {elapsed:.1f} 秒')
except Exception as e:
    print(f'错误: {e}')
    import traceback
    traceback.print_exc()