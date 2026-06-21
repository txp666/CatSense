#include <Arduino.h>
#include <InternalFileSystem.h>
#include <LSM6DS3.h>
#include <bluefruit.h>

#include <ctype.h>
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

using namespace Adafruit_LittleFS_Namespace;

namespace {

constexpr const char *DEVICE_NAME = "CatSense-V0";
constexpr const char *CACHE_PATH = "/daily.csv";
constexpr const char *MODE_PATH = "/mode.txt";
constexpr uint8_t DEFAULT_RATE_HZ = 25;
constexpr uint8_t MIN_RATE_HZ = 25;
constexpr uint8_t MAX_RATE_HZ = 50;
constexpr uint8_t DAILY_BURST_RATE_HZ = 25;
constexpr uint16_t DAILY_BURST_SAMPLES = 50;      // 2 seconds at 25Hz.
constexpr uint32_t DAILY_BURST_INTERVAL_MS = 60000;
constexpr uint32_t DAILY_UPLOAD_INTERVAL_MS = 300000;
constexpr uint32_t DAILY_UPLOAD_WINDOW_MS = 30000;
constexpr uint32_t CACHE_FLUSH_INTERVAL_MS = 60000;
constexpr uint32_t CACHE_MAX_BYTES = 20UL * 1024UL;
constexpr size_t CACHE_BUFFER_SIZE = 512;
constexpr uint32_t BATTERY_READ_INTERVAL_MS = 5000;
constexpr uint8_t BATTERY_ADC_SAMPLES = 8;
constexpr uint32_t BATTERY_MV_NUMERATOR = 3980;
constexpr uint32_t BATTERY_MV_DENOMINATOR = 2621;
constexpr int8_t COLLECT_BLE_TX_POWER_DBM = 8;
constexpr int8_t DAILY_BLE_TX_POWER_DBM = 0;
constexpr size_t TX_BUFFER_SIZE = 224;
constexpr size_t COMMAND_BUFFER_SIZE = 64;

enum class DeviceMode : uint8_t {
  Collect,
  Daily,
};

BLEDfu bledfu;
BLEUart bleuart;
LSM6DS3 imu(I2C_MODE, 0x6A);

DeviceMode deviceMode = DeviceMode::Collect;
bool sampling = false;
uint8_t sampleRateHz = DEFAULT_RATE_HZ;
uint32_t sequenceNumber = 0;
uint32_t nextSampleMs = 0;
uint32_t nextBatteryReadMs = 0;
int32_t cachedBatteryMv = -1;
char commandBuffer[COMMAND_BUFFER_SIZE];
size_t commandLength = 0;
bool fsReady = false;
uint32_t cacheBytes = 0;
uint32_t cacheRows = 0;
uint32_t cacheDroppedRows = 0;
char cacheBuffer[CACHE_BUFFER_SIZE];
size_t cacheBufferLength = 0;
uint32_t nextCacheFlushMs = 0;
bool dailyBurstActive = false;
uint16_t dailyBurstSamplesLeft = 0;
uint32_t nextDailyBurstStartMs = 0;
uint32_t nextDailyBurstSampleMs = 0;
bool dailyAdvertising = false;
uint32_t dailyUploadWindowEndMs = 0;
uint32_t nextDailyUploadWindowMs = 0;

const char *modeName() {
  return deviceMode == DeviceMode::Daily ? "daily" : "collect";
}

uint32_t sampleIntervalMs() {
  return 1000UL / sampleRateHz;
}

uint32_t dailyBurstSampleIntervalMs() {
  return 1000UL / DAILY_BURST_RATE_HZ;
}

void sendText(const char *text) {
  if (!Bluefruit.connected() || !bleuart.notifyEnabled()) {
    return;
  }

  bleuart.write(reinterpret_cast<const uint8_t *>(text), strlen(text));
}

void sendStatus() {
  char line[TX_BUFFER_SIZE];
  snprintf(
      line,
      sizeof(line),
      "STATUS,mode=%s,sampling=%u,rate=%u,daily_rate=%u,seq=%lu,battery_mv=%ld,tx_power_dbm=%d,cache_bytes=%lu,cache_rows=%lu,cache_dropped=%lu,fs=%u\n",
      modeName(),
      sampling ? 1 : 0,
      sampleRateHz,
      DAILY_BURST_RATE_HZ,
      static_cast<unsigned long>(sequenceNumber),
      static_cast<long>(cachedBatteryMv),
      static_cast<int>(Bluefruit.getTxPower()),
      static_cast<unsigned long>(cacheBytes + cacheBufferLength),
      static_cast<unsigned long>(cacheRows),
      static_cast<unsigned long>(cacheDroppedRows),
      fsReady ? 1 : 0);
  sendText(line);
}

void refreshCacheStats() {
  cacheBytes = 0;
  cacheRows = 0;

  if (!fsReady || !InternalFS.exists(CACHE_PATH)) {
    return;
  }

  File file(CACHE_PATH, FILE_O_READ, InternalFS);
  if (!file) {
    return;
  }

  cacheBytes = file.size();
  while (file.available()) {
    if (file.read() == '\n') {
      ++cacheRows;
    }
  }
  file.close();
}

void flushCacheBuffer() {
  if (!fsReady || cacheBufferLength == 0) {
    return;
  }

  File file(CACHE_PATH, FILE_O_WRITE, InternalFS);
  if (!file) {
    cacheDroppedRows++;
    cacheBufferLength = 0;
    return;
  }

  const size_t written = file.write(cacheBuffer, cacheBufferLength);
  file.close();

  if (written == cacheBufferLength) {
    cacheBytes += cacheBufferLength;
  } else {
    cacheDroppedRows++;
    refreshCacheStats();
  }
  cacheBufferLength = 0;
  nextCacheFlushMs = millis() + CACHE_FLUSH_INTERVAL_MS;
}

void clearCache() {
  cacheBufferLength = 0;
  cacheBytes = 0;
  cacheRows = 0;
  cacheDroppedRows = 0;
  if (fsReady && InternalFS.exists(CACHE_PATH)) {
    InternalFS.remove(CACHE_PATH);
  }
}

bool appendCacheLine(const char *line, size_t length) {
  if (!fsReady || length == 0) {
    ++cacheDroppedRows;
    return false;
  }

  if (cacheBytes + cacheBufferLength + length > CACHE_MAX_BYTES) {
    ++cacheDroppedRows;
    return false;
  }

  if (length > CACHE_BUFFER_SIZE) {
    flushCacheBuffer();
    File file(CACHE_PATH, FILE_O_WRITE, InternalFS);
    if (!file) {
      ++cacheDroppedRows;
      return false;
    }
    const size_t written = file.write(line, length);
    file.close();
    if (written == length) {
      cacheBytes += length;
      ++cacheRows;
      return true;
    }
    ++cacheDroppedRows;
    refreshCacheStats();
    return false;
  }

  if (cacheBufferLength + length > CACHE_BUFFER_SIZE) {
    flushCacheBuffer();
  }

  memcpy(cacheBuffer + cacheBufferLength, line, length);
  cacheBufferLength += length;
  ++cacheRows;
  return true;
}

void maybeFlushCache() {
  if (cacheBufferLength == 0) {
    return;
  }

  const uint32_t now = millis();
  if (static_cast<int32_t>(now - nextCacheFlushMs) >= 0) {
    flushCacheBuffer();
  }
}

int32_t readBatteryMillivolts() {
#if defined(PIN_VBAT)
  pinMode(PIN_VBAT, INPUT);

#if defined(VBAT_ENABLE)
  pinMode(VBAT_ENABLE, OUTPUT);
  digitalWrite(VBAT_ENABLE, LOW);
  delay(2);
#endif

  analogReference(AR_INTERNAL_3_0);
  analogReadResolution(12);
  delay(1);

  (void)analogRead(PIN_VBAT);

  uint32_t rawSum = 0;
  for (uint8_t index = 0; index < BATTERY_ADC_SAMPLES; ++index) {
    rawSum += analogRead(PIN_VBAT);
    delay(1);
  }

  analogReference(AR_DEFAULT);
  analogReadResolution(10);

  if (rawSum == 0) {
    return -1;
  }

  // XIAO nRF52840 Sense reads VBAT through an enabled divider. The base
  // conversion is calibrated against a DMM measurement: firmware 2621mV,
  // measured battery 3980mV.
  const uint32_t denominator = static_cast<uint32_t>(BATTERY_ADC_SAMPLES) * 4096UL;
  const uint32_t uncalibratedMv = (rawSum * 6000UL + denominator / 2) / denominator;
  return static_cast<int32_t>(
      (uncalibratedMv * BATTERY_MV_NUMERATOR + BATTERY_MV_DENOMINATOR / 2) /
      BATTERY_MV_DENOMINATOR);
#else
  return -1;
#endif
}

void updateBatteryIfDue(bool force = false) {
  const uint32_t now = millis();
  if (!force && static_cast<int32_t>(now - nextBatteryReadMs) < 0) {
    return;
  }

  cachedBatteryMv = readBatteryMillivolts();
  nextBatteryReadMs = now + BATTERY_READ_INTERVAL_MS;
}

size_t buildSampleLine(char *line, size_t lineSize) {
  if (lineSize == 0) {
    return 0;
  }
  line[0] = '\0';
  updateBatteryIfDue();

  const int32_t axMg = static_cast<int32_t>(lround(imu.readFloatAccelX() * 1000.0f));
  const int32_t ayMg = static_cast<int32_t>(lround(imu.readFloatAccelY() * 1000.0f));
  const int32_t azMg = static_cast<int32_t>(lround(imu.readFloatAccelZ() * 1000.0f));

  const int written = snprintf(
      line,
      lineSize,
      "CS0,%lu,%lu,%ld,%ld,%ld,%ld\n",
      static_cast<unsigned long>(sequenceNumber++),
      static_cast<unsigned long>(millis()),
      static_cast<long>(axMg),
      static_cast<long>(ayMg),
      static_cast<long>(azMg),
      static_cast<long>(cachedBatteryMv));

  if (written <= 0) {
    return 0;
  }
  return static_cast<size_t>(written) < lineSize ? static_cast<size_t>(written) : lineSize - 1;
}

void setDeviceMode(DeviceMode newMode, bool persist);

void setSampling(bool enabled) {
  if (enabled && deviceMode != DeviceMode::Collect) {
    setDeviceMode(DeviceMode::Collect, false);
  }

  sampling = enabled;

  if (sampling) {
    nextSampleMs = millis();
    updateBatteryIfDue(true);
    Serial.println("START sampling");
    sendText("OK START\n");
  } else {
    Serial.println("STOP sampling");
    sendText("OK STOP\n");
  }
}

void setRate(uint8_t newRateHz) {
  sampleRateHz = newRateHz;
  nextSampleMs = millis();

  Serial.print("RATE set to ");
  Serial.print(sampleRateHz);
  Serial.println("Hz");

  char line[24];
  snprintf(line, sizeof(line), "OK RATE %u\n", sampleRateHz);
  sendText(line);
}

void sendCacheStatus() {
  char line[TX_BUFFER_SIZE];
  snprintf(
      line,
      sizeof(line),
      "CACHE,bytes=%lu,rows=%lu,buffered=%u,dropped=%lu,max_bytes=%lu\n",
      static_cast<unsigned long>(cacheBytes + cacheBufferLength),
      static_cast<unsigned long>(cacheRows),
      static_cast<unsigned int>(cacheBufferLength),
      static_cast<unsigned long>(cacheDroppedRows),
      static_cast<unsigned long>(CACHE_MAX_BYTES));
  sendText(line);
}

void streamCache() {
  if (!fsReady) {
    sendText("ERR fs not ready\n");
    return;
  }

  flushCacheBuffer();
  refreshCacheStats();

  char header[TX_BUFFER_SIZE];
  snprintf(
      header,
      sizeof(header),
      "UPLOAD BEGIN bytes=%lu rows=%lu\n",
      static_cast<unsigned long>(cacheBytes),
      static_cast<unsigned long>(cacheRows));
  sendText(header);

  File file(CACHE_PATH, FILE_O_READ, InternalFS);
  if (file) {
    char line[TX_BUFFER_SIZE];
    size_t length = 0;
    while (file.available() && Bluefruit.connected()) {
      const int value = file.read();
      if (value < 0) {
        break;
      }

      line[length++] = static_cast<char>(value);
      if (value == '\n' || length >= sizeof(line) - 1) {
        line[length] = '\0';
        sendText(line);
        length = 0;
        delay(2);
      }
    }

    if (length > 0) {
      line[length] = '\0';
      sendText(line);
    }
    file.close();
  }

  sendText("UPLOAD END\n");
}

void saveMode() {
  if (!fsReady) {
    return;
  }

  File file(MODE_PATH, FILE_O_WRITE, InternalFS);
  if (!file) {
    return;
  }
  file.truncate(0);
  file.write(modeName());
  file.write("\n");
  file.close();
}

void loadMode() {
  deviceMode = DeviceMode::Collect;
  if (!fsReady || !InternalFS.exists(MODE_PATH)) {
    return;
  }

  File file(MODE_PATH, FILE_O_READ, InternalFS);
  if (!file) {
    return;
  }

  char buffer[16] = {0};
  const int readLen = file.read(buffer, sizeof(buffer) - 1);
  file.close();
  if (readLen > 0 && strstr(buffer, "daily") != nullptr) {
    deviceMode = DeviceMode::Daily;
  }
}

void stopAdvertising() {
  Bluefruit.Advertising.stop();
  dailyAdvertising = false;
}

void startCollectAdvertising() {
  Bluefruit.setTxPower(COLLECT_BLE_TX_POWER_DBM);
  Bluefruit.Advertising.restartOnDisconnect(true);
  Bluefruit.Advertising.setInterval(32, 244);
  Bluefruit.Advertising.setFastTimeout(30);
  Bluefruit.Advertising.start(0);
  dailyAdvertising = false;
  Serial.println("BLE advertising collect");
}

void startDailyUploadWindow() {
  Bluefruit.setTxPower(DAILY_BLE_TX_POWER_DBM);

  if (Bluefruit.connected()) {
    return;
  }

  Bluefruit.Advertising.restartOnDisconnect(false);
  Bluefruit.Advertising.setInterval(1600, 3200);
  Bluefruit.Advertising.setFastTimeout(0);
  Bluefruit.Advertising.start(DAILY_UPLOAD_WINDOW_MS / 1000);
  dailyAdvertising = true;
  dailyUploadWindowEndMs = millis() + DAILY_UPLOAD_WINDOW_MS;
  nextDailyUploadWindowMs = millis() + DAILY_UPLOAD_INTERVAL_MS;
  Serial.println("BLE advertising daily upload window");
}

void scheduleDailyWork(bool immediateUploadWindow) {
  const uint32_t now = millis();
  sampling = false;
  dailyBurstActive = false;
  dailyBurstSamplesLeft = 0;
  nextDailyBurstStartMs = now + 1000;
  nextDailyBurstSampleMs = now;
  nextDailyUploadWindowMs = immediateUploadWindow ? now : now + DAILY_UPLOAD_INTERVAL_MS;
  nextCacheFlushMs = now + CACHE_FLUSH_INTERVAL_MS;
}

void setDeviceMode(DeviceMode newMode, bool persist) {
  if (newMode == DeviceMode::Daily) {
    deviceMode = DeviceMode::Daily;
    Bluefruit.setTxPower(DAILY_BLE_TX_POWER_DBM);
    scheduleDailyWork(true);
    if (!Bluefruit.connected()) {
      stopAdvertising();
      startDailyUploadWindow();
    }
    Serial.println("MODE daily");
    sendText("OK MODE DAILY\n");
  } else {
    deviceMode = DeviceMode::Collect;
    Bluefruit.setTxPower(COLLECT_BLE_TX_POWER_DBM);
    sampling = false;
    dailyBurstActive = false;
    stopAdvertising();
    startCollectAdvertising();
    Serial.println("MODE collect");
    sendText("OK MODE COLLECT\n");
  }

  if (persist) {
    saveMode();
  }
}

void enterOtaDfuMode() {
  sampling = false;
  dailyBurstActive = false;
  dailyBurstSamplesLeft = 0;
  flushCacheBuffer();

  Serial.println("ENTER OTA DFU");
  sendText("OK DFU\n");
  delay(250);
  enterOTADfu();
}

void trimCommand(char *command) {
  size_t length = strlen(command);
  while (length > 0 && isspace(static_cast<unsigned char>(command[length - 1]))) {
    command[length - 1] = '\0';
    --length;
  }

  size_t start = 0;
  while (command[start] != '\0' && isspace(static_cast<unsigned char>(command[start]))) {
    ++start;
  }

  if (start > 0) {
    memmove(command, command + start, strlen(command + start) + 1);
  }
}

void uppercaseCommand(char *command) {
  for (size_t index = 0; command[index] != '\0'; ++index) {
    command[index] = static_cast<char>(toupper(static_cast<unsigned char>(command[index])));
  }
}

void handleCommand(const char *command) {
  if (strcmp(command, "START") == 0) {
    setSampling(true);
    return;
  }

  if (strcmp(command, "STOP") == 0) {
    setSampling(false);
    return;
  }

  if (strcmp(command, "PING") == 0) {
    sendText("PONG\n");
    return;
  }

  if (strcmp(command, "STATUS") == 0) {
    sendStatus();
    return;
  }

  if (strcmp(command, "MODE") == 0 || strcmp(command, "MODE?") == 0) {
    sendStatus();
    return;
  }

  if (strcmp(command, "MODE COLLECT") == 0) {
    setDeviceMode(DeviceMode::Collect, true);
    return;
  }

  if (strcmp(command, "MODE DAILY") == 0) {
    setDeviceMode(DeviceMode::Daily, true);
    return;
  }

  if (strcmp(command, "CACHE") == 0 || strcmp(command, "CACHE?") == 0) {
    sendCacheStatus();
    return;
  }

  if (strcmp(command, "DFU") == 0 || strcmp(command, "OTA") == 0) {
    enterOtaDfuMode();
    return;
  }

  if (strcmp(command, "UPLOAD") == 0) {
    streamCache();
    return;
  }

  if (strcmp(command, "CLEAR") == 0 || strcmp(command, "CACHE CLEAR") == 0) {
    clearCache();
    sendText("OK CLEAR\n");
    return;
  }

  if (strcmp(command, "FORMAT") == 0 || strcmp(command, "CACHE FORMAT") == 0) {
    if (fsReady) {
      cacheBufferLength = 0;
      InternalFS.format();
      refreshCacheStats();
      saveMode();
      sendText("OK FORMAT\n");
    } else {
      sendText("ERR fs not ready\n");
    }
    return;
  }

  if (strcmp(command, "RATE 25") == 0) {
    setRate(MIN_RATE_HZ);
    return;
  }

  if (strcmp(command, "RATE 50") == 0) {
    setRate(MAX_RATE_HZ);
    return;
  }

  sendText("ERR unknown command\n");
}

void flushCommand() {
  commandBuffer[commandLength] = '\0';
  trimCommand(commandBuffer);
  uppercaseCommand(commandBuffer);

  if (commandBuffer[0] != '\0') {
    handleCommand(commandBuffer);
  }

  commandLength = 0;
}

void pollCommand() {
  while (bleuart.available()) {
    const int value = bleuart.read();
    if (value < 0) {
      return;
    }

    const char ch = static_cast<char>(value);
    if (ch == '\n') {
      flushCommand();
      continue;
    }
    if (ch == '\r') {
      continue;
    }

    if (commandLength >= COMMAND_BUFFER_SIZE - 1) {
      commandLength = 0;
      sendText("ERR command too long\n");
      continue;
    }

    commandBuffer[commandLength++] = ch;
  }
}

void sendSample() {
  char line[TX_BUFFER_SIZE];
  buildSampleLine(line, sizeof(line));
  if (line[0] != '\0') {
    sendText(line);
  }
}

void pollSampling() {
  if (!sampling) {
    return;
  }

  const uint32_t now = millis();
  if (static_cast<int32_t>(now - nextSampleMs) < 0) {
    return;
  }

  sendSample();
  nextSampleMs += sampleIntervalMs();

  if (static_cast<int32_t>(now - nextSampleMs) > static_cast<int32_t>(sampleIntervalMs())) {
    nextSampleMs = now + sampleIntervalMs();
  }
}

void appendDailySample() {
  char line[TX_BUFFER_SIZE];
  const size_t length = buildSampleLine(line, sizeof(line));
  if (length > 0) {
    appendCacheLine(line, length);
  }
}

void pollDailyBurst() {
  if (deviceMode != DeviceMode::Daily) {
    return;
  }

  const uint32_t now = millis();
  if (!dailyBurstActive && static_cast<int32_t>(now - nextDailyBurstStartMs) >= 0) {
    dailyBurstActive = true;
    dailyBurstSamplesLeft = DAILY_BURST_SAMPLES;
    nextDailyBurstSampleMs = now;
  }

  if (!dailyBurstActive || static_cast<int32_t>(now - nextDailyBurstSampleMs) < 0) {
    return;
  }

  appendDailySample();
  if (dailyBurstSamplesLeft > 0) {
    --dailyBurstSamplesLeft;
  }

  nextDailyBurstSampleMs += dailyBurstSampleIntervalMs();
  if (dailyBurstSamplesLeft == 0) {
    dailyBurstActive = false;
    nextDailyBurstStartMs = now + DAILY_BURST_INTERVAL_MS;
    flushCacheBuffer();
  }
}

void pollDailyAdvertising() {
  if (deviceMode != DeviceMode::Daily || Bluefruit.connected()) {
    return;
  }

  const uint32_t now = millis();
  if (dailyAdvertising && static_cast<int32_t>(now - dailyUploadWindowEndMs) >= 0) {
    Bluefruit.Advertising.stop();
    dailyAdvertising = false;
    Serial.println("BLE daily upload window closed");
  }

  if (!dailyAdvertising && static_cast<int32_t>(now - nextDailyUploadWindowMs) >= 0) {
    startDailyUploadWindow();
  }
}

void connectCallback(uint16_t connHandle) {
  (void)connHandle;
  Serial.println("BLE connected");
  sampling = false;
  dailyAdvertising = false;
  commandLength = 0;
  nextSampleMs = millis();
}

void disconnectCallback(uint16_t connHandle, uint8_t reason) {
  (void)connHandle;
  (void)reason;

  if (sampling) {
    Serial.println("STOP sampling");
  }
  sampling = false;
  commandLength = 0;
  if (deviceMode == DeviceMode::Daily) {
    dailyAdvertising = false;
    nextDailyUploadWindowMs = millis() + DAILY_UPLOAD_INTERVAL_MS;
  }
  Serial.println("BLE disconnected");
}

void startAdvertising() {
  static bool configured = false;
  if (!configured) {
    Bluefruit.Advertising.addFlags(BLE_GAP_ADV_FLAGS_LE_ONLY_GENERAL_DISC_MODE);
    Bluefruit.Advertising.addTxPower();
    Bluefruit.Advertising.addService(bleuart);
    Bluefruit.ScanResponse.addName();
    configured = true;
  }

  if (deviceMode == DeviceMode::Daily) {
    startDailyUploadWindow();
  } else {
    startCollectAdvertising();
  }
}

void waitForSerialWindow() {
  const uint32_t startMs = millis();
  while (!Serial && millis() - startMs < 2000) {
    delay(10);
  }
}

void initImuOrHalt() {
  if (imu.begin() == 0) {
    Serial.println("IMU init ok");
    return;
  }

  while (true) {
    Serial.println("IMU init failed");
    delay(1000);
  }
}

void initBatteryMonitor() {
#if defined(VBAT_ENABLE)
  pinMode(VBAT_ENABLE, OUTPUT);
  digitalWrite(VBAT_ENABLE, LOW);
#endif
  cachedBatteryMv = readBatteryMillivolts();
  nextBatteryReadMs = millis() + BATTERY_READ_INTERVAL_MS;

  Serial.print("Battery ");
  Serial.print(cachedBatteryMv);
  Serial.println(" mV");
}

void initStorage() {
  fsReady = InternalFS.begin();
  if (!fsReady) {
    Serial.println("InternalFS init failed");
    return;
  }

  loadMode();
  refreshCacheStats();
  nextCacheFlushMs = millis() + CACHE_FLUSH_INTERVAL_MS;

  Serial.print("Mode ");
  Serial.println(modeName());
  Serial.print("Cache rows ");
  Serial.print(cacheRows);
  Serial.print(" bytes ");
  Serial.println(cacheBytes);
}

void initBleOrHalt() {
  Bluefruit.autoConnLed(true);
  Bluefruit.configPrphBandwidth(BANDWIDTH_MAX);

  if (!Bluefruit.begin()) {
    while (true) {
      Serial.println("BLE init failed");
      delay(1000);
    }
  }

  Bluefruit.setName(DEVICE_NAME);
  Bluefruit.setTxPower(deviceMode == DeviceMode::Daily ? DAILY_BLE_TX_POWER_DBM : COLLECT_BLE_TX_POWER_DBM);
  Bluefruit.Periph.setConnectCallback(connectCallback);
  Bluefruit.Periph.setDisconnectCallback(disconnectCallback);

  bledfu.begin();
  bleuart.begin();
  Serial.print("BLE tx power ");
  Serial.print(Bluefruit.getTxPower());
  Serial.println(" dBm");
  startAdvertising();
}

}  // namespace

void setup() {
  Serial.begin(115200);
  waitForSerialWindow();
  Serial.println("CatSense V0 boot");

  initImuOrHalt();
  initBatteryMonitor();
  initStorage();
  if (deviceMode == DeviceMode::Daily) {
    scheduleDailyWork(true);
  }
  initBleOrHalt();
}

void loop() {
  if (Bluefruit.connected()) {
    pollCommand();
    if (deviceMode == DeviceMode::Collect) {
      pollSampling();
    } else {
      pollDailyBurst();
      maybeFlushCache();
    }
  } else {
    sampling = false;
    if (deviceMode == DeviceMode::Daily) {
      pollDailyBurst();
      maybeFlushCache();
      pollDailyAdvertising();
    }
  }

  delay(deviceMode == DeviceMode::Daily && !dailyBurstActive ? 20 : 1);
}
