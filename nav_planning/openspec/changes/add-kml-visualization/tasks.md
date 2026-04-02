## Tasks

### 1. KML module
- [x] 1.1 Create `kml.py` with helpers: `_haversine_distance`, `_compute_heading`, `_kml_color`, KML namespace setup
- [x] 1.2 Implement `generate_kml_track()` — gx:Track per mower with synthetic timestamps and distinct colors
- [x] 1.3 Implement `generate_kml_tour()` — gx:Tour with FlyTo playlist following mower 1, static LineString paths for all mowers

### 2. CLI integration
- [x] 2.1 Add `--kml-track` and `--kml-tour` flags to `mow` command in `cli.py`
- [x] 2.2 Wire flags to `kml.py` functions, output `_track.kml` / `_tour.kml`

### 3. Tests
- [x] 3.1 Unit tests for `generate_kml_track`: file creation, gx:Track elements, timestamps, multi-mower placemarks, empty input error
- [x] 3.2 Unit tests for `generate_kml_tour`: file creation, gx:Tour/FlyTo elements, LookAt params, static LineString paths, empty input error
- [x] 3.3 CLI tests: `--kml-track` / `--kml-tour` produce files, omitting flags produces no files
- [x] 3.4 Run full test suite, confirm all 74 pass
