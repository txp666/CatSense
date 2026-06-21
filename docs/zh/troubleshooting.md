# 问题排查

这篇文档记录 CatSense V0 常见问题。

## PlatformIO 找不到板子

错误：

```text
UnknownBoard: Unknown board ID 'seeed_xiao_nrf52840_sense'
```

原因：PlatformIO 官方 `nordicnrf52` 平台里不一定内置这个 board ID。

处理：当前项目已经带了本地 board 配置，并使用 Seeed 官方 nRF52 Arduino core。优先在项目固件目录运行：

```bash
cd firmware/xiao_nrf52840_sense
pio run
```

不要随便把 board 改成普通 XIAO nRF52840，否则 IMU 引脚和板级配置可能不对。

## 固件显示 IMU init failed

可能原因：

- 板子不是 XIAO nRF52840 Sense
- IMU 供电引脚不对
- I2C 初始化失败
- 板子硬件异常

处理：

- 确认购买的是 Sense 版本
- 重新烧录当前项目固件
- 打开串口看完整启动日志

## 运行 logger.py 提示缺少参数

错误：

```text
logger.py: error: the following arguments are required: --label, --cat, --rate
```

命令行采集器必须指定标签、猫编号和采样率：

```bash
python logger.py --label eat --cat cat001 --rate 25
```

如果要网页手动标记，用：

```bash
python web_logger.py --host 0.0.0.0 --port 8000
```

## 端口被占用

错误：

```text
OSError: [Errno 48] Address already in use
```

说明当前端口已有服务。

处理：

```bash
python web_logger.py --host 0.0.0.0 --port 8001
```

或者关闭之前运行的 `web_logger.py`。

## 手机打不开网页

检查：

- 手机和电脑是否同一个 Wi-Fi
- 启动命令是否用了 `--host 0.0.0.0`
- 是否打开了终端打印的 `Phone` 地址
- macOS 防火墙是否阻止 Python
- 路由器是否开启客户端隔离

正确启动：

```bash
python web_logger.py --host 0.0.0.0 --port 8000
```

## 扫描不到 CatSense-V0

检查：

- 固件是否已经启动
- 串口是否显示 `BLE advertising`
- 板子是否离电脑太远
- 是否已有另一个程序连接了设备
- 电池是否电量过低

可以重启板子，再重新运行网页采集器。

## 网页 OTA 刷写失败

先看网页“设备管理”的固件包状态：

- 显示未找到 `firmware.zip`：进入 `firmware/xiao_nrf52840_sense`，运行 `pio run`。
- 能看到固件包大小和时间：可以继续刷写。

常见处理：

- 点“刷写固件”失败后，不要反复断电；如果板子红灯闪烁，说明已经在 DFU/bootloader，直接点“慢速重试”。
- 如果提示没有扫描到 DFU bootloader，先点“进入 OTA”，或双击 reset 让板子进入 bootloader，再点“刷写固件”。
- 如果提示 `Operation Failed` 或 `notification from device`，让电脑靠近板子，保持红灯闪烁，再点“慢速重试”。
- 如果提示固件数据已发送但仍停留在 DFU bootloader，先点“重启 DFU”；如果仍不恢复，按一下 reset，等待恢复 `CatSense-V0` 广播，再点“读取状态”确认。
- 如果电脑蓝牙环境一直失败，走手机备用流程：下载固件包，进入 OTA，用 `nRF Connect` 或 `Adafruit Bluefruit Connect` 刷入。

OTA 过程中不要关闭网页服务，不要断电。日常模式下有缓存数据时，先拉取缓存再升级。

## 采集 0 samples 后断开

可能原因：

- BLE 连接成功但 Notify 没持续收到
- 距离太远或信号差
- 电池供电不稳
- 固件没有收到 `START`

处理：

- 靠近电脑测试
- 使用 USB 供电测试
- 看串口日志
- 用网页采集器观察日志
- 确认固件是最新版本

## 电池电量不涨

XIAO nRF52840 Sense 板子支持电池连接和充电，但实际是否充电取决于：

- 电池是否接在正确焊盘或接口
- USB 是否供电
- 充电电路是否正常
- 电池保护板状态
- 采样时电压波动

`battery_mv` 是电压，不是精确百分比。锂电池电压在充放电过程中不是线性变化。

## 预测一直跳

原因：

- 当前 baseline 很简单
- 多个类别中心点距离接近
- 分数不是概率
- 真实动作可能混合
- 佩戴位置变化导致模式不稳定

当前已经加入平滑和切换门槛。仍然跳时，说明模型对这段动作没有足够把握。

处理：

- 多采同类真实数据
- 尤其补 `walk/groom/play`
- 检查是否标错
- 保持佩戴位置更稳定
- 后续用更强模型

## 预测还显示旧标签

改标签集合或重新训练模型后，正在运行的 `web_logger.py` 不会自动换掉内存里的旧模型。

处理：

1. 在运行网页服务的终端按 `Ctrl+C`
2. 重新运行：

```bash
python web_logger.py --host 0.0.0.0 --port 8000
```

3. 浏览器刷新页面

当前代码会在加载模型时过滤停用标签，实时预测列表只显示当前有效标签。

## 预测切换慢

实时预测使用 2 秒窗口，所以动作刚变化时至少要等窗口里新动作占多数。当前切换参数偏向中等稳定：约每 0.5 秒预测一次，连续 3 个新窗口支持后允许切换，并且两次显示切换之间至少间隔约 2 秒。

如果仍然十几秒才切换，优先检查：

- 是否重启了 `web_logger.py`
- 浏览器是否刷新了页面
- 当前项圈是否还在晃动或过渡动作中
- `models/baseline_centroid.json` 是否是最新训练出的模型

## 百分比都差不多

这表示多个标签距离接近。网页里的百分比是相对稳定度，不是概率。

看到“低置信”或“观察中”是正常的，不代表程序坏了。
