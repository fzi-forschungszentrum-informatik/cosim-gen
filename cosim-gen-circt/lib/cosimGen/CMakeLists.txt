add_circt_dialect_library(CIRCTCosimGen
        HWSubGraph.cpp
        HWDme.cpp
        HWOpt.cpp
        HWOptInterfaces.cpp
        HWMoveCombUp.cpp
        HWTaint.cpp
        HWMarkComb.cpp
        HWPropPorts2TLM.cpp
        HWKeepPorts.cpp
        HWKeepPath.cpp
        HWReleaseKeep.cpp
        HWRenameTop.cpp
        HWRemoveSV.cpp
        HWRemoveOM.cpp
        HWRemoveCustomAttr.cpp
        HWInlineTrivial.cpp
        HWStateJson.cpp
        HWMakefile.cpp
        PortTagging.cpp
        FIRRTLKeepInterfaces.cpp
        FIRRTLRemoveInline.cpp

        ADDITIONAL_HEADER_DIRS
        ${PROJECT_SOURCE_DIR}/include

        DEPENDS
        CIRCTCosimGenPassesIncGen

        LINK_LIBS PUBLIC
        MLIRIR
        MLIRInferTypeOpInterface
        MLIRFuncDialect
        CIRCTFIRRTL
        CIRCTSV
        CIRCTHW
)
