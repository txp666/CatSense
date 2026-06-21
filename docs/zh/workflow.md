# 完整流程

这篇文档记录 CatSense V0 每一步做什么、输入是什么、输出是什么、做到什么程度算完成。

## 第 1 步：硬件验证

目的：确认板子、IMU、电池读取和 BLE 都能工作。

输入：

- Seeed Studio XIAO nRF52840 Sense
- 锂电池
- USB 数据线
- PlatformIO 环境

输出：

- 固件能启动
- IMU 初始化成功
- BLE 广播 `CatSense-V0`
- 串口能看到电池电压

完成标准：

- 串口显示 `IMU init ok`
- 串口显示 `BLE tx power 8 dBm`
- 网关可以连接并收到 `CS0,...` 样本

## 第 2 步：固件采样

目的：让板子稳定采集加速度和电池电压，并通过 BLE 发出。

输入：

- 固件目录：`firmware/xiao_nrf52840_sense`
- 主机命令：`START`、`STOP`、`RATE 25`、`RATE 50`

输出：

```csv
CS0,seq,device_ms,ax_mg,ay_mg,az_mg,battery_mv
```

要求：

- `seq` 单调增加
- `device_ms` 单调增加
- 默认 25 Hz 采样稳定
- 电池电压约 5 秒刷新一次
- BLE TX power 为 `+8 dBm`

完成标准：

- 摇动板子时三轴数据变化明显
- 静止时三轴数据比较稳定
- 采集器能保存 CSV

## 第 3 步：网页采集和手动标记

目的：采集真实行为数据，并给每段行为打标签。

输入：

- BLE 实时样本
- 网页上的手动行为按钮

输出：

```text
data/raw/{cat_id}/manual_{YYYYMMDD_HHMMSS}.csv
```

网页行为：

- 点击“开始记录”开始采样
- 点击动作按钮开始当前标签
- 再点同一个动作按钮结束当前标签
- 不确定时保持未标记

完成标准：

- CSV 持续写入
- `label` 列只在确定行为时有值
- `marker` 记录标签开始和结束事件
- 断连后 CSV 能正常关闭

## 第 4 步：数据质量检查

目的：判断当前数据是否适合训练。

网页操作：停止记录后，在底部“数据处理”面板点“检查数据”。

输出包括：

- 每类秒数
- 每类片段数
- 文件采样率
- 电池范围
- 时间间隔异常
- `seq` 跳变
- 解析错误

完成标准：

- `parse_errors=0`
- 当前要训练的标签都有足够秒数
- 明显错标片段已删除或重新采集
- 断连和缺样在可接受范围内

## 第 5 步：数据处理和 baseline 训练

目的：把自采 raw CSV 转成统一样本和训练窗口，并验证数据能否形成一个可运行模型。

网页操作：在底部“数据处理”面板点“一键全部”。如果已经检查过数据，也可以依次点“构建数据”、“训练模型”、“Session 评估”。

输出：

```text
data/processed/unified_samples.csv
data/processed/features.csv
data/processed/windows.csv
models/baseline_centroid.json
models/baseline_report.txt
models/session_eval_report.txt
```

当前 baseline：

- 2 秒窗口
- 1 秒步长
- 统计特征
- nearest-centroid 分类器
- 无第三方 ML 依赖

完成标准：

- 网页结果区显示处理完成
- 报告有 train/test accuracy
- 报告有每类 precision/recall
- 混淆矩阵能指出下一步数据问题

## 第 6 步：实时预测预览

目的：把训练好的 baseline 接回网页，验证实时链路。

输入：

- `models/baseline_centroid.json`
- 网页采集器实时样本

输出：

- 当前预测行为
- 稳定度
- top 类别相对分数
- 稳定、观察中、保持中、低置信等状态

要求：

- 预测不能写入原始 CSV
- 手动标签仍然是训练真值
- 分数不能当作严格概率
- 低置信时应该提示继续观察

完成标准：

- 网页能显示实时预测
- 预测不会频繁闪烁
- 断连和重连后状态清晰

## 第 7 步：模型迭代

目的：从流程验证走向更可靠的行为识别。

下一步方向：

- 增加弱标签数据：`walk`、`groom`、`play`
- 按 recording session 或日期划分训练/测试
- 尝试更强模型
- 调整实时预测平滑参数
- 记录佩戴位置和松紧程度

完成标准：

- 测试集来自不同录制 session
- 每个标签 recall 可解释
- 混淆原因有记录
- 模型版本、标签 schema 和窗口参数可追踪

## 第 8 步：开源发布

目的：让其他人能理解、复现、贡献。

发布前需要：

- README 清楚说明项目定位
- 中文和英文文档齐全
- 许可证和隐私说明齐全
- 示例数据为合成数据或明确可公开数据
- 明确不提交私人原始数据
- 固件能从干净环境构建
- 网关能从干净 Python venv 运行
- 给出已知限制
