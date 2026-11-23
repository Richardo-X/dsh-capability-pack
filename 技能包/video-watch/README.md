# video-watch

> 让 AI Agent 真的「看」视频 —— 听得见声音，也看得见画面。
> DeepSeek Harness 技能包 · 纯 Python · 零外部二进制依赖

---

## 它解决什么问题

把 B 站链接或本地视频丢给 Agent，它通常只能：
- 拿到标题和简介（**没看内容**）
- 或者把音频转成文字（**画面全丢了**）

这个技能补上两件事：

| 能力 | 做法 |
|---|---|
| **听得见** | faster-whisper 转写 + 逐段置信度 + 可信度判定 |
| **看得见** | 按时间点抽帧（原始分辨率）+ 带时间戳图版 + 裁切放大读小字 |

一句概括作者的设计：

> **量测负责「什么时候」，眼睛负责「是什么」，耳朵负责「说了什么」。**

---

## 为什么不用 ffmpeg.exe / ImageMagick

很多同类方案要求系统装 `ffmpeg` 和 `ImageMagick`。本技能**一个都不需要**：

| 依赖 | 本技能用什么 | 好处 |
|---|---|---|
| ffmpeg | **PyAV**（内置 FFmpeg 库） | 不依赖外部 exe，不被 WindowsApps 权限/杀软拦 |
| ImageMagick | **Pillow** | 裁切、放大、拼图一把梭 |

实测：43 分钟 852×480 视频，顺序解码全片约 **30 秒**（约 2500 帧/秒）。

---

## 安装

### 1. 放技能目录

```powershell
git clone https://github.com/Richardo-X/video-watch "$env:USERPROFILE\.dsh\skills\video-watch"
```

用户级（所有项目可用）。只给单个项目用就放到 `<项目>/.dsh/skills/video-watch`。

### 2. 装依赖

```powershell
pip install "av<19" Pillow faster-whisper
```

> ⚠️ **`av<19` 不能省**：faster-whisper 调用 `av.open(..., metadata_errors=...)`，
> 而 PyAV 19 删掉了这个参数，装最新版第一次转写就 `TypeError`。

### 3. 自检

```powershell
python "$env:USERPROFILE\.dsh\skills\video-watch\scripts\vw.py" doctor
```

输出示例：

```
  OK   Python          3.12.14  (win32)
  OK   av              18.1.0  PyAV
  OK   PIL             12.3.0  Pillow
  OK   faster-whisper  1.2.1
  OK   模型            C:\Users\you\AppData\Local\video-watch\fw-small (461 MB)
  OK   B站 API         可达
  OK   输出目录        可写

  必需项就绪：probe / transcribe / frames / zoom / fetch 全部可用
```

---

## 模型

默认到 `%LOCALAPPDATA%\video-watch\fw-small` 找 `faster-whisper-small`（约 461 MB）。

没有会自动下载。国内建议先设镜像：

```powershell
$env:HF_ENDPOINT = "https://hf-mirror.com"
```

> 实测 `hf-mirror.com` 的大文件可能卡在 0 字节；**ModelScope 更快**：
> `https://modelscope.cn/models/Systran/faster-whisper-small/resolve/master/model.bin`

---

## 用法

### 一条龙

```powershell
python vw.py all BV1o4xg6RE9m --dir ./vw_out --times "180,600,1800"
```

产出：

| 文件 | 内容 |
|---|---|
| `transcript.txt` | `[HH:MM:SS]` 前缀的全文 |
| `transcript.srt` | 标准字幕 |
| `segments.json` | 每段 `no_speech_prob`、`avg_logprob` |
| `risky.md` | **建议优先核对的若干段** + 重复句（弱信号，见下方「已知限制」） |
| `frames/frame_XXmYYs.png` | 指定时刻的原始分辨率截图 |
| `frames/sheet.png` | 带时间戳图版，用于定位 |

### 分步

```powershell
vw.py fetch     BV1o4xg6RE9m --dir ./out --quality mid   # 下载音频+视频
vw.py transcribe ./out/audio.m4s -o ./out                # 转写
vw.py verify     ./out/segments.json ./out/audio.m4s     # 可信度判定
vw.py frames     ./out/video.m4s --times "60,300" -o ./out/frames
vw.py zoom       ./out/frames/frame_01m00s.png --region "40,600,640,80" --scale 4
```

### 本地文件

```powershell
vw.py transcribe D:\video\a.mp4 -o ./out
vw.py frames     D:\video\a.mp4 --auto 8 -o ./out
```

---

## 子命令

| 命令 | 作用 |
|---|---|
| `fetch` | B 站 BV 号/链接 → 下载音频（+可选视频）+ `meta.json` |
| `probe` | 读时长/分辨率/帧率/编码 |
| `transcribe` | 转写 → txt / srt / segments.json / risky.md |
| `verify` | 转写可信度判定（三路互校） |
| `frames` | 按时间点抽帧 + 拼图版 |
| `zoom` | 裁切 + 放大，专门读画面小字 |
| `doctor` | 环境自检 |
| `all` | fetch + transcribe + frames |

---

## 转写可信度：`no_speech_prob` 的语义

**这是最容易搞反的一处。**

`no_speech_prob` 是「**这里没人说话**」的概率：

| 数值 | 含义 |
|---|---|
| `0.0 ~ 0.4` | 倾向**有人**说话 |
| `0.6 ~ 1.0` | 倾向**没人**说话 → 此时的文字很可能是模型编的 |

`avg_logprob` 越接近 0 越自信；`< -0.8` 可疑，通常落在专有名词上。

`verify` 会跑两种模式对照：

1. 默认（开 VAD）
2. 强制（关 VAD、拆掉所有阈值，逼模型无论如何都出字）

然后比对段数、unique 文本比、平均 `no_speech_prob`。**两种证据冲突时它明说「冲突，建议复核」，不硬下结论。**

> 市面上有实现把 `no_speech` 语义读反了（`0.83` 会打印成"低，即认为有人说话"）。
> 本实现按上述语义，不受此影响。

---

## 三条使用铁律

1. **先量测再理解** —— 先 `probe` 拿时长/帧率，再决定抽哪几帧，不猜。
2. **读画面小字必须看原图** —— 图版只用来「定位」，缩略图里的字不能当结论。
3. **转写要交代可信度** —— 别把转录直接当事实交付，尤其专有名词；先跑 `verify`、读 `risky.md`。

---

## 已知限制

### 置信度抓不到「自信的错误」

`risky.md` 的判据来自模型自报的置信度（`avg_logprob`、`no_speech_prob`）。**这只能找"模型犹豫的地方"，找不到"模型自信却听错的地方"。**

实测例子：一段 6 分钟中文技术音频，模型把「知识库」听成「**支持库**」、「不建」听成「**不见**」，而这些段落置信度**完全正常**，`risky.md` 圈不出来。

所以要清醒：

| 情形 | 置信度能发现吗 |
|---|---|
| 音频模糊、口音重、背景吵 | ✅ 通常能 |
| 专有名词被听成常见词（Hermes→爱马仕） | ❌ **不能** |
| 同音近义替换（知识库→支持库） | ❌ **不能** |

**涉及人名、产品名、术语时，必须对照画面文字（用 `zoom` 读原图）或请用户确认，不要只信转录。**

### 其他

| 边界 | 说明 |
|---|---|
| 需登录/付费视频 | 取不到播放地址，需本地文件 |
| 多 P 视频 | `fetch --page N`，默认第 1 P |
| 无音轨 | `frames` 仍可用 |
| 中文字幕烧在画面里 | ASR 与字幕可能不一致，以画面原图为准 |
| 超长视频 | 顺序解码约 2500 帧/秒（852×480） |
| 跨盘移动模型 | 461 MB，建议直接下载到目标位置 |

---

## 许可

MIT

---

## 致谢

方法论受 [video-watch-plus](https://github.com/xinhailaopo/video-watch-plus) 与上游
[video-watch-skill](https://github.com/CFITCorporation/video-watch-skill) 启发：
「ffmpeg 看全部帧（零 token），模型只看几十帧，靠时间戳缝合」。

本实现独立编写，差异在于：
- 用 PyAV 免去外部 ffmpeg / ImageMagick
- 修正了 `no_speech_prob` 的语义判定
- 增加 `doctor` 自检与 `zoom` 读字命令
