# -*- coding: utf-8 -*-
"""a4ef25c 의 kdp_core 로 합성 자료 응답을 정답 파일로 굳힌다(한 번만, a4ef25c 코드에서 실행).

실행: python tests/make_golden_a4ef25c.py
kdp_core.py 가 a4ef25c 와 다르면 멈춘다(줄바꿈은 LF 로 맞춰 비교).
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)
os.environ.pop("STORAGE_ENDPOINT", None)
os.environ.pop("STORAGE_BUCKET", None)

BASE = "a4ef25c"


def _lf_sha(data: bytes) -> str:
    return hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()


def main() -> int:
    want = subprocess.run(["git", "show", f"{BASE}:kdp_core.py"], cwd=ROOT, capture_output=True,
                          check=True).stdout
    with open(os.path.join(ROOT, "kdp_core.py"), "rb") as f:
        have = f.read()
    if _lf_sha(want) != _lf_sha(have):
        print("kdp_core.py 가 a4ef25c 와 다릅니다 — 정답 파일은 a4ef25c 코드로만 만듭니다.")
        return 1

    import databricks_client as dbx
    import kdp_core
    import golden_cases as G
    import oot_fake_rows

    kdp_core._save_cache_disk = lambda: None
    os.makedirs(G.GOLDEN_DIR, exist_ok=True)
    for name, ds, fn in G.LOT_CASES + G.UNCHANGED_CASES:
        kdp_core._DATA_CACHE.clear()
        dbx.query = oot_fake_rows.fake_query(G.ROWS[ds]())
        text = G.dumps(fn(kdp_core))
        with open(G.golden_path(name), "w", encoding="utf-8", newline="\n") as f:
            f.write(text + "\n")
        print("wrote", name)
    with open(os.path.join(G.GOLDEN_DIR, "_made_with.json"), "w", encoding="utf-8",
              newline="\n") as f:
        json.dump({"commit": BASE, "kdp_core_sha256_lf": _lf_sha(have)}, f, indent=1)
        f.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
