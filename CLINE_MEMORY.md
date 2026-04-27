# Cline Tiered Memory

## [L1] Core Mission (STRICT)
- [x] 目标: 航道断面算量自动化平台 - DXF断面图处理与面积计算
- [x] 架构: Python主程序 + C++/Qt重构版 + 3D地质模型构建器
- [x] 新目标: 将Online3DViewer转化为本地桌面应用程序（OBJ+DXF文件加载渲染） - 已完成打包
- [x] V18地质模型: 回淤图层 + 平滑处理 + Z值约束 + 实心深黄色显示

## [L2] Hard-won Knowledge (ADAPTIVE)

### 核心坑点与解决方案

#### 1. ARC方向反转问题 (2026-04-13)
**问题**: `explode()`分解LWPOLYLINE后，ARC实体的start/end点与多段线顶点顺序相反，导致中心线不连续（出现800m级跳跃）。

**解决**: 在`get_centerline_points()`中实现自动方向校正：
```python
# 检查与前一个实体的连续性
if prev_end is not None:
    dist_start = distance(arc_start, prev_end)
    dist_end = distance(arc_end, prev_end)
    if dist_end < dist_start:
        arc_pts = arc_pts[::-1]  # 反转ARC点序
```

**关键代码**: [`extract_spine_points.py`](extract_spine_points.py:36) 第36-109行

#### 2. 桩号匹配数据源问题
**问题**: 使用错误的比例0.6元数据导致K68-K70区间数据缺失。

**解决**: 统一使用比例为1的元数据文件：
- 正确: `...2018_bim_metadata.json`
- 错误: `...面积比例0.6_bim_metadata.json`

#### 3. 中心线提取精度
**参数**: `sagitta=0.1` 提供足够精度（原1.0太粗糙）
**方法**: `flattening(sagitta)` 将ARC离散为线段序列

#### 4. 坐标系转换
- **工程坐标**: CGCS2000 (~505300, ~2374800)
- **CAD局部坐标**: 相对于L1基准点 (~-1000~1100, ~2500)
- **转换公式**: `eng = spine + dx * (cosθ, sinθ)`

#### 5. 文件路径规范
```
测试文件目录: D:\断面算量平台\测试文件\
核心脚本目录: D:\断面算量平台\Code\
```

### 关键脚本速查

| 脚本 | 功能 | 输入 | 输出 |
|------|------|------|------|
| `extract_spine_points.py` | 脊梁点提取 | 内湾底图.dxf | 内湾底图_脊梁点.json (245个) |
| `bim_model_builder.py` | 断面元数据 | 断面图.dxf | *_bim_metadata.json (245个) |
| `match_spine_to_sections.py` | 脊梁点匹配 | 上述两者JSON | 脊梁点_L1匹配结果.json |
| `extract_xyz_from_dxf.py` | XYZ提取 | 断面图.dxf + 匹配结果 | 开挖线_xyz.txt, 超挖线_xyz.txt |
| `run_xyz_extraction.py` | 一键运行 | - | 完整流程 |

### 数据结构速查

**脊梁点JSON**:
```json
{
  "spine_points": [{
    "station_name": "K67+400",
    "station_value": 67400,
    "x": 505299.90, "y": 2374797.30,
    "tangent_angle": 1.23
  }]
}
```

**断面元数据JSON**:
```json
{
  "sections": [{
    "station_value": 67400,
    "bounds": {"x_min": -1000, "x_max": 1100, ...},
    "l1_ref_point": {"x": -986.92, "y": 2510.86}
  }]
}
```

### 统计数据
- 断面数量: 245个 (K67+400 ~ K73+500)
- 桩号间隔: 25m
- 开挖线点: 2838个
- 超挖线点: 3124个
- 坐标范围: X[505261, 509486], Y[2374778, 2379130], Z[-20, 0]

#### 6. Electron打包坑点 (2026-04-13)
**问题1**: `electron`必须放在`devDependencies`而非`dependencies`
- electron-builder报错: `Package "electron" is only allowed in "devDependencies"`

**问题2**: winCodeSign解压失败 - 符号链接权限不足
- 错误: `ERROR: Cannot create symbolic link : 客户端没有所需的特权`
- 原因: Windows创建符号链接需要管理员权限或开发者模式
- 解决: 使用`--dir`参数生成解压即用版本，手动压缩为便携版zip

**打包命令**:

#### 7. 外海断面XYZ提取坐标转换问题 (2026-04-17)
**问题**: 散点图和DXF调试文件坐标完全不一致，差异达数百米。

**根本原因**: 三处关键错误：
1. **符号反转**: `dx_cad = center_line_x - local_x`（错误）vs `dx_cad = local_x - center_line_x`（正确）
2. **脊梁点坐标错误**: 中心线位置文件保存`left_top`坐标而非脊梁点世界坐标
3. **插值点Y坐标固定**: 使用固定Y坐标而非根据X坐标和方向向量动态计算

**修复方案**:
```python
# 1. 修复符号（extract_waihai_xyz_v2.py 第533-536行）
dx_cad = local_x - center_line_x  # 与export_debug_to_world_coords.py一致

# 2. 修复脊梁点保存（第900-908行）
spine_x = e['spine_world']['x']  # 使用脊梁点坐标
spine_y = e['spine_world']['y']

# 3. 修复插值点Y坐标（第754-810行）
if abs(cos_a) > 0.001:
    dx_scaled = (x - spine_x) / cos_a
    y = spine_y + dx_scaled * sin_a  # 动态计算
```

**验证结果**: 18+300断面DXF和XYZ坐标差异<5米，匹配成功。

#### 8. 外海完整版断面图高程和底边插值问题 (2026-04-17)
**问题**: XYZ输出显示错误分布(16.8%:83.2%)，但CAD坐标和坐标转换公式都正确(50.0%:50.0%)

**根因**: 分析脚本 `compare_neiwan_waihai_section.py` 使用的是基于X坐标范围的比例计算（中心线在X范围中的位置），而不是真正的左右点数统计。

**验证**: 使用 `analyze_xyz_distribution.py` 统计每个断面的左右点数，结果显示每个断面都是50.0% : 50.0%分布。

**结论**: XYZ数据正确，问题在于分析方法。正确的分析方法应该是：
- 将XYZ点分配到最近的断面（基于中心线距离）
- 统计每个断面中 X < 中心线X 的点数（左侧）和 X >= 中心线X 的点数（右侧）
**问题**: XYZ文件显示高程为正值（19.40m），底边插值点缺失（z≈-24m点数为0）。

**根本原因**: 四处关键错误：
1. **高程输出取负**: `write_xyz_file`函数对z值取负输出（内湾遗留问题）
2. **过滤条件错误**: `z >= 0`过滤掉上边点，`z < -20`过滤掉下边点
3. **延长点存储错误**: 延长到-24m的点被错误存储为`left_top/right_top`而非`left_bottom/right_bottom`
4. **高程基准错误**: ELEVATION_REF应为0.0（上长边），而非-12.0

**修复方案**:
```python
# 1. 修复高程输出（write_xyz_file函数）
f.write(f"{p['x']:.6f} {p['y']:.6f} {z:.6f}\n")  # 不取负

# 2. 修复过滤条件
if z > 5 or z < -30:  # 放宽范围，允许-24m点

# 3. 修复延长点存储（开挖线和超挖线）
'left_bottom': {
    'x': left_ext_x if left_ext_x is not None else left_bottom_x,
    'z': left_ext_z if left_ext_z is not None else left_bottom_z  # 延长点作为底部
}

# 4. 修复高程基准
ELEVATION_REF = 0.0  # 小框上长边对应0米
TARGET_ELEVATION = -24.0  # 延长目标高程
```

**验证结果**:
- 高程范围: -24.00m ~ 0.00m（正确）
- 底边点数: 3591个（z≈-24m）
- 开挖线总点数: 12447个
- 超挖线总点数: 12753个

**外海完整版数据统计**:
- 断面数量: 295个 (0+000 ~ 29+300)
- 桩号间隔: 100m
- 开挖线点: 12447个
- 超挖线点: 12753个
- 脊梁点: 295个
- 高程范围: -24m ~ 0m

**关键脚本**:
- `extract_waihai_xyz_v2.py` - 外海断面XYZ提取（已修复）
- `export_debug_to_world_coords.py` - DXF调试文件生成（参考标准）
- `compare_outputs_direct.py` - 坐标对比验证
- `check_xyz_bottom.py` - 高程分布验证

**外海数据统计（旧版43个断面）**:
- 断面数量: 43个 (18+300 ~ 22+500)
- 桩号间隔: 100m
- 开挖线点: 1032个
- 超挖线点: 1032个
- 脊梁点: 43个
```bash
# 需在项目目录执行
powershell -Command "Set-Location 'D:\断面算量平台\LocalViewer'; npm run build:dir"
```

**打包结果**:
- 解压即用版: `dist\win-unpacked\航道三维地质展示平台.exe`
- 便携版zip: `dist\航道三维地质展示平台-便携版.zip` (~104MB)

#### 9. 回淤层平滑处理与Z值约束 (2026-04-24)
**问题**: 回淤层显示有尖刺现象，分布区域不符合实际（部分低于DMX），样式与DMX相同无法分辨。

**解决方案**:

**1. 平滑处理** - 使用二维高斯滤波
```python
# "掩码-填充-滤波-恢复"策略处理含NaN的网格数据
def smooth_backfill_grid(Z, sigma=(1.2, 1.5), min_neighbors=2):
    # 1. 记录原始NaN掩码
    # 2. 用邻近有效值填充NaN
    # 3. 应用二维高斯滤波
    # 4. 恢复原始NaN位置
    # 5. 孤立点过滤
    Z_smoothed = gaussian_filter(Z_filled, sigma=sigma, mode='nearest')
```

**参数说明**:
- `sigma=(1.2, 1.5)` - 各向异性参数（桩号方向1.2，横向偏移1.5）
- `min_neighbors=2` - 孤立点过滤阈值

**2. Z值约束** - 地质层与超挖槽必须在DMX以下
```python
# 地质层约束
if Z_clamped[i, j] > z_dmx:
    Z_clamped[i, j] = np.nan  # 剔除高于DMX的点

# 回淤约束 - 只保留高于DMX的部分
if Z_clamped[i, j] < z_dmx:
    Z_clamped[i, j] = np.nan  # 剔除低于DMX的回淤
```

**约束结果**:
- 淤泥层(MUD): 1667个高于DMX的点被剔除
- 黏土层(CLAY): 121个高于DMX的点被剔除
- 砂层(SAND): 787个高于DMX的点被剔除
- 超挖槽(OVERDREDGE): 536个高于DMX的点被剔除
- 回淤(BACKFILL): 3822个高于DMX保留，3888个低于DMX剔除

**3. 样式区分** - 回淤改为实心深黄色
```python
OBJ_MATERIALS = {
    'BACKFILL_SOLID': {
        'color_rgb': (0.8, 0.6, 0.0),  # 深黄色
        'opacity': 1.0,  # 实心（不透明）
    }
}
```

**关键代码**: [`geology_model_v18.py`](geology_model_v18.py)
- `smooth_backfill_grid()` 第138-210行
- Z值约束 第900-980行
- `create_backfill_solid()` 第1112-1155行

#### 10. 展示平台UI功能完善 (2026-04-24)
**问题**: 无法关闭旧模型重新打开新模型，多个模型混在一起；多个UI功能未实现。

**解决方案**:

**1. 清除旧模型**
```javascript
function clearCurrentModel() {
    if (AppState.currentModel) {
        AppState.scene.remove(AppState.currentModel);
        // 释放几何体和材质内存
        AppState.currentModel.traverse((child) => {
            if (child.geometry) child.geometry.dispose();
            if (child.material) child.material.dispose();
        });
        AppState.currentModel = null;
    }
}
```

**2. 实现的功能**:
- 视图切换（俯视/前视/侧视）- 快捷键 1/2/3
- 截图导出PNG - 快捷键 Ctrl+S
- 全屏模式 - 快捷键 F11
- 透明度调节滑块
- 线框模式切换
- 剖面切割控制（X/Y/Z轴）
- FPS实时显示
- 键盘快捷键（R重置视角、Ctrl+O打开文件）

**关键文件**: [`LocalViewer/renderer/renderer.js`](renderer.js)
- `clearCurrentModel()` 第276行
- `setView()` 第650行
- `takeScreenshot()` 第672行
- `toggleFullscreen()` 第683行
- `setModelOpacity()` 第692行
- `setWireframeMode()` 第704行
- `updateClipping()` 第714行
- `handleKeyboard()` 第760行

## [L3] Current Status (AUTO-SYNC)

### 今日完成 (2026-04-24)

**V18地质模型改进**:
- [x] 回淤层平滑处理（高斯滤波sigma=(1.2, 1.5)）
- [x] 回淤层Z值约束（只保留DMX以上）
- [x] 地质层/超挖槽Z值约束（剔除DMX以上的部分）
- [x] 回淤样式改为实心深黄色（opacity=1.0）

**展示平台UI完善**:
- [x] 清除旧模型功能（避免多个模型混在一起）
- [x] 视图切换（俯视/前视/侧视）
- [x] 截图导出PNG
- [x] 全屏模式
- [x] 透明度调节
- [x] 线框模式
- [x] 剖面切割控制
- [x] FPS显示
- [x] 键盘快捷键

**生成结果**:
- 回淤有效点: 4072个（平滑后）
- 回淤实心体积: 18774个3DFACEs
- OBJ文件: 231624个顶点，167078个面

### 参数配置总结 (2026-04-17)

**统一流程**（适用于所有断面图类型）：
1. 脊梁点提取（从背景底图）
2. 断面元数据生成（从断面图）
3. 脊梁点匹配
4. XYZ提取
5. 可视化验证

**可配置参数**：
| 参数 | 说明 | 内湾默认值 | 外海默认值 |
|------|------|-----------|-----------|
| 水平比例尺 | 米/单位 | 1.0（自动检测） | 3.0 |
| 垂直比例尺 | 米/单位 | 10.0（自动检测） | 0.2 |
| 高程基准 | 米 | -12.0 | 0.0 |
| 目标高程 | 米 | 0.0 | -24.0 |
| 插值间隔 | 米 | 4.0 | 4.0 |

**输入文件**：
- 背景底图DXF：脊梁点来源（内湾底图.dxf / 外海背景.dxf）
- 断面图DXF：开挖线和超挖线来源
- 输出目录：存放所有中间文件和最终XYZ文件

**输出文件**：
- 脊梁点JSON：`{背景底图名}_脊梁点.json`
- 断面元数据JSON：`{断面图名}_bim_metadata.json`
- 脊梁点匹配JSON：`脊梁点_L1匹配结果.json`
- 开挖线XYZ：`开挖线_xyz.txt` / `外海_开挖线_xyz.txt`
- 超挖线XYZ：`超挖线_xyz.txt` / `外海_超挖线_xyz.txt`
- 中心线位置：`中心线位置.txt` / `外海_中心线位置.txt`
- 可视化PNG：`xyz_scatter_plot.png` / `外海_xyz_scatter_plot.png`

**GUI更新**：[`xyz_extraction_gui.py`](xyz_extraction_gui.py:1) 已更新为统一流程，参数可配置
- [>] 当前进度: 脊梁点曲线对齐修复完成，245个断面全部正确匹配
- [?] 待办步骤:
  1. LocalViewer Phase 2: 集成OBJ渲染功能（Three.js）
  2. LocalViewer Phase 3: 实现DXF解析模块
- [X] 已解决:
  - ARC方向反转问题修复 (extract_spine_points.py)
  - 中心线连续性验证通过 (108个离散点，无跳跃)
  - 脊梁点与中心线对齐验证通过 (245/245)
  - XYZ提取系统完整运行 (开挖线2838点 + 超挖线3124点)

### 今日修复记录 (2026-04-13)

**问题**: 弧线上脊梁点偏离中心线

**根因**: `explode()`后ARC实体方向与多段线顶点顺序相反

**修复**: 
1. 修改`get_centerline_points()`添加方向检测逻辑
2. 比较ARC两端点到前一个实体终点的距离
3. 自动反转方向确保连续性

**验证**:
- 中心线离散点: 108个 (原109个，去重1个)
- 最大间隙: < 1m (原800m)
- 脊梁点对齐: 245/245 全部在中心线上

**关键发现**:
- `flattening(sagitta=0.1)` 提供足够精度
- 必须检查LINE和ARC的方向一致性
- Shapely LineString要求点序列连续
