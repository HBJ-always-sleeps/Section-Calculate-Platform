"""
3D地质模型构建脚本 - 增强版
使用PyVista实现断面放样与交互式可视化
功能：
1. 图层分组复选框控制
2. Y轴滑动切片
3. 透明度差异化设置
4. 快捷键视角切换
"""
import json
import numpy as np
import pyvista as pv
from collections import defaultdict
import sys
import os
import io

# 设置控制台编码
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# ==================== 颜色与透明度配置 ====================

# 地质类型颜色映射
STRATA_COLORS = {
    # 砂类 - 黄色/橙色系（明亮，核心开挖层）
    "砂": "#FFD700",      # 金黄色
    "6级砂": "#FFD700",
    "7级砂": "#FFA500",   # 橙色
    "9级碎石": "#CD853F", # 秘鲁色
    
    # 淤泥类 - 灰色系（较软、待清理）
    "淤泥": "#696969",    # 暗灰色
    "1级淤泥": "#808080",
    "2级淤泥": "#909090",
    "3级淤泥": "#A0A0A0",
    
    # 黏土类 - 褐色系
    "黏土": "#8B4513",    # 马鞍棕
    "3级黏土": "#A0522D", # 赭色
    "4级黏土": "#8B4513",
    "5级黏土": "#6B3E26",
    
    # 填土 - 绿色
    "填土": "#228B22",
}

def get_layer_config(layer_name):
    """
    根据图层名称获取颜色和透明度配置
    设计图层：40% 透明度 (opacity=0.4)
    超挖图层：80% 不透明 (opacity=0.8)
    """
    # 确定颜色
    color = "#CCCCCC"  # 默认灰色
    for key, c in STRATA_COLORS.items():
        if key in layer_name:
            color = c
            break
    
    # 确定透明度
    if "超挖" in layer_name:
        opacity = 0.8  # 超挖区较不透明
    elif "设计" in layer_name:
        opacity = 0.4  # 设计区较透明
    else:
        opacity = 0.6  # 默认透明度
    
    return color, opacity

def get_layer_group(layer_name):
    """
    获取图层所属的地质分组
    """
    if "砂" in layer_name or "碎石" in layer_name:
        return "砂类"
    elif "淤泥" in layer_name:
        return "淤泥类"
    elif "黏土" in layer_name:
        return "黏土类"
    elif "填土" in layer_name:
        return "填土"
    else:
        return "其他"

# ==================== 几何处理函数 ====================

def resample_polygon(polygon, num_points=100):
    """
    对多边形进行等间距重采样
    """
    if len(polygon) < 3:
        return polygon
    
    points = np.array(polygon)
    diffs = np.diff(points, axis=0)
    segment_lengths = np.sqrt(np.sum(diffs**2, axis=1))
    cumulative_length = np.concatenate([[0], np.cumsum(segment_lengths)])
    total_length = cumulative_length[-1]
    
    if total_length < 1e-6:
        return polygon[:1] * num_points
    
    sample_distances = np.linspace(0, total_length, num_points, endpoint=False)
    
    resampled = []
    for dist in sample_distances:
        idx = np.searchsorted(cumulative_length, dist) - 1
        idx = max(0, min(idx, len(points) - 2))
        
        if idx < len(segment_lengths) and segment_lengths[idx] > 1e-6:
            t = (dist - cumulative_length[idx]) / segment_lengths[idx]
            t = max(0, min(1, t))
            new_point = points[idx] + t * (points[idx + 1] - points[idx])
        else:
            new_point = points[idx]
        
        resampled.append(tuple(new_point))
    
    return resampled

# 默认缩放因子（可通过命令行参数覆盖）
DEFAULT_X_SCALE = 1.0  # X轴（断面横向）缩放
DEFAULT_Y_SCALE = 1.0  # Y轴（里程轴）缩放  
DEFAULT_Z_SCALE = 1.0  # Z轴（高程）缩放

def polygon_to_3d(polygon, station_m, scale_x=1.0, scale_y=1.0, scale_z=1.0):
    """
    将2D多边形（归一化坐标）转换为3D坐标
    
    坐标映射：
    - 3D_X = x_rel * scale_x（断面内的横向相对位置）
    - 3D_Y = station_m * scale_y（里程轴）
    - 3D_Z = -y_rel * scale_z（高程，断面Y向上为正，3D中向下为正）
    
    参数：
    - scale_x: X轴缩放因子（断面横向）
    - scale_y: Y轴缩放因子（里程轴）
    - scale_z: Z轴缩放因子（高程）
    """
    points_3d = []
    for x_rel, y_rel in polygon:
        x_3d = x_rel * scale_x
        y_3d = station_m * scale_y
        z_3d = -y_rel * scale_z
        points_3d.append((x_3d, y_3d, z_3d))
    return points_3d

def create_loft_surface(polygons_3d_list, num_points=100, scale_x=1.0, scale_y=1.0, scale_z=1.0):
    """
    在多个断面之间创建放样表面
    
    参数：
    - polygons_3d_list: [(station_m, polygon_3d), ...]
    - num_points: 重采样点数
    - scale_x, scale_y, scale_z: 各轴缩放因子
    """
    if len(polygons_3d_list) < 2:
        return None
    
    resampled_list = []
    for station_m, polygon_3d in polygons_3d_list:
        polygon_2d = [(p[0], -p[2]) for p in polygon_3d]
        resampled_2d = resample_polygon(polygon_2d, num_points)
        resampled_3d = polygon_to_3d(resampled_2d, station_m, scale_x, scale_y, scale_z)
        resampled_list.append(resampled_3d)
    
    vertices = []
    faces = []
    
    n_stations = len(resampled_list)
    n_points_per_section = num_points
    
    for section in resampled_list:
        vertices.extend(section)
    
    vertices = np.array(vertices)
    
    for i in range(n_stations - 1):
        for j in range(n_points_per_section - 1):
            p0 = i * n_points_per_section + j
            p1 = i * n_points_per_section + (j + 1)
            p2 = (i + 1) * n_points_per_section + (j + 1)
            p3 = (i + 1) * n_points_per_section + j
            
            faces.extend([3, p0, p1, p2])
            faces.extend([3, p0, p2, p3])
    
    mesh = pv.PolyData(vertices, faces)
    return mesh

def compute_data_bounds(data):
    """
    计算数据的边界范围
    
    返回：(x_range, y_range, z_range) 各轴的范围
    """
    x_values = []
    y_values = []
    
    for section in data['sections'].values():
        if section.get('section_line'):
            for x, y in section['section_line']:
                x_values.append(x)
                y_values.append(y)
    
    if not x_values or not y_values:
        for section in data['sections'].values():
            for layer_polygons in section['layers'].values():
                for polygon in layer_polygons:
                    for x, y in polygon:
                        x_values.append(x)
                        y_values.append(y)
    
    if not x_values or not y_values:
        return 1.0, 1.0, 1.0
    
    x_range = max(x_values) - min(x_values) if x_values else 1.0
    y_range = max(y_values) - min(y_values) if y_values else 1.0
    
    # 里程轴范围
    stations = [sec['station_m'] for sec in data['sections'].values()]
    station_range = max(stations) - min(stations) if stations else 1.0
    
    print(f"\n数据边界范围:")
    print(f"  X轴（断面横向）: {x_range:.2f}")
    print(f"  Y轴（里程轴）: {station_range:.2f}")
    print(f"  Z轴（高程）: {y_range:.2f}")
    print(f"  原始比例 X:Z = {x_range/y_range:.2f}:1")
    
    return x_range, station_range, y_range


def compute_auto_scale(x_range, y_range, z_range, target_size=200):
    """
    计算自动缩放比例，使模型各方向尺寸相近
    
    参数：
    - x_range, y_range, z_range: 各轴的原始范围
    - target_size: 目标尺寸（默认200单位）
    
    返回：(scale_x, scale_y, scale_z)
    """
    # 避免除零
    x_range = max(x_range, 1e-6)
    y_range = max(y_range, 1e-6)
    z_range = max(z_range, 1e-6)
    
    # 计算各轴缩放因子，使所有方向都缩放到目标尺寸
    scale_x = target_size / x_range
    scale_y = target_size / y_range
    scale_z = target_size / z_range
    
    print(f"\n自动缩放计算:")
    print(f"  目标尺寸: {target_size}")
    print(f"  X缩放: {scale_x:.4f}")
    print(f"  Y缩放: {scale_y:.4f}")
    print(f"  Z缩放: {scale_z:.4f}")
    
    return scale_x, scale_y, scale_z

def create_3d_strata(json_file, scale_x=1.0, scale_y=1.0, scale_z=1.0, num_resample_points=100):
    """
    从JSON数据构建3D地质模型
    
    参数：
    - json_file: 输入JSON文件路径
    - scale_x: X轴缩放因子（断面横向）
    - scale_y: Y轴缩放因子（里程轴）
    - scale_z: Z轴缩放因子（高程）
    - num_resample_points: 多边形重采样点数
    """
    print(f"加载数据: {json_file}")
    with open(json_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    # 显示数据边界范围
    compute_data_bounds(data)
    
    print(f"\n缩放参数: X={scale_x}, Y={scale_y}, Z={scale_z}")
    
    all_layers = set()
    for sec in data['sections'].values():
        all_layers.update(sec['layers'].keys())
    
    print(f"\n发现 {len(all_layers)} 个地层图层:")
    for layer in sorted(all_layers):
        count = sum(1 for sec in data['sections'].values() if layer in sec['layers'])
        print(f"  - {layer}: {count} 个断面")
    
    stations = sorted(data['sections'].keys(), key=lambda x: data['sections'][x]['station_m'])
    print(f"\n开始构建3D模型，共 {len(stations)} 个断面...")
    
    meshes = {}
    
    for layer_name in all_layers:
        print(f"\n处理地层: {layer_name}")
        
        layer_polygons = []
        
        for station_str in stations:
            section = data['sections'][station_str]
            station_m = section['station_m']
            
            if layer_name in section['layers'] and section['layers'][layer_name]:
                polygon = section['layers'][layer_name][0]
                if len(polygon) >= 3:
                    polygon_3d = polygon_to_3d(polygon, station_m, scale_x, scale_y, scale_z)
                    layer_polygons.append((station_m, polygon_3d))
        
        if len(layer_polygons) >= 2:
            mesh = create_loft_surface(layer_polygons, num_resample_points, scale_x, scale_y, scale_z)
            if mesh is not None:
                meshes[layer_name] = mesh
                print(f"  [OK] 创建成功，顶点数: {mesh.n_points}, 面片数: {mesh.n_cells}")
            else:
                print(f"  [FAIL] 创建失败")
        else:
            print(f"  - 跳过（断面数不足）")
    
    return meshes, data

# ==================== 增强版可视化 ====================

class InteractiveGeologicalViewer:
    """
    交互式3D地质模型查看器
    """
    
    def __init__(self, meshes, data=None, scale_x=1.0, scale_y=1.0, scale_z=1.0):
        self.meshes = meshes
        self.data = data
        self.actors = {}
        self.layer_visibility = {}
        self.group_visibility = {
            "砂类": True,
            "淤泥类": True,
            "黏土类": True,
            "填土": True,
            "其他": True
        }
        
        # 缩放因子
        self.scale_x = scale_x
        self.scale_y = scale_y
        self.scale_z = scale_z
        
        # 保存原始多边形数据用于重建网格
        self.original_polygons = {}  # {layer_name: [(station_m, polygon_2d), ...]}
        self.num_resample_points = 80
        
        # 从data中提取原始多边形数据
        if data:
            self._extract_original_polygons(data)
        
        # 计算模型边界
        self.compute_bounds()
    
    def _extract_original_polygons(self, data):
        """从原始数据中提取多边形，用于后续重建"""
        stations = sorted(data['sections'].keys(), key=lambda x: data['sections'][x]['station_m'])
        
        for station_str in stations:
            section = data['sections'][station_str]
            station_m = section['station_m']
            
            for layer_name, layer_polygons in section['layers'].items():
                if layer_name not in self.original_polygons:
                    self.original_polygons[layer_name] = []
                
                if layer_polygons and len(layer_polygons[0]) >= 3:
                    self.original_polygons[layer_name].append((station_m, layer_polygons[0]))
    
    def _init_plotter(self):
        """初始化PyVista Plotter"""
        self.plotter = pv.Plotter(
            title="航道断面3D地质模型 - 交互式查看器",
            shape=(1, 1),
            border=False
        )
        
        # 切片平面状态
        self.clipping_enabled = False
        self.clip_position = (self.y_min + self.y_max) / 2
        
    def compute_bounds(self):
        """计算模型的边界范围"""
        all_points = []
        for mesh in self.meshes.values():
            all_points.append(mesh.points)
        
        if all_points:
            combined = np.vstack(all_points)
            self.x_min, self.x_max = combined[:, 0].min(), combined[:, 0].max()
            self.y_min, self.y_max = combined[:, 1].min(), combined[:, 1].max()
            self.z_min, self.z_max = combined[:, 2].min(), combined[:, 2].max()
        else:
            self.x_min = self.x_max = 0
            self.y_min = self.y_max = 0
            self.z_min = self.z_max = 0
    
    def setup_scene(self):
        """设置场景"""
        # 添加坐标轴
        self.plotter.add_axes()
        self.plotter.show_grid()
        
        # 添加所有地层网格
        self._add_all_meshes()
        
        # 设置背景
        self.plotter.set_background('white', top='lightblue')
        
    def _add_all_meshes(self):
        """添加所有地层网格"""
        for layer_name, mesh in self.meshes.items():
            color, opacity = get_layer_config(layer_name)
            group = get_layer_group(layer_name)
            
            actor = self.plotter.add_mesh(
                mesh,
                name=layer_name,
                color=color,
                opacity=opacity,
                show_edges=True,
                edge_color='darkgray',
                line_width=0.3,
                lighting=True,
                smooth_shading=True
            )
            
            self.actors[layer_name] = {
                'actor': actor,
                'group': group,
                'color': color,
                'opacity': opacity
            }
            self.layer_visibility[layer_name] = True
    
    def toggle_group(self, group_name, state):
        """切换整个分组的可见性"""
        self.group_visibility[group_name] = state
        
        for layer_name, info in self.actors.items():
            if info['group'] == group_name:
                info['actor'].SetVisibility(state)
                self.layer_visibility[layer_name] = state
        
        self.plotter.render()
        print(f"[图层控制] {group_name}: {'显示' if state else '隐藏'}")
    
    def toggle_layer(self, layer_name, state):
        """切换单个图层的可见性"""
        if layer_name in self.actors:
            self.actors[layer_name]['actor'].SetVisibility(state)
            self.layer_visibility[layer_name] = state
            self.plotter.render()
            print(f"[图层控制] {layer_name}: {'显示' if state else '隐藏'}")
    
    def set_top_view(self):
        """设置为俯视图"""
        self.plotter.view_xy()
        self.plotter.camera.zoom(0.8)
        self.plotter.add_text("视角: 航道俯视图", position='upper_left', font_size=10)
        self.plotter.render()
        print("[视角] 已切换为航道俯视图")
    
    def set_side_view(self):
        """设置为侧向纵剖图"""
        self.plotter.view_xz()
        self.plotter.camera.zoom(0.8)
        self.plotter.add_text("视角: 侧向纵剖图", position='upper_left', font_size=10)
        self.plotter.render()
        print("[视角] 已切换为侧向纵剖图")
    
    def set_front_view(self):
        """设置为正向断面图"""
        self.plotter.view_yz()
        self.plotter.camera.zoom(0.8)
        self.plotter.add_text("视角: 正向断面图", position='upper_left', font_size=10)
        self.plotter.render()
        print("[视角] 已切换为正向断面图")
    
    def reset_view(self):
        """重置视角"""
        self.plotter.camera_position = 'isometric'
        self.plotter.reset_camera()
        self.plotter.render()
        print("[视角] 已重置为等轴测视图")
    
    def update_clip_position(self, value):
        """更新切片位置"""
        self.clip_position = value
        
        # 更新所有网格的裁剪
        for layer_name, info in self.actors.items():
            mesh = self.meshes[layer_name]
            if self.clipping_enabled:
                clipped = mesh.clip(normal=(0, 1, 0), origin=(0, value, 0))
                # 更新actor显示裁剪后的网格
                # 注意：PyVista需要重新添加mesh来更新显示
    
    def enable_clipping(self, enable=True):
        """启用/禁用切片"""
        self.clipping_enabled = enable
        if enable:
            self.plotter.add_mesh_clip_box(
                list(self.meshes.values())[0],  # 参考网格
                normal=(0, 1, 0),
                origin=(0, self.clip_position, 0),
                color='red',
                opacity=0.3
            )
        self.plotter.render()
        print(f"[切片] {'启用' if enable else '禁用'}Y轴切片")
    
    def show(self):
        """显示交互窗口"""
        # 初始化Plotter
        self._init_plotter()
        
        self.setup_scene()
        
        # 创建UI面板
        self._create_ui_panel()
        
        # 绑定快捷键
        self._bind_shortcuts()
        
        # 打印操作说明
        self._print_instructions()
        
        # 显示窗口
        self.plotter.show()
    
    def _create_ui_panel(self):
        """创建UI控制面板"""
        # 创建分组复选框
        y_offset = 0.95
        
        # 标题
        self.plotter.add_text("图层控制", position=(0.02, y_offset), font_size=12, color='black')
        y_offset -= 0.05
        
        # 地质分组复选框
        groups = ["砂类", "淤泥类", "黏土类", "填土"]
        group_colors = {
            "砂类": "#FFD700",
            "淤泥类": "#808080",
            "黏土类": "#8B4513",
            "填土": "#228B22"
        }
        
        for group in groups:
            # 创建回调函数
            def make_callback(g):
                return lambda state: self.toggle_group(g, state)
            
            self.plotter.add_checkbox_button_widget(
                make_callback(group),
                value=True,
                position=(0.02, y_offset),
                size=20,
                border_size=2,
                color_on=group_colors.get(group, 'gray'),
                color_off='white'
            )
            
            self.plotter.add_text(
                group,
                position=(0.05, y_offset),
                font_size=10,
                color='black'
            )
            
            y_offset -= 0.04
        
        # 添加轴缩放滑块
        self._add_scale_sliders()
    
    def _add_scale_sliders(self):
        """添加轴缩放滑块"""
        # X轴缩放滑块（范围0.1-100）
        self.plotter.add_slider_widget(
            callback=self._update_x_scale,
            rng=[0.1, 100.0],
            value=self.scale_x,
            title="X轴缩放",
            pointa=(0.02, 0.15),
            pointb=(0.25, 0.15),
            style='modern',
            title_height=0.02
        )
        
        # Y轴缩放滑块（范围0.001-2.0，用于里程轴压缩/拉伸）
        self.plotter.add_slider_widget(
            callback=self._update_y_scale,
            rng=[0.001, 2.0],
            value=self.scale_y,
            title="Y轴缩放",
            pointa=(0.02, 0.10),
            pointb=(0.25, 0.10),
            style='modern',
            title_height=0.02
        )
        
        # Z轴缩放滑块（范围0.1-20）
        self.plotter.add_slider_widget(
            callback=self._update_z_scale,
            rng=[0.1, 20.0],
            value=self.scale_z,
            title="Z轴缩放",
            pointa=(0.02, 0.05),
            pointb=(0.25, 0.05),
            style='modern',
            title_height=0.02
        )
    
    def _update_x_scale(self, value):
        """更新X轴缩放"""
        self.scale_x = value
        self._refresh_meshes()
    
    def _update_y_scale(self, value):
        """更新Y轴缩放"""
        self.scale_y = value
        self._refresh_meshes()
    
    def _update_z_scale(self, value):
        """更新Z轴缩放"""
        self.scale_z = value
        self._refresh_meshes()
    
    def _refresh_meshes(self):
        """刷新所有网格（重新应用缩放）"""
        print(f"\n重建网格: X={self.scale_x:.2f}, Y={self.scale_y:.2f}, Z={self.scale_z:.2f}")
        
        # 保存当前相机的方向向量
        old_cam = self.plotter.camera
        old_position = np.array(old_cam.position)
        old_focal = np.array(old_cam.focal_point)
        old_view_dir = old_position - old_focal
        old_distance = np.linalg.norm(old_view_dir)
        old_view_dir_normalized = old_view_dir / old_distance if old_distance > 0 else np.array([1, 0, 0])
        
        # 清除现有的actors
        for layer_name in list(self.actors.keys()):
            self.plotter.remove_actor(layer_name)
        self.actors.clear()
        
        # 使用新的缩放参数重新构建网格
        for layer_name, polygons_data in self.original_polygons.items():
            if len(polygons_data) >= 2:
                # 重新转换3D坐标并创建放样网格
                new_mesh = self._create_scaled_mesh(polygons_data)
                if new_mesh is not None:
                    color, opacity = get_layer_config(layer_name)
                    group = get_layer_group(layer_name)
                    
                    actor = self.plotter.add_mesh(
                        new_mesh,
                        name=layer_name,
                        color=color,
                        opacity=opacity,
                        show_edges=True,
                        edge_color='darkgray',
                        line_width=0.3,
                        lighting=True,
                        smooth_shading=True
                    )
                    
                    self.actors[layer_name] = {
                        'actor': actor,
                        'group': group,
                        'color': color,
                        'opacity': opacity
                    }
                    self.meshes[layer_name] = new_mesh
        
        # 更新边界
        self.compute_bounds()
        
        # 计算新的模型中心
        new_center = np.array([
            (self.x_min + self.x_max) / 2,
            (self.y_min + self.y_max) / 2,
            (self.z_min + self.z_max) / 2
        ])
        
        # 计算新的模型尺寸
        model_size = max(
            self.x_max - self.x_min,
            self.y_max - self.y_min,
            self.z_max - self.z_min
        )
        
        # 设置新的相机位置：保持视角方向，但聚焦到新的模型中心
        # 距离按模型尺寸比例调整
        new_distance = max(old_distance, model_size * 2)
        new_position = new_center + old_view_dir_normalized * new_distance
        
        self.plotter.camera.position = new_position
        self.plotter.camera.focal_point = new_center
        
        self.plotter.render()
        print(f"网格重建完成 (Y范围: {self.y_min:.1f} ~ {self.y_max:.1f}, 长度: {self.y_max - self.y_min:.1f})")
    
    def _create_scaled_mesh(self, polygons_data):
        """根据当前缩放参数创建单个地层网格"""
        # polygons_data: [(station_m, polygon_2d), ...]
        resampled_list = []
        
        for station_m, polygon_2d in polygons_data:
            if len(polygon_2d) < 3:
                continue
            # 重采样多边形
            resampled_2d = resample_polygon(polygon_2d, self.num_resample_points)
            # 转换为3D坐标（应用缩放）
            resampled_3d = polygon_to_3d(resampled_2d, station_m, 
                                         self.scale_x, self.scale_y, self.scale_z)
            resampled_list.append(resampled_3d)
        
        if len(resampled_list) < 2:
            return None
        
        # 构建网格
        vertices = []
        faces = []
        n_stations = len(resampled_list)
        n_points = self.num_resample_points
        
        for section in resampled_list:
            vertices.extend(section)
        
        vertices = np.array(vertices)
        
        for i in range(n_stations - 1):
            for j in range(n_points - 1):
                p0 = i * n_points + j
                p1 = i * n_points + (j + 1)
                p2 = (i + 1) * n_points + (j + 1)
                p3 = (i + 1) * n_points + j
                
                faces.extend([3, p0, p1, p2])
                faces.extend([3, p0, p2, p3])
        
        return pv.PolyData(vertices, faces)
    
    def _bind_shortcuts(self):
        """绑定快捷键"""
        # 视角快捷键
        self.plotter.add_key_event('t', self.set_top_view)       # Top view
        self.plotter.add_key_event('s', self.set_side_view)      # Side view
        self.plotter.add_key_event('f', self.set_front_view)     # Front view
        self.plotter.add_key_event('r', self.reset_view)         # Reset
        
        # 图层控制快捷键
        self.plotter.add_key_event('1', lambda: self.toggle_group("砂类", not self.group_visibility["砂类"]))
        self.plotter.add_key_event('2', lambda: self.toggle_group("淤泥类", not self.group_visibility["淤泥类"]))
        self.plotter.add_key_event('3', lambda: self.toggle_group("黏土类", not self.group_visibility["黏土类"]))
        self.plotter.add_key_event('4', lambda: self.toggle_group("填土", not self.group_visibility["填土"]))
    
    def _print_instructions(self):
        """打印操作说明"""
        print("\n" + "="*60)
        print("     航道断面3D地质模型 - 交互操作说明")
        print("="*60)
        print("\n【鼠标操作】")
        print("  左键拖动  - 旋转视角")
        print("  右键拖动  - 缩放")
        print("  中键拖动  - 平移")
        print("  滚轮      - 缩放")
        print("\n【视角快捷键】")
        print("  T - 航道俯视图（从上往下看）")
        print("  S - 侧向纵剖图（从侧面看）")
        print("  F - 正向断面图（从正面看）")
        print("  R - 重置为等轴测视图")
        print("\n【图层控制】")
        print("  1 - 切换砂类图层")
        print("  2 - 切换淤泥类图层")
        print("  3 - 切换黏土类图层")
        print("  4 - 切换填土图层")
        print("\n【其他】")
        print("  Q - 退出")
        print("="*60 + "\n")

def visualize_model_enhanced(meshes, data=None, scale_x=1.0, scale_y=1.0, scale_z=1.0):
    """
    增强版可视化入口
    """
    viewer = InteractiveGeologicalViewer(meshes, data, scale_x, scale_y, scale_z)
    viewer.show()
    return viewer

# ==================== 导出功能 ====================

def export_to_obj(meshes, output_dir):
    """
    导出模型为多种格式
    """
    import os
    os.makedirs(output_dir, exist_ok=True)
    
    # 创建图层ID映射
    layer_id_map = {}
    layer_info = {}
    for i, layer_name in enumerate(meshes.keys()):
        layer_id_map[layer_name] = i
        color, opacity = get_layer_config(layer_name)
        layer_info[layer_name] = {
            'id': i,
            'color': color,
            'opacity': opacity,
            'group': get_layer_group(layer_name)
        }
    
    # 保存图层信息到JSON
    info_path = os.path.join(output_dir, "layer_info.json")
    with open(info_path, 'w', encoding='utf-8') as f:
        json.dump(layer_info, f, ensure_ascii=False, indent=2)
    print(f"图层信息: {info_path}")
    
    # 合并所有网格
    combined_mesh = None
    for layer_name, mesh in meshes.items():
        mesh.cell_data['layer_id'] = [layer_id_map[layer_name]] * mesh.n_cells
        
        if combined_mesh is None:
            combined_mesh = mesh
        else:
            combined_mesh = combined_mesh.merge(mesh)
    
    # 导出各种格式
    obj_path = os.path.join(output_dir, "geological_model.obj")
    combined_mesh.save(obj_path)
    print(f"\n模型已导出: {obj_path}")
    
    vtk_path = os.path.join(output_dir, "geological_model.vtk")
    combined_mesh.save(vtk_path)
    print(f"VTK格式: {vtk_path}")
    
    ply_path = os.path.join(output_dir, "geological_model.ply")
    combined_mesh.save(ply_path)
    print(f"PLY格式: {ply_path}")
    
    return obj_path

# ==================== 主程序 ====================

def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='3D地质模型构建 - 增强版')
    parser.add_argument('--no-viz', action='store_true', help='不显示可视化窗口')
    parser.add_argument('--json', type=str, 
                        default=r"D:\tunnel_build\测试文件\断面3D数据_归一化.json",
                        help='输入JSON文件')
    parser.add_argument('--output', type=str,
                        default=r"D:\tunnel_build\测试文件\3D_Model_Output",
                        help='输出目录')
    parser.add_argument('--auto-scale', action='store_true',
                        help='自动计算缩放比例使模型各方向尺寸相近')
    parser.add_argument('--target-size', type=float, default=200,
                        help='自动缩放的目标尺寸，默认200')
    # 三轴缩放参数（手动模式时使用）
    parser.add_argument('--sx', type=float, default=1.0,
                        help='X轴缩放因子（断面横向），默认1.0')
    parser.add_argument('--sy', type=float, default=1.0,
                        help='Y轴缩放因子（里程轴），默认1.0')
    parser.add_argument('--sz', type=float, default=1.0,
                        help='Z轴缩放因子（高程），默认1.0')
    args = parser.parse_args()
    
    # 先加载数据获取边界信息
    print(f"加载数据: {args.json}")
    with open(args.json, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    x_range, y_range, z_range = compute_data_bounds(data)
    
    # 计算缩放参数
    if args.auto_scale:
        scale_x, scale_y, scale_z = compute_auto_scale(x_range, y_range, z_range, args.target_size)
    else:
        scale_x, scale_y, scale_z = args.sx, args.sy, args.sz
        print(f"\n缩放参数: X={scale_x}, Y={scale_y}, Z={scale_z}")
    
    # 构建3D模型（使用已加载的data）
    meshes = {}
    all_layers = set()
    for sec in data['sections'].values():
        all_layers.update(sec['layers'].keys())
    
    print(f"\n发现 {len(all_layers)} 个地层图层:")
    for layer in sorted(all_layers):
        count = sum(1 for sec in data['sections'].values() if layer in sec['layers'])
        print(f"  - {layer}: {count} 个断面")
    
    stations = sorted(data['sections'].keys(), key=lambda x: data['sections'][x]['station_m'])
    print(f"\n开始构建3D模型，共 {len(stations)} 个断面...")
    
    for layer_name in all_layers:
        print(f"\n处理地层: {layer_name}")
        
        layer_polygons = []
        
        for station_str in stations:
            section = data['sections'][station_str]
            station_m = section['station_m']
            
            if layer_name in section['layers'] and section['layers'][layer_name]:
                polygon = section['layers'][layer_name][0]
                if len(polygon) >= 3:
                    polygon_3d = polygon_to_3d(polygon, station_m, scale_x, scale_y, scale_z)
                    layer_polygons.append((station_m, polygon_3d))
        
        if len(layer_polygons) >= 2:
            mesh = create_loft_surface(layer_polygons, 80, scale_x, scale_y, scale_z)
            if mesh is not None:
                meshes[layer_name] = mesh
                print(f"  [OK] 创建成功，顶点数: {mesh.n_points}, 面片数: {mesh.n_cells}")
            else:
                print(f"  [FAIL] 创建失败")
        else:
            print(f"  - 跳过（断面数不足）")
    
    print(f"\n共生成 {len(meshes)} 个地层网格")
    
    # 统计信息
    total_vertices = sum(m.n_points for m in meshes.values())
    total_faces = sum(m.n_cells for m in meshes.values())
    print(f"总顶点数: {total_vertices}")
    print(f"总面片数: {total_faces}")
    
    # 按分组统计
    group_stats = defaultdict(lambda: {'count': 0, 'vertices': 0})
    for layer_name, mesh in meshes.items():
        group = get_layer_group(layer_name)
        group_stats[group]['count'] += 1
        group_stats[group]['vertices'] += mesh.n_points
    
    print("\n分组统计:")
    for group, stats in group_stats.items():
        print(f"  {group}: {stats['count']} 个图层, {stats['vertices']} 个顶点")
    
    # 导出模型
    export_to_obj(meshes, args.output)
    
    # 可视化
    if not args.no_viz:
        print("\n启动增强版3D可视化窗口...")
        visualize_model_enhanced(meshes, data, scale_x, scale_y, scale_z)
    else:
        print("\n导出完成，跳过可视化")

if __name__ == '__main__':
    main()