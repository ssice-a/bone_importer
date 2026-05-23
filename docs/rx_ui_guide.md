# RX Export UI Guide / RX 导出 UI 指南

This guide records the intended user workflow for RX Export v3. The goal is to
make authoring feel like the Blender scene: what the user places in an IB
collection is what the runtime package draws.

本指南记录 RX Export v3 的目标使用流程。核心原则是所见即所得：用户放进
IB 集合里的可见网格，就是运行时包真正绘制的网格。

## Core Mental Model / 核心心智模型

```text
Set Capture Manifest, then Create/Sync RX Collections
-> put visible meshes under IB collections
-> choose Export Type
-> optionally export mesh buffers
-> Export
```

| Term / 术语 | Meaning / 含义 |
| --- | --- |
| IB Collection / IB 集合 | One child collection named `<hash>-<match_index_count>-<first_index>`. It is one runtime DrawPart context. / 一个命名为 `<hash>-<match_index_count>-<first_index>` 的子集合，对应一个运行时 DrawPart。 |
| Visible Source Mesh / 可见源网格 | The mesh the user actually wants to export and see in Blender. Mesh buffers, UVs, normals, tangents, shape keys, and INI draw comments come from it. / 用户真正想导出的网格。Mesh 缓冲、UV、法线、切线、形态键和 ini 绘制注释都以它为准。 |
| Slot Adapter / 槽位适配器 | Optional helper mesh used only to supply game-compatible numeric vertex groups for final `vb2`. It should not remain as the visible export object. / 可选辅助网格，只负责提供游戏可识别的数字顶点组来写最终 `vb2`，不应作为用户可见导出物体保留。 |
| Draw Segment / 绘制段 | One mesh draw range in the generated INI. The line before `drawindexedinstanced` must name the visible source mesh. / 生成 ini 中的一段 draw。`drawindexedinstanced` 前一行必须注释可见源网格名。 |

## Export Setup / 导出设置

| UI | Meaning / 含义 |
| --- | --- |
| UI Language / 界面语言 | Switch panel labels between Chinese and English. / 切换插件面板中英文显示。 |
| Output Dir / 输出目录 | Folder containing buffers, manifests, generated ini, and hlsl. / 存放缓冲、清单、生成 ini 和 hlsl 的目录。 |
| Capture Manifest / 捕获清单 | Explicit `capture_manifest.json` path used for game vertex layouts. / 显式选择 `capture_manifest.json`，用于读取游戏顶点布局。 |
| RX Export Collection / RX 导出集合 | Root collection whose children are IB Collections. / 根集合，其子集合是各个 IB 集合。 |
| Create/Sync RX Collections / 创建/同步 RX 集合 | Create the root and IB collections automatically from the current runtime manifest, or from `Capture Manifest` on first setup. Users only drag meshes into the generated IB collections. / 从运行时清单自动创建；首次使用时从 `Capture Manifest` 自动创建 IB 集合。用户只需要把物体拖进对应 IB 集合。 |
| Export Type / 导出类型 | `Full RX Package`, `Bone Payload Only`, `Morph Payload Only`, or `INI Only`. / 完整包、仅骨骼、仅形态键或仅 ini。 |
| Export Mesh / 导出 Mesh | Default enabled. Refresh mesh buffers when the chosen export needs draw buffers. / 默认开启。导出类型需要绘制缓冲时刷新 Mesh 缓冲。 |

## UV And Coordinates / UV 与坐标

UV export is an adapter from Blender-correct UVs back to game-format UVs.

UV 导出是把 Blender 里显示正确的 UV 还原成游戏能识别的格式。

Rules / 规则：

- `bi_export_uv_flip_v` is the explicit source of truth for V flipping. / `bi_export_uv_flip_v` 是 V 翻转的显式真值。
- Imported metadata such as `bmc_uv_flip_v` is fallback only. / `bmc_uv_flip_v` 这类导入插件元数据只作为旧场景 fallback。
- External meshes that look correct in Blender still use the same game-format export adapter. / 外部模型只要在 Blender 中显示正确，导出时同样走游戏格式适配。
- Do not fix UV issues by editing textures or guessing material state first; compare exported `vb1` against captured game `vb1`. / 不要优先通过改贴图或猜材质修 UV，先把导出的 `vb1` 与游戏捕获的 `vb1` 对比。

## Timeline / 时间轴

| UI | Meaning / 含义 |
| --- | --- |
| Clip / 动作 | Logical clip name written to the Runtime Manifest. / 写入运行时清单的动作名。 |
| Frame Start / End / Step / 起止帧与步长 | Blender source frame sampling range. Defaults to the scene range. / Blender 源帧采样范围，默认使用场景范围。 |
| Source FPS / 源 FPS | Source action FPS. Defaults to scene FPS. / 源动作帧率，默认场景帧率。 |
| Target Game FPS / 目标游戏 FPS | Runtime present rate, default 120. / 游戏运行帧率，默认 120。 |
| Playback Speed / 播放倍速 | Intuitive multiplier: `2.0` means 2x, `0.5` means half speed. / 直觉倍速：`2.0` 是两倍速，`0.5` 是半速。 |

## Action Bank / 动作库

The Action Bank panel manages clips that already exist in the current output
folder. It edits the runtime manifest and local action payload buffers directly,
so it is meant for package maintenance after one or more exports.

动作库面板用于管理当前输出目录里已经导出的动作。它会直接修改运行时清单和
本地动作数据缓冲，因此主要用于已有一个或多个导出结果之后的维护。

| UI | Meaning / 含义 |
| --- | --- |
| Action / 动作 | Select an exported clip by index and name. / 按序号和名称选择已经导出的动作。 |
| Use For Overwrite / 用于覆盖导出 | Copy the selected action name and clip id back to the normal export fields, so the next export overwrites that clip instead of appending a new one. / 把选中动作的名称和 clip id 写回普通导出字段，下一次导出会覆盖该动作，而不是追加新动作。 |
| New Name / 新名称 | Target name for rename. / 重命名目标名称。 |
| Rename / 重命名 | Rename the selected clip in the manifest, then regenerate INI. Payload row order is unchanged. / 只修改清单中的动作名称并重新生成 INI，不改变 payload 行顺序。 |
| Delete / 删除 | Remove the selected clip, compact clip indices, rewrite shared timeline, bone payloads, morph payloads, and regenerate INI. Deleting the last remaining action is blocked. / 删除选中动作，压缩 clip index，重写共享时间轴、骨骼数据、形态键数据并重新生成 INI；禁止删除最后一个动作。 |

Recommended workflow:

推荐流程：

- To replace an old action: select it in Action Bank, click `Use For Overwrite`, then export the current Blender action.
- To rename an action: select it, fill `New Name`, click `Rename`.
- To remove an unwanted action: select it, click `Delete`, then test the package once because all following clip indices are compacted.

## Collection Rules / 集合规则

- Put only the mesh objects you intend to export under an IB Collection. / IB 集合内只放真正要导出的网格。
- If an exported mesh needs numeric game groups, use a Slot Adapter internally or through advanced settings. / 如果导出网格需要数字游戏顶点组，用 Slot Adapter 在内部或高级设置中适配。
- The visible mesh remains the morph source and INI draw identity. / 可见网格仍然是形态键来源和 ini draw 身份。
- Explicit `partNN` child collections are allowed, but do not mix direct meshes and explicit `partNN` children in the same IB Collection. / 可以使用显式 `partNN` 子集合，但同一 IB 集合中不要混用直接网格和显式 `partNN`。
- If any mesh buffers are exported for an IB Collection, the original game draw is skipped. / 如果某个 IB 集合导出了 Mesh 缓冲，该 IB 的原始游戏 draw 会被跳过。

## Current RX Validation Scene / 当前 RX 验证场景

The current validation package at `E:\XXMI\EFMI\Mods\RX` uses:

当前 `E:\XXMI\EFMI\Mods\RX` 验证包使用：

```text
RX Export Collection
  e78c7068-10590-0
    000_面
  2009f0d6-1356-0
    005_睫眉

RX Slot Adapters  (hidden)
  RXEXP_e78c7068-10590-0_000_面.001
  RXEXP_2009f0d6-1356-0_005_睫眉.001

RX Runtime DrawParts  (hidden/internal)
  1377f2c3-59679-0
    1377f2c3-59679-0
  ...
```

Rules for this scene:

此场景规则：

- `000_面` and `005_睫眉` are the visible source meshes and shape-key sources. / `000_面` 与 `005_睫眉` 是可见源网格，也是形态键来源。
- `RXEXP_*` meshes only provide numeric slot weights for exported `vb2`. / `RXEXP_*` 只负责给导出的 `vb2` 提供数字槽位权重。
- `RXEXP_*` meshes must stay linked in hidden `RX Slot Adapters`; do not delete or orphan them. / `RXEXP_*` 必须挂在隐藏的 `RX Slot Adapters`，不要删除或孤儿化。
- `RX Runtime DrawParts` is internal and hidden; users should drag meshes into `RX Export Collection` IB children instead. / `RX Runtime DrawParts` 是隐藏内部集合；用户应把网格拖到 `RX Export Collection` 的 IB 子集合下。
- Direct meshes under an IB child are implicit `part00`; explicit `partNN` collections are only allowed inside an IB child. / IB 子集合下的直接网格才是隐式 `part00`；显式 `partNN` 只允许出现在 IB 子集合内部。
- `Capture Manifest` should point to `E:\XXMI\EFMI\Mods\lxi\capture_manifest.json` for this validation package. / 此验证包的 `Capture Manifest` 指向 `E:\XXMI\EFMI\Mods\lxi\capture_manifest.json`。
- The exported package should not contain `RXEXP_` or `RXTMP_RX_` in `export_manifest.json`, `rx_export_manifest.json`, or `rxanimin.ini`. / 导出后的 `export_manifest.json`、`rx_export_manifest.json`、`rxanimin.ini` 不应出现 `RXEXP_` 或 `RXTMP_RX_`。

Automation command:

自动化导出命令：

```powershell
$env:RX_CAPTURE_MANIFEST='E:\XXMI\EFMI\Mods\lxi\capture_manifest.json'
& 'g:\blender5.0\blender.exe' --background 'E:\XXMI\EFMI\Mods\RX\rx_test_scene.blend' --python 'e:\vscode\bone_importer\scripts\export_rx_test.py'
```

## Validation Checklist / 校验清单

Before testing in game, check:

进入游戏前建议检查：

- `rx_export_manifest.json` names the visible meshes, such as `000_面` and `005_睫眉`. / `rx_export_manifest.json` 中应显示可见物体名，例如 `000_面` 与 `005_睫眉`。
- `export_manifest.json` should also use visible mesh names, not `RXTMP_RX_*` temporary names. / `export_manifest.json` 也应使用可见物体名，而不是 `RXTMP_RX_*` 临时名。
- `rxanimin.ini` has `; draw segment: <object>` immediately before each replacement draw. / `rxanimin.ini` 每个替换 draw 前都有 `; draw segment: <object>`。
- Eyelash or PNTA40 meshes should compare their exported `vb1` UV range against the captured source game `vb1`. / 眼睫毛或 PNTA40 网格应把导出的 `vb1` UV 范围与游戏原始捕获的 `vb1` 对比。
- The RX Geometry Export collection should show the intended visible meshes after export. / 导出后 RX Geometry Export 集合应显示真正要导出的可见网格。
