# -*- coding: utf-8 -*-

#~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~IMPORTS~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~#

# Standard library imports
from collections import OrderedDict, namedtuple, Counter
import hashlib

# Third party imports
from tqdm import tqdm
import numpy as np
import pandas as pd
import jinja2
from pyfaidx import Fasta
from scipy.ndimage import gaussian_filter1d

# Plotly imports
import plotly.graph_objs as go
from plotly.subplots import make_subplots
from plotly.colors import n_colors
import plotly.figure_factory as ff
import plotly.offline as py

# Local imports
from pycoMeth import __version__ as version
from pycoMeth.common import *

#~~~~~~~~~~~~~~~~~~~~~~~~Main Function~~~~~~~~~~~~~~~~~~~~~~~~#

def Comp_Report (
    methcomp_fn:str,
    gff3_fn:str,
    ref_fasta_fn:str,
    outdir:str="./",
    n_top:int=100,
    max_tss_distance:int=100000,
    pvalue_threshold:float=0.01,
    min_diff_llr:float=1,
    n_len_bin:int=500,
    api_mode:bool=False,
    export_static_plots:bool=False,
    report_non_significant:bool=False,
    verbose:bool=False,
    quiet:bool=False,
    progress:bool=False,
    **kwargs):
    """
    Generate an HTML report of significantly differentially methylated CpG intervals from `Meth_Comp` text output.
    Significant intervals are annotated with their closest transcript TSS.
    * methcomp_fn
        Input tsv file generated by Meth_comp (can be gzipped). At the moment only data binned by intervals with Interval_Aggregate are supported.
    * gff3_fn
        Path to an **ensembl GFF3** file containing genomic annotations. Only the transcripts details are extracted.
    * ref_fasta_fn
        Reference file used for alignment in Fasta format (ideally already indexed with samtools faidx)
    * outdir
        Directory where to output HTML reports, By default current directory
    * n_top
        Number of top interval candidates for which to generate an interval report.
        If there are not enough significant candidates this is automatically scaled down.
    * max_tss_distance
        Maximal distance to transcription stat site to find transcripts close to interval candidates
    * pvalue_threshold
        pValue cutoff for top interval candidates
    * min_diff_llr
        Minimal llr boundary for negative and positive median llr. 1 is recommanded for vizualization purposes.
    * n_len_bin
        Number of genomic intervals for the longest chromosome of the ideogram figure
    * api_mode
        Don't generate reports or tables, just parse data and return a tuple containing an overall median CpG dataframe and a dictionary of CpG dataframes
        for the top candidates found. These dataframes can then be used to with the plotting functions containned in this module
    * export_static_plots
        Export all the plots from the reports in SVG format.
    * report_non_significant
        Report all valid CpG islands, significant or not in the text report. This option also adds a non-significant track to the TSS_distance plot
    """

    # Init method
    opt_summary_dict = opt_summary(local_opt=locals())
    log = get_logger (name="pycoMeth_CpG_Comp", verbose=verbose, quiet=quiet)

    log.warning("Checking options and input files")
    log_dict(opt_summary_dict, log.debug, "Options summary")

    log.warning("Loading and preparing data")

    # Parse methcomp data
    log.info("Loading Methcomp data from TSV file")
    df = pd.read_table(methcomp_fn, low_memory=False)

    # Check that the input file was generated by methcomp from samples aggregated with Interval_Aggregate
    req_fields = [
        "chromosome","start","end","n_samples","pvalue","adj_pvalue","neg_med","pos_med",
        "ambiguous_med","unique_cpg_pos","labels","med_llr_list","raw_llr_list","raw_pos_list"]
    if not all_in(req_fields, df.columns):
        raise pycoMethError ("Invalid input file type passed. Expecting Meth_Comp TSV file generated from samples processed with Interval_Aggregate")

    # Parse GFF3 annotations
    log.info("Loading transcripts info from GFF file")
    tx_df = get_ensembl_tx(gff3_fn)
    if tx_df.empty:
        log.error("No valid transcripts found in GFF3 input file")
    if not all_in(df["chromosome"], tx_df["chromosome"]):
        log.error ("Not all the chromosomes found in the data file are present in the GFF3 file. This will lead to missing transcript ids")

    # Parse FASTA reference
    log.info("Loading chromosome info from reference FASTA file")
    chr_len_d = get_chr_len(ref_fasta_fn)
    if not chr_len_d:
        log.error("No valid reference sequences found in FASTA file")
    if not all_in(df["chromosome"], chr_len_d.keys()):
        log.error ("Not all the chromosomes found in the data file are present in the Fasta file. This will lead to missing reference sequences in the ideogram")

    # Select only sites with a valid pvalue
    valid_df = df.dropna(subset=["adj_pvalue"])

    # Check number of valid pvalues
    sig_df = valid_df[valid_df.adj_pvalue <= pvalue_threshold]
    log.info("Number of significant intervals found (adjusted pvalue<{}): {}".format(pvalue_threshold, len(sig_df)))
    if len(sig_df)<5:
        log.error("Low number of significant sites. The summary report will likely contain errors")
    if len(sig_df)<n_top:
        log.error("Number of significant intervals lower than number of top candidates to plot")

    # List top candidates
    log.info("Finding top candidates")
    top_dict = OrderedDict()
    top_candidates = sig_df.sort_values(by="adj_pvalue").head(n_top)
    for rank, (idx, line) in enumerate(iter_idx_tuples(top_candidates), 1):
        coord = "{}-{}-{}".format(line.chromosome,line.start,line.end)
        bn = "interval_{:04}_chr{}".format(rank, coord)
        top_dict[idx] = {"rank":rank, "coord":coord, "bn":bn}
    rank_fn_dict = {i["rank"]:i["bn"] for i in top_dict.values()}

    all_cpg_d = OrderedDict()
    all_interval_summary = []
    top_interval_summary = []

    # Init dict to collect data for api_mode
    if api_mode:
        top_cpg_df_d = OrderedDict()

    # In normal mode, create output structure and file names
    else:
        log.info("Creating output directory structure")
        summary_report_fn = "pycoMeth_summary_report.html"
        top_intervals_fn = "pycoMeth_summary_intervals.tsv"
        reports_outdir = "interval_reports"
        tables_outdir = "interval_tables"
        mkdir (outdir, exist_ok=True)
        mkdir (os.path.join(outdir, reports_outdir), exist_ok=True)
        mkdir (os.path.join(outdir, tables_outdir), exist_ok=True)
        if export_static_plots:
            kaleido = Kaleido()
            plot_outdir = "static_plots"
            mkdir (os.path.join(outdir, plot_outdir), exist_ok=True)

        # Prepare src file for report and compute md5
        log.info("Computing source md5")
        src_file = os.path.abspath(methcomp_fn)
        md5 = md5_str(methcomp_fn)

    # Extract info from each intervals
    log.warning("Parsing methcomp data")
    log.info("Iterating over significant intervals")

    for idx, line in tqdm(iter_idx_tuples(valid_df), total=len(valid_df), unit=" intervals", unit_scale=True, desc="\tProgress", disable=not progress):

        # collect summary stats for significant intervals or all if required
        if line.adj_pvalue <= pvalue_threshold or report_non_significant:
            close_tx_df = get_close_tx_df(tx_df=tx_df, chromosome=line.chromosome, start=line.start, end=line.end, max_tss_distance=max_tss_distance)
            all_interval_summary.append(get_interval_summary(line=line, close_tx_df=close_tx_df))

        # collect median llr for all significant intervals
        if line.adj_pvalue <= pvalue_threshold:
            lab_list = ["Sample {}".format(lab) for lab in str_to_list(line.labels)]
            med_list = str_to_list(line.med_llr_list)
            coord = "{}-{}-{}".format(line.chromosome,line.start,line.end)
            all_cpg_d[coord] = {lab:llr for lab, llr in zip(lab_list, med_list)}

        # Extract more data for reports of top hits
        if idx in top_dict:
            rank = top_dict[idx]["rank"]
            log.debug (f"Ploting top candidates rank: #{rank}")

            # Extract data from line
            cpg_df = get_cpg_df(line)

            # In API mode just collect the CpG data
            if api_mode:
                top_cpg_df_d[rank] = cpg_df

            # Generate figures and tables
            else:
                try:
                    heatmap_fig = cpg_heatmap(cpg_df, lim_llr=10, min_diff_llr=min_diff_llr)
                    ridgeplot_fig = cpg_ridgeplot(cpg_df, box=False, scatter=True, min_diff_llr=min_diff_llr)
                    interval_df = get_interval_df(line=line, rank=rank)
                except ValueError as E:
                    from IPython.core.display import display
                    print(line)
                    display(cpg_df)
                    raise E

                # Collect Interval minimal info
                link_out_file = os.path.join(reports_outdir, top_dict[idx]["bn"]+".html")
                top_interval_summary.append(get_interval_summary(line=line, close_tx_df=close_tx_df, rank=rank, out_file=link_out_file))

                # Render interval HTML report
                html_out_file = os.path.join(outdir, reports_outdir, top_dict[idx]["bn"]+".html")
                write_cpg_interval_html(
                    out_file = html_out_file,
                    src_file = src_file,
                    md5 = md5,
                    summary_link = "../{}".format(summary_report_fn),
                    previous_link = prev_fn(rank_fn_dict, rank)+".html",
                    next_link = next_fn(rank_fn_dict, rank)+".html",
                    max_tss_distance = max_tss_distance,
                    interval_df = interval_df,
                    close_tx_df = close_tx_df,
                    heatmap_fig = heatmap_fig,
                    ridgeplot_fig = ridgeplot_fig)

                # Write out TSV table
                if not close_tx_df.empty:
                    table_out_path = os.path.join(outdir, tables_outdir, top_dict[idx]["bn"]+".tsv")
                    close_tx_df.to_csv(table_out_path, sep="\t", index=False)

                # Try to export static plots if required
                if export_static_plots:
                    kaleido.export_plotly_svg (fig=heatmap_fig, fn=os.path.join(outdir, plot_outdir, top_dict[idx]["bn"]+"_heatmap.svg"), width=1400)
                    kaleido.export_plotly_svg (fig=ridgeplot_fig, fn=os.path.join(outdir, plot_outdir, top_dict[idx]["bn"]+"_ridgeplot.svg"), width=1400)

    # Convert to DataFrame
    all_cpg_df = pd.DataFrame.from_dict(all_cpg_d)
    all_summary_df = get_interval_summary_df(all_interval_summary)

    if api_mode:
        # Sort dictionary by rank
        top_cpg_df_d = OrderedDict(sorted(top_cpg_df_d.items(), key=lambda t: t[0]))
        # Return all dataframe and sorted dataframe dictionary
        return (all_summary_df, all_cpg_df, top_cpg_df_d)

    else:
        # Collect data at CpG interval level
        log.info("Generating summary report")

        # Generate figures and tables
        summary_df = get_summary_df(df, sig_df)
        top_interval_summary_df = get_interval_summary_df(top_interval_summary)
        all_heatmap_fig = cpg_heatmap(all_cpg_df, lim_llr=4, min_diff_llr=min_diff_llr)
        all_ridgeplot_fig = cpg_ridgeplot(all_cpg_df, box=True, scatter=False, min_diff_llr=min_diff_llr)
        catplot_fig = category_barplot(all_cpg_df, min_diff_llr=min_diff_llr)
        ideogram_fig = chr_ideogram_plot(all_cpg_df, ref_fasta_fn, n_len_bin=n_len_bin)
        tss_dist_fig = tss_dist_plot(all_summary_df, pvalue_threshold=pvalue_threshold, max_distance=max_tss_distance)

        # Write out HTML report
        html_out_path = os.path.join(outdir, summary_report_fn)
        write_summary_html(
            out_file = html_out_path,
            src_file = src_file,
            md5 = md5,
            summary_df = summary_df,
            top_interval_summary_df = top_interval_summary_df,
            catplot_fig = catplot_fig,
            heatmap_fig = all_heatmap_fig,
            ridgeplot_fig = all_ridgeplot_fig,
            ideogram_fig = ideogram_fig,
            tss_dist_fig = tss_dist_fig)

        # Write out TSV table
        table_out_path = os.path.join(outdir, top_intervals_fn)
        if not all_summary_df.empty:
            all_summary_df.to_csv(table_out_path, sep="\t", index=False)

        # Try to export static plots if required
        if export_static_plots:
            kaleido.export_plotly_svg (fig=all_heatmap_fig, fn=os.path.join(outdir, plot_outdir, "all_heatmap.svg"), width=1400)
            kaleido.export_plotly_svg (fig=all_ridgeplot_fig, fn=os.path.join(outdir, plot_outdir, "all_ridgeplot.svg"), width=1400)
            kaleido.export_plotly_svg (fig=catplot_fig, fn=os.path.join(outdir, plot_outdir, "all_catplot.svg"), width=1400)
            kaleido.export_plotly_svg (fig=ideogram_fig, fn=os.path.join(outdir, plot_outdir, "all_ideogram.svg"), width=1400)
            kaleido.export_plotly_svg (fig=tss_dist_fig, fn=os.path.join(outdir, plot_outdir, "all_tss_distance.svg"), width=1400)

#~~~~~~~~~~~~~~~~~~~~~~~~HTML generating functions~~~~~~~~~~~~~~~~~~~~~~~~#

def write_cpg_interval_html (out_file, src_file, md5, summary_link, previous_link, next_link, max_tss_distance, interval_df, close_tx_df, heatmap_fig, ridgeplot_fig):
    """Write CpG interval HTML report"""
    # Get CpG_Interval template
    template = get_jinja_template ("CpG_Interval.html.j2")

    # Render pandas dataframes and plotly figures to HTML
    interval_html = render_df(interval_df)
    transcript_html = render_df(close_tx_df, empty_msg=f"No transcripts TTS found within {max_tss_distance} bp upstream or downstream")
    heatmap_html = render_fig (heatmap_fig)
    ridgeplot_html = render_fig (ridgeplot_fig)

    # Render HTML report using Jinja
    rendering = template.render(
        plotlyjs = py.get_plotlyjs(),
        version = version,
        date = datetime.datetime.now().strftime("%d/%m/%y"),
        src_file = src_file,
        md5 = md5,
        summary_link = summary_link,
        previous_link = previous_link,
        next_link = next_link,
        interval_html = interval_html,
        transcript_html = transcript_html,
        heatmap_html = heatmap_html,
        ridgeplot_html = ridgeplot_html)

    with open(out_file, "w") as fp:
        fp.write(rendering)

def write_summary_html (out_file, src_file, md5, summary_df, top_interval_summary_df, catplot_fig, heatmap_fig, ridgeplot_fig, ideogram_fig, tss_dist_fig):
    """Write summary HTML report"""
    # Get CpG_Interval template
    template = get_jinja_template("CpG_summary.html.j2")

    # Render pandas dataframes and plotly figures to HTML
    summary_html = render_df(summary_df)
    top_html = render_df(top_interval_summary_df, empty_msg="No significant candidates found")
    catplot_html = render_fig (catplot_fig, empty_msg= "Not enough significant candidates to render catplot")
    heatmap_html = render_fig (heatmap_fig, empty_msg= "Not enough significant candidates to render heatmap")
    ridgeplot_html = render_fig (ridgeplot_fig, empty_msg= "Not enough significant candidates to render ridgeplot")
    ideogram_html = render_fig (ideogram_fig, empty_msg= "Not enough significant candidates to render ideogram")
    tss_dist_html = render_fig (tss_dist_fig, empty_msg= "Not enough significant candidates to render tss distance plot")

    # Render HTML report using Jinja
    rendering = template.render(
        plotlyjs = py.get_plotlyjs(),
        version = version,
        date = datetime.datetime.now().strftime("%d/%m/%y"),
        src_file = src_file,
        md5 = md5,
        summary_html = summary_html,
        top_html = top_html,
        catplot_html = catplot_html,
        heatmap_html = heatmap_html,
        ridgeplot_html = ridgeplot_html,
        ideogram_html = ideogram_html,
        tss_dist_html = tss_dist_html)

    with open(out_file, "w") as fp:
        fp.write(rendering)

#~~~~~~~~~~~~~~~~~~~~~~~~GFF/FASTA parsing functions~~~~~~~~~~~~~~~~~~~~~~~~#

def get_ensembl_tx (gff_fn):
    """Simple parsing function transcript data from ensembl GFF3 files"""
    l = []
    open_fun, open_mode = (gzip.open, "rt") if gff_fn.endswith(".gz") else (open, "r")

    with open_fun (gff_fn, open_mode) as fp:

        valid_file = False
        for line in fp:
            # Verify that GFF3 tag is present in header
            if line.startswith ("##gff-version 3"):
                valid_file = True

            elif not line.startswith ("#"):

                # Raise error if GFF3 tag not previously found in header
                if not valid_file:
                    raise pycoMethError("GFF3 tag not found in file header. Please provide an Ensembl GFF3 file")

                ls = line.strip().split("\t")
                # Define transcript as feature type containing RNA or transcript and with a gene as a Parent
                if ("RNA" in ls[2] or "transcript" in ls[2]) and "Parent=gene" in ls[8]:

                    d = OrderedDict()
                    d["chromosome"] = ls[0]
                    d["strand"] = ls[6]
                    d["start"] = int(ls[3])
                    d["end"] = int(ls[4])
                    d["tss"] = d["start"] if d["strand"] == "+" else d["end"]
                    d["feature type"] = ls[2]

                    # Parse attributes
                    attrs = OrderedDict()
                    try:
                        for a in ls[8].split(";"):
                            i, j = a.split("=")
                            attrs[i.lower()] = j.lower()
                    except Exception:
                        pass

                    # Extract specific attrs
                    d["transcript id"] = attrs.get("id", pd.NA).strip("transcript:")
                    d["gene id"] = attrs.get("parent", pd.NA).strip("gene:")
                    d["transcript biotype"] = attrs.get("biotype", pd.NA)
                    d["transcript name"] = attrs.get("name", pd.NA)
                    l.append(d)

        df = pd.DataFrame(l)
        df = df.fillna(pd.NA)
        return df

def get_chr_len(fasta_fn):
    """Extract reference sequences length from fasta files"""
    len_d = OrderedDict()
    with Fasta(fasta_fn) as fa:
        for seq in fa:
            len_d[seq.name] = len(seq)
    return len_d

#~~~~~~~~~~~~~~~~~~~~~~~~DataFrame functions~~~~~~~~~~~~~~~~~~~~~~~~#

def get_cpg_df (line):
    """"""
    lab_list = ["Sample {}".format(lab) for lab in str_to_list(line.labels)]
    llr_list = str_to_list(line.raw_llr_list)
    pos_list = str_to_list(line.raw_pos_list)

    cpg_df = pd.DataFrame()
    for lab, llr, pos in zip(lab_list, llr_list, pos_list):
        pos = ["{}-{:,}".format(line.chromosome, pos) for pos in pos]
        cpg_sdf = pd.DataFrame(index=pos, data=llr, columns=[lab])
        if cpg_df.empty:
            cpg_df = cpg_sdf
        else:
            cpg_df = pd.merge(cpg_df, cpg_sdf, left_index=True, right_index=True, how="outer")

    return cpg_df.T

def get_close_tx_df (tx_df, chromosome, start, end, max_tss_distance=100000):
    """Find transcripts with a TSS within a given genomic interval"""
    rdf = tx_df.query("chromosome == '{}' and tss >= {} and tss <= {}".format(chromosome, start-max_tss_distance, end+max_tss_distance))
    tss_dist = []
    for tx, line in iter_idx_tuples(rdf):
        if line.tss > end:
            tss_dist.append(line.tss-end)
        elif line.tss < start:
            tss_dist.append(line.tss-start)
        else:
            tss_dist.append(0)
    rdf["distance to tss"] = tss_dist
    rdf["abs_tss"] = np.abs(tss_dist)
    rdf.sort_values("abs_tss", inplace=True)
    rdf = rdf[["distance to tss", "transcript id","gene id","transcript name","chromosome","start","end","strand","feature type","transcript biotype"]]
    return rdf

def get_interval_df (line, rank):
    """Generate a single line dataframe describing the current interval"""

    line_dict = OrderedDict()
    line_dict["pvalue rank"] = f"#{rank}"
    line_dict["chromosome"] = line.chromosome
    line_dict["start"] = line.start
    line_dict["end"] = line.end
    line_dict["length"] = line.end-line.start
    line_dict["number of samples"] = line.n_samples
    line_dict["number of CpGs"] = line.unique_cpg_pos
    line_dict["adjusted pvalue"] = line.adj_pvalue

    return pd.DataFrame.from_dict(line_dict, orient="index").T

def get_summary_df (df, sig_df):
    """Generate a single line dataframe with summary information"""
    s = pd.Series()
    s.loc["Total intervals"] = "{:,}".format(len(df))

    for comment, comment_df in df.groupby("comment"):
        s.loc[comment] = "{:,}".format(len(comment_df))

    return s.to_frame().T

def get_interval_summary (line, close_tx_df, rank=None, out_file=None):
    """Generate a summary dict for intervals"""
    d = OrderedDict()
    if rank:
        d["rank"] = f"#{rank}"
    if out_file:
        d["detailled report"] = f"<a href='{out_file}'>report link</a>"
    d["pvalue"] = line.adj_pvalue
    d["chromosome"] = line.chromosome
    d["start"] = line.start
    d["end"] = line.end

    if close_tx_df.empty:
        d["Number of nearby TSS"] = 0
        d["closest tx id"] = pd.NA
        d["closest tx name"] = pd.NA
        d["closest tx biotype"] = pd.NA
        d["distance to tss"] = pd.NA
    else:
        d["Number of nearby TSS"] = len(close_tx_df)
        d["closest tx id"] = close_tx_df.iloc[0]["transcript id"]
        d["closest tx name"] = close_tx_df.iloc[0]["transcript name"]
        d["closest tx biotype"] = close_tx_df.iloc[0]["transcript biotype"]
        d["distance to tss"] = close_tx_df.iloc[0]["distance to tss"]
    return  d

def get_interval_summary_df (interval_summary_list):
    """Generate a dataframe containing information for interval summaries"""
    # Convert list to df
    interval_summary_df = pd.DataFrame(interval_summary_list)
    # return if empty df
    if interval_summary_df.empty:
        return interval_summary_df
    # Sort values by ascending value
    interval_summary_df.sort_values(by="pvalue", inplace=True, ascending=True)
    return interval_summary_df

#~~~~~~~~~~~~~~~~~~~~~~~~Plotting functions~~~~~~~~~~~~~~~~~~~~~~~~#

def cpg_heatmap (
    df,
    methylated_color:str = 'rgb(215,48,39)',
    unmethylated_color:str = 'rgb(33,102,172)',
    ambiguous_color:str = 'rgb(240,240,240)',
    lim_llr:float = 10,
    min_diff_llr:float = 1,
    fig_width:int=None,
    fig_height:int=None,
    column_widths=[0.95, 0.05]):
    """
    Plot the values per CpG as a heatmap
    """
    # Cannot calculate if at least not 2 values
    if len(df.columns) <= 1:
        return None

    # Fill missing values by 0 = ambiguous methylation
    df = df.fillna(0)

    # Prepare subplot aread
    fig = make_subplots(
        rows=1,
        cols=2,
        shared_yaxes=True,
        column_widths=column_widths,
        specs=[[{"type": "heatmap"},{"type": "scatter"}]])

    # Plot dendogramm
    dendrogram = ff.create_dendrogram(df.values, labels=df.index, orientation='left', color_threshold=0, colorscale=["grey"])
    for data in dendrogram.data:
        fig.add_trace (data, row=1, col=2)

    # Reorder rows
    labels_ordered = np.flip(dendrogram.layout['yaxis']['ticktext'])
    df = df.reindex(labels_ordered)

    # Define min_llr if not given = symetrical 2nd percentile
    if not lim_llr:
        lim_llr = max(np.absolute(np.nanpercentile(df.values, [2,98])))

    # Define colorscale
    offset = min_diff_llr/lim_llr*0.5
    colorscale = [
        [0.0, unmethylated_color],
        [0.5-offset, ambiguous_color],
        [0.5+offset, ambiguous_color],
        [1.0, methylated_color]]

    # plot heatmap
    heatmap = go.Heatmap(name="heatmap", x=df.columns, y=df.index, z=df.values, zmin=-lim_llr, zmax=lim_llr, zmid=0, colorscale=colorscale, colorbar_title="Median LLR")
    fig.add_trace (heatmap, row=1, col=1)

    # Tweak figure layout
    fig.update_layout(
        dict1 = {'showlegend':False, 'hovermode':'closest', "plot_bgcolor":'rgba(0,0,0,0)',"width":fig_width, "height":fig_height, "margin":{"t":50,"b":50}},
        xaxis2 = {"fixedrange":True, 'showgrid':False, 'showline':False, "showticklabels":False,'zeroline':False,'ticks':""},
        yaxis2 = {"fixedrange":True, 'showgrid':False, 'showline':False, "showticklabels":False,'zeroline':False,'ticks':"", "automargin":True},
        xaxis = {"fixedrange":False, "domain":[0, column_widths[0]], "showticklabels":False, "title":"CpG positions"},
        yaxis = {"fixedrange":True, "domain":[0, 1], "ticks":"outside", "automargin":True})

    return fig

def cpg_ridgeplot (
    df,
    methylated_color:str = 'rgb(215,48,39)',
    unmethylated_color:str = 'rgb(33,102,172)',
    ambiguous_color:str = 'rgb(100,100,100)',
    min_diff_llr:float = 1,
    lim_quantile:int = 0.0001,
    scatter:bool = True,
    box:bool = False,
    trace_width:int = 2,
    fig_width:int = None,
    fig_height:int = None):
    """
    Plot a distribution of the llr values as a ridgeplot
    """
    # Cannot calculate if at least not 2 values
    if len(df.columns) <= 1:
        return None

    # Sorted labels by median llr
    d = OrderedDict()
    for lab, row in iter_idx_tuples(df):
        d[lab] = np.nanmedian(row)
    sorted_labels = [i for i,j in sorted(d.items(), key=lambda t: t[1])]

    # Define color map depending on number of samples
    cmap = n_colors(unmethylated_color, methylated_color, len(sorted_labels), colortype='rgb')

    # Find minimal and maximal llr values
    xmin, xmax = np.nanquantile(df.values, q = [lim_quantile, 1-lim_quantile])
    xmax = np.ceil(xmax)
    xmin = np.floor(xmin)

    # Create ridgeplot traces
    points="all" if scatter else False
    box_visible = True if box else False

    fig = go.Figure()
    for label, color in zip(sorted_labels, cmap):
        violin = go.Violin(
            x=df.loc[label],
            name=label,
            orientation="h",
            width=trace_width,
            hoveron="violins",
            points=points,
            box_visible=box_visible,
            box_width=trace_width/3,
            pointpos=0.2,
            jitter=0.2,
            marker_size=5,
            side="positive",
            line_color=color)
        fig.add_trace (violin)

    # Add shape for ambigous log likelihood area
    fig.add_shape(type="rect", xref="x", yref="paper", x0=-min_diff_llr, y0=0, x1=min_diff_llr, y1=1, fillcolor=ambiguous_color, opacity=0.25, layer="below", line_width=0)
    fig.add_annotation(text="Ambiguous", xref="x", yref="paper", x=0, y=1.06, showarrow=False, font_color=ambiguous_color)
    fig.add_annotation(text="Unmethylated", xref="x", yref="paper", x=(xmin+min_diff_llr)/2-min_diff_llr, y=1.06, showarrow=False, font_color=unmethylated_color)
    fig.add_annotation(text="Methylated", xref="x", yref="paper", x=(xmax-min_diff_llr)/2+min_diff_llr, y=1.06, showarrow=False, font_color=methylated_color)

    # tweak figure layout
    fig.update_layout(
        dict1 = {'showlegend':False, 'hovermode':'closest', "plot_bgcolor":'rgba(0,0,0,0)',"width":fig_width, "height":fig_height, "margin":{"t":50,"b":50}},
        xaxis={"showgrid":False, "zeroline":False, "domain":[0, 1], "title":"CpG median log likelihood ratio", "range":(xmin, xmax)},
        yaxis={"fixedrange":True, "showgrid":True, 'zeroline':False, "gridcolor":"lightgrey", "automargin":True})

    return fig

def category_barplot (
    df,
    methylated_color:str = 'rgb(215,48,39)',
    unmethylated_color:str = 'rgb(33,102,172)',
    ambiguous_color:str = 'rgb(150,150,150)',
    no_data_color:str = 'rgb(50,50,50)',
    min_diff_llr:float = 1,
    fig_width:int = None,
    fig_height:int = None):
    """
    Plot a stacked barplot of the number of intervals per category for each samples
    """
    # Cannot calculate if at least not 2 values
    if len(df.columns) <= 1:
        return None

    # Count values per categories
    d = OrderedDict()
    for sample_id, llr_list in df.iterrows():
        sample_d = OrderedDict()
        sample_d["Unmethylated"] = len(llr_list[llr_list <= -min_diff_llr])
        sample_d["Methylated"] = len(llr_list[llr_list >= min_diff_llr])
        sample_d["Ambiguous"] = len(llr_list[(llr_list > -min_diff_llr) & (llr_list < min_diff_llr) ])
        sample_d["No data"] = len(llr_list[llr_list.isna()])
        d[sample_id] = sample_d

    # Cast to dataframe and reorder per value
    count_df = pd.DataFrame.from_dict(d)
    count_df = count_df.reindex(columns=count_df.columns.sort_values())

    # Generate barplot per category
    data = []
    for status, color in [
        ("Unmethylated", unmethylated_color),
        ("Methylated", methylated_color),
        ("Ambiguous", ambiguous_color),
        ("No data", no_data_color)]:
        data.append(go.Bar(name=status, x=count_df.columns, y=count_df.loc[status], marker_color=color, marker_line_color=color, opacity=0.9))

    fig = go.Figure(data)

    # Change the bar mode
    fig.update_layout(barmode='stack', xaxis_tickangle=-45)

    # tweak figure layout
    fig.update_layout(
        barmode='stack',
        dict1 = {"plot_bgcolor":'rgba(0,0,0,0)',"width":fig_width, "height":fig_height, "margin":{"t":50,"b":50}},
        xaxis={"fixedrange":True, "showgrid":False, "tickangle":-45},
        yaxis={"fixedrange":True, "showgrid":True, 'zeroline':False, "title":"Counts per category", "gridcolor":"lightgrey"})

    return fig

def chr_ideogram_plot(
    all_cpg_df,
    ref_fasta_fn,
    n_len_bin:int=1000,
    colorscale:str = "Reds",
    fig_width:int=None,
    fig_height:int=None):
    """Plot an ideogram of significant sites distribution per chromosome """

    # Load chromosome length
    chr_len_d = get_chr_len(ref_fasta_fn)

    # Autodefine length of bins based on longest sequence
    longest_seq = max(chr_len_d.values())

    # Failsafe in case of very short references
    if longest_seq < n_len_bin:
        n_len_bin = longest_seq
    bin_len = longest_seq//n_len_bin

    # Filter out sequences shorter than bin length and store idx for numpy array indexing
    chr_d = OrderedDict()
    idx=0
    for seq_name, seq_len in reversed(list(chr_len_d.items())):
        if seq_len > bin_len:
            chr_d[seq_name] = {"idx":idx, "len":seq_len}
            idx+=1
    # If no valid chromosome
    if not chr_d:
        return None

    # Create zero filled array to count coverage per genomic windows
    cov_array = np.zeros((len(chr_d), n_len_bin+1))
    # Fill in array significant site coordinates
    # for chrom, start, end in all_cpg_d.keys():
    for coord in all_cpg_df.columns:
        chrom, start, end = coord.split("-")
        start = int(start)
        end = int(end)

        if chrom in chr_d:
            chr_idx = chr_d[chrom]["idx"]
            bin_pos = int((start+(end-start)/2)/bin_len)
            cov_array[chr_idx][bin_pos]+=1

    cov_array[cov_array==0] = np.nan
    # If no data entered in cov_array
    if np.all(np.isnan(cov_array)):
        return None

    # Define x and y labels
    y_lab = ["chr {}".format(i) for i in chr_d.keys()]
    x_lab = [i*bin_len for i in range(0, n_len_bin+1)]

    fig = go.Figure()

    # Plot heatmap
    heatmap = go.Heatmap(
        z=cov_array, y=y_lab, x=x_lab, colorscale=colorscale,
        zmin=0, zmax=np.nanquantile(cov_array, 0.99), ygap=10,
        hoverongaps=False, hovertemplate="Significant intervals: %{z}<extra>%{y}:%{x:,}</extra>")
    fig.add_trace(heatmap)

    # Define shapes for chromosome shadowing
    for seq_name, seq_data in chr_d.items():
        seq_idx = seq_data["idx"]
        seq_len = seq_data["len"]
        fig.add_shape(
            go.layout.Shape (
                type="rect", x0=0, y0=seq_idx-0.4, x1=seq_len, y1=seq_idx+0.4,
                fillcolor="whitesmoke", layer="below", line_width=0, name=seq_name))

    # tweak figure layout
    if not fig_height:
        fig_height = 100+30*len(chr_d)

    fig.update_layout(
        dict1 = {'showlegend':False, 'hovermode':'closest', "plot_bgcolor":'rgba(0,0,0,0)',"width":fig_width, "height":fig_height, "margin":{"t":50,"b":50}},
        xaxis={"ticks":"outside", "showgrid":True, 'zeroline':False,'zeroline':False, "domain":[0, 1], "title":"Genomic coordinates"},
        yaxis={"fixedrange":True, "ticks":"outside", 'showgrid':False, 'showline':False, 'zeroline':False, "title":"Reference sequences"})

    return fig

def tss_dist_plot (
    df,
    sig_color:str='rgba(215,48,39,0.5)',
    non_sig_color:str='rgba(33,102,172,0.5)',
    pvalue_threshold:float=0.01,
    max_distance:int=100000,
    n_bins:int=500,
    smooth_sigma:float=2,
    fig_width:int=None,
    fig_height:int=None):

    """Plot an ideogram of significant sites distribution per chromosome """

    sig_val = df["distance to tss"][df["pvalue"]<=pvalue_threshold].dropna()
    non_sig_val = df["distance to tss"][df["pvalue"]>pvalue_threshold].dropna()
    if sig_val.empty:
        return None

    if not non_sig_val.empty:
        x_ns, y_ns = gaussian_hist (
            val_list=non_sig_val,
            start=-max_distance,
            stop=max_distance,
            num=n_bins,
            smooth_sigma=smooth_sigma)

    x_sig, y_sig = gaussian_hist (
        val_list=sig_val,
        start=-max_distance,
        stop=max_distance,
        num=n_bins,
        smooth_sigma=smooth_sigma)

    fig = go.Figure()

    # Plot significant trace
    sig_trace = go.Scatter (
        x=x_sig, y=y_sig,
        name="Significant",
        fill='tozeroy',
        fillcolor=sig_color,
        line_color=sig_color,
        mode="lines")
    fig.add_trace(sig_trace)

    # Add non significant trace if data available
    if not non_sig_val.empty:
        ns_trace = go.Scatter (
            x=x_ns, y=y_ns,
            name="Non_significant",
            fill='tozeroy',
            fillcolor=non_sig_color,
            line_color=non_sig_color,
            mode="lines")
        fig.add_trace(ns_trace)

    # tweak figure layout
    fig.update_layout(
        dict1 = {"plot_bgcolor":'rgba(0,0,0,0)',"width":fig_width, "height":fig_height, "margin":{"t":50,"b":50}},
        xaxis={"fixedrange":False, "showgrid":True, 'zeroline':False, "title":'Distance to closest TSS',},
        yaxis={"fixedrange":True, "showgrid":True, 'zeroline':False, "title":"CpG Islands density"})

    return fig

#~~~~~~~~~~~~~~~~~~~~~~~~Help functions~~~~~~~~~~~~~~~~~~~~~~~~#

def get_jinja_template (template_fn):
    """Load Jinja template"""
    try:
        env = jinja2.Environment (
            loader=jinja2.PackageLoader('pycoMeth', 'templates'),
            autoescape=jinja2.select_autoescape(["html"]))

        template = env.get_template(template_fn)
        return template

    except (FileNotFoundError, IOError, jinja2.exceptions.TemplateNotFound, jinja2.exceptions.TemplateSyntaxError):
        print("\t\tFile not found, non-readable or invalid")

def render_df (df, empty_msg="No data"):
    """Render_dataframe in HTML"""
    # Return placeholder if empty
    if df.empty:
        return f"<div class='empty'><p class='empty-title h6'>{empty_msg}</p></div>"
    else:
        table = df.to_html(
            classes=["table","table-striped","table-hover", "table-scroll"],
            border=0,
            index=False,
            justify="justify-all",
            escape=False)
        return table

def render_fig (fig, empty_msg="No data"):
    """Render plotly figure in HTML"""
    # Return placeholder if empty
    if not fig:
        return f"<div class='empty'><p class='empty-title h6'>{empty_msg}</p></div>"

    fig.update_layout(margin={"t":50,"b":50})
    rendering = py.plot(
        fig,
        output_type='div',
        include_plotlyjs=False,
        image_width='',
        image_height='',
        show_link=False,
        auto_open=False)
    return rendering

def prev_fn (rank_fn_dict, rank):
    """Get the filepath for the previous interval in rank. The first interval links to the last"""
    prev_rank = len(rank_fn_dict) if rank == 1 else rank-1
    return rank_fn_dict[prev_rank]

def next_fn (rank_fn_dict, rank):
    """Get the filepath for the next interval in rank. The last interval links to the first"""
    prev_rank = 1 if rank == len(rank_fn_dict) else rank+1
    return rank_fn_dict[prev_rank]

def md5_str (fn):
    """Compute md5 has for a given file"""
    hash_md5 = hashlib.md5()
    with open(fn, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hash_md5.update(chunk)
    return hash_md5.hexdigest()

def gaussian_hist (val_list, start, stop, num, smooth_sigma=1):
    """return a histogram smoothed with a gaussian filter"""
    # Compute histogram with numpy
    y, bins = np.histogram (a=val_list, bins=np.linspace(start=start, stop=stop, num=num))
    # x labels = middle of each bins
    x = [(bins[i]+bins[i+1])/2 for i in range(0, len(bins)-1)]
    # Normalise and smooth y data
    y = y/y.sum()
    y = gaussian_filter1d (y, sigma=smooth_sigma)
    return (x,y)