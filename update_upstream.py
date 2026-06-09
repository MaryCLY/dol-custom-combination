#!/usr/bin/env python3
"""Update the repository from the latest Chinese localization release."""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path


REPOSITORY = "Eltirosto/Degrees-of-Lewdity-Chinese-Localization"
API_URL = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
LATEST_URL = f"https://github.com/{REPOSITORY}/releases/latest"
USER_AGENT = "dol-custom-combination-updater/1.0"

NORMAL_RE = re.compile(r"^DoL-ModLoader-.+(?<!-polyfill)\.zip$")
POLYFILL_RE = re.compile(r"^DoL-ModLoader-.+-polyfill\.zip$")
IMAGE_RE = re.compile(r"^GameOriginalImagePack-.+\.mod\.zip$")
I18N_RE = re.compile(r"^ModI18N-.+\.mod\.zip$")


@dataclass(frozen=True)
class Release:
    tag: str
    assets: dict[str, str]


def request(url: str) -> urllib.request.Request:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": USER_AGENT,
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return urllib.request.Request(url, headers=headers)


def latest_release() -> Release:
    try:
        with urllib.request.urlopen(request(API_URL), timeout=30) as response:
            payload = json.load(response)
        return Release(
            tag=payload["tag_name"],
            assets={asset["name"]: asset["browser_download_url"] for asset in payload["assets"]},
        )
    except (urllib.error.URLError, KeyError, json.JSONDecodeError) as error:
        print(f"GitHub API 不可用，改用发布页面查询：{error}", file=sys.stderr)
        return latest_release_from_page()


def latest_release_from_page() -> Release:
    with urllib.request.urlopen(request(LATEST_URL), timeout=30) as response:
        final_url = response.geturl()
    marker = "/releases/tag/"
    if marker not in final_url:
        raise RuntimeError(f"无法从最新发布地址识别 tag：{final_url}")

    tag = urllib.parse.unquote(final_url.split(marker, 1)[1])
    expanded_url = f"https://github.com/{REPOSITORY}/releases/expanded_assets/{urllib.parse.quote(tag)}"
    with urllib.request.urlopen(request(expanded_url), timeout=30) as response:
        page = response.read().decode("utf-8")

    pattern = re.compile(
        rf'href="(/Eltirosto/Degrees-of-Lewdity-Chinese-Localization/releases/download/'
        rf'{re.escape(urllib.parse.quote(tag, safe=""))}/([^"]+))"'
    )
    assets = {}
    for path, encoded_name in pattern.findall(page):
        name = html.unescape(urllib.parse.unquote(encoded_name))
        assets[name] = urllib.parse.urljoin("https://github.com", html.unescape(path))
    if not assets:
        raise RuntimeError(f"发布 {tag} 中未找到附件")
    return Release(tag=tag, assets=assets)


def select_asset(assets: dict[str, str], pattern: re.Pattern[str], description: str) -> tuple[str, str]:
    matches = [(name, url) for name, url in assets.items() if pattern.fullmatch(name)]
    if len(matches) != 1:
        names = ", ".join(name for name, _ in matches) or "无"
        raise RuntimeError(f"{description}附件应恰好有一个，实际找到：{names}")
    return matches[0]


def current_loader(index_path: Path) -> str | None:
    content = index_path.read_text(encoding="utf-8")
    match = re.search(r'<meta name="dol-loader-version" content="([^"]+)"\s*/?>', content)
    return match.group(1) if match else None


def download(url: str, target: Path) -> None:
    print(f"下载 {target.name}")
    with urllib.request.urlopen(request(url), timeout=180) as response:
        with target.open("wb") as output:
            shutil.copyfileobj(response, output)


def html_member(archive: Path) -> str:
    with zipfile.ZipFile(archive) as bundle:
        members = [name for name in bundle.namelist() if not name.endswith("/") and name.lower().endswith(".html")]
        if len(members) != 1:
            raise RuntimeError(f"{archive.name} 应恰好包含一个 HTML，实际找到 {len(members)} 个")
        return members[0]


def extract_html(archive: Path, member: str, target: Path) -> None:
    with zipfile.ZipFile(archive) as bundle:
        with bundle.open(member) as source, target.open("wb") as output:
            shutil.copyfileobj(source, output)


def game_version(loader_name: str) -> str:
    match = re.fullmatch(r"DoL-ModLoader-(.+)-v[^/]+\.zip", loader_name)
    if not match:
        raise RuntimeError(f"无法从附件名识别游戏版本：{loader_name}")
    return match.group(1)


def update_index(index_path: Path, loader_name: str, version: str) -> None:
    content = index_path.read_text(encoding="utf-8")
    content, normal_count = re.subn(
        r'vanilla/(?:DoL-ModLoader-[^"]+(?<!-polyfill)|index)\.html',
        "vanilla/index.html",
        content,
    )
    content, polyfill_count = re.subn(
        r'vanilla/(?:DoL-ModLoader-[^"]+-polyfill|polyfill)\.html',
        "vanilla/polyfill.html",
        content,
    )
    content, version_count = re.subn(r"(ver:)\S+", rf"\g<1>{version}", content, count=1)
    if (normal_count, polyfill_count, version_count) != (1, 1, 1):
        raise RuntimeError("index.html 中的普通版链接、兼容版链接或版本号格式不符合预期")
    meta = f'<meta name="dol-loader-version" content="{loader_name}" />'
    content, meta_count = re.subn(
        r'<meta name="dol-loader-version" content="[^"]+"\s*/?>',
        meta,
        content,
        count=1,
    )
    if meta_count == 0:
        content, head_count = re.subn(r"(<head>\s*)", rf"\1    {meta}\n", content, count=1)
        if head_count != 1:
            raise RuntimeError("index.html 中未找到 head 标签")
    index_path.write_text(content, encoding="utf-8", newline="\n")


def run_git(root: Path, *args: str, capture: bool = False) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        text=True,
        capture_output=capture,
    )
    return result.stdout.strip() if capture else ""


def publish(root: Path, tag: str) -> None:
    paths = ["index.html", "vanilla", "mods"]
    run_git(root, "add", "--", *paths)
    if subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=root).returncode == 0:
        print("没有需要提交的变更")
        return
    run_git(root, "commit", "-m", f"更新上游汉化版至 {tag}")
    run_git(root, "push", "origin", "HEAD")
    print(f"已提交并推送 {tag}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="只检查是否有更新，不下载或修改文件")
    parser.add_argument("--publish", action="store_true", help="更新后提交并推送到 origin")
    parser.add_argument("--force", action="store_true", help="即使加载器文件名一致也重新下载替换")
    args = parser.parse_args()
    if args.check and (args.publish or args.force):
        parser.error("--check 不能与 --publish 或 --force 同时使用")
    return args


def main() -> int:
    args = parse_args()
    root = Path(__file__).resolve().parent
    vanilla_dir = root / "vanilla"
    mods_dir = root / "mods"

    if args.publish and run_git(root, "status", "--porcelain", capture=True):
        raise RuntimeError("--publish 要求运行前 git 工作区干净")

    release = latest_release()
    normal = select_asset(release.assets, NORMAL_RE, "普通版")
    polyfill = select_asset(release.assets, POLYFILL_RE, "兼容版")
    image = select_asset(release.assets, IMAGE_RE, "图片包")
    i18n = select_asset(release.assets, I18N_RE, "汉化包")

    current = current_loader(root / "index.html")
    if current == normal[0] and not args.force:
        print(f"当前已是最新版本：{normal[0]}（上游发布 {release.tag}）")
        return 0
    if args.check:
        print(f"发现新版本：当前 {current or '无'}，最新 {normal[0]}（上游发布 {release.tag}）")
        return 0

    with tempfile.TemporaryDirectory(prefix="dol-update-") as temp:
        temp_dir = Path(temp)
        downloaded = {}
        for name, url in (normal, polyfill, image, i18n):
            target = temp_dir / name
            download(url, target)
            downloaded[name] = target

        for name, archive in downloaded.items():
            if not zipfile.is_zipfile(archive):
                raise RuntimeError(f"下载的附件不是有效 ZIP：{name}")
        normal_member = html_member(downloaded[normal[0]])
        polyfill_member = html_member(downloaded[polyfill[0]])

        vanilla_dir.mkdir(exist_ok=True)
        mods_dir.mkdir(exist_ok=True)
        extract_html(downloaded[normal[0]], normal_member, vanilla_dir / "index.html")
        extract_html(downloaded[polyfill[0]], polyfill_member, vanilla_dir / "polyfill.html")
        shutil.copyfile(downloaded[image[0]], mods_dir / "GameOriginalImagePack.mod.zip")
        shutil.copyfile(downloaded[i18n[0]], mods_dir / "ModI18N.mod.zip")

    for old_html in vanilla_dir.glob("DoL-ModLoader-*.html"):
        old_html.unlink()
    update_index(root / "index.html", normal[0], game_version(normal[0]))

    print(f"已更新至 {normal[0]}（上游发布 {release.tag}）")
    if args.publish:
        publish(root, release.tag)
    else:
        print("文件已更新但未提交；确认后可使用 --publish 自动提交并推送")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, subprocess.CalledProcessError, zipfile.BadZipFile) as error:
        print(f"更新失败：{error}", file=sys.stderr)
        raise SystemExit(1)
