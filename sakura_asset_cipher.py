#!/usr/bin/env python3
import argparse
import base64
import hashlib
import json
import re
import shutil
import sys
import time
from functools import lru_cache
from pathlib import Path

import clr  # type: ignore
from Crypto.Cipher import AES

from System.Text import Encoding  # type: ignore
from System.Security.Cryptography import PasswordDeriveBytes  # type: ignore


DEFAULT_KEY = (
    "Jr9DW9ksMRv1Lc796mrwv145fXC3L5VcpmKE5VfCuvbrpZGfYwXMpwo9sGkJ54zH"
    "se4G7zftpjkhqHHY60O7aQPj4M2ekKMSw094PmXRkN4ftTmDFlYMPmwK8QvhJ20H"
)

KEY_LENGTH = 0x2000
BLOCK_SIZE = 16
PLAINTEXT_MAGICS = (b"UnityFS", b"CPK ")
DEFAULT_CHUNK_SIZE = 1024 * 1024
HASH_RE = re.compile(r"([0-9a-fA-F]{32})(?:\.[A-Za-z0-9]+)?$")


@lru_cache(maxsize=8)
def derive_key(password: str, secret_key: str) -> bytes:
    salt = Encoding.UTF8.GetBytes(secret_key)
    pdb = PasswordDeriveBytes(password, salt)
    return bytes(int(x) for x in pdb.GetBytes(16))


def crypt_bytes(data: bytes, password: str, secret_key: str | None = None, start_pos: int = 0) -> bytes:
    secret_key = password if secret_key is None else secret_key
    cipher = AES.new(derive_key(password, secret_key), AES.MODE_ECB)
    out = bytearray(data)

    block_index = ((start_pos // BLOCK_SIZE) + 1) % KEY_LENGTH
    in_block_offset = start_pos % BLOCK_SIZE
    keystream = b""

    for i in range(len(out)):
        if i == 0 or in_block_offset == 0:
            counter = bytearray(BLOCK_SIZE)
            counter[:4] = (block_index & 0xFFFFFFFF).to_bytes(4, "little")
            keystream = cipher.encrypt(bytes(counter))
            block_index = (block_index + 1) % KEY_LENGTH

        out[i] ^= keystream[in_block_offset]
        in_block_offset = (in_block_offset + 1) % BLOCK_SIZE

    return bytes(out)


def crypt_stream(src: Path, dst: Path, password: str, secret_key: str | None = None) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    pos = 0
    with src.open("rb") as in_file, dst.open("wb") as out_file:
        while True:
            chunk = in_file.read(DEFAULT_CHUNK_SIZE)
            if not chunk:
                break
            out_file.write(crypt_bytes(chunk, password, secret_key, pos))
            pos += len(chunk)


def cache_name_from_url(url: str, suffix: str = "_d") -> str:
    leaf = url.rstrip("/").split("/")[-1]
    digest = hashlib.sha1(leaf.encode()).digest()
    return base64.b64encode(digest).decode("ascii").replace("/", "_") + suffix


def safe_name(name: str) -> str:
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(" .") or "unnamed"


def load_catalog_names(catalog_path: Path) -> dict[str, str]:
    data = json.loads(catalog_path.read_text(encoding="utf-8"))
    internal_ids = data.get("m_InternalIds", [])
    mapping: dict[str, str] = {}

    for value in internal_ids:
        if not isinstance(value, str):
            continue

        leaf = value.rstrip("/").split("/")[-1]
        match = HASH_RE.search(leaf)
        if not match:
            continue

        digest = match.group(1).lower()
        mapping.setdefault(digest, safe_name(leaf))

    return mapping


def mapped_catalog_name(src: Path, catalog_names: dict[str, str]) -> str | None:
    hash_path = src.with_name(src.name.removesuffix("_d") + "_h")
    if not hash_path.exists():
        return None

    digest = hash_path.read_text(encoding="ascii", errors="ignore").strip().lower()
    return catalog_names.get(digest)


def classify(data: bytes) -> str:
    if data.startswith(b"UnityFS"):
        return "UnityFS"
    if data.startswith(b"CPK "):
        return "CPK"
    if data.startswith(bytes.fromhex("64 63 ea dd a9 86 43 4f")):
        return "encrypted-cache"
    return data[:16].hex(" ")


def printable_bytes(data: bytes) -> str:
    return "".join(chr(b) if 0x20 <= b <= 0x7E else f"\\x{b:02x}" for b in data)


def format_size(size: float) -> str:
    units = ("B", "KiB", "MiB", "GiB", "TiB")
    for unit in units:
        if size < 1024 or unit == units[-1]:
            return f"{size:5.1f} {unit}"
        size /= 1024
    return f"{size:.1f} B"


def format_duration(seconds: float) -> str:
    if seconds < 0 or seconds == float("inf"):
        return "--:--"
    minutes, sec = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours:d}:{minutes:02d}:{sec:02d}"
    return f"{minutes:02d}:{sec:02d}"


def progress_bar(done: int, total: int, width: int = 28) -> str:
    if total <= 0:
        return "[" + "." * width + "]"
    filled = min(width, int(width * done / total))
    return "[" + "#" * filled + "." * (width - filled) + "]"


class ProgressReporter:
    def __init__(self, total_files: int, total_bytes: int, enabled: bool = True) -> None:
        self.total_files = total_files
        self.total_bytes = total_bytes
        self.enabled = enabled and sys.stdout.isatty()
        self.start = time.monotonic()
        self.last_len = 0

    def update(
        self,
        done_files: int,
        done_bytes: int,
        action: str,
        name: str,
        final: bool = False,
    ) -> None:
        if not self.enabled:
            return

        elapsed = max(time.monotonic() - self.start, 0.001)
        file_rate = done_files / elapsed
        byte_rate = done_bytes / elapsed
        remaining_files = max(self.total_files - done_files, 0)
        eta = remaining_files / file_rate if file_rate > 0 else float("inf")
        percent = (done_files / self.total_files * 100) if self.total_files else 100.0
        short_name = name if len(name) <= 38 else name[:17] + "..." + name[-18:]
        line = (
            f"\r{progress_bar(done_files, self.total_files)} "
            f"{done_files}/{self.total_files} {percent:6.2f}% | "
            f"{format_size(done_bytes)}/{format_size(self.total_bytes)} | "
            f"{format_size(byte_rate)}/s | {file_rate:5.1f} files/s | "
            f"ETA {format_duration(eta)} | {action}: {short_name}"
        )
        padding = " " * max(self.last_len - len(line), 0)
        print(line + padding, end="\n" if final else "", flush=True)
        self.last_len = len(line)

    def clear_line(self) -> None:
        if self.enabled and self.last_len:
            print("\r" + " " * self.last_len + "\r", end="", flush=True)
            self.last_len = 0


def output_name_for(
    src: Path,
    header: bytes,
    transformed_header: bytes,
    keep_suffix: bool,
    catalog_name: str | None = None,
) -> str:
    if keep_suffix:
        return src.name
    if catalog_name:
        if transformed_header.startswith(b"UnityFS") or header.startswith(b"UnityFS"):
            return catalog_name
        if transformed_header.startswith(b"CPK ") or header.startswith(b"CPK "):
            return Path(catalog_name).with_suffix(".cpk").name
        return catalog_name
    if transformed_header.startswith(b"UnityFS"):
        return src.name.removesuffix("_d") + ".unityfs"
    if header.startswith(b"UnityFS"):
        return src.name.removesuffix("_d") + ".unityfs"
    if transformed_header.startswith(b"CPK ") or header.startswith(b"CPK "):
        return src.name.removesuffix("_d") + ".cpk"
    return src.name.removesuffix("_d") + ".bin"


def transform_file(src: Path, dst: Path, password: str, secret_key: str | None, force: bool) -> None:
    header = src.read_bytes()[:128]
    if not force and header.startswith(PLAINTEXT_MAGICS):
        raise SystemExit(f"Refusing to transform plaintext-looking file without --force: {src}")

    crypt_stream(src, dst, password, secret_key)


def batch_transform(
    src_dir: Path,
    dst_dir: Path,
    password: str,
    secret_key: str | None,
    force: bool,
    copy_plaintext: bool,
    keep_suffix: bool,
    limit: int | None,
    pattern: str,
    catalog_names: dict[str, str] | None,
    show_progress: bool,
) -> None:
    if not src_dir.is_dir():
        raise SystemExit(f"Batch input must be a directory: {src_dir}")

    files = sorted(p for p in src_dir.glob(pattern) if p.is_file() and p.name.endswith("_d"))
    if limit is not None:
        files = files[:limit]

    sizes = {path: path.stat().st_size for path in files}
    total_bytes = sum(sizes.values())
    processed_bytes = 0
    progress = ProgressReporter(len(files), total_bytes, show_progress)
    stats = {"decrypted": 0, "copied": 0, "skipped": 0, "unknown": 0, "failed": 0}
    for index, src in enumerate(files, 1):
        header = src.read_bytes()[:128]
        transformed_header = crypt_bytes(header, password, secret_key)
        catalog_name = mapped_catalog_name(src, catalog_names) if catalog_names else None
        dst = dst_dir / output_name_for(src, header, transformed_header, keep_suffix, catalog_name)

        try:
            if header.startswith(PLAINTEXT_MAGICS):
                if copy_plaintext:
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, dst)
                    stats["copied"] += 1
                    action = "copied"
                elif force:
                    crypt_stream(src, dst, password, secret_key)
                    stats["decrypted"] += 1
                    action = "forced"
                else:
                    stats["skipped"] += 1
                    action = "skipped"
            elif transformed_header.startswith(PLAINTEXT_MAGICS):
                crypt_stream(src, dst, password, secret_key)
                stats["decrypted"] += 1
                action = "decrypted"
            else:
                stats["unknown"] += 1
                action = "unknown"

            processed_bytes += sizes[src]
            if not progress.enabled and (index == 1 or index % 250 == 0 or index == len(files)):
                print(f"[{index}/{len(files)}] {action}: {src.name} -> {dst.name}")
            progress.update(index, processed_bytes, action, dst.name, final=index == len(files))
        except Exception as exc:
            processed_bytes += sizes[src]
            stats["failed"] += 1
            progress.clear_line()
            print(f"[{index}/{len(files)}] failed: {src.name}: {exc}")
            progress.update(index, processed_bytes, "failed", src.name, final=index == len(files))

    print(
        "summary: "
        + ", ".join(f"{name}={count}" for name, count in stats.items())
        + f", total={len(files)}"
    )


def preview_file(src: Path, password: str, secret_key: str | None, count: int) -> None:
    raw = src.read_bytes()[:count]
    transformed = crypt_bytes(raw, password, secret_key)
    print(f"{src}")
    print(f"  raw:         {classify(raw)}")
    print(f"  transformed: {classify(transformed)}")
    print(f"  hex:         {transformed[:32].hex(' ')}")
    print(f"  ascii:       {printable_bytes(transformed[:64])}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Encrypt/decrypt Sakura Kakumei AssetCache _d files. The operation is symmetric."
    )
    parser.add_argument("input", nargs="?", help="Input _d file")
    parser.add_argument("output", nargs="?", help="Output file")
    parser.add_argument("--key", default=DEFAULT_KEY, help="Password and default secret key")
    parser.add_argument("--secret-key", default=None, help="Override salt/secret key")
    parser.add_argument("--preview", action="store_true", help="Only decrypt/encrypt the first bytes and print magic")
    parser.add_argument("--batch", action="store_true", help="Process every *_d file in an AssetCache directory")
    parser.add_argument("--copy-plaintext", action="store_true", help="In batch mode, copy plaintext UnityFS/CPK files")
    parser.add_argument("--keep-suffix", action="store_true", help="In batch mode, keep original *_d output names")
    parser.add_argument("--limit", type=int, default=None, help="In batch mode, process only the first N *_d files")
    parser.add_argument("--glob", default="*_d", help="In batch mode, input filename glob")
    parser.add_argument("--catalog", help="Addressables catalog.json used to restore readable bundle names via *_h hash")
    parser.add_argument("--no-progress", action="store_true", help="Disable the live batch progress bar")
    parser.add_argument("--count", type=int, default=128, help="Preview byte count")
    parser.add_argument("--force", action="store_true", help="Allow transforming files that already look plaintext")
    parser.add_argument("--cache-name", help="Print AssetCache file name for a URL leaf and exit")
    args = parser.parse_args()

    if args.cache_name:
        print(cache_name_from_url(args.cache_name))
        return

    if not args.input:
        parser.error("input is required unless --cache-name is used")

    src = Path(args.input)
    if args.batch:
        if not args.output:
            parser.error("output directory is required with --batch")
        batch_transform(
            src,
            Path(args.output),
            args.key,
            args.secret_key,
            args.force,
            args.copy_plaintext,
            args.keep_suffix,
            args.limit,
            args.glob,
            load_catalog_names(Path(args.catalog)) if args.catalog else None,
            not args.no_progress,
        )
        return

    if args.preview:
        preview_file(src, args.key, args.secret_key, args.count)
        return

    if not args.output:
        parser.error("output is required unless --preview is used")

    transform_file(src, Path(args.output), args.key, args.secret_key, args.force)


if __name__ == "__main__":
    main()
