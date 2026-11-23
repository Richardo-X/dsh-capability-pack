# -*- coding: utf-8 -*-
"""
video-watch —— 让 agent 真的"看"视频：听声音 + 看画面

设计原则
--------
1. 不依赖任何外部二进制：PyAV 内置 FFmpeg 库，Pillow 拼图版。
   （不装 ffmpeg.exe / ImageMagick，避开 WindowsApps 权限与 GBK 路径问题）
2. B 站直取：给 BV 号即可，无需登录、无需先下载视频。
3. 只让模型看"真正有信息量"的帧：顺序解码一趟，按时间点抓拍，
   拼成带时间戳的图版，读字时再单张看原图。
4. 转写给出可信度判定，且 no_speech 语义不被读反。

子命令
------
  fetch     BV号/链接 → 下载音频（+可选视频）+ meta.json
  probe     读媒体信息（时长/分辨率/帧率/编码）
  transcribe 音频 → transcript.txt / .srt / segments.json（含 no_speech、logprob）
  verify    segments.json + 音频 → 可信度判定 + 可疑专有名词段
  frames    视频 + 时间点 → 单帧 PNG + 带时间戳图版
  all       一条龙：fetch → transcribe → frames

用法见 SKILL.md。
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.request

BILI_UA = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/131.0 Safari/537.36",
    "Referer": "https://www.bilibili.com/",
}

# ---------------------------------------------------------------- 工具

def die(msg, code=1):
    print(f"[vw] 错误: {msg}", file=sys.stderr)
    sys.exit(code)


def log(msg):
    print(f"[vw] {msg}", flush=True)


def ensure_dir(p):
    os.makedirs(p, exist_ok=True)
    return p


def human(n):
    return f"{n/1048576:.1f} MB" if n >= 1048576 else f"{n/1024:.0f} KB"


def ts_mmss(x):
    x = max(0, int(x))
    return f"{x//60:02d}:{x%60:02d}"


def ts_hms(x):
    x = max(0, int(x))
    return f"{x//3600:02d}:{x%3600//60:02d}:{x%60:02d}"


def srt_time(x):
    h = int(x // 3600); m = int(x % 3600 // 60); s = int(x % 60)
    ms = int(round((x - int(x)) * 1000))
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def http_get(url, headers=None, timeout=60):
    req = urllib.request.Request(url, headers=headers or {})
    return urllib.request.urlopen(req, timeout=timeout)


def http_json(url, headers=None, timeout=30):
    with http_get(url, headers, timeout) as r:
        return json.loads(r.read().decode("utf-8", "ignore"))


def download(url, dst, headers=None, timeout=180, quiet=False):
    ensure_dir(os.path.dirname(dst) or ".")
    n = 0
    t = time.time()
    with http_get(url, headers, timeout) as r, open(dst, "wb") as f:
        while True:
            b = r.read(1 << 18)
            if not b:
                break
            f.write(b)
            n += len(b)
    if not quiet:
        dt = max(time.time() - t, 0.001)
        log(f"下载 {os.path.basename(dst)}  {human(n)} / {dt:.1f}s = {n/1048576/dt:.1f} MB/s")
    return n


# ---------------------------------------------------------------- B 站

BV_RE = re.compile(r"(BV[0-9A-Za-z]{10})")


def parse_bv(arg):
    m = BV_RE.search(arg)
    if not m:
        die(f"无法从 {arg!r} 里识别 BV 号（形如 BV1xx411c7mD）")
    return m.group(1)


def bili_view(bv):
    d = http_json(f"https://api.bilibili.com/x/web-interface/view?bvid={bv}", BILI_UA)
    if d.get("code") != 0:
        die(f"取视频信息失败: {d.get('code')} {d.get('message')}")
    v = d["data"]
    return {
        "bvid": v["bvid"],
        "aid": v["aid"],
        "cid": v["cid"],
        "title": v["title"],
        "duration": v["duration"],
        "uploader": v["owner"]["name"],
        "pages": [(p["page"], p["part"], p["cid"], p["duration"]) for p in v.get("pages", [])],
    }


def bili_playurl(bv, cid):
    q = (f"https://api.bilibili.com/x/player/playurl?bvid={bv}&cid={cid}&fnval=16&fourk=1")
    d = http_json(q, BILI_UA)
    if d.get("code") != 0:
        die(f"取播放地址失败: {d.get('code')} {d.get('message')}（可能有区域/会员限制）")
    dash = d["data"].get("dash") or {}
    return dash.get("audio") or [], dash.get("video") or []


def pick_audio(audio_list):
    if not audio_list:
        return None
    return sorted(audio_list, key=lambda x: -x.get("id", 0))[0]


QUALITY_RANK = {"low": 360, "mid": 480, "high": 720, "max": 1080}


def pick_video(video_list, quality="mid"):
    if not video_list:
        return None
    cap = QUALITY_RANK.get(quality, 480)
    cand = [v for v in video_list if (v.get("height") or 0) <= cap] or video_list
    avc = [v for v in cand if "avc1" in (v.get("codecs") or "")] or cand
    return sorted(avc, key=lambda x: ((x.get("height") or 0), (x.get("bandwidth") or 0)), reverse=True)[0]


def cmd_fetch(a):
    bv = parse_bv(a.target)
    out = ensure_dir(a.dir or f"./vw_{bv}")
    meta = bili_view(bv)
    log(f"{meta['title']}  ·  {meta['uploader']}  ·  {ts_hms(meta['duration'])}")

    cid = meta["cid"]
    if a.page and meta["pages"]:
        hit = [p for p in meta["pages"] if p[0] == a.page]
        if hit:
            cid = hit[0][2]

    audios, videos = bili_playurl(bv, cid)
    result = dict(meta, cid=cid, audio=None, video=None)

    au = pick_audio(audios)
    if au:
        p = os.path.join(out, "audio.m4s")
        dl = download(au["baseUrl"], p, BILI_UA)
        result["audio"] = {"path": p, "id": au.get("id"), "codecs": au.get("codecs"), "bytes": dl}
    else:
        log("警告：没有可用的音频流")

    if not a.audio_only:
        vd = pick_video(videos, a.quality)
        if vd:
            p = os.path.join(out, "video.m4s")
            dl = download(vd["baseUrl"], p, BILI_UA)
            result["video"] = {"path": p, "width": vd.get("width"), "height": vd.get("height"),
                               "codecs": vd.get("codecs"), "bytes": dl}
        else:
            log("警告：没有可用的视频流")

    with open(os.path.join(out, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    log(f"输出目录: {out}")
    print(json.dumps({"dir": out, "audio": (result["audio"] or {}).get("path"),
                      "video": (result["video"] or {}).get("path"),
                      "duration": meta["duration"], "title": meta["title"]}, ensure_ascii=False))


# ---------------------------------------------------------------- 媒体信息

def make_container(path, headers=None, timeout=60):
    import av
    if headers:
        return av.open(path, options={"headers": headers}, timeout=timeout)
    return av.open(path)


def cmd_probe(a):
    import av
    headers = "Referer: https://www.bilibili.com/\r\nUser-Agent: Mozilla/5.0\r\n" \
        if a.target.startswith("http") else None
    c = make_container(a.target, headers)
    info = {"path": a.target, "duration": (c.duration / 1e6) if c.duration else None}
    if c.streams.video:
        v = c.streams.video[0]
        info.update({"video": {"codec": v.codec_context.name, "width": v.width, "height": v.height,
                               "fps": float(v.average_rate) if v.average_rate else None,
                               "frames": v.frames}})
    if c.streams.audio:
        s = c.streams.audio[0]
        info["audio"] = {"codec": s.codec_context.name, "rate": s.rate, "channels": s.channels}
    c.close()
    print(json.dumps(info, ensure_ascii=False, indent=2))


# ---------------------------------------------------------------- 转写

MODEL_CANDIDATES = [
    os.path.join(os.environ.get("LOCALAPPDATA", ""), "video-watch", "fw-small"),
]


def resolve_model(name_or_path):
    if os.path.isdir(name_or_path):
        return name_or_path
    for p in MODEL_CANDIDATES:
        if p and os.path.isdir(p) and os.path.exists(os.path.join(p, "model.bin")):
            log(f"复用本地模型: {p}")
            return p
    return name_or_path  # 让 faster-whisper 按名字下载


PROPER_NOUN_HINT = ("以下是普通话讲解，可能包含技术术语、产品名、英文缩写"
                    "（如 DeepSeek、Harness、Agent、MCP、GitHub、Claude、Hermes、Obsidian）。")


def run_asr(path, model_dir, lang, vad=True, strict=False, prompt=PROPER_NOUN_HINT):
    from faster_whisper import WhisperModel
    m = WhisperModel(model_dir, device="cpu", compute_type="int8")
    kw = dict(language=lang, beam_size=5, vad_filter=vad, initial_prompt=prompt,
              condition_on_previous_text=False)
    if strict:
        kw.update(no_speech_threshold=1.0, log_prob_threshold=-10.0, compression_ratio_threshold=10.0)
    segs, info = m.transcribe(path, **kw)
    out = []
    for s in segs:
        t = (s.text or "").strip()
        if not t:
            continue
        out.append({"start": round(s.start, 2), "end": round(s.end, 2), "text": t,
                    "no_speech_prob": round(float(getattr(s, "no_speech_prob", 0.0)), 3),
                    "avg_logprob": round(float(getattr(s, "avg_logprob", 0.0)), 3)})
    return out, {"language": getattr(info, "language", None),
                 "duration": getattr(info, "duration", None)}


def cmd_transcribe(a):
    out = ensure_dir(a.out or ".")
    model_dir = resolve_model(a.model)
    log(f"转写中（模型 {model_dir}）…")
    t0 = time.time()
    segs, info = run_asr(a.audio, model_dir, a.lang, vad=True, prompt=a.prompt)
    dt = time.time() - t0
    log(f"完成 {len(segs)} 段 / {dt:.0f}s（音频 {ts_hms(info.get('duration') or 0)}）")

    with open(os.path.join(out, "segments.json"), "w", encoding="utf-8") as f:
        json.dump({"info": info, "segments": segs}, f, ensure_ascii=False, indent=2)

    with open(os.path.join(out, "transcript.txt"), "w", encoding="utf-8") as f:
        for s in segs:
            f.write(f"[{ts_hms(s['start'])}] {s['text']}\n")

    with open(os.path.join(out, "transcript.srt"), "w", encoding="utf-8") as f:
        for i, s in enumerate(segs, 1):
            f.write(f"{i}\n{srt_time(s['start'])} --> {srt_time(s['end'])}\n{s['text']}\n\n")

    # 可疑段：低置信度或模型自认"这里没人说话"
    risky = [s for s in segs if s["avg_logprob"] < -0.8 or s["no_speech_prob"] > 0.6]
    with open(os.path.join(out, "risky.md"), "w", encoding="utf-8") as f:
        f.write("# 需要人工核对的段落\n\n")
        f.write("判据：avg_logprob < -0.8（模型自己不确定）或 no_speech_prob > 0.6（模型认为可能没人说话）。\n")
        f.write("这些位置最可能是**专有名词误听**，建议对照画面字幕或上下文确认。\n\n")
        if not risky:
            f.write("（无）\n")
        for s in risky:
            f.write(f"- `{ts_hms(s['start'])}` logprob={s['avg_logprob']} no_speech={s['no_speech_prob']}\n")
            f.write(f"  - {s['text']}\n")

    print(json.dumps({"dir": out, "segments": len(segs), "elapsed": round(dt),
                      "risky": len(risky),
                      "transcript": os.path.join(out, "transcript.txt")}, ensure_ascii=False))


# ---------------------------------------------------------------- 可信度判定（修正版）

def cmd_verify(a):
    data = json.load(open(a.segments, encoding="utf-8"))
    vad_segs = data["segments"]
    log("强制模式复跑（关闭 VAD、拆掉所有阈值）以做对照…")
    forced, _ = run_asr(a.audio, resolve_model(a.model), a.lang, vad=False, strict=True)

    n_vad, n_forced = len(vad_segs), len(forced)
    ftexts = [s["text"] for s in forced]
    uniq = len(set(ftexts))
    ratio = (uniq / n_forced) if n_forced else 0.0
    avg_ns = (sum(s["no_speech_prob"] for s in forced) / n_forced) if n_forced else 0.0

    reasons = []
    # no_speech_prob 语义：**越高越可能没人说话**（0~1）
    if n_vad == 0 and n_forced == 0:
        verdict = "无人声：两种模式都无输出"
        reasons.append("VAD 与强制模式均未产出文本")
    elif n_vad == 0 and n_forced and uniq == 1 and n_forced >= 2:
        verdict = "判定为幻觉：音轨很可能没有人声"
        reasons.append(f"{n_forced} 个互不重叠的时间窗输出完全相同的文本 {ftexts[0]!r}")
    elif n_vad == 0 and n_forced and avg_ns >= 0.6:
        verdict = "判定为幻觉：音轨很可能没有人声"
        reasons.append("VAD 模式没有任何输出（该检测器不依赖语言模型）")
        reasons.append(f"模型自报 no_speech 概率均值 {avg_ns:.2f}，**偏高**说明模型自己认为这里多半没人说话")
    elif n_vad == 0 and n_forced and ratio <= 0.5 and n_forced >= 4:
        verdict = "高度疑似幻觉：全片几乎只落在少数几个模板句上"
        reasons.append(f"{n_forced} 段里只有 {uniq} 种不同文本（unique 比 {ratio:.2f}）")
        reasons.append(f"模型自报 no_speech 概率均值 {avg_ns:.2f}")
    elif n_vad == 0:
        verdict = "倾向无人声：VAD 模式无输出"
        reasons.append(f"强制模式产出 {n_forced} 段，unique 比 {ratio:.2f}，no_speech 均值 {avg_ns:.2f}")
    elif avg_ns >= 0.6:
        verdict = "可疑：VAD 有输出，但模型自报很可能没人说话"
        reasons.append(f"VAD {n_vad} 段 / 强制 {n_forced} 段，unique 比 {ratio:.2f}")
        reasons.append(f"no_speech 均值 **{avg_ns:.2f} 偏高** —— 按语义这是「很可能没人说话」，与 VAD 结论冲突，建议复核")
    elif n_forced and ratio >= 0.8 and n_vad >= 1:
        verdict = "转写可信：有真实语音"
        reasons.append(f"两种模式都能产出语音（VAD {n_vad} 段 / 强制 {n_forced} 段）")
        reasons.append(f"强制模式 {n_forced} 段里有 {uniq} 种不同文本（unique 比 {ratio:.2f}）——幻觉不会这么多样")
        reasons.append(f"no_speech 均值 {avg_ns:.2f}（{'偏低' if avg_ns < 0.4 else '中等'}，即倾向认为有人说话）")
    else:
        verdict = "可判定为人声，但需复核：两种模式分段差异较大"
        reasons.append(f"VAD {n_vad} 段 / 强制 {n_forced} 段，unique 比 {ratio:.2f}，no_speech 均值 {avg_ns:.2f}")

    print(f"  判定：{verdict}")
    for r in reasons:
        print(f"   - {r}")
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            json.dump({"verdict": verdict, "reasons": reasons, "vad_count": n_vad,
                       "forced_count": n_forced, "unique_ratio": round(ratio, 3),
                       "mean_no_speech": round(avg_ns, 3)}, f, ensure_ascii=False, indent=2)
    print(json.dumps({"verdict": verdict, "vad": n_vad, "forced": n_forced,
                      "unique_ratio": round(ratio, 3), "mean_no_speech": round(avg_ns, 3)},
                     ensure_ascii=False))


# ---------------------------------------------------------------- 抽帧

def load_font(size):
    from PIL import ImageFont
    for p in (r"C:\Windows\Fonts\msyh.ttc", r"C:\Windows\Fonts\msyhbd.ttc",
              r"C:\Windows\Fonts\simhei.ttf", "/System/Library/Fonts/PingFang.ttc"):
        try:
            return ImageFont.truetype(p, size)
        except Exception:
            continue
    return ImageFont.load_default()


def build_sheet(tiles, out_path, cols=3, pad=8, label_h=26):
    """tiles: [(PIL.Image, label), ...]"""
    from PIL import Image, ImageDraw
    if not tiles:
        return None
    tw, th = tiles[0][0].size
    rows = (len(tiles) + cols - 1) // cols
    W = cols * tw + (cols + 1) * pad
    H = rows * (th + label_h) + (rows + 1) * pad
    sheet = Image.new("RGB", (W, H), (255, 255, 255))
    d = ImageDraw.Draw(sheet)
    font = load_font(18)
    for i, (im, label) in enumerate(tiles):
        r, c = divmod(i, cols)
        x = pad + c * (tw + pad)
        y = pad + r * (th + label_h + pad)
        d.text((x + 2, y + 2), label, fill=(20, 20, 20), font=font)
        sheet.paste(im, (x, y + label_h))
    sheet.save(out_path)
    return out_path


def grab_frames(video, times, outdir, quality_note=""):
    """顺序解码一趟，按时间点抓拍。返回 [(path, ts, PIL.Image)]"""
    import av
    ensure_dir(outdir)
    times = sorted(set(round(float(t), 2) for t in times))
    got = []
    c = av.open(video)
    vs = c.streams.video[0]
    fps = float(vs.average_rate) if vs.average_rate else 30.0
    idx = 0
    t0 = time.time()
    for fr in c.decode(vs):
        idx += 1
        if fr.pts is None:
            continue
        ts = float(fr.pts * vs.time_base)
        while idx and times and ts >= times[0] - 1.0 / fps:
            im = fr.to_image()
            path = os.path.join(outdir, f"frame_{int(ts//60):02d}m{int(ts%60):02d}s.png")
            im.save(path)
            got.append((path, ts, im))
            times.pop(0)
            if not times:
                break
        if not times:
            break
    c.close()
    log(f"抓帧 {len(got)} 张（解码 {idx} 帧 / {time.time()-t0:.1f}s）{quality_note}")
    return got


def cmd_frames(a):
    out = ensure_dir(a.out or ".")
    if a.times:
        times = [float(x) for x in a.times.replace("，", ",").split(",") if x.strip()]
    elif a.auto:
        import av
        c = av.open(a.video)
        dur = (c.duration / 1e6) if c.duration else 0
        c.close()
        if not dur:
            die("无法读取视频时长，请改用 --times")
        step = dur / a.auto
        times = [step * (i + 0.5) for i in range(a.auto)]
    else:
        die("需要 --times \"180,600\" 或 --auto N")

    got = grab_frames(a.video, times, out)
    for line in [f"{ts_hms(ts)} -> {p}" for p, ts, _ in got]:
        print(line)
    if got and a.sheet:
        tiles = [(im, ts_hms(ts)) for _, ts, im in got]
        sp = os.path.join(out, "sheet.png")
        build_sheet(tiles, sp, cols=a.cols)
        log(f"图版: {sp}")
        print(json.dumps({"sheet": sp, "count": len(got)}, ensure_ascii=False))


# ---------------------------------------------------------------- 放大读字

def cmd_zoom(a):
    """裁切一块区域并放大，专门用来读画面里的小字。"""
    from PIL import Image
    im = Image.open(a.image)
    if a.region:
        try:
            x, y, w, h = [int(v) for v in a.region.replace("，", ",").split(",")]
        except ValueError:
            die('--region 格式应为 "x,y,w,h"（原始像素）')
        x2, y2 = min(x + w, im.width), min(y + h, im.height)
        im = im.crop((max(0, x), max(0, y), x2, y2))
    if a.scale and a.scale != 1:
        im = im.resize((im.width * a.scale, im.height * a.scale), Image.LANCZOS)
    out = a.out or (os.path.splitext(a.image)[0] + "_zoom.png")
    im.save(out)
    log(f"区域 {im.width}x{im.height} -> {out}")
    print(json.dumps({"out": out, "width": im.width, "height": im.height}, ensure_ascii=False))


# ---------------------------------------------------------------- 自检

def cmd_doctor(a):
    """检查运行环境，缺什么、怎么装，一次说清。"""
    import importlib
    import shutil

    rows = []

    # Python
    pv = sys.version.split()[0]
    ok = sys.version_info >= (3, 9)
    rows.append(("Python", f"{pv}  ({sys.platform})", ok, "需要 3.9+"))

    # 必需库
    need = [
        ("av", "PyAV —— 内置 FFmpeg 库，读视频/音频", "pip install av"),
        ("PIL", "Pillow —— 抽帧/拼图版/裁切放大", "pip install Pillow"),
    ]
    for mod, why, how in need:
        try:
            m = importlib.import_module(mod)
            v = getattr(m, "__version__", "")
            rows.append((mod, f"{v}  {why.split(' —— ')[0]}", True, how))
        except Exception:
            rows.append((mod, "未安装", False, how))

    # 可选但强烈建议
    try:
        import faster_whisper as fw
        rows.append(("faster-whisper", f"{getattr(fw, '__version__', '?')}  转写", True, ""))
    except Exception:
        rows.append(("faster-whisper", "未安装（只会抽帧，不能转写）",
                     False, "pip install faster-whisper 'av<19'"))

    # 模型
    model = None
    for p in MODEL_CANDIDATES:
        if p and os.path.isdir(p) and os.path.exists(os.path.join(p, "model.bin")):
            model = p
            break
    if model:
        sz = os.path.getsize(os.path.join(model, "model.bin")) / 1048576
        rows.append(("模型", f"{model}  ({sz:.0f} MB)", True, ""))
    else:
        rows.append(("模型", "未找到（首次运行会下载约 460 MB）", False,
                     f"放到 {MODEL_CANDIDATES[0]}，或联网自动下载"))

    # 网络（B 站 API）
    try:
        d = http_json("https://api.bilibili.com/x/web-interface/view?bvid=BV1o4xg6RE9m",
                      BILI_UA, timeout=8)
        ok = d.get("code") == 0
        rows.append(("B站 API", "可达" if ok else f"异常 code={d.get('code')}", ok, "直连不行时先下好文件再本地处理"))
    except Exception as e:
        rows.append(("B站 API", f"不可达（{type(e).__name__}）", False, "本地文件仍可用"))

    # 输出目录可写
    try:
        probe_dir = os.path.join(os.getcwd(), ".vw_write_test")
        os.makedirs(probe_dir, exist_ok=True)
        os.rmdir(probe_dir)
        rows.append(("输出目录", f"{os.getcwd()} 可写", True, ""))
    except Exception:
        rows.append(("输出目录", "当前目录不可写，请用 --out 指定", False, ""))

    w = max(len(r[0]) for r in rows)
    print()
    for name, detail, ok, how in rows:
        mark = "OK  " if ok else "缺  "
        print(f"  {mark} {name:<{w}}  {detail}")
        if not ok and how:
            print(f"       └─ 解决：{how}")
    bad = [r for r in rows if not r[2]]
    print()
    if not bad:
        print("  必需项就绪：probe / transcribe / frames / zoom / fetch 全部可用")
    else:
        print(f"  {len(bad)} 项待处理（见上面的「解决」）")
    return 0 if not bad else 1


# ---------------------------------------------------------------- 一条龙

def cmd_all(a):
    bv = parse_bv(a.target)
    out = ensure_dir(a.dir or f"./vw_{bv}")
    ns = argparse.Namespace(**vars(a))
    ns.dir = out
    ns.quality = a.quality
    ns.audio_only = False
    cmd_fetch(ns)

    meta = json.load(open(os.path.join(out, "meta.json"), encoding="utf-8"))
    audio = meta["audio"]["path"]
    ns2 = argparse.Namespace(audio=audio, model=a.model, lang=a.lang, out=out, prompt=a.prompt)
    cmd_transcribe(ns2)

    if meta.get("video") and (a.times or a.auto):
        ns3 = argparse.Namespace(video=meta["video"]["path"], times=a.times, auto=a.auto,
                                 out=os.path.join(out, "frames"), sheet=True, cols=3)
        cmd_frames(ns3)


# ---------------------------------------------------------------- CLI

def main():
    ap = argparse.ArgumentParser(prog="vw", description="让 agent 看视频：听声音 + 看画面")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("fetch", help="B站 BV号/链接 → 下载音频(+视频)")
    p.add_argument("target")
    p.add_argument("--dir", "-d")
    p.add_argument("--audio-only", action="store_true")
    p.add_argument("--quality", default="mid", choices=list(QUALITY_RANK))
    p.add_argument("--page", type=int, default=1)
    p.set_defaults(func=cmd_fetch)

    p = sub.add_parser("probe", help="读媒体信息")
    p.add_argument("target")
    p.set_defaults(func=cmd_probe)

    p = sub.add_parser("transcribe", help="音频转文字")
    p.add_argument("audio")
    p.add_argument("--model", default="small")
    p.add_argument("--lang", default="zh")
    p.add_argument("--out", "-o")
    p.add_argument("--prompt", default=PROPER_NOUN_HINT)
    p.set_defaults(func=cmd_transcribe)

    p = sub.add_parser("verify", help="转写可信度判定（no_speech 语义修正版）")
    p.add_argument("segments")
    p.add_argument("audio")
    p.add_argument("--model", default="small")
    p.add_argument("--lang", default="zh")
    p.add_argument("--out", "-o")
    p.set_defaults(func=cmd_verify)

    p = sub.add_parser("frames", help="按时间点抽帧 + 拼图版")
    p.add_argument("video")
    p.add_argument("--times", help='逗号分隔秒数，如 "180,600,1800"')
    p.add_argument("--auto", type=int, help="自动均匀取 N 帧")
    p.add_argument("--out", "-o")
    p.add_argument("--cols", type=int, default=3)
    p.add_argument("--no-sheet", dest="sheet", action="store_false", default=True)
    p.set_defaults(func=cmd_frames)

    p = sub.add_parser("zoom", help="裁切+放大一块区域，用来读小字")
    p.add_argument("image")
    p.add_argument("--region", help='"x,y,w,h" 原始像素；省略则整张')
    p.add_argument("--scale", type=int, default=3)
    p.add_argument("--out", "-o")
    p.set_defaults(func=cmd_zoom)

    p = sub.add_parser("doctor", help="环境自检：缺什么、怎么装")
    p.set_defaults(func=cmd_doctor)

    p = sub.add_parser("all", help="一条龙：fetch + transcribe + frames")
    p.add_argument("target")
    p.add_argument("--dir", "-d")
    p.add_argument("--model", default="small")
    p.add_argument("--lang", default="zh")
    p.add_argument("--quality", default="mid", choices=list(QUALITY_RANK))
    p.add_argument("--times")
    p.add_argument("--auto", type=int)
    p.add_argument("--prompt", default=PROPER_NOUN_HINT)
    p.add_argument("--page", type=int, default=1)
    p.set_defaults(func=cmd_all)

    a = ap.parse_args()
    a.func(a)


if __name__ == "__main__":
    main()
