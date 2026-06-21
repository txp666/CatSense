# CatSense V0 中文文档

这里是 CatSense V0 的中文文档入口。

建议按下面顺序阅读：

1. [快速开始](quick_start.md)
2. [流程图](diagrams.md)
3. [系统原理](principles.md)
4. [完整流程](workflow.md)
5. [数据采集规范](data_collection.md)
6. [数据处理和服务命令](data_processing.md)
7. [固件 OTA 升级](ota.md)
8. [建模说明](modeling.md)
9. [当前状态](current_status.md)
10. [问题排查](troubleshooting.md)
11. [开源准备](open_source.md)
12. [贡献指南](../../CONTRIBUTING.zh-CN.md)

## 项目一句话说明

CatSense V0 用猫咪项圈上的 IMU 采集三轴加速度，通过 BLE 发给电脑或树莓派，在网页上实时查看曲线、手动标记行为，并用 CSV 数据训练一个本地 baseline 行为模型。

## V0 做什么

- 采集猫咪佩戴项圈时的三轴加速度
- 记录电池电压
- 通过 BLE 实时传输数据
- 在网页上手动标记行为
- 生成可训练的 CSV 数据
- 做数据质量检查
- 训练一个无第三方 ML 依赖的 baseline 模型
- 在网页中做实时预测预览
- 通过网页直接刷写固件、进入 OTA/DFU 并下载固件包

## V0 暂时不做什么

- 不做医疗诊断
- 不做安全告警设备
- 不做生产级宠物定位器
- 不做云端账号系统
- 不做手机 App
- 不保证当前模型可泛化到所有猫

## 核心限制

当前模型来自少量单设备数据，主要用于验证数据闭环。真实可用模型需要更多猫、更多天、更多佩戴状态和更严格的评估方式。
