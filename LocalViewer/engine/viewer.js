/**
 * 航道三维地质展示平台 - 3D查看器核心引擎
 * 
 * 功能：
 * 1. 场景管理
 * 2. 相机控制
 * 3. 材质管理
 * 4. 图层状态机
 * 
 * 设计原则：
 * - 复用Online3DViewer的核心逻辑
 * - 支持大坐标优化（相对中心偏移）
 * - 支持Web Worker异步加载
 */

// ==================== 图层状态机 ====================

class LayerStateMachine {
    constructor() {
        this.layers = new Map();
        this.visibleMask = 0xFFFFFFFF;
    }
    
    /**
     * 添加图层
     * @param {string} name - 图层名称
     * @param {THREE.Object3D} object - 3D对象
     * @param {Object} options - 选项
     */
    addLayer(name, object, options = {}) {
        const layer = {
            name: name,
            object: object,
            visible: true,
            color: options.color || 0x888888,
            opacity: options.opacity || 1.0,
            wireframe: false
        };
        
        this.layers.set(name, layer);
        this.updateVisibilityMask();
        
        return layer;
    }
    
    /**
     * 切换图层可见性
     * @param {string} name - 图层名称
     */
    toggleLayer(name) {
        const layer = this.layers.get(name);
        if (layer) {
            layer.visible = !layer.visible;
            layer.object.visible = layer.visible;
            this.updateVisibilityMask();
        }
    }
    
    /**
     * 设置图层颜色
     * @param {string} name - 图层名称
     * @param {number} color - 颜色值
     */
    setLayerColor(name, color) {
        const layer = this.layers.get(name);
        if (layer) {
            layer.color = color;
            layer.object.traverse((child) => {
                if (child.isMesh && child.material) {
                    child.material.color.setHex(color);
                }
            });
        }
    }
    
    /**
     * 设置图层透明度
     * @param {string} name - 图层名称
     * @param {number} opacity - 透明度 (0-1)
     */
    setLayerOpacity(name, opacity) {
        const layer = this.layers.get(name);
        if (layer) {
            layer.opacity = opacity;
            layer.object.traverse((child) => {
                if (child.isMesh && child.material) {
                    child.material.transparent = opacity < 1;
                    child.material.opacity = opacity;
                }
            });
        }
    }
    
    /**
     * 全部显示/隐藏
     */
    toggleAll() {
        const allVisible = Array.from(this.layers.values()).every(l => l.visible);
        
        this.layers.forEach((layer) => {
            layer.visible = !allVisible;
            layer.object.visible = layer.visible;
        });
        
        this.updateVisibilityMask();
    }
    
    /**
     * 更新可见性位掩码
     */
    updateVisibilityMask() {
        let mask = 0;
        let bit = 1;
        
        this.layers.forEach((layer) => {
            if (layer.visible) {
                mask |= bit;
            }
            bit <<= 1;
        });
        
        this.visibleMask = mask;
    }
    
    /**
     * 获取图层列表
     */
    getLayerList() {
        return Array.from(this.layers.entries()).map(([name, layer]) => ({
            name: name,
            visible: layer.visible,
            color: layer.color,
            opacity: layer.opacity
        }));
    }
}

// ==================== 材质管理器 ====================

class MaterialManager {
    constructor() {
        this.materials = new Map();
        this.defaultMaterial = this.createDefaultMaterial();
    }
    
    /**
     * 创建默认材质
     */
    createDefaultMaterial() {
        return new THREE.MeshStandardMaterial({
            color: 0x888888,
            metalness: 0.1,
            roughness: 0.8,
            side: THREE.DoubleSide
        });
    }
    
    /**
     * 创建材质
     * @param {string} name - 材质名称
     * @param {Object} options - 材质选项
     */
    createMaterial(name, options = {}) {
        const material = new THREE.MeshStandardMaterial({
            color: options.color || 0x888888,
            metalness: options.metalness || 0.1,
            roughness: options.roughness || 0.8,
            transparent: (options.opacity || 1.0) < 1,
            opacity: options.opacity || 1.0,
            side: options.side || THREE.DoubleSide,
            wireframe: options.wireframe || false
        });
        
        this.materials.set(name, material);
        return material;
    }
    
    /**
     * 获取材质
     * @param {string} name - 材质名称
     */
    getMaterial(name) {
        return this.materials.get(name) || this.defaultMaterial;
    }
    
    /**
     * 从MTL内容解析材质
     * @param {string} mtlContent - MTL文件内容
     */
    parseMTL(mtlContent) {
        const materials = {};
        let currentMaterial = null;
        
        const lines = mtlContent.split('\n');
        
        for (const line of lines) {
            const parts = line.trim().split(/\s+/);
            const type = parts[0];
            
            if (type === 'newmtl') {
                currentMaterial = parts[1];
                materials[currentMaterial] = {
                    name: currentMaterial,
                    color: 0x888888,
                    opacity: 1.0
                };
            } else if (currentMaterial) {
                if (type === 'Kd' && parts.length >= 4) {
                    // 漫反射颜色
                    const r = parseFloat(parts[1]);
                    const g = parseFloat(parts[2]);
                    const b = parseFloat(parts[3]);
                    materials[currentMaterial].color = this.rgbToHex(r, g, b);
                } else if (type === 'd' && parts.length >= 2) {
                    // 透明度
                    materials[currentMaterial].opacity = parseFloat(parts[1]);
                } else if (type === 'Tr' && parts.length >= 2) {
                    // 透明度（另一种格式）
                    materials[currentMaterial].opacity = 1.0 - parseFloat(parts[1]);
                }
            }
        }
        
        // 创建Three.js材质
        for (const [name, data] of Object.entries(materials)) {
            this.createMaterial(name, {
                color: data.color,
                opacity: data.opacity
            });
        }
        
        return materials;
    }
    
    /**
     * RGB转十六进制
     */
    rgbToHex(r, g, b) {
        return (Math.round(r * 255) << 16) | 
               (Math.round(g * 255) << 8) | 
               Math.round(b * 255);
    }
}

// ==================== 相机管理器 ====================

class CameraManager {
    constructor(camera, controls) {
        this.camera = camera;
        this.controls = controls;
        this.views = {
            perspective: { position: [100, 100, 100], target: [0, 0, 0] },
            top: { position: [0, 1000, 0], target: [0, 0, 0] },
            front: { position: [0, 0, 1000], target: [0, 0, 0] },
            side: { position: [1000, 0, 0], target: [0, 0, 0] }
        };
    }
    
    /**
     * 设置视图
     * @param {string} viewName - 视图名称
     */
    setView(viewName) {
        const view = this.views[viewName];
        if (view) {
            this.camera.position.set(...view.position);
            this.controls.target.set(...view.target);
            this.controls.update();
        }
    }
    
    /**
     * 重置视角
     */
    reset() {
        this.setView('perspective');
    }
    
    /**
     * 适应模型
     * @param {THREE.Box3} boundingBox - 包围盒
     */
    fitToModel(boundingBox) {
        const center = boundingBox.getCenter(new THREE.Vector3());
        const size = boundingBox.getSize(new THREE.Vector3());
        const maxDim = Math.max(size.x, size.y, size.z);
        
        // 计算相机距离
        const distance = maxDim * 1.5;
        
        // 设置相机位置
        this.camera.position.set(distance, distance, distance);
        this.controls.target.copy(center);
        this.controls.update();
        
        // 更新预设视图
        this.views.perspective = {
            position: [center.x + distance, center.y + distance, center.z + distance],
            target: [center.x, center.y, center.z]
        };
        this.views.top = {
            position: [center.x, center.y + maxDim * 2, center.z],
            target: [center.x, center.y, center.z]
        };
        this.views.front = {
            position: [center.x, center.y, center.z + maxDim * 2],
            target: [center.x, center.y, center.z]
        };
        this.views.side = {
            position: [center.x + maxDim * 2, center.y, center.z],
            target: [center.x, center.y, center.z]
        };
    }
}

// ==================== 导出 ====================

// 全局实例（由renderer.js初始化）
window.LayerStateMachine = LayerStateMachine;
window.MaterialManager = MaterialManager;
window.CameraManager = CameraManager;