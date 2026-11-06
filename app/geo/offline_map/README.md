# Offline map packs (cartography only)

These files are **basemap cartography**. They never touch `app/data/registry.db`.
Together they cover the whole world for every offline map type the application
offers — a requirement of the registry: no place on Earth may fall off the map.

| File | Role |
|---|---|
| `world.vectormap.json` | World vector basemap (borders, coastlines, rivers, lakes, urban areas, 7.3k cities) from Natural Earth — public domain |
| `world.vectormap.json.gz` | Same file, gzip-compressed (~1.1 MB) — preferred by the server |
| `gaza.vectormap.json` | Street-level OSM extract (roads, water, green, places) for the Gaza working area |
| `gaza.vectormap.json.gz` | Same file, gzip-compressed (~229 KB) — preferred by the server |
| `world.tilepack` | Raster WebP tile pack (`TILEPACK` binary): the whole world at z0–z6 plus street-level z7–15 over the working area (~7.5 MB) |

The server **merges the world and detail vectormaps** into one payload:
`/api/geo/vectormap` serves world coverage everywhere and street detail where the
working-area extract carries it. The raster pack serves
`/api/geo/tiles/{z}/{x}/{y}.webp` and enables the map workspace's raster mode.

Rebuild the packs from their sources:

```bash
# vector basemap layers (countries, provinces, urban, places, …)
python3 -m app.geo.basemap_build   --source /path/to/natural-earth-geojson --target app/geo/basemap.sqlite
python3 -m app.geo.vectormap_build --source /path/to/natural-earth-geojson
# raster tiles (world z0–6 + working-area streets z7–15)
python3 -m app.geo.tilepack_build
```

The Natural Earth geojsons ship in
[nvkelso/natural-earth-vector](https://github.com/nvkelso/natural-earth-vector)
(`geojson/` — 1:110m, 1:50m, and 1:10m). The street extract is produced from
OpenStreetMap (Overpass, `out geom`).

Environment overrides (still never point at the registry DB):

- `SIRAJ_VECTORMAP_FILE` — path to the street-detail vectormap JSON
- `SIRAJ_TILEPACK_FILE` — path to a `.tilepack` (falls back to `world.tilepack`, then `gaza.tilepack`)

Attribution: Natural Earth (public domain); © OpenStreetMap contributors (ODbL)
for the street extract and derived raster tiles.
