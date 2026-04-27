# -*- coding: utf-8 -*-
"""
XYZ提取整合脚本 - 一键运行完整流程

流程步骤:
1. 脊梁点提取 (extract_spine_points.py)
2. 断面元数据生成 (bim_model_builder.py)
3. 脊梁点匹配 (match_spine_to_sections.py)
4. XYZ提取 (extract_xyz_from_dxf.py)
5. 可视化验证 (visualize_xyz_scatter.py)

作者: @黄秉俊
日期: 2026-04-12
"""

import os
import sys
import subprocess
import argparse
from datetime import datetime

# ==================== 脚本目录检测 ====================
# 在打包环境中，使用打包后的内部目录
if getattr(sys, 'frozen', False):
    # 打包环境，使用sys._MEIPASS
    SCRIPT_DIR = sys._MEIPASS
else:
    # 开发环境，使用脚本所在目录
    SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# ==================== 配置区域 ====================

# 默认路径配置（可根据需要修改）
DEFAULT_CONFIG = {
    # 输入文件
    'neiwan_ditu_dxf': r'D:\断面算量平台\测试文件\内湾底图.dxf',
    'section_dxf': r'D:\断面算量平台\测试文件\内湾段分层图（全航道底图20260331）2018.dxf',
    
    # 输出目录
    'output_dir': r'D:\断面算量平台\测试文件',
    
    # 中间文件名
    'spine_points_json': '内湾底图_脊梁点.json',
    'bim_metadata_json': '内湾段分层图（全航道底图20260331）2018_bim_metadata.json',
    'spine_match_json': '脊梁点_L1匹配结果.json',
    
    # 最终输出文件名
    'kaiwa_xyz': '开挖线_xyz.txt',
    'chaowa_xyz': '超挖线_xyz.txt',
    'centerline_txt': '中心线位置.txt',
    'section_xyz_json': '断面XYZ数据.json',
    'visualization_png': 'xyz_scatter_plot.png',
}


def print_banner(title: str):
    """打印横幅标题"""
    width = 70
    print("\n" + "=" * width)
    print(f"  {title}")
    print("=" * width)


def print_step(step_num: int, total_steps: int, description: str):
    """打印步骤信息"""
    print(f"\n{'─' * 70}")
    print(f"  步骤 [{step_num}/{total_steps}] {description}")
    print(f"{'─' * 70}")


def run_command(cmd: list, description: str) -> bool:
    """
    运行命令并返回是否成功
    
    Args:
        cmd: 命令列表
        description: 步骤描述
    
    Returns:
        bool: 是否成功
    """
    # 在打包环境中，需要使用外部Python解释器
    if getattr(sys, 'frozen', False):
        # 打包环境，找到系统Python解释器
        python_exe = r'D:\DevTools\Python\pythoncore-3.14-64\python.exe'
        # 替换命令中的sys.executable
        if cmd[0] == sys.executable:
            cmd[0] = python_exe
        # 将脚本路径转换为绝对路径
        for i, arg in enumerate(cmd):
            if arg.endswith('.py') and not os.path.isabs(arg):
                cmd[i] = os.path.join(SCRIPT_DIR, arg)
    
    print(f"\n执行命令: {' '.join(cmd)}")
    print("-" * 50)
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=False,
            text=True,
            encoding='utf-8'
        )
        
        if result.returncode == 0:
            print(f"[OK] {description} 完成")
            return True
        else:
            print(f"[FAIL] {description} 失败 (返回码: {result.returncode})")
            return False
            
    except Exception as e:
        print(f"[FAIL] {description} 异常: {e}")
        return False


def check_file_exists(filepath: str, description: str) -> bool:
    """检查文件是否存在"""
    if os.path.exists(filepath):
        print(f"[OK] {description}: {filepath}")
        return True
    else:
        print(f"[FAIL] {description} 不存在: {filepath}")
        return False


def step1_extract_spine_points(config: dict) -> bool:
    """
    步骤1: 脊梁点提取
    
    从内湾底图提取脊梁点坐标
    """
    print_step(1, 5, "脊梁点提取 (extract_spine_points.py)")
    
    # 检查输入文件
    if not check_file_exists(config['neiwan_ditu_dxf'], "内湾底图DXF"):
        return False
    
    # 检查断面元数据是否存在（用于过滤桩号）
    bim_metadata_path = os.path.join(config['output_dir'], config['bim_metadata_json'])
    if not os.path.exists(bim_metadata_path):
        print(f"! 断面元数据不存在，将跳过桩号过滤: {bim_metadata_path}")
    
    # 运行脚本
    cmd = [sys.executable, 'extract_spine_points.py']
    success = run_command(cmd, "脊梁点提取")
    
    # 验证输出
    output_path = os.path.join(config['output_dir'], config['spine_points_json'])
    if success and check_file_exists(output_path, "脊梁点JSON"):
        return True
    return False


def step2_build_bim_metadata(config: dict) -> bool:
    """
    步骤2: 断面元数据生成
    
    从DXF断面图构建BIM元数据
    """
    print_step(2, 5, "断面元数据生成 (bim_model_builder.py)")
    
    # 检查输入文件
    if not check_file_exists(config['section_dxf'], "断面DXF"):
        return False
    
    # 构建命令
    output_path = os.path.join(config['output_dir'], config['bim_metadata_json'])
    cmd = [
        sys.executable, 
        'bim_model_builder.py',
        '--input', config['section_dxf'],
        '--output', output_path
    ]
    
    success = run_command(cmd, "断面元数据生成")
    
    # 验证输出
    if success and check_file_exists(output_path, "断面元数据JSON"):
        return True
    return False


def step3_match_spine_to_sections(config: dict) -> bool:
    """
    步骤3: 脊梁点匹配
    
    将脊梁点与断面L1基准点进行坐标匹配
    """
    print_step(3, 5, "脊梁点匹配 (match_spine_to_sections.py)")
    
    # 检查输入文件
    spine_json = os.path.join(config['output_dir'], config['spine_points_json'])
    bim_json = os.path.join(config['output_dir'], config['bim_metadata_json'])
    
    if not check_file_exists(spine_json, "脊梁点JSON"):
        return False
    if not check_file_exists(bim_json, "断面元数据JSON"):
        return False
    
    # 运行脚本
    cmd = [sys.executable, 'match_spine_to_sections.py']
    success = run_command(cmd, "脊梁点匹配")
    
    # 验证输出
    output_path = os.path.join(config['output_dir'], config['spine_match_json'])
    if success and check_file_exists(output_path, "匹配结果JSON"):
        return True
    return False


def step4_extract_xyz(config: dict) -> bool:
    """
    步骤4: XYZ提取
    
    从DXF提取开挖线和超挖线的XYZ坐标
    """
    print_step(4, 5, "XYZ提取 (extract_xyz_from_dxf.py)")
    
    # 检查输入文件
    if not check_file_exists(config['section_dxf'], "断面DXF"):
        return False
    
    spine_match_json = os.path.join(config['output_dir'], config['spine_match_json'])
    if not check_file_exists(spine_match_json, "脊梁点匹配结果JSON"):
        return False
    
    # 运行脚本
    cmd = [
        sys.executable, 'extract_xyz_from_dxf.py',
        '--input', config['section_dxf'],
        '--spine-match', spine_match_json,
        '--output-dir', config['output_dir']
    ]
    success = run_command(cmd, "XYZ提取")
    
    # 验证输出
    kaiwa_path = os.path.join(config['output_dir'], config['kaiwa_xyz'])
    chaowa_path = os.path.join(config['output_dir'], config['chaowa_xyz'])
    centerline_path = os.path.join(config['output_dir'], config['centerline_txt'])
    json_path = os.path.join(config['output_dir'], config['section_xyz_json'])
    
    outputs_ok = True
    if not check_file_exists(kaiwa_path, "开挖线XYZ"):
        outputs_ok = False
    if not check_file_exists(chaowa_path, "超挖线XYZ"):
        outputs_ok = False
    if not check_file_exists(centerline_path, "中心线位置"):
        outputs_ok = False
    if not check_file_exists(json_path, "断面XYZ数据JSON"):
        outputs_ok = False
    
    return success and outputs_ok


def step5_visualize(config: dict) -> bool:
    """
    步骤5: 可视化验证
    
    生成XYZ散点图验证坐标正确性
    """
    print_step(5, 5, "可视化验证 (visualize_xyz_scatter.py)")
    
    # 检查输入文件
    kaiwa_path = os.path.join(config['output_dir'], config['kaiwa_xyz'])
    chaowa_path = os.path.join(config['output_dir'], config['chaowa_xyz'])
    centerline_path = os.path.join(config['output_dir'], config['centerline_txt'])
    
    if not check_file_exists(kaiwa_path, "开挖线XYZ"):
        return False
    if not check_file_exists(chaowa_path, "超挖线XYZ"):
        return False
    if not check_file_exists(centerline_path, "中心线位置"):
        return False
    
    # 运行脚本
    cmd = [sys.executable, 'visualize_xyz_scatter.py']
    success = run_command(cmd, "可视化验证")
    
    # 验证输出
    output_path = os.path.join(config['output_dir'], config['visualization_png'])
    if success and check_file_exists(output_path, "可视化PNG"):
        return True
    return False


def main():
    """主程序"""
    parser = argparse.ArgumentParser(
        description='XYZ提取整合脚本 - 一键运行完整流程',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python run_xyz_extraction.py                    # 运行全部步骤
  python run_xyz_extraction.py --steps 1,2,3      # 只运行指定步骤
  python run_xyz_extraction.py --skip 5           # 跳过可视化步骤
  python run_xyz_extraction.py --check-only        # 只检查文件状态
        """
    )
    
    parser.add_argument('--steps', type=str, default='1,2,3,4,5',
                       help='指定运行的步骤，用逗号分隔 (默认: 1,2,3,4,5)')
    parser.add_argument('--skip', type=str, default='',
                       help='跳过的步骤，用逗号分隔 (例如: 5)')
    parser.add_argument('--check-only', action='store_true',
                       help='只检查文件状态，不执行')
    parser.add_argument('--neiwan-ditu', type=str, default=None,
                       help='内湾底图DXF路径')
    parser.add_argument('--section-dxf', type=str, default=None,
                       help='断面DXF路径')
    parser.add_argument('--output-dir', type=str, default=None,
                       help='输出目录')
    
    args = parser.parse_args()
    
    # 打印开始信息
    print_banner("XYZ提取整合脚本")
    print(f"开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # 构建配置
    config = DEFAULT_CONFIG.copy()
    if args.neiwan_ditu:
        config['neiwan_ditu_dxf'] = args.neiwan_ditu
    if args.section_dxf:
        config['section_dxf'] = args.section_dxf
    if args.output_dir:
        config['output_dir'] = args.output_dir
    
    # 打印配置
    print("\n配置信息:")
    print(f"  内湾底图: {config['neiwan_ditu_dxf']}")
    print(f"  断面DXF: {config['section_dxf']}")
    print(f"  输出目录: {config['output_dir']}")
    
    # 解析步骤
    all_steps = {1, 2, 3, 4, 5}
    run_steps = set(int(s.strip()) for s in args.steps.split(',') if s.strip().isdigit())
    skip_steps = set(int(s.strip()) for s in args.skip.split(',') if s.strip().isdigit())
    run_steps = run_steps - skip_steps
    
    # 步骤映射
    step_functions = {
        1: ('脊梁点提取', step1_extract_spine_points),
        2: ('断面元数据生成', step2_build_bim_metadata),
        3: ('脊梁点匹配', step3_match_spine_to_sections),
        4: ('XYZ提取', step4_extract_xyz),
        5: ('可视化验证', step5_visualize),
    }
    
    # 只检查模式
    if args.check_only:
        print("\n文件状态检查:")
        print("-" * 50)
        
        files_to_check = [
            ('内湾底图DXF', config['neiwan_ditu_dxf']),
            ('断面DXF', config['section_dxf']),
            ('脊梁点JSON', os.path.join(config['output_dir'], config['spine_points_json'])),
            ('断面元数据JSON', os.path.join(config['output_dir'], config['bim_metadata_json'])),
            ('匹配结果JSON', os.path.join(config['output_dir'], config['spine_match_json'])),
            ('开挖线XYZ', os.path.join(config['output_dir'], config['kaiwa_xyz'])),
            ('超挖线XYZ', os.path.join(config['output_dir'], config['chaowa_xyz'])),
            ('中心线位置', os.path.join(config['output_dir'], config['centerline_txt'])),
            ('断面XYZ数据', os.path.join(config['output_dir'], config['section_xyz_json'])),
            ('可视化PNG', os.path.join(config['output_dir'], config['visualization_png'])),
        ]
        
        for name, path in files_to_check:
            status = "[OK] 存在" if os.path.exists(path) else "[FAIL] 不存在"
            print(f"  {name}: {status}")
            if os.path.exists(path):
                size = os.path.getsize(path)
                mtime = datetime.fromtimestamp(os.path.getmtime(path)).strftime('%Y-%m-%d %H:%M:%S')
                print(f"      大小: {size:,} 字节, 修改时间: {mtime}")
        
        return
    
    # 执行步骤
    results = {}
    for step_num in sorted(run_steps):
        if step_num not in step_functions:
            print(f"[WARN] 跳过无效步骤: {step_num}")
            continue
        
        step_name, step_func = step_functions[step_num]
        try:
            success = step_func(config)
            results[step_num] = success
            
            if not success:
                print(f"\n[FAIL] 步骤 {step_num} ({step_name}) 失败，是否继续？")
                # 可以在这里添加用户确认逻辑
                
        except Exception as e:
            print(f"\n[FAIL] 步骤 {step_num} ({step_name}) 异常: {e}")
            import traceback
            traceback.print_exc()
            results[step_num] = False
    
    # 打印结果汇总
    print_banner("执行结果汇总")
    print(f"结束时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    
    for step_num in sorted(all_steps):
        step_name = step_functions[step_num][0]
        if step_num in skip_steps:
            status = "[SKIP] 跳过"
        elif step_num not in run_steps:
            status = "- 未执行"
        elif results.get(step_num, False):
            status = "[OK] 成功"
        else:
            status = "[FAIL] 失败"
        print(f"  步骤 {step_num} ({step_name}): {status}")
    
    # 统计
    success_count = sum(1 for v in results.values() if v)
    total_count = len(run_steps)
    print(f"\n总计: {success_count}/{total_count} 步骤成功")
    
    if success_count == total_count:
        print("\n[SUCCESS] 所有步骤执行成功！")
    else:
        print("\n[WARN] 部分步骤执行失败，请检查日志")


if __name__ == '__main__':
    main()