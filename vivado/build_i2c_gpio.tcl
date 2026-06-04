# =============================================================================
# PYNQ-Z2 I2C (AXI GPIO bit-bang) overlay - otomatik Vivado build
# MPU6050 / GY-521 ve diger I2C sensorler icin.
#
# AXI GPIO 2-bit, bidirectional (tri-state) -> RPi header:
#   bit0 = SDA = Pin 3 = W18
#   bit1 = SCL = Pin 5 = W19
# Linux device-tree gerekmez; /dev/mem MMIO ile bit-bang yapilir.
#
# Cikti: ../output/i2c_gpio.bit + .bin + .hwh
# Calistir: run_build_i2c.bat
# =============================================================================

set origin_dir [file normalize [file dirname [info script]]]
set proj_root  [file normalize [file join $origin_dir ..]]
set proj_name  i2c_gpio
set proj_dir   [file join $origin_dir build $proj_name]
set out_dir    [file join $proj_root output]
set preset_tcl [file join $proj_root "pynq-z2_v1.0.xdc" "PYNQ-Z2 v1.0.tcl"]
set xdc_file   [file join $origin_dir rpi_i2c.xdc]
set board_repo [file join $proj_root pynq-z2]

file mkdir $out_dir
file mkdir [file join $origin_dir build]

puts "=============================================="
puts " PYNQ-Z2 I2C (AXI GPIO) overlay build"
puts " Project : $proj_dir"
puts " Output  : $out_dir"
puts "=============================================="

create_project $proj_name $proj_dir -part xc7z020clg400-1 -force
set_property target_language Verilog [current_project]

if {[file exists [file join $board_repo pynq-z2 A.0 board.xml]]} {
  set_param board.repoPaths [list $board_repo]
  if {[lsearch [get_board_parts] tul.com.tw:pynq-z2:part0:1.0] >= 0} {
    set_property board_part tul.com.tw:pynq-z2:part0:1.0 [current_project]
    puts "OK: Board part tul.com.tw:pynq-z2:part0:1.0"
  }
} else {
  puts "UYARI: Board dosyasi bulunamadi, preset TCL kullanilacak."
}

# --- Block Design ---
set design_name design_1
create_bd_design $design_name
current_bd_design $design_name

# Zynq PS7
set ps7 [create_bd_cell -type ip -vlnv xilinx.com:ip:processing_system7:5.5 processing_system7_0]

if {[get_property board_part [current_project]] ne ""} {
  apply_bd_automation -rule xilinx.com:bd_rule:processing_system7 \
    -config {make_external "FIXED_IO, DDR" apply_board_preset "1"} \
    $ps7
  puts "OK: Zynq PS7 board preset uygulandi."
} elseif {[file exists $preset_tcl]} {
  source $preset_tcl
  set cfg [apply_preset $ps7]
  set_property -dict $cfg $ps7
  apply_bd_automation -rule xilinx.com:bd_rule:processing_system7 \
    -config {make_external "FIXED_IO, DDR"} \
    $ps7
  puts "OK: Zynq PS7 PYNQ-Z2 v1.0.tcl preset uygulandi."
} else {
  error "Board part veya PYNQ-Z2 v1.0.tcl bulunamadi!"
}

set_property -dict [list \
  CONFIG.PCW_USE_M_AXI_GP0 {1} \
  CONFIG.PCW_EN_CLK0_PORT {1} \
  CONFIG.PCW_EN_RST0_PORT {1} \
  CONFIG.PCW_FPGA0_PERIPHERAL_FREQMHZ {100} \
] $ps7

# AXI GPIO - 2 bit, bidirectional (her bit ayri tri-state -> bit-bang I2C)
create_bd_cell -type ip -vlnv xilinx.com:ip:axi_gpio:2.0 axi_gpio_0
set_property -dict [list \
  CONFIG.C_GPIO_WIDTH {2} \
  CONFIG.C_IS_DUAL {0} \
  CONFIG.C_ALL_INPUTS {0} \
  CONFIG.C_ALL_OUTPUTS {0} \
] [get_bd_cells axi_gpio_0]

# AXI Interconnect
create_bd_cell -type ip -vlnv xilinx.com:ip:axi_interconnect:2.1 axi_interconnect_0
set_property -dict [list CONFIG.NUM_MI {1}] [get_bd_cells axi_interconnect_0]

# Reset controller
create_bd_cell -type ip -vlnv xilinx.com:ip:proc_sys_reset:5.0 proc_sys_reset_0

# AXI baglantilari
connect_bd_intf_net [get_bd_intf_pins processing_system7_0/M_AXI_GP0] [get_bd_intf_pins axi_interconnect_0/S00_AXI]
connect_bd_intf_net [get_bd_intf_pins axi_interconnect_0/M00_AXI] [get_bd_intf_pins axi_gpio_0/S_AXI]

# Clock (PYNQ preset bazi ekstra AXI portlarini acar -> hepsinin ACLK'si baglanmali)
connect_bd_net [get_bd_pins processing_system7_0/FCLK_CLK0] \
  [get_bd_pins processing_system7_0/M_AXI_GP0_ACLK] \
  [get_bd_pins processing_system7_0/M_AXI_GP1_ACLK] \
  [get_bd_pins processing_system7_0/S_AXI_GP0_ACLK] \
  [get_bd_pins processing_system7_0/S_AXI_HP0_ACLK] \
  [get_bd_pins processing_system7_0/S_AXI_HP2_ACLK] \
  [get_bd_pins axi_interconnect_0/ACLK] \
  [get_bd_pins axi_interconnect_0/S00_ACLK] \
  [get_bd_pins axi_interconnect_0/M00_ACLK] \
  [get_bd_pins axi_gpio_0/s_axi_aclk] \
  [get_bd_pins proc_sys_reset_0/slowest_sync_clk]

# Reset
connect_bd_net [get_bd_pins processing_system7_0/FCLK_RESET0_N] [get_bd_pins proc_sys_reset_0/ext_reset_in]
connect_bd_net [get_bd_pins proc_sys_reset_0/interconnect_aresetn] [get_bd_pins axi_interconnect_0/ARESETN]
connect_bd_net [get_bd_pins proc_sys_reset_0/peripheral_aresetn] \
  [get_bd_pins axi_interconnect_0/S00_ARESETN] \
  [get_bd_pins axi_interconnect_0/M00_ARESETN] \
  [get_bd_pins axi_gpio_0/s_axi_aresetn]

# GPIO dis pina cikar (gpio_rtl_tri_io[1:0]) -> RPi Pin 3/5
create_bd_intf_port -mode Master -vlnv xilinx.com:interface:gpio_rtl:1.0 gpio_rtl
connect_bd_intf_net [get_bd_intf_ports gpio_rtl] [get_bd_intf_pins axi_gpio_0/GPIO]

# Adres ata ve sabitle (Python varsayilani 0x41200000 ile uyumlu)
assign_bd_address
set seg [get_bd_addr_segs -of_objects [get_bd_addr_spaces processing_system7_0/Data]]
catch {set_property offset 0x41200000 $seg}
catch {set_property range  64K         $seg}
puts "OK: AXI GPIO adresi = [get_property offset $seg]"

regenerate_bd_layout
save_bd_design

if {[catch {validate_bd_design} err]} {
  puts "BD validation hatasi: $err"
  error $err
}
puts "OK: Block design tamam."

# --- HDL Wrapper ---
make_wrapper -files [get_files ${design_name}.bd] -top -import
set_property top ${design_name}_wrapper [current_fileset]
update_compile_order -fileset sources_1

# --- Constraints ---
add_files -fileset constrs_1 -norecurse $xdc_file

# --- Build ---
launch_runs synth_1 -jobs 4
wait_on_run synth_1
if {[get_property PROGRESS [get_runs synth_1]] != "100%"} {
  error "Synthesis basarisiz!"
}
puts "OK: Synthesis tamam."

launch_runs impl_1 -to_step write_bitstream -jobs 4
wait_on_run impl_1
if {[get_property PROGRESS [get_runs impl_1]] != "100%"} {
  error "Implementation / bitstream basarisiz!"
}
puts "OK: Bitstream olusturuldu."

# --- PYNQ ciktilari ---
open_run impl_1

set bit_src [file join $proj_dir "${proj_name}.runs" impl_1 "${design_name}_wrapper.bit"]
set bit_dst [file join $out_dir i2c_gpio.bit]
file copy -force $bit_src $bit_dst
puts "OK: Bitstream kopyalandi -> $bit_dst"

# Adresi dosyaya yaz
set addr_fp [open [file join $out_dir i2c_gpio_addr.txt] w]
puts $addr_fp "AXI_GPIO_BASE=[get_property offset $seg]"
close $addr_fp

# fpga_manager icin byte-swapped .bin (PYNQ --direct modu)
set bif_dst [file join $out_dir i2c_gpio.bif]
set bin_dst [file join $out_dir i2c_gpio.bin]
set bif_fp [open $bif_dst w]
puts $bif_fp "all:\n\{\n\t[file join $out_dir i2c_gpio.bit]\n\}"
close $bif_fp

set bootgen_exe bootgen
foreach cand [list \
    [file join $::env(XILINX_VIVADO) bin bootgen.bat] \
    "C:/Xilinx/Vivado/2022.2/bin/bootgen.bat" \
    [file join $::env(XILINX_VIVADO) bin bootgen]] {
  if {[file exists $cand]} { set bootgen_exe $cand; break }
}
if {[catch {exec $bootgen_exe -image $bif_dst -arch zynq -process_bitstream bin -o $bin_dst -w} err]} {
  puts "UYARI: bootgen .bin uretemedi: $err"
} else {
  puts "OK: fpga_manager bin -> $bin_dst"
}

set hwh_src [file join $proj_dir "${proj_name}.gen" sources_1 bd $design_name hw_handoff ${design_name}.hwh]
set hwh_dst [file join $out_dir i2c_gpio.hwh]
if {[file exists $hwh_src]} {
  file copy -force $hwh_src $hwh_dst
  puts "OK: HWH (XML) -> $hwh_dst"
} else {
  puts "UYARI: $hwh_src bulunamadi"
}

puts ""
puts "=============================================="
puts " BITTI!"
puts " Karta kopyala: i2c_gpio.bit  i2c_gpio.bin  i2c_gpio.hwh"
puts " AXI GPIO base : [get_property offset $seg]  (SDA=bit0, SCL=bit1)"
puts "=============================================="

close_project
