/**
 * 航道三维地质展示平台 - DXF图纸加载器
 * 
 * 功能：
 * 1. 解析DXF文件格式
 * 2. 支持3DFACE、LINE、LWPOLYLINE等实体
 * 3. 支持图层和颜色
 * 4. 支持大坐标优化
 * 
 * DXF格式说明：
 * - 3DFACE: 三维面（4个顶点）
 * - LINE: 直线
 * - LWPOLYLINE: 轻量多段线
 * - POLYLINE: 多段线
 * - POINT: 点
 * - TEXT/MTEXT: 文字
 * 
 * Phase 3 将实现完整功能
 */

class DXFLoader {
    constructor() {
        this.entities = [];
        this.layers = {};
        this.header = {};
    }
    
    /**
     * 解析DXF文件内容
     * @param {string} content - DXF文件内容
     * @returns {THREE.Group} - Three.js组对象
     */
    parse(content) {
        console.log('[DXFLoader] Starting parse...');
        
        // 重置状态
        this.entities = [];
        this.layers = {};
        this.header = {};
        
        // 解析DXF结构
        const dxf = this.parseDXFStructure(content);
        
        // 转换为Three.js对象
        const group = this.convertToThreeJS(dxf);
        
        console.log('[DXFLoader] Parse complete. Entities:', this.entities.length);
        
        return group;
    }
    
    /**
     * 解析DXF文件结构
     * @param {string} content - DXF文件内容
     * @returns {Object} - 解析后的DXF对象
     */
    parseDXFStructure(content) {
        const lines = content.split(/\r?\n/);
        const dxf = {
            header: {},
            tables: {},
            blocks: {},
            entities: []
        };
        
        let currentSection = null;
        let currentTable = null;
        let currentBlock = null;
        let i = 0;
        
        while (i < lines.length) {
            const code = parseInt(lines[i].trim());
            const value = lines[i + 1] ? lines[i + 1].trim() : '';
            
            if (isNaN(code)) {
                i++;
                continue;
            }
            
            // 处理节
            if (code === 0) {
                if (value === 'SECTION') {
                    // 下一行是节名
                    i += 2;
                    if (i < lines.length) {
                        currentSection = lines[i].trim();
                    }
                } else if (value === 'ENDSEC') {
                    currentSection = null;
                    currentTable = null;
                } else if (value === 'TABLE') {
                    // 表格开始
                } else if (value === 'ENDTAB') {
                    currentTable = null;
                } else if (value === 'BLOCK') {
                    currentBlock = { name: '', entities: [] };
                } else if (value === 'ENDBLK') {
                    if (currentBlock && currentBlock.name) {
                        dxf.blocks[currentBlock.name] = currentBlock;
                    }
                    currentBlock = null;
                } else {
                    // 实体
                    const entity = this.parseEntity(code, value, lines, i);
                    if (entity) {
                        if (currentBlock) {
                            currentBlock.entities.push(entity);
                        } else if (currentSection === 'ENTITIES') {
                            dxf.entities.push(entity);
                        }
                    }
                }
            }
            
            // 处理节内容
            if (currentSection === 'HEADER') {
                this.parseHeader(code, value, dxf.header);
            } else if (currentSection === 'TABLES') {
                this.parseTable(code, value, dxf.tables);
            } else if (currentSection === 'BLOCKS' && currentBlock) {
                if (code === 2) {
                    currentBlock.name = value;
                }
            }
            
            i += 2;
        }
        
        return dxf;
    }
    
    /**
     * 解析实体
     */
    parseEntity(code, value, lines, startIndex) {
        const entity = { type: value };
        let i = startIndex + 2;
        
        while (i < lines.length) {
            const c = parseInt(lines[i].trim());
            const v = lines[i + 1] ? lines[i + 1].trim() : '';
            
            if (isNaN(c)) {
                i++;
                continue;
            }
            
            if (c === 0) {
                // 下一个实体或节结束
                break;
            }
            
            // 解析实体属性
            switch (c) {
                case 8:  // 图层名
                    entity.layer = v;
                    break;
                case 62:  // 颜色索引
                    entity.color = parseInt(v);
                    break;
                case 10:  // X坐标
                    entity.x = parseFloat(v);
                    break;
                case 20:  // Y坐标
                    entity.y = parseFloat(v);
                    break;
                case 30:  // Z坐标
                    entity.z = parseFloat(v);
                    break;
                case 11:  // 终点X
                    entity.x2 = parseFloat(v);
                    break;
                case 21:  // 终点Y
                    entity.y2 = parseFloat(v);
                    break;
                case 31:  // 终点Z
                    entity.z2 = parseFloat(v);
                    break;
                // 3DFACE顶点
                case 12: entity.x3 = parseFloat(v); break;
                case 22: entity.y3 = parseFloat(v); break;
                case 32: entity.z3 = parseFloat(v); break;
                case 13: entity.x4 = parseFloat(v); break;
                case 23: entity.y4 = parseFloat(v); break;
                case 33: entity.z4 = parseFloat(v); break;
            }
            
            i += 2;
        }
        
        return entity;
    }
    
    /**
     * 解析头部
     */
    parseHeader(code, value, header) {
        // 简化处理，主要关注插入基点等
    }
    
    /**
     * 解析表格
     */
    parseTable(code, value, tables) {
        // 简化处理
    }
    
    /**
     * 转换为Three.js对象
     */
    convertToThreeJS(dxf) {
        const group = new THREE.Group();
        
        // 处理实体
        if (dxf.entities) {
            for (const entity of dxf.entities) {
                const mesh = this.convertEntity(entity);
                if (mesh) {
                    group.add(mesh);
                }
            }
        }
        
        return group;
    }
    
    /**
     * 转换单个实体
     */
    convertEntity(entity) {
        switch (entity.type) {
            case '3DFACE':
                return this.convert3DFace(entity);
            case 'LINE':
                return this.convertLine(entity);
            case 'LWPOLYLINE':
            case 'POLYLINE':
                return this.convertPolyline(entity);
            case 'POINT':
                return this.convertPoint(entity);
            default:
                return null;
        }
    }
    
    /**
     * 转换3DFACE
     */
    convert3DFace(entity) {
        const vertices = [
            entity.x || 0, entity.y || 0, entity.z || 0,
            entity.x2 || 0, entity.y2 || 0, entity.z2 || 0,
            entity.x3 || 0, entity.y3 || 0, entity.z3 || 0,
            entity.x4 || 0, entity.y4 || 0, entity.z4 || 0
        ];
        
        // 创建两个三角形（四边形）
        const positions = [
            vertices[0], vertices[1], vertices[2],
            vertices[3], vertices[4], vertices[5],
            vertices[6], vertices[7], vertices[8],
            vertices[0], vertices[1], vertices[2],
            vertices[6], vertices[7], vertices[8],
            vertices[9], vertices[10], vertices[11]
        ];
        
        const geometry = new THREE.BufferGeometry();
        geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
        geometry.computeVertexNormals();
        
        const material = new THREE.MeshStandardMaterial({
            color: this.getColor(entity.color),
            side: THREE.DoubleSide
        });
        
        const mesh = new THREE.Mesh(geometry, material);
        mesh.userData.layer = entity.layer || '0';
        
        return mesh;
    }
    
    /**
     * 转换LINE
     */
    convertLine(entity) {
        const geometry = new THREE.BufferGeometry();
        const positions = [
            entity.x || 0, entity.y || 0, entity.z || 0,
            entity.x2 || 0, entity.y2 || 0, entity.z2 || 0
        ];
        geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
        
        const material = new THREE.LineBasicMaterial({
            color: this.getColor(entity.color)
        });
        
        const line = new THREE.Line(geometry, material);
        line.userData.layer = entity.layer || '0';
        
        return line;
    }
    
    /**
     * 转换POLYLINE
     */
    convertPolyline(entity) {
        // 简化处理，创建直线段
        return null;
    }
    
    /**
     * 转换POINT
     */
    convertPoint(entity) {
        const geometry = new THREE.SphereGeometry(0.5, 8, 8);
        geometry.translate(entity.x || 0, entity.y || 0, entity.z || 0);
        
        const material = new THREE.MeshBasicMaterial({
            color: this.getColor(entity.color)
        });
        
        return new THREE.Mesh(geometry, material);
    }
    
    /**
     * 获取颜色
     */
    getColor(colorIndex) {
        // DXF颜色索引转RGB
        const colors = [
            0x000000, 0xFF0000, 0xFFFF00, 0x00FF00,
            0x00FFFF, 0x0000FF, 0xFF00FF, 0xFFFFFF,
            0x808080, 0xC0C0C0
        ];
        
        if (colorIndex && colorIndex > 0 && colorIndex <= colors.length) {
            return colors[colorIndex - 1];
        }
        
        return 0x888888;
    }
    
    /**
     * 计算包围盒
     */
    computeBoundingBox(group) {
        const box = new THREE.Box3();
        
        group.traverse((child) => {
            if (child.isMesh || child.isLine) {
                if (child.geometry) {
                    child.geometry.computeBoundingBox();
                    const childBox = child.geometry.boundingBox;
                    if (childBox) {
                        box.union(childBox);
                    }
                }
            }
        });
        
        return box;
    }
}

// 导出
window.DXFLoader = DXFLoader;