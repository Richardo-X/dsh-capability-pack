---
name: video-watch
description: Use when the user gives a Bilibili link (BV id) or a local video/audio file and expects the actual content to be read — spoken words, on-screen text, slides, diagrams, demo screens — instead of guessed from the title or description. Produces a timestamped transcript, an ASR trust verdict that flags likely mis-heard proper nouns, and timestamped frame captures plus a labelled contact sheet. Works without login, without external ffmpeg or ImageMagick, and for local files too.
whenToUse: The user pastes a bilibili.com/video/BV... link or a local .mp4/.mkv/.m4a/.wav path and asks what it says, what it shows, how some part of it works, or asks to summarize/extract/compare its content. Also use when a previous answer about a video was based only on its description or a transcript and the user questions whether the screen content was actually seen.
---

# video-watch — 真的看视频

## 什么时候必须用

- 用户给了 B 站链接或本地视频，问"讲了什么/第几分钟说了啥/画面里那个图是什么"
- **特别地**：只用简介或转录回答过、被用户质疑"你是不是没看视频"时 —— 这是本 skill 存在的首要原因

## 三条铁律

1. **先量测再理解**：先 `probe` 拿时长/分辨率/帧率，再决定抽哪几帧。不猜。
2. **读画面小字必须看原图**：图版（contact sheet）只用来"定位"，不要把缩略图里的字当结论。
3. **转写要交代可信度**：不要直接把自己转出来的文字当事实交付，尤其专有名词 —— 跑 `verify`，并读 `risky.md`。

## 环境

- 纯 Python：`PyAV`（内置 FFmpeg 库）+ `Pillow` + `faster-whisper`
- **不需要**外部 `ffmpeg.exe`、**不需要** ImageMagick
- 模型：若 `<LOCALAPPDATA>\video-watch\fw-small` 存在则复用，否则 `--model small` 会自动下载（约 460 MB，国内建议先设 `HF_ENDPOINT=https://hf-mirror.com`）
- 脚本路径：本 skill 目录下的 `scripts/vw.py`（记为 `<VW>`）

## 标准流程

### 1. 一串命令跑完（推荐）

```bash
python <VW> all BV1xxxxxxxxx --dir ./vw_out --times "180,600,1800"
```

产出：

| 文件 | 内容 |
|---|---|
| `transcript.txt` | 带 `[HH:MM:SS]` 的全文 |
| `transcript.srt` | 字幕 |
| `segments.json` | 每段的 `no_speech_prob`、`avg_logprob` |
| `risky.md` | **低置信度段落** —— 专有名词最可能错的地方 |
| `frames/frame_XXmYYs.png` | 指定时间点的**原始分辨率**截图 |
| `frames/sheet.png` | 带时间戳的图版，用于快速定位 |

### 2. 分步跑（需要精细控制时）

```bash
python <VW> fetch BV1xxxxxxxxx --dir ./vw_out --quality mid   # 下载音频+视频+meta.json
python <VW> transcribe ./vw_out/audio.m4s -o ./vw_out          # 转写
python <VW> verify ./vw_out/segments.json ./vw_out/audio.m4s   # 可信度判定
python <VW> frames ./vw_out/video.m4s --times "60,300" -o ./vw_out/frames
```

### 3. 本地文件

```bash
python <VW> transcribe D:\path\a.mp4 -o ./out
python <VW> frames D:\path\a.mp4 --auto 8 -o ./out
```

## 抽帧策略

| 情况 | 做法 |
|---|---|
| 用户点名时间点 | `--times "180,600"`（秒） |
| 要摸清全片结构 | `--auto 8`（均匀 8 帧，先看图版定方向） |
| 讲演示/界面/图表 | 每个论点处抽 1 帧，然后对**关键几张看原图**读字 |
| 纯口播无画面 | 不用抽帧，只转写 |

**图版只是地图**：图版上看到哪一格有重要内容，用 `frames --times <那一刻>` 再单独看原图。

## 可信度判定的语义（别搞反）

`no_speech_prob` 是「**这里没人说话**」的概率，**数值越高越可能是幻听**。

- `0.0~0.4`：倾向有人说话
- `0.6~1.0`：**倾向没人说话**，此时的文字很可能是模型编的

`avg_logprob` 越接近 0 越自信；`< -0.8` 属于可疑，通常就落在专有名词上。

`verify` 已按上述语义实现，并会在两种证据冲突时明确说"冲突，建议复核"，不会强行下结论。

## 交付时必须说明

- 转写覆盖了多长时间、共几段
- 可信度判定结论（一句话）
- **哪些地方可能听错** —— 但要说清 `risky.md` 只是**弱信号**：
  它能找"模型犹豫处"，**找不到"模型自信却听错"的专有名词**
- 画面部分：看了哪几个时间点，图版在哪，是否读了原图
- 涉及人名/产品名/术语时，若没对照过画面文字，明确说"这些词未核实"

## 已知边界

| 边界 | 说明 |
|---|---|
| 需要登录/付费的视频 | 取不到播放地址，只能让用户提供本地文件 |
| 直播回放 | 视同普通视频，但时间戳可能不准 |
| 多 P 视频 | `fetch --page N` 指定；默认第 1 P |
| 无音轨 | `frames` 仍可用 |
| 超长视频 | 顺序解码约 2500 帧/秒（852×480），43 分钟约 30 秒 |
| 中文字幕烧录在画面里 | ASR 与字幕可能不一致；以画面为准时看原图 |

## 输出给用户时的格式建议

```markdown
## 视频内容
（按时间轴的组织，而非逐句转录）

## 画面里看到的
- 03:00 总纲图：……
- 18:00 演示：……

## 转写可信度
判定：转写可信 / 有 N 处可疑
可能听错：Hermes（转写为"爱马仕"）、Obsidian（"黑钥匙"）……
```
