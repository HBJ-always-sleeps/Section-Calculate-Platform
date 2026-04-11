// Minimal Electron test - using destructuring
console.log('Starting minimal test...');
console.log('Electron version:', process.versions.electron);

try {
    // Direct destructuring from require
    const { app, BrowserWindow } = require('electron');
    console.log('app:', app);
    console.log('BrowserWindow:', BrowserWindow);
    
    if (app) {
        app.on('ready', () => {
            console.log('App is ready!');
            const win = new BrowserWindow({
                width: 800,
                height: 600,
                webPreferences: {
                    nodeIntegration: true,
                    contextIsolation: false
                }
            });
            win.loadURL('data:text/html,<h1>Hello Electron!</h1>');
        });
    } else {
        console.error('app is undefined!');
    }
} catch (err) {
    console.error('Error:', err);
}