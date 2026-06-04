# ESP-IDF component wrapper for the platform-neutral web-grpc client core
# (ubo_lvgl/client + nanopb). Compiles the framing codec, RPC layer, view
# translator, keymap, the generated nanopb bindings, and the esp_http_client
# transport. Excludes the libcurl transport and the pthread desktop main.
set(UBO_ROOT "${CMAKE_CURRENT_LIST_DIR}/../../..")
set(CLIENT "${UBO_ROOT}/client")
set(NANOPB "${UBO_ROOT}/third_party/nanopb")

idf_component_register(
    SRCS
        "${CLIENT}/grpc_web_frame.c"
        "${CLIENT}/ubo_rpc.c"
        "${CLIENT}/view_translate.c"
        "${CLIENT}/keymap.c"
        "${CLIENT}/http_transport_esp.c"
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
