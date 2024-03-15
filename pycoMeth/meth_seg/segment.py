import numpy as np
from meth5.sparse_matrix import SparseMethylationMatrixContainer
import logging

from pycoMeth.meth_seg.math import llr_to_p
from pycoMeth.meth_seg.emissions import BernoulliPosterior
from pycoMeth.meth_seg.hmm import SegmentationHMM
from pycoMeth.meth_seg.postprocessing import cleanup_segmentation


def segment(sparse_matrix: SparseMethylationMatrixContainer, max_segments_per_window: int, verbose: bool = False, core_number: int = None, log: logging.Logger = None):
    log.debug(f"Core {core_number}: Starting segmentation")
    
    log.debug(f"Core {core_number}: Converting sparse matrix to dense")
    llrs = np.array(sparse_matrix.met_matrix.todense())
    
    log.debug(f"Core {core_number}: Converting llrs to probabilities")
    obs = llr_to_p(llrs)
    samples = sparse_matrix.read_samples
    
    log.debug(f"Core {core_number}: Getting unique samples")
    unique_samples = list(set(samples))
    
    log.debug(f"Core {core_number}: Creating sample dictionaries")
    id_sample_dict = {i: s for i, s in enumerate(unique_samples)}
    sample_id_dict = {v: k for k, v in id_sample_dict.items()}
    
    log.debug(f"Core {core_number}: Converting samples to ids")
    sample_ids = np.array([sample_id_dict[s] for s in samples])
    
    log.debug(f"Core {core_number}: Creating emission likelihoods")
    emission_lik = BernoulliPosterior(len(unique_samples), max_segments_per_window, prior_a=None)
    
    log.debug(f"Core {core_number}: Creating HMM")
    hmm = SegmentationHMM(
        max_segments=max_segments_per_window, t_stay=0.1, t_move=0.8, e_fn=emission_lik, eps=np.exp(-512)
    )
    
    log.debug(f"Core {core_number}: Running Baum-Welch algorithm")
    segment_p, posterior = hmm.baum_welch(obs, tol=np.exp(-8), samples=sample_ids, verbose = verbose)
    
    log.debug(f"Core {core_number}: Running MAP estimation")
    segmentation, _ = hmm.MAP(posterior)
    
    log.debug(f"Core {core_number}: Cleaning up segmentation")
    segment_p_array = np.concatenate([v[np.newaxis, :] for v in segment_p.values()], axis=0)
    segmentation = cleanup_segmentation(segment_p_array, segmentation, min_parameter_diff=0.2)
    
    log.debug(f"Core {core_number}: Finished segmentation")
    
    return segmentation
