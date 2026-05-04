import sys
import types
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import op_bake


class FakeImage:
    def __init__(self, name, is_dirty):
        self.name = name
        self.is_dirty = is_dirty


def assert_equal(actual, expected, message):
    if actual != expected:
        raise AssertionError(f"{message}: expected {expected!r}, got {actual!r}")


def assert_true(value, message):
    if not value:
        raise AssertionError(message)


def assert_raises(exc_type, func, message):
    try:
        func()
    except exc_type:
        return
    raise AssertionError(message)


def run():
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

    assert_equal(status, {"FINISHED"}, "FINISHED bake status should be accepted")
    assert_equal(calls, [("INVOKE_DEFAULT", "NORMAL")], "Bake operator should be invoked once")

    assert_raises(
        RuntimeError,
        lambda: op_bake._validate_bake_operator_result({"CANCELLED"}),
        "CANCELLED bake status should fail",
    )
    assert_raises(
        TimeoutError,
        lambda: op_bake._is_bake_image_ready(
            FakeImage("SmokeBake", False),
            started_at=1.0,
            timeout_seconds=2.0,
            now_fn=lambda: 4.0,
        ),
        "Bake image wait should time out",
    )
    assert_true(
        op_bake._is_bake_image_ready(
            FakeImage("SmokeBake", True),
            started_at=1.0,
            timeout_seconds=2.0,
            now_fn=lambda: 4.0,
        ),
        "Dirty bake image should complete",
    )

    print("SMOKE_BAKE_MODAL_PASS")


if __name__ == "__main__":
    run()
