#!/usr/bin/env python3
# tools/bundle.py: Bundles the HTML, CSS, and JS into a single file for easy offline viewing
import os
import re

base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
index_html_path = os.path.join(base_dir, "index.html")
dist_html_path = os.path.join(base_dir, "dist", "synapse-wireframe-single.html")

def inline_css(match):
    css_path = match.group(1)
    full_path = os.path.join(base_dir, css_path)
    with open(full_path, "r", encoding="utf-8") as f:
        content = f.read()
    return f"<style>\n{content}\n</style>"

def inline_js(match):
    js_path = match.group(1)
    full_path = os.path.join(base_dir, js_path)
    with open(full_path, "r", encoding="utf-8") as f:
        content = f.read()
    return f"<script>\n{content}\n</script>"

with open(index_html_path, "r", encoding="utf-8") as f:
    html = f.read()

# Replace css links
html = re.sub(r'<link\s+rel="stylesheet"\s+href="([^"]+)">', inline_css, html)
# Replace script srcs
html = re.sub(r'<script\s+src="([^"]+)"></script>', inline_js, html)

with open(dist_html_path, "w", encoding="utf-8") as f:
    f.write(html)

print(f"Bundled successfully into {dist_html_path}")
