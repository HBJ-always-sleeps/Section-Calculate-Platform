# -*- coding: utf-8 -*-
"""
航道断面算量自动化平台 v3.0 - 独立版打包脚本
无需后端服务，直接调用 engine_cad 模块
"""

import os
import sys
import subprocess
import shutil
from pathlib import Path
from datetime import datetime

# 项目根目录
PROJECT_DIR = Path(__file__).parent
CODE_DIR = PROJECT_DIR / "Code"

# 输出目录
timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
OUTPUT_DIR = PROJECT_DIR / f"航道断面算量自动化平台v3.0_独立版_{timestamp}"

# Logo 文件
LOGO_PATH = r"C:\Users\训教\Downloads\Gemini_Generated_Image_3db1n53db1n53db1.png"

# 隐式导入
HIDDEN_IMPORTS = [
    'PyQt6',
    'PyQt6.QtWidgets',
    'PyQt6.QtCore',
    'PyQt6.QtGui',
    'ezdxf',
    'pandas',
    'shapely',
    'shapely.geometry',
    'shapely.ops',
    'numpy',
    'openpyxl',
]


def build():
    """执行打包"""
    print("=" * 60)
    print("  航道断面算量自动化平台 v3.0 - 独立版打包")
    print("=" * 60)
    
    # 创建输出目录
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"[输出] {OUTPUT_DIR}")
    
    # 检查 PyInstaller
    try:
        import PyInstaller
    except ImportError:
        print("[安装] PyInstaller...")
        subprocess.run([sys.executable, '-m', 'pip', 'install', 'pyinstaller'], check=True)
    
    # 前端脚本
    frontend_script = CODE_DIR / "platform_ui_v3_standalone.py"
    if not frontend_script.exists():
        print(f"[错误] 前端脚本不存在: {frontend_script}")
        return False
    
    # 核心模块
    engine_py = CODE_DIR / "engine_cad.py"
    engine_pyd = None
    
    # 检查 .pyd 文件
    for pyd in PROJECT_DIR.glob("engine_cad.*.pyd"):
        engine_pyd = pyd
        break
    
    # 构建 hidden-imports 参数
    hidden_args = []
    for mod in HIDDEN_IMPORTS:
        hidden_args.extend(['--hidden-import', mod])
    
    # 构建 datas 参数
    data_args = []
    
    # 添加 Logo
    if Path(LOGO_PATH).exists():
        data_args.extend(['--add-data', f'{LOGO_PATH};.'])
    
    # 添加 engine_cad
    if engine_pyd:
        data_args.extend(['--add-data', f'{engine_pyd};.'])
        print(f"[添加] {engine_pyd.name}")
    elif engine_py.exists():
        data_args.extend(['--add-data', f'{engine_py};.'])
        print(f"[添加] engine_cad.py")
    
    # 构建目录
    build_dir = PROJECT_DIR / 'build_standalone_temp'
    
    # PyInstaller 命令
    cmd = [
        sys.executable, '-m', 'PyInstaller',
        '--onedir',            # 目录模式
        '--windowed',          # 无控制台窗口
        '--name', '航道断面算量自动化平台v3.0',
        '--distpath', str(OUTPUT_DIR),
        '--workpath', str(build_dir),
        '--specpath', str(PROJECT_DIR),
        '--noconfirm',
    ]
    
    # 添加数据文件
    cmd.extend(data_args)
    
    # 添加隐式导入
    cmd.extend(hidden_args)
    
    # 添加主脚本
    cmd.append(str(frontend_script))
    
    print("\n[执行] PyInstaller...")
    result = subprocess.run(cmd, cwd=str(PROJECT_DIR))
    
    # 清理
    if build_dir.exists():
        shutil.rmtree(build_dir)
    
    spec_file = PROJECT_DIR / "航道断面算量自动化平台v3.0.spec"
    if spec_file.exists():
        spec_file.unlink()
    
    # 检查结果
    exe_path = OUTPUT_DIR / "航道断面算量自动化平台v3.0" / "航道断面算量自动化平台v3.0.exe"
    if result.returncode == 0 and exe_path.exists():
        print("\n" + "=" * 60)
        print("[成功] 打包完成!")
        print(f"[输出] {exe_path}")
        print(f"[大小] {exe_path.stat().st_size / 1024 / 1024:.1f} MB")
        print("=" * 60)
        return True
    else:
        print("[错误] 打包失败")
        return False


if __name__ == '__main__':
    build()