# -*- coding: utf-8 -*-
"""测试ezdxf头变量设置方法"""

import ezdxf
from ezdxf.math import Vec3

# 创建新文档
doc = ezdxf.new()

# 检查当前EXTMIN/EXTMAX值
print("Before setting:")
print(f"  EXTMIN: {doc.header.hdrvars['$EXTMIN'].value}")
print(f"  EXTMAX: {doc.header.hdrvars['$EXTMAX'].value}")

# 尝试不同的设置方法
print("\nTrying different methods...")

# 方法1：直接设置（带$前缀）
try:
    doc.header['$EXTMIN'] = Vec3(100, 200, 300)
    print("Method 1 (doc.header['$EXTMIN'] = Vec3): SUCCESS")
except Exception as e:
    print(f"Method 1 failed: {e}")

# 方法2：使用set方法
try:
    doc.header.set('$EXTMIN', Vec3(100, 200, 300))
    print("Method 2 (doc.header.set('$EXTMIN', Vec3)): SUCCESS")
except Exception as e:
    print(f"Method 2 failed: {e}")

# 方法3：检查是否有专门的设置方法
print(f"\nHeader methods: {[m for m in dir(doc.header) if not m.startswith('_')]}")

# 保存测试文件
test_path = r'D:\断面算量平台\测试文件\test_header.dxf'
doc.saveas(test_path)

# 重新读取验证
doc2 = ezdxf.readfile(test_path)
print("\nAfter reload:")
print(f"  EXTMIN: {doc2.header.hdrvars['$EXTMIN'].value}")
print(f"  EXTMAX: {doc2.header.hdrvars['$EXTMAX'].value}")