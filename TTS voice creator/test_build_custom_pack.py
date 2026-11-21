import hashlib
import math
import struct
import tarfile
import tempfile
import wave
from pathlib import Path
import unittest

from build_custom_pack import build_custom_pack


class BuildCustomPackTests(unittest.TestCase):
    def test_replaces_selected_ids_and_preserves_other_pack_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source_pack = root / "source.tar.gz"
            custom_sounds = root / "custom-sounds"
            output_dir = root / "output"
            custom_sounds.mkdir()

            with tarfile.open(source_pack, "w:gz") as archive:
                for filename, content in (
                    ("0.ogg", b"original zero"),
                    ("1.ogg", b"original one"),
                    ("2.ogg", b"unchanged"),
                    ("tts.json", b'{"voice":"base"}'),
                ):
                    source_file = root / filename
                    source_file.write_bytes(content)
                    archive.add(source_file, arcname=filename)

            self._write_wav(custom_sounds / "s0.wav")
            self._write_wav(custom_sounds / "1.wav")
            output_pack, metadata_file, _ = build_custom_pack(
                source_pack,
                custom_sounds,
                "custom-voice",
                output_dir,
            )

            with tarfile.open(output_pack, "r:gz") as archive:
                self.assertEqual(
                    set(archive.getnames()),
                    {"0.ogg", "1.ogg", "2.ogg", "tts.json"},
                )
                self.assertTrue(archive.extractfile("0.ogg").read().startswith(b"OggS"))
                self.assertTrue(archive.extractfile("1.ogg").read().startswith(b"OggS"))
                self.assertEqual(archive.extractfile("2.ogg").read(), b"unchanged")
                self.assertEqual(
                    archive.extractfile("tts.json").read(),
                    b'{"voice":"base"}',
                )

            expected_hash = hashlib.md5(output_pack.read_bytes()).hexdigest()
            self.assertIn(f"MD5 hash: {expected_hash}", metadata_file.read_text())

    @staticmethod
    def _write_wav(path: Path) -> None:
        sample_rate = 16000
        frames = (
            struct.pack("<h", int(10000 * math.sin(2 * math.pi * 440 * index / sample_rate)))
            for index in range(sample_rate // 2)
        )
        with wave.open(str(path), "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(sample_rate)
            wav_file.writeframes(b"".join(frames))


if __name__ == "__main__":
    unittest.main()
