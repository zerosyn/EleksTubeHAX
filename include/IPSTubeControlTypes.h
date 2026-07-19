#ifndef IPSTUBE_CONTROL_TYPES_H
#define IPSTUBE_CONTROL_TYPES_H

#include <stddef.h>
#include <stdint.h>

namespace IPSTubeControl
{
constexpr uint8_t SCREEN_COUNT = 6;
constexpr uint8_t COLON_IMAGE = 250;
constexpr uint8_t STATUS_IDLE_IMAGE = 251;
constexpr uint8_t STATUS_WORKING_IMAGE = 252;
constexpr uint8_t STATUS_WAITING_IMAGE = 253;
constexpr uint8_t STATUS_COMPLETE_IMAGE = 254;
constexpr uint8_t BLANK_IMAGE = 255;

enum class ClockRole : uint8_t
{
  MANUAL = 0,
  H1,
  H2,
  M1,
  M2,
  S1,
  S2,
  COLON,
  COUNT
};

struct ClockDigits
{
  uint8_t hoursTens;
  uint8_t hoursOnes;
  uint8_t minutesTens;
  uint8_t minutesOnes;
  uint8_t secondsTens;
  uint8_t secondsOnes;
  bool blankHoursTens;
};

struct LayoutEntry
{
  uint8_t screen;
  ClockRole role;
};

enum class LayoutError : uint8_t
{
  OK = 0,
  INVALID_SCREEN,
  INVALID_ROLE,
  DUPLICATE_SCREEN
};

enum class BacklightEffect : uint8_t
{
  OFF = 0,
  CONSTANT,
  RAINBOW,
  PULSE,
  BREATH,
  COUNT
};

enum class AnimationPreset : uint8_t
{
  OFF = 0,
  MATRIX,
  RINGS,
  SQUARES,
  SWIRL,
  COUNT
};

struct BacklightSettings
{
  BacklightEffect effect;
  uint32_t color;
  uint8_t brightness;
  uint8_t pulseBpm;
  uint8_t breathBpm;
  float rainbowSeconds;
};

#pragma pack(push, 1)
struct PersistedConfigV1
{
  uint8_t roles[SCREEN_COUNT];
  uint8_t savedImages[SCREEN_COUNT];
  uint8_t effect;
  uint32_t color;
  uint8_t brightness;
  uint8_t pulseBpm;
  uint8_t breathBpm;
  float rainbowSeconds;
};
#pragma pack(pop)

static_assert(sizeof(PersistedConfigV1) == 24, "PersistedConfigV1 layout changed");

class DisplayState
{
public:
  DisplayState() { resetDefaults(); }
  void resetDefaults();
  LayoutError replaceClockLayout(const LayoutEntry *entries, size_t count);
  ClockRole role(uint8_t screen) const;
  uint8_t currentImage(uint8_t screen) const;
  uint8_t savedImage(uint8_t screen) const;
  void setCurrentImage(uint8_t screen, uint8_t image);
  void setSavedImage(uint8_t screen, uint8_t image);

private:
  ClockRole roles_[SCREEN_COUNT];
  uint8_t currentImages_[SCREEN_COUNT];
  uint8_t savedImages_[SCREEN_COUNT];
};

void imageName(uint8_t image, char *buffer, size_t bufferSize);
const char *clockRoleName(ClockRole role);
bool parseClockRole(const char *name, ClockRole &role);
ClockRole defaultClockRole(uint8_t screen);
uint8_t defaultSavedImage(uint8_t screen);
uint8_t imageForClockRole(ClockRole role, const ClockDigits &digits);
const char *backlightEffectName(BacklightEffect effect);
bool parseBacklightEffect(const char *name, BacklightEffect &effect);
const char *animationPresetName(AnimationPreset preset);
bool parseAnimationPreset(const char *name, AnimationPreset &preset);
uint8_t brightnessToHardware(uint8_t brightness);
uint32_t lerpColor(uint32_t from, uint32_t to, uint32_t elapsed, uint32_t duration);
bool validatePersistedConfig(const PersistedConfigV1 &config);
}

#endif
