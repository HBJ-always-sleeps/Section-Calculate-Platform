# -*- coding: utf-8 -*-
"""
航道断面算量自动化平台 打包脚本
使用 PyInstaller 将平台打包成单个可执行文件
"""

import os
import sys
import subprocess
import shutil

# 项目根目录
PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))

# 需要包含的数据文件
DATA_FILES = [
    ('engine_cad.py', '.'),
    ('engine_cad.cp311-win_amd64.pyd', '.'),
    ('platform_resources.py', '.'),
    ('adaptive.py', '.'),
    ('autoline.py', '.'),
    ('autopaste.py', '.'),
    ('autosection.py', '.'),
    ('autoclassify.py', '.'),
    ('stat_above_5m.py', '.'),
]

# 隐式导入
HIDDEN_IMPORTS = [
    'ezdxf',
    'pandas',
    'shapely',
    'shapely.geometry',
    'shapely.ops',
    'numpy',
    'openpyxl',
    'PyQt6',
    'PyQt6.QtWidgets',
    'PyQt6.QtCore',
    'PyQt6.QtGui',
]

def build():
    """执行打包"""
    print("=" * 50)
    print("航道断面算量自动化平台 打包工具")
    print("=" * 50)
    
    # 检查 PyInstaller
    try:
        import PyInstaller
        print("[OK] PyInstaller 已安装")
    except ImportError:
        print("[INSTALL] 正在安装 PyInstaller...")
        subprocess.run([sys.executable, '-m', 'pip', 'install', 'pyinstaller'], check=True)
    
    # 构建 datas 参数
    datas = []
    for src, dst in DATA_FILES:
        src_path = os.path.join(PROJECT_DIR, src)
        if os.path.exists(src_path):
            datas.append(f'("{src_path}", "{dst}")')
            print(f"[DATA] {src}")
        else:
            print(f"[WARN] 文件不存在: {src}")
    
    # 构建 hidden-imports 参数
    hidden_args = []
    for mod in HIDDEN_IMPORTS:
        hidden_args.extend(['--hidden-import', mod])
    
    # 构建 datas 参数
    data_args = []
    for src, dst in DATA_FILES:
        src_path = os.path.join(PROJECT_DIR, src)
        if os.path.exists(src_path):
            data_args.extend(['--add-data', f'{src_path};{dst}'])
    
    # 主程序入口
    main_script = os.path.join(PROJECT_DIR, 'platform_ui.py')
    
    # 输出目录
    dist_dir = os.path.join(PROJECT_DIR, 'dist')
    build_dir = os.path.join(PROJECT_DIR, 'build_exe')
    
    # PyInstaller 命令
    cmd = [
        sys.executable, '-m', 'PyInstaller',
        '--onefile',           # 单文件
        '--windowed',          # 无控制台窗口
        '--name', '航道断面算量自动化平台',
        '--distpath', dist_dir,
        '--workpath', build_dir,
        '--specpath', PROJECT_DIR,
    ]
    
    # 添加数据文件
    cmd.extend(data_args)
    
    # 添加隐式导入
    cmd.extend(hidden_args)
    
    # 添加主脚本
    cmd.append(main_script)
    
    print("\n[CMD] 执行打包命令...")
    print(' '.join(cmd[:10]), '...')
    
    # 执行打包
    result = subprocess.run(cmd, cwd=PROJECT_DIR)
    
    if result.returncode == 0:
        exe_path = os.path.join(dist_dir, '航道断面算量自动化平台.exe')
        if os.path.exists(exe_path):
            print("\n" + "=" * 50)
            print("[SUCCESS] 打包完成!")
            print(f"[OUTPUT] {exe_path}")
            print(f"[SIZE] {os.path.getsize(exe_path) / 1024 / 1024:.1f} MB")
            print("=" * 50)
            
            # 清理构建目录
            if os.path.exists(build_dir):
                shutil.rmtree(build_dir)
                print("[CLEAN] 已清理构建目录")
        else:
            print("[ERROR] 未找到输出文件")
    else:
        print("[ERROR] 打包失败")
    
    return result.returncode

if __name__ == '__main__':
    sys.exit(build())