#include "IPSTubeDisplayController.h"

#ifdef HARDWARE_IPSTUBE_CLOCK

using namespace IPSTubeControl;

IPSTubeDisplayController ipstubeDisplay;

void IPSTubeDisplayController::begin(TFTs &tfts)
{
  tfts_ = &tfts;
  state_.resetDefaults();
}

bool IPSTubeDisplayController::showImage(uint8_t screen, uint8_t image)
{
  if (tfts_ == nullptr || screen >= SCREEN_COUNT)
    return false;
  if (image != BLANK_IMAGE && !tfts_->imageExists(image))
    return false;
  if (!tfts_->drawImageById(screen, image))
    return false;
  state_.setCurrentImage(screen, image);
  return true;
}

LayoutError IPSTubeDisplayController::replaceClockLayout(
    const LayoutEntry *entries, size_t count, const ClockDigits &digits)
{
  const LayoutError result = state_.replaceClockLayout(entries, count);
  if (result != LayoutError::OK)
    return result;

  updateClock(digits, true);
  return LayoutError::OK;
}

void IPSTubeDisplayController::updateClock(const ClockDigits &digits, bool force)
{
  for (uint8_t screen = 0; screen < SCREEN_COUNT; ++screen)
  {
    const ClockRole role = state_.role(screen);
    if (role == ClockRole::MANUAL)
      continue;
    const uint8_t image = imageForClockRole(role, digits);
    if (force || state_.currentImage(screen) != image)
      showImage(screen, image);
  }
}

void IPSTubeDisplayController::restoreManualImages()
{
  for (uint8_t screen = 0; screen < SCREEN_COUNT; ++screen)
  {
    if (state_.role(screen) == ClockRole::MANUAL &&
        !showImage(screen, state_.savedImage(screen)))
      showImage(screen, BLANK_IMAGE);
  }
}

void IPSTubeDisplayController::redrawImage(uint8_t image)
{
  for (uint8_t screen = 0; screen < SCREEN_COUNT; ++screen)
  {
    if (state_.currentImage(screen) == image)
      showImage(screen, image);
  }
}

void IPSTubeDisplayController::loadPersistent(
    const uint8_t roles[SCREEN_COUNT], const uint8_t savedImages[SCREEN_COUNT])
{
  LayoutEntry entries[SCREEN_COUNT];
  for (uint8_t screen = 0; screen < SCREEN_COUNT; ++screen)
  {
    entries[screen] = {screen, ClockRole(roles[screen])};
    state_.setSavedImage(screen, savedImages[screen]);
  }
  if (state_.replaceClockLayout(entries, SCREEN_COUNT) != LayoutError::OK)
    state_.resetDefaults();
}

#endif
