# Fonts

`ubo_icon_18.c` / `ubo_icon_14.c` are LVGL fonts generated from
`../../assets/fonts/ArimoNerdFont-Regular.ttf` — the same Nerd Font `ubo_gui`
uses — covering the Material Design Icon glyphs (Private Use Area) that the UI
renders. Text labels use the built-in `lv_font_montserrat_*`.

## Regenerate

```sh
npm install lv_font_conv   # once
lv_font_conv \
  --font ../../assets/fonts/ArimoNerdFont-Regular.ttf \
  --size 18 --bpp 4 --format lvgl --no-compress \
  -r 0x0F2C7 -r 0xF0131 -r 0xF02FC -r 0xF035C -r 0xF044A -r 0xF0459 \
  -r 0xF0504 -r 0xF0C52 -r 0xF1A4E -r 0xF05A9 -r 0xF0493 -r 0xF00AF \
  -r 0xF057E -r 0xF02DC -r 0xF0140 -r 0xF0143 -r 0xF0425 -r 0xF02D1 \
  -o ubo_icon_18.c
```

Notes:
- `--no-compress` is required unless `LV_USE_FONT_COMPRESSED` is enabled in
  `lv_conf.h`.
- Add `-r 0x...` codepoints for any new icons. The 9 codepoints hardcoded in the
  Kivy client are included; the rest arrive at runtime from services. For full
  dynamic coverage on the Pi we can switch to a runtime-loaded `.bin` font over
  the whole Nerd-Font MDI range (`0xF0001-0xF1AF0`).
