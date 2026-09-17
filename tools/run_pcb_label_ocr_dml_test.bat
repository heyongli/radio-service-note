@echo off
rem run_ic_ocr_dml_test.bat - 测试 DirectML GPU 是否真正在跑

cd /d C:\Users\radio\radio-service-note

echo === GPU Load BEFORE OCR ===
powershell -Command "Get-Counter '\GPU Engine(*)\Utilization Percentage' -ErrorAction SilentlyContinue | Select-Object -ExpandProperty CounterSamples | Where-Object {$_.CookedValue -gt 0} | Select-Object InstanceName, CookedValue | Format-Table -AutoSize"

echo === Running OCR with DML ===
C:\Users\radio\py311\python.exe tools\pcb_label_ocr\pcb_label_ocr_dml.py ^
    --crops-index projects\icom2200h\crops\rectangle\crops_index.json ^
    --pcb projects\icom2200h\render\pcb-top-600-1.png ^
    --view top ^
    --rots 0,90,270 ^
    --categories ic ^
    --out projects\icom2200h\crops\rectangle\ic_ocr_results.json

echo === GPU Load AFTER OCR ===
powershell -Command "Get-Counter '\GPU Engine(*)\Utilization Percentage' -ErrorAction SilentlyContinue | Select-Object -ExpandProperty CounterSamples | Where-Object {$_.CookedValue -gt 0} | Select-Object InstanceName, CookedValue | Format-Table -AutoSize"

echo Done.
pause
