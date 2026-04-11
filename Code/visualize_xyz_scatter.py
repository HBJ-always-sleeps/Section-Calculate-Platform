"""
可视化XYZ坐标散点图 - 验证X和Y坐标是否正确
"""
import matplotlib
matplotlib.use('Agg')  # 非交互后端，不显示窗口
import matplotlib.pyplot as plt
import numpy as np

# 设置中文字体
plt.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei']
plt.rcParams['axes.unicode_minus'] = False

def read_xyz_file(filepath):
    """读取XYZ文件 - 格式: x y z 每行三个数值"""
    points = []
    with open(filepath, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            # 直接用空格分割
            coords = line.split()
            if len(coords) >= 3:
                x = float(coords[0])
                y = float(coords[1])
                z = float(coords[2])
                points.append((x, y, z))
    return points

def read_centerline_file(filepath):
    """读取中心线文件"""
    points = []
    with open(filepath, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            parts = line.split()
            if len(parts) >= 5:
                x = float(parts[2])
                y = float(parts[3])
                z = float(parts[4])
                points.append((x, y, z))
    return points

# 读取数据
print("读取开挖线数据...")
excavation_points = read_xyz_file(r"D:\断面算量平台\测试文件\开挖线_xyz.txt")
print(f"  开挖线点数: {len(excavation_points)}")

print("读取超挖线数据...")
overbreak_points = read_xyz_file(r"D:\断面算量平台\测试文件\超挖线_xyz.txt")
print(f"  超挖线点数: {len(overbreak_points)}")

print("读取中心线数据...")
centerline_points = read_centerline_file(r"D:\断面算量平台\测试文件\中心线位置.txt")
print(f"  中心线点数: {len(centerline_points)}")

# 提取XY坐标
exc_x = [p[0] for p in excavation_points]
exc_y = [p[1] for p in excavation_points]
exc_z = [p[2] for p in excavation_points]

over_x = [p[0] for p in overbreak_points]
over_y = [p[1] for p in overbreak_points]
over_z = [p[2] for p in overbreak_points]

center_x = [p[0] for p in centerline_points]
center_y = [p[1] for p in centerline_points]

# 创建图形
fig, axes = plt.subplots(2, 2, figsize=(16, 14))

# 图1: XY平面散点图（俯视图）
ax1 = axes[0, 0]
ax1.scatter(exc_x, exc_y, c='red', s=2, alpha=0.6, label=f'开挖线 ({len(excavation_points)}点)')
ax1.scatter(over_x, over_y, c='blue', s=2, alpha=0.6, label=f'超挖线 ({len(overbreak_points)}点)')
ax1.plot(center_x, center_y, 'g-', linewidth=2, label=f'中心线 ({len(centerline_points)}点)')
ax1.set_xlabel('X坐标 (真实世界坐标)')
ax1.set_ylabel('Y坐标 (真实世界坐标)')
ax1.set_title('XY平面散点图（俯视图）')
ax1.legend()
ax1.grid(True, alpha=0.3)
ax1.set_aspect('equal')

# 输出坐标范围
print(f"\n坐标范围:")
print(f"  开挖线 X: {min(exc_x):.2f} ~ {max(exc_x):.2f}")
print(f"  开挖线 Y: {min(exc_y):.2f} ~ {max(exc_y):.2f}")
print(f"  超挖线 X: {min(over_x):.2f} ~ {max(over_x):.2f}")
print(f"  超挖线 Y: {min(over_y):.2f} ~ {max(over_y):.2f}")
print(f"  中心线 X: {min(center_x):.2f} ~ {max(center_x):.2f}")
print(f"  中心线 Y: {min(center_y):.2f} ~ {max(center_y):.2f}")

# 图2: XZ视图（侧面图）
ax2 = axes[0, 1]
ax2.scatter(exc_x, exc_z, c='red', s=2, alpha=0.6, label='开挖线')
ax2.scatter(over_x, over_z, c='blue', s=2, alpha=0.6, label='超挖线')
ax2.set_xlabel('X坐标')
ax2.set_ylabel('Z坐标 (高程)')
ax2.set_title('XZ视图（侧面图）')
ax2.legend()
ax2.grid(True, alpha=0.3)

# 图3: YZ视图（侧面图）
ax3 = axes[1, 0]
ax3.scatter(exc_y, exc_z, c='red', s=2, alpha=0.6, label='开挖线')
ax3.scatter(over_y, over_z, c='blue', s=2, alpha=0.6, label='超挖线')
ax3.set_xlabel('Y坐标')
ax3.set_ylabel('Z坐标 (高程)')
ax3.set_title('YZ视图（侧面图）')
ax3.legend()
ax3.grid(True, alpha=0.3)

# 图4: 高程分布统计
ax4 = axes[1, 1]
ax4.hist(exc_z, bins=50, color='red', alpha=0.6, label='开挖线高程分布')
ax4.hist(over_z, bins=50, color='blue', alpha=0.6, label='超挖线高程分布')
ax4.set_xlabel('Z坐标 (高程)')
ax4.set_ylabel('点数')
ax4.set_title('高程分布统计')
ax4.legend()
ax4.grid(True, alpha=0.3)

plt.tight_layout()

# 保存图片
output_path = r"D:\断面算量平台\测试文件\xyz_scatter_plot.png"
plt.savefig(output_path, dpi=150, bbox_inches='tight')
print(f"\n图片已保存: {output_path}")

# 不显示窗口，直接完成
# plt.show()

print("\n可视化完成！")
