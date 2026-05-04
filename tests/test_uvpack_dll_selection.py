import importlib
import re
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

uvpack_lib = importlib.import_module("uvpack_lib")


def _current_uvpack_version_tag():
    source = (ROOT / "uvpack_cpp" / "uvpack.cpp").read_text(encoding="utf-8")
    match = re.search(r'return\s+"uvpack\s+(\d+)\.(\d+)\.(\d+)"', source)
    if not match:
        raise AssertionError("uvpack.cpp does not expose a parseable uvpack_version string")
    return "".join(match.groups())


class UVPackDllSelectionTests(unittest.TestCase):
    def test_newer_unversioned_dll_is_preferred_over_stale_versioned_dll(self):
        with tempfile.TemporaryDirectory() as tmp:
            base_dir = Path(tmp)
            stale_versioned = base_dir / "lib_uvpack_121.dll"
            fresh_unversioned = base_dir / "lib_uvpack.dll"
            stale_versioned.write_bytes(b"old")
            fresh_unversioned.write_bytes(b"new")

            old_time = 1_700_000_000
            new_time = old_time + 60
            stale_versioned.touch()
            fresh_unversioned.touch()
            import os
            os.utime(stale_versioned, (old_time, old_time))
            os.utime(fresh_unversioned, (new_time, new_time))

            candidates = uvpack_lib._collect_library_candidates(str(base_dir), "Windows")

        self.assertEqual(Path(candidates[0]).name, "lib_uvpack.dll")
        self.assertEqual(Path(candidates[1]).name, "lib_uvpack_121.dll")

    def test_build_script_emits_current_versioned_dll_artifact(self):
        version_tag = _current_uvpack_version_tag()
        script = (ROOT / "build_uvpack.bat").read_text(encoding="utf-8")

        self.assertIn(f'set "UVPACK_VERSION_TAG={version_tag}"', script)
        self.assertIn('set "VERSIONED_DLL=lib_uvpack_%UVPACK_VERSION_TAG%.dll"', script)
        self.assertIn('copy /Y "%OUT_DIR%\\lib_uvpack.dll" "%OUT_DIR%\\%VERSIONED_DLL%"', script)


if __name__ == "__main__":
    unittest.main()
