#include "IPSTubeControlTypes.h"
#include "IPSTubeBmpValidator.h"

#include <assert.h>
#include <fstream>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <vector>

using namespace IPSTubeControl;

static void write16(std::vector<uint8_t> &data, size_t offset, uint16_t value)
{
  data[offset] = uint8_t(value);
  data[offset + 1] = uint8_t(value >> 8);
}

static void write32(std::vector<uint8_t> &data, size_t offset, uint32_t value)
{
  data[offset] = uint8_t(value);
  data[offset + 1] = uint8_t(value >> 8);
  data[offset + 2] = uint8_t(value >> 16);
  data[offset + 3] = uint8_t(value >> 24);
}

static std::vector<uint8_t> makeBmpHeader(uint32_t width, uint32_t height,
                                          uint16_t bitsPerPixel,
                                          uint32_t compression = 0)
{
  const uint32_t rowStride = ((uint32_t(bitsPerPixel) * width + 31U) >> 5U) * 4U;
  const uint32_t fileSize = 54U + rowStride * height;
  std::vector<uint8_t> data(54, 0);
  data[0] = 'B';
  data[1] = 'M';
  write32(data, 2, fileSize);
  write32(data, 10, 54);
  write32(data, 14, 40);
  write32(data, 18, width);
  write32(data, 22, height);
  write16(data, 26, 1);
  write16(data, 28, bitsPerPixel);
  write32(data, 30, compression);
  write32(data, 34, rowStride * height);
  return data;
}

static void testImageNames()
{
  char name[24];
  imageName(0, name, sizeof(name));
  assert(strcmp(name, "IMAGE_000") == 0);
  imageName(249, name, sizeof(name));
  assert(strcmp(name, "IMAGE_249") == 0);
  imageName(250, name, sizeof(name));
  assert(strcmp(name, "COLON") == 0);
  imageName(251, name, sizeof(name));
  assert(strcmp(name, "STATUS_IDLE") == 0);
  imageName(252, name, sizeof(name));
  assert(strcmp(name, "STATUS_WORKING") == 0);
  imageName(253, name, sizeof(name));
  assert(strcmp(name, "STATUS_WAITING") == 0);
  imageName(254, name, sizeof(name));
  assert(strcmp(name, "STATUS_COMPLETE") == 0);
  imageName(255, name, sizeof(name));
  assert(strcmp(name, "BLANK") == 0);
}

static void testClockRoles()
{
  const char *names[] = {"MANUAL", "H1", "H2", "M1", "M2", "S1", "S2", "COLON"};
  for (uint8_t i = 0; i < sizeof(names) / sizeof(names[0]); ++i)
  {
    ClockRole role = ClockRole::MANUAL;
    assert(parseClockRole(names[i], role));
    assert(uint8_t(role) == i);
    assert(strcmp(clockRoleName(role), names[i]) == 0);
  }

  ClockRole role = ClockRole::MANUAL;
  assert(!parseClockRole("h1", role));
  assert(!parseClockRole("UNKNOWN", role));

  const ClockRole expected[SCREEN_COUNT] = {
      ClockRole::H1, ClockRole::H2, ClockRole::COLON,
      ClockRole::M1, ClockRole::M2, ClockRole::MANUAL};
  for (uint8_t screen = 0; screen < SCREEN_COUNT; ++screen)
    assert(defaultClockRole(screen) == expected[screen]);
  assert(defaultSavedImage(5) == STATUS_IDLE_IMAGE);
  assert(defaultSavedImage(0) == BLANK_IMAGE);
}

static void testClockImageMapping()
{
  ClockDigits digits = {1, 7, 4, 2, 5, 9, false};
  assert(imageForClockRole(ClockRole::H1, digits) == 1);
  assert(imageForClockRole(ClockRole::H2, digits) == 7);
  assert(imageForClockRole(ClockRole::M1, digits) == 4);
  assert(imageForClockRole(ClockRole::M2, digits) == 2);
  assert(imageForClockRole(ClockRole::S1, digits) == 5);
  assert(imageForClockRole(ClockRole::S2, digits) == 9);
  assert(imageForClockRole(ClockRole::COLON, digits) == COLON_IMAGE);
  assert(imageForClockRole(ClockRole::MANUAL, digits) == BLANK_IMAGE);

  digits.blankHoursTens = true;
  assert(imageForClockRole(ClockRole::H1, digits) == BLANK_IMAGE);
}

static void testDisplayState()
{
  DisplayState state;
  state.resetDefaults();
  assert(state.role(0) == ClockRole::H1);
  assert(state.role(5) == ClockRole::MANUAL);
  assert(state.savedImage(5) == STATUS_IDLE_IMAGE);
  assert(state.currentImage(5) == STATUS_IDLE_IMAGE);

  const LayoutEntry hoursOnly[] = {
      {0, ClockRole::H1},
      {1, ClockRole::H2},
  };
  assert(state.replaceClockLayout(hoursOnly, 2) == LayoutError::OK);
  assert(state.role(0) == ClockRole::H1);
  assert(state.role(1) == ClockRole::H2);
  for (uint8_t screen = 2; screen < SCREEN_COUNT; ++screen)
    assert(state.role(screen) == ClockRole::MANUAL);

  state.setCurrentImage(5, STATUS_WORKING_IMAGE);
  assert(state.currentImage(5) == STATUS_WORKING_IMAGE);
  assert(state.savedImage(5) == STATUS_IDLE_IMAGE);
  state.setSavedImage(5, STATUS_COMPLETE_IMAGE);
  assert(state.currentImage(5) == STATUS_WORKING_IMAGE);
  assert(state.savedImage(5) == STATUS_COMPLETE_IMAGE);

  const LayoutEntry duplicate[] = {
      {0, ClockRole::H1},
      {0, ClockRole::M1},
  };
  assert(state.replaceClockLayout(duplicate, 2) == LayoutError::DUPLICATE_SCREEN);
  assert(state.role(0) == ClockRole::H1);

  const LayoutEntry badScreen[] = {{6, ClockRole::H1}};
  assert(state.replaceClockLayout(badScreen, 1) == LayoutError::INVALID_SCREEN);
  const LayoutEntry badRole[] = {{0, ClockRole::COUNT}};
  assert(state.replaceClockLayout(badRole, 1) == LayoutError::INVALID_ROLE);
}

static void testBmpValidation()
{
  BmpInfo info = {};

  std::vector<uint8_t> valid = makeBmpHeader(135, 240, 24);
  assert(validateBmpHeader(valid.data(), valid.size(), 97974, info) == BmpError::OK);
  assert(info.width == 135);
  assert(info.height == 240);
  assert(info.bitsPerPixel == 24);
  assert(info.requiredBytes == 97974);

  std::vector<uint8_t> tooWide = makeBmpHeader(136, 240, 24);
  assert(validateBmpHeader(tooWide.data(), tooWide.size(), 98614, info) == BmpError::DIMENSIONS);

  std::vector<uint8_t> compressed = makeBmpHeader(135, 240, 24, 1);
  assert(validateBmpHeader(compressed.data(), compressed.size(), 97974, info) == BmpError::COMPRESSION);

  std::vector<uint8_t> unsupportedDepth = makeBmpHeader(135, 240, 16);
  assert(validateBmpHeader(unsupportedDepth.data(), unsupportedDepth.size(), 66294, info) == BmpError::BIT_DEPTH);

  std::vector<uint8_t> negativeHeight = makeBmpHeader(135, uint32_t(-240), 24);
  assert(validateBmpHeader(negativeHeight.data(), negativeHeight.size(), 97974, info) == BmpError::DIMENSIONS);

  std::vector<uint8_t> truncated = makeBmpHeader(135, 240, 24);
  assert(validateBmpHeader(truncated.data(), truncated.size(), 90000, info) == BmpError::TRUNCATED);

  std::vector<uint8_t> badMagic = valid;
  badMagic[0] = 'P';
  assert(validateBmpHeader(badMagic.data(), badMagic.size(), 97974, info) == BmpError::MAGIC);

  std::vector<uint8_t> overlappingDib = valid;
  write32(overlappingDib, 14, 124);
  assert(validateBmpHeader(overlappingDib.data(), overlappingDib.size(), 97974, info) == BmpError::HEADER);

  assert(validateBmpHeader(valid.data(), 20, 97974, info) == BmpError::HEADER);
}

static void testBacklightTypes()
{
  const char *names[] = {"off", "constant", "rainbow", "pulse", "breath"};
  for (uint8_t index = 0; index < sizeof(names) / sizeof(names[0]); ++index)
  {
    BacklightEffect effect = BacklightEffect::OFF;
    assert(parseBacklightEffect(names[index], effect));
    assert(uint8_t(effect) == index);
    assert(strcmp(backlightEffectName(effect), names[index]) == 0);
  }
  BacklightEffect effect = BacklightEffect::OFF;
  assert(!parseBacklightEffect("Test", effect));
  assert(!parseBacklightEffect("Constant", effect));

  const uint8_t expectedBrightness[] = {1, 3, 7, 15, 31, 63, 127, 255};
  for (uint8_t level = 0; level < 8; ++level)
    assert(brightnessToHardware(level) == expectedBrightness[level]);
  assert(brightnessToHardware(8) == 255);

  assert(lerpColor(0x000000, 0xFFFFFF, 0, 1000) == 0x000000);
  assert(lerpColor(0x000000, 0xFFFFFF, 500, 1000) == 0x808080);
  assert(lerpColor(0x102030, 0x90A0B0, 1000, 1000) == 0x90A0B0);
  assert(lerpColor(0x102030, 0x90A0B0, 5, 0) == 0x90A0B0);
}

static void testPersistedConfigValidation()
{
  PersistedConfigV1 config = {};
  for (uint8_t screen = 0; screen < SCREEN_COUNT; ++screen)
  {
    config.roles[screen] = uint8_t(defaultClockRole(screen));
    config.savedImages[screen] = defaultSavedImage(screen);
  }
  config.effect = uint8_t(BacklightEffect::CONSTANT);
  config.color = 0xFF8000;
  config.brightness = 7;
  config.pulseBpm = 60;
  config.breathBpm = 20;
  config.rainbowSeconds = 8.0f;
  assert(sizeof(config) == 24);
  assert(validatePersistedConfig(config));

  PersistedConfigV1 invalid = config;
  invalid.roles[2] = uint8_t(ClockRole::COUNT);
  assert(!validatePersistedConfig(invalid));
  invalid = config;
  invalid.effect = uint8_t(BacklightEffect::COUNT);
  assert(!validatePersistedConfig(invalid));
  invalid = config;
  invalid.brightness = 8;
  assert(!validatePersistedConfig(invalid));
  invalid = config;
  invalid.pulseBpm = 19;
  assert(!validatePersistedConfig(invalid));
  invalid = config;
  invalid.breathBpm = 61;
  assert(!validatePersistedConfig(invalid));
  invalid = config;
  invalid.rainbowSeconds = 10.1f;
  assert(!validatePersistedConfig(invalid));
}

static void assertValidAsset(uint16_t image)
{
  char path[32];
  snprintf(path, sizeof(path), "data/%u.bmp", image);
  std::ifstream file(path, std::ios::binary | std::ios::ate);
  assert(file.good());
  const std::streamsize size = file.tellg();
  assert(size > 0 && size <= 102400);
  file.seekg(0);
  uint8_t header[54] = {};
  file.read(reinterpret_cast<char *>(header), sizeof(header));
  assert(file.gcount() == sizeof(header));
  BmpInfo info = {};
  assert(validateBmpHeader(header, sizeof(header), uint32_t(size), info) == BmpError::OK);
}

static void testDefaultAssets()
{
  for (uint16_t image = 0; image <= 9; ++image)
    assertValidAsset(image);
  for (uint16_t image = 250; image <= 254; ++image)
    assertValidAsset(image);
}

int main()
{
  testImageNames();
  testClockRoles();
  testClockImageMapping();
  testDisplayState();
  testBmpValidation();
  testBacklightTypes();
  testPersistedConfigValidation();
  testDefaultAssets();
  puts("ipstube_control_tests: PASS");
  return 0;
}
