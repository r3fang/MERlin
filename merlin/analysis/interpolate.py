from typing import List
from typing import Union
import numpy as np
from skimage import transform
from skimage import registration
from skimage import feature
from scipy.ndimage.interpolation import map_coordinates

import cv2
import os
import tifffile
from scipy import ndimage
from merlin.core import analysistask
from merlin.util import aberration
from merlin.util import imagewriter

class Interpolate3D(analysistask.ParallelAnalysisTask):

    """
    An abstract class for interpolating 3D image stack
    between images taken in different imaging rounds.
    """

    def __init__(self, dataSet, parameters=None, analysisName=None):
        super().__init__(dataSet, parameters, analysisName)
        
        if "write_aligned_feature_images" not in self.parameters:
            self.parameters['write_aligned_feature_images'] = True

        if "write_aligned_images" not in self.parameters:
            self.parameters['write_aligned_images'] = True

        if "highpass_sigma" not in self.parameters:
            self.parameters['highpass_sigma'] = -1

        if "median_filter_size" not in self.parameters:
            self.parameters['median_filter_size'] = 2

        self.parameters['z_pixel_size_micron'] = \
            float(self.parameters["z_pixel_size_micron"])
            
    def fragment_count(self):
        return len(self.dataSet.get_fovs())

    def get_estimated_memory(self):
        return 2048

    def get_estimated_time(self):
        return 5

    def get_dependencies(self):
        return []

    def interpolate_single_image(self, movie, zIndex, shifts):
        # get the 3D coordinates
        single_im_size = np.array([movie.shape[1], movie.shape[2]])
        _coords = np.meshgrid( 
            np.arange(single_im_size[0]), 
            np.arange(single_im_size[1]),)
    
        _coords = np.stack(_coords).transpose((0, 2, 1)) # transpose is necessary 
        _coords = _coords.reshape(_coords.shape[0], -1)
        _coords_3D = np.zeros([3, _coords.shape[1]])
        _coords_3D[0,:] = zIndex - shifts[0]
        _coords_3D[1,:] = _coords[0,:] - shifts[1]
        _coords_3D[2,:] = _coords[1,:] - shifts[2]
    
        _corr_im = map_coordinates(movie, _coords_3D, order=1)
        return _corr_im.reshape(single_im_size).astype(movie.dtype)

    def get_interpolated_image(
            self, fov: int, 
            dataChannel: int, 
            zPos: float) -> np.ndarray:

        """Get the specific interpolated image 

        Args:
            fov: index of the field of view
            dataChannel: index of the data channel
            zpos: a specific z position in micron to be interoplated
        Returns:
            a 2-dimensional numpy array containing the specific interpolated image
        """
    
        zPositions = self.dataSet.get_z_positions()
        zPixelSizeMicron = self.parameters['z_pixel_size_micron']
        zmax = max(zPositions)
        
        movie = np.zeros([
            int(zmax / zPixelSizeMicron) + 1, 
            self.dataSet.get_image_dimensions()[0],
            self.dataSet.get_image_dimensions()[1]])
        
        for z in zPositions:
            movie[int(z / zPixelSizeMicron)] = \
                self.dataSet.get_raw_image(dataChannel, fov, z)

        return self.interpolate_single_image(
            movie = movie,
            zIndex = zPos / zPixelSizeMicron,
            shifts = self.get_shift_micron(fov, dataChannel) * zPos)

    def get_interpolated_image_set(
            self, fov: int, 
            dataChannel: int, 
            zPosList: List
            ) -> np.ndarray:

        """Get the interpolated image set

        Args:
            fov: index of the field of view
            dataChannel: index of the data channel
            zPosList: a list of z positions in micron to be interpolated
        Returns:
            a 3-dimensional numpy array containing the interpolated image set
        """
    
        zPositions = self.dataSet.get_z_positions()
        zPixelSizeMicron = self.parameters['z_pixel_size_micron']
        zmax = min(self.dataSet.dataOrganization.get_feature_z_positions())
        
        movie = np.zeros([
            int(zmax / zPixelSizeMicron) + 1, 
            self.dataSet.get_image_dimensions()[0],
            self.dataSet.get_image_dimensions()[1]])

        for z in zPositions:
            movie[int(z / zPixelSizeMicron)] = \
                self.dataSet.get_raw_image(dataChannel, fov, z)
        
        return [ self.interpolate_single_image(
                            movie = movie, 
                            zIndex = zPos / zPixelSizeMicron, 
                            shifts = self.get_shift_micron(fov, dataChannel) * zPos) \
                        for zPos in zPosList ]

    def get_transformation(self, fov: int, dataChannel: int=None
                            ) ->np.ndarray:
        transformationMatrices = self.dataSet.load_numpy_analysis_result(
            'offsets', self, resultIndex=fov, subdirectory='transformations')
        if dataChannel is not None:
            return transformationMatrices[dataChannel]
        else:
            return transformationMatrices

    def get_shift_pixel(self, fov: int, dataChannel: int=None):
        shifts = self.dataSet.load_numpy_analysis_result(
            'offsets', self, resultIndex=fov, subdirectory='shifts')
        if dataChannel is not None:
            return shifts[dataChannel]
        else:
            return shifts

    def get_shift_micron(self, fov: int, dataChannel: int=None):
        shifts = self.dataSet.load_numpy_analysis_result(
            'offsets', self, resultIndex=fov, subdirectory='shifts')
        zmax = min(self.dataSet.dataOrganization.get_feature_z_positions())
        shifts = shifts / zmax
        if dataChannel is not None:
            return shifts[dataChannel]
        else:
            return shifts

    def _filter(self, inputImage: np.ndarray) -> np.ndarray:
        return self._high_pass_filter(self._median_filter(inputImage))

    def _filter_set(self, inputImages: np.ndarray) -> np.ndarray:
        return np.array([ self._high_pass_filter(self._median_filter(x)) \
            for x in inputImages ])

    def _median_filter(self, inputImage: np.ndarray) -> np.ndarray:
        median_filter_size = self.parameters['median_filter_size']
        return ndimage.median_filter(inputImage, 
            size=median_filter_size, mode="mirror")
    
    def _high_pass_filter(self, inputImage: np.ndarray) -> np.ndarray:
        highPassSigma = self.parameters['highpass_sigma']
        if highPassSigma == -1:
            return inputImage
        highPassFilterSize = int(2 * np.ceil(2 * highPassSigma) + 1)
        return inputImage.astype(float) - cv2.GaussianBlur(
                inputImage, (highPassFilterSize, highPassFilterSize),
                highPassSigma, borderType=cv2.BORDER_REPLICATE) 

    def get_feature_image_set(self, dataChannel, fov: int):
        return np.array([ self.dataSet.get_feature_image(dataChannel, fov, zpos) \
            for zpos in self.dataSet.get_data_organization().get_feature_z_positions() ])

    def _save_transformations(self, transformationList, fov: int) -> None:
        self.dataSet.save_numpy_analysis_result(
            np.array(transformationList), 'offsets',
            self.get_analysis_name(), resultIndex=fov,
            subdirectory='transformations')

    def _save_shifts(self, shiftList, fov: int) -> None:
        self.dataSet.save_numpy_analysis_result(
            np.array(shiftList), 'offsets',
            self.get_analysis_name(), resultIndex=fov,
            subdirectory='shifts')
    
    def _analysis_image_name(self,
                             subdirectory: str,
                             imageBaseName: str, 
                             imageIndex: int,
                             dataChannel: int,
                             fileType = "tif"
                             ) -> str:
        destPath = self.dataSet.get_analysis_subdirectory(
                self, subdirectory=subdirectory)
        return os.sep.join([destPath, 
            imageBaseName+"_"+str(imageIndex)+"_"+str(dataChannel)+'.'+fileType])

    def writer_for_analysis_images(self,
                                   movie: np.ndarray,
                                   subdirectory: str,
                                   imageBaseName: str,
                                   imageIndex: int,
                                   dataChannel: int,
                                   fileType = 'dax'
                                   ) -> None:
        
        fname = self._analysis_image_name(
                subdirectory, imageBaseName,
                imageIndex, dataChannel, 
                fileType)
        
        if fileType == "dax":
            f = imagewriter.DaxWriter(fname)
            for x in movie.astype(np.uint16):
                f.addFrame(x)
            f.close()
        else:
            tifffile.imwrite(
                data=movie.astype(np.uint16),
                file=fname)

    def _run_analysis(self, fragmentIndex: int):

        try:
            shifts3D = self.get_shift_pixel(fragmentIndex);
            shifts2D = self.get_transformation(fragmentIndex);
        except (FileNotFoundError, OSError, ValueError):

            fixImage = np.array([self._filter(
                self.dataSet.get_feature_fiducial_image(0, fragmentIndex))
                                ]);

            shifts2D = np.array([registration.phase_cross_correlation(
                reference_image = fixImage,
                moving_image = np.array([self._filter(
                    self.dataSet.get_feature_fiducial_image(x, fragmentIndex))
                                       ]),
                upsample_factor = 100)[0] for x in \
                    self.dataSet.get_data_organization().get_data_channels()
                                ])
            self._save_transformations(
                shifts2D, fragmentIndex)
            
            fixImageStack = self._filter_set(self.get_feature_image_set(0, fragmentIndex))

            shifts3D = np.array([
                registration.phase_cross_correlation(
                    reference_image = fixImageStack,
                    moving_image = self._filter_set(
                        self.get_feature_image_set(x, fragmentIndex)),
                    upsample_factor = 100)[0] for x in \
                    self.dataSet.get_data_organization().get_data_channels()])

            shifts3D = shifts3D - shifts2D
            self._save_shifts(
                shifts3D, fragmentIndex)

        if self.parameters['write_aligned_feature_images']:
            dataChannels = self.dataSet.get_data_organization().get_data_channels()
            for dataChannel in dataChannels:
                featureImages = self._filter_set(
                        self.get_feature_image_set(dataChannel, fragmentIndex))
                transformations_xy = transform.SimilarityTransform(
                    translation=[-(shifts2D[dataChannel,2] + shifts3D[dataChannel,2]), 
                                 -(shifts2D[dataChannel,1] + shifts3D[dataChannel,1])]);

                warpedImages = np.array([ 
                        transform.warp(
                            x, transformations_xy, 
                            preserve_range=True
                            ).astype(featureImages.dtype) \
                    for x in featureImages ]);
                
                # warp based on y,z estimated by 3D beads
                imageSet = np.zeros(warpedImages.shape)
                for i in range(warpedImages.shape[1]):
                    transformations_xz = transform.SimilarityTransform(
                        translation=[-shifts3D[dataChannel,2], 
                                     -shifts3D[dataChannel,0]]);
                    imageSet[:,i,:] = transform.warp(
                        warpedImages[:,i,:], 
                        transformations_xz, 
                        preserve_range=True
                        ).astype(warpedImages.dtype)

                imageSet[imageSet < 0] = 0
                self.writer_for_analysis_images(
                    imageSet.astype(np.uint16), 
                    subdirectory = "interpolatedFeatureImages",
                    imageBaseName = "images", 
                    imageIndex = fragmentIndex,
                    dataChannel = dataChannel,
                    fileType = "tif")

        # write down interpolated images
        if self.parameters['write_aligned_images']:
            dataChannels = self.dataSet.get_data_organization().get_data_channels()
            for dataChannel in dataChannels:
                imageSet = self.get_interpolated_image_set(
                        fragmentIndex, dataChannel,
                        self.parameters["z_coordinates_micron"]) 
                
                fimage = self.dataSet.get_fiducial_image(
                    dataChannel, fragmentIndex)
            
                self.writer_for_analysis_images(
                    np.array([fimage] + imageSet), 
                    subdirectory = "interpolatedImages",
                    imageBaseName = "images", 
                    imageIndex = fragmentIndex,
                    dataChannel = dataChannel,
                    fileType = "dax")

