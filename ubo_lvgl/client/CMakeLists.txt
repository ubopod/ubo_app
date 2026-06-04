# Native C web-grpc LVGL client. Included from the top-level CMakeLists when
# UBO_WITH_CLIENT is ON. Links the libubo_lvgl renderer, libcurl (HTTP/1.1),
# and the nanopb runtime + committed generated bindings.

find_package(CURL REQUIRED)
find_package(Threads REQUIRED)

set(NANOPB_DIR ${CMAKE_CURRENT_SOURCE_DIR}/../third_party/nanopb)

# nanopb runtime (pointer/malloc mode). Generated files are committed; see
# proto/regen.sh to refresh them when ubo_client.proto changes.
add_library(ubo_nanopb STATIC
    ${NANOPB_DIR}/pb_common.c
    ${NANOPB_DIR}/pb_encode.c
    ${NANOPB_DIR}/pb_decode.c
    ${CMAKE_CURRENT_SOURCE_DIR}/proto/ubo_client.pb.c
)
target_include_directories(ubo_nanopb PUBLIC
    ${NANOPB_DIR}
    ${CMAKE_CURRENT_SOURCE_DIR}/proto
)
# PB_ENABLE_MALLOC: pointer-mode dynamic fields. PB_FIELD_32BIT: widen pb_size_t
# to 32-bit so large bytes fields (camera frames are ~172KB > the 16-bit default
# limit of 65535) decode correctly.
target_compile_definitions(ubo_nanopb PUBLIC PB_ENABLE_MALLOC PB_FIELD_32BIT)

# Manual codegen target (not part of the default build): `cmake --build . --target
# ubo_client_proto_regen`. Requires uv + python protobuf.
add_custom_target(ubo_client_proto_regen
    COMMAND ${CMAKE_CURRENT_SOURCE_DIR}/proto/regen.sh
    WORKING_DIRECTORY ${CMAKE_CURRENT_SOURCE_DIR}/proto
    COMMENT "Regenerating ubo_client.pb.{c,h} via nanopb"
    VERBATIM
)

# Reusable client core (transport + framing + RPC + config), no main / no
# renderer dependency — shared by the client executable and the test harnesses.
# view_translate.c is added in Phase 3.
add_library(ubo_client_core STATIC
    grpc_web_frame.c
    http_transport.c
    ubo_rpc.c
    client_config.c
    view_translate.c
    keymap.c
)
target_include_directories(ubo_client_core PUBLIC
    ${CMAKE_CURRENT_SOURCE_DIR}
    ${CMAKE_CURRENT_SOURCE_DIR}/../include
)
target_link_libraries(ubo_client_core PUBLIC ubo_nanopb CURL::libcurl Threads::Threads)
target_compile_options(ubo_client_core PRIVATE -Wall -Wextra)

add_executable(ubo_lvgl_client client_main.c)
target_link_libraries(ubo_lvgl_client PRIVATE ubo_client_core ubo_lvgl)
target_compile_options(ubo_lvgl_client PRIVATE -Wall -Wextra)

# Phase-2 live probe (needs a running core + Envoy; not a ctest).
add_executable(ubo_client_probe tests/probe.c)
target_link_libraries(ubo_client_probe PRIVATE ubo_client_core)
target_compile_options(ubo_client_probe PRIVATE -Wall -Wextra)

# Phase-3 live render+snapshot harness (renders live views to BMP for parity).
add_executable(ubo_client_render_snapshot tests/render_snapshot.c)
target_link_libraries(ubo_client_render_snapshot PRIVATE ubo_client_core ubo_lvgl)
target_compile_options(ubo_client_render_snapshot PRIVATE -Wall -Wextra)

# Offline layout preview: renders synthetic representative views to BMP (no core)
# for iterating on geometry/fonts at a given panel size.
add_executable(ubo_client_layout_preview tests/layout_preview.c)
target_link_libraries(ubo_client_layout_preview PRIVATE ubo_lvgl)
target_compile_options(ubo_client_layout_preview PRIVATE -Wall -Wextra)

# ── Tests ──
# Phase-0 decode smoke test (proves the curated schema matches server bytes).
add_executable(ubo_client_test_decode tests/test_decode.c)
target_link_libraries(ubo_client_test_decode PRIVATE ubo_nanopb)
target_compile_options(ubo_client_test_decode PRIVATE -Wall -Wextra)

# Phase-1 gRPC-Web framing codec unit tests.
add_executable(ubo_client_test_frame tests/test_frame.c)
target_link_libraries(ubo_client_test_frame PRIVATE ubo_client_core)
target_compile_options(ubo_client_test_frame PRIVATE -Wall -Wextra)

add_test(NAME frame_codec COMMAND ubo_client_test_frame)
add_test(NAME decode_home
         COMMAND ubo_client_test_decode home
                 ${CMAKE_CURRENT_SOURCE_DIR}/tests/fixtures/home_view.bin)
