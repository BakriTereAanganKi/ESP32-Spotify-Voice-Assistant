/*
  ESP32 voice remote for Spotify (push-to-talk).
  Board: any plain ESP32 dev board. Needs ESP32 Arduino core 3.x (Boards Manager).
  Libraries (Library Manager): "Adafruit SSD1306" and "Adafruit GFX Library".

  Wiring
    INMP441:  VDD -> 3.3V, GND -> GND, L/R -> GND, SCK -> GPIO26, WS -> GPIO25, SD -> GPIO33
    OLED I2C: VCC -> 3.3V, GND -> GND, SDA -> GPIO21, SCL -> GPIO22
    Button:   one leg -> GPIO4, other leg -> GND
*/
#include <WiFi.h>
#include <HTTPClient.h>
#include <Wire.h>
#include <ESP_I2S.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>

// ---------- EDIT THESE ----------
const char* WIFI_SSID = "YOUR_WIFI";
const char* WIFI_PASS = "YOUR_PASSWORD";
const char* SERVER_URL = "http://192.168.1.12:8000/voice";  // your laptop's IP
// --------------------------------

#define PIN_BCLK 26
#define PIN_WS   25
#define PIN_DIN  33
#define PIN_BTN  4

#define SAMPLE_RATE   16000
#define MAX_SECONDS   3       // raise to 4 if the boot log shows enough free memory
#define GAIN_SHIFT    14      // 16 = no gain, lower = louder (14 is a good start)
#define SKIP_SAMPLES  3200    // discard the first 200 ms (mic start-up noise)
#define MIN_SAMPLES   (SAMPLE_RATE / 3)

Adafruit_SSD1306 oled(128, 64, &Wire, -1);
I2SClass i2s;
int16_t* audioBuf = nullptr;
const size_t MAX_SAMPLES = (size_t)SAMPLE_RATE * MAX_SECONDS;

void show(const String& line1, const String& line2 = "") {
  oled.clearDisplay();
  oled.setTextSize(1);
  oled.setTextColor(SSD1306_WHITE);
  oled.setCursor(0, 0);
  oled.println(line1);
  if (line2.length()) {
    oled.println();
    oled.println(line2);
  }
  oled.display();
}

void connectWifi() {
  show("Connecting WiFi...");
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  uint32_t start = millis();
  while (WiFi.status() != WL_CONNECTED) {
    delay(300);
    if (millis() - start > 20000) {
      show("WiFi failed", "Check name/password");
      delay(3000);
      ESP.restart();
    }
  }
}

size_t recordWhileHeld() {
  // Start the mic only while recording, so there is no stale audio in the buffer.
  if (!i2s.begin(I2S_MODE_STD, SAMPLE_RATE, I2S_DATA_BIT_WIDTH_32BIT,
                 I2S_SLOT_MODE_MONO, I2S_STD_SLOT_LEFT)) {
    Serial.println("I2S begin failed");
    return 0;
  }
  static int32_t raw[256];
  size_t n = 0, skipped = 0;
  while (digitalRead(PIN_BTN) == LOW && n < MAX_SAMPLES) {
    size_t got = i2s.readBytes((char*)raw, sizeof(raw)) / sizeof(int32_t);
    for (size_t i = 0; i < got && n < MAX_SAMPLES; i++) {
      if (skipped < SKIP_SAMPLES) { skipped++; continue; }
      int32_t s = raw[i] >> GAIN_SHIFT;
      if (s > 32767) s = 32767;
      if (s < -32768) s = -32768;
      audioBuf[n++] = (int16_t)s;
    }
  }
  i2s.end();
  return n;
}

void sendAudio(size_t samples) {
  show("Thinking...");
  HTTPClient http;
  http.begin(SERVER_URL);
  http.setConnectTimeout(5000);
  http.setTimeout(30000);  // transcription + AI + Spotify can take a few seconds
  http.addHeader("Content-Type", "audio/pcm");
  int code = http.POST((uint8_t*)audioBuf, samples * sizeof(int16_t));
  if (code == 200) {
    String body = http.getString();
    int nl = body.indexOf('\n');
    String heard = nl >= 0 ? body.substring(0, nl) : body;
    String reply = nl >= 0 ? body.substring(nl + 1) : "";
    show("You: " + heard, reply);
  } else {
    show("Server error", String(code) + " " + HTTPClient::errorToString(code));
  }
  http.end();
}

void setup() {
  Serial.begin(115200);
  pinMode(PIN_BTN, INPUT_PULLUP);

  Wire.begin(21, 22);
  if (!oled.begin(SSD1306_SWITCHCAPVCC, 0x3C)) {
    Serial.println("OLED not found (try address 0x3D)");
    while (true) delay(1000);
  }
  show("Starting...");

  audioBuf = (int16_t*)malloc(MAX_SAMPLES * sizeof(int16_t));
  Serial.printf("Free heap: %u, largest block: %u, need: %u\n",
                ESP.getFreeHeap(), ESP.getMaxAllocHeap(), (unsigned)(MAX_SAMPLES * 2));
  if (!audioBuf) {
    show("Out of memory", "Lower MAX_SECONDS");
    while (true) delay(1000);
  }

  i2s.setPins(PIN_BCLK, PIN_WS, -1, PIN_DIN, -1);
  connectWifi();
  show("Ready", "Hold button and talk");
}

void loop() {
  if (digitalRead(PIN_BTN) == LOW) {
    delay(30);  // debounce
    if (digitalRead(PIN_BTN) != LOW) return;
    show("Listening...");
    size_t n = recordWhileHeld();
    if (n < MIN_SAMPLES) {
      show("Too short", "Hold the button while talking");
    } else {
      if (WiFi.status() != WL_CONNECTED) connectWifi();
      sendAudio(n);
    }
    delay(5000);  // keep the result on screen
    show("Ready", "Hold button and talk");
  }
  delay(10);
}
