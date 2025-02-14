These instructions try to install RISCOF, RISC-V toolchain and SAIL under Arch Linux needed for running `runtests.sh`.

# Install general tools

```bash
sudo pacman --sync --refresh
sudo pacman --sync --needed python python-pip git python-virtualenv
```

# Install RISCOF

Create virtual environment:
```bash
# cd some_work_directory_without_spaces
virtualenv venv-riscof
```

Activate virtual environment:
```bash
source venv-riscof/bin/activate
```

Install known working version of RISCOF in virtual environment.

```bash
pip install git+https://github.com/riscv/riscof.git@d38859f85fe407bcacddd2efcd355ada4683aee4
```

Test if working:
```bash
riscof --help
```

Deactivate virtual environment:
```bash
deactivate
```

# Install RISCV-GNU Toolchain

```bash
yay --sync riscv32-gnu-toolchain-elf-bin
```

Test RISCV gcc:
```bash
riscv32-unknown-elf-gcc --version
```

# SAIL

Compile reference emulator:
```bash
sudo pacman --sync --needed opam z3 cmake

opam init -y --disable-sandboxing
opam switch create 5.1.0
opam install sail -y
eval $(opam config env)
git clone https://github.com/riscv/sail-riscv.git
cd sail-riscv
./build_simulators.sh
sudo ln -s "$(pwd)/build/c_emulator/riscv_sim_rv64d" /usr/local/bin/riscv_sim_RV64
sudo ln -s "$(pwd)/build/c_emulator/riscv_sim_rv32d" /usr/local/bin/riscv_sim_RV32
```

Test:
```bash
sail --help
riscv_sim_RV32
riscv_sim_RV64
```

# Running tests

Activate virtual environment:
```bash
source venv-riscof/bin/activate
```

Then execute `runtests.sh`.

