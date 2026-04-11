# 清除所有 Electron 相关环境变量
$env:ELECTRON_RUN_AS_NODE = $null
$env:ELECTRON_NO_ATTACH_CONSOLE = $null

# 切换到项目目录
Set-Location "D:\断面算量平台\LocalViewer"

# 启动 Electron
Start-Process -FilePath ".\node_modules\electron\dist\electron.exe" -ArgumentList "." -NoNewWindow