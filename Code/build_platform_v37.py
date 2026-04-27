# -*- coding: utf-8 -*-
"""
航道断面算量自动化平台 v3.7.0 打包脚本
"""

import PyInstaller.__main__
import os
import shutil
import time
from pathlib import Path

# 打包脚本在Code目录下，所以PROJECT_DIR就是Code目录
PROJECT_DIR = Path(__file__).parent
OUTPUT_DIR = PROJECT_DIR.parent / "航道断面算量自动化平台v3.7.0@黄秉俊"

if OUTPUT_DIR.exists():
    print(f"清理旧构建: {OUTPUT_DIR}")
    try: shutil.rmtree(OUTPUT_DIR)
    except PermissionError as e:
        OUTPUT_DIR = PROJECT_DIR.parent / f"航道断面算量自动化平台v3.7.0@黄秉俊_{int(time.time())}"

FRONTEND_ENTRY = PROJECT_DIR / "platform_ui_v3.py"
BACKEND_ENGINE = PROJECT_DIR / "engine_cad_v3.py"

print("=" * 60)
print("航道断面算量自动化平台 v3.7.0 打包脚本")
print("=" * 60)

ENGINE_PYD = None
try:
    import Cython.Build
    setup_script = f"""
from distutils.core import setup
from Cython.Build import cythonize
setup(ext_modules=cythonize(r"{BACKEND_ENGINE}", compiler_directives={{'language_level': '3'}}))
"""
    temp_setup = PROJECT_DIR / "temp_setup_engine.py"
    temp_setup.write_text(setup_script, encoding='utf-8')
    os.system(f'cd "{PROJECT_DIR}" && python temp_setup_engine.py build_ext --inplace')
    pyd_files = list(PROJECT_DIR.glob("engine_cad_v3*.pyd"))
    if pyd_files: ENGINE_PYD = pyd_files[0]
    temp_setup.unlink(missing_ok=True)
except: print("跳过pyd编译，使用源码打包")

PyInstaller.__main__.run([
    str(FRONTEND_ENTRY),
    '--name=航道断面算量自动化平台v3.7.0@黄秉俊',
    '--windowed', '--onedir', '--noconfirm',
    f'--icon={PROJECT_DIR.parent / "logo.ico"}',
    f'--distpath={OUTPUT_DIR.parent}',
    f'--workpath={PROJECT_DIR / "build_temp"}',
    '--hidden-import=ezdxf', '--hidden-import=shapely', '--hidden-import=pandas',
    '--hidden-import=PyQt6', '--hidden-import=openpyxl',
    f'--add-data={ENGINE_PYD};.' if ENGINE_PYD else f'--add-data={BACKEND_ENGINE};.',
])

test_dir = OUTPUT_DIR / "平台专用测试"
test_dir.mkdir(exist_ok=True)
src_test = PROJECT_DIR.parent / "测试文件" / "平台专用测试"
if src_test.exists():
    for f in src_test.iterdir():
        if f.is_file(): shutil.copy(f, test_dir / f.name)

for tmp in ["temp_setup_engine.py", "build_temp"]:
    p = PROJECT_DIR / tmp
    if p.exists(): p.unlink() if p.is_file() else shutil.rmtree(p)

print(f"\n打包完成! 输出目录: {OUTPUT_DIR}")