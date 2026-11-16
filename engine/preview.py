"""Write a standalone HTML preview of a theme's background (open it in any Chromium browser).

    python engine/preview.py themes/ring-trails-ascii.json preview.html
"""
import html, json, sys
from pathlib import Path

theme = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
out = Path(sys.argv[2] if len(sys.argv) > 2 else "preview.html")
out.write_text(
    "<!doctype html><html class=dark><head><meta charset=utf-8><title>%s</title>"
    "<style>body{margin:0;height:100vh}</style><style>%s</style></head><body></body></html>"
    % (html.escape(theme["name"]), theme["css"]),
    encoding="utf-8",
)
print("wrote", out)
