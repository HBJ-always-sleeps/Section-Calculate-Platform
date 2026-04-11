# -*- coding: utf-8 -*-
"""编译engine_cad.py为pyd文件"""
import os
import sys
from setuptools import setup
from Cython.Build import cythonize

# 切换到脚本所在目录
os.chdir(os.path.dirname(os.path.abspath(__file__)))
print(f"工作目录: {os.getcwd()}")
print(f"Python版本: {sys.version}")

# 检查文件是否存在
if os.path.exists('engine_cad.py'):
    print("找到 engine_cad.py")
else:
    print("错误: engine_cad.py 不存在!")
    sys.exit(1)

# 编译
setup(
    ext_modules=cythonize('engine_cad.py', language_level=3),
    script_args=['build_ext', '--inplace']
)

print("\n编译完成!")