# NEO-6M GPS -> PYNQ-Z2 PMOD A (UART, 9600 baud)
# PMOD A Pin 1 (JA1_P) = Y18 -> FPGA TX  -> GPS RX
# PMOD A Pin 2 (JA1_N) = Y19 -> FPGA RX  <- GPS TX

set_property -dict {PACKAGE_PIN Y18 IOSTANDARD LVCMOS33} [get_ports uart_rtl_txd]
set_property -dict {PACKAGE_PIN Y19 IOSTANDARD LVCMOS33} [get_ports uart_rtl_rxd]
