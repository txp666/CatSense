# 快速开始

这篇文档用于从零跑通 CatSense V0。

## 1. 准备硬件

需要：

- Seeed Studio XIAO nRF52840 Sense
- USB 数据线
- 锂电池
- 电脑或树莓派，要求支持 BLE

确认板子是 `XIAO nRF52840 Sense`。普通 XIAO nRF52840 没有板载 IMU，不能直接运行这个项目。

## 2. 烧录固件

```bash
make firmware
make upload
```

看串口日志：

```bash
pio device monitor
```

正常日志：

```text
CatSense V0 boot
IMU init ok
Battery <mv> mV
BLE tx power 8 dBm
BLE advertising
```

## 3. 安装网关依赖

```bash
make setup
```

## 4. 启动网页采集器

```bash
make web
```

终端会打印：

```text
Computer: http://127.0.0.1:8000
Phone:    http://你的局域网IP:8000
```

手机打不开时，优先检查：

- 手机和电脑是否在同一个 Wi-Fi
- 是否用了 `--host 0.0.0.0`
- 端口是否被占用
- macOS 防火墙是否拦截 Python

## 5. 开始采集

网页里设置：

- 猫咪编号：例如 `cat001`
- 采样率：优先用 `25 Hz`
- BLE 设备：默认 `CatSense-V0`
- 保存方式：默认 `按天一个 CSV`

点击“开始记录”。

网页会显示：

- 三轴加速度曲线
- 样本数
- 采样速率
- 电池电压
- 当前手动标签
- 实时预测预览

## 6. 手动标记行为

行为按钮：

- 休息
- 跑酷
- 走动
- 玩耍
- 舔毛
- 进食

点击某个动作按钮后，后续样本会写入这个标签。再点同一个按钮会结束标记，后续样本标签为空。

不要在不确定时硬标。宁可留空，也不要错标。

## 7. 保存方式

网页有三种保存方式：

| 保存方式 | 结果 | 适合场景 |
| --- | --- | --- |
| 按天一个 CSV | 写入 `manual_YYYYMMDD.csv` | 日常采集，减少文件数量 |
| 每次一个 CSV | 写入 `manual_YYYYMMDD_HHMMSS.csv` | 严格区分每次 session |
| 只预览不保存 | 不写 CSV | 只看曲线和实时预测 |

实时预测不会写入 CSV。训练只使用手动标签。

## 8. 查看数据质量

采集结束后先点“停止记录”，然后在网页底部“数据处理”面板点“检查数据”。

重点看：

- 每个标签有多少秒
- 是否有解析错误
- 是否有大量断连或时间间隔
- 采样率是否接近预期

## 9. 构建数据、训练和评估

在网页底部“数据处理”面板点“一键全部”。它会按顺序完成：

1. 检查数据
2. 构建统一样本和特征
3. 训练 baseline 模型
4. 做 Session 评估

输出文件：

```text
data/processed/unified_samples.csv
data/processed/features.csv
data/processed/windows.csv
models/baseline_centroid.json
models/baseline_report.txt
models/session_eval_report.txt
```

训练完成后，网页服务会重新加载 `models/baseline_centroid.json`。下一次开始记录时会使用新模型做实时预测预览。
