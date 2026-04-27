@echo off
chcp 65001 >nul
echo ============================================
echo 断面算量平台 - 清理并推送代码
echo ============================================
echo.

cd /d "D:\断面算量平台\Code"

echo [1/4] 清理 git 缓存...
git rm -r --cached "测试文件/" 2>nul
git rm -r --cached "test_files/" 2>nul
git rm -cached "*.dxf" 2>nul
git rm -cached "*.obj" 2>nul
git rm -cached "*.mtl" 2>nul
git rm -cached "*.html" 2>nul

echo [2/4] 更新 .gitignore 并重新添加代码文件...
git add .gitignore
git add *.py
git add *.md
git add *.spec
git add *.json 2>nul
git add *.bat 2>nul
git add *.txt 2>nul
git add .gitignore

echo [3/4] 检查将要提交的文件...
git status --short

echo.
echo 按任意键继续提交并推送...
pause >nul

echo [4/4] 提交并推送...
git commit -m "更新.gitignore忽略大文件，优化推送配置"
git push origin main

echo.
echo ============================================
echo 完成！
echo ============================================
pause
