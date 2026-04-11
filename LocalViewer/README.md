# 航道三维地质展示平台

基于 Electron + Three.js 构建的本地桌面3D模型查看器，支持 OBJ 和 DXF 格式。

## 功能特性

- **格式支持**: OBJ（带MTL材质）、DXF（3DFACE、LINE等实体）
- **交互操作**: 旋转、缩放、平移、视图切换
- **图层管理**: 显示/隐藏、颜色调整、透明度控制
- **剖面切割**: 实时切割查看内部结构
- **测量工具**: 距离测量
- **大坐标优化**: 解决CGCS2000坐标系抖动问题

## 快速开始

### 环境要求

- Node.js 18+
- npm 9+

### 安装步骤

1. 双击运行 `启动.bat`
2. 首次运行会自动安装依赖和下载Three.js库
3. 等待应用窗口打开

### 手动安装

```bash
# 安装依赖
npm install

# 下载Three.js库
# 将以下文件放到 libs/ 目录:
# - three.min.js (https://unpkg.com/three@0.160.0/build/three.min.js)
# - OrbitControls.js (https://unpkg.com/three@0.160.0/examples/js/controls/OrbitControls.js)

# 启动应用
npm start
```

## 项目结构

```
LocalViewer/
├── main.js              # Electron主进程
├── package.json         # 项目配置
├── 启动.bat             # Windows启动脚本
├── renderer/            # 渲染进程
│   ├── index.html       # 主界面
│   ├── renderer.js      # 渲染进程入口
│   └── css/
│       └── style.css    # 样式表
├── engine/              # 核心引擎
│   ├── viewer.js        # 查看器核心
│   ├── obj-loader.js    # OBJ加载器
│   └── dxf-loader.js    # DXF加载器
├── libs/                # 第三方库
│   ├── three.min.js     # Three.js
│   └── OrbitControls.js # 轨道控制器
└── assets/              # 资源文件
    └── icons/           # 图标
```

## 快捷键

| 快捷键 | 功能 |
|--------|------|
| Ctrl+O | 打开OBJ模型 |
| Ctrl+Shift+O | 打开DXF图纸 |
| Ctrl+S | 导出截图 |
| R | 重置视角 |
| 1 | 俯视图 |
| 2 | 前视图 |
| 3 | 侧视图 |
| M | 测量距离 |
| C | 剖面切割 |
| F11 | 全屏 |
| F12 | 开发者工具 |

## 开发说明

### 构建发布版本

```bash
npm run build
```

生成的安装包位于 `dist/` 目录。

### 开发模式

```bash
npm start -- --dev
```

## 技术栈

- **Electron** 28.0 - 桌面应用框架
- **Three.js** 0.160.0 - 3D渲染引擎
- **dxf-parser** 5.1.0 - DXF解析库

## 已知问题

1. DXF解析器目前仅支持基本实体（3DFACE、LINE），完整支持将在Phase 3实现
2. 大文件加载建议使用Web Worker（计划在后续版本实现）

## 更新日志

### v1.0.0 (Phase 1)
- Electron基础框架搭建
- Three.js渲染引擎集成
- OBJ加载器实现
- 基础UI界面
- 图层管理器
- 剖面切割功能

## 许可证

MIT License

## 作者

断面算量平台开发团队