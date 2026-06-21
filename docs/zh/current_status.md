# 当前状态

日期：2026-06-22

## 已完成

- XIAO nRF52840 Sense 固件
- LSM6DS3 加速度采样
- BLE UART 协议
- 电池电压读取
- BLE 发射功率设为 `+8 dBm`
- Python 命令行采集器
- 支持手机访问的本地网页采集器
- 手动行为按钮标记
- 数据质量报告脚本
- 自采数据特征构建脚本
- baseline 训练脚本
- 按 session 留出评估脚本
- 训练前标签片段边缘裁剪
- 网页实时预测预览
- 实时预测平滑和切换迟滞
- 固件采集模式 / 日常工作模式
- 日常工作模式内部 LittleFS 缓存和定时 BLE 上传窗口
- 网页 OTA/DFU 直接刷写和慢速重试
- 中文文档初版
- 开源基础文件、合成示例数据、轻量 CI 和隐私说明

## 当前标签覆盖

最近一次 `dataset_report.py` 摘要：

| 标签 | 中文 | 秒数 | 状态 |
| --- | --- | ---: | --- |
| `rest` | 休息 | 292.8 | OK |
| `parkour` | 跑酷 | 156.0 | OK |
| `walk` | 走动 | 254.0 | OK |
| `play` | 玩耍 | 313.1 | OK |
| `groom` | 舔毛 | 260.4 | OK |
| `eat` | 进食 | 288.0 | OK |

## 当前 baseline

最近一次 `train_baseline.py` 随机窗口摘要：

```text
windows=1236
labels=eat,groom,parkour,play,rest,walk
trim_edge_s=0.800
train_accuracy=0.730
test_accuracy=0.718
```

解释：

- 足够证明端到端流程。
- 不足以做公开准确率宣传。
- 可以作为 6 类 checkpoint。
- 当前网页标签集合已停用 `roll` 和 `litter`，历史停用标签只保留在 `raw_label`，不参与训练。
- 训练时默认丢弃每段标签头尾各 0.8 秒，减少手动标记反应慢造成的污染。

## Session 评估

最近一次 `evaluate_by_session.py` 摘要：

```text
sessions=16/16
windows=1236
accuracy=0.576
```

解释：

- 这个结果比随机窗口测试更严格。
- `eat/parkour` 相对稳定。
- `groom/walk` 泛化差，是下一轮重点补数据对象。

## 实时预测

网页采集器会加载 `models/baseline_centroid.json`，用最近 2 秒窗口做预测。

显示包括：

- 当前稳定标签
- 稳定度
- 原始预测变化
- top 类别相对分数
- 稳定、观察中、保持中、低置信等状态

限制：

- 预测结果不会写入训练 CSV
- 手动标签仍然是训练真值
- 分数不是概率

## 下一步

优先级：

1. 增加 `walk/groom/play` 的真实佩戴数据
2. 增加不同佩戴位置和松紧程度
3. 按 session 或日期重新评估模型
4. 调整实时预测平滑参数
5. 补充硬件佩戴照片或结构图，并先确认不泄露家庭环境
