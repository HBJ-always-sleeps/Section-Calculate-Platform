/**
 * 航道三维地质展示平台 - OBJ模型加载器
 * 
 * 功能：
 * 1. 解析OBJ文件格式
 * 2. 支持MTL材质文件
 * 3. 支持大坐标优化
 * 4. 支持Web Worker异步加载
 * 
 * OBJ格式说明：
 * - v: 顶点坐标
 * - vt: 纹理坐标
 * - vn: 法线向量
 * - f: 面（三角形/四边形）
 * - usemtl: 使用材质
 * - mtllib: 材质库文件
 */

class OBJLoader {
    constructor() {
        this.vertices = [];
        this.normals = [];
        this.uvs = [];
        this.faces = [];
        this.materials = {};
        this.currentMaterial = 'default';
    }
    
    /**
     * 解析OBJ文件内容
     * @param {string} content - OBJ文件内容
     * @returns {THREE.Group} - Three.js组对象
     */
    parse(content) {
        // 重置状态
        this.vertices = [];
        this.normals = [];
        this.uvs = [];
        this.faces = [];
        
        const lines = content.split('\n');
        
        for (const line of lines) {
            this.parseLine(line);
        }
        
        return this.buildMesh();
    }
    
    /**
     * 解析单行
     * @param {string} line - 行内容
     */
    parseLine(line) {
        const trimmed = line.trim();
        if (trimmed.length === 0 || trimmed.startsWith('#')) {
            return;
        }
        
        const parts = trimmed.split(/\s+/);
        const type = parts[0].toLowerCase();
        
        switch (type) {
            case 'v':
                this.parseVertex(parts);
                break;
            case 'vn':
                this.parseNormal(parts);
                break;
            case 'vt':
                this.parseUV(parts);
                break;
            case 'f':
                this.parseFace(parts);
                break;
            case 'usemtl':
                this.currentMaterial = parts[1] || 'default';
                break;
            case 'mtllib':
                // 材质库由外部处理
                break;
        }
    }
    
    /**
     * 解析顶点
     *
     * 坐标转换：OBJ文件使用Z-up坐标系，Three.js使用Y-up坐标系
     * 需要交换Y和Z坐标，并取反新的Y轴（原Z轴）
     */
    parseVertex(parts) {
        if (parts.length >= 4) {
            // OBJ: x, y, z (Z-up)
            // Three.js: x, z, -y (Y-up)
            this.vertices.push({
                x: parseFloat(parts[1]),
                y: parseFloat(parts[3]),  // Z -> Y
                z: -parseFloat(parts[2])  // -Y -> Z (取负使模型朝上)
            });
        }
    }
    
    /**
     * 解析法线
     *
     * 坐标转换：与顶点相同的转换
     */
    parseNormal(parts) {
        if (parts.length >= 4) {
            this.normals.push({
                x: parseFloat(parts[1]),
                y: parseFloat(parts[3]),  // Z -> Y
                z: -parseFloat(parts[2])  // -Y -> Z
            });
        }
    }
    
    /**
     * 解析纹理坐标
     */
    parseUV(parts) {
        if (parts.length >= 3) {
            this.uvs.push({
                u: parseFloat(parts[1]),
                v: parseFloat(parts[2])
            });
        }
    }
    
    /**
     * 解析面
     */
    parseFace(parts) {
        const faceIndices = [];
        
        for (let i = 1; i < parts.length; i++) {
            const indices = this.parseFaceVertex(parts[i]);
            faceIndices.push(indices);
        }
        
        // 三角化（如果是四边形或更多边形）
        if (faceIndices.length === 3) {
            this.faces.push({
                indices: faceIndices,
                material: this.currentMaterial
            });
        } else if (faceIndices.length === 4) {
            // 四边形拆分为两个三角形
            this.faces.push({
                indices: [faceIndices[0], faceIndices[1], faceIndices[2]],
                material: this.currentMaterial
            });
            this.faces.push({
                indices: [faceIndices[0], faceIndices[2], faceIndices[3]],
                material: this.currentMaterial
            });
        } else if (faceIndices.length > 4) {
            // 多边形扇形三角化
            for (let i = 1; i < faceIndices.length - 1; i++) {
                this.faces.push({
                    indices: [faceIndices[0], faceIndices[i], faceIndices[i + 1]],
                    material: this.currentMaterial
                });
            }
        }
    }
    
    /**
     * 解析面顶点索引
     * 格式: v/vt/vn 或 v//vn 或 v/vt 或 v
     */
    parseFaceVertex(part) {
        const indices = part.split('/');
        
        return {
            v: parseInt(indices[0]) - 1,  // 顶点索引（OBJ从1开始）
            t: indices[1] ? parseInt(indices[1]) - 1 : -1,  // 纹理索引
            n: indices[2] ? parseInt(indices[2]) - 1 : -1   // 法线索引
        };
    }
    
    /**
     * 构建Three.js网格
     */
    buildMesh() {
        const group = new THREE.Group();
        
        // 按材质分组
        const materialGroups = new Map();
        
        for (const face of this.faces) {
            if (!materialGroups.has(face.material)) {
                materialGroups.set(face.material, []);
            }
            materialGroups.get(face.material).push(face);
        }
        
        // 为每个材质创建网格
        for (const [materialName, faces] of materialGroups) {
            const mesh = this.createMesh(faces, materialName);
            group.add(mesh);
        }
        
        return group;
    }
    
    /**
     * 创建单个网格
     */
    createMesh(faces, materialName) {
        const positions = [];
        const normals = [];
        const uvs = [];
        
        for (const face of faces) {
            for (const idx of face.indices) {
                // 顶点位置
                const v = this.vertices[idx.v];
                if (v) {
                    positions.push(v.x, v.y, v.z);
                }
                
                // 法线
                if (idx.n >= 0 && this.normals[idx.n]) {
                    const n = this.normals[idx.n];
                    normals.push(n.x, n.y, n.z);
                }
                
                // 纹理坐标
                if (idx.t >= 0 && this.uvs[idx.t]) {
                    const t = this.uvs[idx.t];
                    uvs.push(t.u, t.v);
                }
            }
        }
        
        // 创建几何体
        const geometry = new THREE.BufferGeometry();
        geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
        
        if (normals.length > 0) {
            geometry.setAttribute('normal', new THREE.Float32BufferAttribute(normals, 3));
        } else {
            geometry.computeVertexNormals();
        }
        
        if (uvs.length > 0) {
            geometry.setAttribute('uv', new THREE.Float32BufferAttribute(uvs, 2));
        }
        
        // 创建材质
        const material = this.createMaterial(materialName);
        
        return new THREE.Mesh(geometry, material);
    }
    
    /**
     * 创建材质
     */
    createMaterial(name) {
        const matData = this.materials[name] || {};
        
        return new THREE.MeshStandardMaterial({
            name: name,
            color: matData.color || 0x888888,
            metalness: matData.metalness || 0.1,
            roughness: matData.roughness || 0.8,
            transparent: (matData.opacity || 1.0) < 1,
            opacity: matData.opacity || 1.0,
            side: THREE.DoubleSide
        });
    }
    
    /**
     * 设置材质数据（从MTL解析）
     */
    setMaterials(materials) {
        this.materials = materials;
    }
    
    /**
     * 计算包围盒
     */
    computeBoundingBox() {
        if (this.vertices.length === 0) {
            return null;
        }
        
        const box = new THREE.Box3();
        
        for (const v of this.vertices) {
            box.expandByPoint(new THREE.Vector3(v.x, v.y, v.z));
        }
        
        return box;
    }
    
    /**
     * 计算相对中心偏移（解决大坐标抖动问题）
     */
    computeCenterOffset() {
        const box = this.computeBoundingBox();
        if (!box) {
            return { x: 0, y: 0, z: 0 };
        }
        
        const center = box.getCenter(new THREE.Vector3());
        return { x: center.x, y: center.y, z: center.z };
    }
}

// ==================== MTL解析器 ====================

class MTLLoader {
    /**
     * 解析MTL文件内容
     * @param {string} content - MTL文件内容
     * @returns {Object} - 材质对象字典
     */
    parse(content) {
        const materials = {};
        let currentMaterial = null;
        
        const lines = content.split('\n');
        
        for (const line of lines) {
            const trimmed = line.trim();
            if (trimmed.length === 0 || trimmed.startsWith('#')) {
                continue;
            }
            
            const parts = trimmed.split(/\s+/);
            const type = parts[0].toLowerCase();
            
            switch (type) {
                case 'newmtl':
                    currentMaterial = parts[1] || 'default';
                    materials[currentMaterial] = {
                        name: currentMaterial,
                        color: 0x888888,
                        opacity: 1.0,
                        metalness: 0.1,
                        roughness: 0.8
                    };
                    break;
                    
                case 'kd':
                    // 漫反射颜色
                    if (currentMaterial && parts.length >= 4) {
                        const r = parseFloat(parts[1]);
                        const g = parseFloat(parts[2]);
                        const b = parseFloat(parts[3]);
                        materials[currentMaterial].color = this.rgbToHex(r, g, b);
                    }
                    break;
                    
                case 'ka':
                    // 环境光颜色（暂不处理）
                    break;
                    
                case 'ks':
                    // 高光颜色（暂不处理）
                    break;
                    
                case 'd':
                    // 透明度
                    if (currentMaterial && parts.length >= 2) {
                        materials[currentMaterial].opacity = parseFloat(parts[1]);
                    }
                    break;
                    
                case 'tr':
                    // 透明度（另一种格式，反向）
                    if (currentMaterial && parts.length >= 2) {
                        materials[currentMaterial].opacity = 1.0 - parseFloat(parts[1]);
                    }
                    break;
                    
                case 'ns':
                    // 高光指数（可转换为roughness）
                    if (currentMaterial && parts.length >= 2) {
                        const ns = parseFloat(parts[1]);
                        // ns范围通常是0-1000，转换为roughness
                        materials[currentMaterial].roughness = Math.max(0, Math.min(1, 1 - ns / 1000));
                    }
                    break;
            }
        }
        
        return materials;
    }
    
    /**
     * RGB转十六进制
     */
    rgbToHex(r, g, b) {
        const clamp = (v) => Math.max(0, Math.min(1, v));
        return (Math.round(clamp(r) * 255) << 16) | 
               (Math.round(clamp(g) * 255) << 8) | 
               Math.round(clamp(b) * 255);
    }
}

// 导出
window.OBJLoader = OBJLoader;
window.MTLLoader = MTLLoader;