-- Pin the WM8960 HAT as the preferred default audio device.
--
-- Every ubo-app playback path opens the ALSA `default` PCM (simpleaudio in
-- `AudioManager.play_sample`, alsaaudio in `play_sequence`), and volume/mute
-- open the `default` CTL. Because `libasound2-plugins` ships a hook that
-- redirects both to PulseAudio whenever a server is running, all of them land
-- on whatever sink WirePlumber picked as default -- `/etc/asound.conf` never
-- gets a say.
--
-- Out of the box every ALSA sink gets `priority.session = 1000`, so that pick
-- is a three-way tie between the HAT and the two vc4 HDMI outputs. With no
-- monitor attached the HDMI cards have no available route and the HAT wins by
-- elimination; plug a monitor in and an HDMI sink becomes eligible and can take
-- the tie, silently moving playback (and the volume knob) to the monitor's
-- speakers.
--
-- Breaking the tie explicitly makes the HAT the deterministic default. This
-- only affects *automatic* selection: an explicit user choice is stored as
-- `default.configured.audio.sink` and still outranks these priorities.

alsa_monitor.rules = alsa_monitor.rules or {}

table.insert(alsa_monitor.rules, {
  matches = {
    { { 'alsa.card_name', 'equals', 'wm8960-soundcard' } },
  },
  apply_properties = {
    ['priority.driver'] = 2000,
    ['priority.session'] = 2000,
  },
})

table.insert(alsa_monitor.rules, {
  matches = {
    { { 'alsa.card_name', 'matches', 'vc4-hdmi*' } },
  },
  apply_properties = {
    ['priority.driver'] = 100,
    ['priority.session'] = 100,
  },
})
