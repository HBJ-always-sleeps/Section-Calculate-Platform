# -*- coding: utf-8 -*-
"""
外海XYZ提取整合脚本 - 一键运行完整流程

流程步骤:
1. 加载背景底图桩号位置（从外海背景.dxf）
2. 检测断面图开挖线和超挖线（从外海断面图.dxf）
3. 坐标转换（延长至0米高程）
4. 水平4米间隔插值生成XYZ点
5. 保存XYZ文件

作者: @黄秉俊
日期: 2026-04-16
"""

import os
import sys
import subprocess
import argparse
from datetime import datetime

# ==================== 脚本目录检测 ====================
if getattr(sys, 'frozen', False):
    SCRIPT_DIR = sys._MEIPASS
else:
    SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# ==================== 配置区域 ====================

DEFAULT_CONFIG = {
    # 输入文件
    'section_dxf': r'D:\断面算量平台\测试文件\外海断面图.dxf',
    'background_dxf': r'D:\断面算量平台\测试文件\外海背景.dxf',
    
    # 输出目录
    'output_dir': r'D:\断面算量平台\测试文件',
    
    # 比例尺参数
    'scale_x': 200.0,  # 水平比例尺: 1单位 = 200米
    'scale_y': 10.0,   # 垂直比例尺: 1单位 = 10米
    'elevation_ref': -12.0,  # 小框上长边高程基准
    'target_elevation': 0.0,  # 延长目标高程
    'interval_x': 4.0,  # 水平插值间隔
    
    # 输出文件名（与内湾格式一致）
    'excav_xyz': '外海_开挖线_xyz.txt',
    'overbreak_xyz': '外海_超挖线_xyz.txt',
    'centerline_txt': '外海_中心线位置.txt',
    'section_xyz_json': '外海_断面XYZ数据.json',
    'visualization_png': '外海_xyz_scatter_plot.png',
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
    """运行命令并返回是否成功"""
    if getattr(sys, 'frozen', False):
        python_exe = r'D:\DevTools\Python\pythoncore-3.14-64\python.exe'
        if cmd[0] == sys.executable:
            cmd[0] = python_exe
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


def step1_check_inputs(config: dict) -> bool:
    """步骤1: 检查输入文件"""
    print_step(1, 5, "检查输入文件")
    
    section_ok = check_file_exists(config['section_dxf'], "外海断面图DXF")
    background_ok = check_file_exists(config['background_dxf'], "外海背景DXF")
    
    return section_ok and background_ok


def step2_extract_xyz(config: dict) -> bool:
    """步骤2: 运行XYZ提取脚本"""
    print_step(2, 5, "运行XYZ提取 (extract_waihai_xyz_v2.py)")
    
    cmd = [sys.executable, 'extract_waihai_xyz_v2.py']
    success = run_command(cmd, "XYZ提取")
    
    return success


def step3_verify_outputs(config: dict) -> bool:
    """步骤3: 验证输出文件"""
    print_step(3, 5, "验证输出文件")
    
    files_to_check = [
        ('开挖线XYZ', os.path.join(config['output_dir'], config['excav_xyz'])),
        ('超挖线XYZ', os.path.join(config['output_dir'], config['overbreak_xyz'])),
        ('中心线位置', os.path.join(config['output_dir'], config['centerline_txt'])),
        ('断面XYZ数据JSON', os.path.join(config['output_dir'], config['section_xyz_json'])),
    ]
    
    all_ok = True
    for name, path in files_to_check:
        if not check_file_exists(path, name):
            all_ok = False
    
    return all_ok


def step4_show_summary(config: dict) -> bool:
    """步骤4: 显示结果摘要"""
    print_step(4, 5, "显示结果摘要")
    
    json_path = os.path.join(config['output_dir'], config['section_xyz_json'])
    
    if os.path.exists(json_path):
        import json
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        print(f"\n  比例尺参数:")
        print(f"    水平比例尺: 1单位 = {data.get('scale_x', 'N/A')}米")
        print(f"    垂直比例尺: 1单位 = {data.get('scale_y', 'N/A')}米")
        print(f"    小框上长边高程基准: {data.get('elevation_ref', 'N/A')}米")
        print(f"    延长目标高程: {data.get('target_elevation', 'N/A')}米")
        print(f"    水平插值间隔: {data.get('interval_x', 'N/A')}米")
        
        print(f"\n  输出统计:")
        print(f"    断面数: {len(data.get('sections', []))}个")
        print(f"    开挖线插值点数: {len(data.get('excav_points', []))}个")
        print(f"    超挖线插值点数: {len(data.get('overbreak_points', []))}个")
        
        # 计算总点数
        total_kaiwa = sum(len(s.get('kaiwa_xyz', [])) for s in data.get('sections', []))
        total_chaowa = sum(len(s.get('chaowa_xyz', [])) for s in data.get('sections', []))
        print(f"    总开挖线点数: {total_kaiwa}")
        print(f"    总超挖线点数: {total_chaowa}")
        
        print(f"\n  生成时间: {data.get('timestamp', 'N/A')}")
        
        return True
    else:
        print(f"[FAIL] 无法读取JSON文件")
        return False


def step5_visualize(config: dict) -> bool:
    """步骤5: 生成散点图可视化"""
    print_step(5, 6, "生成散点图可视化 (visualize_waihai_xyz_scatter.py)")
    
    # 检查输入文件
    excav_path = os.path.join(config['output_dir'], config['excav_xyz'])
    overbreak_path = os.path.join(config['output_dir'], config['overbreak_xyz'])
    centerline_path = os.path.join(config['output_dir'], config['centerline_txt'])
    
    if not check_file_exists(excav_path, "开挖线XYZ"):
        return False
    if not check_file_exists(overbreak_path, "超挖线XYZ"):
        return False
    if not check_file_exists(centerline_path, "中心线位置"):
        return False
    
    # 运行可视化脚本
    cmd = [sys.executable, 'visualize_waihai_xyz_scatter.py']
    success = run_command(cmd, "散点图可视化")
    
    # 验证输出
    output_path = os.path.join(config['output_dir'], config['visualization_png'])
    if success and check_file_exists(output_path, "可视化PNG"):
        return True
    return False


def step6_show_file_info(config: dict) -> bool:
    """步骤6: 显示文件信息"""
    print_step(6, 6, "显示文件信息")
    
    files_to_show = [
        ('开挖线XYZ', os.path.join(config['output_dir'], config['excav_xyz'])),
        ('超挖线XYZ', os.path.join(config['output_dir'], config['overbreak_xyz'])),
        ('中心线位置', os.path.join(config['output_dir'], config['centerline_txt'])),
        ('断面XYZ数据JSON', os.path.join(config['output_dir'], config['section_xyz_json'])),
        ('散点图PNG', os.path.join(config['output_dir'], config['visualization_png'])),
    ]
    
    print(f"\n  输出文件详情:")
    for name, path in files_to_show:
        if os.path.exists(path):
            size = os.path.getsize(path)
            mtime = datetime.fromtimestamp(os.path.getmtime(path)).strftime('%Y-%m-%d %H:%M:%S')
            print(f"    {name}:")
            print(f"      路径: {path}")
            print(f"      大小: {size:,} 字节")
            print(f"      修改时间: {mtime}")
    
    return True


def main():
    """主程序"""
    parser = argparse.ArgumentParser(
        description='外海XYZ提取整合脚本 - 一键运行完整流程',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python run_waihai_xyz_extraction.py                    # 运行全部步骤
  python run_waihai_xyz_extraction.py --check-only       # 只检查文件状态
  python run_waihai_xyz_extraction.py --interval 2       # 使用2米插值间隔
        """
    )
    
    parser.add_argument('--section-dxf', type=str, default=None,
                       help='外海断面图DXF路径')
    parser.add_argument('--background-dxf', type=str, default=None,
                       help='外海背景DXF路径')
    parser.add_argument('--output-dir', type=str, default=None,
                       help='输出目录')
    parser.add_argument('--interval', type=float, default=4.0,
                       help='水平插值间隔（米）')
    parser.add_argument('--check-only', action='store_true',
                       help='只检查文件状态，不执行')
    
    args = parser.parse_args()
    
    # 打印开始信息
    print_banner("外海XYZ提取整合脚本")
    print(f"开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # 构建配置
    config = DEFAULT_CONFIG.copy()
    if args.section_dxf:
        config['section_dxf'] = args.section_dxf
    if args.background_dxf:
        config['background_dxf'] = args.background_dxf
    if args.output_dir:
        config['output_dir'] = args.output_dir
    config['interval_x'] = args.interval
    
    # 打印配置
    print("\n配置信息:")
    print(f"  外海断面图: {config['section_dxf']}")
    print(f"  外海背景: {config['background_dxf']}")
    print(f"  输出目录: {config['output_dir']}")
    print(f"  水平插值间隔: {config['interval_x']}米")
    
    # 只检查模式
    if args.check_only:
        print("\n文件状态检查:")
        print("-" * 50)
        
        files_to_check = [
            ('外海断面图DXF', config['section_dxf']),
            ('外海背景DXF', config['background_dxf']),
            ('开挖线XYZ', os.path.join(config['output_dir'], config['excav_xyz'])),
            ('超挖线XYZ', os.path.join(config['output_dir'], config['overbreak_xyz'])),
            ('中心线位置', os.path.join(config['output_dir'], config['centerline_txt'])),
            ('断面XYZ数据JSON', os.path.join(config['output_dir'], config['section_xyz_json'])),
            ('散点图PNG', os.path.join(config['output_dir'], config['visualization_png'])),
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
    step_functions = [
        ('检查输入文件', step1_check_inputs),
        ('XYZ提取', step2_extract_xyz),
        ('验证输出', step3_verify_outputs),
        ('结果摘要', step4_show_summary),
        ('散点图可视化', step5_visualize),
        ('文件信息', step6_show_file_info),
    ]
    
    results = {}
    for step_num, (step_name, step_func) in enumerate(step_functions, 1):
        try:
            success = step_func(config)
            results[step_num] = success
            
            if not success and step_num <= 3:
                print(f"\n[FAIL] 步骤 {step_num} ({step_name}) 失败，终止执行")
                break
                
        except Exception as e:
            print(f"\n[FAIL] 步骤 {step_num} ({step_name}) 异常: {e}")
            import traceback
            traceback.print_exc()
            results[step_num] = False
            break
    
    # 打印结果汇总
    print_banner("执行结果汇总")
    print(f"结束时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    
    for step_num, (step_name, _) in enumerate(step_functions, 1):
        if step_num in results:
            status = "[OK] 成功" if results[step_num] else "[FAIL] 失败"
        else:
            status = "- 未执行"
        print(f"  步骤 {step_num} ({step_name}): {status}")
    
    # 统计
    success_count = sum(1 for v in results.values() if v)
    total_count = len(results)
    print(f"\n总计: {success_count}/{total_count} 步骤成功")
    
    if success_count == total_count and total_count == len(step_functions):
        print("\n[SUCCESS] 所有步骤执行成功！")
    else:
        print("\n[WARN] 部分步骤执行失败，请检查日志")


if __name__ == '__main__':
    main()