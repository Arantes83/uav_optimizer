cmake_minimum_required(VERSION 3.15)
project(uvpack VERSION 1.0.0 LANGUAGES CXX)
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

add_library(uvpack SHARED uvpack.cpp uvpack.h)

if(MSVC)
    target_compile_options(uvpack PRIVATE /O2 /GL /arch:AVX2)
    target_link_options(uvpack PRIVATE /LTCG)
    set_target_properties(uvpack PROPERTIES OUTPUT_NAME "lib_uvpack")
else()
    target_compile_options(uvpack PRIVATE -O3 -march=native -fvisibility=hidden)
    if(APPLE)
        set_target_properties(uvpack PROPERTIES
            OUTPUT_NAME "lib_uvpack" PREFIX "lib" SUFFIX ".dylib")
    else()
        set_target_properties(uvpack PROPERTIES
            OUTPUT_NAME "lib_uvpack" PREFIX "lib" SUFFIX ".so")
    endif()
endif()

# Instala direto para o addon
set(ADDON_LIB_DIR "${CMAKE_SOURCE_DIR}/../uvpack_lib"
    CACHE PATH "Destino da DLL dentro do addon")

install(TARGETS uvpack
    LIBRARY DESTINATION "${ADDON_LIB_DIR}"
    RUNTIME DESTINATION "${ADDON_LIB_DIR}")
