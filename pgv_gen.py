import csv
import math
import argparse
import sys
import os

def parse_csv(filepath):
	"""
	讀取並解析 CtrlCode.csv，轉換為 1-bit 二進位位元流 (Bitstream)
	"""
	bitstream = []
	
	if not os.path.exists(filepath):
		raise FileNotFoundError(f"找不到指定的輸入檔案: {filepath}")

	# 使用 utf-8-sig 自動處理可能帶有 BOM 的 CSV 檔案
	with open(filepath, mode='r', encoding='utf-8-sig') as f:
		reader = csv.DictReader(f)
		
		# 驗證 CSV 標頭是否正確
		required_fields = ['Data Name', 'Bit Width', 'Direction', 'Value']
		if not all(field in reader.fieldnames for field in required_fields):
			raise KeyError(f"CSV 標頭缺失或格式錯誤。必須包含: {', '.join(required_fields)}")

		for line_idx, row in enumerate(reader, start=2):
			try:
				name = row.get('Data Name', f'Row_{line_idx}')
				bit_count = int(row['Bit Width'])
				direction = int(row['Direction'])
				value = int(row['Value'])
			except ValueError as e:
				raise ValueError(f"第 {line_idx} 行資料解析失敗 (請確認數值皆為整數): {e}")

			# 異常處理：檢查數值是否為負數，或是否超過位元數能表示的最大值
			if value < 0:
				raise ValueError(f"數值錯誤: 第 {line_idx} 行 ({name}) 數值不能為負數 ({value})。")
			if value >= (1 << bit_count):
				raise ValueError(f"溢位錯誤: 第 {line_idx} 行 ({name}) 的數值 {value} 超出 {bit_count} bits 可表示的範圍。")

			# 轉換為指定位元數長度的二進位字串 (補零)
			bin_str = format(value, f'0{bit_count}b')
			
			if direction == 1:
				bits = [int(b) for b in bin_str]			# start output from MSB
			elif direction == 0:
				bits = [int(b) for b in reversed(bin_str)]	# start output from LSB
			else:
				raise ValueError(f"方向值錯誤: 第 {line_idx} 行 ({name}) 的方向為 {direction}，僅接受 0 或 1。")

			bitstream.extend(bits)

	return bitstream

def generate_pgv(bitstream, output_file, enable_reset=False, enable_write=False, enable_read=False):
	"""
	依據 Acute Pattern Generator No Time Stamp 格式規範產生 .pgv 檔案
	"""
	total_bits = len(bitstream)
	if total_bits == 0:
		raise ValueError("轉換後的 Bitstream 為空，無有效資料可生成波形。請檢查 CSV 內容。")

	with open(output_file, mode='w', encoding='utf-8') as f:
		
		# 1. 宣告輸入腳位 (順序必須與 Pattern 對應)
		f.write(f"INPUTS PG_Function CLK_M CLK_S addr scan_in EN_SCAN_IN RST_CKT RST_CNT EN_SCAN_OUT;\n")
		
		# 2. 腳位通道對應 (ASSIGN)
		# addr 固定從 Channel 0 開始
		current_ch = 0
		f.write(f"ASSIGN addr 0..7;\n")
		f.write(f"ASSIGN CLK_M 8;\n")
		f.write(f"ASSIGN CLK_S 9;\n")
		f.write(f"ASSIGN scan_in 10;\n")
		f.write(f"ASSIGN EN_SCAN_IN 11;\n")
		f.write(f"ASSIGN RST_CKT 12;\n")
		f.write(f"ASSIGN RST_CNT 13;\n")
		f.write(f"ASSIGN EN_SCAN_OUT 14;\n\n")
		
		# 寫入標頭、模式與頻率宣告
		f.write("RADIX AUTO;\n")
		f.write("FREQUENCYMODE INTERNAL;\n")
		f.write("FREQUENCY 1 MHz;\n\n")

		# 3. 輸出波形資料 (每列代表 1 us)
		f.write("PATTERN\n")

		def write_pattern_row(clk_m=0, clk_s=0, addr=0, scan_in=0, en_scan_in=0, rst_ckt=0, rst_cnt=0, en_scan_out=0):
			# PG_Function 欄位固定輸出 000h
			f.write(f"000h {clk_m} {clk_s} {addr:4d} {scan_in} {en_scan_in} {rst_ckt} {rst_cnt} {en_scan_out}\n")
		
		def write_pattern_row_idle(n):
			for _ in range(n):
				f.write(f"000h 0 0 {0:4d} 0 0 0 0 0 // Idle\n")

		# PG function setting ############################################
		write_pattern_row_idle(15)
		f.write(f"8FFh 0 0 {0:4d} 0 0 0 0 0 //	(MOV RL, 255)\n")
		f.write(f"2FFh 0 0 {0:4d} 0 0 0 0 0 // 	(MOV RH, 255)\n")
		f.write(f"900h 0 0 {0:4d} 0 0 0 0 0 //	OE 65535    \n")
		write_pattern_row_idle(10)
		##################################################################
		
		# [階段一] Reset 階段
		if enable_reset:
			for _ in range(20):
				write_pattern_row(rst_ckt=1, rst_cnt=1)
			write_pattern_row_idle(10)

		# [階段二] Scan-IN 階段 ###########################################
		if enable_write:
			for i, bit_val in enumerate(bitstream):
				# 每個 bit 的週期為 10 us (10 列)
				for j in range(10):
					clk_m_val = 1 if 3 <= j <= 6 else 0
					if i == 0:
						clk_s_val = 1 if j in (8, 9) else 0
					else:
						clk_s_val = 1 if j in (0, 1, 8, 9) else 0
					
					write_pattern_row(
						clk_m=clk_m_val, 
						clk_s=clk_s_val, 
						addr=i, 
						scan_in=bit_val, 
						en_scan_in=1
					)

			# 確保最後一個 bit 的 CLK_S Pulse 完整輸出
			write_pattern_row(clk_m=0, clk_s=1, en_scan_in=1)
			write_pattern_row(clk_m=0, clk_s=1, en_scan_in=1)
			write_pattern_row_idle(10)

			# [階段三] 鎖存與結束階段
			# 發送一組完整的鎖存訊號，並將 EN_SCAN_IN 拉回 0
			for j in range(30):
				clk_m_val = 1 if 13 <= j <= 16 else 0
				clk_s_val = 1 if 18 <= j <= 21 else 0
				write_pattern_row(
					clk_m=clk_m_val, 
					clk_s=clk_s_val
				)

			# 結束訊號：將 EN_SCAN_IN 拉回 0，完成整體波形輸出
			write_pattern_row_idle(20)

			for _ in range(20):
				write_pattern_row(rst_ckt=0, rst_cnt=1)
			write_pattern_row_idle(10)

		#  Wait for counting #############################################
		if enable_write and enable_read:
			# write_pattern_row_idle(54500)
			write_pattern_row_idle(44724)

		# [階段二] Scan-OUT 階段 ##########################################
		if enable_read: 
			for j in range(20):
				clk_m_val = 1 if 3 <= j <=  6 else 0
				clk_s_val = 1 if 8 <= j <= 11 else 0
				write_pattern_row(
					clk_m=clk_m_val, 
					clk_s=clk_s_val
				)

			addr = 9
			for i in range(4):
				for j in range(40):
					for k in range(10):
						clk_m_val = 1 if 3 <= k <= 6 else 0
						if i == 0 and j == 0:
							clk_s_val = 1 if k in (8, 9) else 0
						else:
							clk_s_val = 1 if k in (0, 1, 8, 9) else 0
						if k == 0 and (j % 4) == 0:
							addr = 9 if j == 0 else addr - 1

						write_pattern_row(
							clk_m=clk_m_val, 
							clk_s=clk_s_val, 
							addr=addr, 
							en_scan_out=1
						)
						
			write_pattern_row(clk_m=0, clk_s=1, en_scan_out=1)
			write_pattern_row(clk_m=0, clk_s=1, en_scan_out=1)
			write_pattern_row_idle(10)

def main():
	parser = argparse.ArgumentParser(description="Acute PGV Vector Generator (自動轉換 CSV 為 PGV)")
	parser.add_argument('-i', '--input', default='CtrlCode.csv', help="輸入的 CSV 檔案名稱 (預設: CtrlCode.csv)")
	parser.add_argument('-o', '--output', default='output.pgv', help="輸出的 PGV 檔案名稱 (預設: output.pgv)")
	parser.add_argument('-R', '--reset', action='store_true', help="啟用一開始的 Reset 階段 (若無此參數則不安插 Reset)")
	parser.add_argument('-w', '--write', action='store_true', help="啟用寫入資料階段")
	parser.add_argument('-r', '--read', action='store_true', help="啟用讀出資料階段")

	args = parser.parse_args()

	try:
		print(f"[*] 正在讀取並解析輸入檔案: {args.input} ...")
		bitstream = parse_csv(args.input)
		total_bits = len(bitstream)
		print(f"[*] 解析完成。總共提取出 {total_bits} bits 的資料序列。")

		print(f"[*] 正在依據時序規範生成 PGV 波形檔...")
		generate_pgv(bitstream, args.output, enable_reset=args.reset, enable_write=args.write, enable_read=args.read)
		
		print(f"[+] 成功輸出檔案: {args.output}")
		print("[+] 執行完畢！")

	except Exception as e:
		print(f"\n[!] 執行失敗: {e}", file=sys.stderr)
		sys.exit(1)

if __name__ == '__main__':
	main()