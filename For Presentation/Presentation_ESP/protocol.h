#pragma once
#include <Arduino.h>

// USB-CDC frame: 0xAA 0x55 CMD LEN PAYLOAD... CRC8
// CRC8 over CMD + LEN + PAYLOAD (poly 0x07, init 0x00)

static const uint8_t FRAME_H1 = 0xAA;
static const uint8_t FRAME_H2 = 0x55;

enum : uint8_t {
  CMD_DRIVE = 0x01,   // payload: int8 leftSpeed, int8 rightSpeed   (-100..+100)
  CMD_DRUM  = 0x02,   // unused in presentation build
  CMD_PING  = 0x03,
};

inline uint8_t crc8(const uint8_t* data, size_t n) {
  uint8_t crc = 0;
  for (size_t i = 0; i < n; ++i) {
    crc ^= data[i];
    for (uint8_t b = 0; b < 8; ++b)
      crc = (crc & 0x80) ? (uint8_t)((crc << 1) ^ 0x07) : (uint8_t)(crc << 1);
  }
  return crc;
}
