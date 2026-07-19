#ifndef IPSTUBE_DISPLAY_CONTROLLER_H
#define IPSTUBE_DISPLAY_CONTROLLER_H

#include "GLOBAL_DEFINES.h"

#ifdef HARDWARE_IPSTUBE_CLOCK

#include "IPSTubeAnimations.h"
#include "IPSTubeControlTypes.h"
#include "TFTs.h"

class IPSTubeDisplayController
{
public:
  void begin(TFTs &tfts);
  void loop(uint32_t now);
  bool showImage(uint8_t screen, uint8_t image);
  bool setAnimation(uint8_t screen, IPSTubeControl::AnimationPreset preset,
                    bool restoreWhenStopped = true);
  void clearAnimation(uint8_t screen);
  IPSTubeControl::AnimationPreset animation(uint8_t screen) const;
  bool isAnimating(uint8_t screen) const;
  void loadPersistentAnimations(
      const uint8_t animations[IPSTubeControl::SCREEN_COUNT]);
  IPSTubeControl::LayoutError replaceClockLayout(
      const IPSTubeControl::LayoutEntry *entries, size_t count,
      const IPSTubeControl::ClockDigits &digits);
  void updateClock(const IPSTubeControl::ClockDigits &digits, bool force);
  void restoreManualImages();
  void redrawImage(uint8_t image);
  void loadPersistent(const uint8_t roles[IPSTubeControl::SCREEN_COUNT],
                      const uint8_t savedImages[IPSTubeControl::SCREEN_COUNT]);

  IPSTubeControl::DisplayState &state() { return state_; }
  const IPSTubeControl::DisplayState &state() const { return state_; }

private:
  TFTs *tfts_ = nullptr;
  IPSTubeControl::DisplayState state_;
  IPSTubeControl::AnimationPreset animations_[IPSTubeControl::SCREEN_COUNT] = {};
  IPSTubeControl::MatrixAnimationState matrixStates_[IPSTubeControl::SCREEN_COUNT] = {};
  IPSTubeControl::GeometricAnimationState geometricStates_[IPSTubeControl::SCREEN_COUNT] = {};
  uint32_t nextFrameAt_[IPSTubeControl::SCREEN_COUNT] = {};
  uint8_t animationCursor_ = 0;
  IPSTubeControl::ClockDigits lastClockDigits_ = {};
  bool haveClockDigits_ = false;
};

extern IPSTubeDisplayController ipstubeDisplay;

#endif
#endif
