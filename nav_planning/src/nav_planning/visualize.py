"""Generate standalone HTML visualization of mower paths on a satellite map."""

from __future__ import annotations

import json

# Distinct colors for up to 20 mowers, then cycles
COLORS = [
    "#e6194b", "#3cb44b", "#4363d8", "#f58231", "#911eb4",
    "#42d4f4", "#f032e6", "#bfef45", "#fabed4", "#469990",
    "#dcbeff", "#9A6324", "#800000", "#aaffc3", "#808000",
    "#000075", "#a9a9a9", "#e6beff", "#fffac8", "#ffd8b1",
]


def generate_visualization_html(
    mower_paths: list[list[tuple[float, float]]],
    output_path: str,
) -> None:
    """Write a standalone HTML file visualizing mower paths on a Leaflet map.

    Args:
        mower_paths: List of per-mower paths, each a list of (lat, lon) tuples.
        output_path: File path for the HTML output.
    """
    if not mower_paths:
        raise ValueError("No mower paths to visualize")

    # Build JS data: array of arrays of [lat, lon]
    paths_js = json.dumps(
        [[[lat, lon] for lat, lon in path] for path in mower_paths]
    )
    colors_js = json.dumps(
        [COLORS[i % len(COLORS)] for i in range(len(mower_paths))]
    )

    # Compute bounds for auto-fit
    all_lats = [lat for path in mower_paths for lat, lon in path]
    all_lons = [lon for path in mower_paths for lat, lon in path]
    bounds_js = json.dumps([
        [min(all_lats), min(all_lons)],
        [max(all_lats), max(all_lons)],
    ])

    html = _HTML_TEMPLATE.replace("__PATHS__", paths_js)
    html = html.replace("__COLORS__", colors_js)
    html = html.replace("__BOUNDS__", bounds_js)
    html = html.replace("__NUM_MOWERS__", str(len(mower_paths)))

    with open(output_path, "w") as f:
        f.write(html)


_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Mower Path Visualization</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
  #map { position: absolute; top: 0; left: 0; right: 0; bottom: 0; }
  #controls {
    position: absolute; top: 10px; right: 10px; z-index: 1000;
    background: rgba(255,255,255,0.95); border-radius: 8px;
    padding: 12px 16px; box-shadow: 0 2px 8px rgba(0,0,0,0.3);
    max-height: 90vh; overflow-y: auto; min-width: 180px;
  }
  #controls h3 { margin: 0 0 8px; font-size: 14px; }
  #controls button {
    padding: 6px 16px; margin-right: 6px; border: 1px solid #ccc;
    border-radius: 4px; background: #fff; cursor: pointer; font-size: 13px;
  }
  #controls button.active { background: #4363d8; color: #fff; border-color: #4363d8; }
  .speed-row { margin: 8px 0; font-size: 13px; }
  .speed-row input { width: 100px; vertical-align: middle; }
  .mower-toggle { display: flex; align-items: center; margin: 4px 0; font-size: 13px; cursor: pointer; }
  .mower-toggle input { margin-right: 6px; }
  .color-dot {
    display: inline-block; width: 12px; height: 12px;
    border-radius: 50%; margin-right: 6px;
  }
  .progress-row { margin: 8px 0; font-size: 12px; color: #666; }
</style>
</head>
<body>
<div id="map"></div>
<div id="controls">
  <h3>Mower Paths</h3>
  <div>
    <button id="playBtn" onclick="togglePlay()">Play</button>
    <button id="resetBtn" onclick="resetAnimation()">Reset</button>
  </div>
  <div class="speed-row">
    Speed: <input type="range" id="speedSlider" min="1" max="10" value="3">
    <span id="speedLabel">3x</span>
  </div>
  <div class="progress-row" id="progressLabel">Ready</div>
  <hr style="margin: 8px 0; border: none; border-top: 1px solid #eee;">
  <div id="toggles"></div>
</div>

<script>
(function() {
  var paths = __PATHS__;
  var colors = __COLORS__;
  var bounds = __BOUNDS__;
  var numMowers = __NUM_MOWERS__;

  var map = L.map('map', { zoomControl: true });
  L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', {
    attribution: 'Tiles: Esri World Imagery',
    maxZoom: 22
  }).addTo(map);
  map.fitBounds(bounds, { padding: [40, 40] });

  // Draw polylines and create markers
  var polylines = [];
  var markers = [];
  var visible = [];
  var distances = []; // cumulative distance arrays per path

  for (var m = 0; m < numMowers; m++) {
    var pl = L.polyline(paths[m], { color: colors[m], weight: 3, opacity: 0.8 }).addTo(map);
    polylines.push(pl);
    visible.push(true);

    var marker = L.circleMarker(paths[m][0], {
      radius: 7, color: '#fff', weight: 2,
      fillColor: colors[m], fillOpacity: 1
    }).addTo(map);
    markers.push(marker);

    // Precompute cumulative distances
    var dists = [0];
    for (var i = 1; i < paths[m].length; i++) {
      var dlat = paths[m][i][0] - paths[m][i-1][0];
      var dlon = paths[m][i][1] - paths[m][i-1][1];
      dists.push(dists[i-1] + Math.sqrt(dlat*dlat + dlon*dlon));
    }
    distances.push(dists);
  }

  // Build mower toggles
  var togglesDiv = document.getElementById('toggles');
  for (var m = 0; m < numMowers; m++) {
    (function(idx) {
      var label = document.createElement('label');
      label.className = 'mower-toggle';
      var cb = document.createElement('input');
      cb.type = 'checkbox';
      cb.checked = true;
      cb.onchange = function() {
        visible[idx] = cb.checked;
        if (cb.checked) {
          polylines[idx].addTo(map);
          markers[idx].addTo(map);
        } else {
          polylines[idx].remove();
          markers[idx].remove();
        }
      };
      var dot = document.createElement('span');
      dot.className = 'color-dot';
      dot.style.background = colors[idx];
      label.appendChild(cb);
      label.appendChild(dot);
      label.appendChild(document.createTextNode('Mower ' + (idx + 1)));
      togglesDiv.appendChild(label);
    })(m);
  }

  // Animation state
  var playing = false;
  var progress = 0; // 0..1
  var animFrame = null;
  var lastTime = null;
  var speedSlider = document.getElementById('speedSlider');
  var speedLabel = document.getElementById('speedLabel');
  var progressLabel = document.getElementById('progressLabel');
  var playBtn = document.getElementById('playBtn');

  speedSlider.oninput = function() {
    speedLabel.textContent = speedSlider.value + 'x';
  };

  function getMaxDist() {
    var mx = 0;
    for (var m = 0; m < numMowers; m++) {
      var d = distances[m][distances[m].length - 1];
      if (d > mx) mx = d;
    }
    return mx;
  }

  function interpolate(pathIdx, t) {
    var totalDist = distances[pathIdx][distances[pathIdx].length - 1];
    var targetDist = t * totalDist;
    var pts = paths[pathIdx];
    var dists = distances[pathIdx];

    if (targetDist <= 0) return pts[0];
    if (targetDist >= totalDist) return pts[pts.length - 1];

    for (var i = 1; i < dists.length; i++) {
      if (dists[i] >= targetDist) {
        var segLen = dists[i] - dists[i-1];
        var frac = segLen > 0 ? (targetDist - dists[i-1]) / segLen : 0;
        return [
          pts[i-1][0] + frac * (pts[i][0] - pts[i-1][0]),
          pts[i-1][1] + frac * (pts[i][1] - pts[i-1][1])
        ];
      }
    }
    return pts[pts.length - 1];
  }

  function animate(timestamp) {
    if (!playing) return;
    if (lastTime === null) lastTime = timestamp;
    var dt = (timestamp - lastTime) / 1000;
    lastTime = timestamp;

    var speed = parseFloat(speedSlider.value);
    // Base duration: 30 seconds at 1x speed
    progress += (dt * speed) / 30;

    if (progress >= 1) {
      progress = 1;
      playing = false;
      playBtn.textContent = 'Play';
      playBtn.classList.remove('active');
    }

    for (var m = 0; m < numMowers; m++) {
      if (!visible[m]) continue;
      var pos = interpolate(m, progress);
      markers[m].setLatLng(pos);
    }

    progressLabel.textContent = Math.round(progress * 100) + '% complete';
    if (playing) animFrame = requestAnimationFrame(animate);
  }

  window.togglePlay = function() {
    if (playing) {
      playing = false;
      playBtn.textContent = 'Play';
      playBtn.classList.remove('active');
      if (animFrame) cancelAnimationFrame(animFrame);
    } else {
      if (progress >= 1) progress = 0;
      playing = true;
      lastTime = null;
      playBtn.textContent = 'Pause';
      playBtn.classList.add('active');
      animFrame = requestAnimationFrame(animate);
    }
  };

  window.resetAnimation = function() {
    playing = false;
    progress = 0;
    lastTime = null;
    playBtn.textContent = 'Play';
    playBtn.classList.remove('active');
    if (animFrame) cancelAnimationFrame(animFrame);
    for (var m = 0; m < numMowers; m++) {
      markers[m].setLatLng(paths[m][0]);
    }
    progressLabel.textContent = 'Ready';
  };
})();
</script>
</body>
</html>
"""
