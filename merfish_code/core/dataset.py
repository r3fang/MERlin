import os
import dotenv
import errno
import pickle
import shutil
import pandas
import numpy as np
import re
import csv

from storm_analysis.sa_library import datareader


class DataSet(object):

    def __init__(self, dataDirectoryName, 
            dataName=None, dataHome=None, analysisHome=None):

        dotenvPath = dotenv.find_dotenv()
        dotenv.load_dotenv(dotenvPath)

        if dataHome is None:
            dataHome = os.environ.get('DATA_HOME')

        if analysisHome is None:
            analysisHome = os.environ.get('ANALYSIS_HOME')

        self.rawDataPath = os.sep.join([dataHome, dataDirectoryName])
        if not os.path.isdir(self.rawDataPath):
            raise FileNotFoundError(
                    errno.ENOENT, os.strerror(errno.ENOENT), self.rawDataPath)
            
        self.analysisPath = os.sep.join([analysisHome, dataDirectoryName])
        os.makedirs(self.analysisPath, exist_ok=True)

        self.logPath = os.sep.join([self.analysisPath, 'logs'])
        os.makedirs(self.logPath, exist_ok=True)

        self.figurePath = os.sep.join([self.analysisPath, 'figures'])
        os.makedirs(self.figurePath, exist_ok=True)

    def save_figure(figure, figureName, subDirectory=None):
        if subDirectory is not None:
            savePath = os.sep.join([self.figurePath, subDirectory, figureName])
            os.makedirs(savePath, exist_ok=True)
        else:
            savePath = os.sep.join([self.figurePath, figureName])

        figure.savefig(savePath + '.png', pad_inches=0)
        figure.savefig(savePath + '.pdf', transparent=True, pad_inches=0)

    def _analysis_result_save_path(self, resultName, analysisName,
            resultIndex=None, subdirectory=None):
        saveName = resultName
        if resultIndex is not None:
            saveName += '_' + str(resultIndex)
        return os.sep.join([self.get_analysis_subdirectory(
            analysisName, subdirectory), saveName])

    def save_analysis_result(self, analysisResult, resultName, 
            analysisName, resultIndex=None, subdirectory=None):
        #TODO - only implemented currently for ndarray
        if not isinstance(analysisResult, np.ndarray):
            raise TypeError('analysisResult must be a numpy array')

        savePath = self._analysis_result_save_path(
                resultName, analysisName, resultIndex, subdirectory)
        np.save(savePath, analysisResult)
    
    def load_analysis_result(self, resultName, analysisName, 
            resultIndex=None, subdirectory=None):
        #TODO - This should determine the file extension based on the 
        #files that are present
        savePath = self._analysis_result_save_path(
                resultName, analysisName, resultIndex, subdirectory) + '.npy'
        return np.load(savePath)

    def get_analysis_subdirectory(self, analysisName, subdirectory=None):
        if subdirectory is None:
            subdirectoryPath = os.sep.join(
                    [self.analysisPath, analysisName])
        else:
            subdirectoryPath = os.sep.join(
                    [self.analysisPath, analysisName, subdirectory])
        os.makedirs(subdirectoryPath, exist_ok=True)

        return subdirectoryPath

    def get_task_subdirectory(self, analysisName):
        taskDirectoryPath = os.sep.join(
                [self.get_analysis_subdirectory(analysisName), 'tasks'])
        os.makedirs(taskDirectoryPath, exist_ok=True)

        return taskDirectoryPath
        
    def save_analysis_task(self, analysisTask):
        #TODO - this should be made more adaptable to code changes
        saveName = os.sep.join([self.get_task_subdirectory(
            analysisTask.get_analysis_name()), 'task.pkl'])
        
        with open(saveName, 'wb') as outFile:
            pickle.dump(
                    analysisTask, outFile, protocol=pickle.HIGHEST_PROTOCOL)

    def load_analysis_task(self, analysisTaskName):
        #TODO - this should be made more adaptable to code changes
        loadName = os.sep.join([self.get_task_subdirectory(
            analysisTaskName), 'task.pkl'])

        with open(loadName, 'rb') as inFile:
            return pickle.load(inFile)

    def record_analysis_running(self, analysisTask, fragmentIndex=None):
        self._record_analysis_event(analysisTask, 'run', fragmentIndex)

    def record_analysis_complete(self, analysisTask, fragmentIndex=None):
        self._record_analysis_event(analysisTask, 'done', fragmentIndex)

    def _record_analysis_event(
            self, analysisTask, eventName, fragmentIndex=None):    
        if fragmentIndex is None:
            fileName = analysisTask.get_analysis_name() + '.' + eventName
        else:
            fileName = analysisTask.get_analysis_name() + \
                    '_' + str(fragmentIndex) + '.' + eventName

        fullName = os.sep.join([self.get_task_subdirectory(
            analysisTask.get_analysis_name()), fileName])
        open(fullName, 'a').close()

    def check_analysis_running(self, analysisTask, fragmentIndex=None):
        return self._check_analysis_event(analysisTask, 'run', fragmentIndex)

    def check_analysis_done(self, analysisTask, fragmentIndex=None):
        return self._check_analysis_event(analysisTask, 'done', fragmentIndex)

    def _check_analysis_event(
            self, analysisTask, eventName, fragmentIndex=None):
        if fragmentIndex is None:
            fileName = analysisTask.get_analysis_name() + '.' + eventName
        else:
            fileName = analysisTask.get_analysis_name() + \
                    '_' + str(fragmentIndex) + '.' + eventName
    
        fullName = os.sep.join([self.get_task_subdirectory(
            analysisTask.get_analysis_name()), fileName])
        return os.path.exists(fullName)


class ImageDataSet(DataSet):

    def __init__(self, dataDirectoryName, 
            dataName=None, dataHome=None, analysisHome=None):
        super().__init__(dataDirectoryName, dataName, dataHome, analysisHome)

    def get_image_file_names(self):
        return sorted(
                [os.sep.join([self.rawDataPath, currentFile]) \
                    for currentFile in os.listdir(self.rawDataPath) \
                if currentFile.endswith('.dax') \
                or currentFile.endswith('.tif')])

    def load_image(self, imagePath, frameIndex):
        reader = datareader.inferReader(imagePath)
        return reader.loadAFrame(frameIndex)


class MERFISHDataSet(ImageDataSet):

    def __init__(self, dataDirectoryName, codebookName=None, 
            dataOrganizationName=None,
            dataName=None, dataHome=None, analysisHome=None):
        super().__init__(dataDirectoryName, dataName, dataHome, analysisHome)

        if codebookName is not None:
            self._import_codebook(codebookName)

        if dataOrganizationName is not None:
            self._import_dataorganization(dataOrganizationName)

        self._load_dataorganization()
        self._load_codebook()
        self._map_images()

    def get_bit_names(self):
        '''Get the names of the bits for this MERFISH data set.

        Returns:
            A list of the names of the bits in order from the lowest to highest
        '''
        return self.bitNames

    def get_data_channels(self):
        '''Get the data channels for the MERFISH data set.

        Returns:
            A list of the data channels
        '''
        return self.dataOrganization.index

    def get_data_channel_for_bit(self, bitName):
        '''Get the data channel associated with the specified bit.

        Args:
            bitName: the name of the bit to search for
        Returns:
            The associated data channel
        '''
        return self.dataOrganization[\
                self.dataOrganization['bitName'] == bitName].index.item()


    def get_z_positions(self):
        '''Get the z positions present in this dataset.

        Returns:
            A sorted list of all unique z positions
        '''
        return(sorted(np.unique([x for x in self.dataOrganization['zPos']])))

    def get_image_path(self, imageType, fov, imagingRound):
        selection = self.fileMap[(self.fileMap['imageType'] == imageType) & \
                (self.fileMap['fov'] == fov) & \
                (self.fileMap['imagingRound'] == imagingRound)]

        return selection['imagePath'].values[0]

    def get_fovs(self):
        return np.unique(self.fileMap['fov'])

    def get_imaging_rounds(self):
        return np.unique(self.fileMap['imagingRound'])

    def get_fiducial_filename(self, dataChannel, fov):
        imageType = self.dataOrganization.loc[dataChannel, 'fiducialImageType']
        imagingRound = \
                self.dataOrganization.loc[dataChannel, 'fiducialImagingRound']
        return(self.get_image_path(imageType, fov, imagingRound))

    def get_fiducial_frame(self, dataChannel):
        return self.dataOrganization.loc[dataChannel, 'fiducialFrame']

    def get_raw_image(self, dataChannel, fov, zPosition):
        channelInfo = self.dataOrganization.loc[dataChannel]
        imagePath = self.get_image_path(
                channelInfo['imageType'], fov, channelInfo['imagingRound'])

        channelZ = channelInfo['zPos']
        if isinstance(channelZ, np.ndarray):
            zIndex = np.where(channelZ == zPosition)[0]
            if len(zIndex) == 0:
                frameIndex = 0
            else:
                frameIndex = zIndex[0]
        else:
            frameIndex = 0

        frames = channelInfo['frame']
        if isinstance(frames, np.ndarray):
            frame = frames[frameIndex]
        else:
            frame = frames

        return self.load_image(imagePath, frame)

    def get_fiducial_image(self, dataChannel, fov):
        channelInfo = self.dataOrganization.loc[dataChannel]
        imagePath = self.get_image_path(
                channelInfo['fiducialImageType'], 
                fov, 
                channelInfo['fiducialImagingRound'])
        frame = channelInfo['fiducialFrame']
        return self.load_image(imagePath, frame)

    def _map_images(self):
        #TODO: This doesn't map the fiducial image types and currently assumes
        #that the fiducial image types and regular expressions are part of the 
        #standard image types.
        #TODO: This doesn't verify that all files are present
        mapPath = os.sep.join([self.analysisPath, 'filemap.csv'])

        if not os.path.exists(mapPath):
            uniqueTypes, uniqueIndexes = np.unique(
                self.dataOrganization['imageType'], return_index=True)

            fileNames = self.get_image_file_names()
            fileData = []
            for currentType, currentIndex in zip(uniqueTypes, uniqueIndexes):
                matchRE = re.compile(
                        self.dataOrganization.imageRegExp[currentIndex])


                for currentFile in fileNames:
                    matchedName = matchRE.match(os.path.split(currentFile)[-1])
                    if matchedName is not None:
                        transformedName = matchedName.groupdict()
                        if transformedName['imageType'] == currentType:
                            if 'imagingRound' not in transformedName:
                                transformedName['imagingRound'] = -1
                            transformedName['imagePath'] = currentFile
                            fileData.append(transformedName)
        
            self.fileMap = pandas.DataFrame(fileData)
            self.fileMap[['imagingRound', 'fov']] = \
                    self.fileMap[['imagingRound', 'fov']].astype(int)
    
            self.fileMap.to_csv(mapPath)

        else:
            self.fileMap = pandas.read_csv(mapPath)

    def _parse_list(self, inputString, dtype=float):
        return np.fromstring(inputString.strip('[]'), dtype=dtype, sep=',')

    def _parse_int_list(self, inputString):
        return self._parse_list(inputString, dtype=int)

    def _parse_barcode_from_string(self, inputString):
        return np.fromstring(inputString, dtype=int, sep=' ')

    def _import_codebook(self, codebookName):
        sourcePath = os.sep.join([os.environ.get('CODEBOOK_HOME'), \
                codebookName + '_codebook.csv'])
        destPath = os.sep.join([self.analysisPath, 'codebook.csv'])

        shutil.copyfile(sourcePath, destPath)    

    def _load_codebook(self):
        path = os.sep.join([self.analysisPath, 'codebook.csv'])

        headerLength = 3
        self.codebook = pandas.read_csv(
                path, header=headerLength, skipinitialspace=True,
                usecols=['name','id','barcode'],
                converters={'barcode': self._parse_barcode_from_string})
        with open(path, 'r') as inFile:
            csvReader = csv.reader(inFile, delimiter=',')
            header = [row for i,row in enumerate(csvReader) if i<headerLength]
        self.bitNames = [x.strip() for x in header[2][1:]]

    def _convert_parameter_list(self, listIn, castFunction, delimiter=';'):
        return [castFunction(x) for x in listIn.split(delimiter) if len(x)>0]

    def _import_dataorganization(self, dataOrganizationName):
        sourcePath = os.sep.join([os.environ.get('DATA_ORGANIZATION_HOME'), \
                dataOrganizationName + '.csv'])
        destPath = os.sep.join([self.analysisPath, 'dataorganization.csv'])
            
        shutil.copyfile(sourcePath, destPath)    

    def _load_dataorganization(self):
        path = os.sep.join([self.analysisPath, 'dataorganization.csv'])
        self.dataOrganization = pandas.read_csv(
                path, 
                converters={'frame': self._parse_int_list,
                    'zPos': self._parse_list})
