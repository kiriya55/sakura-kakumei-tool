#!/usr/bin/env python3
import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent
DEFAULT_INPUT = ROOT / "decrypted_asset"
DEFAULT_OUTPUT = ROOT / "converted_media"
DEFAULT_USM_KEY = "382759"


def find_tool(name: str, bundled: Path | None = None) -> str:
    if bundled and bundled.exists():
        return str(bundled)
    found = shutil.which(name)
    if found:
        return found
    raise SystemExit(f"Missing tool: {name}")


def safe_part(text: str) -> str:
    return "".join("_" if ch in '<>:"/\\|?*\0' or ord(ch) < 32 else ch for ch in text).strip(" .") or "unnamed"


def collect_inputs(paths: list[Path]) -> list[Path]:
    files: list[Path] = []
    for path in paths:
        if path.is_dir():
            files.extend(path.rglob("*"))
        elif path.is_file():
            files.append(path)
    return sorted(
        p for p in files
        if p.is_file() and p.suffix.lower() in {".acb", ".awb", ".usm"}
    )


def choose_paths_gui() -> list[Path]:
    import tkinter as tk
    from tkinter import filedialog

    root = tk.Tk()
    root.withdraw()
    choice = filedialog.askyesno(
        "Sakura media converter",
        "Yes: choose a folder recursively\nNo: choose individual files",
    )
    if choice:
        folder = filedialog.askdirectory(title="Choose folder containing acb/awb/usm")
        return [Path(folder)] if folder else []
    files = filedialog.askopenfilenames(
        title="Choose acb/awb/usm files",
        filetypes=[
            ("CRI media", "*.acb *.awb *.usm"),
            ("All files", "*.*"),
        ],
    )
    return [Path(f) for f in files]


def relative_output_base(src: Path, input_roots: list[Path], output_dir: Path) -> Path:
    rel = None
    for root in input_roots:
        if root.is_dir():
            try:
                rel = src.relative_to(root)
                break
            except ValueError:
                pass
    if rel is None:
        rel = Path(src.name)
    return output_dir / rel.parent / safe_part(src.stem)


def run_logged(cmd: list[str], log_path: Path) -> int:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", encoding="utf-8", errors="replace") as log:
        log.write(" ".join(f'"{x}"' if " " in x else x for x in cmd) + "\n\n")
        proc = subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT)
        log.write(f"\nexit_code={proc.returncode}\n")
        return proc.returncode


def parse_usm_key(text: str | None) -> int | None:
    if not text:
        return None
    value = text.strip().replace("_", "")
    if value.lower().startswith("0x"):
        return int(value, 16)
    if len(value) == 16 and all(ch in "0123456789abcdefABCDEF" for ch in value):
        return int(value, 16)
    return int(value, 10)


def usm_masks(keycode: int) -> tuple[bytes, bytes, bytes]:
    key = keycode.to_bytes(8, "little", signed=False)
    t = [0] * 0x20
    t[0x00] = key[0]
    t[0x01] = key[1]
    t[0x02] = key[2]
    t[0x03] = (key[3] - 0x34) & 0xFF
    t[0x04] = (key[4] + 0xF9) & 0xFF
    t[0x05] = key[5] ^ 0x13
    t[0x06] = (key[6] + 0x61) & 0xFF
    t[0x07] = t[0x00] ^ 0xFF
    t[0x08] = (t[0x02] + t[0x01]) & 0xFF
    t[0x09] = (t[0x01] - t[0x07]) & 0xFF
    t[0x0A] = t[0x02] ^ 0xFF
    t[0x0B] = t[0x01] ^ 0xFF
    t[0x0C] = (t[0x0B] + t[0x09]) & 0xFF
    t[0x0D] = (t[0x08] - t[0x03]) & 0xFF
    t[0x0E] = t[0x0D] ^ 0xFF
    t[0x0F] = (t[0x0A] - t[0x0B]) & 0xFF
    t[0x10] = (t[0x08] - t[0x0F]) & 0xFF
    t[0x11] = t[0x10] ^ t[0x07]
    t[0x12] = t[0x0F] ^ 0xFF
    t[0x13] = t[0x03] ^ 0x10
    t[0x14] = (t[0x04] - 0x32) & 0xFF
    t[0x15] = (t[0x05] + 0xED) & 0xFF
    t[0x16] = t[0x06] ^ 0xF3
    t[0x17] = (t[0x13] - t[0x0F]) & 0xFF
    t[0x18] = (t[0x15] + t[0x07]) & 0xFF
    t[0x19] = (0x21 - t[0x13]) & 0xFF
    t[0x1A] = t[0x14] ^ t[0x17]
    t[0x1B] = (t[0x16] + t[0x16]) & 0xFF
    t[0x1C] = (t[0x17] + 0x44) & 0xFF
    t[0x1D] = (t[0x03] + t[0x04]) & 0xFF
    t[0x1E] = (t[0x05] - t[0x16]) & 0xFF
    t[0x1F] = t[0x1D] ^ t[0x13]
    mask1 = bytes(t)
    mask2 = bytes(x ^ 0xFF for x in t)
    table = b"URUC"
    audio_mask = bytes(table[(i >> 1) & 3] if i & 1 else mask2[i] for i in range(0x20))
    return mask1, mask2, audio_mask


def decrypt_usm_video_payload(payload: bytes, keycode: int | None) -> bytes:
    if keycode is None or len(payload) < 0x240:
        return payload
    data = bytearray(payload)
    mask1, mask2, _ = usm_masks(keycode)
    data_offset = 0x40
    size = len(data) - data_offset

    rolling = bytearray(mask2)
    for i in range(0x100, size):
        pos = data_offset + i
        data[pos] ^= rolling[i & 0x1F]
        rolling[i & 0x1F] = data[pos] ^ mask2[i & 0x1F]

    rolling = bytearray(mask1)
    for i in range(0x100):
        rolling[i & 0x1F] ^= data[data_offset + 0x100 + i]
        data[data_offset + i] ^= rolling[i & 0x1F]
    return bytes(data)


def decrypt_usm_audio_payload(payload: bytes, keycode: int | None) -> bytes:
    if keycode is None or len(payload) <= 0x140:
        return payload
    data = bytearray(payload)
    _, _, audio_mask = usm_masks(keycode)
    for i in range(0x140, len(data)):
        data[i] ^= audio_mask[(i - 0x140) & 0x1F]
    return bytes(data)


def extract_usm_video(src: Path, out: Path, keycode: int | None) -> int:
    data = src.read_bytes()
    pos = 0
    chunks = 0
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("wb") as fh:
        while pos + 0x20 <= len(data):
            chunk_id = data[pos:pos + 4]
            chunk_size = int.from_bytes(data[pos + 4:pos + 8], "big")
            header_size = int.from_bytes(data[pos + 8:pos + 10], "big")
            padding_size = int.from_bytes(data[pos + 10:pos + 12], "big")
            chunk_type = int.from_bytes(data[pos + 14:pos + 16], "big") & 0x03
            if chunk_size <= 0 or pos + 8 + chunk_size > len(data):
                break
            payload_size = chunk_size - header_size - padding_size
            payload_start = pos + 8 + header_size
            if chunk_id == b"@SFV" and chunk_type == 0 and payload_size > 0:
                payload = data[payload_start:payload_start + payload_size]
                fh.write(decrypt_usm_video_payload(payload, keycode))
                chunks += 1
            pos += 8 + chunk_size
    if chunks == 0 or out.stat().st_size == 0:
        out.unlink(missing_ok=True)
        return 0
    return chunks


def extract_usm_audio(src: Path, out_dir: Path, keycode: int | None) -> list[Path]:
    data = src.read_bytes()
    pos = 0
    outputs: dict[int, object] = {}
    paths: dict[int, Path] = {}
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        while pos + 0x20 <= len(data):
            chunk_id = data[pos:pos + 4]
            chunk_size = int.from_bytes(data[pos + 4:pos + 8], "big")
            header_size = int.from_bytes(data[pos + 8:pos + 10], "big")
            padding_size = int.from_bytes(data[pos + 10:pos + 12], "big")
            channel = data[pos + 12]
            chunk_type = int.from_bytes(data[pos + 14:pos + 16], "big") & 0x03
            if chunk_size <= 0 or pos + 8 + chunk_size > len(data):
                break
            payload_size = chunk_size - header_size - padding_size
            payload_start = pos + 8 + header_size
            if chunk_id == b"@SFA" and chunk_type == 0 and payload_size > 0:
                payload = data[payload_start:payload_start + payload_size]
                if channel not in outputs:
                    path = out_dir / f"{src.stem}_{channel}.adx"
                    paths[channel] = path
                    outputs[channel] = path.open("wb")
                outputs[channel].write(decrypt_usm_audio_payload(payload, keycode))
            pos += 8 + chunk_size
    finally:
        for fh in outputs.values():
            fh.close()
    return [p for _, p in sorted(paths.items()) if p.exists() and p.stat().st_size > 0]


def convert_audio(src: Path, output_base: Path, vgmstream: str, log_dir: Path) -> bool:
    out_dir = output_base
    out_dir.mkdir(parents=True, exist_ok=True)
    pattern = str(out_dir / "?s_?n.wav")
    cmd = [vgmstream, "-i", "-S", "0", "-o", pattern, str(src)]
    code = run_logged(cmd, log_dir / f"{src.stem}.vgmstream.log")
    wavs = [p for p in out_dir.glob("*.wav") if p.stat().st_size > 44]
    return code == 0 and bool(wavs)


def convert_audio_file(src: Path, output_dir: Path, vgmstream: str, log_path: Path) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    pattern = str(output_dir / f"{safe_part(src.stem)}.wav")
    code = run_logged([vgmstream, "-i", "-o", pattern, str(src)], log_path)
    if code != 0:
        return []
    return sorted(p for p in output_dir.glob("*.wav") if p.stat().st_size > 44)


def convert_usm(src: Path, output_base: Path, ffmpeg: str, vgmstream: str, log_dir: Path, usm_key: int | None) -> bool:
    out = output_base.with_suffix(".mp4")
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        out.unlink()

    with tempfile.TemporaryDirectory(prefix="sakura_usm_") as tmp_name:
        tmp = Path(tmp_name)
        video_input = tmp / f"{src.stem}.m2v"
        chunks = extract_usm_video(src, video_input, usm_key)
        if chunks == 0:
            existing_video = src.with_suffix(".m2v")
            if not existing_video.exists():
                existing_video = next(iter(sorted(src.parent.glob("*.m2v"))), src)
            video_input = existing_video if existing_video.exists() else src

        audio_payload_dir = tmp / "audio_payload"
        audio_files = extract_usm_audio(src, audio_payload_dir, usm_key)
        wavs: list[Path] = []
        for audio_index, audio_file in enumerate(audio_files):
            wavs.extend(convert_audio_file(
                audio_file,
                tmp / f"audio_wav_{audio_index}",
                vgmstream,
                log_dir / f"{src.stem}.usm_audio_{audio_index}.vgmstream.log",
            ))

        if not wavs:
            wavs = convert_audio_file(
                src,
                tmp / "audio_fallback",
                vgmstream,
                log_dir / f"{src.stem}.usm_audio_fallback.vgmstream.log",
            )

        cmd = [
            ffmpeg,
            "-y",
            "-hide_banner",
            "-probesize",
            "100M",
            "-analyzeduration",
            "100M",
            "-i",
            str(video_input),
        ]
        if wavs:
            cmd.extend(["-i", str(wavs[0])])
        cmd.extend([
            "-map",
            "0:v:0",
        ])
        if wavs:
            cmd.extend(["-map", "1:a:0"])
        cmd.extend([
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "18",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-movflags",
            "+faststart",
            str(out),
        ])
        code = run_logged(cmd, log_dir / f"{src.stem}.ffmpeg.log")
    if code == 0 and out.exists() and out.stat().st_size > 1024:
        return True
    if out.exists() and out.stat().st_size == 0:
        out.unlink()
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Convert Sakura CRI acb/awb to wav and usm to mp4.")
    parser.add_argument("paths", nargs="*", type=Path, help="Input files or folders. Empty opens a picker.")
    parser.add_argument("-o", "--output", type=Path, default=DEFAULT_OUTPUT, help="Output folder.")
    parser.add_argument("--no-gui", action="store_true", help="Do not open file picker when paths are empty.")
    parser.add_argument("--usm-key", default=DEFAULT_USM_KEY, help="USM key as decimal or 16-digit hex. Empty disables USM decryption.")
    args = parser.parse_args()

    input_paths = args.paths
    if not input_paths and DEFAULT_INPUT.exists() and args.no_gui:
        input_paths = [DEFAULT_INPUT]
    elif not input_paths and not args.no_gui:
        input_paths = choose_paths_gui()
    if not input_paths:
        print("No input selected.")
        return 1

    vgmstream = find_tool("vgmstream-cli.exe", ROOT / "tools" / "vgmstream" / "vgmstream-cli.exe")
    ffmpeg = find_tool("ffmpeg.exe")
    usm_key = parse_usm_key(args.usm_key)
    output_dir = args.output.resolve()
    log_dir = output_dir / "_logs"
    files = collect_inputs([p.resolve() for p in input_paths])
    if not files:
        print("No .acb/.awb/.usm files found.")
        return 1

    ok = 0
    failed: list[Path] = []
    for index, src in enumerate(files, 1):
        base = relative_output_base(src, [p.resolve() for p in input_paths], output_dir)
        print(f"[{index}/{len(files)}] {src}")
        try:
            if src.suffix.lower() in {".acb", ".awb"}:
                success = convert_audio(src, base, vgmstream, log_dir)
            else:
                success = convert_usm(src, base, ffmpeg, vgmstream, log_dir, usm_key)
        except Exception as exc:
            success = False
            (log_dir / "exceptions.log").parent.mkdir(parents=True, exist_ok=True)
            with (log_dir / "exceptions.log").open("a", encoding="utf-8") as log:
                log.write(f"{src}: {exc}\n")

        if success:
            ok += 1
        else:
            failed.append(src)
            print(f"  failed; see {log_dir}")

    if failed:
        fail_list = output_dir / "_failed.txt"
        fail_list.parent.mkdir(parents=True, exist_ok=True)
        fail_list.write_text("\n".join(str(p) for p in failed), encoding="utf-8")
        print(f"Failed: {len(failed)} file(s). List: {fail_list}")
    print(f"Done: {ok} succeeded, {len(failed)} failed. Output: {output_dir}")
    return 0 if not failed else 2


if __name__ == "__main__":
    raise SystemExit(main())
