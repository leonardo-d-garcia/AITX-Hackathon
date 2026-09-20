@echo off
cd /d "%~dp0.."
start "DroneBench Web" /D "apps\web" cmd /c npm run dev
start "" "C:\Program Files\Epic Games\UE_5.8\Engine\Binaries\Win64\UnrealEditor.exe" "%~dp0..\unreal\DroneBench\DroneBench.uproject"
