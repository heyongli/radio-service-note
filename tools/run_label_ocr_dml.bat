@echo off
rem run_ic_ocr_dml.bat - Windows DirectML GPU OCR (全类别)
rem 用法: 双击或命令行运行

cd /d C:\Users\radio\radio-service-note

C:\Users\radio\py311\python.exe tools\label_ocr_scan\label_ocr_scan_dml.py ^
    --crops-index projects\icom2200h\crops\rectangle\crops_index.json ^
    --pcb projects\icom2200h\render\pcb-top-600-1.png ^
    --view top ^
    --rots 0,90,270 ^
    --categories all

echo Done.
pause
