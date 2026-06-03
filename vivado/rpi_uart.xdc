# NEO-6M GPS -> PYNQ-Z2 Raspberry Pi Header (9600 baud UART)
# DOGRU pinler (resmi PYNQ-Z2 base.xdc ile dogrulandi):
# Pin 8  (GPIO14 / UART0_TXD) = V6  -> FPGA TX -> GPS RX
# Pin 10 (GPIO15 / UART0_RXD) = Y6  <- FPGA RX <- GPS TX
#
# NOT: Onceki surumde Y8/C20 yanlisti (onlar Pin 35 / Pin 12).

set_property -dict {PACKAGE_PIN V6 IOSTANDARD LVCMOS33} [get_ports uart_rtl_txd]
set_property -dict {PACKAGE_PIN Y6 IOSTANDARD LVCMOS33} [get_ports uart_rtl_rxd]
