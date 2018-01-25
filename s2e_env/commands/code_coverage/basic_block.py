"""
Copyright (c) 2017 Dependable Systems Laboratory, EPFL

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""


from __future__ import division

from collections import namedtuple
import json
import logging
import os

from s2e_env.command import ProjectCommand, CommandError
from . import get_tb_files, parse_tb_file


logger = logging.getLogger('basicblock')


BasicBlock = namedtuple('BasicBlock', ['start_addr', 'end_addr', 'function'])
TranslationBlock = namedtuple('TranslationBlock', ['start_addr', 'end_addr'])


def _basic_block_coverage(basic_blocks, translation_blocks):
    """
    Calculate the basic block coverage.

    This information is derived from the basic block list (generated by IDA
    Pro) and the translation block list (generated by S2E's
    ``TranslationBlockCoverage``).

    Args:
        basic_blocks: List of basic blocks.
        translation_blocks: List of executed translation blocks.

    Returns:
        A list of ``BasicBlock``s executed by S2E.
    """
    logger.info('Calculating basic block coverage')

    # Naive approach :(
    covered_bbs = set()
    for tb_start_addr, tb_end_addr in translation_blocks:
        for bb in basic_blocks:
            # Check if the translation block falls within a basic block OR
            # a basic block falls within a translation block
            if (bb.end_addr >= tb_start_addr >= bb.start_addr or
                    bb.start_addr <= tb_end_addr <= bb.end_addr):
                covered_bbs.add(bb)

    return list(covered_bbs)


class BasicBlockCoverage(ProjectCommand):
    """
    Generate a basic block coverage report.

    This subcommand requires either IDA Pro or Radare2 as a disassembler.
    """

    help = 'Generate a basic block coverage report. This requires either IDA '  \
           'Pro or Radare2 as a disassembler.'

    RESULTS = 'Basic block coverage saved to {bb_file}\n\n'             \
              'Statistics\n'                                            \
              '==========\n\n'                                          \
              'Total basic blocks: {num_bbs}\n'                         \
              'Covered basic blocks: {num_covered_bbs} ({percent:.1%})'

    def handle(self, *args, **options):
        # Get translation block coverage information
        target_path = self._project_desc['target_path']
        target_dir = os.path.dirname(target_path)
        modules = self._project_desc['modules']

        for module_info in modules:
            module = module_info[0]
            module_path = os.path.join(target_dir, module)

            # Initialize the backend disassembler
            self._initialize_disassembler(module_path)

            tbs = self._get_tb_coverage(module)
            if not tbs:
                raise CommandError('No translation block coverage information found')

            # Get the basic block information
            bbs = self._get_basic_blocks(module_path)
            if not bbs:
                raise CommandError('No basic block information found')

            # Calculate the basic block coverage information
            bb_coverage = _basic_block_coverage(bbs, tbs)

            # Calculate some statistics
            total_bbs = len(bbs)
            covered_bbs = len(bb_coverage)

            # Write the basic block information to a JSON file
            bb_coverage_file = self._save_basic_block_coverage(module, bb_coverage, total_bbs)

            return self.RESULTS.format(bb_file=bb_coverage_file,
                                       num_bbs=total_bbs,
                                       num_covered_bbs=covered_bbs,
                                       percent=covered_bbs / total_bbs)

    def _initialize_disassembler(self, module_path):
        """
        Initialize the backend disassembler.
        """
        pass

    def _get_basic_blocks(self, module_path):
        """
        Extract basic block information from the target binary using one of the
        disassembler backends (IDA Pro or Radare2).

        Returns:
            A list of ``BasicBlock``s, i.e. named tuples containing:
                1. Basic block start address
                2. Basic block end address
                3. Name of function that the basic block resides in
        """
        raise NotImplementedError('subclasses of BasicBlockCoverage must '
                                  'provide a _get_basic_blocks() method')

    def _get_tb_coverage(self, target_name):
        """
        Extract translation block (TB) coverage from the JSON file(s) generated
        by the ``TranslationBlockCoverage`` plugin.

        Args:
            target_name: Name of the analysis target file.

        Returns:
            A list of ``TranslationBlock``'s, i.e. named tuples containing:
                1. Translation block start address
                2. Translation block end address
        """
        logger.info('Generating translation block coverage information')

        tb_coverage_files = get_tb_files(self.project_path('s2e-last'))
        covered_tbs = set()

        for tb_coverage_file in tb_coverage_files:
            tb_coverage_data = parse_tb_file(tb_coverage_file, target_name)
            if not tb_coverage_data:
                continue

            covered_tbs.update(TranslationBlock(start_addr, end_addr) for
                               start_addr, end_addr, _ in
                               tb_coverage_data)

        return list(covered_tbs)

    def _save_basic_block_coverage(self, module, basic_blocks, total_bbs):
        """
        Write the basic block coverage information to a JSON file.

        Args:
            basic_blocks: Covered basic blocks.
            total_bbs: The total number of basic blocks in the program.

        Returns:
            The path of the JSON file.
        """
        bb_coverage_file = self.project_path('s2e-last',
                                             '%s_coverage.json' % module)

        logger.info('Saving basic block coverage to %s', bb_coverage_file)

        to_dict = lambda bb: {'start_addr': bb.start_addr,
                              'end_addr': bb.end_addr,
                              'function': bb.function}
        bbs_json = {
            'stats': {
                'total_basic_blocks': total_bbs,
                'covered_basic_blocks': len(basic_blocks),
            },
            'coverage': [to_dict(bb) for bb in basic_blocks],
        }

        with open(bb_coverage_file, 'w') as f:
            json.dump(bbs_json, f)

        return bb_coverage_file
