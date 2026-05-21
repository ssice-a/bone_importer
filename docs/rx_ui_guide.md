# RX Export UI Guide / RX 导出 UI 说明

## Export Setup / 导出设置

| UI | 含义 |
| --- | --- |
| UI Language / 语言 | Switches panel labels between Chinese and English. / 切换插件面板的中英文显示。 |
| Output Dir / 输出目录 | Folder containing RX buffers, manifest, generated ini, and hlsl. / RX 缓冲、清单、ini 和 hlsl 的输出目录。 |
| Capture Manifest / 捕获清单 | External geometry layout source used when geometry export is enabled. / 导出几何时读取的游戏顶点布局清单。 |
| RX Export Collection / RX 导出集合 | Root collection whose child collections are IB regions. / 承载导出内容的根集合，子集合对应 IB。 |
| Create/Sync RX Collections / 创建/同步 RX 集合 | Creates the root collection and IB child collections from `rx_export_manifest.json`, then links found scene objects directly under each IB collection as implicit `part00`. / 根据 `rx_export_manifest.json` 创建根集合和 IB 子集合，并把场景内能找到的物体直接链接到 IB 集合下，作为隐式 `part00`。 |
| Export Type / 导出类型 | Chooses whether this run exports full package, bone-only, morph-only, or ini-only. / 选择本次导出完整包、仅骨骼、仅形态键或仅 ini。 |
| Export Geometry / 导出几何 | Enables geometry refresh when the selected export type can produce geometry. / 在导出类型允许时刷新几何数据。 |

## Timeline / 时间轴

| UI | 含义 |
| --- | --- |
| Clip / 动作 | Logical animation clip name used by manifest and generated ini. / 写入清单和 ini 的动作名。 |
| ID | Stable numeric clip id. / 稳定的动作数字 ID。 |
| Start / End / 开始 / 结束 | Blender source frame range to sample. / Blender 采样帧范围。 |
| Frame Step / 采样步长 | Source-frame interval between exported samples. / 导出采样间隔。 |
| Source FPS / 源 FPS | Source animation FPS; 0 follows the Blender scene FPS. / 源动画帧率，0 表示使用场景帧率。 |
| Target Game FPS / 目标游戏 FPS | Runtime Present rate used to derive playback step, default 120. / 游戏运行帧率，默认 120。 |
| Playback Speed / 播放倍速 | Intuitive multiplier: 2.0 is double speed, 0.5 is half speed. / 直觉倍速，2.0 为两倍速，0.5 为半速。 |

## IB Preview / IB 预览

| UI | 含义 |
| --- | --- |
| IB Collections / IB 集合 | Count of IB child collections under the root. / 根集合下的 IB 子集合数量。 |
| Parts / Part 数 | Count of export parts, including generated splits. / 导出 part 数，包括自动拆分。 |
| Draw Segments / 绘制段 | Mesh segments that the planner will consider. / 规划器会处理的网格段数。 |
| Geometry Required / 需要导出几何 | Segments that require replacement geometry or pre-deform output. / 需要替换几何或预变形输出的段。 |
| Source Skin / 源模型蒙皮 | Segments using game/source numeric slots as final skin. / 最终使用游戏数字槽位蒙皮的段。 |
| Own Skin / 自有骨骼蒙皮 | Segments using their own armature palette. / 使用自有骨架调色板的段。 |
| Morph / 形态键 | Segments with morph payload enabled. / 启用形态键数据的段。 |
| Pre-Skin Bone / 骨骼预蒙皮 | Segments with bone pre-skin enabled. / 启用骨骼预蒙皮的段。 |

## Active Mesh Advanced / 当前网格高级设置

| UI | 含义 |
| --- | --- |
| Final Skin / 最终绘制路线 | Auto/Source Game/Own final palette route. / 自动、源游戏槽位或自有骨骼的最终蒙皮路线。 |
| Force Geometry / 强制几何 | Forces replacement geometry export even if route analysis would keep the original draw. / 即使可保留原 draw，也强制导出几何。 |
| Pre-Skin Bone / 骨骼预蒙皮 | Runs a compute pre-skin step before final source-game skinning. / 在最终源游戏蒙皮前先做一次 CS 骨骼预蒙皮。 |
| Morph / 形态键 | Enables morph payload for this mesh. / 为当前网格启用形态键数据。 |
| Runtime Adapters / 运行时适配 | Per-mesh match priority, CB1 profile, layout, mirror, and UV adapters. / 每网格的优先级、CB1、布局、镜像和 UV 适配。 |
