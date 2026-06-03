@echo off
REM PYNQ-Z2 GPS UART overlay - Vivado 2022.2 batch build
REM Vivado kurulum yolunu gerekirse duzenleyin:

set VIVADO=C:\Xilinx\Vivado\2022.2\bin\vivado.bat

if not exist "%VIVADO%" (
    echo Vivado bulunamadi: %VIVADO%
    echo Lutfen bu dosyada VIVADO yolunu duzenleyin.
    pause
    exit /b 1
)

cd /d "%~dp0"
echo Vivado build basliyor...
call "%VIVADO%" -mode batch -source build_gps_uart.tcl -notrace
echo.
echo Cikti klasoru: ..\output\
pause
