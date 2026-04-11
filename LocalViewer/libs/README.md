# 依赖库说明

## Three.js

Three.js 是用于3D渲染的核心库。

### 获取方式

1. **从CDN下载**（推荐）:
   - https://unpkg.com/three@0.160.0/build/three.min.js
   - https://unpkg.com/three@0.160.0/examples/js/controls/OrbitControls.js

2. **从npm安装**:
   ```bash
   npm install three@0.160.0
   ```
   然后从 `node_modules/three/build/` 复制文件

3. **从Online3DViewer复用**:
   项目已包含Three.js，可从以下位置复制：
   - `D:\断面算量平台\Online3DViewer-master\website\libs\three.min.js`

## dxf-parser

DXF文件解析库。

### 获取方式

```bash
npm install dxf-parser@5.1.0
```

或从CDN下载：
- https://unpkg.com/dxf-parser@5.1.0/dist/dxf-parser.min.js

## 文件列表

```
libs/
├── three.min.js          # Three.js核心库
├── OrbitControls.js      # 轨道控制器
└── dxf-parser.min.js     # DXF解析库（Phase 3）
```

## 注意事项

1. 确保所有库文件都是本地化的，不要使用CDN链接
2. 版本号应与package.json中声明的一致
3. OrbitControls.js需要放在与three.min.js同级目录