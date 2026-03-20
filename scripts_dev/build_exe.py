# -*- coding: utf-8 -*-
"""
build_exe.py - PyInstaller打包脚本
"""
import subprocess
import sys
import os
import shutil

def build():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    code_dir = os.path.join(base_dir, "Code")
    dist_dir = os.path.join(base_dir, "dist")
    
    # 清理旧的构建文件
    for d in ["build", "dist"]:
        path = os.path.join(base_dir, d)
        if os.path.exists(path):
            shutil.rmtree(path)
            print(f"已清理: {path}")
    
    # PyInstaller命令
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",           # 打包成单个exe
        "--windowed",          # 不显示控制台窗口
        "--name=断面分类算量",   # 输出文件名
        f"--add-data={code_dir};Code",  # 包含Code目录
        "--hidden-import=ezdxf",
        "--hidden-import=pandas",
        "--hidden-import=shapely",
        "--hidden-import=shapely.geometry",
        "--hidden-import=shapely.ops",
        "--distpath=" + dist_dir,
        os.path.join(code_dir, "autoclassify_gui.py")
    ]
    
    print("开始打包...")
    print(" ".join(cmd))
    
    result = subprocess.run(cmd, cwd=base_dir)
    
    if result.returncode == 0:
        exe_path = os.path.join(dist_dir, "断面分类算量.exe")
        if os.path.exists(exe_path):
            print(f"\n打包成功！输出文件: {exe_path}")
        else:
            print("\n打包完成，但未找到exe文件")
    else:
        print("\n打包失败！")

if __name__ == "__main__":
    build()