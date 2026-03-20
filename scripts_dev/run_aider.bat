@echo off
REM Aider 启动脚本
REM 激活环境并运行 aider (阿里云百炼 openai/qwen3-coder-next)
REM --no-pretty 禁用rich格式化，避免GBK编码错误

call venv\Scripts\activate.bat
aider --model openai/qwen3-coder-plus --no-pretty %*
