
# OCR 协同计算集群说明

本文件记录参与 OCR 协同计算的各机器信息、任务分工与连通方式。
维护更新于 2026-09-14。

## 物理拓扑

```
┌─ Windows 宿主 (Hyper-V, Default Switch NAT 172.28.32.0/20) ──────┐
│  LXC "radio-service-note" = 本机  172.28.46.227/20  (MAC 00:15:5d=Hyper-V) │
└───────────────────────────────────────────────────────┬───────────┘
                        (两个虚拟网段互不相通, 靠转发, 间歇 No route)
┌─ Proxmox VE 宿主 "yvr"  10.0.0.100/24  vmbr0 (root/plus1234) ─────┐
│  LXC 121 "llm" OCR从机  10.0.0.121/24  14核 E5-2697v3/100G ★       │
│  VM 200 "vpn"  stopped                                             │
└────────────────────────────────────────────────────────────────────┘
```

- **本机不是 Proxmox 管理的容器**: 它是 Windows 宿主上 Hyper-V 的虚拟机
  (OUI `00:15:5d` = Microsoft, 网关 172.28.32.1 同 MAC), 网段
  `172.28.32.0/20` 由 Hyper-V 自动 NAT 分配。
- **Proxmox 宿主 yvr(10.0.0.100) 管着 llm(10.0.0.121) 从机和 VPN VM(200)**:
  `pct list` 只有 121, `qm list` 只有 200。llm 是 LXC(veth 桥接 vmbr0,
  gw=10.0.0.1)。**宿主 2026-09-14 20:24 刚重启过** → 之前所有 No route 抖动。
- 本机↔Proxmox/llm 之间隔着 Windows Hyper-V 网络和 Proxmox 桥, 两个虚拟网段
  不互通, 只能靠中间某跳转发 → 表现为间歇 No route to host。
- **可靠管法**: SSH 到宿主 `ssh root@10.0.0.100`(root/plus1234), 在宿主上:
  - `pct list`(LXC) / `qm list`(VM) / `qm status 200`
  - `pct enter 121` / `pct exec 121 -- <cmd>` : llm 从机内执行
  - 从机 llm 内: /opt/pcbocr + /opt/ocrvenv, 部署同主控
- llm 已有公网 IPv6(SLAAC `2604:3d08:6883:3500:.../64` dynamic), 宿主 vmbr0
  IPv6 转发已开(forwarding=1), 本机暂无全局 IPv6(只有 link-local)。

## 宿主 yvr 无故硬断电诊断 (2026-09-14)

- **机器**: **Dell Precision Tower 5810** (Xeon E5-2697v3, BIOS A31/2019)。
  自带 amdgpu+nouveau 两块 GPU, dell_smm(SMM) 风扇驱动已加载但**只读**、
  无 pwm/fan 控制通路; BIOS 默认"静音"散热策略。
- **根因**: 满载时 CPU 温度冲高 → 触发硬件热保护(thermal trip) **瞬间断电**,
  内核来不及记日志 → 表现为日志戛然而止、last 显示 crash、无 panic。
  重启都在我拉起高负载任务后 (20:36/21:23 启动 host600 后立即崩) 完全吻合;
  用户"听不到风扇启动"证实风扇被 BIOS 锁在低速。**非网络/非任务强度本身。**
- **排除项**: SMART 磁盘 PASSED; EDAC 内存错误 0; 无 MCE/Oops/panic; pstore 空;
  无 ACPI power 事件; corosync 未启用; 无 IP/ARP 冲突(邻居表干净); 10.0.0.42
  = 本机 Windows 宿主的 NAT 出口(MAC 54:bf:64), 非外敌。
- **处置（二选一/都做）**:
  1. **BIOS 改风扇策略**: 开机 F2 → Maintenance/Advanced → 关闭静音, 散热设
     Performance/全速 (5810 无独立风扇菜单时找 Thermal/Performance 档)。
  2. **OS 强制全速(不重启)**: `modprobe dell_smm fan_control=1` 后经
     `/proc/i8k` 写入强制转速; 或装 i8kutils(`i8kfan 2 2`)/fancontrol。
     A31 BIOS 的 SMM 接口可写, 此路径可行。
  3. **物理清灰/查风扇**: 5810 久置易积灰堵死 CPU 散热器侧风扇。
- **临时策略**: 修好散热前**不在宿主跑满载**(jobs 高), 长任务靠本机 8 核;
  宿主仅低频轻任务。
- **实测定论 (2026-09-14 21:30)**:
  - **注意**: 用户指出 5810 的 **CPU 是被动塔式散热器(无自带风扇)**, CPU 散热靠
    **机箱风道风扇**(rear 抽风 + front 进风)。
  - **fan2_input=0 RPM 恒定(多次复读, 非偶发)** = 一个机箱风道风扇(前/后)停转/
    没插/断路 → 塔式散热器风道断流 → 满载积热。fan1=1007、fan3=586、fan4=608 正常。
  - 8 线程 ACPI temp1 压力 12s 内 50→56°C (斜率陡)。
  - 卸载重载 dell_smm_hwmon restricted=0 + 直写 /proc/i8k 均被 **SMM 固件
    拒绝(write=-22)** → **A31 BIOS 固件锁死风扇在自动模式, 软件无法控扇**。
  - **结论**: 满载 28T 时热量排不出 → thermal trip 硬断电。非网络非软件。
  - **正解(需人工开盖)**: 找 fan2 对应的机箱风扇, 检查其供电线是否插上/
    卡死/进灰; 复插+清灰。可同时 F2 把散热改 Performance。
  - GPU 独立无影响: 03:00.0 AMD FirePro W5100(amdgpu), 04:00.0 NVIDIA
    Quadro P400(nouveau, fan=1624RPM 100%)。

### 5810 BIOS/散热处置清单 (2026-09-14, 供人工照做)

- **机器识别**: Dell Precision Tower 5810, 服务标签 **87DFGB2**,
  主板 0HHV7N, BIOS A31 (2019-06-05)。Dell 支持:
  https://www.dell.com/support (按服务标签 87DFGB2)。
- **现状**: A31 已是该机后期 BIOS (2019); fwupd 检测
  **"UEFI capsule updates not available"** → 5810 无法在 Linux 软件层
  刷 BIOS。需走**BIOS 菜单/U盘/Windows 工具**。
- **散热根因**: **fan2(CPU 风扇2) = 0 RPM(停转/没插)**; fan1 满载也锁死
  1001-1002 RPM 不升速; 8 线程 12s 温度 50→56°C。SMM 固件拒绝软件控扇
  (write=-22)。英文: fan2 tach 0 + fan gating locked at ~1000RPM.
- **A. 物理(最优先)**: 开盖确认 CPU 散热器两个风扇的供电线是否都插上,
  fan2 若没插/卡死 → 复位/清灰; 检查散热器积灰堵塞。
- **B. BIOS 设置**: F2 → 找 Thermal/散热/风扇档, 从"静音/自动"改
  **Performance/全速**; 保存重启后 `cat /sys/class/hwmon/hwmon0/fan*_input`
  验证 fan1/fan2 转速是否随负载变化。
- **C. 升级 BIOS(可选)**: Dell 支持服务标签 87DFGB2 下载最新 .exe →
  解出 firmwares 用 F12 (BIOS Flash Update / USB) 刷; 或 Windows 环境
  Dell Command Update。升级不解决 fan2 物理停转, 但可能改善策略。
- **验证命令**:
  - 温度: `cat /sys/class/thermal/thermal_zone0/temp` (÷1000 得 °C)
  - 风扇: `for i in 1 2 3 4; do cat /sys/class/hwmon/hwmon0/fan${i}_input; done`
  - BIOS: `dmidecode -t bios | grep -E 'Version|Release'`

## 计算策略 (2026-09-14 定案)

- **宿主 yvr 与 llm(121) 命运绑定**: 121 是 yvr 上的 LXC 容器, 宿主掉电时两者
  一起断。两者都不可靠。
- **唯一稳定节点 = 本机** (Hyper-V 上, Windows 宿主承载, 不掉电): **全部长任务
  在本机跑**。本机 8 核 Xeon W-2123 @3.6G。
- **本机 GPU 直通 (规划, 待启用 GPU-P)**: 本机容器当前**无任何 GPU**
  (无 /dev/dri、无 nvidia-smi、onnxruntime 仅 CPUExecutionProvider)。
  Windows 宿主有 NVIDIA 卡, 计划用 **Hyper-V GPU-P (GPU Partitioning)** 直通:
  - Windows 侧启用: `Get-VMPartitionableGpu` → `Add-VMGpuPartitionAdapter -VMName <本VM名>`
    → `Set-VMGpuPartitionAdapter` 配置 → 启动增强会话。
  - Linux 侧: 装 NVIDIA 驱动 + CUDA onnxruntime (onnxruntime-gpu), 换
    CUDAExecutionProvider; PP-OCRv5 db+rec 推理显著提速。
  - **注意**: GPU-P 需 Windows 侧 Hyper-V 管理员操作 + VM 重启, 已定用户愿意直通。

- **宿主 yvr 与 llm(121) 命运绑定**: 121 是 yvr 上的 LXC 容器, 宿主掉电时两者
  一起断。两者都不可靠。
- **唯一稳定节点 = 本机** (Hyper-V 上, Windows 宿主承载, 不掉电): **全部长任务
  在本机跑**。本机 8 核 Xeon W-2123 @3.6G。
- **多进程并行**: 工具 v0.3.0 新增 `--jobs N` 在 stage1 用多进程并行扫描
  tile(默认 1=串行)。本机 8 核跑 `--jobs 8`, 600dpi 全板可数倍提速。
- **进度 + 中间结果**: `--progress`(每块完成 stderr 输出 n/total、%、elapsed、
  ETA、hits) + `--checkpoint PATH [--checkpoint-every N]`(周期性落盘
  raw_stage1/raw_stage2, 可 `--reuse-*` 续跑; Ctrl-C 自动保存)。
- **本地运行归档**: `ocr_runs/bot600_work/(log|runs)`、`ocr_runs/cp/`。
  例: bot600 全板 5100×6600 jobs=8 + v4,v5s + 1.5x + 3朝向。

## 双机全板并行 (2026-09-14 21:23 启动, llm 已停)

- **已停 llm(121)**: 负载 0.00、无任务, 停掉把 28 线程全部还给宿主。
- **宿主 yvr 用 28 线程跑 top600**(jobs=14 平滑起步): pid 10519,
  stage1 v4,v5s + 900/350 tile + 1.5x + 3朝向 + stage2 v4,v6 + 1.5x。
  日志 `/opt/pcbocr/logs/host600.log`, checkpoint `/opt/pcbocr/cp/`。
  (首启 v5 rec_server.onnx 被上次断电损坏, 自动重下 80MB)
- **本机 8 核跑 bot600**(jobs=8): pid 152080, 同参数。日志
  `ocr_runs/bot600_work/bot600.log`, checkpoint `ocr_runs/cp/`。
  进度 6.7%@180s ETA~42min(8核) → 提速: 宿主 28t 远快于本机 8t。
- **平滑负载策略**: 勿刚启动就 jobs=28 全满载(怀疑电源功率余量), 先 14
  稳定再逐级上调; 避免瞬时峰值再触发掉电。
- **运维建议**: 检查供电/机房UPS; 或在宿主电源设置/BIOS 打开"断电后自动
  上电"(Power-on after AC loss); 任务改放 121(llm LXC, 宿主重启不杀容器)
  或本机。

## 节点总览

| 节点 | 角色 | 地址 | CPU | 内存 | 磁盘 | Python | 状态 |
|------|------|------|-----|------|------|--------|------|
| radio-service-note (本机) | 主控 / 渲染 / 归档 | 172.28.46.227/20 | 8 核 Xeon W-2123 @3.6G | 27 GiB | 1TB (944G 空闲) | 3.12.3 | 在线 |
| pcb-ocr-121 (从机) | OCR 计算从机 | 10.0.0.121/24 | 14 核 Xeon E5-2697 v3 @2.6G | 99 GiB | 196G (171G 空闲) | 3.11.2 (venv) | 在线(网络间歇) |

## 从机 10.0.0.121

- 连接: `sshpass -p 'plus1234' ssh -o StrictHostKeyChecking=no root@10.0.0.121`
- 工作目录: `/opt/pcbocr/` (render/ 底图, runs/ 结果, tools/ 工具)
- Python venv: `/opt/ocrvenv/` (rapidocr 3.9.2, rapidocr-onnxruntime 1.4.4,
  opencv-python 5.0.0.93 headless, scipy 1.17.1, pillow 12.3.0, numpy 2.4.6)
- 模型: v4 (rapidocr_onnxruntime) 已内置; v5s server 首次运行自动从
  modelscope 下载至 venv site-packages (网络可达 modelscope.cn).
- 系统依赖: 需 `libgl1 libglib2.0-0` (已装, 否则 opencv 报 libGL.so.1).
- 本机到从机路由: **无 10.0.0.0/24 静态路由** (容器无 NET_ADMIN), 连通靠
  宿主机网络自愈, 会出现间歇 No route to host; 重试即可。

## 任务分工

- **主控 (本机)**: 渲染底图 (pdftoppm 600/300dpi), 工具开发/参数调优,
  waypoints 生成, SVG/PNG 标注, 结果合并入 components_index, 归档。
- **从机 (10.0.0.121)**: 重负载全板扫描 (600dpi 多引擎多朝向), 与本地
  并行为事后合并; 本地小图快速试参, 从机跑最终大图。

## 协同工作流

1. `scp` 更新 `tools/zref/ai_ocr_eval/ai_refdes_ocr.py` 与待扫底图到从机。
2. 远程执行 `./slave_remote.sh <top600|bot600|smoke|check|pull>`。
3. `./slave_remote.sh pull` 可读各任务 result.json hits 数(远程已含该脚本)。
4. 结果按 `--out-dpi 600` 空间回传, 主控 ÷2 转 300dpi 入 components_index,
   坐标系转换参照 architecture.md §5A (每视图独立, 不得混用)。

## 从机任务类型

| 任务 | 底图 | dpi | 引擎 | tile | 备注 |
|------|------|-----|------|------|------|
| smoke | pcb-top-300 | 300 | v4 stage1 | 1000/200 | 冒烟验证 (~22s) |
| top600 | pcb-top-600 | 600 | v4,v5s s1 / v4,v6 s2 | 900/350, upscale1.5, rots 0/90/270 | 全板高精度 |
| bot600 | pcb-bot-600 | 600 | 同上 | 同上 | 背面全板高精度 |

工具参数完整清单见 `tools/zref/ai_ocr_eval/ai_refdes_ocr.py --help`。