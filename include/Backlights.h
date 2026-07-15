#ifndef BACKLIGHTS_H
#define BACKLIGHTS_H

#include "GLOBAL_DEFINES.h"

/*
 * A simple sub-class of the Adafruit_NeoPixel class, to configure it for
 * the EleksTube-IPS clock, and to add a little functionality.
 *
 * The good news is, the pixel numbers in the string line up perfectly
 * with the #defines in Hardware.h, so you can pass SECONDS_ONES directly
 * as the pixel index, no mapping required.
 *
 * Otherwise, class Backlights behaves exactly as Adafruit_NeoPixel does.
 */
#include <stdint.h>
#include <math.h>
#include "StoredConfig.h"
#include <Adafruit_NeoPixel.h>
#ifdef HARDWARE_IPSTUBE_CLOCK
#include "IPSTubeControlTypes.h"
#endif

class Backlights : public Adafruit_NeoPixel
{
public:
  Backlights() : config(NULL), pattern_needs_init(true), off(true),
                 Adafruit_NeoPixel(NUM_BACKLIGHT_LEDS, BACKLIGHTS_PIN, NEO_GRB + NEO_KHZ800)
  {
  }

  enum patterns
  {
    dark,
    test,
    constant,
    rainbow,
    pulse,
    breath,
    num_patterns
  };
  const static String patterns_str[num_patterns];

  void begin(StoredConfig::Config::Backlights *config_);
  void loop();

  void togglePower()
  {
    off = !off;
    pattern_needs_init = true;
  }
  void PowerOn()
  {
    off = false;
    pattern_needs_init = true;
  }
  void PowerOff()
  {
    off = true;
    pattern_needs_init = true;
  }
  bool getPower() { return !off; }

  void setPattern(patterns p)
  {
    config->pattern = uint8_t(p);
    pattern_needs_init = true;
#ifdef HARDWARE_IPSTUBE_CLOCK
    if (controlActive_)
    {
      controlledSettings_.effect = patternToEffect(p);
      markLegacyChange();
    }
#endif
  }
  patterns getPattern();
  String getPatternStr() { return patterns_str[uint8_t(getPattern())]; }
  void setNextPattern(int8_t i = 1);
  void setPrevPattern() { setNextPattern(-1); }

  // Configure the patterns
  void setPulseRate(uint8_t bpm)
  {
    config->pulse_bpm = bpm;
#ifdef HARDWARE_IPSTUBE_CLOCK
    if (controlActive_)
    {
      controlledSettings_.pulseBpm = bpm;
      markLegacyChange();
    }
#endif
  }
  uint8_t getPulseRate();
  void setBreathRate(uint8_t per_min)
  {
    config->breath_per_min = per_min;
#ifdef HARDWARE_IPSTUBE_CLOCK
    if (controlActive_)
    {
      controlledSettings_.breathBpm = per_min;
      markLegacyChange();
    }
#endif
  }
  uint8_t getBreathRate();
  void setRainbowDuration(float seconds)
  {
    config->rainbow_sec = seconds;
#ifdef HARDWARE_IPSTUBE_CLOCK
    if (controlActive_)
    {
      controlledSettings_.rainbowSeconds = seconds;
      markLegacyChange();
    }
#endif
  }
  float getRainbowDuration();

  // Used by all constant color patterns.
  void setColorPhase(uint16_t phase)
  {
    config->color_phase = phase % max_phase;
    pattern_needs_init = true;
#ifdef HARDWARE_IPSTUBE_CLOCK
    if (controlActive_)
    {
      controlledSettings_.color = phaseToColor(config->color_phase);
      markLegacyChange();
    }
#endif
  }
  void adjustColorPhase(int16_t adj);
  uint16_t getColorPhase() { return config->color_phase; }
  uint32_t getColor();

  void setIntensity(uint8_t intensity);
  void adjustIntensity(int16_t adj);
  uint8_t getIntensity();

#ifdef HARDWARE_IPSTUBE_CLOCK
  void loadControlSettings(const IPSTubeControl::BacklightSettings &settings);
  void applyControlSettings(const IPSTubeControl::BacklightSettings &settings,
                            uint32_t transitionMs);
  const IPSTubeControl::BacklightSettings &getControlSettings() const { return controlledSettings_; }
  const IPSTubeControl::BacklightSettings &getPersistenceSettings() const { return persistenceSettings_; }
  bool isTransitioning() const { return transitioning_; }
  bool persistenceRequested() const { return persistenceRequested_; }
  void clearPersistenceRequested() { persistenceRequested_ = false; }
#endif

  void setDimming(bool dim)
  {
    dimming = dim;
    pattern_needs_init = true;
  }

  // Helper methods
  uint32_t phaseToColor(uint16_t phase);
  uint32_t hueToPhase(float hue);
  float phaseToHue(uint32_t phase);
  uint8_t phaseToIntensity(uint16_t phase);

  const uint16_t max_phase = 768;  // 256 up, 256 down, 256 off
  const uint8_t max_intensity = 8; // 0 to 7

private:
  bool dimming = false;
  bool pattern_needs_init;
  bool off;

  // Pattern configs, get backed up.
  StoredConfig::Config::Backlights *config;

  // Pattern methods
  void testPattern();
  void rainbowPattern();
  void pulsePattern();
  void breathPattern();

#ifdef HARDWARE_IPSTUBE_CLOCK
  void markLegacyChange();
  void controlledLoop();
  IPSTubeControl::BacklightEffect patternToEffect(patterns pattern) const;
  patterns effectToPattern(IPSTubeControl::BacklightEffect effect) const;
  uint32_t scaleColor(uint32_t color, uint8_t scale) const;

  bool controlActive_ = false;
  bool persistenceRequested_ = false;
  bool transitioning_ = false;
  uint32_t transitionStartMs_ = 0;
  uint32_t transitionDurationMs_ = 0;
  IPSTubeControl::BacklightSettings controlledSettings_ = {};
  IPSTubeControl::BacklightSettings persistenceSettings_ = {};
  uint32_t transitionFrom_[NUM_BACKLIGHT_LEDS] = {};
  uint32_t lastRendered_[NUM_BACKLIGHT_LEDS] = {};
#endif

  const uint32_t test_ms_delay = 250;
};

extern Backlights backlights;

#endif // BACKLIGHTS_H
