// Simple electron test
const { app, BrowserWindow } = require('electron');

console.log('app:', app);
console.log('BrowserWindow:', BrowserWindow);

app.whenReady().then(() => {
    console.log('App is ready');
    const win = new BrowserWindow({ width: 800, height: 600 });
    win.loadFile('renderer/index.html');
    console.log('Window created');
});