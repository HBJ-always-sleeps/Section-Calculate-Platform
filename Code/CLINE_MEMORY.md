# 🧠 Cline Tiered Memory

## [L1] Core Mission (STRICT)
- [x] 目标 1: 将断面算量平台代码推送到 Git 远程仓库
- [x] 架构设计: 本地 Git 仓库 + GitHub 远程仓库
- [x] 目标 2: 航道三维地质模型构建器 V17 开发完成
- [x] 目标 3: LocalViewer 3D查看器优化完成

## [L2] Hard-won Knowledge (ADAPTIVE)
- [!] 坑点记录: Windows CMD 的 cd /d 命令在跨盘符时，需要用 PowerShell 或 pushd + && 连接命令才能正确切换目录
- [!] 验证路径: D:\断面算量平台\Code 目录，使用 PowerShell -Command "cd '路径'; 命令" 格式最可靠
- [!] 坑点记录: Three.js 使用 Y-up 坐标系，OBJ文件使用 Z-up 坐标系，需要在加载时转换坐标
- [!] 坐标转换公式: y = z (Z→Y), z = -y (负Y→Z，使模型朝上)
- [!] 坑点记录: Electron 默认会自动打开 DevTools，需要在 main.js 中注释掉 openDevTools() 调用
- [!] 验证路径: LocalViewer 使用真实世界坐标（spine_x, spine_y）保留弯道形状，参考 extract_xyz_from_dxf.py
- [!] GitHub仓库: https://github.com/HBJ-always-sleeps/Section-Calculate-Platform.git

## [L3] Current Status (AUTO-SYNC)
- [>] 当前进度: ✅ V17模型和LocalViewer优化完成，已推送到GitHub
- [?] 待办步骤: 无
- [X] 已解决:
  - 桩号线长度增加1.5倍（33.75米）
  - 桩号线两端都有桩号数字（翻转180度）
  - 桩号线横截面增粗（0.2m）
  - 桩号线不透明（opacity 1.0）
  - 桩号文字尺寸增大（16m高，6.4m宽）
  - LocalViewer背景白色
  - 移除网格辅助线
  - 不自动打开DevTools
  - 图层管理器功能实现（显示/隐藏、颜色修改）
  - OBJ坐标转换（Z-up → Y-up）
  - Git推送完成（commit: fcd8921）
