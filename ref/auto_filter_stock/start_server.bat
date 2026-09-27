@echo off
REM 强势股智能筛选系统 - Windows启动脚本
REM ===========================================

echo.
echo ========================================
echo   强势股智能筛选系统
echo   Auto Stock Filter System
echo ========================================
echo.

REM 检查Python是否安装
python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未检测到Python，请先安装Python 3.11+
    echo 下载地址: https://www.python.org/downloads/
    pause
    exit /b 1
)

echo [1/3] 检查Python版本...
python --version

REM 检查是否在正确的目录
if not exist "main.py" (
    echo [错误] 未找到main.py，请确保在项目根目录运行此脚本
    pause
    exit /b 1
)

REM 检查.env文件
if not exist ".env" (
    echo.
    echo [警告] 未找到.env配置文件
    echo 请先创建.env文件并配置PYWENCAI_COOKIE
    echo.
    echo 按任意键继续（将使用默认配置）...
    pause >nul
)

echo.
echo [2/3] 正在启动服务器...
echo.
echo ----------------------------------------
echo   服务器地址: http://localhost:8000
echo   API文档:    http://localhost:8000/docs
echo   按 Ctrl+C 停止服务器
echo ----------------------------------------
echo.

REM 启动服务器
python main.py

REM 如果服务器意外停止
echo.
echo [3/3] 服务器已停止
pause

