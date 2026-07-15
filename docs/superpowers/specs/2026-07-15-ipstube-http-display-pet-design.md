# IPSTube HTTP 显示、图片、Codex 状态与氛围灯控制设计

- 状态：v1 已实现，待实机验收
- 日期：2026-07-15
- 目标硬件：8MB Flash 的 IPSTube H401/H402
- PlatformIO 环境：`IPSTube`
- HTTP API 版本：1
- 持久化数据格式版本：1

## 1. 目标

在不重复刷写固件的前提下，通过局域网 HTTP 接口完成以下工作：

1. 六块屏幕中的任意一块显示任意已安装图片。
2. 动态指定哪些屏幕由时钟自动更新，并支持 `HH:MM` 默认布局。
3. 从浏览器或 HTTP 客户端替换 LittleFS 中的全部可寻址图片。
4. 用最后一块屏幕显示简化的 Codex 宠物状态。
5. 控制氛围灯颜色、亮度和现有效果，并支持非阻塞平滑过渡。
6. 明确区分临时修改和重启后仍保留的修改。

首版以简单、稳定、可恢复为优先，不为少见场景引入任务调度器或通用动画引擎。

## 2. 明确不做的内容

- 不部署 MQTT Broker；局域网控制统一使用 HTTP。
- 不在固件内理解 Codex 任务、线程或优先级；Codex 只是一种 HTTP 调用方。
- 不聚合多个 Codex 任务；多个任务同时调用时，最后到达的状态覆盖前一个状态。
- 不提供失败或 Blocked 状态图片。
- 不提供公网访问、登录、TLS、令牌或权限系统。
- 不提供跨域 CORS；管理页面与 API 同源，命令行客户端不需要 CORS。
- 不提供任意单颗 LED 编程、空间渐变编辑或可配置缓动曲线。
- 不提供图片删除 API；上传同一 ID 即替换，缺失图片可通过重新上传恢复。
- 不保留 IPSTube 自动时钟的旧式“十张图片为一组”的主题切换语义。自动数字固定使用图片 ID `0` 到 `9`。
- 不修改其他硬件环境的显示行为；新增逻辑只在 `HARDWARE_IPSTUBE_CLOCK` 下启用。

## 3. 已有固件分析

### 3.1 Flash 与 LittleFS

`partition_8MB.csv` 为 LittleFS 分配 `0x6b0000` 字节，即 7,012,352 字节（6.6875 MiB）。当前 `data/` 中有 70 张 BMP，逻辑总大小约 1.48 MB，平均约 21.2 KB。

图片数量同时受两个上限约束：

1. API 图片 ID 只有 `0..254`，因此最多寻址 255 张实际图片；`255` 是无文件的黑屏哨兵。
2. LittleFS 容量必须同时容纳所有图片及一次上传所需的临时文件。

容量估算如下，实际结果以 `GET /api/config` 返回的剩余空间为准：

| 图片类型 | 单张典型上限 | 保守可存数量 | 结论 |
| --- | ---: | ---: | --- |
| 当前素材平均值 | 约 21.2 KB | 超过 255 | 可装满全部 255 个图片槽位 |
| 135×240、8 位索引色 BMP | 约 33 KB | 约 175–190 | 容量先于 ID 用尽 |
| 135×240、24 位 BMP | 约 98 KB | 约 55–60 | 不适合大量存储 |

推荐所有素材使用 4 位或 8 位索引色、无压缩 BMP。

### 3.2 当前图片加载器

当前 `TFTs` 支持无压缩的 1、4、8、24 位 BMP，并把图片居中显示到 135×240 屏幕。实现中有两个与本功能直接相关的问题：

- 解码前没有完整校验宽高，超大图片可能写出 `UnpackedImageBuffer` 边界。
- `DrawImage()` 忽略 `LoadImageIntoBuffer()` 的失败返回值，加载失败后仍可能把上一张缓存图片推到屏幕。

实现本设计时必须同时修复这两个问题。绘制接口必须返回成功或失败，失败时保持屏幕原内容。

### 3.3 当前配置存储

现有 `StoredConfig` 把一个固定大小的 C++ 结构体整体写入 Preferences/NVS。直接向该结构体追加字段会改变 blob 长度，旧固件保存的数据可能无法被新固件按原长度读取，连带影响 Wi-Fi、时区等无关配置。

新增显示和 HTTP 灯光配置因此使用独立 NVS namespace，不扩大现有 `StoredConfig::Config`。

### 3.4 当前氛围灯

IPSTube 默认有 6 颗 WS2812；启用底部灯带硬件宏后为 34 颗。现有固件内部效果包括：

- Dark
- Test
- Constant
- Rainbow
- Pulse
- Breath

当前亮度为 `0..7` 八档，颜色为 `0..767` 色相环。HTTP v1 将颜色升级为直接 RGB，但保留八档亮度和现有效果速度范围。

### 3.5 当前应用分区余量

2026-07-15 使用未修改源码执行 `pio run -e IPSTube` 成功，结果为：

```text
RAM:   112,620 / 327,680 bytes（34.4%）
Flash: 1,030,101 / 1,245,184 bytes（82.7%）
Flash 剩余: 215,083 bytes
```

HTTP、JSON 路由和内置管理页必须在现有 `0x130000` 应用分区内完成。v1 不调整分区表；实现后至少保留 65,536 字节应用分区余量。若超限，先压缩管理页和诊断字符串或合并组件，不能静默缩小 LittleFS。

### 3.6 已确认的关键取舍

| 议题 | 采用方案 | 主要原因 |
| --- | --- | --- |
| 局域网协议 | HTTP | 不要求部署 Broker，Codex hook 可直接调用 |
| Web Server | ESP32 Arduino Core 同步 `WebServer` | 无新增依赖，首版请求量低 |
| 图片管理 | LittleFS 在线替换 | 刷一次固件后可长期换图 |
| 自动数字 | 固定使用图片 ID `0..9` | 规则最短，不引入主题组配置 |
| Codex 状态 | 主机 hook 映射成普通图片 ID | 固件保持通用，不绑定 Codex 数据模型 |
| 多任务 | 最后一次事件覆盖 | 用户并行任务少，避免任务聚合器 |
| 灯光颜色 | `#RRGGBB` 直接 RGB | HTTP 调用方无需理解内部色相环 |
| 灯光过渡 | 非阻塞线性插值 | 覆盖淡入淡出需求，不增加缓动系统 |
| 持久化 | 新 namespace、运行态与保存态分离 | 不改变旧配置 blob，不误存临时状态 |

## 4. 总体架构

### 4.1 固件组件

新增或调整以下职责边界：

| 组件 | 职责 |
| --- | --- |
| `HttpControlServer` | 端口 80、路由、JSON 校验、上传流和统一响应 |
| `DisplayController` | 六屏运行状态、时钟角色、手动图片和强制重绘 |
| `ImageStore` | 图片 ID/路径转换、BMP 校验、临时上传、替换和容量查询 |
| `ExtensionConfig` | 独立 NVS 数据格式、默认值、版本检查和持久化影子状态 |
| `TFTs` | 安全解码指定图片 ID，并只在解码成功后推送到屏幕 |
| `Backlights` | 直接 RGB、效果渲染、运行态/持久态分离和非阻塞过渡 |
| 内置管理页 | 从固件 `PROGMEM` 提供最小 HTML/JS 页面，不依赖 LittleFS 文件 |

使用 ESP32 Arduino Core 自带的同步 `WebServer`，继续使用项目已有的 ArduinoJson，不增加异步 Web Server 依赖。主循环调用 `server.handleClient()`；上传按块写入，灯光过渡不得使用 `delay()`。

### 4.2 主机侧 Codex 适配器

Codex 适配器是一个独立的小脚本，由 Codex hooks 调用。它只执行：

```text
Codex 事件 -> 状态图片 ID -> POST /api/display
```

固件不保存 Codex 地址、任务 ID、线程 ID 或任务列表，也不区分调用方。

## 5. 公共枚举与编号

### 5.1 屏幕编号 `ScreenId`

| 值 | 含义 |
| ---: | --- |
| `0` | 物理最左屏 |
| `1` | 从左数第二屏 |
| `2` | 从左数第三屏 |
| `3` | 从左数第四屏 |
| `4` | 从左数第五屏 |
| `5` | 物理最右屏 |

API 始终使用物理从左到右的编号，不暴露当前源码中的秒/分/时内部索引命名。

### 5.2 图片编号 `ImageId`

| 数值 | 枚举名称 | LittleFS 文件 | 说明 |
| ---: | --- | --- | --- |
| `0..249` | `IMAGE_000..IMAGE_249` | `/0.bmp`..`/249.bmp` | 通用图片；其中 `0..9` 同时是自动时钟数字 0..9 |
| `250` | `COLON` | `/250.bmp` | 冒号 |
| `251` | `STATUS_IDLE` | `/251.bmp` | Codex 空闲或会话开始 |
| `252` | `STATUS_WORKING` | `/252.bmp` | Codex 正在工作 |
| `253` | `STATUS_WAITING` | `/253.bmp` | Codex 等待用户批准或输入 |
| `254` | `STATUS_COMPLETE` | `/254.bmp` | Codex 当前轮次完成 |
| `255` | `BLANK` | 无文件 | 直接清黑屏幕；不能上传 |

规则：

- `/api/display` 接受完整的 `0..255`。
- `/api/images/{id}` 只接受 `0..254`。
- 特殊名称只是稳定约定，不限制通用接口；任何调用方都能显示和替换 `250..254`。
- 自动时钟数字值 `n` 直接映射为图片 ID `n`，不再乘以主题编号。
- 初始文件系统把现有第一套数字素材复制为 `/0.bmp` 到 `/9.bmp`；原有 `/10.bmp` 到 `/79.bmp` 可继续作为普通图片存在。

### 5.3 时钟角色 `ClockRole`

HTTP 字符串枚举如下，大小写敏感：

| 值 | 含义 | 自动显示内容 |
| --- | --- | --- |
| `MANUAL` | 手动屏幕 | 不由时钟更新 |
| `H1` | 小时十位 | 当前小时十位 |
| `H2` | 小时个位 | 当前小时个位 |
| `M1` | 分钟十位 | 当前分钟十位 |
| `M2` | 分钟个位 | 当前分钟个位 |
| `S1` | 秒钟十位 | 当前秒钟十位 |
| `S2` | 秒钟个位 | 当前秒钟个位 |
| `COLON` | 固定冒号 | 图片 ID `250` |

相同角色允许绑定到多个屏幕。小时仍遵循现有 12/24 小时设置及小时十位留空设置；需要留空时显示 `BLANK`，不是数字 0。

### 5.4 灯光效果 `BacklightEffect`

HTTP 字符串枚举如下，大小写敏感：

| 值 | 含义 | 使用 `color` | 使用的速度字段 |
| --- | --- | --- | --- |
| `off` | 关闭灯光 | 保留但不显示 | 无 |
| `constant` | 全灯常亮 | 是 | 无 |
| `rainbow` | 现有空间彩虹循环 | 否 | `rainbow_sec` |
| `pulse` | 脉冲亮度 | 是 | `pulse_bpm` |
| `breath` | 呼吸亮度 | 是 | `breath_bpm` |

内部诊断效果 `Test` 不开放为 HTTP 枚举，避免远程接口混入硬件测试行为。

## 6. 默认状态

首次启动、扩展配置不存在或扩展配置版本未知时，采用：

| 屏幕 | 角色 | 保存的手动图片 |
| ---: | --- | ---: |
| 0 | `H1` | `255` |
| 1 | `H2` | `255` |
| 2 | `COLON` | `250` |
| 3 | `M1` | `255` |
| 4 | `M2` | `255` |
| 5 | `MANUAL` | `251` |

默认视觉效果为 `HH:MM + STATUS_IDLE`。

灯光扩展配置不存在时，从现有 Backlights 配置生成运行状态：现有色相转换为 RGB，保留原亮度、效果和速度。这样升级固件不会突然改变用户已有灯光设置。

## 7. HTTP 通用约定

- 协议：HTTP/1.1
- 监听：设备所有局域网接口的 TCP 80 端口
- JSON：`Content-Type: application/json`
- 字符编码：UTF-8
- 修改接口严格校验字段；未知字段返回错误，避免拼写错误静默生效。
- 所有数值必须使用 JSON number，不能用数字字符串代替。
- 所有修改先完整校验，再执行；批量布局不存在部分成功。

成功响应至少包含：

```json
{
  "ok": true
}
```

失败响应统一为：

```json
{
  "ok": false,
  "error": {
    "code": "INVALID_FIELD",
    "message": "brightness must be between 0 and 7",
    "field": "brightness"
  }
}
```

`field` 只在错误能定位到请求字段时出现。

## 8. API 详细定义

### 8.1 `GET /`

返回固件内置的管理页面。页面至少提供：

- 当前六屏角色、当前图片和保存的手动图片。
- 为任意屏幕立即选择图片，并可选择是否保存。
- 编辑完整时钟布局。
- 查看 0..255 的图片枚举及 0..254 的文件存在状态。
- 向 0..254 的任意 ID 上传 BMP。
- 控制灯光颜色、亮度、效果、速度、过渡时间和是否保存。
- 显示 LittleFS 已用和剩余空间。

HTML、CSS 和 JavaScript 编译进 `PROGMEM`，即使 LittleFS 图片损坏，管理页仍可打开。

### 8.2 `GET /api/config`

返回设备当前运行状态、持久状态和容量信息。

示例：

```json
{
  "ok": true,
  "api_version": 1,
  "config_schema_version": 1,
  "device": {
    "name": "ipstube-a1b2c3",
    "hardware": "IPSTube H401/H402",
    "screens": 6
  },
  "clock_layout": [
    {"screen": 0, "clock": "H1"},
    {"screen": 1, "clock": "H2"},
    {"screen": 2, "clock": "COLON"},
    {"screen": 3, "clock": "M1"},
    {"screen": 4, "clock": "M2"},
    {"screen": 5, "clock": "MANUAL"}
  ],
  "screens": [
    {"screen": 0, "current_image": 1, "saved_image": 255},
    {"screen": 1, "current_image": 4, "saved_image": 255},
    {"screen": 2, "current_image": 250, "saved_image": 250},
    {"screen": 3, "current_image": 0, "saved_image": 255},
    {"screen": 4, "current_image": 7, "saved_image": 255},
    {"screen": 5, "current_image": 252, "saved_image": 251}
  ],
  "backlight": {
    "effect": "constant",
    "color": "#FF8000",
    "brightness": 5,
    "pulse_bpm": 60,
    "breath_bpm": 20,
    "rainbow_sec": 8.0,
    "transitioning": false
  },
  "storage": {
    "total_bytes": 7012352,
    "used_bytes": 1483256,
    "free_bytes": 5529096
  }
}
```

`current_image` 是屏幕最后成功绘制的图片 ID；黑屏为 `255`。`saved_image` 是该屏幕下次以 `MANUAL` 启动时使用的图片，不代表当前一定正在显示它。

### 8.3 `GET /api/images`

返回全部图片枚举。响应应流式生成，避免为 255 项列表分配一个大型 JSON 文档。

单项格式：

```json
{
  "id": 252,
  "name": "STATUS_WORKING",
  "path": "/252.bmp",
  "exists": true,
  "size": 21120,
  "uploadable": true
}
```

`255` 的返回值固定为：

```json
{
  "id": 255,
  "name": "BLANK",
  "path": null,
  "exists": true,
  "size": 0,
  "uploadable": false
}
```

### 8.4 `POST /api/images/{id}`

用 multipart/form-data 上传并替换一张图片。

- 路径参数 `id`：整数 `0..254`
- multipart 字段名：`file`
- 文件类型：无压缩 BMP
- 最大 HTTP 文件数据：102,400 字节
- 宽度：`1..135`
- 高度：`1..240`，只接受正高度的 bottom-up BMP
- planes：必须为 1
- bits per pixel：`1`、`4`、`8` 或 `24`
- compression：必须为 `BI_RGB`，即 0

示例：

```bash
curl -F 'file=@working.bmp;type=image/bmp' http://ipstube.local/api/images/252
```

处理顺序：

1. 数据流写入临时文件，不触碰旧图片。
2. 校验 BMP 头、调色板、偏移、行跨度、数据长度、尺寸和位深。
3. 实际尝试解码临时文件，确认不会越界。
4. 用 rename/rollback 流程替换目标文件。
5. 使图片缓存失效。
6. 强制重绘所有当前正在显示该 ID 的屏幕。

上传、校验或替换失败时删除临时文件，保留旧图片与当前屏幕。成功上传本身已经写入 LittleFS，不使用 `save` 字段。

成功响应：

```json
{
  "ok": true,
  "image": {
    "id": 252,
    "name": "STATUS_WORKING",
    "size": 21120
  }
}
```

### 8.5 `POST /api/display`

立即让一块屏幕显示指定图片。

请求字段：

| 字段 | 类型 | 必填 | 取值 | 含义 |
| --- | --- | --- | --- | --- |
| `screen` | integer | 是 | `0..5` | 物理屏幕编号 |
| `image` | integer | 是 | `0..255` | 图片枚举 |
| `save` | boolean | 否 | `false`/`true` | 是否保存为该屏幕的手动启动图片；默认 `false` |

示例：

```json
{
  "screen": 5,
  "image": 252,
  "save": false
}
```

语义：

- 每次调用都强制重绘，即使该屏幕的 `current_image` 已是同一 ID。
- 调用不会改变该屏幕的 `ClockRole`。
- 时钟角色屏幕可以被临时覆盖，但下一次对应时间数字变化时会再次被时钟覆盖。
- `save:true` 只更新该屏幕的 `saved_image`。若屏幕仍有自动角色，重启后仍优先显示自动内容；当角色以后变为 `MANUAL` 时才使用保存图片。
- `image:255` 直接清黑，无需 LittleFS 文件。
- `0..254` 对应文件不存在或解码失败时返回错误，屏幕和保存值均保持不变。
- `save:true` 时先验证图片和 NVS 写入；任一步失败均不应用修改。

### 8.6 `PUT /api/clock-layout`

整体替换六屏时钟角色并持久化。请求体是数组：

```json
[
  {"screen": 0, "clock": "H1"},
  {"screen": 1, "clock": "H2"}
]
```

数组项字段：

| 字段 | 类型 | 必填 | 取值 |
| --- | --- | --- | --- |
| `screen` | integer | 是 | `0..5` |
| `clock` | string | 是 | `MANUAL`、`H1`、`H2`、`M1`、`M2`、`S1`、`S2`、`COLON` |

规则：

- 同一 `screen` 不能出现两次。
- 同一时钟角色可以用于多块屏幕。
- 未出现在数组里的屏幕自动变为 `MANUAL`。
- 空数组 `[]` 表示六屏全部手动。
- 全部字段校验成功后才写 NVS 和切换，失败时保持旧布局。
- 这是配置接口，因此成功请求总是持久化，不提供 `save` 字段。
- 新绑定的数字角色和 `COLON` 立即重绘。
- 新变为 `MANUAL` 的屏幕暂时保留当前画面，之后只由 `/api/display` 修改；设备重启时显示其 `saved_image`。

### 8.7 `POST /api/backlight`

对当前灯光目标做部分更新。未提供的字段保留当前值。

请求字段：

| 字段 | 类型 | 必填 | 取值/格式 | 持久化 |
| --- | --- | --- | --- | --- |
| `effect` | string | 否 | `off`、`constant`、`rainbow`、`pulse`、`breath` | `save:true` 时保存 |
| `color` | string | 否 | `#RRGGBB`，正则 `^#[0-9A-Fa-f]{6}$` | `save:true` 时保存 |
| `brightness` | integer | 否 | `0..7` | `save:true` 时保存 |
| `pulse_bpm` | integer | 否 | `20..120` | `save:true` 时保存 |
| `breath_bpm` | integer | 否 | `5..60` | `save:true` 时保存 |
| `rainbow_sec` | number | 否 | `0.2..10.0` | `save:true` 时保存 |
| `transition_ms` | integer | 否 | `0..60000`，默认 `0` | 不保存，仅控制本次变化 |
| `save` | boolean | 否 | 默认 `false` | 决定是否保存最终灯光目标 |

`brightness:0` 保持与现有八档亮度的兼容语义，表示最低档而不是逻辑关闭；完全关闭使用 `effect:"off"`。八档的最大硬件亮度依次为 `1、3、7、15、31、63、127、255`。Pulse 和 Breath 可以在各自周期低点短暂低于该最大值。

完整示例：

```json
{
  "effect": "breath",
  "color": "#2080FF",
  "brightness": 6,
  "breath_bpm": 10,
  "transition_ms": 800,
  "save": true
}
```

规则：

- 除 `transition_ms` 和 `save` 外，请求至少包含一个灯光状态字段。
- 效果速度字段可提前设置，即使当前不是对应效果。
- `rainbow` 使用现有每颗 LED 相位错开的空间彩虹，不使用 `color`，但不会清除已保存颜色。
- `off` 不清除颜色、亮度或速度；以后切回其他效果时继续使用原值。
- `save:false` 只修改运行状态，不写 NVS。
- `save:true` 先写入持久化目标，再开始过渡；写入失败时不改变运行状态。
- 只保存最终目标，不保存中间动画帧；`transition_ms` 不持久化。

成功响应返回合并后的目标：

```json
{
  "ok": true,
  "saved": true,
  "backlight": {
    "effect": "breath",
    "color": "#2080FF",
    "brightness": 6,
    "pulse_bpm": 60,
    "breath_bpm": 10,
    "rainbow_sec": 8.0,
    "transitioning": true
  }
}
```

## 9. 灯光过渡定义

首版“渐变”定义为整组灯从当前实际输出平滑过渡到新目标，不是用户可编程的逐灯空间渐变。

实现规则：

1. 收到请求时快照每颗 LED 的当前实际 RGB 输出。
2. 每次 `Backlights::loop()` 根据新效果计算该时刻的目标帧。
3. 按 `elapsed / transition_ms` 对快照帧和目标帧做线性 RGB 插值。
4. 到达 100% 后直接运行目标效果。
5. 过渡期间收到新请求时，以当时已渲染的帧为新起点重新开始，不跳回旧目标。
6. `transition_ms:0` 立即切换。
7. 整个过程基于 `millis()`，不得阻塞 HTTP、时钟更新、按钮或 Wi-Fi 维护。

不增加 easing 枚举。线性插值已经覆盖颜色淡变、亮度淡入淡出、关闭和效果切换；后续只有在实际观感不足时才考虑扩展。

## 10. 持久化设计

### 10.1 NVS 位置与版本

使用独立 Preferences namespace：

```text
namespace: ipstube_ext
key: schema   -> uint8，当前为 1
key: payload  -> PersistedConfigV1 blob
```

版本号只表示持久化数据布局，不是固件版本、HTTP API 版本或用户修改次数。

读取规则：

- `schema` 不存在：使用第 6 节默认值。
- `schema == 1` 且 payload 长度正确：按 V1 加载。
- 版本未知或长度不正确：记录串口警告，只对扩展功能使用默认值，不擦除数据，不影响原 Wi-Fi、时区和 RTC 配置。
- 将来出现 V2 时再增加明确的 V1→V2 迁移；V1 不预先实现通用迁移框架。

NVS 自身已有记录完整性保护，V1 不额外增加 CRC。

### 10.2 V1 持久字段

`PersistedConfigV1` 逻辑上包含：

- 六个 `ClockRole`
- 六个 `saved_image`
- 灯光 `effect`
- 灯光直接 RGB 值
- 灯光 `brightness`
- `pulse_bpm`
- `breath_bpm`
- `rainbow_sec`

不持久化：

- `current_image`
- 灯光中间帧
- `transition_ms`
- HTTP 客户端或 Codex 任务信息

### 10.3 运行态与持久态分离

内存中必须保存独立的 runtime state 和 persisted shadow，避免后续一次配置保存把先前 `save:false` 的临时状态意外写入 NVS。

- `/api/display save:false`：只改当前屏幕。
- `/api/display save:true`：更新指定屏幕的 persisted shadow 并写 NVS。
- `/api/backlight save:false`：只改灯光 runtime state。
- `/api/backlight save:true`：更新灯光 persisted shadow 并写 NVS。
- `/api/clock-layout`：更新角色 persisted shadow 并写 NVS。

现有物理菜单和 MQTT 若修改并保存灯光，也必须通过同一个 Backlights 持久化入口更新灯光 persisted shadow，不能形成第二套互相覆盖的灯光来源。HTTP 的临时状态仍不得因菜单保存其他字段而被顺带持久化。

## 11. Codex 简化宠物集成

### 11.1 状态映射

根据 Codex 官方 hooks 的轮次事件，主机脚本采用：

| Codex hook | 图片 ID | 状态 |
| --- | ---: | --- |
| `SessionStart` | 251 | idle |
| `UserPromptSubmit` | 252 | working |
| `PermissionRequest` | 253 | waiting |
| `PostToolUse` | 252 | working |
| `Stop` | 254 | complete |

不映射失败状态。`Stop` 后保持 complete，直到下一次 `SessionStart` 或 `UserPromptSubmit`；首版不启动延迟回 idle 的常驻进程。

### 11.2 调用约定

适配器默认把宠物状态发到屏幕 5：

```http
POST /api/display
Content-Type: application/json

{"screen":5,"image":252,"save":false}
```

脚本配置使用主机环境变量，例如：

```text
IPSTUBE_URL=http://ipstube.local
IPSTUBE_STATUS_SCREEN=5
```

脚本要求：

- HTTP 连接和总超时均保持很短，建议 500 ms。
- 网络失败只写本地诊断或静默忽略，始终以 0 退出，不能阻断 Codex 工作。
- 不向 stdout 输出内容，避免输出被 Codex 当成 hook 上下文。
- 用户需要在 Codex `/hooks` 中审核并信任 hook 定义。
- 用户级 `~/.codex/hooks.json` 适合覆盖所有仓库；项目级 hook 只适合希望跟随该仓库的情况。

可直接从 `tools/codex_ipstube_hooks.example.json` 开始配置：

1. 把示例复制为 `~/.codex/hooks.json`，或将其中各事件合并进已有的 `hooks` 对象。
2. 把五处 `/absolute/path/to/EleksTubeHAX` 改为本仓库的绝对路径。
3. 把 `http://ipstube.local` 改为设备实际地址；如状态屏不是最右屏，再改 `IPSTUBE_STATUS_SCREEN`。
4. 重启或恢复 Codex 任务后执行 `/hooks`，审核并信任这些命令。

不经过 Codex 的手动联调命令：

```bash
printf '%s' '{"hook_event_name":"UserPromptSubmit"}' \
  | IPSTUBE_URL=http://ipstube.local IPSTUBE_STATUS_SCREEN=5 \
    python3 tools/codex_ipstube_status.py
```

脚本刻意吞掉网络异常且不输出 stdout，因此设备离线时也不会影响 Codex；联调时可另用 `curl` 检查设备是否可达。

### 11.3 多任务语义

Codex 桌面宠物会聚合多个任务，并按 Needs input、Blocked、Ready、Running 的顺序决定优先显示项。本方案有意简化：

- 不查询 Codex 全局任务列表。
- 不保存任务集合或时间戳。
- 任意任务的最后一次 hook HTTP 请求决定当前图片。
- 用户很少并行运行多个任务时，这一行为足够直观。

## 12. 图片安全与替换可靠性

BMP 校验器必须在任何像素写入前完成整数范围检查，并使用至少 32 位无符号整数计算：

```text
row_stride = ((bits_per_pixel * width + 31) >> 5) * 4
required_bytes = pixel_offset + row_stride * height
```

必须检查乘法和加法不会溢出，并验证 `required_bytes <= uploaded_file_size`。调色板项数不能超过对应位深允许的数量。

替换策略：

- 上传文件使用不会与图片 ID 冲突的固定临时路径。
- 只有校验和试解码均通过后才进入替换阶段。
- 若底层 rename 不能覆盖已有文件，先把旧文件改名为 rollback 文件，再把临时文件改为目标；第二步失败时恢复旧文件。
- 启动时清理遗留临时文件，并在目标缺失而 rollback 文件存在时恢复 rollback 文件。

这样既满足普通失败时保留旧图，也覆盖替换过程中掉电留下的可恢复状态。

## 13. HTTP 状态码与错误码

| HTTP | `error.code` | 使用场景 |
| ---: | --- | --- |
| 400 | `INVALID_JSON` | JSON 语法错误或顶层类型错误 |
| 400 | `INVALID_FIELD` | 缺字段、未知字段、类型或范围错误 |
| 400 | `DUPLICATE_SCREEN` | clock-layout 同一屏幕重复出现 |
| 404 | `NOT_FOUND` | 路由不存在 |
| 404 | `IMAGE_NOT_FOUND` | 请求显示的 0..254 图片文件不存在 |
| 409 | `IMAGE_DECODE_FAILED` | 文件存在但无法安全解码；当前屏幕保持不变 |
| 413 | `IMAGE_TOO_LARGE` | 上传数据超过 102,400 字节 |
| 415 | `INVALID_IMAGE_FORMAT` | BMP 头、尺寸、位深、压缩或数据长度不符合要求 |
| 507 | `INSUFFICIENT_STORAGE` | LittleFS 空间不足，无法完成临时上传 |
| 500 | `FILESYSTEM_ERROR` | LittleFS 打开、写入、rename 或 rollback 失败 |
| 500 | `PERSISTENCE_ERROR` | NVS 写入失败 |

所有错误同时写一条简短串口日志，但不得包含 Wi-Fi 密码或请求中的无关数据。

## 14. 安全边界

HTTP v1 假设设备仅位于可信局域网。任何能访问设备 80 端口的人都可以：

- 改变六屏内容；
- 替换图片；
- 改变灯光；
- 修改并持久化布局。

管理页不读取或返回 Wi-Fi 密码，不执行外部脚本，不从 CDN 加载资源。若未来需要跨网段或公网控制，应在网络层使用 VPN/反向代理，而不是在 ESP32 首版中加入自制认证系统。

## 15. 与现有功能的兼容性

- 其他 PlatformIO 硬件环境维持原有时钟主题和显示逻辑。
- IPSTube 的 RTC、NTP、12/24 小时制、小时十位留空、按钮、屏幕调光和夜间调光继续工作。
- IPSTube 自动时钟角色只决定哪些屏幕接收数字，不改变时间来源。
- 旧式 `current_graphic * 10 + digit` 不再用于 IPSTube 的自动角色；旧图片仍可被 HTTP 当普通图片显示。
- MQTT 可以继续编译，但不是本功能依赖。MQTT 与物理菜单的灯光修改必须调用统一 Backlights 状态入口。
- HTTP 页面只有在 Wi-Fi 已连接后可访问；Wi-Fi 断开时本地时钟、手动屏幕和灯光继续运行。

## 16. 实际代码改动

新增：

- `include/IPSTubeControlTypes.h`、`src/IPSTubeControlTypes.cpp`
- `include/IPSTubeBmpValidator.h`、`src/IPSTubeBmpValidator.cpp`
- `include/IPSTubeExtensionConfig.h`、`src/IPSTubeExtensionConfig.cpp`
- `include/IPSTubeDisplayController.h`、`src/IPSTubeDisplayController.cpp`
- `include/IPSTubeHttpServer.h`、`src/IPSTubeHttpServer.cpp`
- `tools/codex_ipstube_status.py`：只使用 Python 标准库的主机脚本
- `tools/codex_ipstube_hooks.example.json`：用户级 hooks 配置模板
- `scripts/generate_ipstube_assets.py`：可重复生成冒号和四张默认状态图
- `scripts/test_ipstube_control.sh`、`tests/`：主机侧核心逻辑与 hook 测试

修改：

- `src/main.cpp`：初始化/轮询 HTTP，改由 DisplayController 分发时钟数字。
- `include/TFTs.h`、`src/TFTs.cpp`：安全的 `drawImageById()`、路径解码和布尔返回值。
- `include/Backlights.h`、`src/Backlights.cpp`：直接 RGB、统一状态入口、线性过渡。
- `data/`：提供 `/0.bmp` 到 `/9.bmp`、`/250.bmp` 到 `/254.bmp` 的默认素材。

实现保持在 IPSTube 条件编译边界内，没有为其他硬件引入 HTTP 显示状态。

### 16.1 首次烧录与后续维护

首次使用本功能必须同时烧录固件和 LittleFS，因为 `0..9`、`250..254` 的默认文件位于 `data/`：

```bash
pio run -e IPSTube -t upload
pio run -e IPSTube -t uploadfs
```

之后修改任意图片只需打开 `http://<设备地址>/`，或调用 `POST /api/images/{id}`，无需重新编译或刷写固件。布局、手动图片和灯光设置按各接口的持久化规则写入 NVS，也不需要重刷。

如需重建仓库内的默认冒号与状态素材：

```bash
python3 scripts/generate_ipstube_assets.py
```

该脚本只生成默认占位素材；设备上已经通过 HTTP 上传的自定义图片不受影响。

## 17. 验证计划

### 17.1 构建

```bash
pio run -e IPSTube
```

还必须执行 `pio run -e EleksTube`，证明条件编译没有泄漏 IPSTube 专用类型。实现后的 IPSTube 固件至少保留 65,536 字节应用分区余量。

### 17.2 API 与显示

1. 默认启动显示 `HH:MM + idle`。
2. 六个 `screen` 编号与物理左到右一致。
3. `POST /api/display` 可显示 0、249、250、251、252、253、254 和 255。
4. 相同图片 ID 重复请求仍发生强制重绘。
5. 时钟绑定屏幕临时覆盖后，在对应数字变化时恢复自动显示。
6. `PUT /api/clock-layout` 示例只绑定 H1/H2，其余屏幕之后不再被时钟更新。
7. 重复 screen、未知 role 和越界值均整体失败。

### 17.3 图片上传

1. 分别上传 1、4、8、24 位合法 BMP。
2. 上传错误 magic、压缩 BMP、负高度、超尺寸、截断数据和超 100 KiB 文件。
3. 所有非法文件都保留旧图片和当前屏幕。
4. 替换当前正在多个屏幕显示的图片时，全部相关屏幕重绘。
5. 空间不足返回 507，并清理临时文件。
6. 模拟遗留 rollback 文件后重启，验证自动恢复。

### 17.4 持久化

1. `save:false` 的图片和灯光修改在重启后消失。
2. `save:true` 的手动图片和灯光目标在重启后恢复。
3. clock-layout 总是跨重启保留。
4. 自动角色优先于 `saved_image`。
5. 写入未知 schema 后，扩展功能回默认，原 Wi-Fi 和时间配置保持不变。
6. 一次菜单或其他配置保存不会意外保存先前的 HTTP 临时灯光状态。

### 17.5 灯光

1. 验证 `off`、`constant`、`rainbow`、`pulse`、`breath`。
2. 验证颜色 `#000000`、`#FFFFFF` 和三原色。
3. 验证亮度 0 与 7、速度边界和越界拒绝。
4. 验证 0 ms 立即切换和 60,000 ms 非阻塞过渡。
5. 过渡中发出新请求，不发生跳回旧颜色。
6. 过渡期间 HTTP、时钟秒更新和按钮仍响应。

### 17.6 Codex hooks

1. SessionStart 显示 idle。
2. 提交消息后显示 working。
3. 出现批准请求时显示 waiting。
4. 工具继续执行后恢复 working。
5. 当前轮次停止后显示 complete。
6. IPSTube 离线时 hook 快速成功退出，不拖慢或阻断 Codex。

## 18. 完成标准

满足以下条件即认为 v1 完成：

- 初次刷入一次固件和 LittleFS 后，所有 0..254 图片均可通过 HTTP 替换。
- 六屏均可通过通用 API 显示任意图片枚举或黑屏。
- 时钟角色可由 HTTP 整体重配并跨重启保存。
- 默认布局稳定显示 `HH:MM + Codex 状态`。
- Codex 状态映射不依赖 MQTT，且固件保持调用方无关。
- 氛围灯支持 RGB、八档亮度、五种公开效果和非阻塞线性过渡。
- 临时状态和持久状态不会互相污染。
- 非法或失败的图片上传不会导致旧图丢失、缓存旧图误画或内存越界。
- 现有 Wi-Fi、时间和其他硬件构建不因扩展配置而损坏。

## 19. 参考资料

- 仓库 `platformio.ini`、`partition_8MB.csv`
- 仓库 `include/TFTs.h`、`src/TFTs.cpp`
- 仓库 `include/Backlights.h`、`src/Backlights.cpp`
- 仓库 `include/StoredConfig.h`
- Codex 官方文档：[Hooks](https://learn.chatgpt.com/docs/hooks.md)
- Codex 官方文档：[Pets](https://learn.chatgpt.com/docs/pets.md)

## 20. 实现验证结果

2026-07-15 的主机侧验证结果：

| 项目 | 结果 |
| --- | --- |
| 核心 C++ 单元测试 | 通过；覆盖枚举、布局原子替换、时钟映射、BMP 边界、持久化字段和灯光插值 |
| Codex hook Python 测试 | 6/6 通过 |
| `IPSTube` 固件构建 | 通过；RAM 113,252 / 327,680，Flash 1,087,113 / 1,245,184 |
| IPSTube 应用分区余量 | 158,071 字节，大于 65,536 字节目标 |
| `EleksTube` 兼容构建 | 通过；证明 IPSTube 条件编译未破坏原硬件环境 |
| LittleFS 素材 | 85 张 BMP；`data/` 全部文件逻辑大小 1,941,731 字节 |
| 7,012,352 字节 LittleFS 镜像 | 使用 PlatformIO 对应的 `mklittlefs 1.203.210628` 参数构建成功 |

尚需在真实 H401/H402 上完成第 17.2 到 17.6 节中的硬件验收，重点检查物理左右屏幕编号、BMP 上传掉电恢复、60 秒灯光过渡期间的交互响应，以及本机网络环境中的 Codex hook 时序。
