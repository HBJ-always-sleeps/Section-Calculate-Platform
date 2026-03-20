# 🧠 Cline Tiered Memory

## [L1] Core Mission (STRICT)
- [x] 目标 1: autopaste批量粘贴功能修复
- [x] 架构设计: 通过红线-0.00-桩号的匹配链实现精确定位
- [x] 目标 2: engine_cad.py 代码重构优化（2026-03-18完成）
  - 备份：engine_cad_working.py
  - 优化：封装重复功能为类方法
  - 完善：文件输出逻辑支持自定义目录
  - 修复：断面线合并命名问题

## [L2] Hard-won Knowledge (ADAPTIVE)
- [!] **engine_cad.py 核心模块重构（2026-03-18）**：
  - **Config**: 全局配置类（图层名、颜色、地层排序）
  - **EntityHelper**: 实体处理工具集（线段转LineString、文本获取）
  - **LineUtils**: 线段处理工具集（Y坐标获取、延长、交点计算）
  - **LayerExtractor**: 图层提取工具集（线段、文本、多段线提取）
  - **StationMatcher**: 桩号匹配工具集（提取、排序、最近点查找）
  - **OutputHelper**: 文件输出工具集（路径生成、图层确保）
  - **SectionGenerator**: 断面线生成器（最终断面线生成）
  - **BasePointDetector**: 基点检测器（源端/目标端基点检测）
  - **HatchProcessor**: 填充处理器（转多边形、添加标注）

- [!] **关键函数保护清单**：
  - `run_autoline()`: 断面线合并
  - `run_autopaste()`: 批量粘贴
  - `run_autohatch()`: 快速填充
  - `run_autoclassify()`: 分类算量
  - `run_autocut()`: 分层算量

- [!] **测试脚本**：
  - 位置：`D:\断面算量平台\test_engine_all_functions.py`
  - 用途：一键测试所有核心功能
  - 测试文件目录：`D:\断面算量平台\测试文件\平台专用测试`
  - **请勿删除此测试脚本，后续迭代后都需运行验证**
  - **新增**：`D:\断面算量平台\test_area_scale_local.py` - 分类算量专用测试

- [!] **面积比例系数功能（2026-03-19新增）**：
  - **用途**：处理坐标已缩放的DXF文件（如按√0.6缩放）
  - **参数**：`面积比例系数`，默认1.0
  - **算法**：
    - 坐标缩放比例 = √面积比例系数
    - 所有距离匹配参数自动乘以坐标缩放比例
    - 最终面积乘以面积比例系数
  - **关键函数**：`StationMatcher.calc_adaptive_params()` - 计算自适应参数
  - **测试结果**：autoclassify_test.dxf 正确识别6个断面和桩号

- [!] **autolabel自动标注模块（2026-03-19整合）**：
  - **功能**：从Excel工程量表汇总数据 + 更新DXF面积标注
  - **代码位置**：`Code/autolabel.py`
  - **类**：`AutoLabel`
  - **方法**：
    - `summarize_excel(excel_path)` - 汇总Excel开挖/超挖面积
    - `update_dxf(dxf_path, data, output_path)` - 更新DXF面积标注
    - `run(excel_path, dxf_path, output_path)` - 完整流程
  - **自验证**：更新后重新读取DXF验证，成功才输出
  - **使用**：
    ```python
    from autolabel import AutoLabel
    autolabel = AutoLabel()
    success, result = autolabel.run(excel_path, dxf_path, output_path)
    ```

- [!] **桩号面积数据提取模块（2026-03-18新增）**：
  - **功能**：从DXF文件提取桩号和对应的面积标注数据
  - **代码位置**：`Code/enhanced_extract_data.py`
  - **图层结构**：
    - "桩号"图层：包含桩号文本（如K67+450）
    - "面积标注"图层：包含三行标注数据
  - **对应关系**：三行面积标注对应一个桩号
  
- [!] **面积标注结构分析（2026-03-18~19重要发现）**：
  - **标注文本结构**（每个断面三行）：
    1. `本期总剩余面积=` → 断面剩余面积
    2. `本期设计剩余面积=` → 超挖面积（设计）
    3. `本期超挖剩余面积=` → 欠挖面积（超挖）
  - **数值文本格式**：`548.15㎡`（数值+㎡符号，㎡=U+33A1）
  - **空间位置关系**：
    - 面积标注在桩号的**右上方**（Y更大）
    - 垂直距离约110-150单位
    - 按X坐标分左右侧（X<280为左侧，X>=280为右侧）
  - **桩号分组**：同一Y坐标的桩号为左右线一对
  
- [!] **面积标注更新功能（2026-03-19新增）**：
  - **功能**：根据Excel数据更新DXF面积标注
  - **代码位置**：`Code/enhanced_extract_data.py` -> `update_dxf_area_annotations()`
  - **输入数据格式**：
    ```python
    data = [
        {'桩号': 'K67+400', '设计剩余面积': 350.25, '超挖面积': 180.50},
        ...
    ]
    ```
  - **计算逻辑**：总剩余面积 = 设计剩余面积 + 超挖面积
  - **输出**：修改后的DXF文件

- [!] **DXF文件图层差异问题（2026-03-19重要教训）**：
  - **问题**：不同来源的DXF文件图层命名不一致
    - 测试文件：图层名为"面积标注"、"桩号"
    - 实际文件：所有实体都在图层"0"
  - **解决方案**：
    1. 代码需要支持自定义图层名参数
    2. 默认兼容图层"0"和专用图层
    3. 遍历时检查多个可能的图层名
  - **代码示例**：
    ```python
    # 兼容多图层名
    target_layers = ['面积标注', '0']  # 优先级顺序
    if entity.dxf.layer in target_layers:
        # 处理逻辑
    ```

- [!] **桩号排序算法（2026-03-19）**：
  - **问题**：桩号文本如"K67+400"无法直接按字符串排序
  - **解决**：提取桩号数字值排序
  - **代码**：
    ```python
    def sort_pile_number(pile_text):
        match = re.search(r'K(\d+)\+(\d+)', pile_text)
        if match:
            return int(match.group(1)) * 1000 + int(match.group(2))
        return 0
    ```
  - **结果**：K67+400 → 67400, K67+425 → 67425, K68+000 → 68000

- [!] **Y坐标空间关系总结**：
  - DXF坐标系：Y轴向下为负（屏幕坐标系）
  - "上方"意味着Y值更大（更接近0）
  - 面积标注在桩号上方 → 标注Y > 桩号Y
  - 搜索范围：桩号Y + 0~160 单位

- [!] **DXF面积标注更新经验教训（2026-03-19）**：
  - **核心原则**：更新后必须重新提取验证，否则不要输出结果
  - **X坐标偏移问题**：
    - 桩号X ≠ 面积标注X
    - 桩号X=123.9 → 描述文本X=166.2 → 数值文本X=197.7
    - 解决：扩大X匹配范围（桩号X-30 到 桩号X+150）
  - **描述文本识别**：
    - "本期总剩余面积=" → 总剩余
    - "本期设计剩余面积=" → 设计
    - "本期超挖剩余面积=" → 超挖
  - **数值文本格式**：数字+O 或 数字+㎡（O是乱码的㎡）
  - **匹配策略**：
    1. 先识别描述文本确定类型
    2. 通过Y坐标关联同一行的数值与描述
    3. 通过Y坐标关联桩号与其上方的数值文本
  - **验证方法**：更新后重新读取DXF，对比期望值与实际值
  - **脚本位置**：`D:\断面算量平台\scripts_dev\update_dxf_from_excel.py`


- [!] **基点检测算法（2026-03-16突破）**：
  - **核心方法**：航道底斜线顶端中点法
  - **原理**：航道底是倒梯形，左右两条斜线的顶端中点就是正确的基点X坐标
  - **代码位置**：`Code/engine_cad.py` -> `BasePointDetector.find_source_basepoints()`

- [!] **autopaste核心原理（用户说明）**：
  1. 首先得到第一个0.00位置和源基点位置
  2. 后续的0.00与基点的相对位置不变，所以找到0.00等于找到源基点
  3. 用断面间距找到下一个0.00
  4. 各要素的格式固定，但位置随断面形状而变
  5. 自动检测变化的要素，用不变的距离去对应正确的基点

## [L3] Current Status (AUTO-SYNC)
- [>] 当前进度: engine_cad.py 重构完成，待测试验证
- [X] 已解决: 
  - DXF断面数据结构分析
  - 桩号-断面关联建立
  - 3D放样建模实现（PyVista）
  - engine_cad.py 代码结构优化
  - 文件输出逻辑完善（支持自定义目录）
  - main_v3.py 同步修改（添加输出目录选择）
  - 测试脚本创建
- [?] 待办步骤: 
  1. 运行 test_engine_all_functions.py 测试验证
- [!] 注意: 不要动v2和v3版本的代码，不要私自用全航道测试文件

## [L2] 项目目录结构（2026-03-19整理）

**项目路径**：`D:\断面算量平台`

- **根目录**：
  - `CLINE_MEMORY.md` - 记忆文件
  - `断面分类算量.spec` - 打包配置
  - `test_engine_all_functions.py` - **不能删** 核心测试脚本
  - `test_area_scale_local.py` - **不能删** 分类算量测试
  - `engine_cad.cp311-win_amd64.pyd` - 编译模块

- **Code/** - 主程序代码：
  - `engine_cad.py` - 核心CAD处理模块
  - `main.py`, `main_v2.py`, `main_v3.py` - 主程序入口
  - `autopaste.py`, `autoline.py`, `autosection.py` 等 - 功能模块
  - `build_platform.py`, `build_platform_v2.py` - 平台构建脚本

- **_legacy_code/** - 旧版代码存档（参考用）：
  - `AutoLine.py`, `AutoPaste.py`, `AutoPaste_Tool.py`, `Paste_good.py`
  - `legacy_*.py` - 旧版功能模块
  - `Section/` - 旧版断面处理代码

- **scripts_dev/** - 开发测试脚本（定期清理）：
  - 分析脚本：`analyze_*.py`, `compare_*.py`, `debug_*.py`
  - 测试脚本：`test_*.py`（除了根目录的两个核心测试）
  - 工具脚本：`check_*.py`, `update_*.py`, `extract_*.py`, `build_3d_model.py`
  - 打包脚本：`build_exe.py`, `run_autoclassify.bat` 等

- **测试文件/** - 测试用DXF文件
  - `平台专用测试/` - 核心功能测试文件
  - `legacy_tests/` - 旧版测试文件存档
- **输出文件/** - 程序输出结果
