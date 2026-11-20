@echo off
chcp 65001 >nul
cd /d "%~dp0"
title 听写 · 全局语音输入
echo 听写 · 全局语音输入（默认：鼠标侧键 x1，一按开始、再按停止）
echo.
echo   自定义触发键  听写-全局输入.cmd --trigger ctrl+shift+d
echo   列出可选键    听写-全局输入.cmd --list-keys
echo   切换引擎      听写-全局输入.cmd --asr local   ^(只用本机^)
echo                听写-全局输入.cmd --asr online  ^(只用云端^)
echo                听写-全局输入.cmd --asr auto    ^(云端优先，失败回退本地^)
echo.
echo   云端需要先复制 config.example.json 为 config.json 并填入 online.api_key
echo   麦克风要在 Windows 设置里允许桌面应用访问
echo.
"%~dp0Tingxie.exe" --dictate %*
echo.
echo 已退出。按任意键关闭窗口。
pause >nul