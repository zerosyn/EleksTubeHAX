#include "Backlights.h"

void Backlights::begin(StoredConfig::Config::Backlights *config_)
{
  Adafruit_NeoPixel::begin(); // Initialize RMT and pin
  config = config_;

  if (config->is_valid != StoredConfig::valid)
  {
    // Config is invalid, probably a new device never had its config written.
    // Load some reasonable defaults.
    Serial.println("Loaded Backlights config is invalid, using default.  This is normal on first boot.");
    setPattern(rainbow);
    setColorPhase(0);
    setIntensity(max_intensity - 1);
    setPulseRate(60);
    setBreathRate(20);
    setRainbowDuration(DEFAULT_BL_RAINBOW_DURATION_SEC);
    config->is_valid = StoredConfig::valid;
  }
  off = false;
}

// These feel like they should be generalizable into a helper function.
// https://stackoverflow.com/questions/11720656/modulo-operation-with-negative-numbers
void Backlights::setNextPattern(int8_t i)
{
  int8_t next_pattern = (config->pattern + i) % num_patterns;
  while (next_pattern < 0)
  {
    next_pattern += num_patterns;
  }
  setPattern(patterns(next_pattern));
}

void Backlights::adjustColorPhase(int16_t adj)
{
  int16_t new_phase = (int16_t(config->color_phase % max_phase) + adj) % max_phase;
  while (new_phase < 0)
  {
    new_phase += max_phase;
  }
  setColorPhase(new_phase);
}

void Backlights::adjustIntensity(int16_t adj)
{
  int16_t new_intensity = (int16_t(config->intensity) + adj) % max_intensity;
  while (new_intensity < 0)
  {
    new_intensity += max_intensity;
  }
  setIntensity(new_intensity);
}

void Backlights::setIntensity(uint8_t intensity)
{
  if (intensity >= max_intensity)
    intensity = max_intensity - 1;
  config->intensity = intensity;
  setBrightness(0xFF >> max_intensity - config->intensity - 1);
  pattern_needs_init = true;
#ifdef HARDWARE_IPSTUBE_CLOCK
  if (controlActive_)
  {
    controlledSettings_.brightness = intensity;
    markLegacyChange();
  }
#endif
}

Backlights::patterns Backlights::getPattern()
{
#ifdef HARDWARE_IPSTUBE_CLOCK
  if (controlActive_)
    return effectToPattern(controlledSettings_.effect);
#endif
  return patterns(config->pattern);
}

uint8_t Backlights::getPulseRate()
{
#ifdef HARDWARE_IPSTUBE_CLOCK
  if (controlActive_)
    return controlledSettings_.pulseBpm;
#endif
  return config->pulse_bpm;
}

uint8_t Backlights::getBreathRate()
{
#ifdef HARDWARE_IPSTUBE_CLOCK
  if (controlActive_)
    return controlledSettings_.breathBpm;
#endif
  return config->breath_per_min;
}

float Backlights::getRainbowDuration()
{
#ifdef HARDWARE_IPSTUBE_CLOCK
  if (controlActive_)
    return controlledSettings_.rainbowSeconds;
#endif
  return config->rainbow_sec;
}

uint8_t Backlights::getIntensity()
{
#ifdef HARDWARE_IPSTUBE_CLOCK
  if (controlActive_)
    return controlledSettings_.brightness;
#endif
  return config->intensity;
}

uint32_t Backlights::getColor()
{
#ifdef HARDWARE_IPSTUBE_CLOCK
  if (controlActive_)
    return controlledSettings_.color;
#endif
  return phaseToColor(config->color_phase);
}

void Backlights::loop()
{
#ifdef HARDWARE_IPSTUBE_CLOCK
  if (controlActive_)
  {
    controlledLoop();
    return;
  }
#endif
  //   enum patterns { dark, test, constant, rainbow, pulse, breath, num_patterns };
  if (off || config->pattern == dark)
  {
    if (pattern_needs_init)
    {
      clear();
      show();
    }
  }
  else if (config->pattern == test)
  {
    testPattern();
  }
  else if (config->pattern == constant)
  {
    if (pattern_needs_init)
    {
      fill(phaseToColor(config->color_phase));
    }
    if (dimming)
    {
      setBrightness(0xFF >> max_intensity - BACKLIGHT_DIMMED_INTENSITY - 1);
    }
    else
    {
      setBrightness(0xFF >> max_intensity - config->intensity - 1);
    }
    show();
  }
  else if (config->pattern == rainbow)
  {
    rainbowPattern();
  }
  else if (config->pattern == pulse)
  {
    pulsePattern();
  }
  else if (config->pattern == breath)
  {
    breathPattern();
  }

  pattern_needs_init = false;
}

void Backlights::pulsePattern()
{
  fill(phaseToColor(config->color_phase));

  float pulse_length_millis = (60.0f * 1000) / config->pulse_bpm;
  float val = 1 + abs(sin(2 * M_PI * millis() / pulse_length_millis)) * 254;
  if (dimming)
  {
    val = val * BACKLIGHT_DIMMED_INTENSITY / 7;
  }
  else
  {
    val = val * config->intensity / 7;
  }
  setBrightness((uint8_t)val);

  show();
}

void Backlights::breathPattern()
{
  fill(phaseToColor(config->color_phase));

  // https://sean.voisen.org/blog/2011/10/breathing-led-with-arduino/
  // Avoid a 0 value as it shuts off the LEDs and we have to re-initialize.
  float pulse_length_millis = (60.0f * 1000) / config->breath_per_min;
  float val = (exp(sin(2 * M_PI * millis() / pulse_length_millis)) - 0.36787944f) * 108.0f;

  if (dimming)
  {
    val = val * BACKLIGHT_DIMMED_INTENSITY / 7;
  }
  else
  {
    val = val * config->intensity / 7;
  }

  uint8_t brightness = (uint8_t)val;
  if (brightness < 1)
  {
    brightness = 1;
  }
  setBrightness(brightness);

  show();
}

void Backlights::testPattern()
{
  const uint8_t num_colors = 4; // or 3 if you don't want black
  uint8_t num_states = NUM_BACKLIGHT_LEDS * num_colors;
  uint8_t state = (millis() / test_ms_delay) % num_states;

  uint8_t digit = state / num_colors;
  uint32_t color = 0xFF0000 >> (state % num_colors) * 8;

  clear();
  setPixelColor(digit, color);

  if (dimming)
  {
    setBrightness(0xFF >> max_intensity - (uint8_t)BACKLIGHT_DIMMED_INTENSITY - 1);
  }
  else
  {
    setBrightness(0xFF >> max_intensity - config->intensity - 1);
  }

  show();
}

uint8_t Backlights::phaseToIntensity(uint16_t phase)
{
  uint16_t color = 0;
  if (phase <= 255)
  {
    // Ramping up
    color = phase;
  }
  else if (phase <= 511)
  {
    // Ramping down
    color = 511 - phase;
  }
  else
  {
    // Off
    color = 0;
  }
  if (color > 255)
  {
    // TODO: Trigger ERROR STATE, bug in code.
  }
  return uint8_t(color % 256);
}

uint32_t Backlights::phaseToColor(uint16_t phase)
{
  uint8_t red = phaseToIntensity(phase);
  uint8_t green = phaseToIntensity((phase + 256) % max_phase);
  uint8_t blue = phaseToIntensity((phase + 512) % max_phase);
  return (uint32_t(red) << 16 | uint32_t(green) << 8 | uint32_t(blue));
}

uint32_t Backlights::hueToPhase(float hue)
{
  hue = hue - 120.f;
  if (hue < 0)
  {
    hue = hue + 360.f;
  }
  uint32_t phase = uint32_t(round(768.f * (1.f - hue / 360.f)));
  phase = phase % max_phase;
  return (phase);
}

float Backlights::phaseToHue(uint32_t phase)
{
  float hue = 120.f + ((768.f - float(phase)) / 768.f) * 360.f;
  // h = 120 + (1 - p/768)*360
  if (hue >= 360.f)
  {
    hue = hue - 360.f;
  }
  return (round(hue));
}

void Backlights::rainbowPattern()
{
  // Divide by 3 to spread it out some, so the whole rainbow isn't displayed at once.
  // TODO Make this /3 a parameter
  const uint16_t phase_per_digit = (max_phase / NUM_BACKLIGHT_LEDS) / 3;

  // Rainbow roatation speed now configurable
  uint16_t duration = uint16_t(round(getRainbowDuration() * 1000));
  uint16_t phase = uint16_t(round(float(millis() % duration) / duration * max_phase));

  for (uint8_t digit = 0; digit < NUM_BACKLIGHT_LEDS; digit++)
  {
    // Shift the phase for this LED.
    uint16_t my_phase = (phase + digit * phase_per_digit) % max_phase;
    setPixelColor(digit, phaseToColor(my_phase));
  }
  if (dimming)
  {
#if BACKLIGHT_DIMMED_INTENSITY > 0
    setBrightness(0xFF >> max_intensity - (uint8_t)BACKLIGHT_DIMMED_INTENSITY - 1);
#else // turn off backlight if intensity is 0
    setBrightness(0);
#endif
  }
  else
  {
    setBrightness(0xFF >> max_intensity - config->intensity - 1);
  }
  show();
}

const String Backlights::patterns_str[Backlights::num_patterns] =
    {"Dark", "Test", "Constant", "Rainbow", "Pulse", "Breath"};

#ifdef HARDWARE_IPSTUBE_CLOCK

IPSTubeControl::BacklightEffect Backlights::patternToEffect(patterns pattern) const
{
  switch (pattern)
  {
  case dark:
    return IPSTubeControl::BacklightEffect::OFF;
  case rainbow:
    return IPSTubeControl::BacklightEffect::RAINBOW;
  case pulse:
    return IPSTubeControl::BacklightEffect::PULSE;
  case breath:
    return IPSTubeControl::BacklightEffect::BREATH;
  case test:
  case constant:
  case num_patterns:
    return IPSTubeControl::BacklightEffect::CONSTANT;
  }
  return IPSTubeControl::BacklightEffect::CONSTANT;
}

Backlights::patterns Backlights::effectToPattern(IPSTubeControl::BacklightEffect effect) const
{
  switch (effect)
  {
  case IPSTubeControl::BacklightEffect::OFF:
    return dark;
  case IPSTubeControl::BacklightEffect::RAINBOW:
    return rainbow;
  case IPSTubeControl::BacklightEffect::PULSE:
    return pulse;
  case IPSTubeControl::BacklightEffect::BREATH:
    return breath;
  case IPSTubeControl::BacklightEffect::CONSTANT:
  case IPSTubeControl::BacklightEffect::COUNT:
    return constant;
  }
  return constant;
}

void Backlights::markLegacyChange()
{
  transitioning_ = false;
  persistenceSettings_ = controlledSettings_;
  persistenceRequested_ = true;
}

void Backlights::loadControlSettings(const IPSTubeControl::BacklightSettings &settings)
{
  controlledSettings_ = settings;
  controlledSettings_.color &= 0xFFFFFFU;
  if (controlledSettings_.brightness > 7)
    controlledSettings_.brightness = 7;
  config->pattern = uint8_t(effectToPattern(controlledSettings_.effect));
  config->intensity = controlledSettings_.brightness;
  config->pulse_bpm = controlledSettings_.pulseBpm;
  config->breath_per_min = controlledSettings_.breathBpm;
  config->rainbow_sec = controlledSettings_.rainbowSeconds;
  controlActive_ = true;
  persistenceSettings_ = controlledSettings_;
  persistenceRequested_ = false;
  transitioning_ = false;
  setBrightness(255);
}

void Backlights::applyControlSettings(const IPSTubeControl::BacklightSettings &settings,
                                      uint32_t transitionMs)
{
  for (uint8_t pixel = 0; pixel < NUM_BACKLIGHT_LEDS; ++pixel)
    transitionFrom_[pixel] = lastRendered_[pixel];
  controlledSettings_ = settings;
  controlledSettings_.color &= 0xFFFFFFU;
  controlActive_ = true;
  transitionStartMs_ = millis();
  transitionDurationMs_ = transitionMs;
  transitioning_ = transitionMs > 0;
  setBrightness(255);
}

uint32_t Backlights::scaleColor(uint32_t color, uint8_t scale) const
{
  const uint8_t red = uint8_t((uint16_t(uint8_t(color >> 16U)) * scale + 127U) / 255U);
  const uint8_t green = uint8_t((uint16_t(uint8_t(color >> 8U)) * scale + 127U) / 255U);
  const uint8_t blue = uint8_t((uint16_t(uint8_t(color)) * scale + 127U) / 255U);
  return (uint32_t(red) << 16U) | (uint32_t(green) << 8U) | blue;
}

void Backlights::controlledLoop()
{
  const uint32_t now = millis();
  uint8_t level = controlledSettings_.brightness > 7 ? 7 : controlledSettings_.brightness;
  if (dimming)
    level = BACKLIGHT_DIMMED_INTENSITY > 7 ? 7 : BACKLIGHT_DIMMED_INTENSITY;
  const uint8_t maximum = IPSTubeControl::brightnessToHardware(level);

  uint32_t target[NUM_BACKLIGHT_LEDS] = {};
  if (!off && controlledSettings_.effect != IPSTubeControl::BacklightEffect::OFF)
  {
    if (controlledSettings_.effect == IPSTubeControl::BacklightEffect::RAINBOW)
    {
      const uint32_t duration = uint32_t(controlledSettings_.rainbowSeconds * 1000.0f);
      const uint16_t phase = duration == 0 ? 0 : uint16_t((uint64_t(now % duration) * max_phase) / duration);
      const uint16_t phasePerPixel = (max_phase / NUM_BACKLIGHT_LEDS) / 3;
      for (uint8_t pixel = 0; pixel < NUM_BACKLIGHT_LEDS; ++pixel)
        target[pixel] = scaleColor(phaseToColor((phase + pixel * phasePerPixel) % max_phase), maximum);
    }
    else
    {
      uint8_t effectScale = 255;
      if (controlledSettings_.effect == IPSTubeControl::BacklightEffect::PULSE)
      {
        const float period = 60000.0f / controlledSettings_.pulseBpm;
        effectScale = uint8_t(1.0f + fabs(sin(2.0f * M_PI * now / period)) * 254.0f);
      }
      else if (controlledSettings_.effect == IPSTubeControl::BacklightEffect::BREATH)
      {
        const float period = 60000.0f / controlledSettings_.breathBpm;
        const float value = (exp(sin(2.0f * M_PI * now / period)) - 0.36787944f) * 108.0f;
        effectScale = value < 1.0f ? 1 : uint8_t(value);
      }
      const uint8_t scale = uint8_t((uint16_t(maximum) * effectScale + 127U) / 255U);
      const uint32_t color = scaleColor(controlledSettings_.color, scale);
      for (uint8_t pixel = 0; pixel < NUM_BACKLIGHT_LEDS; ++pixel)
        target[pixel] = color;
    }
  }

  const uint32_t elapsed = now - transitionStartMs_;
  for (uint8_t pixel = 0; pixel < NUM_BACKLIGHT_LEDS; ++pixel)
  {
    const uint32_t rendered = transitioning_
                                  ? IPSTubeControl::lerpColor(transitionFrom_[pixel], target[pixel],
                                                             elapsed, transitionDurationMs_)
                                  : target[pixel];
    lastRendered_[pixel] = rendered;
    setPixelColor(pixel, rendered);
  }
  show();
  if (transitioning_ && elapsed >= transitionDurationMs_)
    transitioning_ = false;
}

#endif
