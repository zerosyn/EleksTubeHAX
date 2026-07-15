#ifndef IPSTUBE_DISPLAY_CONTROLLER_H
#define IPSTUBE_DISPLAY_CONTROLLER_H

#include "GLOBAL_DEFINES.h"

#ifdef HARDWARE_IPSTUBE_CLOCK

#include "IPSTubeControlTypes.h"
#include "TFTs.h"

class IPSTubeDisplayController
{
public:
  void begin(TFTs &tfts);
  bool showImage(uint8_t screen, uint8_t image);
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
};

extern IPSTubeDisplayController ipstubeDisplay;

#endif
#endif
