# 剪映可编辑工程 Skill

私有复用的剪映工程转换方案。把已有视频方案、SRT、人物和独立素材，生成可继续手动精修的新剪映工程。

包含原生字幕、文字/图片/视频混排、唯一主轨、素材兼容属性、保守轨道压缩、字体与素材打包、路径迁移、结构校验，以及本人的剪辑风格偏好。不会上传或附带真实人物视频、成片、字体文件和业务工程。

## 在另一台 Windows 电脑安装

需要能访问此私有仓库的 GitHub 账号、Git、Python 3.10+，使用工程时还需要剪映专业版。先克隆，再安装 Skill：

```powershell
git clone https://github.com/1119870144/jianying-editable-project-skill.git
cd jianying-editable-project-skill
python scripts/install_skill.py
```

默认安装到 `%USERPROFILE%\.codex\skills\jianying-editable-project`；设置了 `CODEX_HOME` 时改用其 `skills` 目录。已存在的同名 Skill 会完整备份到 `CODEX_HOME/skill-backups/` 下的时间戳目录，不丢弃旧文件，也不会被重复发现。安装器不会安装 Python 依赖、修改剪映设置或上传任何内容。

重新打开 Codex 会话后说：

> 使用 $jianying-editable-project，把这个视频方案和素材生成新的可编辑剪映工程，沿用我的字幕风格。

其他支持 `SKILL.md` 的工具也可读取整个目录，具体安装位置按该工具规定。私有仓库无法匿名下载，需要在自己的电脑登录 GitHub，不要把访问令牌发到聊天里。

## 准备生成环境

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe scripts/draft_tool.py build manifest.json work/NewDraft
.\.venv\Scripts\python.exe scripts/draft_tool.py check work/NewDraft
.\.venv\Scripts\python.exe scripts/draft_tool.py install work/NewDraft 'D:/JianyingPro Drafts' --name NewDraft_v1
```

最后一行需替换成该电脑实际使用的草稿根目录，目标根目录必须已存在。不要把另一台电脑的旧绝对素材路径直接搬过来；清单使用相对于清单文件的素材路径，构建器会复制并登记新路径。人物原片、字体和 SRT 另行在本机准备。

清单格式见 [references/manifest.md](references/manifest.md)，完整流程入口为 [SKILL.md](SKILL.md)。本机参考路径仅用于寻找已有实现，在其他电脑不要求存在。

生成前先指定长期保存目录，并集中收集素材。当前脚本使用草稿内素材和绝对路径；直接重命名或移动磁盘上的草稿文件夹不属于已验证的迁移方式，独立外置素材目录尚需适配。备份整个项目包后，在新位置迁移引用并复核；剪映云端迁移需实际上传、下载后验证。详见 [保存位置与迁移](references/workflow.md#保存位置与迁移)。

## 测试与打包

```powershell
python -m unittest discover -s tests -v
python examples/make_demo.py work/demo --font 'C:/Windows/Fonts/arial.ttf' --ffmpeg ffmpeg
python scripts/draft_tool.py build work/demo/manifest.json work/DemoDraft
python scripts/draft_tool.py check work/DemoDraft
python scripts/package_skill.py
```

合成样例包含同排文字、图片、空档、视频、可删除的空副轨、SRT 和独立音频。FFmpeg 只供样例生成和转码使用。样例未包含真实人脸，不能验证美颜；宿主中的分割、美颜、预览和导出仍需实际核对。

`dist/jianying-editable-project.skill` 是带顶层技能目录的 ZIP 包，也可解压后复制到 Skill 目录。打包采用明确文件范围，排除 `work`、`.git`、缓存、依赖环境和真实媒体。更新时 `git pull` 后重新运行安装器。

## 版本与边界

v0.1.1 补充指定素材保存位置、集中打包、改名和云迁移的验证规则，并记录本次素材引用恢复结果；构建器功能未改变。基于 Windows / Python 3.12 / pyJianYingDraft 0.3.0，参考剪映 11.6.0.14551。2026-10-13 的隔离修复方案已获用户实测成功反馈；参数化构建器的 11 项测试、合成样例构建、路径迁移和安装备份检查通过。参见 [验证记录](references/validation.md) 和 [兼容记录](references/compatibility.md)。

本方案不是官方 API，不是把任意 MP4 自动还原为完整图层的工具，也不自动重建复杂多时间线、模板特效或复合片段。每次生成都新建目录和 ID，拒绝覆盖已有工程。文件检查通过不等于所有宿主界面功能通过。

依赖 [pyJianYingDraft](https://github.com/GuanYixuan/pyJianYingDraft) 按其原有许可证使用；本私有仓库未授予对外开源或素材再分发许可。
