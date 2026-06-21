# 网页采集、数据处理和训练流程

这页是 CatSense V0 的日常完整流程。当前项目只使用自己的 `data/raw` 数据训练，不读取公共数据集。

原则：除了启动网页服务外，采集、检查数据、构建特征、训练模型、Session 评估都在网页里完成，不需要再手动运行处理脚本。

## 第一次准备环境

只需要做一次：

```bash
make setup
```

以后启动服务：

```bash
make web
```

终端会打印电脑和手机访问地址：

```text
Computer: http://127.0.0.1:8000
Phone:    http://你的局域网IP:8000
```

手机要和电脑在同一个 Wi-Fi。网页打不开时，换一个端口启动服务，例如 `8001`。如果电脑上已经有旧服务在跑，先在旧终端按 `Ctrl+C` 停掉，再启动新版本。

## 网页采集

网页里推荐设置：

- `cat_id`: `cat001`
- 采样率：`25 Hz`
- 保存方式：`按天一个 CSV`
- BLE 设备：`CatSense-V0`

点击“开始记录”后，曲线、采样率、电池电压和实时预测会开始刷新。

手动标签的操作方式：

- 点一个动作按钮，开始标记这个动作。
- 再点同一个动作按钮，结束标记，后续样本回到空标签。
- 换动作时，直接点另一个动作按钮即可。
- 点“取消”也会结束当前标记，后续样本回到空标签；已经写入 CSV 的历史样本不会被改写。

当前动作标签：

```text
休息、跑酷、走动、玩耍、舔毛、进食
```

输出文件：

```text
data/raw/{cat_id}/manual_{YYYYMMDD}.csv
```

实时预测只是预览，不会写回 raw CSV。训练真值只来自手动标签。

## 网页数据处理面板

采集结束后，在网页底部“数据处理”面板操作。处理任务运行时不能同时采集，先点“停止记录”。

按钮含义：

| 按钮 | 做什么 | 主要输出 |
| --- | --- | --- |
| 检查数据 | 统计 raw 数据、每类秒数、采样率、电量范围、断点和异常 | 网页结果区 |
| 构建数据 | 读取 `data/raw`，统一样本格式，切窗口，提特征 | `data/processed/unified_samples.csv`、`data/processed/features.csv` |
| 训练模型 | 用自采 features 训练 baseline 模型 | `data/processed/windows.csv`、`models/baseline_centroid.json`、`models/baseline_report.txt` |
| Session 评估 | 每次留出一个 CSV/session 做测试，评估跨录制片段效果 | `models/session_eval_report.txt` |
| 一键全部 | 按顺序执行检查、构建、训练、Session 评估 | 上面所有输出 |

日常推荐直接点“一键全部”。如果只是想看数据是否够，点“检查数据”。如果刚补采了一批并想更新实时预测，点“一键全部”。

训练完成后，网页服务会重新加载 `models/baseline_centroid.json`。下一次开始记录时，实时预测会使用新模型。

## 数据处理规则

原始数据读取位置：

```text
data/raw/{cat_id}/*.csv
```

统一样本输出：

```text
data/processed/unified_samples.csv
```

统一样本会保留空标签行，方便排查原始时间线。字段包括：

```text
source, host_time_iso, device_ms, seq, ax_mg, ay_mg, az_mg,
battery_mv, label, cat_id, device_id, raw_label, file
```

训练特征输出：

```text
data/processed/features.csv
```

进入特征和训练的数据规则：

- 只使用自己的 `data/raw`。
- 空 `label` 不参与训练。
- 不在当前标签表里的历史标签会保留在 `raw_label`，但训练标签置空。
- 按文件、猫编号、标签、时间连续性切成片段。
- 默认裁掉每个有标签片段头尾各 `0.8` 秒。
- 裁剪后放不下 2 秒窗口的片段会被跳过。
- 默认窗口长度 `2` 秒，步长 `1` 秒，训练采样率按 `25 Hz` 计算。

为什么要裁头尾：人工点开始和结束经常会慢一点，动作切换边缘最容易混入上一个或下一个动作。裁掉头尾能减少标签污染。真实动作很短时，尽量提前一点点点开始、结束时晚一点点点结束，让中间留下干净片段。

## 看哪些结果

点完“一键全部”后重点看：

- 每个标签秒数是否太少或严重不均衡。
- `parse_errors` 是否为 `0`。
- `features` 和 `windows` 是否正常生成。
- `models/baseline_report.txt` 里的混淆矩阵。
- `models/session_eval_report.txt` 里的 `session_holdout_accuracy`。
- 网页实时预测是否频繁跳变，或者某些动作总被混成另一类。

如果某个动作预测很差，下一步不是盲目采很多，而是补更干净、更典型、更多姿态变化的数据。

## 当前输出位置

原始数据：

```text
data/raw/cat001/
```

处理后数据：

```text
data/processed/unified_samples.csv
data/processed/features.csv
data/processed/windows.csv
```

模型和报告：

```text
models/baseline_centroid.json
models/baseline_report.txt
models/session_eval_report.txt
```
