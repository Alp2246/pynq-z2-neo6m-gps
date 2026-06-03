# =============================================================================
# PYNQ-Z2 GPS UART overlay - otomatik Vivado build
# Vivado 2022.2: Tools -> Run Tcl Script... veya run_build.bat
#
# Cikti: ../output/gps_uart.bit + gps_uart.hwh
# =============================================================================

set origin_dir [file normalize [file dirname [info script]]]
set proj_root  [file normalize [file join $origin_dir ..]]
set proj_name  gps_uart
set proj_dir   [file join $origin_dir build $proj_name]
set out_dir    [file join $proj_root output]
set preset_tcl [file join $proj_root "pynq-z2_v1.0.xdc" "PYNQ-Z2 v1.0.tcl"]
set xdc_file   [file join $origin_dir rpi_uart.xdc]
set board_repo [file join $proj_root pynq-z2]

file mkdir $out_dir
file mkdir [file join $origin_dir build]

puts "=============================================="
puts " PYNQ-Z2 GPS UART overlay build"
puts " Project : $proj_dir"
puts " Output  : $out_dir"
puts "=============================================="

# --- Proje olustur ---
create_project $proj_name $proj_dir -part xc7z020clg400-1 -force
set_property target_language Verilog [current_project]

# Board dosyalari (varsa otomatik preset icin)
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

# PL tarafi icin GP0 clock/reset acik olsun
set_property -dict [list \
  CONFIG.PCW_USE_M_AXI_GP0 {1} \
  CONFIG.PCW_EN_CLK0_PORT {1} \
  CONFIG.PCW_EN_RST0_PORT {1} \
  CONFIG.PCW_FPGA0_PERIPHERAL_FREQMHZ {100} \
] $ps7

# AXI UART Lite (9600 baud - NEO-6M varsayilan)
create_bd_cell -type ip -vlnv xilinx.com:ip:axi_uartlite:2.0 axi_uartlite_0
set_property -dict [list CONFIG.C_BAUDRATE {9600}] [get_bd_cells axi_uartlite_0]

# AXI Interconnect
create_bd_cell -type ip -vlnv xilinx.com:ip:axi_interconnect:2.1 axi_interconnect_0
set_property -dict [list CONFIG.NUM_MI {1}] [get_bd_cells axi_interconnect_0]

# Reset controller
create_bd_cell -type ip -vlnv xilinx.com:ip:proc_sys_reset:5.0 proc_sys_reset_0

# AXI baglantilari
connect_bd_intf_net [get_bd_intf_pins processing_system7_0/M_AXI_GP0] [get_bd_intf_pins axi_interconnect_0/S00_AXI]
connect_bd_intf_net [get_bd_intf_pins axi_interconnect_0/M00_AXI] [get_bd_intf_pins axi_uartlite_0/S_AXI]
assign_bd_address [get_bd_addr_segs axi_uartlite_0/S_AXI/Reg]

# Clock
connect_bd_net [get_bd_pins processing_system7_0/FCLK_CLK0] \
  [get_bd_pins processing_system7_0/M_AXI_GP0_ACLK] \
  [get_bd_pins processing_system7_0/M_AXI_GP1_ACLK] \
  [get_bd_pins processing_system7_0/S_AXI_GP0_ACLK] \
  [get_bd_pins processing_system7_0/S_AXI_HP0_ACLK] \
  [get_bd_pins processing_system7_0/S_AXI_HP2_ACLK] \
  [get_bd_pins axi_interconnect_0/ACLK] \
  [get_bd_pins axi_interconnect_0/S00_ACLK] \
  [get_bd_pins axi_interconnect_0/M00_ACLK] \
  [get_bd_pins axi_uartlite_0/s_axi_aclk] \
  [get_bd_pins proc_sys_reset_0/slowest_sync_clk]

# Reset
connect_bd_net [get_bd_pins processing_system7_0/FCLK_RESET0_N] [get_bd_pins proc_sys_reset_0/ext_reset_in]
connect_bd_net [get_bd_pins proc_sys_reset_0/interconnect_aresetn] [get_bd_pins axi_interconnect_0/ARESETN]
connect_bd_net [get_bd_pins proc_sys_reset_0/peripheral_aresetn] \
  [get_bd_pins axi_interconnect_0/S00_ARESETN] \
  [get_bd_pins axi_interconnect_0/M00_ARESETN] \
  [get_bd_pins axi_uartlite_0/s_axi_aresetn]

# UART dis pina cikar (RPi header pin 8/10)
create_bd_intf_port -mode Master -vlnv xilinx.com:interface:uart_rtl:1.0 uart_rtl
connect_bd_intf_net [get_bd_intf_ports uart_rtl] [get_bd_intf_pins axi_uartlite_0/UART]

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
set bit_dst [file join $out_dir gps_uart.bit]
file copy -force $bit_src $bit_dst
puts "OK: Bitstream kopyalandi -> $bit_dst"

# fpga_manager icin byte-swapped .bin (PYNQ --direct modu)
set bif_dst [file join $out_dir gps_uart.bif]
set bin_dst [file join $out_dir gps_uart.bin]
set bif_fp [open $bif_dst w]
puts $bif_fp "all:\n\{\n\tgps_uart.bit\n\}"
close $bif_fp
set bootgen [file join [file dirname [info script]] .. ..]
if {[file exists [file join $::env(XILINX_VIVADO) bin bootgen]]} {
  set bootgen_exe [file join $::env(XILINX_VIVADO) bin bootgen]
} elseif {[file exists C:/Xilinx/Vivado/2022.2/bin/bootgen.exe]} {
  set bootgen_exe C:/Xilinx/Vivado/2022.2/bin/bootgen.exe
} else {
  set bootgen_exe bootgen
}
if {[catch {exec $bootgen_exe -image $bif_dst -arch zynq -process_bitstream bin -o $bin_dst} err]} {
  puts "UYARI: bootgen .bin uretemedi: $err"
} else {
  puts "OK: fpga_manager bin -> $bin_dst"
}

# PYNQ icin XML handoff dosyasi (write_hwdef ZIP uretir, kullanma!)
set hwh_src [file join $proj_dir "${proj_name}.gen" sources_1 bd $design_name hw_handoff ${design_name}.hwh]
set hwh_dst [file join $out_dir gps_uart.hwh]
if {[file exists $hwh_src]} {
  file copy -force $hwh_src $hwh_dst
  puts "OK: HWH (XML) -> $hwh_dst"
} else {
  puts "UYARI: $hwh_src bulunamadi"
}

puts ""
puts "=============================================="
puts " BITTI!"
puts " Dosyalari PYNQ kartina kopyala:"
puts "   gps_uart.bit"
puts "   gps_uart.bin"
puts "   gps_uart.hwh"
puts "   neo_gps_pynq.py"
puts " Kartta: python3 neo_gps_pynq.py --overlay gps_uart.bit"
puts "=============================================="

close_project
