## Tasks

### 1. Spine extraction
- [x] 1.1 Add `extract_spine(vertices_xy)` to `polygon.py` — walks vertices from index 0, computes turn angles, returns polyline up to first ≥ 90° turn
- [x] 1.2 Add tests for spine extraction: simple rectangle (1 edge), multi-vertex corridor (follows curves), all-sharp-turns edge case

### 2. Contour path generation module
- [x] 2.1 Create `contour.py` with `generate_contour_paths(vertices_xy, spine_xy, width_inches)` — generates spine + parallel offsets using Shapely `offset_curve()`, clips to polygon
- [x] 2.2 Add `_determine_offset_sign()` helper to detect which side of the spine faces the polygon interior
- [x] 2.3 Add tests for contour paths: rectangular polygon, narrowing polygon, single-path-fits case, all-within-polygon, offset spacing

### 3. CLI update
- [x] 3.1 Update `cli.py` — replace boustrophedon pipeline with contour pipeline, change `--width` to inches, remove `--overlap` and `--heading`
- [x] 3.2 Update CLI tests: KML + width in inches, multi-mower output, verify mower count display

### 4. Integration
- [x] 4.1 Run full test suite, verify all 41 tests pass
- [x] 4.2 Manual test with `input/700.kml` — 41 mower paths at 21" width
