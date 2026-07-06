#!/usr/bin/env python3
import argparse
import shutil
import struct
import sys
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parent
DEFAULT_INPUT = ROOT / "decrypted_asset"
DEFAULT_OUTPUT = ROOT / "decrypted_asset"
NULL_U64 = 0xFFFFFFFFFFFFFFFF


def safe_part(text: str) -> str:
    return "".join("_" if ch in '<>:"/\\|?*\0' or ord(ch) < 32 else ch for ch in text).strip(" .") or "unnamed"


def read_cstring(data: bytes, offset: int) -> str:
    end = data.find(b"\0", offset)
    if end < 0:
        end = len(data)
    return data[offset:end].decode("utf-8", errors="replace")


def decrypt_utf(data: bytes) -> bytes:
    out = bytearray(len(data))
    mask = 0x655F
    mult = 0x4115
    for i, value in enumerate(data):
        out[i] = value ^ (mask & 0xFF)
        mask = (mask * mult) & 0xFFFFFFFF
    return bytes(out)


def read_packet(fh, offset: int, magic: bytes | None = None) -> bytes:
    fh.seek(offset)
    if magic is not None:
        actual = fh.read(4)
        if actual != magic:
            raise ValueError(f"expected {magic!r} at 0x{offset:x}, got {actual!r}")
    else:
        fh.read(4)
    fh.read(4)
    size = struct.unpack("<Q", fh.read(8))[0]
    data = fh.read(size)
    if not data.startswith(b"@UTF"):
        data = decrypt_utf(data)
    if not data.startswith(b"@UTF"):
        raise ValueError(f"UTF packet at 0x{offset:x} did not decrypt")
    return data


def read_value(data: bytes, offset: int, typ: int, strings_offset: int, data_offset: int):
    if typ in (0, 1):
        return data[offset], offset + 1
    if typ in (2, 3):
        return struct.unpack_from(">H", data, offset)[0], offset + 2
    if typ in (4, 5):
        return struct.unpack_from(">I", data, offset)[0], offset + 4
    if typ in (6, 7):
        return struct.unpack_from(">Q", data, offset)[0], offset + 8
    if typ == 8:
        return struct.unpack_from(">f", data, offset)[0], offset + 4
    if typ == 0xA:
        str_off = struct.unpack_from(">I", data, offset)[0]
        return read_cstring(data, strings_offset + str_off), offset + 4
    if typ == 0xB:
        rel, size = struct.unpack_from(">II", data, offset)
        return data[data_offset + rel:data_offset + rel + size], offset + 8
    raise NotImplementedError(f"UTF column type 0x{typ:x}")


class UtfTable:
    def __init__(self, data: bytes):
        if not data.startswith(b"@UTF"):
            raise ValueError("not an @UTF table")
        table_size, rows_rel, strings_rel, data_rel = struct.unpack_from(">IIII", data, 4)
        self.rows_offset = rows_rel + 8
        self.strings_offset = strings_rel + 8
        self.data_offset = data_rel + 8
        self.table_name = struct.unpack_from(">I", data, 20)[0]
        self.num_columns = struct.unpack_from(">H", data, 24)[0]
        self.row_length = struct.unpack_from(">H", data, 26)[0]
        self.num_rows = struct.unpack_from(">I", data, 28)[0]
        self.columns: list[tuple[int, str, object | None]] = []
        pos = 32
        for _ in range(self.num_columns):
            flags = data[pos]
            pos += 1
            if flags == 0:
                pos += 3
                flags = data[pos]
                pos += 1
            name_off = struct.unpack_from(">I", data, pos)[0]
            pos += 4
            const_value = None
            storage = flags & 0xF0
            if storage == 0x30:
                const_value, pos = read_value(data, pos, flags & 0x0F, self.strings_offset, self.data_offset)
            self.columns.append((flags, read_cstring(data, self.strings_offset + name_off), const_value))

        self.rows: list[dict[str, object | None]] = []
        for row_index in range(self.num_rows):
            row_pos = self.rows_offset + row_index * self.row_length
            row: dict[str, object | None] = {}
            for flags, name, const_value in self.columns:
                storage = flags & 0xF0
                typ = flags & 0x0F
                if storage in (0x00, 0x10):
                    row[name] = None
                elif storage == 0x30:
                    row[name] = const_value
                elif storage == 0x50:
                    row[name], row_pos = read_value(data, row_pos, typ, self.strings_offset, self.data_offset)
                else:
                    raise NotImplementedError(f"UTF storage 0x{storage:x}")
            self.rows.append(row)


@dataclass
class CpkEntry:
    name: str
    offset: int
    size: int
    extract_size: int | None = None
    dirname: str | None = None

    @property
    def path_name(self) -> str:
        name = safe_part(self.name)
        if self.dirname:
            parts = [safe_part(p) for p in str(self.dirname).replace("\\", "/").split("/") if p]
            return str(Path(*parts) / name) if parts else name
        return name


def get_u64(row: dict[str, object | None], key: str) -> int:
    value = row.get(key)
    return NULL_U64 if value is None else int(value)


def parse_toc(fh, toc_offset: int, content_offset: int) -> list[CpkEntry]:
    packet = read_packet(fh, toc_offset, b"TOC ")
    table = UtfTable(packet)
    add_offset = min(toc_offset, content_offset) if content_offset != NULL_U64 else toc_offset
    entries: list[CpkEntry] = []
    for row in table.rows:
        size = row.get("FileSize")
        file_offset = row.get("FileOffset")
        name = row.get("FileName")
        if size is None or file_offset is None or name is None:
            continue
        entries.append(CpkEntry(
            name=str(name),
            dirname=str(row["DirName"]) if row.get("DirName") else None,
            offset=int(file_offset) + add_offset,
            size=int(size),
            extract_size=int(row["ExtractSize"]) if row.get("ExtractSize") is not None else None,
        ))
    return entries


def parse_itoc(fh, itoc_offset: int, content_offset: int, align: int) -> list[CpkEntry]:
    packet = read_packet(fh, itoc_offset, b"ITOC")
    table = UtfTable(packet)
    if not table.rows:
        return []
    root = table.rows[0]
    sizes: dict[int, tuple[int, int | None]] = {}
    for key in ("DataL", "DataH"):
        blob = root.get(key)
        if not isinstance(blob, (bytes, bytearray)) or not blob:
            continue
        sub = UtfTable(bytes(blob))
        for row in sub.rows:
            if row.get("ID") is None or row.get("FileSize") is None:
                continue
            file_id = int(row["ID"])
            sizes[file_id] = (
                int(row["FileSize"]),
                int(row["ExtractSize"]) if row.get("ExtractSize") is not None else None,
            )
    entries: list[CpkEntry] = []
    offset = content_offset
    for file_id in sorted(sizes):
        size, extract_size = sizes[file_id]
        entries.append(CpkEntry(f"{file_id:04d}", offset, size, extract_size))
        offset += size
        if align and size % align:
            offset += align - (size % align)
    return entries


def get_next_bits(data: bytes, state: dict[str, int], bit_count: int) -> int:
    out = 0
    produced = 0
    while produced < bit_count:
        if state["bits_left"] == 0:
            state["bit_pool"] = data[state["offset"]]
            state["bits_left"] = 8
            state["offset"] -= 1
        take = min(state["bits_left"], bit_count - produced)
        out <<= take
        out |= (state["bit_pool"] >> (state["bits_left"] - take)) & ((1 << take) - 1)
        state["bits_left"] -= take
        produced += take
    return out


def decompress_crilayla(data: bytes) -> bytes:
    if not data.startswith(b"CRILAYLA"):
        return data
    uncompressed_size, header_offset = struct.unpack_from("<II", data, 8)
    result = bytearray(uncompressed_size + 0x100)
    result[:0x100] = data[header_offset + 0x10:header_offset + 0x110]
    state = {"offset": len(data) - 0x100 - 1, "bit_pool": 0, "bits_left": 0}
    output_end = 0x100 + uncompressed_size - 1
    bytes_output = 0
    vle_lens = (2, 3, 5, 8)
    while bytes_output < uncompressed_size:
        if get_next_bits(data, state, 1):
            backref = output_end - bytes_output + get_next_bits(data, state, 13) + 3
            length = 3
            for level_bits in vle_lens:
                value = get_next_bits(data, state, level_bits)
                length += value
                if value != (1 << level_bits) - 1:
                    break
            else:
                while True:
                    value = get_next_bits(data, state, 8)
                    length += value
                    if value != 0xFF:
                        break
            for _ in range(length):
                result[output_end - bytes_output] = result[backref]
                backref -= 1
                bytes_output += 1
        else:
            result[output_end - bytes_output] = get_next_bits(data, state, 8)
            bytes_output += 1
    return bytes(result)


def read_entries(cpk: Path) -> list[CpkEntry]:
    with cpk.open("rb") as fh:
        if fh.read(4) != b"CPK ":
            raise ValueError("not a CPK file")
        cpk_table = UtfTable(read_packet(fh, 0, None))
        if not cpk_table.rows:
            return []
        row = cpk_table.rows[0]
        toc_offset = get_u64(row, "TocOffset")
        itoc_offset = get_u64(row, "ItocOffset")
        content_offset = get_u64(row, "ContentOffset")
        align = int(row.get("Align") or 0x800)
        if toc_offset != NULL_U64:
            return parse_toc(fh, toc_offset, content_offset)
        if itoc_offset != NULL_U64:
            return parse_itoc(fh, itoc_offset, content_offset, align)
    return []


def unpack_cpk(cpk: Path, output_root: Path, overwrite: bool = False) -> tuple[int, int]:
    entries = read_entries(cpk)
    out_dir = output_root / f"{safe_part(cpk.stem)}.unpack"
    out_dir.mkdir(parents=True, exist_ok=True)
    written = 0
    skipped = 0
    with cpk.open("rb") as fh:
        for entry in entries:
            out = out_dir / entry.path_name
            if out.exists() and not overwrite:
                skipped += 1
                continue
            fh.seek(entry.offset)
            data = fh.read(entry.size)
            if data.startswith(b"CRILAYLA"):
                data = decompress_crilayla(data)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(data)
            written += 1
    return written, skipped


def collect_cpk(paths: list[Path]) -> list[Path]:
    files: list[Path] = []
    for path in paths:
        if path.is_dir():
            files.extend(path.rglob("*.cpk"))
            files.extend(path.rglob("*.CPK"))
        elif path.is_file() and path.suffix.lower() == ".cpk":
            files.append(path)
    return sorted(set(p.resolve() for p in files))


def choose_paths_gui() -> list[Path]:
    import tkinter as tk
    from tkinter import filedialog

    root = tk.Tk()
    root.withdraw()
    choice = filedialog.askyesno("Sakura CPK unpacker", "Yes: choose a folder recursively\nNo: choose individual CPK files")
    if choice:
        folder = filedialog.askdirectory(title="Choose folder containing CPK files")
        return [Path(folder)] if folder else []
    files = filedialog.askopenfilenames(title="Choose CPK files", filetypes=[("CPK archives", "*.cpk"), ("All files", "*.*")])
    return [Path(f) for f in files]


def main() -> int:
    parser = argparse.ArgumentParser(description="Unpack Sakura CPK archives using a pure Python CRI CPK extractor.")
    parser.add_argument("paths", nargs="*", type=Path, help="CPK files or folders. Empty opens a picker.")
    parser.add_argument("-o", "--output", type=Path, default=DEFAULT_OUTPUT, help="Output root folder.")
    parser.add_argument("--no-gui", action="store_true", help="Use decrypted_asset when no paths are given.")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing extracted files.")
    parser.add_argument("--limit", type=int, help="Only unpack the first N CPK files.")
    args = parser.parse_args()

    inputs = args.paths
    if not inputs and args.no_gui:
        inputs = [DEFAULT_INPUT]
    elif not inputs:
        inputs = choose_paths_gui()
    if not inputs:
        print("No input selected.")
        return 1

    cpks = collect_cpk([p.resolve() for p in inputs])
    if args.limit is not None:
        cpks = cpks[:args.limit]
    if not cpks:
        print("No .cpk files found.")
        return 1

    output = args.output.resolve()
    ok = 0
    failed: list[Path] = []
    for index, cpk in enumerate(cpks, 1):
        print(f"[{index}/{len(cpks)}] {cpk}")
        try:
            written, skipped = unpack_cpk(cpk, output, args.overwrite)
            print(f"  extracted={written} skipped={skipped}")
            ok += 1
        except Exception as exc:
            failed.append(cpk)
            print(f"  failed: {type(exc).__name__}: {exc}")

    if failed:
        fail_list = output / "_cpk_failed.txt"
        fail_list.parent.mkdir(parents=True, exist_ok=True)
        fail_list.write_text("\n".join(str(p) for p in failed), encoding="utf-8")
        print(f"Failed: {len(failed)}. List: {fail_list}")
    print(f"Done: {ok} succeeded, {len(failed)} failed. Output: {output}")
    return 0 if not failed else 2


if __name__ == "__main__":
    raise SystemExit(main())
