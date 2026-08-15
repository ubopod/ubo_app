# ruff: noqa: D100
AUDIO_MIC_STATE_ICON_PRIORITY = -20
AUDIO_MIC_STATE_ICON_ID = 'audio:mic-state'

# Insert-detect line of the lineout jack. Held high by the board's own pull-up
# with the socket empty; the socket's switch takes it to ground once a plug is
# seated, so an inserted jack reads low.
AUDIO_LINEOUT_DETECT_PIN = 6

AUDIO_SETTINGS_MENU_ID = 'audio:main'
AUDIO_OUTPUT_MENU_ID = 'audio:output'
