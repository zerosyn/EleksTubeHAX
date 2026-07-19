#include "IPSTubeExtensionConfig.h"

#ifdef HARDWARE_IPSTUBE_CLOCK

#include <string.h>

using namespace IPSTubeControl;

namespace
{
constexpr const char *NAMESPACE = "ipstube_ext";
constexpr const char *SCHEMA_KEY = "schema";
constexpr const char *PAYLOAD_KEY = "payload";
constexpr uint8_t SCHEMA_VERSION = 1;
constexpr const char *ANIMATION_SCHEMA_KEY = "anim_schema";
constexpr const char *ANIMATIONS_KEY = "animations";
constexpr uint8_t ANIMATION_SCHEMA_VERSION = 1;
}

IPSTubeExtensionConfig ipstubeExtensionConfig;

void IPSTubeExtensionConfig::setDefaults(const BacklightSettings &legacyBacklight)
{
  config_ = {};
  for (uint8_t screen = 0; screen < SCREEN_COUNT; ++screen)
  {
    config_.roles[screen] = uint8_t(defaultClockRole(screen));
    config_.savedImages[screen] = defaultSavedImage(screen);
    animations_[screen] = uint8_t(AnimationPreset::OFF);
  }
  config_.effect = uint8_t(legacyBacklight.effect);
  config_.color = legacyBacklight.color & 0xFFFFFFU;
  config_.brightness = legacyBacklight.brightness > 7 ? 7 : legacyBacklight.brightness;
  config_.pulseBpm = legacyBacklight.pulseBpm;
  config_.breathBpm = legacyBacklight.breathBpm;
  config_.rainbowSeconds = legacyBacklight.rainbowSeconds;

  if (!validatePersistedConfig(config_))
  {
    config_.effect = uint8_t(BacklightEffect::RAINBOW);
    config_.brightness = 7;
    config_.pulseBpm = 60;
    config_.breathBpm = 20;
    config_.rainbowSeconds = 8.0f;
  }
}

void IPSTubeExtensionConfig::loadAnimations()
{
  const uint8_t schema = preferences_.getUChar(ANIMATION_SCHEMA_KEY, 0);
  const size_t length = preferences_.getBytesLength(ANIMATIONS_KEY);
  if (schema == 0 && length == 0)
    return;
  if (schema != ANIMATION_SCHEMA_VERSION || length != sizeof(animations_))
  {
    Serial.println("IPSTube animation config version/length unknown; using defaults.");
    return;
  }

  uint8_t loaded[SCREEN_COUNT] = {};
  if (preferences_.getBytes(ANIMATIONS_KEY, loaded, sizeof(loaded)) != sizeof(loaded))
    return;
  for (uint8_t screen = 0; screen < SCREEN_COUNT; ++screen)
  {
    if (loaded[screen] >= uint8_t(AnimationPreset::COUNT))
    {
      Serial.println("IPSTube animation config invalid; using defaults.");
      return;
    }
  }
  memcpy(animations_, loaded, sizeof(animations_));
}

void IPSTubeExtensionConfig::begin(const BacklightSettings &legacyBacklight)
{
  setDefaults(legacyBacklight);
  if (!preferences_.begin(NAMESPACE, false))
  {
    Serial.println("IPSTube extension NVS open failed; using defaults.");
    return;
  }
  loadAnimations();

  const uint8_t schema = preferences_.getUChar(SCHEMA_KEY, 0);
  const size_t length = preferences_.getBytesLength(PAYLOAD_KEY);
  if (schema != SCHEMA_VERSION || length != sizeof(PersistedConfigV1))
  {
    if (schema != 0)
      Serial.println("IPSTube extension config version/length unknown; using defaults.");
    return;
  }

  PersistedConfigV1 loaded = {};
  if (preferences_.getBytes(PAYLOAD_KEY, &loaded, sizeof(loaded)) != sizeof(loaded) ||
      !validatePersistedConfig(loaded))
  {
    Serial.println("IPSTube extension config invalid; using defaults.");
    return;
  }

  config_ = loaded;
  loaded_ = true;
}

bool IPSTubeExtensionConfig::save(const PersistedConfigV1 &config)
{
  if (!validatePersistedConfig(config))
    return false;
  if (preferences_.putBytes(PAYLOAD_KEY, &config, sizeof(config)) != sizeof(config))
    return false;
  if (preferences_.getUChar(SCHEMA_KEY, 0) != SCHEMA_VERSION &&
      preferences_.putUChar(SCHEMA_KEY, SCHEMA_VERSION) != sizeof(uint8_t))
    return false;
  config_ = config;
  loaded_ = true;
  return true;
}

bool IPSTubeExtensionConfig::saveAnimations(const uint8_t animations[SCREEN_COUNT])
{
  if (animations == nullptr)
    return false;
  for (uint8_t screen = 0; screen < SCREEN_COUNT; ++screen)
  {
    if (animations[screen] >= uint8_t(AnimationPreset::COUNT))
      return false;
  }
  if (preferences_.putBytes(ANIMATIONS_KEY, animations, sizeof(animations_)) != sizeof(animations_))
    return false;
  if (preferences_.getUChar(ANIMATION_SCHEMA_KEY, 0) != ANIMATION_SCHEMA_VERSION &&
      preferences_.putUChar(ANIMATION_SCHEMA_KEY, ANIMATION_SCHEMA_VERSION) != sizeof(uint8_t))
    return false;
  memcpy(animations_, animations, sizeof(animations_));
  return true;
}

#endif
