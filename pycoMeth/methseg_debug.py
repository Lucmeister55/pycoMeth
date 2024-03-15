from pathlib import Path
from Meth_Seg import Meth_Seg

# Define the parameters for Meth_Seg
h5_file_list = [Path('/data/lvisser/pycoMeth/IMR-32.haplotagged.filtered.sorted.nohydro.sorted.m5')]
output_tsv_fn = 'methseg_output.tsv'
chromosome = 'chr1'
workers = 16
reader_workers = 4

Meth_Seg(h5_file_list, output_tsv_fn, chromosome, workers=workers, reader_workers=reader_workers, verbose = False)