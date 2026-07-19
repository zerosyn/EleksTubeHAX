#ifndef IPSTUBE_HTTP_SERVER_H
#define IPSTUBE_HTTP_SERVER_H

#include "GLOBAL_DEFINES.h"

#ifdef HARDWARE_IPSTUBE_CLOCK

#include <FS.h>
#include <WebServer.h>

class IPSTubeHttpServer
{
public:
  void begin();
  void loop() { server_.handleClient(); }

private:
  enum class UploadResult : uint8_t
  {
    NO_FILE,
    IN_PROGRESS,
    SUCCESS,
    INVALID_ID,
    INVALID_FIELD,
    TOO_LARGE,
    NO_SPACE,
    INVALID_IMAGE,
    FILESYSTEM_ERROR
  };

  void handleRoot();
  void handleConfig();
  void handleImages();
  void handleDisplay();
  void handleAnimation();
  void handleClockLayout();
  void handleBacklight();
  void handleUploadData();
  void handleUploadComplete();
  void handleNotFound();
  void recoverUploads();

  void sendError(int status, const char *code, const char *message,
                 const char *field = nullptr);
  bool parseUploadImageId(uint8_t &image);
  bool replaceUploadedImage(uint8_t image);

  WebServer server_{80};
  fs::File uploadFile_;
  UploadResult uploadResult_ = UploadResult::NO_FILE;
  uint8_t uploadImage_ = 0;
  size_t uploadSize_ = 0;
  char uploadTempPath_[24] = {};
};

extern IPSTubeHttpServer ipstubeHttpServer;

#endif
#endif
