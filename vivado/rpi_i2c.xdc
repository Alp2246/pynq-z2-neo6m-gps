# MPU6050 (GY-521) I2C -> PYNQ-Z2 Raspberry Pi Header
# AXI GPIO bit-bang I2C (open-drain). Master XDC ile dogrulandi:
#   Pin 3 (GPIO2 / SDA1) = W18  -> SDA  = gpio_rtl_tri_io[0]
#   Pin 5 (GPIO3 / SCL1) = W19  -> SCL  = gpio_rtl_tri_io[1]
#
# NOT 1: MPU6050 VCC -> 3.3V (Pin 1). Modulde 4.7k pull-up SDA/SCL hatlari
#        VCC'ye baglidir; 3.3V verilirse hatlar 3.3V'a cekilir (FPGA-safe).
#        5V VERME -> hatlar 5V'a cikar, FPGA 3.3V girisini zorlar.
# NOT 2: Yedek olarak FPGA ic pull-up da aciyoruz (PULLUP TRUE).

set_property -dict {PACKAGE_PIN W18 IOSTANDARD LVCMOS33 PULLTYPE PULLUP} [get_ports {gpio_rtl_tri_io[0]}]
set_property -dict {PACKAGE_PIN W19 IOSTANDARD LVCMOS33 PULLTYPE PULLUP} [get_ports {gpio_rtl_tri_io[1]}]
