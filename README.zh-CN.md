# CatSense V0

CatSense V0 是一个开源猫咪行为采集项圈原型。

它的目标不是一开始就做完整产品，而是先把最小闭环跑通：

```text
XIAO nRF52840 Sense -> IMU 加速度 -> BLE -> Python/网页采集器 -> CSV 数据 -> baseline 模型 -> 实时预测预览
```

V0 暂时不包含手机 App、云同步或量产外壳。当前重点是采集真实佩戴数据，验证猫咪行为识别的数据链路和本地训练流程。固件已加入“日常工作模式”的低功耗缓存雏形，但内部 flash 缓存很小，只适合验证机制。OTA 已接入网页：电脑后端可通过 BLE 直接刷写 `firmware.zip`，手机 nRF Connect / Bluefruit Connect 作为备用方案。

![CatSense V0 system flow](docs/assets/system-flow.svg)

## 常用命令

在仓库根目录运行：

```bash
make setup      # 创建 gateway/.venv 并安装 Python 依赖
make web        # 启动网页采集器，默认 0.0.0.0:8000
make check      # 运行轻量源码检查
make firmware   # 编译固件
make upload     # USB 烧录固件
make pipeline   # 检查数据、处理、训练和评估
```

真实采集数据、处理后数据和模型输出默认不会进入 Git。公开示例放在 `examples/`。

Windows 说明：`Makefile` 推荐在 Git Bash/MSYS 这类 shell 里使用，会自动识别
`%USERPROFILE%\.platformio\penv\Scripts\pio.exe`。如果用 PowerShell，可运行：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/check.ps1
```

## 当前功能

- XIAO nRF52840 Sense 固件
- 三轴加速度采样
- BLE UART 数据传输
- 电池电压读取
- Python 命令行采集器
- 网页实时采集和手动标记
- 数据质量报告
- baseline 模型训练
- 网页实时预测预览
- 预测平滑和切换门槛
- 固件采集模式 / 日常工作模式
- 日常模式内部 LittleFS 缓存和定时 BLE 上传窗口
- 网页直接刷写固件、进入 OTA/DFU 和固件包下载

当前模型是 6 类 checkpoint：

| CSV 标签 | 中文 |
| --- | --- |
| `rest` | 休息 |
| `parkour` | 跑酷 |
| `walk` | 走动 |
| `play` | 玩耍 |
| `groom` | 舔毛 |
| `eat` | 进食 |

## 硬件

- Seeed Studio XIAO nRF52840 Sense
- 板载 6 轴 IMU
- 支持 BLE 的 Mac、PC 或 Raspberry Pi
- USB 数据线，用于烧录和串口日志

注意：普通 XIAO nRF52840 没有 Sense 版本的板载 IMU。这个固件面向 XIAO nRF52840 Sense。

## 目录结构

```text
catsense-v0/
├── firmware/
│   └── xiao_nrf52840_sense/
├── gateway/
├── data/
│   └── raw/
├── models/
└── docs/
    └── zh/
```

## 中文文档

- [中文文档首页](docs/zh/index.md)
- [流程图](docs/zh/diagrams.md)
- [快速开始](docs/zh/quick_start.md)
- [系统原理](docs/zh/principles.md)
- [完整流程](docs/zh/workflow.md)
- [数据采集规范](docs/zh/data_collection.md)
- [数据处理和服务命令](docs/zh/data_processing.md)
- [固件 OTA 升级](docs/zh/ota.md)
- [BLE 协议](docs/zh/protocol.md)
- [建模说明](docs/zh/modeling.md)
- [当前状态](docs/zh/current_status.md)
- [问题排查](docs/zh/troubleshooting.md)
- [开源准备](docs/zh/open_source.md)
- [贡献指南](CONTRIBUTING.zh-CN.md)

## 烧录固件

安装 PlatformIO 后：

```bash
make firmware
make upload
```

打开串口监视器：

```bash
pio device monitor
```

期望看到：

```text
CatSense V0 boot
IMU init ok
Battery <mv> mV
BLE tx power 8 dBm
BLE advertising
```

## OTA 升级

GitHub Actions 会在每次 push 和 PR 时编译固件，并上传 `catsense-v0-firmware` 产物。进入仓库的 `Actions` 页面，打开最新 `CI` 运行即可下载。产物里包含：

- `catsense-v0-firmware.zip`：用于网页 OTA/DFU、nRF Connect 或 Bluefruit Connect。
- `catsense-v0-firmware.hex`：用于 USB 烧录或调试流程。

网页“设备管理”面板提供：

- “刷写固件”：电脑后端通过 BLE 直接刷入当前 `firmware.zip`，推荐优先使用。
- “慢速重试”：直接刷写失败时使用，写包更慢但更稳。
- “下载固件包”：下载当前编译生成的 `firmware.zip`。
- “进入 OTA”：让设备重启到 BLE DFU/bootloader 模式。
- “重启 DFU”：固件已刷入但仍停在 bootloader 时，发送重启命令并等待 `CatSense-V0` 恢复广播。

如果网页直接刷写仍失败，可以进入 OTA 后，用手机 `nRF Connect` 或 `Adafruit Bluefruit Connect` 选择下载的 `firmware.zip` 刷写。详细步骤见 [固件 OTA 升级](docs/zh/ota.md)。

## 启动网页采集器

```bash
make setup
make web
```

终端会打印电脑和手机访问地址。手机必须和电脑在同一个 Wi-Fi 下。

网页采集器会保存：

```text
data/raw/{cat_id}/manual_{YYYYMMDD}.csv
```

默认保存方式是“按天一个 CSV”，同一天多次开始/停止都会追加到同一个文件。也可以在网页里切换成“每次一个 CSV”或“只预览不保存”。

手动点击行为按钮开始标记，再点同一个按钮结束标记。预测结果只用于观察，不会写入原始 CSV。

## 网页数据处理和训练

采集结束后先点“停止记录”，然后在网页底部“数据处理”面板操作：

- “检查数据”：查看每类秒数、采样率、断点和异常。
- “构建数据”：生成统一样本和训练特征。
- “训练模型”：生成 baseline 模型并重新加载实时预测。
- “Session 评估”：按 CSV/session 留出测试，检查泛化效果。
- “一键全部”：按顺序完成以上步骤。

输出：

```text
data/processed/unified_samples.csv
data/processed/features.csv
data/processed/windows.csv
models/baseline_centroid.json
models/baseline_report.txt
models/session_eval_report.txt
```

当前 baseline 只用于验证流程，不代表最终模型效果。
