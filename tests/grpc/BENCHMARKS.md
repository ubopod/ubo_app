# gRPC Serialization Benchmarks

## Running

```bash
uv run python tests/grpc/bench_serialization.py
```

Requires proto bindings to be generated first (`uv run poe proto`).

## Results (2026-03-14, macOS, Apple Silicon)

Measured after caching and BasicType flattening optimizations in
`ubo_app/rpc/`.

### `build_message` (Python -> Proto)

| Payload                                    | Before (us) | After (us) | Speedup |
|--------------------------------------------|-------------|------------|---------|
| ViewChangedEvent + MenuView (4 items)      |        1101 |        535 |   2.1x  |
| ViewChangedEvent + MenuView (10 items)     |        1890 |        838 |   2.3x  |
| ViewChangedEvent + HomeView (3 items)      |         806 |        396 |   2.0x  |
| ViewChangedEvent + AppView (5 extra\_data) |        1059 |        454 |   2.3x  |
| MenuViewData only (4 items)               |         626 |        279 |   2.2x  |
| StatusBarData                              |         371 |        179 |   2.1x  |
| Single MenuItemData                        |          75 |         40 |   1.9x  |

### `_pack_to_any` (store subscriptions)

| Payload             | Before (us) | After (us) | Speedup |
|---------------------|-------------|------------|---------|
| string primitive    |          53 |         33 |   1.6x  |
| int primitive       |          39 |         32 |   1.2x  |
| bool primitive      |          46 |         32 |   1.4x  |
| None primitive      |          30 |         21 |   1.4x  |
| MenuViewData object |        1171 |        657 |   1.8x  |

### Micro-operations

| Operation              | Before     | After    | Speedup |
|------------------------|------------|----------|---------|
| snake\_case x10 names  |    62 us   |  1.2 us  |   53x   |
| get\_class (cached)    |   5.6 us   |  0.1 us  |   56x   |

## What was optimized

1. **LRU caching** for `betterproto.casing.snake_case()` and `pascal_case()` (512 entries)
2. **Dict caching** for `get_class()` lookups in both serialization directions
3. **Generated class registry** (`_class_registry.py`) mapping proto class names to
   Python module paths — eliminates `importlib.import_module()` + `dir()` on cold calls
4. **Primitive short-circuit** in `_pack_to_any()` — skips `build_message()` for
   `str | int | float | bool | bytes | None`
5. **Flattened BasicType** — collapsed `BasicType(optional BasicTypeOptional items)`
   into `BasicType(oneof: string/int64/float/bool/bytes)`, removing one proto message
   layer per scalar in `extra_data` maps
