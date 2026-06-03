@echo off
REM PYNQ-Z2 GPS UART - PMOD A build (alternatif pinler)
set VIVADO=C:\Xilinx\Vivado\2022.2\bin\vivado.bat
if not exist "%VIVADO%" (
    echo Vivado bulunamadi: %VIVADO%
    pause
    exit /b 1
)
cd /d "%~dp0"
call "%VIVADO%" -mode batch -source build_gps_uart_pmod.tcl -notrace
pause
