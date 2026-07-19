#include "IPSTubeDisplayController.h"

#ifdef HARDWARE_IPSTUBE_CLOCK

using namespace IPSTubeControl;

IPSTubeDisplayController ipstubeDisplay;

namespace
{
constexpr uint32_t ANIMATION_FRAME_MS = 83;
}

void IPSTubeDisplayController::begin(TFTs &tfts)
{
  tfts_ = &tfts;
  state_.resetDefaults();
  for (uint8_t screen = 0; screen < SCREEN_COUNT; ++screen)
    animations_[screen] = AnimationPreset::OFF;
}

void IPSTubeDisplayController::loop(uint32_t now)
{
  if (tfts_ == nullptr)
    return;
  for (uint8_t offset = 0; offset < SCREEN_COUNT; ++offset)
  {
    const uint8_t screen = uint8_t((animationCursor_ + offset) % SCREEN_COUNT);
    if (!isAnimating(screen) || int32_t(now - nextFrameAt_[screen]) < 0)
      continue;

    if (animations_[screen] == AnimationPreset::MATRIX)
      tfts_->drawGeneratedFrame(screen, renderMatrixAnimation, &matrixStates_[screen]);
    else if (animations_[screen] == AnimationPreset::RINGS)
      tfts_->drawGeneratedFrame(screen, renderRingsAnimation, &geometricStates_[screen]);
    else if (animations_[screen] == AnimationPreset::SQUARES)
      tfts_->drawGeneratedFrame(screen, renderSquaresAnimation, &geometricStates_[screen]);
    else if (animations_[screen] == AnimationPreset::SWIRL)
      tfts_->drawGeneratedFrame(screen, renderSwirlAnimation, &geometricStates_[screen]);
    nextFrameAt_[screen] = now + ANIMATION_FRAME_MS;
    animationCursor_ = uint8_t((screen + 1U) % SCREEN_COUNT);
    break;
  }
}

bool IPSTubeDisplayController::setAnimation(uint8_t screen, AnimationPreset preset,
                                            bool restoreWhenStopped)
{
  if (screen >= SCREEN_COUNT || uint8_t(preset) >= uint8_t(AnimationPreset::COUNT))
    return false;

  const bool wasAnimating = isAnimating(screen);
  animations_[screen] = preset;
  if (preset == AnimationPreset::MATRIX)
  {
    const uint32_t now = millis();
    resetMatrixAnimation(matrixStates_[screen],
                         0x4D415452U ^ (uint32_t(screen + 1U) * 0x9E3779B9U) ^ now,
                         TFT_WIDTH, TFT_HEIGHT);
    nextFrameAt_[screen] = now;
  }
  else if (preset == AnimationPreset::RINGS || preset == AnimationPreset::SQUARES ||
           preset == AnimationPreset::SWIRL)
  {
    const uint32_t now = millis();
    resetGeometricAnimation(geometricStates_[screen]);
    nextFrameAt_[screen] = now;
  }
  else if (wasAnimating && restoreWhenStopped)
  {
    const ClockRole role = state_.role(screen);
    if (role == ClockRole::MANUAL || !haveClockDigits_)
      showImage(screen, state_.currentImage(screen));
    else
      showImage(screen, imageForClockRole(role, lastClockDigits_));
  }
  return true;
}

void IPSTubeDisplayController::clearAnimation(uint8_t screen)
{
  if (screen < SCREEN_COUNT)
    animations_[screen] = AnimationPreset::OFF;
}

AnimationPreset IPSTubeDisplayController::animation(uint8_t screen) const
{
  return screen < SCREEN_COUNT ? animations_[screen] : AnimationPreset::OFF;
}

bool IPSTubeDisplayController::isAnimating(uint8_t screen) const
{
  return animation(screen) != AnimationPreset::OFF;
}

void IPSTubeDisplayController::loadPersistentAnimations(
    const uint8_t animations[SCREEN_COUNT])
{
  for (uint8_t screen = 0; screen < SCREEN_COUNT; ++screen)
  {
    const AnimationPreset preset = AnimationPreset(animations[screen]);
    setAnimation(screen,
                 uint8_t(preset) < uint8_t(AnimationPreset::COUNT) ? preset : AnimationPreset::OFF,
                 false);
  }
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
  lastClockDigits_ = digits;
  haveClockDigits_ = true;
  for (uint8_t screen = 0; screen < SCREEN_COUNT; ++screen)
  {
    if (isAnimating(screen))
      continue;
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
    if (!isAnimating(screen) && state_.currentImage(screen) == image)
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
