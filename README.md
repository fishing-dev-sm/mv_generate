# pi-fleet-wm

MV 生成工作流手册（脱敏版）。从素材到成片的本地全链路 MV 生产线，一份面向 agent 的照做型操作手册。

## 文档

- [`mv_generate.md`](./mv_generate.md) —— MV 全流程手册：13 步「照做版」+ 写词 / 作曲 / 音频分析 / 分镜 / Plate 抽卡 / H3 出片 / 口型闭环 / 视觉层设计 / 渲染合成 / QC 的完整口径与踩坑经验。

> 注：原文的姊妹文档 `mv_render.md`（引擎 / 分窗并行 / 编码 / QC / 排障）已废弃，未随本仓库发布；
> `mv_generate.md` 正文中对它的引用属历史遗留，可忽略。

## 脱敏说明

本文档已脱敏——原稿中与本地环境强相关的路径、主机、账号、内网 IP 均替换为占位符，使用前请按自己的环境替换。

| 占位符 | 原含义 | 替换成 |
|---|---|---|
| `{{IMAGE_HOST}}` | 文生图 ComfyUI 服务所在主机（内网 IP） | 你的 t2i / edit 服务地址 |
| `{{H3_HOST}}` | 视频 + 音乐生成机（SSH 隧道） | 你的 H3 / Music3 主机 |
| `{{LOCAL_MACHINE}}` | 本地无 GPU 剪辑机 | 你的本地机名 |
| `{{FIGMA_ACCOUNT}}` | Figma MCP 授权账号邮箱 | 有权限的 Figma 账号 |
| `{{FIGMA_ACCOUNT_ALT}}` | 无权限的备用账号邮箱 | 对应账号 |
| `{{FIGMA_FILE_KEY}}` | Figma 设计稿 fileKey | 你的 Figma 文件 key |

路径约定（脚本 / 命令相对这些目录）：

| 路径 | 含义 |
|---|---|
| `~/mv-workspace/` | MV 工作区（正文所有脚本路径相对它） |
| `~/mv-docs/` | 上游方法论 PDF、设计规范转述等文档目录 |
| `~/comfyui/` | ComfyUI 安装目录 |
| `~/staging/` | 加速补丁回退清单存档目录 |
