# -*- coding: utf-8 -*-
"""
collect_licenses.py

venv の site-packages から第三者ライセンス本文を収集し、
licenses/ にコピー + THIRD_PARTY_NOTICES.txt を生成します。

使い方（venv を有効化した PowerShell で）:
  python 本ファイルのフルパス.py --clean ← 出力ディレクトリを事前に削除して作り直す

出力:
  release/licenses/               : ライセンス本文（パッケージ名プレフィックス付き）
  release/THIRD_PARTY_NOTICES.txt : 一覧（パッケージ/バージョン/推定ライセンス/同梱ファイル）

注意:
- "推定ライセンス" は dist metadata の License/Classifier から拾います。完全一致を保証しません。
- 一部パッケージ（numpy等）では License フィールドに“本文”が入ることがあります。
  NOTICES が長文化し監査で誤解を招くため、Classifier由来の短い表記を優先します。
- 配布物に実際に含まれるパッケージは PyInstaller の解析結果と一致しない場合があります。
  監査用途で厳密にやるなら、PyInstaller の分析結果（Analysis）を基に絞り込む運用にしてください。

今回の拡張点:
- LICENSE/COPYING/NOTICE の「完全一致」だけでなく、
  LICENSE_BSD_Simple.txt や LICENSE-MIT など “LICENSE*” 相当も収集対象に含めます。
"""

from __future__ import annotations

import argparse
import datetime as dt
import re
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Set, Tuple

try:
    # Python 3.8+
    import importlib.metadata as importlib_metadata
except Exception as e:
    raise SystemExit(f"importlib.metadata が利用できません: {e}")

# LICENSE*, COPYING*, NOTICE* を拾う（例: LICENSE_BSD_Simple.txt / LICENSE-MIT / NOTICE.thirdparty など）
LICENSE_BASENAME_RE = re.compile(r"^(LICENSE|COPYING|NOTICE)([._-].+)?$", re.IGNORECASE)


@dataclass(frozen=True)
class DistLicenseCopy:
    dist_name: str
    dist_version: str
    inferred_license: str
    copied_files: Tuple[str, ...]  # relative filenames under output_dir


def _norm_name(name: str) -> str:
    # file name safety
    s = re.sub(r"\s+", "_", name.strip())
    s = re.sub(r"[^A-Za-z0-9._+-]", "_", s)
    return s


def _infer_license_from_metadata(dist: importlib_metadata.Distribution) -> str:
    """
    dist.metadata から License を推定して返す（短文化版）。

    重要:
    - 一部パッケージ（numpy等）では License フィールドに“ライセンス本文”が入ってしまうことがある。
      この場合 NOTICES が長文化し監査で誤解を招くため、Classifier由来の短い表記を優先する。
    """
    meta = dist.metadata

    # 1) Classifier から License を抽出（短いことが多い）
    classifiers = meta.get_all("Classifier") or []
    lic_classifiers: List[str] = []
    for c in classifiers:
        if isinstance(c, str) and c.strip().startswith("License ::"):
            lic_classifiers.append(c.strip())

    def _short_from_classifiers(items: List[str]) -> str:
        if not items:
            return ""
        cleaned = [x.replace("License ::", "").strip() for x in items]
        # 重複除去（順序維持）
        seen = set()
        uniq: List[str] = []
        for x in cleaned:
            if x not in seen:
                seen.add(x)
                uniq.append(x)
        # 軽い簡約（"OSI Approved ::" 等のノイズ除去、末尾 "License" 削除）
        simplified: List[str] = []
        for x in uniq:
            s = x.replace("OSI Approved ::", "").strip()
            if s.endswith("License"):
                s = s[:-len("License")].strip()
            simplified.append(s)
        return "; ".join(simplified)

    classifier_guess = _short_from_classifiers(lic_classifiers)

    # 2) License フィールド
    lic_field = (meta.get("License") or "").strip()

    # License フィールドが“本文っぽい”場合は無視して classifier を優先
    def _looks_like_full_text(s: str) -> bool:
        if not s:
            return False
        if "\n" in s or "\r" in s:
            return True
        if len(s) > 120:
            return True
        keywords = ["copyright", "permission", "warranty", "redistribution", "liability"]
        low = s.lower()
        return any(k in low for k in keywords)

    if _looks_like_full_text(lic_field):
        return classifier_guess or "UNKNOWN"

    if lic_field and lic_field.upper() != "UNKNOWN":
        return lic_field

    return classifier_guess or "UNKNOWN"


def _site_packages_dir() -> Path:
    # venv 有効化時: sys.prefix が venv のルート
    # Windows: <venv>\Lib\site-packages
    p = Path(sys.prefix) / "Lib" / "site-packages"
    if p.is_dir():
        return p
    # fallback (念のため) Unix-like:
    p2 = Path(sys.prefix) / "lib"
    if p2.is_dir():
        for child in p2.glob("python*/site-packages"):
            if child.is_dir():
                return child
    raise SystemExit("site-packages ディレクトリを特定できません。venv が有効化されているか確認してください。")


def _find_dist_info_dir(site_packages: Path, dist: importlib_metadata.Distribution) -> Optional[Path]:
    """
    dist-info ディレクトリを推定して返す。
    dist-info 名の正確な推定が必要なことがあるため glob で補助する。
    """
    dist_name = dist.metadata.get("Name") or dist.name
    dist_ver = dist.version or "UNKNOWN"

    # 正規化してざっくり探す
    n = re.sub(r"[-_.]+", "[-_.]+", re.escape(dist_name))
    v = re.escape(dist_ver)
    pattern = re.compile(rf"^{n}[-_.]+{v}\.dist-info$", re.IGNORECASE)

    for d in site_packages.glob("*.dist-info"):
        if d.is_dir() and pattern.match(d.name):
            return d

    # fallback: name だけで探して version を含むものを優先
    candidates: List[Path] = []
    for d in site_packages.glob("*.dist-info"):
        if not d.is_dir():
            continue
        low = d.name.lower()
        if _norm_name(dist_name).lower() in low and dist_ver.lower() in low:
            candidates.append(d)
    if candidates:
        candidates.sort(key=lambda x: len(x.name))
        return candidates[0]

    return None


def _select_license_files_from_dist(dist: importlib_metadata.Distribution, dist_info_dir: Optional[Path]) -> List[Path]:
    """
    dist.files からライセンス関連ファイルを抽出して返す。
    取れない場合は dist-info 配下を直接探索する。
    """
    paths: List[Path] = []

    def add_if_file(p: Path) -> None:
        if p.is_file():
            paths.append(p)

    # 1) dist.files（RECORD相当）から拾う
    files = dist.files or []
    if files:
        for f in files:
            s = str(f).replace("\\", "/")
            base = Path(s).name

            # dist-info 直下
            if "/.dist-info/" in s or s.endswith(".dist-info"):
                if LICENSE_BASENAME_RE.match(base):
                    add_if_file(Path(dist.locate_file(f)))
                    continue
                if "/.dist-info/licenses/" in s.lower():
                    add_if_file(Path(dist.locate_file(f)))
                    continue

            # パッケージ直下（または任意階層）に LICENSE* があるケース
            if LICENSE_BASENAME_RE.match(base):
                add_if_file(Path(dist.locate_file(f)))
                continue

    # 2) 上で取れなかった場合は dist-info を探索
    if not paths and dist_info_dir and dist_info_dir.is_dir():
        for p in dist_info_dir.rglob("*"):
            if not p.is_file():
                continue
            base = p.name
            rel = str(p.relative_to(dist_info_dir)).replace("\\", "/").lower()
            if LICENSE_BASENAME_RE.match(base):
                paths.append(p)
            elif rel.startswith("licenses/"):
                paths.append(p)

    # 重複排除（同一実体）
    uniq: List[Path] = []
    seen: Set[str] = set()
    for p in paths:
        key = str(p.resolve()).lower()
        if key not in seen:
            seen.add(key)
            uniq.append(p)
    return uniq


def _copy_with_unique_name(src: Path, out_dir: Path, prefix: str) -> str:
    """
    src を out_dir にコピーし、コピー後のファイル名（out_dir相対）を返す。
    同名が既にあれば _2, _3... を付ける。
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    base = src.name

    # prefix を付ける（パッケージ名-元ファイル名）
    dst_name = f"{prefix}-{base}"
    dst = out_dir / dst_name

    if dst.exists():
        stem = dst.stem
        suffix = dst.suffix
        i = 2
        while True:
            cand = out_dir / f"{stem}_{i}{suffix}"
            if not cand.exists():
                dst = cand
                break
            i += 1

    shutil.copy2(src, dst)
    return dst.name


def _try_copy_python_license(out_dir: Path) -> Optional[str]:
    """
    PyInstaller onefile では Python ランタイムが同梱されるため、
    可能なら Python の LICENSE を out_dir にコピーしておく。
    """
    candidates = [
        Path(sys.base_prefix) / "LICENSE.txt",
        Path(sys.base_prefix) / "LICENSE",
        Path(sys.base_prefix) / "LICENSE.rst",
    ]
    for c in candidates:
        if c.is_file():
            return _copy_with_unique_name(c, out_dir, "Python")
    return None


def collect_licenses(output_dir: Path, exclude: Set[str]) -> Tuple[List[DistLicenseCopy], List[str]]:
    """
    各ディストリビューションのライセンスを output_dir にコピー。
    戻り値:
      - DistLicenseCopy のリスト
      - 警告メッセージ
    """
    site_packages = _site_packages_dir()
    warnings: List[str] = []

    results: List[DistLicenseCopy] = []
    dists = list(importlib_metadata.distributions())

    def sort_key(d: importlib_metadata.Distribution) -> str:
        n = (d.metadata.get("Name") or d.name or "").lower()
        return n

    for dist in sorted(dists, key=sort_key):
        dist_name = dist.metadata.get("Name") or dist.name
        if not dist_name:
            continue

        norm = _norm_name(dist_name).lower()
        if norm in exclude or dist_name.lower() in exclude:
            continue

        dist_ver = dist.version or "UNKNOWN"
        inferred = _infer_license_from_metadata(dist)

        dist_info_dir = _find_dist_info_dir(site_packages, dist)
        lic_files = _select_license_files_from_dist(dist, dist_info_dir)

        copied: List[str] = []
        prefix = _norm_name(dist_name)

        for lf in lic_files:
            try:
                copied_name = _copy_with_unique_name(lf, output_dir, prefix)
                copied.append(copied_name)
            except Exception as e:
                warnings.append(f"[WARN] copy failed: {dist_name} {dist_ver} : {lf} : {e}")

        if not copied:
            warnings.append(f"[WARN] no license file found for: {dist_name} {dist_ver}")

        results.append(
            DistLicenseCopy(
                dist_name=dist_name,
                dist_version=dist_ver,
                inferred_license=inferred,
                copied_files=tuple(sorted(copied)),
            )
        )

    # Python ライセンス（取れれば）→ NOTICES にも明示的に載せる
    py_copied = _try_copy_python_license(output_dir)
    if py_copied:
        py_ver = sys.version.split()[0] if sys.version else "UNKNOWN"
        results.append(
            DistLicenseCopy(
                dist_name="Python",
                dist_version=py_ver,
                inferred_license="Python Software Foundation License (PSF-2.0)",
                copied_files=(py_copied,),
            )
        )
    else:
        warnings.append("[WARN] Python runtime LICENSE was not found under sys.base_prefix.")

    return results, warnings


def write_third_party_notices(
    notices_path: Path,
    copies: List[DistLicenseCopy],
    warnings: List[str],
    output_dir: Path,
) -> None:
    now = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines: List[str] = []
    lines.append("THIRD PARTY NOTICES")
    lines.append("")
    lines.append(f"Generated: {now}")
    # lines.append(f"Output license directory: {output_dir.as_posix()}")
    lines.append(f"Output license directory: licenses")
    lines.append("")
    lines.append("This product bundles third-party software components.")
    lines.append("The following notices are provided for attribution and license compliance.")
    lines.append("")

    for c in sorted(copies, key=lambda x: x.dist_name.lower()):
        lines.append(f"- {c.dist_name} {c.dist_version}")
        lines.append(f"  Declared/Detected License: {c.inferred_license}")
        if c.copied_files:
            lines.append("  Included license files:")
            for f in c.copied_files:
                lines.append(f"    - licenses/{f}")
        else:
            lines.append("  Included license files: (NOT FOUND)")
        lines.append("")

    if warnings:
        lines.append("WARNINGS")
        lines.append("")
        for w in warnings:
            lines.append(w)
        lines.append("")

    notices_path.write_text("\n".join(lines), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument(
        "--output-dir",
        default="release\licenses",
        help="ライセンス本文をコピーするディレクトリ（既定: licenses）",
    )
    p.add_argument(
        "--notices",
        default="release\THIRD_PARTY_NOTICES.txt",
        help="生成する THIRD_PARTY_NOTICES.txt のパス（既定: THIRD_PARTY_NOTICES.txt）",
    )
    p.add_argument(
        "--exclude",
        nargs="*",
        default=["pip", "setuptools", "wheel"],
        help="除外するディストリビューション名（既定: pip setuptools wheel）",
    )
    p.add_argument(
        "--clean",
        action="store_true",
        help="出力ディレクトリを事前に削除して作り直す",
    )
    return p.parse_args()


def main() -> int:
    args = parse_args()
    output_dir = Path(args.output_dir)
    notices_path = Path(args.notices)

    exclude = {_norm_name(x).lower() for x in (args.exclude or [])}

    if args.clean and output_dir.exists():
        shutil.rmtree(output_dir, ignore_errors=True)

    copies, warnings = collect_licenses(output_dir=output_dir, exclude=exclude)
    write_third_party_notices(
        notices_path=notices_path,
        copies=copies,
        warnings=warnings,
        output_dir=output_dir,
    )

    not_found = [c for c in copies if not c.copied_files]
    print(f"[OK] Collected: {len(copies)} distributions")
    print(f"[OK] Output: {output_dir.resolve()}")
    print(f"[OK] Notices: {notices_path.resolve()}")
    if not_found:
        print(f"[WARN] No license file found for {len(not_found)} distributions. See WARNINGS in notices.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
