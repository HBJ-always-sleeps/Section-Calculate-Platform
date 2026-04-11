/**
 * 航道三维地质展示平台 - 渲染进程入口
 * 
 * 使用本地libs中的Three.js和OrbitControls
 */

const { ipcRenderer } = require('electron');

// 全局状态
const AppState = {
    scene: null,
    camera: null,
    renderer: null,
    controls: null,
    currentModel: null,
    modelCenter: { x: 0, y: 0, z: 0 },
    boundingBox: null,
    layers: new Map()
};

// 初始化Three.js场景
function initThreeJS() {
    const container = document.getElementById('viewer-container');
    const canvas = document.getElementById('viewer-canvas');
    
    if (!container || !canvas) {
        console.error('[Renderer] Container or canvas not found');
        return;
    }
    
    // 创建场景
    AppState.scene = new THREE.Scene();
    AppState.scene.background = new THREE.Color(0xffffff);  // 白色背景
    
    // 创建相机
    const aspect = container.clientWidth / container.clientHeight;
    AppState.camera = new THREE.PerspectiveCamera(45, aspect, 0.1, 1000000);
    AppState.camera.position.set(100, 100, 100);
    
    // 创建渲染器
    AppState.renderer = new THREE.WebGLRenderer({
        canvas: canvas,
        antialias: true,
        alpha: true
    });
    AppState.renderer.setSize(container.clientWidth, container.clientHeight);
    AppState.renderer.setPixelRatio(window.devicePixelRatio);
    
    // 添加轨道控制器
    AppState.controls = new THREE.OrbitControls(AppState.camera, canvas);
    AppState.controls.enableDamping = true;
    AppState.controls.dampingFactor = 0.05;
    
    // 添加环境光
    const ambientLight = new THREE.AmbientLight(0xffffff, 0.5);
    AppState.scene.add(ambientLight);
    
    // 添加平行光
    const directionalLight = new THREE.DirectionalLight(0xffffff, 0.8);
    directionalLight.position.set(100, 100, 50);
    AppState.scene.add(directionalLight);
    
    // 不添加网格辅助线
    // const gridHelper = new THREE.GridHelper(1000, 50, 0x444444, 0x333333);
    // AppState.scene.add(gridHelper);
    
    // 添加坐标轴辅助（放在右上角）
    const axisHelper = new THREE.AxesHelper(50);
    axisHelper.position.set(0, 0, 0);  // 原点位置，相机视角调整后会显示在右上角
    AppState.axisHelper = axisHelper;
    AppState.scene.add(axisHelper);
    
    console.log('[Renderer] Three.js initialized');
}

// 初始化事件监听
function initEventListeners() {
    // 窗口大小变化
    window.addEventListener('resize', onWindowResize);
    
    // 文件拖放
    const dropZone = document.getElementById('drop-zone');
    const container = document.getElementById('viewer-container');
    
    if (container && dropZone) {
        container.addEventListener('dragover', (e) => {
            e.preventDefault();
            dropZone.classList.add('drag-over');
        });
        
        container.addEventListener('dragleave', (e) => {
            e.preventDefault();
            dropZone.classList.remove('drag-over');
        });
        
        container.addEventListener('drop', onFileDrop);
    }
    
    // 工具栏按钮
    const btnOpenObj = document.getElementById('btn-open-obj');
    const btnOpenDxf = document.getElementById('btn-open-dxf');
    
    if (btnOpenObj) {
        btnOpenObj.addEventListener('click', () => {
            console.log('[Renderer] OBJ button clicked');
            ipcRenderer.send('menu-action', 'open-obj');
        });
    }
    
    if (btnOpenDxf) {
        btnOpenDxf.addEventListener('click', () => {
            console.log('[Renderer] DXF button clicked');
            ipcRenderer.send('menu-action', 'open-dxf');
        });
    }
    
    // 其他按钮
    const btnResetView = document.getElementById('btn-reset-view');
    if (btnResetView) {
        btnResetView.addEventListener('click', resetView);
    }
    
    // 侧边栏折叠按钮
    const btnCollapseSidebar = document.getElementById('btn-collapse-sidebar');
    if (btnCollapseSidebar) {
        btnCollapseSidebar.addEventListener('click', toggleSidebar);
    }
    
    // 侧边栏展开按钮（折叠状态下显示）
    const sidebarExpandBtn = document.getElementById('sidebar-expand-btn');
    if (sidebarExpandBtn) {
        sidebarExpandBtn.addEventListener('click', expandSidebar);
    }
    
    console.log('[Renderer] Event listeners initialized');
}

// 初始化IPC通信
function initIPC() {
    ipcRenderer.on('load-model', (event, data) => {
        console.log('[Renderer] Received load-model:', data.fileName);
        loadModel(data);
    });
    
    console.log('[Renderer] IPC initialized');
}

// 处理文件拖放
function onFileDrop(e) {
    e.preventDefault();
    const dropZone = document.getElementById('drop-zone');
    if (dropZone) {
        dropZone.classList.remove('drag-over');
    }
    
    const files = e.dataTransfer.files;
    if (files.length === 0) return;
    
    for (const file of files) {
        const filePath = file.path;
        const ext = filePath.split('.').pop().toLowerCase();
        
        if (ext === 'obj' || ext === 'dxf') {
            ipcRenderer.send('file-dropped', filePath);
        } else {
            showStatus(`不支持的文件格式: .${ext}`);
        }
    }
}

// 加载模型
function loadModel(data) {
    showLoading(true, `正在加载 ${data.fileName}...`);
    
    try {
        if (data.type === 'obj') {
            loadOBJModel(data);
        } else if (data.type === 'dxf') {
            loadDXFModel(data);
        }
        // 成功加载后隐藏拖放区域
        hideDropZone();
    } catch (error) {
        console.error('[Renderer] Model loading error:', error);
        showStatus(`加载失败: ${error.message}`);
        // 即使出错也隐藏拖放区域，避免遮挡
        hideDropZone();
    }
    
    showLoading(false);
}

// 加载OBJ模型
function loadOBJModel(data) {
    console.log('[Renderer] Loading OBJ model:', data.fileName);
    console.log('[Renderer] Has MTL:', data.mtlContent ? 'Yes' : 'No');
    
    // 使用自定义OBJ加载器
    if (typeof OBJLoader !== 'undefined') {
        const loader = new OBJLoader();
        
        // 如果有MTL内容，先解析材质
        if (data.mtlContent && typeof MTLLoader !== 'undefined') {
            try {
                const mtlLoader = new MTLLoader();
                const materials = mtlLoader.parse(data.mtlContent);
                loader.setMaterials(materials);
                console.log('[Renderer] MTL materials loaded');
            } catch (e) {
                console.error('[Renderer] MTL parse error:', e);
            }
        }
        
        const object = loader.parse(data.content);
        
        // 计算包围盒
        computeBoundingSphere(object);
        
        // 添加到场景
        AppState.currentModel = object;
        AppState.scene.add(object);
        
        // 提取图层并更新图层列表
        extractLayers(object);
        
        // 更新UI
        updateModelInfo(data.fileName, object);
        
        showStatus(`已加载: ${data.fileName}`);
    } else {
        // 使用简化加载器
        loadOBJSimple(data.content, data.fileName);
    }
}

// 简化OBJ加载
function loadOBJSimple(content, fileName) {
    const vertices = [];
    const faces = [];
    
    const lines = content.split('\n');
    
    for (const line of lines) {
        const parts = line.trim().split(/\s+/);
        const type = parts[0];
        
        if (type === 'v') {
            vertices.push([
                parseFloat(parts[1]),
                parseFloat(parts[2]),
                parseFloat(parts[3])
            ]);
        } else if (type === 'f') {
            const face = [];
            for (let i = 1; i < parts.length; i++) {
                const indices = parts[i].split('/');
                face.push(parseInt(indices[0]) - 1);
            }
            faces.push(face);
        }
    }
    
    // 创建Three.js几何体
    const geometry = new THREE.BufferGeometry();
    const positions = [];
    
    for (const face of faces) {
        if (face.length === 3) {
            for (const idx of face) {
                const v = vertices[idx];
                positions.push(v[0], v[1], v[2]);
            }
        } else if (face.length === 4) {
            // 四边形转三角形
            const idx = face;
            [0, 1, 2, 0, 2, 3].forEach(i => {
                const v = vertices[idx[i]];
                positions.push(v[0], v[1], v[2]);
            });
        }
    }
    
    geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
    geometry.computeVertexNormals();
    
    const material = new THREE.MeshStandardMaterial({
        color: 0x888888,
        metalness: 0.1,
        roughness: 0.8
    });
    
    const mesh = new THREE.Mesh(geometry, material);
    
    // 计算包围盒
    computeBoundingSphere(mesh);
    
    // 添加到场景
    AppState.currentModel = mesh;
    AppState.scene.add(mesh);
    
    // 更新UI
    updateModelInfo(fileName, mesh);
    
    showStatus(`已加载: ${fileName}`);
}

// 加载DXF模型
function loadDXFModel(data) {
    showStatus('DXF加载器将在Phase 3实现');
}

// 计算包围球
function computeBoundingSphere(object) {
    const box = new THREE.Box3().setFromObject(object);
    AppState.boundingBox = box;
    
    const center = box.getCenter(new THREE.Vector3());
    AppState.modelCenter = { x: center.x, y: center.y, z: center.z };
    
    // 应用相对中心偏移
    object.position.sub(center);
    
    const size = box.getSize(new THREE.Vector3());
    const maxDim = Math.max(size.x, size.y, size.z);
    
    // 设置相机位置
    AppState.camera.position.set(maxDim * 1.5, maxDim * 1.5, maxDim * 1.5);
    AppState.controls.target.set(0, 0, 0);
    AppState.controls.update();
    
    console.log('[Renderer] Model center offset:', center);
    console.log('[Renderer] Model size:', size);
}

// 重置视角
function resetView() {
    if (AppState.boundingBox) {
        const size = AppState.boundingBox.getSize(new THREE.Vector3());
        const maxDim = Math.max(size.x, size.y, size.z);
        
        AppState.camera.position.set(maxDim * 1.5, maxDim * 1.5, maxDim * 1.5);
        AppState.controls.target.set(0, 0, 0);
        AppState.controls.update();
    } else {
        AppState.camera.position.set(100, 100, 100);
        AppState.controls.target.set(0, 0, 0);
        AppState.controls.update();
    }
    
    showStatus('视角已重置');
}

// 切换侧边栏
function toggleSidebar() {
    const sidebar = document.getElementById('sidebar');
    const btn = document.getElementById('btn-collapse-sidebar');
    const expandBtn = document.getElementById('sidebar-expand-btn');
    if (sidebar) {
        const isCollapsed = sidebar.classList.toggle('collapsed');
        if (btn) {
            btn.textContent = isCollapsed ? '▶' : '◀';
        }
        // 显示/隐藏展开按钮
        if (expandBtn) {
            expandBtn.style.display = isCollapsed ? 'flex' : 'none';
        }
        // 调整视图大小
        onWindowResize();
    }
}

// 展开侧边栏
function expandSidebar() {
    const sidebar = document.getElementById('sidebar');
    const btn = document.getElementById('btn-collapse-sidebar');
    const expandBtn = document.getElementById('sidebar-expand-btn');
    if (sidebar && sidebar.classList.contains('collapsed')) {
        sidebar.classList.remove('collapsed');
        if (btn) {
            btn.textContent = '◀';
        }
        // 隐藏展开按钮
        if (expandBtn) {
            expandBtn.style.display = 'none';
        }
        onWindowResize();
    }
}

// 窗口大小变化
function onWindowResize() {
    const container = document.getElementById('viewer-container');
    if (!container) return;
    
    AppState.camera.aspect = container.clientWidth / container.clientHeight;
    AppState.camera.updateProjectionMatrix();
    AppState.renderer.setSize(container.clientWidth, container.clientHeight);
}

// 动画循环
function animate() {
    requestAnimationFrame(animate);
    AppState.controls.update();
    AppState.renderer.render(AppState.scene, AppState.camera);
}

// UI辅助函数
function showLoading(show, message) {
    const overlay = document.getElementById('loading-overlay');
    const msgEl = document.getElementById('loading-message');
    
    if (overlay) {
        overlay.style.display = show ? 'flex' : 'none';
        if (msgEl) msgEl.textContent = message || '加载中...';
    }
}

function showStatus(message) {
    const statusEl = document.getElementById('status-message');
    if (statusEl) {
        statusEl.textContent = message;
    }
    ipcRenderer.send('update-status', message);
}

function hideDropZone() {
    const dropZone = document.getElementById('drop-zone');
    if (dropZone) {
        dropZone.classList.add('hidden');
    }
}

function updateModelInfo(fileName, object) {
    const infoDiv = document.getElementById('model-info');
    if (!infoDiv) return;
    
    let vertexCount = 0;
    let faceCount = 0;
    
    object.traverse((child) => {
        if (child.isMesh && child.geometry) {
            vertexCount += child.geometry.attributes.position.count;
            if (child.geometry.index) {
                faceCount += child.geometry.index.count / 3;
            } else {
                faceCount += child.geometry.attributes.position.count / 3;
            }
        }
    });
    
    infoDiv.innerHTML = `
        <div class="info-row"><span>文件名:</span><span>${fileName}</span></div>
        <div class="info-row"><span>顶点数:</span><span>${vertexCount.toLocaleString()}</span></div>
        <div class="info-row"><span>面数:</span><span>${Math.round(faceCount).toLocaleString()}</span></div>
    `;
}

// 提取图层信息
function extractLayers(object) {
    const layerList = document.getElementById('layer-list');
    if (!layerList) return;
    
    // 清空现有图层列表
    AppState.layers.clear();
    layerList.innerHTML = '';
    
    // 遍历模型提取图层/材质信息
    const materialGroups = new Map();
    
    object.traverse((child) => {
        if (child.isMesh) {
            const materialName = child.material ? (child.material.name || 'default') : 'default';
            if (!materialGroups.has(materialName)) {
                materialGroups.set(materialName, {
                    name: materialName,
                    meshes: [],
                    visible: true
                });
            }
            materialGroups.get(materialName).meshes.push(child);
        }
    });
    
    // 如果没有材质分组，创建一个默认组
    if (materialGroups.size === 0) {
        materialGroups.set('default', {
            name: '全部模型',
            meshes: [object],
            visible: true
        });
    }
    
    // 保存到AppState并创建UI
    materialGroups.forEach((group, name) => {
        AppState.layers.set(name, group);
        
        const layerItem = document.createElement('div');
        layerItem.className = 'layer-item';
        layerItem.innerHTML = `
            <input type="checkbox" class="layer-checkbox" checked data-layer="${name}">
            <span class="layer-name">${name}</span>
            <input type="color" class="layer-color" value="#888888" data-layer="${name}">
        `;
        layerList.appendChild(layerItem);
        
        // 添加事件监听
        const checkbox = layerItem.querySelector('.layer-checkbox');
        checkbox.addEventListener('change', (e) => {
            const layerName = e.target.dataset.layer;
            const layerGroup = AppState.layers.get(layerName);
            if (layerGroup) {
                layerGroup.visible = e.target.checked;
                layerGroup.meshes.forEach(mesh => {
                    mesh.visible = e.target.checked;
                });
            }
        });
        
        const colorInput = layerItem.querySelector('.layer-color');
        colorInput.addEventListener('change', (e) => {
            const layerName = e.target.dataset.layer;
            const layerGroup = AppState.layers.get(layerName);
            if (layerGroup) {
                const color = new THREE.Color(e.target.value);
                layerGroup.meshes.forEach(mesh => {
                    if (mesh.material) {
                        mesh.material.color = color;
                    }
                });
            }
        });
    });
    
    console.log('[Renderer] Layers extracted:', materialGroups.size);
}

// 启动
document.addEventListener('DOMContentLoaded', () => {
    console.log('[Renderer] DOM loaded, initializing...');
    initThreeJS();
    initEventListeners();
    initIPC();
    animate();
    console.log('[Renderer] Application started');
});