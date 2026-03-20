# -*- coding: utf-8 -*-
"""
build_platform_v2.py - 航道断面算量自动化平台v2.0前后端分离打包脚本
前端: platform_ui.py -> exe
后端: engine_cad.py -> pyd (代码保护)
输出: 航道断面算量自动化平台v2.0@黄秉俊/
"""
import subprocess
import sys
import os
import shutil

def build_engine_pyd():
    """编译后端引擎为pyd文件"""
    print("\n" + "="*60)
    print("第一步: 编译后端引擎 (engine_cad.py -> engine_cad.pyd)")
    print("="*60)
    
    base_dir = os.path.dirname(os.path.abspath(__file__))
    code_dir = os.path.join(base_dir, "Code")
    engine_py = os.path.join(code_dir, "engine_cad.py")
    
    if not os.path.exists(engine_py):
        print(f"[ERROR] 找不到 {engine_py}")
        return None
    
    # 创建setup.py用于Cython编译
    setup_py = os.path.join(base_dir, "setup_engine.py")
    with open(setup_py, 'w', encoding='utf-8') as f:
        f.write('''# -*- coding: utf-8 -*-
from setuptools import setup
from Cython.Build import cythonize
import sys
import os

setup(
    name='engine_cad',
    ext_modules=cythonize(
        "Code/engine_cad.py",
        compiler_directives={'language_level': "3"}
    ),
)
''')
    
    print("[INFO] 正在编译 engine_cad.py -> engine_cad.pyd ...")
    
    # 执行编译
    cmd = [sys.executable, setup_py, "build_ext", "--inplace"]
    result = subprocess.run(cmd, cwd=base_dir)
    
    if result.returncode != 0:
        print("[ERROR] 编译失败")
        return None
    
    # 查找生成的pyd文件并重命名
    pyd_file = None
    for f in os.listdir(code_dir):
        if f.startswith("engine_cad") and f.endswith(".pyd"):
            old_path = os.path.join(code_dir, f)
            new_path = os.path.join(code_dir, "engine_cad.pyd")
            if os.path.exists(new_path):
                os.remove(new_path)
            os.rename(old_path, new_path)
            pyd_file = new_path
            print(f"[OK] 编译成功: {pyd_file}")
            break
    
    # 清理临时文件
    if os.path.exists(setup_py):
        os.remove(setup_py)
    
    return pyd_file


def build_frontend_exe():
    """打包前端exe"""
    print("\n" + "="*60)
    print("第二步: 打包前端 (platform_ui.py -> exe)")
    print("="*60)
    
    base_dir = os.path.dirname(os.path.abspath(__file__))
    code_dir = os.path.join(base_dir, "Code")
    
    # PyInstaller命令
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onedir",
        "--windowed",
        "--name=航道断面算量自动化平台v2.0@黄秉俊",
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
    
    print("[INFO] 正在打包前端...")
    result = subprocess.run(cmd, cwd=base_dir)
    
    if result.returncode != 0:
        print("[ERROR] 打包失败")
        return None
    
    # 移动输出目录
    dist_temp = os.path.join(base_dir, "dist_temp", "航道断面算量自动化平台v2.0@黄秉俊")
    output_dir = os.path.join(base_dir, "航道断面算量自动化平台v2.0@黄秉俊")
    
    if os.path.exists(output_dir):
        shutil.rmtree(output_dir)
    
    if os.path.exists(dist_temp):
        shutil.move(dist_temp, output_dir)
        print(f"[OK] 输出目录: {output_dir}")
    
    # 清理临时文件
    for d in ["dist_temp", "build_temp"]:
        path = os.path.join(base_dir, d)
        if os.path.exists(path):
            shutil.rmtree(path)
    
    # 删除spec文件
    spec_file = os.path.join(base_dir, "航道断面算量自动化平台v2.0@黄秉俊.spec")
    if os.path.exists(spec_file):
        os.remove(spec_file)
    
    return output_dir


def copy_backend_files(output_dir, pyd_file):
    """复制后端pyd文件到输出目录"""
    print("\n" + "="*60)
    print("第三步: 组装前后端文件")
    print("="*60)
    
    if pyd_file and os.path.exists(pyd_file):
        dest_pyd = os.path.join(output_dir, "engine_cad.pyd")
        shutil.copy2(pyd_file, dest_pyd)
        print(f"[OK] 复制后端引擎: engine_cad.pyd")
    
    print("[OK] 前后端分离打包完成")


def clean_unnecessary_files(output_dir):
    """清理不必要的依赖文件"""
    print("\n" + "="*60)
    print("第四步: 清理不必要的依赖")
    print("="*60)
    
    # 需要删除的_internal子目录
    dirs_to_remove = [
        "Cython",
        "Pythonwin",
        "pywin32_system32",
        "win32",
        "win32com",
        "setuptools-65.5.0.dist-info",
        "matplotlib",
        "PIL",
        "lxml",
        "contourpy",
        "kiwisolver",
        "fontTools",
        "dateutil",
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


def show_result(output_dir):
    """显示打包结果"""
    print("\n" + "="*60)
    print("打包完成!")
    print("="*60)
    print(f"\n输出目录: {output_dir}")
    print("\n文件结构:")
    
    total_size = 0
    for f in os.listdir(output_dir):
        path = os.path.join(output_dir, f)
        if os.path.isdir(path):
            dir_size = sum(os.path.getsize(os.path.join(dp, fn)) 
                          for dp, dn, fn in os.walk(path) for fn in fn)
            total_size += dir_size
            print(f"  [DIR] {f}/ ({dir_size/1024/1024:.1f} MB)")
        else:
            size = os.path.getsize(path)
            total_size += size
            if f.endswith('.exe'):
                print(f"  [EXE] {f} ({size/1024/1024:.1f} MB) - 前端UI")
            elif f.endswith('.pyd'):
                print(f"  [PYD] {f} ({size/1024:.1f} KB) - 后端引擎(已加密)")
            else:
                print(f"  [FILE] {f} ({size/1024:.1f} KB)")
    
    print(f"\n总大小: {total_size/1024/1024:.1f} MB")
    print("\n架构说明:")
    print("  - 前端: exe文件，包含UI界面和业务逻辑调用")
    print("  - 后端: pyd文件，包含核心计算引擎(已加密保护)")


def main():
    print("="*60)
    print("航道断面算量自动化平台v2.0 - 前后端分离打包")
    print("="*60)
    
    # 第一步: 编译后端
    pyd_file = build_engine_pyd()
    if not pyd_file:
        print("[WARN] 后端编译失败，将使用Python源码打包")
    
    # 第二步: 打包前端
    output_dir = build_frontend_exe()
    if not output_dir:
        print("[ERROR] 打包失败!")
        return
    
    # 第三步: 复制后端文件
    copy_backend_files(output_dir, pyd_file)
    
    # 第四步: 清理不必要文件
    clean_unnecessary_files(output_dir)
    
    # 显示结果
    show_result(output_dir)


if __name__ == "__main__":
    main()