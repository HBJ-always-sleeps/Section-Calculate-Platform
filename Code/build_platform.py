# -*- coding: utf-8 -*-
"""
build_platform.py - 航道断面算量自动化平台打包脚本
精简版：只包含必要依赖
"""
import subprocess
import sys
import os
import shutil

def clean_output_dir(output_dir):
    """清理输出目录中不必要的文件"""
    print("\n" + "="*60)
    print("第四步：清理不必要的文件")
    print("="*60)
    
    # 需要删除的顶层文件
    top_files_to_remove = [
        "autoclassify.py",
        "stat_above_5m.py",
        "platform_resources.py",  # 已嵌入exe
    ]
    
    for f in top_files_to_remove:
        path = os.path.join(output_dir, f)
        if os.path.exists(path):
            os.remove(path)
            print(f"[DEL] {f}")
    
    # 需要删除的_internal子目录
    dirs_to_remove = [
        "Cython",           # 编译工具，运行不需要
        "Pythonwin",        # win32ui，不需要
        "pywin32_system32", # pywin32，不需要
        "win32",            # win32，不需要
        "win32com",         # win32com，不需要
        "setuptools-65.5.0.dist-info",  # setuptools，不需要
        "matplotlib",       # matplotlib，暂不需要
        "PIL",              # Pillow，暂不需要
        "lxml",             # lxml，暂不需要
        "contourpy",        # matplotlib依赖，不需要
        "kiwisolver",       # matplotlib依赖，不需要
        "fontTools",        # matplotlib依赖，不需要
        "dateutil",         # matplotlib依赖，可能需要保留
    ]
    
    internal_dir = os.path.join(output_dir, "_internal")
    if os.path.exists(internal_dir):
        for d in dirs_to_remove:
            path = os.path.join(internal_dir, d)
            if os.path.exists(path):
                try:
                    shutil.rmtree(path)
                    print(f"[DEL] _internal/{d}/")
                except Exception as e:
                    print(f"[WARN] 无法删除 {d}: {e}")
    
    print("[OK] 清理完成")


def build_platform():
    """打包平台"""
    print("="*60)
    print("航道断面算量自动化平台 - 精简打包")
    print("="*60)
    
    base_dir = os.path.dirname(os.path.abspath(__file__))
    code_dir = os.path.join(base_dir, "Code")
    
    # 输出目录
    output_dir = os.path.join(base_dir, "航道断面算量平台")
    if os.path.exists(output_dir):
        shutil.rmtree(output_dir)
        print(f"[INFO] 已清理: {output_dir}")
    
    # PyInstaller命令
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onedir",           # 打包成目录
        "--windowed",         # 不显示控制台窗口
        "--name=航道断面算量平台",
        "--distpath=" + os.path.join(base_dir, "dist_temp"),
        "--workpath=" + os.path.join(base_dir, "build_temp"),
        "--specpath=" + base_dir,
        # 隐藏导入
        "--hidden-import=ezdxf",
        "--hidden-import=pandas",
        "--hidden-import=shapely",
        "--hidden-import=shapely.geometry",
        "--hidden-import=shapely.ops",
        "--hidden-import=numpy",
        "--hidden-import=platform_resources",
        # 排除不需要的模块
        "--exclude-module=Cython",
        "--exclude-module=matplotlib",
        "--exclude-module=PIL",
        "--exclude-module=lxml",
        "--exclude-module=win32com",
        "--exclude-module=win32ui",
        "--exclude-module=pythonwin",
        "--exclude-module=setuptools",
        # 前端入口
        os.path.join(code_dir, "platform_ui.py")
    ]
    
    print("\n[INFO] 正在打包...")
    result = subprocess.run(cmd, cwd=base_dir)
    
    if result.returncode != 0:
        print("[ERROR] 打包失败")
        return None
    
    # 移动输出目录
    dist_temp = os.path.join(base_dir, "dist_temp", "航道断面算量平台")
    if os.path.exists(dist_temp):
        shutil.move(dist_temp, output_dir)
        print(f"[OK] 输出目录: {output_dir}")
    
    # 清理临时文件
    for d in ["dist_temp", "build_temp"]:
        path = os.path.join(base_dir, d)
        if os.path.exists(path):
            shutil.rmtree(path)
    
    # 删除spec文件
    spec_file = os.path.join(base_dir, "航道断面算量平台.spec")
    if os.path.exists(spec_file):
        os.remove(spec_file)
    
    # 复制engine_cad.pyd
    engine_pyd = os.path.join(code_dir, "engine_cad.pyd")
    if os.path.exists(engine_pyd):
        shutil.copy2(engine_pyd, os.path.join(output_dir, "engine_cad.pyd"))
        print(f"[OK] 复制: engine_cad.pyd")
    
    # 清理不必要文件
    clean_output_dir(output_dir)
    
    return output_dir


def show_result(output_dir):
    """显示打包结果"""
    print("\n" + "="*60)
    print("打包完成！")
    print("="*60)
    print(f"\n输出目录: {output_dir}")
    print("\n文件列表:")
    
    total_size = 0
    for f in os.listdir(output_dir):
        path = os.path.join(output_dir, f)
        if os.path.isdir(path):
            # 计算目录大小
            dir_size = sum(os.path.getsize(os.path.join(dp, f)) 
                          for dp, dn, fn in os.walk(path) for f in fn)
            total_size += dir_size
            print(f"  [DIR] {f}/ ({dir_size/1024/1024:.1f} MB)")
        else:
            size = os.path.getsize(path)
            total_size += size
            if f.endswith('.exe'):
                print(f"  [EXE] {f} ({size/1024/1024:.1f} MB)")
            elif f.endswith('.pyd'):
                print(f"  [PYD] {f} ({size/1024:.1f} KB) - 后端引擎")
            else:
                print(f"  [FILE] {f} ({size/1024:.1f} KB)")
    
    print(f"\n总大小: {total_size/1024/1024:.1f} MB")


if __name__ == "__main__":
    output_dir = build_platform()
    if output_dir:
        show_result(output_dir)