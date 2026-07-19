#ifndef IPSTUBE_EXTENSION_CONFIG_H
#define IPSTUBE_EXTENSION_CONFIG_H

#include "GLOBAL_DEFINES.h"

#ifdef HARDWARE_IPSTUBE_CLOCK

#include "IPSTubeControlTypes.h"
#include <Preferences.h>

class IPSTubeExtensionConfig
{
public:
  void begin(const IPSTubeControl::BacklightSettings &legacyBacklight);
  bool save(const IPSTubeControl::PersistedConfigV1 &config);
  bool saveAnimations(const uint8_t animations[IPSTubeControl::SCREEN_COUNT]);
  const IPSTubeControl::PersistedConfigV1 &get() const { return config_; }
  const uint8_t *getSavedAnimations() const { return animations_; }
  bool wasLoaded() const { return loaded_; }

private:
  void setDefaults(const IPSTubeControl::BacklightSettings &legacyBacklight);
  void loadAnimations();

  Preferences preferences_;
  IPSTubeControl::PersistedConfigV1 config_ = {};
  uint8_t animations_[IPSTubeControl::SCREEN_COUNT] = {};
  bool loaded_ = false;
};

extern IPSTubeExtensionConfig ipstubeExtensionConfig;

#endif
#endif
