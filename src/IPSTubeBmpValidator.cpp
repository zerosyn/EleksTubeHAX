#include "IPSTubeBmpValidator.h"

#include <limits.h>

namespace IPSTubeControl
{
static uint16_t read16(const uint8_t *data)
{
  return uint16_t(data[0]) | (uint16_t(data[1]) << 8U);
}

static uint32_t read32(const uint8_t *data)
{
  return uint32_t(data[0]) | (uint32_t(data[1]) << 8U) |
         (uint32_t(data[2]) << 16U) | (uint32_t(data[3]) << 24U);
}

BmpError validateBmpHeader(const uint8_t *header, size_t headerSize,
                           uint32_t fileSize, BmpInfo &info)
{
  info = {};
  if (header == nullptr || headerSize < 54)
    return BmpError::HEADER;
  if (header[0] != 'B' || header[1] != 'M')
    return BmpError::MAGIC;

  const uint32_t declaredFileSize = read32(header + 2);
  const uint32_t pixelOffset = read32(header + 10);
  const uint32_t dibSize = read32(header + 14);
  const uint64_t dibEnd = uint64_t(14U) + dibSize;
  if (dibSize < 40 || pixelOffset < 54 || dibEnd > pixelOffset)
    return BmpError::HEADER;

  const int32_t signedWidth = int32_t(read32(header + 18));
  const int32_t signedHeight = int32_t(read32(header + 22));
  if (signedWidth <= 0 || signedHeight <= 0 || signedWidth > 135 || signedHeight > 240)
    return BmpError::DIMENSIONS;
  if (read16(header + 26) != 1)
    return BmpError::PLANES;

  const uint16_t bitsPerPixel = read16(header + 28);
  if (bitsPerPixel != 1 && bitsPerPixel != 4 && bitsPerPixel != 8 && bitsPerPixel != 24)
    return BmpError::BIT_DEPTH;
  if (read32(header + 30) != 0)
    return BmpError::COMPRESSION;

  const uint32_t width = uint32_t(signedWidth);
  const uint32_t height = uint32_t(signedHeight);
  const uint64_t bitsPerRow = uint64_t(bitsPerPixel) * width;
  const uint64_t rowStride64 = ((bitsPerRow + 31U) >> 5U) * 4U;
  const uint64_t requiredBytes64 = uint64_t(pixelOffset) + rowStride64 * height;
  if (rowStride64 > UINT32_MAX || requiredBytes64 > UINT32_MAX)
    return BmpError::OVERFLOW;

  uint32_t paletteEntries = 0;
  if (bitsPerPixel <= 8)
  {
    paletteEntries = read32(header + 46);
    const uint32_t maxPaletteEntries = 1U << bitsPerPixel;
    if (paletteEntries == 0)
      paletteEntries = maxPaletteEntries;
    if (paletteEntries > maxPaletteEntries)
      return BmpError::PALETTE;

    const uint64_t paletteEnd = dibEnd + uint64_t(paletteEntries) * 4U;
    if (paletteEnd > pixelOffset || paletteEnd > UINT32_MAX)
      return BmpError::PALETTE;
  }

  const uint32_t requiredBytes = uint32_t(requiredBytes64);
  if (requiredBytes > fileSize || (declaredFileSize != 0 && declaredFileSize > fileSize))
    return BmpError::TRUNCATED;

  info.width = width;
  info.height = height;
  info.bitsPerPixel = bitsPerPixel;
  info.pixelOffset = pixelOffset;
  info.rowStride = uint32_t(rowStride64);
  info.requiredBytes = requiredBytes;
  info.paletteEntries = paletteEntries;
  return BmpError::OK;
}

const char *bmpErrorName(BmpError error)
{
  static const char *const NAMES[] = {
      "OK", "HEADER", "MAGIC", "DIMENSIONS", "PLANES", "BIT_DEPTH",
      "COMPRESSION", "PALETTE", "TRUNCATED", "OVERFLOW"};
  const uint8_t index = uint8_t(error);
  return index < sizeof(NAMES) / sizeof(NAMES[0]) ? NAMES[index] : "UNKNOWN";
}
}
