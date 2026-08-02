# Home Assistant Wyoming integration

This service gives Home Assistant access to the Pod's microphone/speaker through
the Wyoming satellite protocol and provides Wyoming ASR, TTS, and conversation
engines backed by the Pod assistant.

## Security model

Wyoming has no protocol authentication or encryption. Both listeners are disabled
by default and the service defaults to loopback-only binding. Do not expose either
port through a router, reverse proxy, or VPN without an additional authenticated
transport.

Add one or more access policies from **Settings → Assistant → Satellites →
Wyoming**. Policies **combine**: a peer is admitted if it matches any of them, so
a Docker bridge and explicit LAN addresses can be permitted at the same time, and
each can be withdrawn on its own.

- **Docker bridge** permits only the subnet Docker actually assigned to the
  shared `ubo_net` bridge, resolved from the daemon each time the listeners are
  reconciled. The private ranges Docker draws from are ordinary RFC1918 space, so
  trusting the range rather than the live subnet would authorize every host on a
  LAN that happens to be numbered inside it. If the bridge cannot be resolved it
  contributes nothing — and if it is the only policy, no listener is opened. The
  bundled Home Assistant composition maps `host.docker.internal` to the Pod host.
- **IP address or CIDR** permits exactly what it names. Host names are rejected:
  they resolve at an unpredictable moment to an address nobody reviewed.

**With no policies the listeners bind `127.0.0.1`** and nothing off-device can
reach them. That is the default, and it is what "local only" means here — it is
not a policy you add but the absence of any, so removing the last policy returns
the device to it.

Adding a policy is what opens the port to the LAN, so it raises a sticky warning.
Listeners can be announced with mDNS/Zeroconf whenever at least one policy
exists; the toggle is in the same menu. Docker clients reach the Pod through the
host-gateway hostname and do not need the advertisement.

## Home Assistant configuration

1. Enable the desired listener(s) under **Settings → Assistant → Satellites →
   Wyoming** on the Pod.
2. Add the matching access policy. For the bundled Home Assistant container add
   **Docker bridge** and use `host.docker.internal`; for a separate installation
   add its source **IP address or CIDR**. Both can be present at once.
3. Add the integrations in Home Assistant:
   - Wyoming satellite: `host.docker.internal:10700`
   - Wyoming ASR, TTS, and conversation: `host.docker.internal:10600`

The same ASR/TTS/conversation port accepts the three Wyoming engine request types.
Use the assistant settings on the Pod to choose their underlying providers and
voices.

## Wake word

The satellite detects its wake word **on-device**, using the Pod's own Vosk and
OpenWakeWord engines. Configure it under **Settings → Speech Recognition → Wake
Up → Phrases → Home Assistant**; a fresh install ships one Vosk phrase (`hey home
assistant`, overridable with `UBO_HOME_ASSISTANT_WAKE_PHRASE`). An upgrade keeps
its existing wake configuration, so add the phrase there manually.

Consequences worth knowing:

- **Home Assistant needs no wake-word engine.** The satellite asks for a pipeline
  run starting at the ASR stage, and Home Assistant only requires a wake-word
  entity for a run that starts at the wake stage. Nothing else has to be
  installed — which matters for a container install, where add-ons such as
  openWakeWord are not available. The pipeline does still need a
  speech-to-text engine.
- **The microphone stays on the Pod between commands.** Audio is only forwarded
  from the moment a wake word fires until Home Assistant reports the end of the
  command (`voice-stopped` from its voice-activity detection, or `transcript`
  when speech-to-text completes), bounded by `MAX_UTTERANCE_SECONDS`.
- Audio is captured from the wake word onward with no pre-roll, matching the
  on-device assistant, so a command must follow the wake word rather than run
  into it.
- **The LED ring is green while Home Assistant is listening**, and dark again as
  soon as the command ends — a different colour from the blue the on-device
  voice-shortcut listener uses, so the ring says which one has the microphone.
  Every exit from an utterance (end of command, error, timeout, pause, dropped
  connection) darkens it, so a lit ring always means something is listening.

## Operational limits

Only one satellite can be connected at once; a new authenticated-by-policy client
replaces the prior one. Engine requests are bounded to two concurrent pipelines,
and audio requests have size and format validation before they enter the assistant.
Disconnecting a Wyoming engine client cancels its correlated assistant request.

Home Assistant's speech clients stop reading only on `transcript` (ASR) and
`audio-stop` (TTS); they ignore `error` and apply no timeout of their own. A
failed ASR or TTS request therefore sends `error` **and closes the connection**,
which is what makes it fail rather than hang. The conversation client is the
exception: it treats `not-handled` as terminal, so failures there answer
`not-handled` and leave the connection open.

The conversation agent is one-turn and text-only: it ignores the conversation
context Home Assistant supplies and runs with tool calling disabled, so it cannot
control the home. This is reflected in its advertised `Info`
(`supports_home_control=False`, `supports_handled_streaming=False`).

A `synthesize` request's `voice` field is ignored; the Pod's selected voice is
authoritative and is what the service advertises.
