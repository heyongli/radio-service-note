
# radio knowledge — 无线电通用知识库

> 项目无关的通用无线电知识(RX/TX 信号链、控制原理、典型架构、信号规格)。
> 工程特定的设计内容请放 `projects/<机型>/radio-design.md`。

参考: ARRL Handbook, LibreTexts Microwave and RF Design (Steer),
Analog Devices Basic Linear Design Chapter 4, ICOM IC-2200H Service Manual。

---

## 1. RX (接收) 信号链典型架构

### 1.1 超外差接收机 (superheterodyne)

**主流架构**, IC-2200H 采用单超外差(单 IF)。

```
ANT → Preselector(BPF) → RF-AMP → Mixer(LO注入) → IF BPF(Crystal Filter)
  → IF-AMP → Detector(Product Detector) → AF-AMP → SPK
       ↑                                              ↓
     AGC 控制 RF/IF-AMP 增益                     Audio 滤波/Mute/Squelch
```

### 1.2 典型链路节点(信号流向 + 功能)

| 段 | 功能 | 典型器件 / 电路 |
|---|---|---|
| **1. Antenna Input** | 接收/发射共用, 阻抗匹配 50Ω | J11 (Main Unit J3), SMA |
| **2. Preselector / BPF** | 频段预选, 抑制镜像与带外强信号 | LC 带通, SAW, 陶瓷滤波器, CFWS450F |
| **3. RF Amplifier** | 低噪声前置放大 (LNA), 改善 NF | 3SK299 双栅 MOSFET, BJT (2SC), JFET |
| **4. Mixer** | 频率搬移 RF → IF | TA31136 (内置混频+检波), SA602, SBL-1 双平衡二极管环 |
| **5. IF Filter** | 信道选择, 抑制邻道 | 陶瓷滤波器 (FL-363), 晶体滤波器, 机械滤波器 |
| **6. IF Amplifier** | IF 段主增益, AGC 受控 | MC1350, TA31136 内部, 分立 BJT |
| **7. Detector** | FM/SSB/CW 解调 | 乘积检波器 (Product Detector), 鉴频器, 检波二极管 |
| **8. AF Amplifier** | 音频前置放大 | LM386, μPC1241, TDA2003 |
| **9. Squelch (SQL)** | 静噪门限 | 噪声检波 + 比较器, 来自 AF 噪声带 |
| **AGC** | 自动增益控制 | 检测 IF 幅度 → DC → 控 RF/IF-AMP 偏置 |
| **SQL ATT** | 静噪衰减 | 双栅 MOSFET 第二栅, AGC/SQL 共用 |

### 1.3 关键指标

- **灵敏度**: 0.1-0.5 μV (典型业余 HF/VHF)
- **选择性**: IF 滤波器带宽 (SSB 2.4kHz, CW 500Hz, FM 15kHz)
- **动态范围**: -130 dBm ~ +20 dBm
- **IP3**: 三阶交调截点, 衡量大信号处理能力
- **NF**: 噪声系数, 前级 LNA 决定整体 NF

---

## 2. TX (发射) 信号链典型架构

```
MIC → 语音放大 → 音频处理(压缩/滤波) → 调制器(SSB/CW/FM)
  → 边带滤波 → Mixer(上变频) → BPF → 驱动级 → PA → LPF → ANT
                       ↑
                     VFO/Carrier Osc (BFO)
```

### 2.1 关键节点

| 段 | 功能 | 典型器件 |
|---|---|---|
| **1. MIC Input** | 麦克风输入 | MIC 插座, 偏置电阻 |
| **2. Audio Preamp** | 麦克风放大 | LM358, 运放 |
| **3. Audio Filter** | 音频限带 (300-3000Hz) | 有源滤波 |
| **4. Modulator** | AM/SSB/CW 调制 | MC1496 平衡调制器, 双平衡二极管环 |
| **5. SSB Filter** | 边带滤波 (Xtal Filter) | 9MHz / 10.7MHz 晶体滤波器 |
| **6. Up-conversion Mixer** | IF → RF | SA602, 双栅 MOSFET |
| **7. BPF (TX)** | 抑制谐波 | LC 带通 |
| **8. Driver** | 前置驱动 | 2N3866, 2SC2290 |
| **9. PA** | 功率放大 | IRF511, 2SC2290, RD70HVF1 (VHF) |
| **10. LPF** | 谐波滤波 (LC π 型) | LC 低通 |
| **11. T/R Switch** | 收发切换 | 继电器, PIN 二极管 |

---

## 3. 控制 (control) 原理

### 3.1 PTT (push-to-talk)

- 物理: 按键接地 → 切换收发状态
- 控制链: PTT 键 → 收发切换继电器 → RX/TX 电源切换 → MIC 静音

### 3.2 squelch (SQL)

- 原理: 检测 AF 段的噪声带(无信号时噪声强)→ 比较阈值
- 类型: 载波电平, 噪声电平, CTCSS/DCS

### 3.3 AGC (automatic gain control)

- 接收: 检测 IF 输出幅度 → DC 反馈 → 控 RF/IF 偏置/衰减器
- 实现: PIN 二极管衰减器, 双栅 MOSFET 第二栅, 可变增益放大器
- 顺序: 后级先衰减, 然后前级(避免过载)

### 3.4 PLL / VCO / frequency synthesis

- 参考: TCXO (温补晶振) → PLL → VCO → LO (本振)
- IC-2200H 典型: DDS + PLL 混合

### 3.5 电源 (power supply)

```
DC IN (13.8V) → 保险丝 → 开关 → 主滤波 → 各路稳压:
  +5V (逻辑/MCU/显示)
  +8V (中频/混频)
  +13.8V (RF PA 直接)
  -8V (LCD bias, op-amp)
  +5V/3.3V (DDS/PLL)
```

---


## 4. 关键术语表

| 术语 | 英文 | 含义 |
|---|---|---|
| ANT | Antenna | 天线 |
| BPF | Band-Pass Filter | 带通滤波器 |
| LNA | Low Noise Amplifier | 低噪声放大器 |
| LO | Local Oscillator | 本振 |
| IF | Intermediate Frequency | 中频 |
| AF | Audio Frequency | 音频 |
| AGC | Automatic Gain Control | 自动增益控制 |
| SQL | Squelch | 静噪 |
| PLL | Phase-Locked Loop | 锁相环 |
| VCO | Voltage Controlled Oscillator | 压控振荡器 |
| DDS | Direct Digital Synthesis | 直接数字合成 |
| TCXO | Temperature Compensated Xtal Oscillator | 温补晶振 |
| PTT | Push-To-Talk | 按键通话 |
| PA | Power Amplifier | 功率放大器 |
| LPF | Low-Pass Filter | 低通滤波器 |
| DBM / dBm | Decibel milliwatt | 功率单位(0 dBm = 1 mW) |
| IP3 | Third-Order Intercept | 三阶交调截点 |
| NF | Noise Figure | 噪声系数 |
| RX | Receiver | 接收 |
| TX | Transmitter | 发射 |
| MIDI | Mixer/Demodulator/IF/Detector | 混频/解调/中频/检波组合 |
