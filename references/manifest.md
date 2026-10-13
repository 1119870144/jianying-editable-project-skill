# 工程清单

脚本适用于从已拆分素材创建**新单时间线**工程；不将旧工程当输入。依赖 Python 3.10+、`pyJianYingDraft==0.3.0`；Windows 测试使用 Python 3.12。已有项目的虚拟环境可直接复用，无需重装。

清单路径以清单文件所在目录为基准，时间单位秒，端点按帧四舍五入。轨道列表从底到顶，第一条可视轨必须有内容。`mixed` 可包含文字、图片、视频；`audio` 单独管理声音。帧率目前只支持整数。视频默认静音，保留原声需明确 `volume: 1`。

```json
{
  "width": 1080,
  "height": 1920,
  "fps": 30,
  "font": "assets/font.ttf",
  "text_style": {"size": 8, "align": 1, "color": [1, 1, 1]},
  "tracks": [
    {"name": "人物主轨", "type": "mixed", "clips": [
      {"kind": "video", "path": "assets/person.mp4", "start": 0, "end": 12,
       "source_start": 0, "volume": 1}
    ]},
    {"name": "字幕", "type": "mixed", "srt": "captions.srt", "clips": []},
    {"name": "独立素材", "type": "mixed", "clips": [
      {"kind": "text", "text": "可单独修改", "start": 0, "end": 2,
       "clip": {"transform_y": 0.6}},
      {"kind": "image", "path": "assets/card.png", "start": 2, "end": 4,
       "clip": {"scale_x": 0.5, "scale_y": 0.5}},
      {"kind": "video", "path": "assets/unit.mov", "start": 5, "end": 7}
    ]}
  ]
}
```

图像真实时长必须覆盖 `source_start + end - start`；脚本不循环、不拉伸、不中途静默截断。静态图片可以任意设置显示时长。要使用短视频铺底，先明确制作足够长的背景文件。目录重名时拒绝覆盖；失败后检查输出，再使用一个新目录重试。

文字风格合并顺序：全局 `text_style` → 轨道 `text_style` → 片段 `style`。字体可在 `style.font` 覆盖。字体文件必须存在；字体显示名称不能代替字库。样式参数使用库的 `TextStyle`：`size`、`bold`、`color`、`alpha`、`align`、`auto_wrapping` 等，`shadow` 对应 `TextShadow`。字号不是屏幕像素，需在剪映里校对。

`clip` 使用 `ClipSettings` 的 `transform_x/y`、`scale_x/y`、`rotation`、`alpha`、`flip_horizontal/vertical`。本工作流画布像素位置转为 `x=(px-W/2)/(W/2)`，`y=(H/2-py)/(H/2)`。字幕的实际视觉中心仍受字形和行高影响。

可视片段可写原生关键帧，例如：

```json
"keyframes": [
  {"property": "position_x", "time": 0, "value": -0.2},
  {"property": "position_x", "time": 0.3, "value": 0}
]
```

`time` 是相对片段开头的秒数，`property` 使用库的 `KeyframeProperty` 名称。蒙版、复杂转场、富文本逐字色、变速和嵌套工程不在此清单构建器范围内，需要单独适配并在新测试稿验证。

SRT 保留多行文字和全部 cue，不虚构逐字时间。不支持 SRT 定位扩展；语义不完整、同一轨道 cue 重叠时直接报错。需要重叠字幕应分轨。完整 SRT 随素材复制。

`--compact` 仅压缩本脚本新建的无轨道效果轨道。压缩后临时重命名视觉轨，音轨不动；每对同时出现的视觉单元保持原先遮挡顺序。需要保留“人物/字幕/背景”轨道分组时不加此参数。
