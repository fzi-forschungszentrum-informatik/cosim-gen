# Docker dev environment

A self-contained image with the whole toolchain `cosim` needs, so using it doesn't
require hand-assembling CIRCT/LLVM, Verilator, SystemC, dtc, and the `qemu-fdt` fork
on your host.

## Build

The build context needs `qemu-fdt/` and `cosim-gen-cli/third_party/libsystemctlm-soc/`
populated — both are git submodules, so fetch them first if the repo wasn't cloned with
`--recurse-submodules` (the `Dockerfile` `COPY`s these directories in; an uninitialized
submodule copies in as an empty directory and the build fails):

```sh
git submodule update --init
```

Then, from the repo root (the build context - the image needs `cosim-gen-cli/`,
`cosim-gen-circt/`, and `qemu-fdt/`):

```sh
docker build -t cosim-gen .
```

This is a multi-stage build: a `builder` stage compiles Verilator and `qemu-fdt`
from source, downloads the prebuilt CIRCT release, and builds `cosim-gen-circt`;
a slimmer `runtime` stage copies in just the resulting install trees (under
`/opt/cosim-gen`). Expect the first build to take a while (Verilator and QEMU are
both full source builds) - subsequent builds reuse Docker's layer cache for
anything untouched.

## Use it against your own project

`/work` is left empty in the image - it's the mount point for whatever project
you actually want to run `cosim` against, not this repo. `--user` matches the
container process to your host UID/GID so anything `cosim build` writes into
your mounted tree (build/ dirs, generated sim.cpp, ...) comes back owned by you,
not root:

```sh
docker run --rm -it --user "$(id -u):$(id -g)" -v "$PWD":/work cosim-gen bash
# now /work is your project; e.g.:
cosim doctor -C /work/cosim.json
cosim build -C /work/cosim.json
cosim run rtl -C /work/cosim.json
```

`cosim`, `cosim-extract`, `cosim-gen-opt`, etc. resolve against the toolchain baked
into `/opt/cosim-gen` and `/opt/{circt,verilator,qemu}`, plus SystemC's apt-installed
headers/lib - none of that lives under `/work`, so
mounting over it doesn't shadow anything the tool needs. `cosim doctor -C <cosim.json>`
reports every resolved tool path if something looks wrong.

## Run this repo's own example suite

`cosim-gen-cli` and `cosim-gen-circt` (the tool) are baked into the image under
`/opt/cosim-gen`, but `example/` is not - it's a sample project, not part of the
tool, so exercising it means bind-mounting this repo over `/work` like any other
project:

```sh
docker run --rm -it --user "$(id -u):$(id -g)" -v "$PWD":/work cosim-gen bash run-tests.sh
```
