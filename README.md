# dol-custom-combination

## 更新上游汉化版

脚本使用 Python 标准库，无需安装依赖。它会查询
`Eltirosto/Degrees-of-Lewdity-Chinese-Localization` 的最新 release，并完成以下操作：

- 用两个 `DoL-ModLoader-*.zip` 中的 HTML 替换固定文件名
  `vanilla/index.html` 和 `vanilla/polyfill.html`。
- 将图片包和汉化包去掉版本号后分别保存为
  `mods/GameOriginalImagePack.mod.zip` 和 `mods/ModI18N.mod.zip`。
- 更新 `index.html` 中的版本号及两个 HTML 链接。

仅更新本地文件：

```powershell
python .\update_upstream.py
```

仅检查是否存在新版本：

```powershell
python .\update_upstream.py --check
```

更新后自动提交并推送到 `origin`：

```powershell
python .\update_upstream.py --publish
```

`--publish` 要求运行前工作区干净。脚本默认根据首页中的
`dol-loader-version` 元数据判断是否需要更新；使用 `--force` 可强制重新下载。
设置 `GITHUB_TOKEN` 或 `GH_TOKEN` 可以避免 GitHub API 的匿名请求限流；未设置或 API
限流时，脚本会自动改用 GitHub release 页面查询。
