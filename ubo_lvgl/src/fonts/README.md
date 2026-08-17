# Fonts

`ubo_icon_{14,18,24,32}.c` are LVGL fonts generated from
`../../assets/fonts/ArimoNerdFont-Regular.ttf` — the same Nerd Font `ubo_gui`
uses — covering the Material Design Icon glyphs (Private Use Area) that the UI
renders. Text labels use the built-in `lv_font_montserrat_*`.

On desktop and the Pi, `fonts_runtime.c` loads `../../assets/ubo_icons_*.bin`
instead, which covers the whole Nerd-Font MDI range. These compiled-in fonts are
the fallback — and the only icons the **ESP32 firmware** has, since it cannot
load the `.bin` at runtime. An icon missing from the list below therefore
renders blank on the ESP32 while looking fine on desktop/Pi.

## Regenerate

```sh
npm install lv_font_conv   # once
./regen.sh
```

Add the codepoint to the `CODEPOINTS` list in `regen.sh` whenever a service
starts emitting an icon the ESP32 must show, then re-run it — all four sizes are
regenerated together.
