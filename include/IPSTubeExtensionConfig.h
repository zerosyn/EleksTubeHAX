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
  const IPSTubeControl::PersistedConfigV1 &get() const { return config_; }
  bool wasLoaded() const { return loaded_; }

private:
  void setDefaults(const IPSTubeControl::BacklightSettings &legacyBacklight);

  Preferences preferences_;
  IPSTubeControl::PersistedConfigV1 config_ = {};
  bool loaded_ = false;
};

extern IPSTubeExtensionConfig ipstubeExtensionConfig;

#endif
#endif
