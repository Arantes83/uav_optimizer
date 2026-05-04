import importlib
import sys
import types
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


fake_bpy = types.SimpleNamespace()
sys.modules["bpy"] = fake_bpy
sys.modules["bpy.types"] = types.SimpleNamespace(Operator=object)

op_bake = importlib.import_module("op_bake")


class FakeImage:
    def __init__(self, name="BakeTarget", is_dirty=False):
        self.name = name
        self.is_dirty = is_dirty


class BakeModalGuardTests(unittest.TestCase):
    def test_finished_bake_status_is_accepted_without_retrying_operator(self):
        calls = []

        def fake_bake(invoke_mode, type):
            calls.append((invoke_mode, type))
            return {"FINISHED"}

        original_bpy = op_bake.bpy
        op_bake.bpy = types.SimpleNamespace(
            ops=types.SimpleNamespace(
                object=types.SimpleNamespace(bake=fake_bake),
            ),
        )
        try:
            status = op_bake._invoke_bake_operator("NORMAL")
        finally:
            op_bake.bpy = original_bpy

        self.assertEqual(status, {"FINISHED"})
        self.assertEqual(calls, [("INVOKE_DEFAULT", "NORMAL")])

    def test_cancelled_bake_status_fails_instead_of_looping(self):
        with self.assertRaisesRegex(RuntimeError, "cancel"):
            op_bake._validate_bake_operator_result({"CANCELLED"})

    def test_dirty_wait_times_out_when_image_never_updates(self):
        image = FakeImage(is_dirty=False)

        with self.assertRaisesRegex(TimeoutError, "timed out"):
            op_bake._is_bake_image_ready(
                image,
                started_at=10.0,
                timeout_seconds=5.0,
                now_fn=lambda: 16.0,
            )

    def test_dirty_wait_yields_before_timeout(self):
        image = FakeImage(is_dirty=False)

        self.assertFalse(
            op_bake._is_bake_image_ready(
                image,
                started_at=10.0,
                timeout_seconds=5.0,
                now_fn=lambda: 12.0,
            )
        )

    def test_dirty_wait_completes_when_image_is_dirty(self):
        image = FakeImage(is_dirty=True)

        self.assertTrue(
            op_bake._is_bake_image_ready(
                image,
                started_at=10.0,
                timeout_seconds=5.0,
                now_fn=lambda: 99.0,
            )
        )


if __name__ == "__main__":
    unittest.main()
