#===-------------------------------------------------------------------------===
# Dev/test environment for cosim-gen.
#
# See DOCKER.md.
#===-------------------------------------------------------------------------===

#===-------------------------------------------------------------------------===
# Stage 1: builder
#===-------------------------------------------------------------------------===
FROM ubuntu:26.04 AS builder
ENV DEBIAN_FRONTEND=noninteractive

ARG CIRCT_VERSION=1.154.0
ARG VERILATOR_VERSION=v5.050

RUN apt-get update && apt-get install -y --no-install-recommends \
    # common deps
    libc6-dev make clang lld cmake ninja-build git curl ca-certificates \
    pkg-config python3 python3-venv python3-pip \
    # verilator
    autoconf flex bison help2man perl libfl-dev \
    # qemu-fdt
    libglib2.0-dev libpixman-1-dev meson bzip2 \
    # firtool
    libz3-4 \
    && rm -rf /var/lib/apt/lists/*

# --- CIRCT --------------------------------------- --------------------------
RUN curl -fL -o /tmp/circt.tar.gz \
        "https://github.com/llvm/circt/releases/download/firtool-${CIRCT_VERSION}/circt-full-shared-linux-x64.tar.gz" \
    && mkdir -p /opt/circt \
    && tar -xzf /tmp/circt.tar.gz -C /opt/circt --strip-components=1 \
    && rm /tmp/circt.tar.gz
ENV PATH=/opt/circt/bin:${PATH}
ENV LD_LIBRARY_PATH=/opt/circt/lib

# --- Verilator: built from source with clang --------------------------------
RUN git clone --branch "${VERILATOR_VERSION}" --depth 1 \
        https://github.com/verilator/verilator.git /tmp/verilator \
    && cd /tmp/verilator \
    && autoconf \
    && CC=clang CXX=clang++ ./configure --prefix=/opt/verilator \
    && make -j"$(nproc)" \
    && make install \
    && rm -rf /tmp/verilator
ENV PATH=/opt/verilator/bin:${PATH}

# --- qemu-fdt: the in-repo QEMU fork submodule, built with clang ------------
COPY qemu-fdt/ /tmp/qemu-fdt/
RUN cd /tmp/qemu-fdt \
    && mkdir build && cd build \
    && ../configure \
        --target-list=riscv64-softmmu,riscv32-softmmu \
        --prefix=/opt/qemu \
        --cc=clang --cxx=clang++ \
    && make -j"$(nproc)" \
    && make install \
    && rm -rf /tmp/qemu-fdt
ENV PATH=/opt/qemu/bin:${PATH}

# --- cosim-gen cli ---------------------------------------------------------
COPY cosim-gen-cli/ /opt/cosim-gen/cosim-gen-cli/
RUN python3 -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir --upgrade pip \
    && /opt/venv/bin/pip install --no-cache-dir -e /opt/cosim-gen/cosim-gen-cli lit
ENV PATH=/opt/venv/bin:${PATH}

# --- cosim-gen-circt -------------------------------------------------------
COPY cosim-gen-circt/ /opt/cosim-gen/cosim-gen-circt/
RUN cmake -S /opt/cosim-gen/cosim-gen-circt -B /opt/cosim-gen/cosim-gen-circt/build -GNinja \
        -DCMAKE_BUILD_TYPE=Release \
        -DCMAKE_C_COMPILER=clang \
        -DCMAKE_CXX_COMPILER=clang++ \
        -DLLVM_ENABLE_ZSTD=Off \
        -DLLVM_EXTERNAL_LIT=/opt/venv/bin/lit \
    && ninja -C /opt/cosim-gen/cosim-gen-circt/build check-cosim-gen

#===-------------------------------------------------------------------------===
# Stage 2: runtime
#===-------------------------------------------------------------------------===
FROM ubuntu:26.04
ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    clang lld make cmake ninja-build binutils \
    python3 libz3-4 pkg-config xz-utils \
    libsystemc-dev device-tree-compiler perl \
    libglib2.0-0 libpixman-1-0 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /opt/circt /opt/circt
COPY --from=builder /opt/verilator /opt/verilator
COPY --from=builder /opt/qemu /opt/qemu
COPY --from=builder /opt/venv /opt/venv
COPY --from=builder /opt/cosim-gen /opt/cosim-gen

ENV PATH=/opt/circt/bin:/opt/verilator/bin:/opt/qemu/bin:/opt/venv/bin:${PATH}
ENV LD_LIBRARY_PATH=/opt/circt/lib
ENV CC=clang
ENV CXX=clang++

WORKDIR /work
CMD ["bash"]
