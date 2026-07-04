"""pytest 共通設定：scripts/ を import パスに載せる。

scripts/ はパッケージ（__init__.py 付き）ではなくフラットなスクリプト置き場なので、
`import main` 等が通るよう scripts/ を sys.path 先頭に挿す。conftest.py は
テストモジュールより先に読まれるため、ここで一度だけ配線すれば全テストで有効になる。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
