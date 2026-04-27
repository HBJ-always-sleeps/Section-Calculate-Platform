@echo off
chcp 65001 >nul
echo ========================================
echo 航道三维地质展示平台 - 便携版打包脚本
echo ========================================
echo.

cd /d "%~dp0"

echo 正在打包...
powershell -Command "$env:CSC_IDENTITY_AUTO_DISCOVERY='false'; npx electron-builder --win portable"

echo.
echo ========================================
echo 打包完成！请查看 dist 目录
echo ========================================
pause