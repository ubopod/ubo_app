# ESP-IDF component wrapper for the platform-neutral web-grpc client core
# (ubo_lvgl/client + nanopb). Compiles both framing codecs, the RPC layer, view
# translator, keymap, the generated nanopb bindings, and the transport selected
# by UBO_TRANSPORT. Excludes the libcurl transport and the pthread desktop main.
set(UBO_ROOT "${CMAKE_CURRENT_LIST_DIR}/../../..")
set(CLIENT "${UBO_ROOT}/client")
set(NANOPB "${UBO_ROOT}/third_party/nanopb")

# Uniform with the desktop cmake flag: -DUBO_TRANSPORT=grpc_web selects the
# Envoy/esp_http_client path; default tcp_lite is the raw-TCP path.
if(NOT DEFINED UBO_TRANSPORT)
    set(UBO_TRANSPORT "tcp_lite")
endif()

if(UBO_TRANSPORT STREQUAL "tcp_lite")
    set(UBO_TRANSPORT_SRCS "${CLIENT}/tcp_lite_transport.c" "${CLIENT}/ubo_rpc_tcp_lite.c")
    set(UBO_TRANSPORT_DEFS "UBO_TRANSPORT_TCP_LITE")
else()
    set(UBO_TRANSPORT_SRCS "${CLIENT}/http_transport_esp.c" "${CLIENT}/ubo_rpc.c")
    set(UBO_TRANSPORT_DEFS "")
endif()

# esp_http_client is REQUIRES'd unconditionally (not gated on UBO_TRANSPORT):
# ESP-IDF's early "component requirements expansion" pass doesn't reliably see
# custom `-D` cache flags the way the main configure pass does, so a REQUIRES
# list computed from UBO_TRANSPORT here can desync between passes and silently
# drop esp_http_client for a grpc_web build (`esp_http_client.h: No such file`)
# depending on what UBO_TRANSPORT's *default* happens to be. Linking it in
# unconditionally is harmless for tcp_lite builds -- `-ffunction-sections
# -fdata-sections` + linker `--gc-sections` (ESP-IDF's default) drops the
# unreferenced esp_http_client code from the final image when http_transport_esp.c
# isn't compiled in.
idf_component_register(
    SRCS
        "${CLIENT}/grpc_web_frame.c"
        "${CLIENT}/tcp_lite_frame.c"
        "${CLIENT}/client_core.c"
        "${CLIENT}/view_translate.c"
        "${CLIENT}/keymap.c"
        ${UBO_TRANSPORT_SRCS}
        "${CLIENT}/proto/ubo_client.pb.c"
        "${NANOPB}/pb_common.c"
        "${NANOPB}/pb_encode.c"
        "${NANOPB}/pb_decode.c"
    INCLUDE_DIRS
        "${CLIENT}"
        "${CLIENT}/proto"
        "${NANOPB}"
    REQUIRES
        esp_http_client
        ubo_lvgl_renderer
)

# Pointer-mode dynamic fields, and 32-bit pb_size_t so large bytes fields
# (camera frames ~172KB > the 16-bit default) decode. PUBLIC so every consumer
# of ubo_client.pb.h sees the same nanopb ABI.
target_compile_definitions(${COMPONENT_LIB} PUBLIC PB_ENABLE_MALLOC PB_FIELD_32BIT)
# PUBLIC (not PRIVATE): the main component REQUIRES this one and needs to see
# UBO_TRANSPORT_TCP_LITE too, to pick the matching Kconfig endpoint string.
if(UBO_TRANSPORT_DEFS)
    target_compile_definitions(${COMPONENT_LIB} PUBLIC ${UBO_TRANSPORT_DEFS})
endif()
