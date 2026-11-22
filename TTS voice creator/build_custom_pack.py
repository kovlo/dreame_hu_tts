import argparse
import csv
import hashlib
import re
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path


CREATOR_DIR = Path(__file__).resolve().parent
CSV_PATH = CREATOR_DIR / "all_dreame_hu.csv"
DEFAULT_CUSTOM_SOUNDS = CREATOR_DIR / "custom-sounds"
SUPPORTED_EXTENSIONS = {".mp3", ".wav"}
SOUND_ID_PREFIX = re.compile(r"^(?:s)?(?P<sound_id>[0-9]+)", re.IGNORECASE)
SPEECH_NORMALIZATION = "speechnorm=p=0.95:e=2.0:c=2.0:t=0.0:r=0.001"


def load_sentence_files(csv_path: Path) -> dict[str, str]:
    sentence_files: dict[str, str] = {}
    with csv_path.open(newline="", encoding="utf-8") as csv_file:
        reader = csv.DictReader(csv_file, delimiter=";")
        if reader.fieldnames is None or "Code" not in reader.fieldnames:
            raise ValueError(f"CSV has no Code column: {csv_path}")

        for row in reader:
            code = (row["Code"] or "").strip()
            package_id = code[1:] if code.startswith("s") else code
            if not package_id.isdecimal():
                raise ValueError(f"Unsupported sentence ID in CSV: {code}")

            filename = f"{package_id}.ogg"
            if filename in sentence_files.values():
                raise ValueError(f"Multiple CSV IDs map to {filename}")
            sentence_files[code] = filename

    return sentence_files


def find_custom_sounds(
    custom_sounds_dir: Path,
    sentence_files: dict[str, str],
) -> dict[str, Path]:
    if not custom_sounds_dir.is_dir():
        raise ValueError(f"Custom sounds directory not found: {custom_sounds_dir}")

    custom_sounds: dict[str, Path] = {}
    package_files = {
        str(int(Path(filename).stem)): filename
        for filename in sentence_files.values()
    }
    for path in sorted(custom_sounds_dir.iterdir()):
        if path.name in {".gitignore", ".DS_Store"}:
            continue
        if not path.is_file():
            raise ValueError(f"Expected an audio file, found: {path.name}")
        if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            raise ValueError(f"Only MP3 and WAV files are supported: {path.name}")

        match = SOUND_ID_PREFIX.match(path.stem)
        if match is None:
            raise ValueError(f"Unknown sentence ID in custom sound filename: {path.name}")

        sound_id = str(int(match.group("sound_id")))
        package_filename = package_files.get(sound_id)
        if package_filename is None:
            raise ValueError(f"Unknown sentence ID in custom sound filename: {path.name}")
        if package_filename in custom_sounds:
            raise ValueError(f"More than one custom sound supplied for ID {sound_id}")
        custom_sounds[package_filename] = path

    if not custom_sounds:
        raise ValueError(f"No MP3 or WAV recordings found in {custom_sounds_dir}")
    return custom_sounds


def encode_recording(source: Path, target: Path, temporary_dir: Path) -> None:
    intermediate_wav = temporary_dir / f"{target.stem}.wav"
    subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-v",
            "error",
            "-y",
            "-i",
            str(source),
            "-map",
            "0:a:0",
            "-vn",
            "-af",
            SPEECH_NORMALIZATION,
            "-ac",
            "1",
            "-ar",
            "16000",
            "-c:a",
            "pcm_s16le",
            str(intermediate_wav),
        ],
        check=True,
    )
    subprocess.run(
        [
            "oggenc",
            str(intermediate_wav),
            "--output",
            str(target),
            "--bitrate",
            "56",
            "--resample",
            "16000",
        ],
        check=True,
    )


def build_custom_pack(
    source_pack: Path,
    custom_sounds_dir: Path,
    pack_name: str,
    output_dir: Path,
) -> tuple[Path, Path, int]:
    if not pack_name.strip() or Path(pack_name).name != pack_name:
        raise ValueError("Pack name must be a non-empty filename without a directory")

    sentence_files = load_sentence_files(CSV_PATH)
    custom_sounds = find_custom_sounds(custom_sounds_dir, sentence_files)
    output_pack = output_dir / f"{pack_name}.tar.gz"
    if source_pack.resolve() == output_pack.resolve():
        raise ValueError("Output pack must not overwrite the source pack")

    with tarfile.open(source_pack, "r:*") as source_archive:
        members = source_archive.getmembers()
        names = [member.name for member in members]
        if len(names) != len(set(names)):
            raise ValueError("Source pack contains duplicate filenames")
        if any(Path(name).name != name for name in names):
            raise ValueError("Source pack must contain files at its root")

        missing = sorted(set(custom_sounds) - set(names))
        if missing:
            raise ValueError(
                "The source pack does not contain sentence file(s): "
                + ", ".join(missing)
            )
        for member in members:
            if not member.isfile():
                raise ValueError(f"Unsupported entry in source pack: {member.name}")

        with tempfile.TemporaryDirectory(prefix="dreame-custom-sounds-") as temp_dir:
            temp_path = Path(temp_dir)
            encoded_sounds: dict[str, Path] = {}
            for package_filename, recording in custom_sounds.items():
                encoded_path = temp_path / package_filename
                encode_recording(recording, encoded_path, temp_path)
                encoded_sounds[package_filename] = encoded_path

            output_dir.mkdir(parents=True, exist_ok=True)
            with tarfile.open(output_pack, "w:gz") as output_archive:
                for member in members:
                    replacement = encoded_sounds.get(member.name)
                    if replacement is not None:
                        member.size = replacement.stat().st_size
                        with replacement.open("rb") as encoded_file:
                            output_archive.addfile(member, encoded_file)
                    else:
                        source_file = source_archive.extractfile(member)
                        if source_file is None:
                            raise ValueError(f"Could not read source file: {member.name}")
                        with source_file:
                            output_archive.addfile(member, source_file)

    digest = hashlib.md5()
    with output_pack.open("rb") as pack_file:
        for chunk in iter(lambda: pack_file.read(4096), b""):
            digest.update(chunk)
    file_size = output_pack.stat().st_size
    metadata_file = output_pack.with_name(f"{output_pack.name}.txt")
    metadata_file.write_text(
        f"MD5 hash: {digest.hexdigest()}\nFájlméret: {file_size} byte\n",
        encoding="utf-8",
    )
    return output_pack, metadata_file, file_size


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Replace selected sounds in a Dreame voice pack with recordings."
    )
    parser.add_argument(
        "--source",
        type=Path,
        required=True,
        help="Complete source voice-pack tar.gz file",
    )
    parser.add_argument("--name", required=True, help="Name for the output voice pack")
    parser.add_argument(
        "--custom-sounds",
        type=Path,
        default=DEFAULT_CUSTOM_SOUNDS,
        help=f"Folder containing <sentence-id>.mp3 or .wav files (default: {DEFAULT_CUSTOM_SOUNDS})",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path.cwd(),
        help="Output folder for the generated archive and metadata",
    )
    args = parser.parse_args()

    try:
        output_pack, metadata_file, file_size = build_custom_pack(
            args.source,
            args.custom_sounds,
            args.name,
            args.output_dir,
        )
    except (OSError, ValueError, tarfile.TarError, subprocess.CalledProcessError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1

    print(f"Voice pack: {output_pack}")
    print(f"Metadata: {metadata_file}")
    print(f"Size: {file_size} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
