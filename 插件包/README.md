# 插件包

> 本目录预留给 **DSH 插件**（npm 包形态）。
> 目前为空 —— 因为还没遇到"必须做成插件"的需求。

---

## 技能 vs 插件：什么时候才该做插件

DSH 的两种扩展方式，门槛差很多。**能用技能解决的事，不要做成插件。**

| 需求 | 技能够用 | 必须插件 |
|---|---|---|
| 注册一个原生工具（Agent 直接调用） | ❌ | ✅ |
| 常驻后台服务（长连接、监听端口） | ❌ | ✅ |
| 前端界面（面板、按钮、设置页） | ❌ | ✅ |
| 生命周期钩子（启动时执行） | ❌ | ✅ |
| npm 版本管理与自动更新 | ❌ | ✅ |
| 一套流程 + 跑 CLI 脚本读输出 | ✅ | — |

**判断口诀**：如果核心逻辑是"跑个脚本拿结果"，那就是技能。
如果核心逻辑是"一直活着，随时被调用"，那才是插件。

---

## 如果要做插件，目录长这样

```
插件包/<插件名>/
├── package.json        ← 必需，含 dsh.bundle.patch
├── cordis.patch.yml    ← 必需，声明插入哪些插件行
├── lib/index.js        ← 插件代码（注册工具 / 服务 / UI）
├── README.md
└── LICENSE
```

`package.json` 关键字段：

```json
{
  "name": "dsh-my-plugin",
  "version": "0.1.0",
  "main": "lib/index.js",
  "dsh": {
    "bundle": { "patch": "./cordis.patch.yml" }
  }
}
```

安装（用户侧）：

```powershell
# 走插件市场，或在 profile 里手动装
```

或在 DSH 里用 `plugin_manager` 安装到当前 profile。

---

## 上架社区索引

两个索引源每日同步 GitHub，**不需要提交 PR**：

| 索引 | 收录方式 |
|---|---|
| [Awesome DSH Plugin](https://awesome-dsh-plugin.com/) | 给仓库打 `dsh-plugin` topic |
| [dshfind](https://dshfind.com/) | 同上 |

---

## 已知的第三方插件参考

评估插件时值得看一眼的：

| 插件 | 形态 | 备注 |
|---|---|---|
| [dsh-doyourweb](https://github.com/SheepofSheep/dsh-doyourweb) | 插件 + Chrome 扩展 | 操作你已登录的真实浏览器标签页 |
| [@anweat/dsh-browser](https://www.npmjs.com/package/@anweat/dsh-browser) | 插件 | 自带 Playwright/Patchright |
| [video-watch-plus](https://github.com/xinhailaopo/video-watch-plus) | **技能**（不是插件） | 视频理解，值得参考它的方法论 |
