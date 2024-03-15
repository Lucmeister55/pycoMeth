import unittest
import multiprocessing
import time
from pathlib import Path
from Meth_Seg import Meth_Seg

class TestMethSeg(unittest.TestCase):
    def test_multicore_usage(self):
        # Define the parameters for Meth_Seg
        h5_file_list = [Path('/data/lvisser/pycoMeth/IMR-32.haplotagged.filtered.sorted.nohydro.sorted.m5')]
        output_tsv_fn = 'methseg_output.tsv'
        chromosome = 'chr20'
        workers = 4
        reader_workers = 2

        # Define a function to run Meth_Seg in a separate process
        def run_meth_seg():
            Meth_Seg(h5_file_list, output_tsv_fn, chromosome, workers=workers, reader_workers=reader_workers)

        # Start Meth_Seg in a separate process
        p = multiprocessing.Process(target=run_meth_seg)
        p.start()

        # Periodically check the number of active child processes
        while p.is_alive():
            active_processes = multiprocessing.active_children()
            print(f'Active child processes: {len(active_processes)}')  # print the number of active child processes
            self.assertEqual(len(active_processes), workers + reader_workers + 1)  # +1 for the Meth_Seg process itself
            time.sleep(1)  # wait for 1 second

        # Join the Meth_Seg process
        p.join()

if __name__ == '__main__':
    unittest.main()