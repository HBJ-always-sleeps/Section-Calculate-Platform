# -*- coding: utf-8 -*-
import openpyxl

excel_path = r'D:\tunnel_build\测试文件\2026年2月月进度工程量表（提交版）.xlsx'

wb = openpyxl.load_workbook(excel_path, read_only=True)
print("Sheet names:")
for name in wb.sheetnames:
    print(name)
wb.close()