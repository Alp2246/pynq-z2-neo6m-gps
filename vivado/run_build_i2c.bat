@echo off
REM PYNQ-Z2 I2C (AXI GPIO bit-bang) overlay build
set VIVADO=C:\Xilinx\Vivado\2022.2\bin\vivado.bat
if not exist "%VIVADO%" (
    echo Vivado bulunamadi: %VIVADO%
    pause
    exit /b 1
)
cd /d "%~dp0"
call "%VIVADO%" -mode batch -source build_i2c_gpio.tcl -notrace
pause
