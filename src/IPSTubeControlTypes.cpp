#include "IPSTubeControlTypes.h"

#include <stdio.h>
#include <string.h>

namespace IPSTubeControl
{
static const char *const CLOCK_ROLE_NAMES[] = {
    "MANUAL", "H1", "H2", "M1", "M2", "S1", "S2", "COLON"};
static const char *const BACKLIGHT_EFFECT_NAMES[] = {
    "off", "constant", "rainbow", "pulse", "breath"};
static const char *const ANIMATION_PRESET_NAMES[] = {
    "off", "matrix", "rings", "squares", "swirl"};

void imageName(uint8_t image, char *buffer, size_t bufferSize)
{
  if (bufferSize == 0)
    return;

  switch (image)
  {
  case COLON_IMAGE:
    snprintf(buffer, bufferSize, "COLON");
    break;
  case STATUS_IDLE_IMAGE:
    snprintf(buffer, bufferSize, "STATUS_IDLE");
    break;
  case STATUS_WORKING_IMAGE:
    snprintf(buffer, bufferSize, "STATUS_WORKING");
    break;
  case STATUS_WAITING_IMAGE:
    snprintf(buffer, bufferSize, "STATUS_WAITING");
    break;
  case STATUS_COMPLETE_IMAGE:
    snprintf(buffer, bufferSize, "STATUS_COMPLETE");
    break;
  case BLANK_IMAGE:
    snprintf(buffer, bufferSize, "BLANK");
    break;
  default:
    snprintf(buffer, bufferSize, "IMAGE_%03u", unsigned(image));
    break;
  }
}

const char *clockRoleName(ClockRole role)
{
  const uint8_t index = uint8_t(role);
  return index < uint8_t(ClockRole::COUNT) ? CLOCK_ROLE_NAMES[index] : "UNKNOWN";
}

bool parseClockRole(const char *name, ClockRole &role)
{
  if (name == nullptr)
    return false;

  for (uint8_t index = 0; index < uint8_t(ClockRole::COUNT); ++index)
  {
    if (strcmp(name, CLOCK_ROLE_NAMES[index]) == 0)
    {
      role = ClockRole(index);
      return true;
    }
  }
  return false;
}

ClockRole defaultClockRole(uint8_t screen)
{
  static const ClockRole DEFAULT_ROLES[SCREEN_COUNT] = {
      ClockRole::MANUAL, ClockRole::M2, ClockRole::M1,
      ClockRole::COLON, ClockRole::H2, ClockRole::H1};
  return screen < SCREEN_COUNT ? DEFAULT_ROLES[screen] : ClockRole::MANUAL;
}

uint8_t defaultSavedImage(uint8_t screen)
{
  if (screen == 3)
    return COLON_IMAGE;
  if (screen == 0)
    return STATUS_IDLE_IMAGE;
  return BLANK_IMAGE;
}

static uint8_t validDigit(uint8_t digit)
{
  return digit <= 9 ? digit : BLANK_IMAGE;
}

uint8_t imageForClockRole(ClockRole role, const ClockDigits &digits)
{
  switch (role)
  {
  case ClockRole::H1:
    return digits.blankHoursTens ? BLANK_IMAGE : validDigit(digits.hoursTens);
  case ClockRole::H2:
    return validDigit(digits.hoursOnes);
  case ClockRole::M1:
    return validDigit(digits.minutesTens);
  case ClockRole::M2:
    return validDigit(digits.minutesOnes);
  case ClockRole::S1:
    return validDigit(digits.secondsTens);
  case ClockRole::S2:
    return validDigit(digits.secondsOnes);
  case ClockRole::COLON:
    return COLON_IMAGE;
  case ClockRole::MANUAL:
  case ClockRole::COUNT:
    return BLANK_IMAGE;
  }
  return BLANK_IMAGE;
}

void DisplayState::resetDefaults()
{
  for (uint8_t screen = 0; screen < SCREEN_COUNT; ++screen)
  {
    roles_[screen] = defaultClockRole(screen);
    savedImages_[screen] = defaultSavedImage(screen);
    currentImages_[screen] = savedImages_[screen];
  }
}

LayoutError DisplayState::replaceClockLayout(const LayoutEntry *entries, size_t count)
{
  bool seen[SCREEN_COUNT] = {};
  for (size_t index = 0; index < count; ++index)
  {
    if (entries == nullptr || entries[index].screen >= SCREEN_COUNT)
      return LayoutError::INVALID_SCREEN;
    if (uint8_t(entries[index].role) >= uint8_t(ClockRole::COUNT))
      return LayoutError::INVALID_ROLE;
    if (seen[entries[index].screen])
      return LayoutError::DUPLICATE_SCREEN;
    seen[entries[index].screen] = true;
  }

  for (uint8_t screen = 0; screen < SCREEN_COUNT; ++screen)
    roles_[screen] = ClockRole::MANUAL;
  for (size_t index = 0; index < count; ++index)
    roles_[entries[index].screen] = entries[index].role;
  return LayoutError::OK;
}

ClockRole DisplayState::role(uint8_t screen) const
{
  return screen < SCREEN_COUNT ? roles_[screen] : ClockRole::MANUAL;
}

uint8_t DisplayState::currentImage(uint8_t screen) const
{
  return screen < SCREEN_COUNT ? currentImages_[screen] : BLANK_IMAGE;
}

uint8_t DisplayState::savedImage(uint8_t screen) const
{
  return screen < SCREEN_COUNT ? savedImages_[screen] : BLANK_IMAGE;
}

void DisplayState::setCurrentImage(uint8_t screen, uint8_t image)
{
  if (screen < SCREEN_COUNT)
    currentImages_[screen] = image;
}

void DisplayState::setSavedImage(uint8_t screen, uint8_t image)
{
  if (screen < SCREEN_COUNT)
    savedImages_[screen] = image;
}

const char *backlightEffectName(BacklightEffect effect)
{
  const uint8_t index = uint8_t(effect);
  return index < uint8_t(BacklightEffect::COUNT) ? BACKLIGHT_EFFECT_NAMES[index] : "unknown";
}

bool parseBacklightEffect(const char *name, BacklightEffect &effect)
{
  if (name == nullptr)
    return false;
  for (uint8_t index = 0; index < uint8_t(BacklightEffect::COUNT); ++index)
  {
    if (strcmp(name, BACKLIGHT_EFFECT_NAMES[index]) == 0)
    {
      effect = BacklightEffect(index);
      return true;
    }
  }
  return false;
}

const char *animationPresetName(AnimationPreset preset)
{
  const uint8_t index = uint8_t(preset);
  return index < uint8_t(AnimationPreset::COUNT) ? ANIMATION_PRESET_NAMES[index] : "unknown";
}

bool parseAnimationPreset(const char *name, AnimationPreset &preset)
{
  if (name == nullptr)
    return false;
  for (uint8_t index = 0; index < uint8_t(AnimationPreset::COUNT); ++index)
  {
    if (strcmp(name, ANIMATION_PRESET_NAMES[index]) == 0)
    {
      preset = AnimationPreset(index);
      return true;
    }
  }
  return false;
}

uint8_t brightnessToHardware(uint8_t brightness)
{
  if (brightness > 7)
    brightness = 7;
  return uint8_t(0xFFU >> (7U - brightness));
}

static uint8_t lerpChannel(uint8_t from, uint8_t to, uint32_t elapsed, uint32_t duration)
{
  if (duration == 0 || elapsed >= duration)
    return to;
  const uint64_t numerator = uint64_t(from) * (duration - elapsed) +
                             uint64_t(to) * elapsed + duration / 2U;
  return uint8_t(numerator / duration);
}

uint32_t lerpColor(uint32_t from, uint32_t to, uint32_t elapsed, uint32_t duration)
{
  const uint8_t red = lerpChannel(uint8_t(from >> 16U), uint8_t(to >> 16U), elapsed, duration);
  const uint8_t green = lerpChannel(uint8_t(from >> 8U), uint8_t(to >> 8U), elapsed, duration);
  const uint8_t blue = lerpChannel(uint8_t(from), uint8_t(to), elapsed, duration);
  return (uint32_t(red) << 16U) | (uint32_t(green) << 8U) | blue;
}

bool validatePersistedConfig(const PersistedConfigV1 &config)
{
  for (uint8_t screen = 0; screen < SCREEN_COUNT; ++screen)
  {
    if (config.roles[screen] >= uint8_t(ClockRole::COUNT))
      return false;
  }
  if (config.effect >= uint8_t(BacklightEffect::COUNT) || config.brightness > 7)
    return false;
  if (config.pulseBpm < 20 || config.pulseBpm > 120)
    return false;
  if (config.breathBpm < 5 || config.breathBpm > 60)
    return false;
  if (!(config.rainbowSeconds >= 0.2f && config.rainbowSeconds <= 10.0f))
    return false;
  return true;
}
}
