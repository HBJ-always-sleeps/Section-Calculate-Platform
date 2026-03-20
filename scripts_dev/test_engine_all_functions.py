# -*- coding: utf-8 -*-
"""
测试脚本：engine_cad.py 全功能测试
用途：一键测试所有核心功能，验证代码重构后功能正常
测试文件目录：测试文件\平台专用测试
命名：test_engine_all_functions.py（请勿删除，用于后续迭代测试）
"""

import os
import sys
import json
import tempfile
from datetime import datetime

# 添加 Code 目录到路径
code_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'Code')
if code_path not in sys.path:
    sys.path.insert(0, code_path)

import engine_cad

# 测试文件目录
TEST_DIR = r"D:\tunnel_build\测试文件\平台专用测试"

def log(msg):
    """日志输出"""
    timestamp = datetime.now().strftime("%H:%M:%S")
    try:
        print(f"[{timestamp}] {msg}")
    except UnicodeEncodeError:
        # Windows终端编码问题，使用ASCII安全输出
        safe_msg = msg.encode('ascii', 'replace').decode('ascii')
        print(f"[{timestamp}] {safe_msg}")

def test_autoline():
    """测试断面线合并功能"""
    log("=" * 50)
    log("[TEST] 断面线合并 (autoline)")
    log("=" * 50)
    
    test_file = os.path.join(TEST_DIR, "断面线合并_测试文件.dxf")
    if not os.path.exists(test_file):
        log(f"[SKIP] 测试文件不存在: {test_file}")
        return False
    
    params = {
        '图层A名称': '断面线 1',
        '图层B名称': '断面线 2',
        '输出图层名': 'FINAL_BOTTOM_SURFACE',
        'files': [test_file]
    }
    
    try:
        engine_cad.run_autoline(params, log)
        log("[OK] autoline 测试完成")
        return True
    except Exception as e:
        log(f"[ERROR] autoline 测试失败: {e}")
        return False

def test_autopaste():
    """测试批量粘贴功能"""
    log("=" * 50)
    log("[TEST] 批量粘贴 (autopaste)")
    log("=" * 50)
    
    src_file = os.path.join(TEST_DIR, "批量粘贴_源文件.dxf")
    dst_file = os.path.join(TEST_DIR, "批量粘贴_目标文件.dxf")
    
    if not os.path.exists(src_file):
        log(f"[SKIP] 源文件不存在: {src_file}")
        return False
    if not os.path.exists(dst_file):
        log(f"[SKIP] 目标文件不存在: {dst_file}")
        return False
    
    params = {
        '源文件名': src_file,
        '目标文件名': dst_file,
        'files': [src_file]
    }
    
    try:
        engine_cad.run_autopaste(params, log)
        log("[OK] autopaste 测试完成")
        return True
    except Exception as e:
        log(f"[ERROR] autopaste 测试失败: {e}")
        return False

def test_autohatch():
    """测试快速填充功能"""
    log("=" * 50)
    log("[TEST] 快速填充 (autohatch)")
    log("=" * 50)
    
    test_file = os.path.join(TEST_DIR, "快速填充_测试文件.dxf")
    if not os.path.exists(test_file):
        log(f"[SKIP] 测试文件不存在: {test_file}")
        return False
    
    params = {
        '填充层名称': 'AA_填充算量层',
        'files': [test_file]
    }
    
    try:
        engine_cad.run_autohatch(params, log)
        log("[OK] autohatch 测试完成")
        return True
    except Exception as e:
        log(f"[ERROR] autohatch 测试失败: {e}")
        return False

def test_autoclassify():
    """测试分类算量功能"""
    log("=" * 50)
    log("[TEST] 分类算量 (autoclassify)")
    log("=" * 50)
    
    test_file = os.path.join(TEST_DIR, "分类算量_测试文件.dxf")
    if not os.path.exists(test_file):
        log(f"[SKIP] 测试文件不存在: {test_file}")
        return False
    
    params = {
        '断面线图层': 'DMX',
        '桩号图层': '0-桩号',
        'files': [test_file]
    }
    
    try:
        engine_cad.run_autoclassify(params, log)
        log("[OK] autoclassify 测试完成")
        return True
    except Exception as e:
        log(f"[ERROR] autoclassify 测试失败: {e}")
        return False

def run_all_tests():
    """运行所有测试"""
    log("=" * 60)
    log("HydraulicCAD Engine v2.0 全功能测试")
    log("=" * 60)
    log(f"测试文件目录: {TEST_DIR}")
    log("")
    
    results = {
        'autoline': test_autoline(),
        'autopaste': test_autopaste(),
        'autohatch': test_autohatch(),
        'autoclassify': test_autoclassify(),
    }
    
    log("")
    log("=" * 60)
    log("测试结果汇总")
    log("=" * 60)
    
    passed = 0
    failed = 0
    
    for name, result in results.items():
        status = "✅ PASS" if result else "❌ FAIL"
        log(f"  {name}: {status}")
        if result:
            passed += 1
        else:
            failed += 1
    
    log("")
    log(f"总计: {passed} 通过, {failed} 失败")
    log("=" * 60)
    
    return failed == 0

if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)