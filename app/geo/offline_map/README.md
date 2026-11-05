# Offline map packs (cartography only)

These files are **basemap cartography**. They never touch `app/data/registry.db`.

| File | Role |
|---|---|
| `gaza.vectormap.json` | Street-level OSM extract (roads, water, green, places) for the Gaza working area |
| `gaza.vectormap.json.gz` | Same file, gzip-compressed (~229 KB) — preferred by the server |
| `gaza.tilepack` | *Optional.* Raster WebP tile pack (`TILEPACK` binary). Drop here to enable `/api/geo/tiles/{z}/{x}/{y}.webp` |

Build a tilepack from an MBTiles source (when you have one):

```bash
# from the relationship-map tooling, or any TILEPACK-compatible builder
node scripts/build-tilepack.js path/to/gaza_*.mbtiles app/geo/offline_map/gaza.tilepack
```

Environment overrides (still never point at the registry DB):

- `SIRAJ_VECTORMAP_FILE` — path to a vectormap JSON
- `SIRAJ_TILEPACK_FILE` — path to a `.tilepack`

Attribution: © OpenStreetMap contributors (ODbL). Raster packs may also credit Eurostat GISCO / Copernicus OSM backgrounds.
