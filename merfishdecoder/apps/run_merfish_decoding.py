#!/usr/bin/python
# ----------------------------------------------------------------------------------------
# An application to run MERFISH decode.
# ----------------------------------------------------------------------------------------
# Rongxin Fang
# latest update: 04/15/21
# r4fang@gmail.com
# ----------------------------------------------------------------------------------------

import argparse
import os, sys
import pickle
import pandas as pd
import numpy as np
import geopandas as geo

from merfishdecoder.core import zplane
from merfishdecoder.util import registration
from merfishdecoder.util import preprocessing
from merfishdecoder.util import imagefilter
from merfishdecoder.util import utilities
from merfishdecoder.util import decoder
from merfishdecoder.util import barcoder

class merfishTask:

    """
    A object for merfish task.

    """

    def __init__(self, **arguments):
        for (arg, val) in arguments.items():
            setattr(self, arg, val)

    def to_string(self):
        return ("\n".join(["%s = %s" % (str(key), str(val)) \
                for (key, val) in self.__dict__.items() ]))
    
    def run_job(self):

        dataSetName = self.data_set_name
        fov = self.fov
        zpos = self.zpos
        psmName = self.psm_name
        maxCores = self.max_cores
        outputName = self.output_name
        refFrameIndex = self.ref_frame_index
        highPassFilterSigma = self.high_pass_filter_sigma
        borderSize = self.border_size
        magnitudeThreshold = self.magnitude_threshold
        distanceThreshold = self.distance_threshold
        barcodesPerCore = self.barcodes_per_core
        
        utilities.print_checkpoint(self.to_string() + "\n")
        utilities.print_checkpoint("Start MEFISH Analysis")

        # generate zplane object
        zp = zplane.Zplane(dataSetName,
                           fov=fov,
                           zpos=zpos)

        # load pixel score machine
        psm = pickle.load(open(psmName, "rb"))

        # create the folder
        os.makedirs(os.path.dirname(outputName),
            exist_ok=True)

        utilities.print_checkpoint("Load Readout Images")
        # load readout images
        zp.load_readout_images(
            zp.get_bit_name())

        utilities.print_checkpoint("Correct Stage Drift")
        (zp, errors) = registration.correct_drift(
            obj = zp,
            frameNames = zp.get_bit_name(),
            refFrameIndex = refFrameIndex,
            highPassSigma = highPassFilterSigma)

        utilities.print_checkpoint("Correct Chromatic Abeeration")
        profile = zp.get_chromatic_aberration_profile()
        zp = registration.correct_chromatic_aberration(
            obj = zp,
            frameNames = zp.get_bit_name(),
            profile = profile)

        utilities.print_checkpoint("Remove Cell Background")
        zp = imagefilter.high_pass_filter(
             obj = zp,
             frameNames = zp.get_bit_name(),
             readoutImage = True,
             fiducialImage = False,
             sigma = highPassFilterSigma)

        utilities.print_checkpoint("Adjust Illumination")
        scaleFactors = preprocessing.estimate_scale_factors(
            obj = zp,
            frameNames = zp.get_bit_name())

        # normalize image intensity
        zp = preprocessing.scale_readout_images(
            obj = zp,
            frameNames = zp.get_bit_name(),
            scaleFactors = scaleFactors)

        utilities.print_checkpoint("Pixel-based Decoding")
        decodedImages = decoder.decoding(
                 obj = zp,
                 movie = zp.get_readout_images(zp.get_bit_name()),
                 borderSize = borderSize,
                 distanceThreshold = distanceThreshold,
                 magnitudeThreshold = magnitudeThreshold,
                 numCores = maxCores)

        utilities.print_checkpoint("Extract Barcodes")
        if decodedImages["decodedImage"].max() > -1:
            decodedImages["probabilityImage"] = \
                decoder.calc_pixel_probability(
                    model = psm,
                    decodedImage = decodedImages["decodedImage"],
                    magnitudeImage = decodedImages["magnitudeImage"],
                    distanceImage = decodedImages["distanceImage"],
                    minProbability = 0.01)

            barcodes = barcoder.extract_barcodes(
                decodedImage = decodedImages["decodedImage"],
                distanceImage = decodedImages["distanceImage"],
                probabilityImage = decodedImages["probabilityImage"],
                magnitudeImage = decodedImages["magnitudeImage"],
                barcodesPerCore = barcodesPerCore,
                numCores = maxCores)

            # extract barcodes
            barcodes = barcodes.assign(fov = fov)
            barcodes = barcodes.assign(global_z = zpos)
            barcodes = barcodes.assign(z = \
                zp._dataSet.get_z_positions().index(zpos))
        else:
            barcodes = pd.DataFrame([],
                columns=['x', 'y', 'barcode_id', 'likelihood',
                'magnitude', 'distance', 'area', 'fov', 'global_z', 'z'])

        # save barcodes
        barcodes.to_hdf(outputName, key = "barcodes")
        utilities.print_checkpoint("Done")
        

def main():
    parser = argparse.ArgumentParser(description='MERFISH Analysis.')

    parser_req = parser.add_argument_group("required inputs")
    parser_req.add_argument("--data-set-name",
                             type=str,
                             required=True,
                             help="MERFISH dataset name.")

    parser_req.add_argument("--fov",
                             type=int,
                             required=True,
                             help="Field of view.")

    parser_req.add_argument("--zpos",
                             type=float,
                             required=True,
                             help="Z plane.")

    parser_req.add_argument("--psm-name",
                            type=str,
                            required=True,
                            help="Pixel scoring machine name.")

    parser_req.add_argument("--output-name",
                            type=str,
                            required=True,
                            help="Output barcode file name.")

    parser_opt = parser.add_argument_group("optional inputs")
    parser_opt.add_argument("--ref-frame-index",
                            type=int,
                            default=0,
                            help="Reference frame index for correcting drift.")

    parser_opt.add_argument("--high-pass-filter-sigma",
                            type=int,
                            default=3,
                            help="Low pass sigma for high pass filter prior to registration.")

    parser_opt.add_argument("--border-size",
                             type=int,
                             default=80,
                             help="Number of pixels to be ignored from the border.")

    parser_opt.add_argument("--magnitude-threshold",
                             type=float,
                             default=0,
                             help="Threshold for pixel magnitude.")

    parser_opt.add_argument("--distance-threshold",
                            type=float,
                            default=0.6,
                            help="Threshold between pixel trace and closest barcode.")

    parser_opt.add_argument("--barcodes-per-core",
                            type=int,
                            default=10,
                            help="Number of barcodes to be decoded per core.")

    parser_opt.add_argument("--max-cores",
                            type=int,
                            default=1,
                            help="Max number of CPU cores.")
    
    args = parser.parse_args()
    mt = merfishTask(
        dataSetName = args.data_set_name,
        fov = args.fov,
        zpos = args.zpos,
        psmName = args.psm_name,
        maxCores = args.max_cores,
        outputName = args.output_name,
        refFrameIndex = args.ref_frame_index,
        highPassFilterSigma = args.high_pass_filter_sigma,
        borderSize = args.border_size,
        magnitudeThreshold = args.magnitude_threshold,
        distanceThreshold = args.distance_threshold,
        barcodesPerCore = args.barcodes_per_core)

    mt.run_jon()

if __name__ == "__main__":
    main()

