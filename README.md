# Bone Importer

用于 `VS-T0` 代理骨架导入导出的独立 Blender 插件。

## 目录结构
- `__init__.py`: 插件入口与注册
- `constants.py`: 常量
- `properties.py`: Blender 属性
- `operators.py`: 操作器入口
- `panel.py`: 侧边栏面板
- `core/layout.py`: 缓冲布局与矩阵打包
- `core/proxy.py`: 代理骨架生成与 bind 捕获
- `core/context.py`: 对象解析与上下文辅助
- `core/export.py`: 调色板导出与 patch 计划
- `core/importer.py`: 调色板导入到骨架
- `core/io.py`: 文件读写
- `core/transform.py`: 游戏与 Blender 矩阵转换
- `core/workflow.py`: 高层流程编排
- `core/models.py`: 结果模型

## 当前职责
- 按数字顶点组生成代理骨架
- 为代理骨架绑定 `part_id`
- 导入 `vs-t0` 调色板到代理骨架
- 导出代理骨架到 `vs-t0` 调色板
- 支持单选或多选代理骨架批量导入导出
- 导出时按 `part_id` 只写对应部位窗口

## 默认布局
- 保留行数: `3`
- 部位步长: `1000`
- `part_id` 从 `0` 开始
- `part_base = part_id * 1000`
- 当前窗口: `part_base .. part_base + 999`
- 上一帧窗口: `part_base + 100000 .. part_base + 100999`
- 单骨 3 行: `base + 3 + slot_id * 3 + {0,1,2}`

## 坐标转换
- 网格默认视为已经处于 Blender 中的正确站立空间
- 代理骨架直接按该网格生成，不额外改编辑态坐标
- 导入时对最终蒙皮矩阵做统一的游戏到 Blender 变换
- 导出时应用严格逆变换回到游戏空间

## Bind 行为
- 不再提供手动 `Capture Bind`
- 导入前会自动重抓当前代理骨架的 bind
- 导出前也会自动重抓当前代理骨架的 bind
- 因此编辑模式改骨后，不需要手动再点一次捕获

## Blender 工作流
1. 选中一个或多个带数字顶点组的 mesh，例如 `0`、`1`、`2`
2. 点击 `Generate Proxy Rig`
3. 给生成出的代理骨架设置 `Part Id`
4. 在姿态模式下调整或制作动画
5. 点击 `Export Palette` 导出当前选中代理骨架对应的部位
6. 点击 `Import Palette` 把调色板重新应用回代理骨架

## 导出规则
- 单选时只导出当前活动代理骨架对应的部位
- 多选时把所有选中的代理骨架按各自 `part_id` 合并导出
- 导出文件只 patch 被选中的部位窗口，不会主动改其他部位

## 说明
- `slot_id = 顶点组名`
- 导出矩阵公式为 `M_pose * inverse(M_bind)`
- 导出层与矩阵读写层分离，方便后续复用
