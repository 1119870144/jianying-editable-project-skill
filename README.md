# 剪映可编辑工程 Skill

私有复用的剪映工程转换方案。把已有视频方案、SRT、人物和独立素材，生成可继续手动精修的新剪映工程。

包含原生字幕、文字/图片/视频混排、唯一主轨、素材兼容属性、本地媒体登记、官方字体引用校正、保守轨道压缩、字体与素材打包、路径迁移、结构校验，以及本人的剪辑风格偏好。不会上传或附带真实人物视频、成片、字体文件和业务工程。

## 本机其他聊天窗口调用

本机已经全局安装，无需在每个项目重复安装。在任意本地 Codex 聊天发送：

> 使用 $jianying-editable-project，把我提供的视频方案、SRT 和素材生成新的可编辑剪映工程，沿用我的字幕风格，默认放在剪映草稿目录，并做素材登记和字体检查。

随后提供当前素材路径和制作要求。遇到旧工程则明确要“修复副本”还是“创建新工程”，避免覆盖手工修改。Skill 保存复用规则与脚本，不会自动读取其他聊天的全部对话。

Codex 会自动发现 Skill 更新；列表未刷新时重启 Codex。本机已验证的位置为 `%USERPROFILE%\.codex\skills\jianying-editable-project`。也可以直接要求读取该目录的 `SKILL.md`。调用语法及重新加载说明见 [OpenAI 官方文档](https://learn.chatgpt.com/docs/build-skills)。

## 在另一台 Windows 电脑安装

需要能访问此私有仓库的 GitHub 账号、Git、Python 3.10+，使用工程时还需要剪映专业版。先克隆，再安装 Skill：

```powershell
git clone https://github.com/1119870144/jianying-editable-project-skill.git
cd jianying-editable-project-skill
python scripts/install_skill.py --skills-root "$env:USERPROFILE\.agents\skills"
```

上面使用 [当前官方文档](https://learn.chatgpt.com/docs/build-skills) 的用户级 `.agents/skills` 目录。若该电脑与本机一样使用 `.codex/skills`，最后一行改为 `python scripts/install_skill.py`；设置了 `CODEX_HOME` 时默认使用其 `skills` 目录。选择该客户端实际识别的一个位置，避免重复安装同名 Skill。安装器把已有同名 Skill 完整备份到技能根目录旁的 `skill-backups/` 时间戳目录，不丢弃旧文件，也不会被重复发现。它不会安装 Python 依赖、修改剪映设置或上传任何内容。

安装后按上面的本机调用方式使用；未出现在列表时重启 Codex。也可以直接让另一台电脑上的 Codex 完成安装：

> 从我的私有仓库 https://github.com/1119870144/jianying-editable-project-skill 安装 jianying-editable-project 到本机 Codex 的用户级 Skill 目录，按 README 检查 Python、剪映和字体依赖。使用本机已有 GitHub 登录，不公开仓库，不上传素材。

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

默认保存在该电脑剪映实际草稿目录，素材集中在对应工程内，不再询问保存位置。当前脚本使用草稿内素材和绝对路径；直接重命名或移动磁盘上的草稿文件夹不属于已验证的迁移方式。备份整个项目包后，在新位置迁移引用并复核；剪映内改名和云端上传下载分别验证。详见 [保存位置与迁移](references/workflow.md#保存位置与迁移)。

## 测试与打包

```powershell
python -m unittest discover -s tests -v
python examples/make_demo.py work/demo --font 'C:/Windows/Fonts/arial.ttf' --ffmpeg ffmpeg
python scripts/draft_tool.py build work/demo/manifest.json work/DemoDraft
python scripts/draft_tool.py check work/DemoDraft
python scripts/package_skill.py
```

合成样例包含同排文字、图片、空档、视频、可删除的空副轨、SRT 和独立音频。FFmpeg 只供样例生成和转码使用。普通转换把已剪好视频对应的制作源码、分层素材和 SRT 直接生成并校验为新草稿，不重新剪辑，不打开或采集剪映窗口；完成后提示用户重启剪映检查新草稿。样例未包含真实人脸，不能验证美颜；仅在用户要求软件内验收或排查已报告故障时，实际核对相关的分割、美颜、预览或导出。未做的软件检查标为未验证，不阻塞普通草稿交付。

`dist/jianying-editable-project.skill` 是带顶层技能目录的 ZIP 包，也可改扩展名为 `.zip` 后解压，把整个 `jianying-editable-project` 文件夹放入实际 Skill 根目录。GitHub 私有 Release 同时提供包与 SHA256。打包采用明确文件范围，排除 `work`、`.git`、缓存、依赖环境和真实媒体。更新时 `git pull` 后使用与首次相同的安装命令。

## 版本与边界

v0.2.0 合入本地媒体登记和官方字体内外层引用修复，补齐嵌套媒体及本地音频登记检查。默认使用剪映草稿目录，不再询问保存位置。基于 Windows / Python 3.12 / pyJianYingDraft 0.3.0，参考剪映 11.6.0.14551。2026-10-13 用户确认隔离测试工程的剪映内改名、云端上传下载通过；构建器 17 项测试、合成样例、真实官方字库构建、路径迁移和安装备份检查通过。参见 [验证记录](references/validation.md) 和 [兼容记录](references/compatibility.md)。

本方案不是官方 API，不是把任意 MP4 自动还原为完整图层的工具，也不自动重建复杂多时间线、模板特效或复合片段。每次生成都新建目录和 ID，拒绝覆盖已有工程。文件检查通过不等于所有宿主界面功能通过。

依赖 [pyJianYingDraft](https://github.com/GuanYixuan/pyJianYingDraft) 按其原有许可证使用；本私有仓库未授予对外开源或素材再分发许可。
