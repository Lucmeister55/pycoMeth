![pycoMeth](./docs/pictures/pycoMeth_long.png)

[![GitHub license](https://img.shields.io/github/license/a-slide/pycoMeth.svg)](https://github.com/a-slide/pycoMeth/blob/master/LICENSE)
[![Language](https://img.shields.io/badge/Language-Python3.6+-yellow.svg)](https://www.python.org/)
[![DOI](https://zenodo.org/badge/211195001.svg)](https://zenodo.org/badge/latestdoi/211195001)
[![Build Status](https://travis-ci.com/a-slide/pycoMeth.svg?branch=master)](https://travis-ci.com/a-slide/pycoMeth)

[![PyPI version](https://badge.fury.io/py/pycoMeth.svg)](https://badge.fury.io/py/pycoMeth)
[![PyPI downloads](https://pepy.tech/badge/pycoMeth)](https://pepy.tech/project/pycoMeth)
[![Anaconda Version](https://anaconda.org/aleg/pycometh/badges/version.svg)](https://anaconda.org/aleg/pycometh)
[![Anaconda Downloads](https://anaconda.org/aleg/pycometh/badges/downloads.svg)](https://anaconda.org/aleg/pycometh)

---
Version in this branch: 2.0.0a1

**Full documentation is available at https://a-slide.github.io/pycoMeth/**

---

**DNA methylation analysis downstream to Nanopolish for Oxford Nanopore DNA sequencing datasets**

`pycoMeth` can be used for further analyses starting from the output files generated by [`Nanopolish call-methylation`](https://github.com/jts/nanopolish). The package contains a suite of tools to **find CpG islands** calculate the **methylation probability at CpG dinucleotide or CpG island resolution** across the entire genome and to perform a **simple differential methylation analysis** across multiple samples.

`pycoMeth` generates extensive tabulated reports and BED files which can be loaded in a genome browser. In addition, an interactive HTML report of differentially
methylated intervals/islands can also generated at the end of the analysis.

[`Methplotlib`](https://github.com/wdecoster/methplotlib) developed by [Wouter de coster](https://twitter.com/wouter_decoster) is an excellent complementary tool to visualise and explore methylation status for specific loci.

Please be aware that `pycoMeth` is a research package that is still under development. The API, command line interface, and implementation might change without retro-compatibility.

---

### pycoMeth workflow

![Workflow](docs/pictures/pycoMeth_package.png)

### pycoMeth example output IGV rendering

![IGV](docs/pictures/pycoMeth_all.png)

### pycoMeth example HTML report

[Example HTML report 1](https://a-slide.github.io/pycoMeth/Comp_Report/medaka_html/pycoMeth_summary_report.html)

[Example HTML report 2](https://a-slide.github.io/pycoMeth/Comp_Report/human_html/pycoMeth_summary_report.html)

![HTML](docs/pictures/pycoMeth_HTML.gif)

---

### Citing

The repository is archived at Zenodo. If you use `pycoMeth` please cite as follow:

Adrien Leger. (2020, January 28). a-slide/pycoMeth. Zenodo. https://doi.org/10.5281/zenodo.3629254

## Authors and contributors

* Adrien Leger (@a-slide) - aleg {at} ebi.ac.uk
