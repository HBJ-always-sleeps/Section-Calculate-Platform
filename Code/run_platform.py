# -*- coding: utf-8 -*-
"""
航道断面算量自动化平台 v3.0 - 启动脚本
同时启动前端 PyQt6 界面和后端 FastAPI 服务
"""

import os
import sys
import subprocess
import threading
import time
from pathlib import Path

# 项目根目录
PROJECT_ROOT = Path(__file__).parent


def start_backend():
    """启动后端服务"""
    print("[后端] 正在启动 FastAPI 服务...")
    
    backend_script = PROJECT_ROOT / "server.py"
    
    # 使用系统 Python（避免 venv 缺少依赖）
    cmd = ["python", str(backend_script)]
    
    # 启动后端进程 - 不捕获输出，直接显示
    process = subprocess.Popen(
        cmd,
        cwd=str(PROJECT_ROOT)
    )
    
    # 等待后端启动
    time.sleep(2)
    
    return process


def start_frontend():
    """启动前端界面"""
    print("[前端] 正在启动 PyQt6 界面...")
    
    frontend_script = PROJECT_ROOT / "platform_ui_v3.py"
    
    # 使用系统 Python
    cmd = ["python", str(frontend_script)]
    
    # 启动前端进程
    process = subprocess.Popen(
        cmd,
        cwd=str(PROJECT_ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True
    )
    
    return process


def main():
    print("=" * 60)
    print("  航道断面算量自动化平台 v3.0")
    print("  前后端分离架构")
    print("=" * 60)
    
    # 检查文件是否存在
    backend_script = PROJECT_ROOT / "Code" / "server.py"
    frontend_script = PROJECT_ROOT / "Code" / "platform_ui_v3.py"
    
    if not backend_script.exists():
        print(f"[错误] 后端脚本不存在: {backend_script}")
        return
        
    if not frontend_script.exists():
        print(f"[错误] 前端脚本不存在: {frontend_script}")
        return
    
    # 启动后端
    backend_process = start_backend()
    
    # 等待后端完全启动
    print("[系统] 等待后端服务就绪...")
    time.sleep(3)
    
    # 启动前端
    frontend_process = start_frontend()
    
    print("=" * 60)
    print("[系统] 平台已启动!")
    print("  - 后端地址: http://127.0.0.1:8000")
    print("  - API 文档: http://127.0.0.1:8000/docs")
    print("=" * 60)
    print("[提示] 关闭此窗口将停止所有服务")
    print()
    
    try:
        # 等待前端进程结束
        frontend_process.wait()
    except KeyboardInterrupt:
        print("\n[系统] 正在停止服务...")
    finally:
        # 清理进程
        if backend_process.poll() is None:
            backend_process.terminate()
        if frontend_process.poll() is None:
            frontend_process.terminate()
        print("[系统] 服务已停止")


if __name__ == "__main__":
    main()