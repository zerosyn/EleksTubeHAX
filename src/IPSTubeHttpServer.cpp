#include "IPSTubeHttpServer.h"

#ifdef HARDWARE_IPSTUBE_CLOCK

#include "Backlights.h"
#include "Clock.h"
#include "IPSTubeControlTypes.h"
#include "IPSTubeDisplayController.h"
#include "IPSTubeExtensionConfig.h"
#include "TFTs.h"

#include <ArduinoJson.h>
#include <LittleFS.h>
#include <uri/UriBraces.h>

#include <stdlib.h>

using namespace IPSTubeControl;

extern char UniqueDeviceName[32];

namespace
{
constexpr size_t MAX_IMAGE_BYTES = 102400;

const char MANAGEMENT_PAGE[] PROGMEM = R"HTML(<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>IPSTube 控制台</title><style>
body{font:15px system-ui;margin:auto;max-width:900px;padding:18px;background:#111;color:#eee}fieldset{margin:14px 0;border:1px solid #555}label{display:inline-block;margin:5px}input,select,button,textarea{font:inherit;margin:3px;padding:6px}textarea{width:95%;height:95px}pre{white-space:pre-wrap;background:#222;padding:10px}.ok{color:#8f8}.err{color:#f88}
</style></head><body><h1>IPSTube 控制台</h1><p id="msg"></p>
<fieldset><legend>屏幕</legend><label>screen <select id="screen"></select></label><label>image <select id="image"></select></label><label><input id="displaySave" type="checkbox">保存</label><button onclick="displayImage()">显示</button></fieldset>
<fieldset><legend>时钟布局（整体替换）</legend><textarea id="layout">[{"screen":0,"clock":"H1"},{"screen":1,"clock":"H2"},{"screen":2,"clock":"COLON"},{"screen":3,"clock":"M1"},{"screen":4,"clock":"M2"}]</textarea><br><button onclick="saveLayout()">保存布局</button></fieldset>
<fieldset><legend>上传 BMP</legend><label>ID <input id="uploadId" type="number" min="0" max="254" value="252"></label><input id="file" type="file" accept=".bmp,image/bmp"><button onclick="uploadImage()">上传并替换</button></fieldset>
<fieldset><legend>氛围灯</legend><label>效果 <select id="effect"><option>off</option><option>constant</option><option>rainbow</option><option>pulse</option><option>breath</option></select></label><label>颜色 <input id="color" type="color" value="#ff8000"></label><label>亮度 <input id="brightness" type="number" min="0" max="7" value="5"></label><label>Pulse BPM <input id="pulse" type="number" min="20" max="120" value="60"></label><label>Breath BPM <input id="breath" type="number" min="5" max="60" value="20"></label><label>Rainbow 秒 <input id="rainbow" type="number" min="0.2" max="10" step="0.1" value="8"></label><label>渐变 ms <input id="transition" type="number" min="0" max="60000" value="800"></label><label><input id="lightSave" type="checkbox">保存</label><button onclick="setLight()">应用</button></fieldset>
<fieldset><legend>当前配置</legend><button onclick="loadAll()">刷新</button><pre id="config"></pre></fieldset>
<script>
const $=id=>document.getElementById(id);for(let i=0;i<6;i++)$('screen').add(new Option(i,i));
function message(text,ok=true){$('msg').textContent=text;$('msg').className=ok?'ok':'err'}
async function jsonRequest(url,method,body){const r=await fetch(url,{method,headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});const j=await r.json();if(!r.ok)throw Error(j.error?.message||r.statusText);return j}
async function loadAll(){try{const [c,i]=await Promise.all([fetch('/api/config').then(r=>r.json()),fetch('/api/images').then(r=>r.json())]);$('config').textContent=JSON.stringify(c,null,2);$('layout').value=JSON.stringify(c.clock_layout,null,2);$('image').innerHTML='';for(const x of i.images)$('image').add(new Option(`${x.id} ${x.name} ${x.exists?'':'(missing)'}`,x.id));const b=c.backlight;$('effect').value=b.effect;$('color').value=b.color;$('brightness').value=b.brightness;$('pulse').value=b.pulse_bpm;$('breath').value=b.breath_bpm;$('rainbow').value=b.rainbow_sec;message('已刷新')}catch(e){message(e.message,false)}}
async function displayImage(){try{await jsonRequest('/api/display','POST',{screen:+$('screen').value,image:+$('image').value,save:$('displaySave').checked});message('屏幕已更新');loadAll()}catch(e){message(e.message,false)}}
async function saveLayout(){try{await jsonRequest('/api/clock-layout','PUT',JSON.parse($('layout').value));message('布局已保存');loadAll()}catch(e){message(e.message,false)}}
async function uploadImage(){try{const f=$('file').files[0];if(!f)throw Error('请选择 BMP');const form=new FormData();form.append('file',f);const r=await fetch('/api/images/'+$('uploadId').value,{method:'POST',body:form});const j=await r.json();if(!r.ok)throw Error(j.error?.message||r.statusText);message('图片已替换');loadAll()}catch(e){message(e.message,false)}}
async function setLight(){try{await jsonRequest('/api/backlight','POST',{effect:$('effect').value,color:$('color').value.toUpperCase(),brightness:+$('brightness').value,pulse_bpm:+$('pulse').value,breath_bpm:+$('breath').value,rainbow_sec:+$('rainbow').value,transition_ms:+$('transition').value,save:$('lightSave').checked});message('灯光已更新');loadAll()}catch(e){message(e.message,false)}}
loadAll();</script></body></html>)HTML";

ClockDigits currentClockDigits()
{
  const uint8_t hoursTens = uclock.getHoursTens();
  return {
      uint8_t(hoursTens == TFTs::blanked ? 0 : hoursTens),
      uclock.getHoursOnes(),
      uclock.getMinutesTens(),
      uclock.getMinutesOnes(),
      uclock.getSecondsTens(),
      uclock.getSecondsOnes(),
      hoursTens == TFTs::blanked};
}

bool objectHasOnly(JsonObjectConst object, const char *const *allowed, size_t allowedCount)
{
  for (JsonPairConst pair : object)
  {
    bool found = false;
    for (size_t index = 0; index < allowedCount; ++index)
    {
      if (strcmp(pair.key().c_str(), allowed[index]) == 0)
      {
        found = true;
        break;
      }
    }
    if (!found)
      return false;
  }
  return true;
}

bool objectHasKey(JsonObjectConst object, const char *key)
{
  for (JsonPairConst pair : object)
  {
    if (strcmp(pair.key().c_str(), key) == 0)
      return true;
  }
  return false;
}

bool parseRgb(const char *text, uint32_t &color)
{
  if (text == nullptr || strlen(text) != 7 || text[0] != '#')
    return false;
  for (uint8_t index = 1; index < 7; ++index)
  {
    const char c = text[index];
    if (!((c >= '0' && c <= '9') || (c >= 'a' && c <= 'f') || (c >= 'A' && c <= 'F')))
      return false;
  }
  color = strtoul(text + 1, nullptr, 16) & 0xFFFFFFU;
  return true;
}

String colorString(uint32_t color)
{
  char buffer[8];
  snprintf(buffer, sizeof(buffer), "#%06lX", static_cast<unsigned long>(color & 0xFFFFFFU));
  return String(buffer);
}
}

IPSTubeHttpServer ipstubeHttpServer;

void IPSTubeHttpServer::begin()
{
  recoverUploads();
  server_.on("/", HTTP_GET, [this]() { handleRoot(); });
  server_.on("/api/config", HTTP_GET, [this]() { handleConfig(); });
  server_.on("/api/images", HTTP_GET, [this]() { handleImages(); });
  server_.on("/api/display", HTTP_POST, [this]() { handleDisplay(); });
  server_.on("/api/clock-layout", HTTP_PUT, [this]() { handleClockLayout(); });
  server_.on("/api/backlight", HTTP_POST, [this]() { handleBacklight(); });
  server_.on(UriBraces("/api/images/{}"), HTTP_POST,
             [this]() { handleUploadComplete(); },
             [this]() { handleUploadData(); });
  server_.onNotFound([this]() { handleNotFound(); });
  server_.begin();
  Serial.println("IPSTube HTTP server started on port 80.");
}

void IPSTubeHttpServer::handleRoot()
{
  server_.send_P(200, PSTR("text/html; charset=utf-8"), MANAGEMENT_PAGE);
}

void IPSTubeHttpServer::sendError(int status, const char *code, const char *message,
                                  const char *field)
{
  Serial.printf("IPSTube HTTP %d %s: %s\n", status, code, message);
  JsonDocument document;
  document["ok"] = false;
  JsonObject error = document["error"].to<JsonObject>();
  error["code"] = code;
  error["message"] = message;
  if (field != nullptr)
    error["field"] = field;
  String response;
  serializeJson(document, response);
  server_.send(status, "application/json", response);
}

void IPSTubeHttpServer::handleConfig()
{
  JsonDocument document;
  document["ok"] = true;
  document["api_version"] = 1;
  document["config_schema_version"] = 1;
  JsonObject device = document["device"].to<JsonObject>();
  device["name"] = UniqueDeviceName;
  device["hardware"] = "IPSTube H401/H402";
  device["screens"] = SCREEN_COUNT;

  JsonArray layout = document["clock_layout"].to<JsonArray>();
  JsonArray screens = document["screens"].to<JsonArray>();
  const DisplayState &state = ipstubeDisplay.state();
  for (uint8_t screen = 0; screen < SCREEN_COUNT; ++screen)
  {
    JsonObject role = layout.add<JsonObject>();
    role["screen"] = screen;
    role["clock"] = clockRoleName(state.role(screen));
    JsonObject display = screens.add<JsonObject>();
    display["screen"] = screen;
    display["current_image"] = state.currentImage(screen);
    display["saved_image"] = state.savedImage(screen);
  }

  const BacklightSettings &light = backlights.getControlSettings();
  JsonObject backlight = document["backlight"].to<JsonObject>();
  backlight["effect"] = backlightEffectName(light.effect);
  backlight["color"] = colorString(light.color);
  backlight["brightness"] = light.brightness;
  backlight["pulse_bpm"] = light.pulseBpm;
  backlight["breath_bpm"] = light.breathBpm;
  backlight["rainbow_sec"] = light.rainbowSeconds;
  backlight["transitioning"] = backlights.isTransitioning();

  JsonObject storage = document["storage"].to<JsonObject>();
  storage["total_bytes"] = LittleFS.totalBytes();
  storage["used_bytes"] = LittleFS.usedBytes();
  storage["free_bytes"] = LittleFS.totalBytes() - LittleFS.usedBytes();

  String response;
  response.reserve(2048);
  serializeJson(document, response);
  server_.send(200, "application/json", response);
}

void IPSTubeHttpServer::handleImages()
{
  server_.setContentLength(CONTENT_LENGTH_UNKNOWN);
  server_.send(200, "application/json", "");
  server_.sendContent("{\"ok\":true,\"images\":[");
  for (uint16_t image = 0; image <= 255; ++image)
  {
    if (image != 0)
      server_.sendContent(",");
    char name[24];
    imageName(uint8_t(image), name, sizeof(name));
    JsonDocument item;
    item["id"] = image;
    item["name"] = name;
    if (image == BLANK_IMAGE)
    {
      item["path"] = nullptr;
      item["exists"] = true;
      item["size"] = 0;
      item["uploadable"] = false;
    }
    else
    {
      char path[10];
      snprintf(path, sizeof(path), "/%u.bmp", image);
      const bool exists = LittleFS.exists(path);
      item["path"] = path;
      item["exists"] = exists;
      fs::File file = exists ? LittleFS.open(path, "r") : fs::File();
      item["size"] = file ? file.size() : 0;
      item["uploadable"] = true;
      if (file)
        file.close();
    }
    String output;
    serializeJson(item, output);
    server_.sendContent(output);
  }
  server_.sendContent("]}");
  server_.sendContent("");
}

void IPSTubeHttpServer::handleDisplay()
{
  JsonDocument document;
  if (deserializeJson(document, server_.arg("plain")) || !document.is<JsonObject>())
  {
    sendError(400, "INVALID_JSON", "request body must be a JSON object");
    return;
  }
  JsonObjectConst object = document.as<JsonObjectConst>();
  static const char *const allowed[] = {"screen", "image", "save"};
  if (!objectHasOnly(object, allowed, 3) || !object["screen"].is<int>() ||
      !object["image"].is<int>() || (objectHasKey(object, "save") && !object["save"].is<bool>()))
  {
    sendError(400, "INVALID_FIELD", "screen, image or save has an invalid type");
    return;
  }
  const int screen = object["screen"].as<int>();
  const int image = object["image"].as<int>();
  const bool save = object["save"] | false;
  if (screen < 0 || screen >= SCREEN_COUNT)
  {
    sendError(400, "INVALID_FIELD", "screen must be between 0 and 5", "screen");
    return;
  }
  if (image < 0 || image > 255)
  {
    sendError(400, "INVALID_FIELD", "image must be between 0 and 255", "image");
    return;
  }
  if (image != BLANK_IMAGE && !tfts.imageExists(uint8_t(image)))
  {
    sendError(404, "IMAGE_NOT_FOUND", "image file does not exist", "image");
    return;
  }
  if (image != BLANK_IMAGE)
  {
    char path[10];
    snprintf(path, sizeof(path), "/%d.bmp", image);
    if (!tfts.validateImagePath(path))
    {
      sendError(409, "IMAGE_DECODE_FAILED", "image file cannot be decoded safely", "image");
      return;
    }
  }

  if (save)
  {
    PersistedConfigV1 next = ipstubeExtensionConfig.get();
    next.savedImages[screen] = uint8_t(image);
    if (!ipstubeExtensionConfig.save(next))
    {
      sendError(500, "PERSISTENCE_ERROR", "failed to save manual image");
      return;
    }
    ipstubeDisplay.state().setSavedImage(uint8_t(screen), uint8_t(image));
  }

  if (!ipstubeDisplay.showImage(uint8_t(screen), uint8_t(image)))
  {
    sendError(409, "IMAGE_DECODE_FAILED", "image could not be drawn", "image");
    return;
  }
  server_.send(200, "application/json", "{\"ok\":true}");
}

void IPSTubeHttpServer::handleClockLayout()
{
  JsonDocument document;
  if (deserializeJson(document, server_.arg("plain")) || !document.is<JsonArray>())
  {
    sendError(400, "INVALID_JSON", "request body must be a JSON array");
    return;
  }
  JsonArrayConst array = document.as<JsonArrayConst>();
  if (array.size() > SCREEN_COUNT)
  {
    sendError(400, "INVALID_FIELD", "clock layout can contain at most six entries");
    return;
  }

  LayoutEntry entries[SCREEN_COUNT];
  size_t count = 0;
  static const char *const allowed[] = {"screen", "clock"};
  for (JsonVariantConst value : array)
  {
    if (!value.is<JsonObject>())
    {
      sendError(400, "INVALID_FIELD", "each clock layout entry must be an object");
      return;
    }
    JsonObjectConst object = value.as<JsonObjectConst>();
    if (!objectHasOnly(object, allowed, 2) || !object["screen"].is<int>() ||
        !object["clock"].is<const char *>())
    {
      sendError(400, "INVALID_FIELD", "clock layout entry must contain screen and clock");
      return;
    }
    const int screen = object["screen"].as<int>();
    ClockRole role;
    if (screen < 0 || screen >= SCREEN_COUNT)
    {
      sendError(400, "INVALID_FIELD", "screen must be between 0 and 5", "screen");
      return;
    }
    if (!parseClockRole(object["clock"].as<const char *>(), role))
    {
      sendError(400, "INVALID_FIELD", "unknown clock role", "clock");
      return;
    }
    entries[count++] = {uint8_t(screen), role};
  }

  DisplayState candidate = ipstubeDisplay.state();
  const LayoutError result = candidate.replaceClockLayout(entries, count);
  if (result == LayoutError::DUPLICATE_SCREEN)
  {
    sendError(400, "DUPLICATE_SCREEN", "the same screen appears more than once", "screen");
    return;
  }
  if (result != LayoutError::OK)
  {
    sendError(400, "INVALID_FIELD", "invalid clock layout");
    return;
  }

  PersistedConfigV1 next = ipstubeExtensionConfig.get();
  for (uint8_t screen = 0; screen < SCREEN_COUNT; ++screen)
    next.roles[screen] = uint8_t(candidate.role(screen));
  if (!ipstubeExtensionConfig.save(next))
  {
    sendError(500, "PERSISTENCE_ERROR", "failed to save clock layout");
    return;
  }
  ipstubeDisplay.replaceClockLayout(entries, count, currentClockDigits());
  server_.send(200, "application/json", "{\"ok\":true}");
}

void IPSTubeHttpServer::handleBacklight()
{
  JsonDocument document;
  if (deserializeJson(document, server_.arg("plain")) || !document.is<JsonObject>())
  {
    sendError(400, "INVALID_JSON", "request body must be a JSON object");
    return;
  }
  JsonObjectConst object = document.as<JsonObjectConst>();
  static const char *const allowed[] = {
      "effect", "color", "brightness", "pulse_bpm", "breath_bpm",
      "rainbow_sec", "transition_ms", "save"};
  if (!objectHasOnly(object, allowed, 8))
  {
    sendError(400, "INVALID_FIELD", "request contains an unknown field");
    return;
  }

  const bool hasState = objectHasKey(object, "effect") || objectHasKey(object, "color") ||
                        objectHasKey(object, "brightness") || objectHasKey(object, "pulse_bpm") ||
                        objectHasKey(object, "breath_bpm") || objectHasKey(object, "rainbow_sec");
  if (!hasState)
  {
    sendError(400, "INVALID_FIELD", "at least one backlight state field is required");
    return;
  }

  BacklightSettings next = backlights.getControlSettings();
  if (objectHasKey(object, "effect"))
  {
    if (!object["effect"].is<const char *>() ||
        !parseBacklightEffect(object["effect"].as<const char *>(), next.effect))
    {
      sendError(400, "INVALID_FIELD", "unknown backlight effect", "effect");
      return;
    }
  }
  if (objectHasKey(object, "color"))
  {
    if (!object["color"].is<const char *>() ||
        !parseRgb(object["color"].as<const char *>(), next.color))
    {
      sendError(400, "INVALID_FIELD", "color must use #RRGGBB", "color");
      return;
    }
  }
  if (objectHasKey(object, "brightness"))
  {
    if (!object["brightness"].is<int>() || object["brightness"].as<int>() < 0 ||
        object["brightness"].as<int>() > 7)
    {
      sendError(400, "INVALID_FIELD", "brightness must be between 0 and 7", "brightness");
      return;
    }
    next.brightness = object["brightness"].as<uint8_t>();
  }
  if (objectHasKey(object, "pulse_bpm"))
  {
    if (!object["pulse_bpm"].is<int>() || object["pulse_bpm"].as<int>() < 20 ||
        object["pulse_bpm"].as<int>() > 120)
    {
      sendError(400, "INVALID_FIELD", "pulse_bpm must be between 20 and 120", "pulse_bpm");
      return;
    }
    next.pulseBpm = object["pulse_bpm"].as<uint8_t>();
  }
  if (objectHasKey(object, "breath_bpm"))
  {
    if (!object["breath_bpm"].is<int>() || object["breath_bpm"].as<int>() < 5 ||
        object["breath_bpm"].as<int>() > 60)
    {
      sendError(400, "INVALID_FIELD", "breath_bpm must be between 5 and 60", "breath_bpm");
      return;
    }
    next.breathBpm = object["breath_bpm"].as<uint8_t>();
  }
  if (objectHasKey(object, "rainbow_sec"))
  {
    if (!object["rainbow_sec"].is<float>() || object["rainbow_sec"].as<float>() < 0.2f ||
        object["rainbow_sec"].as<float>() > 10.0f)
    {
      sendError(400, "INVALID_FIELD", "rainbow_sec must be between 0.2 and 10.0", "rainbow_sec");
      return;
    }
    next.rainbowSeconds = object["rainbow_sec"].as<float>();
  }

  uint32_t transitionMs = 0;
  if (objectHasKey(object, "transition_ms"))
  {
    if (!object["transition_ms"].is<int>() || object["transition_ms"].as<int>() < 0 ||
        object["transition_ms"].as<int>() > 60000)
    {
      sendError(400, "INVALID_FIELD", "transition_ms must be between 0 and 60000", "transition_ms");
      return;
    }
    transitionMs = object["transition_ms"].as<uint32_t>();
  }
  if (objectHasKey(object, "save") && !object["save"].is<bool>())
  {
    sendError(400, "INVALID_FIELD", "save must be boolean", "save");
    return;
  }
  const bool save = object["save"] | false;

  if (save)
  {
    PersistedConfigV1 persisted = ipstubeExtensionConfig.get();
    persisted.effect = uint8_t(next.effect);
    persisted.color = next.color;
    persisted.brightness = next.brightness;
    persisted.pulseBpm = next.pulseBpm;
    persisted.breathBpm = next.breathBpm;
    persisted.rainbowSeconds = next.rainbowSeconds;
    if (!ipstubeExtensionConfig.save(persisted))
    {
      sendError(500, "PERSISTENCE_ERROR", "failed to save backlight state");
      return;
    }
    backlights.clearPersistenceRequested();
  }

  backlights.applyControlSettings(next, transitionMs);
  JsonDocument response;
  response["ok"] = true;
  response["saved"] = save;
  JsonObject light = response["backlight"].to<JsonObject>();
  light["effect"] = backlightEffectName(next.effect);
  light["color"] = colorString(next.color);
  light["brightness"] = next.brightness;
  light["pulse_bpm"] = next.pulseBpm;
  light["breath_bpm"] = next.breathBpm;
  light["rainbow_sec"] = next.rainbowSeconds;
  light["transitioning"] = transitionMs > 0;
  String output;
  serializeJson(response, output);
  server_.send(200, "application/json", output);
}

bool IPSTubeHttpServer::parseUploadImageId(uint8_t &image)
{
  const String value = server_.pathArg(0);
  if (value.isEmpty())
    return false;
  for (size_t index = 0; index < value.length(); ++index)
  {
    if (!isDigit(value[index]))
      return false;
  }
  const long parsed = value.toInt();
  if (parsed < 0 || parsed > 254)
    return false;
  image = uint8_t(parsed);
  return true;
}

void IPSTubeHttpServer::handleUploadData()
{
  HTTPUpload &upload = server_.upload();
  if (upload.status == UPLOAD_FILE_START)
  {
    uploadResult_ = UploadResult::NO_FILE;
    uploadSize_ = 0;
    if (!parseUploadImageId(uploadImage_))
    {
      uploadResult_ = UploadResult::INVALID_ID;
      return;
    }
    if (upload.name != "file")
    {
      uploadResult_ = UploadResult::INVALID_FIELD;
      return;
    }
    snprintf(uploadTempPath_, sizeof(uploadTempPath_), "/.upload-%u.tmp", unsigned(uploadImage_));
    LittleFS.remove(uploadTempPath_);
    uploadFile_ = LittleFS.open(uploadTempPath_, "w");
    if (!uploadFile_)
    {
      uploadResult_ = UploadResult::FILESYSTEM_ERROR;
      return;
    }
    uploadResult_ = UploadResult::IN_PROGRESS;
  }
  else if (upload.status == UPLOAD_FILE_WRITE)
  {
    if (uploadResult_ != UploadResult::IN_PROGRESS)
      return;
    if (uploadSize_ + upload.currentSize > MAX_IMAGE_BYTES)
    {
      uploadFile_.close();
      LittleFS.remove(uploadTempPath_);
      uploadResult_ = UploadResult::TOO_LARGE;
      return;
    }
    if (uploadFile_.write(upload.buf, upload.currentSize) != upload.currentSize)
    {
      uploadFile_.close();
      LittleFS.remove(uploadTempPath_);
      uploadResult_ = UploadResult::NO_SPACE;
      return;
    }
    uploadSize_ += upload.currentSize;
  }
  else if (upload.status == UPLOAD_FILE_END)
  {
    if (uploadResult_ != UploadResult::IN_PROGRESS)
      return;
    uploadFile_.close();
    if (!tfts.validateImagePath(uploadTempPath_))
    {
      LittleFS.remove(uploadTempPath_);
      uploadResult_ = UploadResult::INVALID_IMAGE;
      return;
    }
    uploadResult_ = replaceUploadedImage(uploadImage_)
                        ? UploadResult::SUCCESS
                        : UploadResult::FILESYSTEM_ERROR;
  }
  else if (upload.status == UPLOAD_FILE_ABORTED)
  {
    if (uploadFile_)
      uploadFile_.close();
    LittleFS.remove(uploadTempPath_);
    uploadResult_ = UploadResult::FILESYSTEM_ERROR;
  }
}

bool IPSTubeHttpServer::replaceUploadedImage(uint8_t image)
{
  char target[12];
  char rollback[24];
  snprintf(target, sizeof(target), "/%u.bmp", unsigned(image));
  snprintf(rollback, sizeof(rollback), "/.rollback-%u.bmp", unsigned(image));
  LittleFS.remove(rollback);

  const bool hadTarget = LittleFS.exists(target);
  if (hadTarget && !LittleFS.rename(target, rollback))
    return false;
  if (!LittleFS.rename(uploadTempPath_, target))
  {
    if (hadTarget)
      LittleFS.rename(rollback, target);
    return false;
  }
  if (hadTarget)
    LittleFS.remove(rollback);
  tfts.InvalidateImageInBuffer();
  ipstubeDisplay.redrawImage(image);
  return true;
}

void IPSTubeHttpServer::handleUploadComplete()
{
  switch (uploadResult_)
  {
  case UploadResult::SUCCESS:
  {
    char name[24];
    imageName(uploadImage_, name, sizeof(name));
    JsonDocument response;
    response["ok"] = true;
    JsonObject image = response["image"].to<JsonObject>();
    image["id"] = uploadImage_;
    image["name"] = name;
    image["size"] = uploadSize_;
    String output;
    serializeJson(response, output);
    server_.send(200, "application/json", output);
    break;
  }
  case UploadResult::INVALID_ID:
    sendError(400, "INVALID_FIELD", "image id must be between 0 and 254", "id");
    break;
  case UploadResult::INVALID_FIELD:
  case UploadResult::NO_FILE:
    sendError(400, "INVALID_FIELD", "multipart field 'file' is required", "file");
    break;
  case UploadResult::TOO_LARGE:
    sendError(413, "IMAGE_TOO_LARGE", "image exceeds 102400 bytes", "file");
    break;
  case UploadResult::NO_SPACE:
    sendError(507, "INSUFFICIENT_STORAGE", "LittleFS has insufficient free space");
    break;
  case UploadResult::INVALID_IMAGE:
    sendError(415, "INVALID_IMAGE_FORMAT", "BMP format or dimensions are invalid", "file");
    break;
  case UploadResult::FILESYSTEM_ERROR:
  case UploadResult::IN_PROGRESS:
    sendError(500, "FILESYSTEM_ERROR", "failed to store uploaded image");
    break;
  }
  uploadResult_ = UploadResult::NO_FILE;
}

void IPSTubeHttpServer::recoverUploads()
{
  for (uint16_t image = 0; image <= 254; ++image)
  {
    char target[12];
    char temporary[24];
    char rollback[24];
    snprintf(target, sizeof(target), "/%u.bmp", image);
    snprintf(temporary, sizeof(temporary), "/.upload-%u.tmp", image);
    snprintf(rollback, sizeof(rollback), "/.rollback-%u.bmp", image);
    LittleFS.remove(temporary);
    if (LittleFS.exists(rollback))
    {
      if (LittleFS.exists(target))
        LittleFS.remove(rollback);
      else
        LittleFS.rename(rollback, target);
    }
  }
}

void IPSTubeHttpServer::handleNotFound()
{
  sendError(404, "NOT_FOUND", "route not found");
}

#endif
