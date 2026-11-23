# DSH 能力包

> 给 [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness) 用的能力合集。
> 分两类：**技能包**（纯文件，复制即用）和 **插件包**（npm 包，需要安装）。

---

## 这是什么

DeepSeek Harness（DSH）有两种扩展方式，本仓库按这两类分目录维护：

| 目录 | 类型 | 安装方式 | 适合什么 |
|---|---|---|---|
| **[`技能包/`](技能包/)** | Skill（技能） | 复制到 `~/.dsh/skills/` 即可 | 指路 + 脚本：让 Agent 学会一套流程 |
| **[`插件包/`](插件包/)** | Plugin（插件） | `npm install` / 插件市场 | 注册工具、常驻服务、前端界面 |

**一句话区分**：能用"说明文档 + 脚本"解决的就做技能；必须注册原生工具或需要界面的才做插件。

---

## 技能包

| 技能 | 作用 | 依赖 |
|---|---|---|
| [**video-watch**](技能包/video-watch/) | 让 Agent 真的"看"视频：转写 + 抽帧 + 可信度判定 | Python + PyAV + Pillow + faster-whisper |

### 安装一个技能

```powershell
git clone https://github.com/Richardo-X/dsh-capability-pack.git
Copy-Item -Recurse "dsh-capability-pack\技能包\video-watch" "$env:USERPROFILE\.dsh\skills\video-watch"
```

只想取其中一个（仓库不大，上面那种就够；这里给不想下整个仓库的）：

```powershell
git clone --depth 1 --filter=blob:none --sparse https://github.com/Richardo-X/dsh-capability-pack.git
cd dsh-capability-pack
git sparse-checkout set "技能包/video-watch"
```

技能放在下面这些位置，DSH 会自动发现（改完无需重启）：

| 路径 | 生效范围 |
|---|---|
| `~/.dsh/skills/` | **所有项目** |
| `<项目>/.dsh/skills/` | 仅该项目 |

> 技能装好后，让 Agent「用 video-watch 看这个视频」即可；它也可以自己按 `SKILL.md` 的流程调用脚本。

---

## 插件包

目前**还没有**。占位说明见 [`插件包/README.md`](插件包/README.md)，里面记了"什么情况下才该做插件"。

---

## 许可

MIT。各技能/插件内部如另有声明，以内部为准。

---

## 相关

- DSH 官方：<https://github.com/deepseek-ai/deepseek-harness>
- 社区插件索引：
  - [Awesome DSH Plugin](https://awesome-dsh-plugin.com/)
  - [dshfind](https://dshfind.com/)
- 技能开放标准：[agentskills.io](https://agentskills.io)
