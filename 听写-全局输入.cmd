@echo off
chcp 65001 >nul
cd /d "%~dp0"
title 听写 · 全局语音输入
echo 正在启动全局听写（按鼠标侧键开始/停止）...
echo 提示：麦克风要在 Windows 设置里允许桌面应用访问。
echo.
"%~dp0Tingxie.exe" --dictate %*
echo.
echo 已退出。按任意键关闭窗口。
pause >nul