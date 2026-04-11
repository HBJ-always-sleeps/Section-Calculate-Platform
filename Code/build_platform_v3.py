# -*- coding: utf-8 -*-
"""
航道断面算量自动化平台 v3.5 打包脚本
按照v2.0结构打包：
- 前端exe
- _internal文件夹（内部环境）
- engine_cad.pyd后端
"""

import PyInstaller.__main__
import os
import sys
import shutil
import time
from pathlib import Path

# 项目路径
PROJECT_DIR = Path(__file__).parent
CODE_DIR = PROJECT_DIR / "Code"
OUTPUT_DIR = PROJECT_DIR / "航道断面算量自动化平台v3.5@黄秉俊"

# 清理旧构建（跳过被占用的文件）
if OUTPUT_DIR.exists():
    print(f"清理旧构建: {OUTPUT_DIR}")
    try:
        shutil.rmtree(OUTPUT_DIR)
    except PermissionError as e:
        print(f"警告: 部分文件被占用，跳过清理 - {e}")
        OUTPUT_DIR = PROJECT_DIR / f"航道断面算量自动化平台v3.5@黄秉俊_{int(time.time())}"
        print(f"使用新输出目录: {OUTPUT_DIR}")

# 前端入口
FRONTEND_ENTRY = CODE_DIR / "platform_ui_v3.py"

# 后端引擎
BACKEND_ENGINE = CODE_DIR / "engine_cad.py"

print("=" * 60)
print("航道断面算量自动化平台 v3.5 打包脚本")
print("=" * 60)

# Step 1: 尝试编译后端为pyd（可选）
print("\n[Step 1] 检查是否编译后端引擎为pyd...")
ENGINE_PYD = None

try:
    import Cython.Build
    import distutils.core
    
    # 先编译engine_cad.py为pyd
    setup_script = f"""
from distutils.core import setup
from Cython.Build import cythonize
import sys

setup(
    ext_modules=cythonize(
        r"{BACKEND_ENGINE}",
        compiler_directives={{
            'language_level': '3',
            'boundscheck': False,
            'wraparound': False,
        }}
    )
)
"""
    
    # 写入临时setup.py
    temp_setup = PROJECT_DIR / "temp_setup_engine.py"
    temp_setup.write_text(setup_script, encoding='utf-8')
    
    # 执行编译
    result = os.system(f'cd "{PROJECT_DIR}" && python temp_setup_engine.py build_ext --inplace')
    
    # 查找生成的pyd文件
    pyd_files = list(PROJECT_DIR.glob("engine_cad*.pyd"))
    if pyd_files:
        ENGINE_PYD = pyd_files[0]
        print(f"后端编译成功: {ENGINE_PYD}")
    else:
        print("pyd编译未生成文件，将使用源码打包")
    
    # 清理临时文件
    temp_setup.unlink(missing_ok=True)
except ImportError:
    print("Cython未安装，跳过pyd编译，直接使用源码打包")
except Exception as e:
    print(f"pyd编译出错: {e}，将使用源码打包")

# Step 2: 打包前端
print("\n[Step 2] 打包前端...")

PyInstaller.__main__.run([
    str(FRONTEND_ENTRY),
    '--name=航道断面算量自动化平台v3.5@黄秉俊',
    '--windowed',  # GUI模式，无控制台
    '--onedir',   # 目录模式（带_internal）
    '--noconfirm',
    f'--icon={PROJECT_DIR / "logo.ico"}',
    f'--distpath={OUTPUT_DIR}',
    f'--workpath={PROJECT_DIR / "build_temp"}',
    f'--specpath={PROJECT_DIR}',
    # 隐藏导入
    '--hidden-import=ezdxf',
    '--hidden-import=ezdxf.acc',
    '--hidden-import=shapely',
    '--hidden-import=shapely.geometry',
    '--hidden-import=pandas',
    '--hidden-import=numpy',
    '--hidden-import=PyQt6',
    '--hidden-import=openpyxl',
    # 数据文件
    f'--add-data={ENGINE_PYD};.' if ENGINE_PYD else f'--add-data={BACKEND_ENGINE};.',
    # 排除不需要的模块
    '--exclude-module=tkinter',
    '--exclude-module=matplotlib',
    '--exclude-module=scipy',
])

# Step 3: 复制后端pyd到输出目录
print("\n[Step 3] 整理输出目录...")

# 重命名exe
old_exe = OUTPUT_DIR / "航道断面算量自动化平台v3.5@黄秉俊.exe"
if not old_exe.exists():
    # 查找实际生成的exe
    exe_files = list(OUTPUT_DIR.glob("*.exe"))
    if exe_files:
        old_exe = exe_files[0]

print(f"前端exe: {old_exe}")

# 创建平台专用测试文件夹
test_dir = OUTPUT_DIR / "平台专用测试"
test_dir.mkdir(exist_ok=True)

# 复制测试文件
src_test_dir = PROJECT_DIR / "测试文件" / "平台专用测试"
if src_test_dir.exists():
    for f in src_test_dir.iterdir():
        if f.is_file():
            shutil.copy(f, test_dir / f.name)
            print(f"  复制测试文件: {f.name}")

# 清理临时文件
temp_setup_file = PROJECT_DIR / "temp_setup_engine.py"
if temp_setup_file.exists():
    temp_setup_file.unlink()
build_temp = PROJECT_DIR / "build_temp"
if build_temp.exists():
    shutil.rmtree(build_temp)

spec_file = PROJECT_DIR / "航道断面算量自动化平台v3.5@黄秉俊.spec"
spec_file.unlink(missing_ok=True)

print("\n" + "=" * 60)
print("打包完成!")
print(f"输出目录: {OUTPUT_DIR}")
print("=" * 60)

# 列出生成的文件
print("\n生成的文件:")
for f in OUTPUT_DIR.iterdir():
    if f.is_file():
        size = f.stat().st_size / (1024 * 1024)
        print(f"  {f.name}: {size:.2f} MB")
    elif f.is_dir():
        file_count = len(list(f.rglob("*")))
        print(f"  {f.name}/ ({file_count} 个文件)")