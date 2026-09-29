#include "esp_camera.h"

// ----- Camera pin map (Freenove ESP32-S3 / generic OV5640 boards) -----
#define CAM_PIN_PWDN    -1
#define CAM_PIN_RESET   -1
#define CAM_PIN_XCLK    15
#define CAM_PIN_SIOD     4
#define CAM_PIN_SIOC     5
#define CAM_PIN_D7      16
#define CAM_PIN_D6      17
#define CAM_PIN_D5      18
#define CAM_PIN_D4      12
#define CAM_PIN_D3      10
#define CAM_PIN_D2       8
#define CAM_PIN_D1       9
#define CAM_PIN_D0      11
#define CAM_PIN_VSYNC    6
#define CAM_PIN_HREF     7
#define CAM_PIN_PCLK    13

// ----- Stream params -----
static const framesize_t FRAME_SIZE = FRAMESIZE_VGA;   // 640x480; FRAMESIZE_SVGA (800x600) also OK
static const int JPEG_QUALITY = 12;                    // lower = better quality, larger size (0..63)
static const uint32_t TARGET_FPS = 15;

static const uint8_t MAGIC[4] = {0xA5, 0x5A, 0xF0, 0x0D};

void writeU32BE(uint32_t v) {
  uint8_t b[4] = {
    (uint8_t)(v >> 24), (uint8_t)(v >> 16),
    (uint8_t)(v >> 8),  (uint8_t)(v)
  };
  Serial.write(b, 4);
}

bool initCamera() {
  camera_config_t cfg = {};
  cfg.ledc_channel = LEDC_CHANNEL_0;
  cfg.ledc_timer   = LEDC_TIMER_0;
  cfg.pin_d0       = CAM_PIN_D0;
  cfg.pin_d1       = CAM_PIN_D1;
  cfg.pin_d2       = CAM_PIN_D2;
  cfg.pin_d3       = CAM_PIN_D3;
  cfg.pin_d4       = CAM_PIN_D4;
  cfg.pin_d5       = CAM_PIN_D5;
  cfg.pin_d6       = CAM_PIN_D6;
  cfg.pin_d7       = CAM_PIN_D7;
  cfg.pin_xclk     = CAM_PIN_XCLK;
  cfg.pin_pclk     = CAM_PIN_PCLK;
  cfg.pin_vsync    = CAM_PIN_VSYNC;
  cfg.pin_href     = CAM_PIN_HREF;
  cfg.pin_sccb_sda = CAM_PIN_SIOD;
  cfg.pin_sccb_scl = CAM_PIN_SIOC;
  cfg.pin_pwdn     = CAM_PIN_PWDN;
  cfg.pin_reset    = CAM_PIN_RESET;
  cfg.xclk_freq_hz = 20000000;
  cfg.pixel_format = PIXFORMAT_JPEG;
  cfg.frame_size   = FRAME_SIZE;
  cfg.jpeg_quality = JPEG_QUALITY;
  cfg.fb_count     = 2;
  cfg.fb_location  = CAMERA_FB_IN_PSRAM;
  cfg.grab_mode    = CAMERA_GRAB_LATEST;

  if (esp_camera_init(&cfg) != ESP_OK) return false;

  // Flip the image 180° (vertical flip + horizontal mirror) so the GUI shows
  // it the right way up regardless of how the sensor is physically mounted.
  // Image orientation is corrected on the laptop side (PIL .rotate(180)).
  // No sensor-side flips needed.
  return true;
}

void setup() {
  Serial.begin(921600);          // USB-CDC; baud is mostly ignored over CDC but set it large anyway
  while (!Serial && millis() < 3000) { delay(10); }

  if (!initCamera()) {
    // Loop forever signalling failure on the USB log line.
    while (true) {
      Serial.println("CAM_INIT_FAIL");
      delay(1000);
    }
  }
}

void loop() {
  static uint32_t lastUs = 0;
  uint32_t periodUs = 1000000UL / TARGET_FPS;
  uint32_t now = micros();
  if (now - lastUs < periodUs) return;
  lastUs = now;

  camera_fb_t* fb = esp_camera_fb_get();
  if (!fb) return;

  if (fb->format == PIXFORMAT_JPEG && fb->len > 0) {
    Serial.write(MAGIC, 4);
    writeU32BE((uint32_t)fb->len);
    Serial.write(fb->buf, fb->len);
  }

  esp_camera_fb_return(fb);
}
