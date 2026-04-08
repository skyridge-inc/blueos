## Tasks

### 1. Visualization module
- [x] 1.1 Create `visualize.py` with `generate_visualization_html(mower_paths, output_path)` — takes list of mower paths (each a list of (lat, lon) tuples) and writes a standalone HTML file
- [x] 1.2 HTML template: Leaflet.js map with Esri World Imagery tiles, auto-fit bounds, colored polylines per mower
- [x] 1.3 Animation: animated marker per path with play/pause button, speed slider (1x–10x)
- [x] 1.4 Controls: per-mower visibility toggles with color indicators

### 2. CLI integration
- [x] 2.1 Add `--visualize` flag to `mow` command in `cli.py`
- [x] 2.2 When flag is set, call `generate_visualization_html()` after writing waypoint files
- [x] 2.3 Output the `.html` file path alongside waypoint output in console

### 3. Tests
- [x] 3.1 Unit tests for `visualize.py`: verify HTML output contains Leaflet setup, correct coordinate data, expected number of path arrays
- [x] 3.2 CLI tests: verify `--visualize` flag produces HTML file, verify omitting flag does not produce HTML
- [x] 3.3 Run full test suite, confirm all existing + new tests pass (52 passed)
