import argparse
import csv
import re
import subprocess
import sys
import tarfile
from pathlib import Path


CREATOR_DIR = Path(__file__).resolve().parent
DEFAULT_SOURCE_DIR = Path("/base-packs")
DEFAULT_OUTPUT_DIR = CREATOR_DIR / "listening-packs"
VOICE_NAMES = ("jenny", "noemi", "ryan", "tamas")
OGG_FILENAME = re.compile(r"[0-9]+\.ogg\Z")
UNSAFE_FILENAME_CHARACTERS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def load_commands() -> dict[int, str]:
    commands: dict[int, str] = {}
    with (CREATOR_DIR / "all_dreame_hu.csv").open(
        newline="", encoding="utf-8"
    ) as csv_file:
        reader = csv.DictReader(csv_file, delimiter=";")
        if reader.fieldnames is None or not {"Code", "Text"}.issubset(reader.fieldnames):
            raise ValueError("CSV must contain Code and Text columns")

        for row in reader:
            code = (row["Code"] or "").strip()
            package_id = code[1:] if code.startswith("s") else code
            if not package_id.isdecimal():
                raise ValueError(f"Unsupported sentence ID in CSV: {code}")
            sound_id = int(package_id)
            if sound_id in commands:
                raise ValueError(f"Multiple CSV rows map to sound ID {sound_id}")
            commands[sound_id] = row["Text"] or ""
    return commands


def command_filename(sound_id: int, command: str, text_chars: int) -> str:
    excerpt = UNSAFE_FILENAME_CHARACTERS.sub(
        "_", command[:text_chars]
    ).strip(" .")
    if not excerpt:
        excerpt = "sound"
    return f"{sound_id} - {excerpt}.mp3"


def convert_pack(
    pack_path: Path,
    output_dir: Path,
    commands: dict[int, str],
    text_chars: int = 40,
) -> int:
    if text_chars < 1:
        raise ValueError("Command text length must be at least 1")

    output_dir.mkdir(parents=True, exist_ok=True)
    playlist_path = output_dir / "playlist.m3u"
    previous_files: set[str] = set()
    if playlist_path.is_file():
        for line in playlist_path.read_text(encoding="utf-8").splitlines():
            if not line or line.startswith("#"):
                continue
            previous_path = Path(line)
            if previous_path.name != line or previous_path.suffix != ".mp3":
                raise ValueError(f"Unexpected entry in generated playlist: {line}")
            previous_files.add(line)

    entries: list[tuple[int, str, tarfile.TarInfo]] = []

    with tarfile.open(pack_path, "r:*") as archive:
        for member in archive.getmembers():
            if not member.isfile() or not member.name.endswith(".ogg"):
                continue
            if not OGG_FILENAME.fullmatch(member.name):
                raise ValueError(f"Unexpected OGG filename in {pack_path}: {member.name}")
            sound_id = int(member.name.removesuffix(".ogg"))
            entries.append((sound_id, member.name, member))

        if not entries:
            raise ValueError(f"No numbered OGG audio files found in {pack_path}")

        seen_ids: set[int] = set()
        sorted_entries = sorted(entries)
        voice = output_dir.name
        is_terminal = sys.stderr.isatty()
        last_reported_step = -1

        for index, (sound_id, filename, member) in enumerate(sorted_entries, start=1):
            if sound_id in seen_ids:
                raise ValueError(f"Duplicate sound ID in {pack_path}: {sound_id}")
            if sound_id not in commands:
                raise ValueError(f"Sound ID {sound_id} is missing from the CSV")
            seen_ids.add(sound_id)

            source = archive.extractfile(member)
            if source is None:
                raise ValueError(f"Could not read {filename} from {pack_path}")
            with source:
                subprocess.run(
                    [
                        "ffmpeg",
                        "-nostdin",
                        "-v",
                        "error",
                        "-y",
                        "-i",
                        "pipe:0",
                        "-map",
                        "0:a:0",
                        "-vn",
                        "-c:a",
                        "libmp3lame",
                        "-q:a",
                        "2",
                        str(
                            output_dir
                            / command_filename(
                                sound_id,
                                commands.get(sound_id, ""),
                                text_chars,
                            )
                        ),
                    ],
                    input=source.read(),
                    check=True,
                )

            percent = index * 100 // len(sorted_entries)
            step = percent // 5
            if is_terminal:
                bar_width = 24
                filled = bar_width * index // len(sorted_entries)
                progress_bar = "=" * filled + " " * (bar_width - filled)
                print(
                    f"\r{voice}: [{progress_bar}] {percent:3d}% "
                    f"({index}/{len(sorted_entries)})",
                    end="\n" if index == len(sorted_entries) else "",
                    flush=True,
                    file=sys.stderr,
                )
            elif step > last_reported_step:
                print(
                    f"{voice}: {percent}% ({index}/{len(sorted_entries)})",
                    file=sys.stderr,
                    flush=True,
                )
            last_reported_step = step

    playlist_lines = ["#EXTM3U"]
    current_files: set[str] = set()
    for sound_id, _, _ in sorted_entries:
        filename = command_filename(
            sound_id,
            commands.get(sound_id, ""),
            text_chars,
        )
        current_files.add(filename)
        playlist_lines.extend((f"#EXTINF:-1,{sound_id}", filename))
    legacy_files = {f"{sound_id}.mp3" for sound_id, _, _ in sorted_entries}
    for stale_filename in (previous_files | legacy_files) - current_files:
        (output_dir / stale_filename).unlink(missing_ok=True)
    playlist_path.write_text(
        "\n".join(playlist_lines) + "\n",
        encoding="utf-8",
    )
    return len(entries)


def extract_listening_packs(
    source_dir: Path,
    output_dir: Path,
    voices: tuple[str, ...] = VOICE_NAMES,
    text_chars: int = 40,
) -> dict[str, int]:
    commands = load_commands()
    extracted: dict[str, int] = {}
    for voice in voices:
        pack_path = source_dir / f"{voice}_dreame_hu_voice"
        if not pack_path.is_file():
            raise FileNotFoundError(f"Voice pack not found: {pack_path}")
        extracted[voice] = convert_pack(
            pack_path,
            output_dir / voice,
            commands,
            text_chars,
        )
    return extracted


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Convert the bundled Dreame voice packs to locally playable MP3 files."
    )
    parser.add_argument(
        "--source-dir",
        type=Path,
        default=DEFAULT_SOURCE_DIR,
        help=f"Folder containing the bundled voice packs (default: {DEFAULT_SOURCE_DIR})",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"Folder for the MP3 files and playlists (default: {DEFAULT_OUTPUT_DIR})",
    )
    parser.add_argument(
        "--voice",
        choices=VOICE_NAMES,
        action="append",
        help="Voice to convert; repeat to select multiple. By default, convert all voices.",
    )
    parser.add_argument(
        "--text-chars",
        type=int,
        default=40,
        help="Number of command text characters to include in each filename (default: 40)",
    )
    args = parser.parse_args()

    if args.text_chars < 1:
        parser.error("--text-chars must be at least 1")

    try:
        results = extract_listening_packs(
            args.source_dir,
            args.output_dir,
            tuple(args.voice) if args.voice else VOICE_NAMES,
            args.text_chars,
        )
    except (OSError, ValueError, tarfile.TarError, subprocess.CalledProcessError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1

    for voice, count in results.items():
        print(f"{voice}: {count} MP3 files and playlist in {args.output_dir / voice}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
