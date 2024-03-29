This is intended for me only. It contains code and hints on how to use [RISCOF](https://riscof.readthedocs.io/) to run [riscv-non-isa](https://github.com/riscv-non-isa/riscv-arch-test) test using my [Linux implementation](https://github.com/atoomnetmarc/RISC-V-emulator-Native) of my [RISC-V emulator](https://github.com/atoomnetmarc/RISC-V-emulator).

# Hints

Use Ubuntu 22.

Read and execute the [RISCOF quickstart](https://riscof.readthedocs.io/en/stable/installation.html) to prime your machine with all the needed tools.

## Compile `rve`

Compile https://github.com/atoomnetmarc/RISC-V-emulator-Native

You are done when you can execute `rve` from the commandline.

## Configure ISA

RISC-V emulator isa is configured in [rve/rve_isa.yaml](rve/rve_isa.yaml)

## RISCOF Plugin

The plugin to interface the RISC-V emulator to RISCOF is [rve/riscof_rve.py](rve/riscof_rve.py)

## Execute tests

`riscof run --no-browser --config=config.ini --suite=riscv-arch-test/riscv-test-suite/ --env=riscv-arch-test/riscv-test-suite/env`

## Report

The test report will be put into the directory called `riscof_work`.

# License

I license my code Apache2.0, however check the files for individual licenses.

[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
