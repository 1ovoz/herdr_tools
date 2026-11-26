"""Exercise file menu requests through a staged or installed Windows kit helper."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import uuid


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    default = Path(__file__).resolve().parents[1] / "herdr-mod-kit/common/bridge.py"
    parser.add_argument("helper", type=Path, nargs="?", default=default)
    helper = parser.parse_args().helper.resolve(strict=True)

    with tempfile.TemporaryDirectory(prefix="herdr-menu-") as directory:
        root = Path(directory)
        source = root / "테스트.txt"
        source.write_text("Herdr Files", encoding="utf8")
        folder = root / "folder"
        folder.mkdir()

        def request(action, **fields):
            payload = {"job": uuid.uuid4().hex, "action": action, **fields}
            output = subprocess.check_output([
                sys.executable, "-X", "utf8", str(helper), "--hc", "unused-local",
                "--home", str(root), "--request", json.dumps(payload),
            ], encoding="utf8")
            return json.loads(output)

        def success(action, **fields):
            result = request(action, **fields)
            assert result["ok"], (action, result)
            return Path(result["path"])

        created = success("new-folder", directory=str(folder), name="새 폴더")
        assert created == folder / "새 폴더" and created.is_dir()
        new_file = success("new-file", directory=str(created), name="빈 파일.txt")
        assert new_file == created / "빈 파일.txt" and new_file.read_bytes() == b""
        new_file.write_bytes(b"keep")
        for action in ("new-file", "new-folder"):
            for target in (new_file, created):
                collision = request(action, directory=str(target.parent), name=target.name)
                assert collision["code"] == "exists" and "Replace" not in collision["error"]
            for name in ("", ".", "..", "../escape", "nested/item", str(root / "escape")):
                assert not request(action, directory=str(created), name=name)["ok"]
            assert not request(action, directory=str(new_file), name="child")["ok"]
            assert not request(action, directory=".", name="child")["ok"]
        assert new_file.read_bytes() == b"keep" and not (root / "escape").exists()
        with ThreadPoolExecutor(2) as workers:
            results = list(workers.map(
                lambda action: request(action, directory=str(folder), name="race"),
                ("new-file", "new-folder"),
            ))
        assert sorted(result.get("code", "ok") for result in results) == ["exists", "ok"]

        copied = success("copy", source=str(source), directory=str(folder))
        assert copied.read_bytes() == source.read_bytes()
        assert request("copy", source=str(source), directory=str(folder))["code"] == "exists"
        renamed = success("rename", source=str(copied), name="새 이름.txt")
        moved = success("move", source=str(renamed), directory=str(root))
        assert moved.read_bytes() == source.read_bytes() and not renamed.exists()
        assert not request("delete", source=str(moved), confirmed=False)["ok"] and moved.exists()
        success("delete", source=str(moved), confirmed=True)
        assert not moved.exists() and source.is_file()
    print("File helper passed create, collision, copy, rename, move, and delete confirmation checks.")


if __name__ == "__main__":
    main()
