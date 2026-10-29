# Synapse Wireframe

Synapse is a centralised healthcare data platform for Lifecare Diagnostics that collects, structures, and interprets diagnostic reports.

**Notice:** Synthetic data only. All patient names and data used in this wireframe are completely mock/synthetic.

## How to Run
Simply open `index.html` in Chrome or any modern browser. It runs entirely offline without external dependencies.

## Folder Map
- `index.html`: Main markup shell
- `assets/css/`: CSS design tokens, layouts, and components
- `assets/js/core/`: Application state, router, and UI helpers
- `assets/js/data/`: Hardcoded mock JSON data
- `assets/js/screens/`: Screen-specific JavaScript logic
- `docs/`: Markdown documentation for screens and flow mapping
- `legacy/`: Original untouched single-file wireframe
- `dist/`: Generated bundled single HTML file
- `tools/`: Build scripts
- `screenshots/`: For holding screenshots

## Flowchart
See `docs/synapse-flowchart.png` for a visual representation of the data flow.

## Bundling to Single File
To rebuild the single-file wireframe `dist/synapse-wireframe-single.html` for easy distribution:
1. Ensure Python 3 is installed.
2. Run `python tools/bundle.py` from the project root.

## Adding a New Screen
1. Add the screen's HTML into `index.html` with class `screen` and a unique `id`.
2. Add a navigation item in `index.html` sidebar linking to that `id`.
3. Create `assets/js/screens/newscreen.js` with `render()` and `init()` methods.
4. Add the `<script>` tag to `index.html`.
5. Update `docs/screens.md` and `docs/flow-mapping.md` with the new screen info.
