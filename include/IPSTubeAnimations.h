#ifndef IPSTUBE_ANIMATIONS_H
#define IPSTUBE_ANIMATIONS_H

#include <stdint.h>

namespace IPSTubeControl
{
constexpr uint8_t MATRIX_MAX_COLUMNS = 17;

struct MatrixAnimationState
{
  uint32_t seed;
  uint32_t frame;
  int16_t heads[MATRIX_MAX_COLUMNS];
  uint8_t lengths[MATRIX_MAX_COLUMNS];
  uint8_t rates[MATRIX_MAX_COLUMNS];
  uint8_t columns;
  uint8_t rows;
};

struct GeometricAnimationState
{
  uint32_t frame;
};

void resetMatrixAnimation(MatrixAnimationState &state, uint32_t seed,
                          uint16_t width, uint16_t height);
void renderMatrixAnimation(uint16_t *pixels, uint16_t width,
                           uint16_t height, void *context);
void resetGeometricAnimation(GeometricAnimationState &state);
void renderRingsAnimation(uint16_t *pixels, uint16_t width,
                          uint16_t height, void *context);
void renderSquaresAnimation(uint16_t *pixels, uint16_t width,
                            uint16_t height, void *context);
void renderSwirlAnimation(uint16_t *pixels, uint16_t width,
                          uint16_t height, void *context);
}

#endif
