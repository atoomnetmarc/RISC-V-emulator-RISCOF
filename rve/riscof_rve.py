import os
import re
import shutil
import subprocess
import shlex
import logging
import random
import string
from string import Template
import sys

import riscof.utils as utils
import riscof.constants as constants
from riscof.pluginTemplate import pluginTemplate

logger = logging.getLogger()

class rve(pluginTemplate):
    __model__ = "rve"

    #TODO: please update the below to indicate family, version, etc of your DUT.
    __version__ = "XXX"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        config = kwargs.get('config')

        # If the config node for this DUT is missing or empty. Raise an error. At minimum we need
        # the paths to the ispec and pspec files
        if config is None:
            print("Please enter input file paths in configuration.")
            raise SystemExit(1)

        # In case of an RTL based DUT, this would be point to the final binary executable of your
        # test-bench produced by a simulator (like verilator, vcs, incisive, etc). In case of an iss or
        # emulator, this variable could point to where the iss binary is located. If 'PATH variable
        # is missing in the config.ini we can hardcode the alternate here.
        self.dut_exe = os.path.join(config['PATH'] if 'PATH' in config else "","rve")

        # Number of parallel jobs that can be spawned off by RISCOF
        # for various actions performed in later functions, specifically to run the tests in
        # parallel on the DUT executable. Can also be used in the build function if required.
        self.num_jobs = str(config['jobs'] if 'jobs' in config else 1)

        # Path to the directory where this python file is located. Collect it from the config.ini
        self.pluginpath=os.path.abspath(config['pluginpath'])

        # Collect the paths to the  riscv-config absed ISA and platform yaml files. One can choose
        # to hardcode these here itself instead of picking it from the config.ini file.
        self.isa_spec = os.path.abspath(config['ispec'])
        self.platform_spec = os.path.abspath(config['pspec'])

        #We capture if the user would like the run the tests on the target or
        #not. If you are interested in just compiling the tests and not running
        #them on the target, then following variable should be set to False
        if 'target_run' in config and config['target_run']=='0':
            self.target_run = False
        else:
            self.target_run = True

    def initialise(self, suite, work_dir, archtest_env):

       # capture the working directory. Any artifacts that the DUT creates should be placed in this
       # directory. Other artifacts from the framework and the Reference plugin will also be placed
       # here itself.
       self.work_dir = work_dir

       # capture the architectural test-suite directory.
       self.suite_dir = suite

       # Note the march is not hardwired here, because it will change for each
       # test. Similarly the output elf name and compile macros will be assigned later in the
       # runTests function
       self.compile_cmd = 'riscv{1}-unknown-elf-gcc -march={0} \
         -static -mcmodel=medany -fvisibility=hidden -nostdlib -nostartfiles -g3\
         -T '+self.pluginpath+'/env/link.ld\
         -I '+self.pluginpath+'/env/\
         -I ' + archtest_env + ' {2} -o {3} {4}'

       # add more utility snippets here
       self.lssdump_cmd = 'riscv{1}-unknown-elf-objdump --section-headers --source --disassemble-all {0} > {2}'
       self.binrom_cmd = 'riscv{1}-unknown-elf-objcopy -O binary -j .text.init {0} {2}'
       self.binram_cmd = 'riscv{1}-unknown-elf-objcopy -O binary -j .data {0} {2}'
       self.signatureaddresses_cmd = 'riscv{1}-unknown-elf-readelf --wide --symbols {0} | grep -e "begin_signature" -e "end_signature" | awk \'{{ print $$2 \'}} > {2}'

    def build(self, isa_yaml, platform_yaml):

      # load the isa yaml as a dictionary in python.
      ispec = utils.load_yaml(isa_yaml)['hart0']

      # capture the XLEN value by picking the max value in 'supported_xlen' field of isa yaml. This
      # will be useful in setting integer value in the compiler string (if not already hardcoded);
      self.xlen = ('64' if 64 in ispec['supported_xlen'] else '32')

      #TODO: The following assumes you are using the riscv-gcc toolchain. If
      #      not please change appropriately
      self.compile_cmd = self.compile_cmd+' -mabi='+('lp64 ' if 64 in ispec['supported_xlen'] else 'ilp32 ')

    def runTests(self, testList):

      # Delete Makefile if it already exists.
      if os.path.exists(self.work_dir+ "/Makefile." + self.name[:-1]):
            os.remove(self.work_dir+ "/Makefile." + self.name[:-1])
      # create an instance the makeUtil class that we will use to create targets.
      make = utils.makeUtil(makefilePath=os.path.join(self.work_dir, "Makefile." + self.name[:-1]))

      # set the make command that will be used. The num_jobs parameter was set in the __init__
      # function earlier
      make.makeCommand = 'make -k -j' + self.num_jobs

      # we will iterate over each entry in the testList. Each entry node will be refered to by the
      # variable testname.
      for testname in testList:

          # for each testname we get all its fields (as described by the testList format)
          testentry = testList[testname]

          # we capture the path to the assembly file of this test
          test = testentry['test_path']

          # capture the directory where the artifacts of this test will be dumped/created. RISCOF is
          # going to look into this directory for the signature files
          test_dir = testentry['work_dir']

          # name of the elf file after compilation of the test
          elf = 'dut.elf'

          # name of the signature file as per requirement of RISCOF. RISCOF expects the signature to
          # be named as DUT-<dut-name>.signature. The below variable creates an absolute path of
          # signature file.
          sig_file = os.path.join(test_dir, self.name[:-1] + ".signature")

          # for each test there are specific compile macros that need to be enabled. The macros in
          # the testList node only contain the macros/values. For the gcc toolchain we need to
          # prefix with "-D". The following does precisely that.
          compile_macros= ' -D' + " -D".join(testentry['macros'])

          # substitute all variables in the compile command that we created in the initialize
          # function
          cmd = self.compile_cmd.format(testentry['isa'].lower(), self.xlen, test, elf, compile_macros)

          lssdump_cmd = self.lssdump_cmd.format(elf, self.xlen, 'dut.lss')
          binrom_cmd = self.binrom_cmd.format(elf, self.xlen, 'dut-rom.bin')
          binram_cmd = self.binram_cmd.format(elf, self.xlen, 'dut-ram.bin')
          signatureaddresses_cmd = self.signatureaddresses_cmd.format(elf, self.xlen, 'dut-ram-signature_begin_end.txt')

	  # if the user wants to disable running the tests and only compile the tests, then
	  # the "else" clause is executed below assigning the sim command to simple no action
	  # echo statement.
          if self.target_run:
            # set up the simulation command. Template is for spike. Please change.
            simcmd = self.dut_exe + ' > dut.log 2>&1'
          else:
            simcmd = 'echo "NO RUN"'

          # concatenate all commands that need to be executed within a make-target.
          execute = '@cd {0}; {1}; {2}; {3}; {4}; {5}; {6}'.format(testentry['work_dir'], cmd, lssdump_cmd, binrom_cmd, binram_cmd, signatureaddresses_cmd, simcmd)

          # create a target. The makeutil will create a target with the name "TARGET<num>" where num
          # starts from 0 and increments automatically for each new target that is added
          make.add_target(execute)

      # if you would like to exit the framework once the makefile generation is complete uncomment the
      # following line. Note this will prevent any signature checking or report generation.
      #raise SystemExit

      # once the make-targets are done and the makefile has been created, run all the targets in
      # parallel using the make command set above.
      make.execute_all(self.work_dir, timeout=900)

      # if target runs are not required then we simply exit as this point after running all
      # the makefile targets.
      if not self.target_run:
          raise SystemExit(0)

#The following is an alternate template that can be used instead of the above.
#The following template only uses shell commands to compile and run the tests.

#    def runTests(self, testList):
#
#      # we will iterate over each entry in the testList. Each entry node will be referred to by the
#      # variable testname.
#      for testname in testList:
#
#          logger.debug('Running Test: {0} on DUT'.format(testname))
#          # for each testname we get all its fields (as described by the testList format)
#          testentry = testList[testname]
#
#          # we capture the path to the assembly file of this test
#          test = testentry['test_path']
#
#          # capture the directory where the artifacts of this test will be dumped/created.
#          test_dir = testentry['work_dir']
#
#          # name of the elf file after compilation of the test
#          elf = 'my.elf'
#
#          # name of the signature file as per requirement of RISCOF. RISCOF expects the signature to
#          # be named as DUT-<dut-name>.signature. The below variable creates an absolute path of
#          # signature file.
#          sig_file = os.path.join(test_dir, self.name[:-1] + ".signature")
#
#          # for each test there are specific compile macros that need to be enabled. The macros in
#          # the testList node only contain the macros/values. For the gcc toolchain we need to
#          # prefix with "-D". The following does precisely that.
#          compile_macros= ' -D' + " -D".join(testentry['macros'])
#
#          # collect the march string required for the compiler
#          marchstr = testentry['isa'].lower()
#
#          # substitute all variables in the compile command that we created in the initialize
#          # function
#          cmd = self.compile_cmd.format(marchstr, self.xlen, test, elf, compile_macros)
#
#          # just a simple logger statement that shows up on the terminal
#          logger.debug('Compiling test: ' + test)
#
#          # the following command spawns a process to run the compile command. Note here, we are
#          # changing the directory for this command to that pointed by test_dir. If you would like
#          # the artifacts to be dumped else where change the test_dir variable to the path of your
#          # choice.
#          utils.shellCommand(cmd).run(cwd=test_dir)
#
#          # for debug purposes if you would like stop the DUT plugin after compilation, you can
#          # comment out the lines below and raise a SystemExit
#
#          if self.target_run:
#            # build the command for running the elf on the DUT. In this case we use spike and indicate
#            # the isa arg that we parsed in the build stage, elf filename and signature filename.
#            # Template is for spike. Please change for your DUT
#            execute = self.dut_exe + ' --isa={0} +signature={1} +signature-granularity=4 {2}'.format(self.isa, sig_file, elf)
#            logger.debug('Executing on Spike ' + execute)
#
#          # launch the execute command. Change the test_dir if required.
#          utils.shellCommand(execute).run(cwd=test_dir)
#
#          # post-processing steps can be added here in the template below
#          #postprocess = 'mv {0} temp.sig'.format(sig_file)'
#          #utils.shellCommand(postprocess).run(cwd=test_dir)
#
#      # if target runs are not required then we simply exit as this point after running all
#      # the makefile targets.
#      if not self.target_run:
#          raise SystemExit
