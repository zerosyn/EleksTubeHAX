#include "IPSTubeAnimations.h"

#include <math.h>
#include <stddef.h>
#include <string.h>

namespace IPSTubeControl
{
namespace
{
constexpr uint8_t CELL_WIDTH = 8;
constexpr uint8_t CELL_HEIGHT = 12;
constexpr float PI = 3.14159265358979323846f;
constexpr uint16_t GEOMETRIC_BACKGROUND = 0x0000U;
constexpr uint8_t SWIRL_PHASE_STEPS = 240;
constexpr uint8_t SWIRL_QUARTER_PHASE = SWIRL_PHASE_STEPS / 4U;
constexpr uint8_t SWIRL_HALF_PHASE = SWIRL_PHASE_STEPS / 2U;
constexpr uint8_t SWIRL_MAX_RADIUS = 160;

uint8_t swirlAngleLut[256];
uint8_t swirlRadialLut[SWIRL_MAX_RADIUS + 1U];
uint16_t swirlLutHeight = 0;
uint8_t swirlCoreRadius = 0;

constexpr uint16_t rgb565(uint8_t red, uint8_t green, uint8_t blue)
{
  return uint16_t((uint16_t(red & 0xF8U) << 8U) |
                  (uint16_t(green & 0xFCU) << 3U) | (blue >> 3U));
}

// Compact 3x5 hexadecimal glyphs, most-significant bit first.
constexpr uint16_t GLYPHS[16] = {
    0x7B6F, 0x2492, 0x73E7, 0x73CF,
    0x5BC9, 0x79CF, 0x79EF, 0x7249,
    0x7BEF, 0x7BCF, 0x7BED, 0x6BAE,
    0x7927, 0x6B6E, 0x79E7, 0x79E4};

uint32_t mix(uint32_t value)
{
  value ^= value >> 16U;
  value *= 0x7FEB352DU;
  value ^= value >> 15U;
  value *= 0x846CA68BU;
  return value ^ (value >> 16U);
}

uint32_t nextRandom(uint32_t &seed)
{
  seed = mix(seed + 0x9E3779B9U);
  return seed;
}

void resetColumn(MatrixAnimationState &state, uint8_t column, bool initial)
{
  const uint8_t rows = state.rows == 0 ? 1 : state.rows;
  state.lengths[column] = uint8_t(6U + nextRandom(state.seed) % 9U);
  state.rates[column] = uint8_t(1U + nextRandom(state.seed) % 3U);
  if (initial)
    state.heads[column] = int16_t(nextRandom(state.seed) % (rows + 8U)) - 4;
  else
    state.heads[column] = -int16_t(nextRandom(state.seed) % (rows / 2U + 4U));
}

void drawGlyph(uint16_t *pixels, uint16_t width, uint16_t height,
               uint16_t x, uint16_t y, uint8_t glyph, uint16_t color)
{
  const uint16_t bits = GLYPHS[glyph & 0x0FU];
  for (uint8_t row = 0; row < 5; ++row)
  {
    for (uint8_t column = 0; column < 3; ++column)
    {
      const uint8_t bit = uint8_t(14U - (row * 3U + column));
      if ((bits & (1U << bit)) == 0)
        continue;
      const uint16_t px = uint16_t(x + column * 2U);
      const uint16_t py = uint16_t(y + row * 2U);
      for (uint8_t dy = 0; dy < 2; ++dy)
      {
        if (py + dy >= height)
          continue;
        for (uint8_t dx = 0; dx < 2; ++dx)
        {
          if (px + dx < width)
            pixels[size_t(py + dy) * width + px + dx] = color;
        }
      }
    }
  }
}

void putPixel(uint16_t *pixels, uint16_t width, uint16_t height,
              int16_t x, int16_t y, uint16_t color)
{
  if (x >= 0 && y >= 0 && x < int16_t(width) && y < int16_t(height))
    pixels[size_t(y) * width + uint16_t(x)] = color;
}

void drawDisc(uint16_t *pixels, uint16_t width, uint16_t height,
              int16_t centerX, int16_t centerY, uint8_t radius, uint16_t color)
{
  const int16_t squaredRadius = int16_t(radius) * radius;
  for (int16_t y = -int16_t(radius); y <= int16_t(radius); ++y)
  {
    for (int16_t x = -int16_t(radius); x <= int16_t(radius); ++x)
    {
      if (x * x + y * y <= squaredRadius)
        putPixel(pixels, width, height, centerX + x, centerY + y, color);
    }
  }
}

void drawLine(uint16_t *pixels, uint16_t width, uint16_t height,
              int16_t x0, int16_t y0, int16_t x1, int16_t y1,
              uint16_t color, uint8_t thickness)
{
  const int16_t dx = int16_t(abs(x1 - x0));
  const int16_t sx = x0 < x1 ? 1 : -1;
  const int16_t dy = -int16_t(abs(y1 - y0));
  const int16_t sy = y0 < y1 ? 1 : -1;
  int16_t error = dx + dy;
  const uint8_t radius = thickness > 1 ? uint8_t(thickness / 2U) : 0;

  for (;;)
  {
    if (radius == 0)
      putPixel(pixels, width, height, x0, y0, color);
    else
      drawDisc(pixels, width, height, x0, y0, radius, color);
    if (x0 == x1 && y0 == y1)
      break;
    const int16_t doubled = int16_t(2 * error);
    if (doubled >= dy)
    {
      error += dy;
      x0 += sx;
    }
    if (doubled <= dx)
    {
      error += dx;
      y0 += sy;
    }
  }
}

void drawArc(uint16_t *pixels, uint16_t width, uint16_t height,
             int16_t centerX, int16_t centerY, uint8_t radius,
             float startDegrees, float sweepDegrees,
             uint16_t color, uint8_t thickness)
{
  const uint16_t steps = uint16_t(fabsf(sweepDegrees) / 4.0f) + 1U;
  const float start = startDegrees * PI / 180.0f;
  const float increment = (sweepDegrees / steps) * PI / 180.0f;
  const float stepCos = cosf(increment);
  const float stepSin = sinf(increment);
  float x = cosf(start) * radius;
  float y = sinf(start) * radius;

  for (uint16_t step = 0; step < steps; ++step)
  {
    const float nextX = x * stepCos - y * stepSin;
    const float nextY = x * stepSin + y * stepCos;
    drawLine(pixels, width, height,
             int16_t(lroundf(centerX + x)), int16_t(lroundf(centerY + y)),
             int16_t(lroundf(centerX + nextX)), int16_t(lroundf(centerY + nextY)),
             color, thickness);
    x = nextX;
    y = nextY;
  }
}

void drawRotatedSquare(uint16_t *pixels, uint16_t width, uint16_t height,
                       int16_t centerX, int16_t centerY, float side,
                       float angleDegrees, uint16_t color, uint8_t thickness)
{
  const float angle = angleDegrees * PI / 180.0f;
  const float cosine = cosf(angle);
  const float sine = sinf(angle);
  const float half = side * 0.5f;
  int16_t x[4];
  int16_t y[4];
  constexpr int8_t CORNERS[4][2] = {{-1, -1}, {1, -1}, {1, 1}, {-1, 1}};
  for (uint8_t corner = 0; corner < 4; ++corner)
  {
    const float localX = CORNERS[corner][0] * half;
    const float localY = CORNERS[corner][1] * half;
    x[corner] = int16_t(lroundf(centerX + localX * cosine - localY * sine));
    y[corner] = int16_t(lroundf(centerY + localX * sine + localY * cosine));
  }
  for (uint8_t corner = 0; corner < 4; ++corner)
  {
    const uint8_t next = uint8_t((corner + 1U) % 4U);
    drawLine(pixels, width, height, x[corner], y[corner], x[next], y[next],
             color, thickness);
  }
}

uint8_t phaseUnits(float radians)
{
  radians = fmodf(radians, 2.0f * PI);
  if (radians < 0.0f)
    radians += 2.0f * PI;
  const uint16_t quantized = uint16_t(radians * SWIRL_PHASE_STEPS / (2.0f * PI));
  return uint8_t(quantized < SWIRL_PHASE_STEPS ? quantized : 0);
}

void prepareSwirlLookups(uint16_t height)
{
  if (height == swirlLutHeight)
    return;

  for (uint16_t ratio = 0; ratio < 256; ++ratio)
    swirlAngleLut[ratio] = phaseUnits(atanf(float(ratio) / 255.0f));

  swirlCoreRadius = uint8_t((uint32_t(height) * 24U + 200U) / 400U);
  if (swirlCoreRadius == 0)
    swirlCoreRadius = 1;
  // The source boundaries closely follow theta = C + K/r. Scaling the
  // 400x400 source to the display height scales K by the same factor.
  const float reciprocalTwist = 254.36f * height / 400.0f;
  for (uint16_t radius = 0; radius <= SWIRL_MAX_RADIUS; ++radius)
  {
    const float safeRadius = radius > swirlCoreRadius ? float(radius) : float(swirlCoreRadius);
    swirlRadialLut[radius] = phaseUnits(-reciprocalTwist / safeRadius);
  }
  swirlLutHeight = height;
}

uint8_t approximateSwirlPhase(int16_t dx, int16_t dy, uint8_t radius)
{
  const uint16_t absX = uint16_t(dx < 0 ? -dx : dx);
  const uint16_t absY = uint16_t(dy < 0 ? -dy : dy);
  const uint16_t larger = absX > absY ? absX : absY;
  const uint16_t smaller = absX > absY ? absY : absX;
  const uint8_t ratio = larger == 0 ? 0 : uint8_t((smaller * 255U) / larger);
  uint8_t angle = swirlAngleLut[ratio];
  if (absY > absX)
    angle = uint8_t(SWIRL_QUARTER_PHASE - angle);
  if (dx < 0)
    angle = dy < 0 ? uint8_t(SWIRL_HALF_PHASE + angle)
                   : uint8_t(SWIRL_HALF_PHASE - angle);
  else if (dy < 0)
    angle = uint8_t((SWIRL_PHASE_STEPS - angle) % SWIRL_PHASE_STEPS);

  // 52.5 degrees align the fitted frame-zero boundary with the palette.
  constexpr uint8_t INITIAL_PHASE = 35;
  uint16_t phase = uint16_t(angle) + swirlRadialLut[radius] + INITIAL_PHASE;
  while (phase >= SWIRL_PHASE_STEPS)
    phase -= SWIRL_PHASE_STEPS;
  return uint8_t(phase);
}
}

void resetMatrixAnimation(MatrixAnimationState &state, uint32_t seed,
                          uint16_t width, uint16_t height)
{
  memset(&state, 0, sizeof(state));
  state.seed = seed == 0 ? 0x4D415452U : seed;
  const uint16_t columns = width / CELL_WIDTH;
  state.columns = uint8_t(columns > MATRIX_MAX_COLUMNS ? MATRIX_MAX_COLUMNS : columns);
  const uint16_t rows = height / CELL_HEIGHT;
  state.rows = uint8_t(rows > 255 ? 255 : rows);
  for (uint8_t column = 0; column < state.columns; ++column)
    resetColumn(state, column, true);
}

void renderMatrixAnimation(uint16_t *pixels, uint16_t width,
                           uint16_t height, void *context)
{
  if (pixels == nullptr || context == nullptr || width == 0 || height == 0)
    return;

  MatrixAnimationState &state = *static_cast<MatrixAnimationState *>(context);
  memset(pixels, 0, size_t(width) * height * sizeof(uint16_t));
  for (uint8_t column = 0; column < state.columns; ++column)
  {
    if (state.frame % state.rates[column] == 0)
      ++state.heads[column];
    if (state.heads[column] - state.lengths[column] > state.rows)
      resetColumn(state, column, false);

    for (uint8_t trail = 0; trail < state.lengths[column]; ++trail)
    {
      const int16_t row = state.heads[column] - trail;
      if (row < 0 || row >= state.rows)
        continue;

      uint16_t color;
      if (trail == 0)
        color = 0xE7FFU;
      else
      {
        const uint8_t green = uint8_t(63U / (1U + trail / 2U));
        color = uint16_t(green) << 5U;
      }
      const uint32_t glyphHash = mix(state.seed ^ (uint32_t(column) << 24U) ^
                                     (uint32_t(uint16_t(row)) << 8U) ^ (state.frame / 2U));
      drawGlyph(pixels, width, height, uint16_t(column * CELL_WIDTH + 1U),
                uint16_t(row * CELL_HEIGHT + 1U), uint8_t(glyphHash), color);
    }
  }
  ++state.frame;
}

void resetGeometricAnimation(GeometricAnimationState &state)
{
  state.frame = 0;
}

void renderRingsAnimation(uint16_t *pixels, uint16_t width,
                          uint16_t height, void *context)
{
  if (pixels == nullptr || context == nullptr || width == 0 || height == 0)
    return;

  GeometricAnimationState &state = *static_cast<GeometricAnimationState *>(context);
  const uint16_t shorterSide = width < height ? width : height;
  const int16_t centerX = int16_t(width / 2U);
  const int16_t centerY = int16_t(height / 2U);
  constexpr uint8_t CYCLE_FRAMES = 33;
  const float progress = float(state.frame % CYCLE_FRAMES) / CYCLE_FRAMES;
  const float eased = 0.5f - 0.5f * cosf(progress * PI);
  const float sharedSwing = 45.0f * sinf(progress * 2.0f * PI);
  constexpr uint16_t COLORS[8] = {
      0x13B7U, 0x0513U, 0x8628U, 0xF5A5U,
      0xEAC6U, 0xE90BU, 0xC110U, 0x6171U};
  constexpr uint8_t RADIUS_PERCENT[8] = {6, 9, 12, 16, 20, 24, 27, 30};
  constexpr int8_t TURNS[8] = {1, 0, -1, -2, -3, -4, -5, -6};

  for (size_t pixel = 0; pixel < size_t(width) * height; ++pixel)
    pixels[pixel] = GEOMETRIC_BACKGROUND;

  for (uint8_t ring = 0; ring < 8; ++ring)
  {
    const uint8_t radius = uint8_t((uint32_t(shorterSide) * RADIUS_PERCENT[ring]) / 100U);
    const float angle = ring * 51.0f + TURNS[ring] * 360.0f * eased + sharedSwing;
    drawArc(pixels, width, height, centerX, centerY, radius,
            angle, 176.0f, COLORS[ring], 2);
  }
  ++state.frame;
}

void renderSquaresAnimation(uint16_t *pixels, uint16_t width,
                            uint16_t height, void *context)
{
  if (pixels == nullptr || context == nullptr || width == 0 || height == 0)
    return;

  GeometricAnimationState &state = *static_cast<GeometricAnimationState *>(context);
  const uint16_t shorterSide = width < height ? width : height;
  const int16_t centerX = int16_t(width / 2U);
  const int16_t centerY = int16_t(height / 2U);
  constexpr uint8_t CYCLE_FRAMES = 29;
  const float progress = float(state.frame % CYCLE_FRAMES) / CYCLE_FRAMES;
  constexpr uint16_t COLORS[8] = {
      0x0513U, 0x13B7U, 0x6171U, 0xC110U,
      0xE90BU, 0xEAC6U, 0xF5A5U, 0x8628U};

  for (size_t pixel = 0; pixel < size_t(width) * height; ++pixel)
    pixels[pixel] = GEOMETRIC_BACKGROUND;

  for (uint8_t square = 0; square < 8; ++square)
  {
    float localProgress = progress + float(square) / 8.0f;
    if (localProgress >= 1.0f)
      localProgress -= 1.0f;
    const float pulse = 0.5f - 0.5f * cosf(localProgress * 2.0f * PI);
    const float side = shorterSide * (0.085f + 0.37f * pulse);
    const float angle = square * 11.25f;
    drawRotatedSquare(pixels, width, height, centerX, centerY, side,
                      angle, COLORS[square], 2);
  }
  ++state.frame;
}

void renderSwirlAnimation(uint16_t *pixels, uint16_t width,
                          uint16_t height, void *context)
{
  if (pixels == nullptr || context == nullptr || width == 0 || height == 0)
    return;

  GeometricAnimationState &state = *static_cast<GeometricAnimationState *>(context);
  prepareSwirlLookups(height);
  constexpr uint8_t CYCLE_FRAMES = 22;
  constexpr uint16_t COLORS[8] = {
      rgb565(129, 197, 64), rgb565(0, 163, 150),
      rgb565(22, 116, 188), rgb565(97, 46, 141),
      rgb565(194, 34, 134), rgb565(234, 34, 94),
      rgb565(237, 91, 53), rgb565(245, 181, 46)};
  constexpr uint16_t CORE_COLOR = rgb565(38, 38, 38);
  const uint16_t offset = uint16_t((state.frame % CYCLE_FRAMES) *
                                   SWIRL_PHASE_STEPS / CYCLE_FRAMES);
  const int16_t centerX = int16_t(width / 2U);
  const int16_t centerY = int16_t(height / 2U);
  for (uint16_t y = 0; y < height; ++y)
  {
    for (uint16_t x = 0; x < width; ++x)
    {
      const int16_t dx = int16_t(x) - centerX;
      const int16_t dy = int16_t(y) - centerY;
      const uint16_t absX = uint16_t(dx < 0 ? -dx : dx);
      const uint16_t absY = uint16_t(dy < 0 ? -dy : dy);
      const uint16_t larger = absX > absY ? absX : absY;
      const uint16_t smaller = absX > absY ? absY : absX;
      // Low-error integer hypot approximation; especially important near the
      // core where the reciprocal-radius spiral changes phase quickly.
      uint16_t approximateRadius = uint16_t((1007UL * larger +
                                             441UL * smaller + 512UL) >> 10U);
      if (approximateRadius <= swirlCoreRadius)
      {
        pixels[size_t(y) * width + x] = CORE_COLOR;
        continue;
      }
      if (approximateRadius > SWIRL_MAX_RADIUS)
        approximateRadius = SWIRL_MAX_RADIUS;
      uint16_t phase = uint16_t(approximateSwirlPhase(dx, dy, uint8_t(approximateRadius))) +
                       SWIRL_PHASE_STEPS - offset;
      if (phase >= SWIRL_PHASE_STEPS)
        phase -= SWIRL_PHASE_STEPS;
      pixels[size_t(y) * width + x] = COLORS[phase / (SWIRL_PHASE_STEPS / 8U)];
    }
  }
  ++state.frame;
}
}
