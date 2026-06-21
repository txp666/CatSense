# 贡献指南

感谢关注 CatSense V0。这个项目当前处于原型阶段，优先目标是保持简单、可复现、可解释。

## 开发环境

Python 网关：

```bash
make setup
```

固件：

```bash
make firmware
```

## 提交前检查

建议运行：

```bash
make check
```

Windows PowerShell 可运行：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/check.ps1
```

如果没有本地数据，可以跳过 `dataset_report.py` 和 `train_baseline.py`，但需要在 PR 里说明。

## 数据贡献

默认不要提交私人原始数据。

可以贡献：

- 匿名小样本 CSV
- 合成样本 CSV
- 数据质量报告结果
- 采集流程问题
- 标签定义改进建议

公开真实数据前必须：

- 匿名 `cat_id`
- 删除私人备注
- 不包含家庭位置、Wi-Fi、设备私有标识
- 明确记录佩戴位置和松紧程度
- 确认数据贡献者同意公开

## 代码贡献

优先方向：

- 修复采集稳定性
- 改进网页移动端体验
- 增加 session metadata
- 改进数据质量报告
- 改进模型评估切分
- 扩展合成示例数据
- 增加 RSSI 或连接质量显示
- 完善文档和截图

修改要求：

- 修改协议时同步更新 `docs/zh/protocol.md`
- 修改标签时同步更新采集和建模文档
- 修改 CSV 字段时同步更新数据文档
- 修改模型输出时同步更新实时预测说明

## 模型贡献

提交模型改进时，请说明：

- 使用了哪些数据
- 标签集合是什么
- 训练/测试如何划分
- 每类 precision/recall
- 混淆矩阵
- 已知失败场景

不要只提交一个总准确率。总准确率容易掩盖弱类别。

## 项目边界

CatSense V0 不是医疗设备，不应宣传为健康诊断工具。任何行为识别结果都只能作为研究和原型参考。
