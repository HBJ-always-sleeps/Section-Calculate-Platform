@echo off
cd /d "D:\断面算量平台\Code"
if not exist .git (
    git init
)
git add .
git commit -m "Initial commit: 断面算量平台代码"
echo Done.
pause