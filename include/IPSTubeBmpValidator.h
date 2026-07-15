#ifndef IPSTUBE_BMP_VALIDATOR_H
#define IPSTUBE_BMP_VALIDATOR_H

#include <stddef.h>
#include <stdint.h>

namespace IPSTubeControl
{
enum class BmpError : uint8_t
{
  OK = 0,
  HEADER,
  MAGIC,
  DIMENSIONS,
  PLANES,
  BIT_DEPTH,
  COMPRESSION,
  PALETTE,
  TRUNCATED,
  OVERFLOW
};

struct BmpInfo
{
  uint32_t width;
  uint32_t height;
  uint16_t bitsPerPixel;
  uint32_t pixelOffset;
  uint32_t rowStride;
  uint32_t requiredBytes;
  uint32_t paletteEntries;
};

BmpError validateBmpHeader(const uint8_t *header, size_t headerSize,
                           uint32_t fileSize, BmpInfo &info);
const char *bmpErrorName(BmpError error);
}

#endif
