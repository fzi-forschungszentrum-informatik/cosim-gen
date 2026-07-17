add_circt_dialect_library(CIRCTCosimGenHelper
        PathComp.cpp

        ADDITIONAL_HEADER_DIRS
        ${PROJECT_SOURCE_DIR}/include

        LINK_LIBS PUBLIC
        MLIRIR
        MLIRInferTypeOpInterface
        MLIRFuncDialect
        CIRCTFIRRTL
)
