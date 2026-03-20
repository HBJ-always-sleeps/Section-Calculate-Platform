# -*- coding: utf-8 -*-
"""测试分类算量功能 - 使用平台专用测试文件"""
import sys
import os
sys.path.insert(0, r"D:\tunnel_build\Code")

# 强制重新加载模块
for mod in ['engine_cad']:
    if mod in sys.modules:
        del sys.modules[mod]

from engine_cad import run_autoclassify
import pandas as pd

def test_autoclassify():
    """测试分类算量功能"""
    
    # 使用平台专用测试文件
    input_dxf = r"D:\tunnel_build\测试文件\平台专用测试\autoclassify_test.dxf"
    
    print("=" * 60)
    print("分类算量功能测试（桩号聚类版本）")
    print("=" * 60)
    
    # 检查本地文件是否存在
    if not os.path.exists(input_dxf):
        print(f"[ERROR] 找不到测试文件: {input_dxf}")
        return
    
    # 测试参数
    params = {
        'files': [input_dxf],
        '断面线图层': 'DMX',
        '桩号图层': '桩号',
        '面积比例系数': 1.0,  # 正常比例
        '合并断面线': True,
        '输出目录': r"D:\tunnel_build\测试文件\平台专用测试"
    }
    
    def log_func(msg):
        # 过滤掉emoji
        msg = msg.replace('✅', '[OK]').replace('❌', '[ERROR]').replace('⚠️', '[WARN]')
        msg = msg.replace('⏳', '[WAIT]').replace('✨', '[DONE]').replace('🔍', '[SCAN]')
        msg = msg.replace('🎨', '[PAINT]').replace('🚀', '[GO]').replace('📊', '[STATS]')
        print(msg)
    
    print(f"\n[INFO] 正在处理测试文件...")
    
    try:
        # 运行分类算量
        run_autoclassify(params, log_func)
        print("\n[DONE] 测试完成")
    except Exception as e:
        print(f"\n[ERROR] 测试失败: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    test_autoclassify()