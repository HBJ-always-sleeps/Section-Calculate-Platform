# -*- coding: utf-8 -*-
"""
测试面积比例系数功能
对比原始文件和缩放文件的输出
"""
import os
import sys
sys.path.insert(0, r"D:\tunnel_build\Code")

import engine_cad
import pandas as pd

# 测试文件
ORIGINAL_FILE = r"\\Beihai01\广西北海-测量资料\3、内湾段\内湾段分层图（全航道底图20260318）面积比例0.6.dxf"
ORIGINAL_EXCEL = r"D:\tunnel_build\测试文件\内湾段分层图（全航道）_分类汇总_20260316_154717.xlsx"

def log(msg):
    try:
        print(msg)
    except:
        print(msg.encode('ascii', 'replace').decode('ascii'))

def test_area_scale():
    """测试面积比例系数"""
    print("=" * 60)
    print("测试面积比例系数功能")
    print("=" * 60)
    
    # 检查文件
    if not os.path.exists(ORIGINAL_FILE):
        print(f"[ERROR] 找不到测试文件: {ORIGINAL_FILE}")
        return False
    
    # 读取原始Excel作为参考
    if os.path.exists(ORIGINAL_EXCEL):
        ref_df = pd.read_excel(ORIGINAL_EXCEL, sheet_name='设计量汇总')
        print(f"\n[INFO] 原始参考数据（前5行）:")
        print(ref_df.head().to_string())
    else:
        print(f"[WARN] 找不到参考Excel: {ORIGINAL_EXCEL}")
        ref_df = None
    
    # 运行autoclassify，面积比例系数=0.6
    print(f"\n[INFO] 处理面积比例0.6的文件...")
    params = {
        'files': [ORIGINAL_FILE],
        '断面线图层': 'DMX,0225',
        '桩号图层': '0-桩号',
        '面积比例系数': 0.6,
        '输出目录': r"D:\tunnel_build\测试文件"
    }
    
    engine_cad.run_autoclassify(params, log)
    
    print("\n[DONE] 测试完成")
    return True

if __name__ == "__main__":
    test_area_scale()