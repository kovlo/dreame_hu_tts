import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path

from extract_listening_packs import convert_pack


class ExtractListeningPacksTests(unittest.TestCase):
    def test_converts_pack_audio_and_creates_ordered_playlist(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source_audio = root / "1.ogg"
            subprocess.run(
                [
                    "ffmpeg",
                    "-nostdin",
                    "-v",
                    "error",
                    "-f",
                    "lavfi",
                    "-i",
                    "sine=frequency=440:duration=0.1",
                    "-c:a",
                    "libvorbis",
                    str(source_audio),
                ],
                check=True,
            )
            pack_path = root / "voice-pack"
            with tarfile.open(pack_path, "w:gz") as archive:
                archive.add(source_audio, arcname="1.ogg")
                metadata = root / "tts.json"
                metadata.write_text("{}")
                archive.add(metadata, arcname="tts.json")

            output_dir = root / "listening" / "noemi"
            output_dir.mkdir(parents=True)
            (output_dir / "1.mp3").write_bytes(b"old generated name")
            count = convert_pack(
                pack_path,
                output_dir,
                {1: "Várakozás a hálózati konfigurációra."},
                text_chars=20,
            )

            self.assertEqual(count, 1)
            filename = "1 - Várakozás a hálózati.mp3"
            self.assertTrue((output_dir / filename).read_bytes().startswith(b"ID3"))
            self.assertFalse((output_dir / "1.mp3").exists())
            self.assertEqual(
                (output_dir / "playlist.m3u").read_text(),
                f"#EXTM3U\n#EXTINF:-1,1\n{filename}\n",
            )

            convert_pack(
                pack_path,
                output_dir,
                {1: "Várakozás a hálózati konfigurációra."},
                text_chars=9,
            )
            updated_filename = "1 - Várakozás.mp3"
            self.assertTrue((output_dir / updated_filename).is_file())
            self.assertFalse((output_dir / filename).exists())
            self.assertFalse((output_dir / "1.mp3").exists())


if __name__ == "__main__":
    unittest.main()
