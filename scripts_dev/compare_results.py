# -*- coding: utf-8 -*-
"""对比结果验证面积比例系数"""
import pandas as pd
import os

# 原始参考Excel
ref_excel = r"D:\tunnel_build\测试文件\内湾段分层图（全航道）_分类汇总_20260316_154717.xlsx"
# 新生成的Excel
new_excel = r"D:\tunnel_build\测试文件\内湾段分层图（全航道底图20260318）面积比例0.6_分类汇总_20260319_090703.xlsx"

print("=" * 70)
print("面积比例系数验证")
print("=" * 70)

# 读取原始数据
if os.path.exists(ref_excel):
    ref_df = pd.read_excel(ref_excel, sheet_name='设计量汇总')
    print(f"\n[原始参考数据] 面积总和:")
    print(ref_df.sum(numeric_only=True))
else:
    print(f"[ERROR] 找不到参考文件: {ref_excel}")
    ref_df = None

# 读取新生成数据
if os.path.exists(new_excel):
    new_df = pd.read_excel(new_excel, sheet_name='设计量汇总')
    print(f"\n[新生成数据] 面积总和 (面积比例0.6):")
    print(new_df.sum(numeric_only=True))
    
    # 对比
    if ref_df is not None:
        print("\n[对比分析]")
        print("原始数据 * 0.6 vs 新数据:")
        for col in ref_df.columns:
            if col != '桩号':
                orig_sum = ref_df[col].sum()
                new_sum = new_df[col].sum() if col in new_df.columns else 0
                expected = orig_sum * 0.6
                print(f"  {col}: 原始={orig_sum:.2f}, 期望={expected:.2f}, 实际={new_sum:.2f}")
else:
    print(f"[ERROR] 找不到新生成文件: {new_excel}")

print("\n" + "=" * 70)