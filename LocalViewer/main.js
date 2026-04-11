/**
 * 航道三维地质展示平台 - Electron主进程
 */

const { app, BrowserWindow, Menu, dialog, ipcMain } = require('electron');
const path = require('path');
const fs = require('fs');

let mainWindow = null;

function createWindow() {
    mainWindow = new BrowserWindow({
        width: 1400,
        height: 900,
        webPreferences: {
            nodeIntegration: true,
            contextIsolation: false
        },
        backgroundColor: '#1a1a1a',
        show: false
    });

    // 加载完整的index.html
    mainWindow.loadFile(path.join(__dirname, 'renderer', 'index.html'));

    mainWindow.once('ready-to-show', () => {
        mainWindow.show();
    });

    // 不自动打开开发者工具
    // mainWindow.webContents.openDevTools();

    createMenu();
}

function createMenu() {
    const template = [
        {
            label: '文件',
            submenu: [
                { label: '打开OBJ', click: () => openFile('obj') },
                { label: '打开DXF', click: () => openFile('dxf') },
                { type: 'separator' },
                { role: 'quit' }
            ]
        },
        {
            label: '视图',
            submenu: [
                { role: 'reload' },
                { role: 'toggledevtools' },
                { type: 'separator' },
                { role: 'resetzoom' },
                { role: 'zoomin' },
                { role: 'zoomout' },
                { type: 'separator' },
                { role: 'togglefullscreen' }
            ]
        },
        {
            label: '帮助',
            submenu: [
                { label: '关于', click: () => showAbout() }
            ]
        }
    ];

    const menu = Menu.buildFromTemplate(template);
    Menu.setApplicationMenu(menu);
}

function openFile(type) {
    const filters = type === 'obj' 
        ? [{ name: 'OBJ Files', extensions: ['obj'] }, { name: 'All Files', extensions: ['*'] }]
        : [{ name: 'DXF Files', extensions: ['dxf'] }, { name: 'All Files', extensions: ['*'] }];

    dialog.showOpenDialog(mainWindow, {
        title: `打开${type.toUpperCase()}文件`,
        filters: filters,
        properties: ['openFile']
    }).then(result => {
        if (!result.canceled && result.filePaths.length > 0) {
            const filePath = result.filePaths[0];
            loadFile(filePath, type);
        }
    }).catch(err => {
        console.error('Error opening file:', err);
    });
}

function loadFile(filePath, type) {
    try {
        const content = fs.readFileSync(filePath, 'utf-8');
        const fileName = path.basename(filePath);
        
        // 如果是OBJ文件，尝试加载对应的MTL文件
        let mtlContent = null;
        if (type === 'obj') {
            const mtlPath = filePath.replace('.obj', '.mtl');
            if (fs.existsSync(mtlPath)) {
                try {
                    mtlContent = fs.readFileSync(mtlPath, 'utf-8');
                    console.log('[Main] Found MTL file:', path.basename(mtlPath));
                } catch (e) {
                    console.log('[Main] MTL file read error:', e.message);
                }
            }
        }
        
        mainWindow.webContents.send('load-model', {
            type: type,
            fileName: fileName,
            content: content,
            mtlContent: mtlContent
        });
        mainWindow.setTitle(`航道三维地质展示 - ${fileName}`);
    } catch (err) {
        dialog.showErrorBox('文件读取错误', `无法读取文件: ${err.message}`);
    }
}

function showAbout() {
    dialog.showMessageBox(mainWindow, {
        type: 'info',
        title: '关于',
        message: '航道三维地质展示平台',
        detail: '版本: 1.0.0\n支持格式: OBJ, DXF\n\n用于航道三维地质模型的可视化展示。'
    });
}

// 监听渲染进程发来的消息
ipcMain.on('menu-action', (event, action) => {
    console.log('收到菜单操作:', action);
    if (action === 'open-obj') {
        openFile('obj');
    } else if (action === 'open-dxf') {
        openFile('dxf');
    }
});

// 监听文件拖放
ipcMain.on('file-dropped', (event, filePath) => {
    console.log('文件拖放:', filePath);
    const ext = filePath.split('.').pop().toLowerCase();
    if (ext === 'obj' || ext === 'dxf') {
        loadFile(filePath, ext);
    }
});

// App lifecycle
app.whenReady().then(() => {
    console.log('App is ready, creating window...');
    createWindow();
});

app.on('window-all-closed', () => {
    if (process.platform !== 'darwin') app.quit();
});

app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
});