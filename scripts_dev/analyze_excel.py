# -*- coding: utf-8 -*-
import pandas as pd
import os

# 读取原始Excel
excel_path = r"D:\tunnel_build\测试文件\内湾段分层图（全航道）_分类汇总_20260316_154717.xlsx"
print(f"读取文件: {excel_path}")
print(f"文件存在: {os.path.exists(excel_path)}")

if os.path.exists(excel_path):
    # 读取所有sheet
    xls = pd.ExcelFile(excel_path)
    print(f"Sheet列表: {xls.sheet_names}")
    
    for sheet in xls.sheet_names:
        print(f"\n=== {sheet} ===")
        df = pd.read_excel(excel_path, sheet_name=sheet)
        print(df.head(20).to_string())
        print(f"...\n总共 {len(df)} 行")