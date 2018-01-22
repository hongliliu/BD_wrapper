import itertools
import os

import numpy as np

from astropy.io import fits
from astropy.table import Table


class BayesianDistance(object):
    def __init__(self, filename=None):
        """
        initializes the BayesianDistance class

        Parameters
        ----------
        pathToFortran : file path to the Bayesian distance program
            fileExtension
        fortranScript : read in fortran script of the Bayesian distance
            estimator
        pathToFile : file path to weighted FITS cube containing information
            about the decomposed Gaussians
        pathToTable : file path of the astropy table which contains the
            distance results
        pathToInputTable : file path of a table containing information of the
            Gaussian decompositions
        inputTable : table containing information of the Gaussian
            decompositions
        saveInputTable : The default is 'False'. If set to 'True' `inputTable`
            is saved in the directory `pathToTable`
        verbose : The default is 'True'. Prints status messages to the
            terminal.
        gpySetting : The default is 'False'. Set it to 'True' if `inputTable`
            is created from a GaussPy decomposition
        intensityThreshold : Sets the threshold in integrated intensity of
            which decomposed Gaussian components should be considered. The
            default is '0.1'.
        distanceSpacing : Only used for the creation of ppp distance cubes.
            The default is '0.1' [kpc]
        """
        self.pathToFortran = os.path.join('/disk1', 'riener',
                                          'Bayesian_distance')
        pathToFile = os.path.join(
                self.pathToFortran, "Bayesian_distance_v1.0.f")
        with open(pathToFile, "r") as fin:
            fortranScript = fin.readlines()
        self.fortranScript = fortranScript
        self.tableKdaInfo1 = Table.read(
            os.path.join(self.pathToFortran, 'KDA_info_EB+15.dat'),
            format='ascii')
        self.tableKdaInfo2 = Table.read(
            os.path.join(self.pathToFortran, 'KDA_info_RD+09.dat'),
            format='ascii')
        self.tableKdaInfo3 = Table.read(
            os.path.join(self.pathToFortran, 'KDA_info_Urquhart+17.dat'),
            format='ascii')
        self.pathToFile = None
        self.pathToTable = None
        self.pathToInputTable = None
        self.inputTable = None
        self.saveInputTable = False
        self.verbose = True
        self.gpySetting = False
        self.intensityThreshold = 0.1
        self.distanceSpacing = 0.1  # in [kpc]
        self.addKinematicDistance = True
        self.colNameLon, self.colNameLat, self.colNameVel,\
            self.colNameKda = (None for i in range(4))
        self.colNrLon, self.colNrLat, self.colNrVel,\
            self.colNrKda = (None for i in range(4))
        self.prob_SA, self.prob_KD, self.prob_GL, self.prob_PS =\
            0.5, 1.0, 1.0, 0.25

    def set_probability_controls(self):
        s = '      '

        cwd = os.getcwd()
        os.chdir(self.pathToFortran)

        with open(os.path.join(
                self.pathToFortran, 'probability_controls.inp'), 'r') as fin:
            file_content = fin.readlines()
        with open(os.path.join(
                self.pathToFortran, 'probability_controls.inp'), 'w') as fout:
            for line in file_content:
                if not line.startswith('!'):
                    line = '{s}{a}{s}{b}{s}{c}{s}{d}'.format(
                        s=s, a=self.prob_SA, b=self.prob_KD, c=self.prob_GL,
                        d=self.prob_PS)
                fout.write(line)
        os.chdir(cwd)

    def make_fortran_out(self, source):
        """
        Create a fortran executable for the source.

        Replaces the default input file in the fortran script of the Bayesian
        distance estimator with the input file of the source, then creates a
        Fortran executable file.
        """
        with open("{}.f".format(self.pathToSource), "w") as fout:
            for line in self.fortranScript:
                fout.write(line.replace('sources_info.inp',
                                        '{}_sources_info.inp'.format(source)))
        os.system('gfortran {}.f -o {}.out'.format(
                self.pathToSource, self.pathToSource))

    def extract_string(self, s, first, last, incl=False):
        """
        Search for a substring inside a string.

        Parameters
        ----------
        s : string that is searched for the substring
        first : first characters of the substring
        last : last characters of the substring
        incl : defines if the `first` and `last` characters are still part of
            the substring that will be returned. The default is `False`
            (`first` and `last` are not part of the returned substring)

        Returns
        -------
        substring of s
        """
        try:
            if incl is True:
                start = s.index(first)
                end = s.index(last) + len(last)
            else:
                start = s.index(first) + len(first)
                end = s.index(last, start)
            return s[start:end]
        except ValueError:
            return ""

    def extract_probability_info(self, line, lon, lat, pFar, kinDist):
        """
        Extract the distance results from the corresponding string in
        the output file of the Bayesian distance estimator tool.
        """
        deleteString = self.extract_string(
                line, 'Probability component', ':', incl=True)
        replaceString = self.extract_string(
                line, 'Probability component', ':')
        line = line.replace(deleteString, replaceString)
        line = line.replace('\n', '')
        comp, dist, err, prob, arm = line.split()
        c_u, c_v, c_w = self.get_cartesian_coords(lon, lat, float(dist))
        # if np.isnan(dist) is True:
        #     dist, err, prob = (0.0 for i in range(3))
        return [comp, dist, err, prob, arm,
                c_u, c_v, c_w, pFar, kinDist[0], kinDist[1]]

    def extract_results(self, result_file_content, kinDist=None):
        """
        Loop through the lines of the output file of the Bayesian distance
        estimator tool and search for the distance results.

        Parameters
        ----------
        result_file_content : List containing read-in lines of the output file
            ({source_name}.prt) of the Bayesian distance estimator tool
        """
        results = []
        flag = False
        for line in result_file_content:
            if flag:
                params = line.split()
                lon, lat, pFar =\
                    float(params[1]), float(params[2]), float(params[4])
                flag = False
            if 'Extra_info' in line:
                flag = True
            searchString = 'Probability component'
            if searchString in line:
                results.append(self.extract_probability_info(
                    line, lon, lat, pFar, kinDist))
        return results

    def extract_kinematic_distances(self, result_file_content):
        """"""
        kinDist = [np.NAN, np.NAN]

        flag = 'one'
        for line in result_file_content:
            searchString = 'Kinematic distance(s):'
            if searchString in line:
                if flag == 'one':
                    kinDist[0] = self.extract_kinematic_info(line)
                    flag = 'two'
                elif flag == 'two':
                    kinDist[1] = self.extract_kinematic_info(line)
        return kinDist

    def extract_kinematic_info(self, line):
        """
        Extract the distance results from the corresponding string in
        the output file of the Bayesian distance estimator tool.
        """
        line = line.replace('Kinematic distance(s):', '')
        line = line.replace('\n', '')
        return float(line)

    def get_results(self, source):
        """
        Extract the distance results from the output file ({source_name}.prt)
        of the Bayesian distance estimator tool.
        """
        for dirpath, dirnames, filenames in os.walk(self.pathToFortran):
            for filename in [f for f in filenames
                             if f.startswith(source) and f.endswith(".prt")]:
                with open(os.path.join(self.pathToFortran, filename), 'r') as fin:
                    result_file_content = fin.readlines()
            for filename in [f for f in filenames if f.startswith(source)]:
                os.remove(os.path.join(self.pathToFortran, filename))

        if self.addKinematicDistance:
            kinDist = self.extract_kinematic_distances(result_file_content)
        else:
            kinDist = []
        results = self.extract_results(result_file_content, kinDist)
        return results

    def determine(self, row, idx):
        row = list(row)
        """
        Determine the distance of an lbv data point with the Bayesian distance
        estmator tool.
        """
        if self.gpySetting:
            x_pos, y_pos, z_pos, intensity, lon, lat, vel = row
            source = "X{}Y{}Z{}".format(x_pos, y_pos, z_pos)
        else:
            # source, lon, lat, vel = row
            # source = "LON{}LAT{}VEL{}".format(
            #     row[self.colNrLon], row[self.colNrLat], row[self.colNrVel])
            source = "SRC{}".format(str(idx).zfill(9))
            lon, lat, vel =\
                row[self.colNrLon], row[self.colNrLat], row[self.colNrVel]

        if self.colNrKda is not None:
            if row[self.colNrKda] == 'F':
                p_far = 1.0
            elif row[self.colNrKda] == 'N':
                p_far = 0.0
            else:
                p_far = 0.5
        else:
            p_far = self.check_KDA(lon, lat, vel)

        inputString = "{a}\t{b}\t{c}\t{d}\t{e}\t-\n".format(
            a=source, b=lon, c=lat, d=vel, e=p_far)
        self.pathToSource = os.path.join(self.pathToFortran, source)
        filepath = '{}_sources_info.inp'.format(self.pathToSource)
        with open(filepath, 'w') as fin:
            fin.write(inputString)

        self.make_fortran_out(source)
        cwd = os.getcwd()
        os.chdir(self.pathToFortran)
        os.system('{}.out'.format(source))
        os.chdir(cwd)

        rows = []
        if self.gpySetting:
            row = [x_pos, y_pos, z_pos, intensity, lon, lat, vel]
        # else:
        #     row = [source, lon, lat, vel]
        results = self.get_results(source)
        for result in results:
            rows.append(row + result)

        return rows

    def check_KDA(self, lon, lat, vel):
        pFarVal = 0.5
        first = True
        found_entry = False
        for tableKdaInfo in [self.tableKdaInfo3, self.tableKdaInfo1, self.tableKdaInfo2]:
            if not found_entry:
                for lonMin, lonMax, latMin, latMax, velMin, velMax, kda, pFar in zip(
                        tableKdaInfo['lonMin'], tableKdaInfo['lonMax'],
                        tableKdaInfo['latMin'], tableKdaInfo['latMax'],
                        tableKdaInfo['velMin'], tableKdaInfo['velMax'],
                        tableKdaInfo['KDA'], tableKdaInfo['pFar']):
                    if lonMin < lon < lonMax:
                        if latMin < lat < latMax:
                            if velMin < vel < velMax:
                                if first:
                                    kdaVal, pFarVal = kda, pFar
                                    first = False
                                else:
                                    if kdaVal != kda:
                                        pFarVal = 0.5

        return pFarVal

    def determine_column_indices(self):
        self.colNrLon = self.inputTable.colnames.index(self.colNameLon)
        self.colNrLat = self.inputTable.colnames.index(self.colNameLat)
        self.colNrVel = self.inputTable.colnames.index(self.colNameVel)
        if self.colNameKda is not None:
            self.colNrKda = self.inputTable.colnames.index(self.colNameKda)

    # def get_cartesian_coords(self, row):
    #     from astropy.coordinates import SkyCoord
    #     from astropy import units as u
    #
    #     c = SkyCoord(l=row[self.colNameLon]*u.degree,
    #                  b=row[self.colNameLat]*u.degree,
    #                  distance=row['dist']*u.kpc,
    #                  frame='galactic')
    #     c.representation = 'cartesian'
    #     c_u = round(c.u.value, 4)
    #     c_v = round(c.v.value, 4)
    #     c_w = round(c.w.value, 4)
    #
    #     return [c_u, c_v, c_w]

    def get_cartesian_coords(self, lon, lat, dist):
        from astropy.coordinates import SkyCoord
        from astropy import units as u

        c = SkyCoord(l=lon*u.degree,
                     b=lat*u.degree,
                     distance=dist*u.kpc,
                     frame='galactic')
        c.representation = 'cartesian'
        c_u = round(c.u.value, 4)
        c_v = round(c.v.value, 4)
        c_w = round(c.w.value, 4)

        return c_u, c_v, c_w

    def batch_calculation(self):
        self.check_settings()

        if self.verbose:
            string = str("prob_SA: {a}\nprob_KD: {b}\n"
                         "prob_GL: {c}\nprob_PS: {d}\n".format(
                             a=self.prob_SA, b=self.prob_KD, c=self.prob_GL,
                             d=self.prob_PS))
            print("setting probability controls to the following values:")
            print(string)

        self.set_probability_controls()

        if self.verbose:
            print('calculating Bayesian distance...')

        if self.gpySetting:
            self.create_input_table()
        else:
            self.inputTable = Table.read(self.pathToInputTable, format='ascii')
            self.determine_column_indices()

        self.tableDirname = os.path.dirname(self.pathToTable)
        self.tableFile = os.path.basename(self.pathToTable)
        self.tableFilename, self.tableFileExtension =\
            os.path.splitext(self.tableFile)
        if not os.path.exists(self.tableDirname):
            os.makedirs(self.tableDirname)

        import BD_wrapper.BD_multiprocessing as BD_multiprocessing
        BD_multiprocessing.init([self, self.inputTable])
        results_list = BD_multiprocessing.func()
        print('SUCCESS\n')

        results_list = np.array([item for sublist in results_list
                                 for item in sublist])

        self.create_astropy_table(results_list)

    def initialize_data(self):
        self.dirname = os.path.dirname(self.pathToFile)
        self.file = os.path.basename(self.pathToFile)
        self.filename, self.fileExtension = os.path.splitext(self.file)

        self.tableDirname = os.path.dirname(self.pathToTable)
        self.tableFile = os.path.basename(self.pathToTable)
        if not os.path.exists(self.tableDirname):
            os.makedirs(self.tableDirname)

        hdu = fits.open(self.pathToFile)[0]
        self.data = hdu.data
        self.header = hdu.header
        self.shape = (self.data.shape[0], self.data.shape[1],
                      self.data.shape[2])

    def check_settings(self):
        if (self.pathToFile is None) and (self.pathToInputTable is None):
            errorMessage = str("specify 'pathToFile'")
            raise Exception(errorMessage)

        if self.pathToTable is None:
            errorMessage = str("specify 'pathToTable'")
            raise Exception(errorMessage)

        heading = str(
            '\n==============================================\n'
            'Python wrapper for Bayesian distance estimator\n'
            '==============================================\n')
        if self.verbose:
            print(heading)

    def create_input_table(self):
        if self.verbose:
            print('creating input table...')

        self.initialize_data()

        velocityOffset = self.header['CRVAL3'] -\
            self.header['CDELT3']*(self.header['CRPIX3'] - 1)

        x_pos, y_pos, z_pos, intensity, longitude, latitude, velocity = (
                [] for i in range(7))

        for (x, y, z) in itertools.product(range(self.data.shape[2]),
                                           range(self.data.shape[1]),
                                           range(self.data.shape[0])):
            if float(self.data[z, y, x]) > self.intensityThreshold:
                x_pos.append(x)
                y_pos.append(y)
                z_pos.append(z)
                intensity.append(self.data[z, y, x])
                lon = (x - self.header['CRPIX1'])*self.header['CDELT1'] +\
                    self.header['CRVAL1']
                longitude.append(lon)
                lat = (y - self.header['CRPIX2'])*self.header['CDELT2'] +\
                    self.header['CRVAL2']
                latitude.append(lat)
                vel = (velocityOffset + np.array(z) *
                       self.header['CDELT3']) / 1000
                velocity.append(vel)

        names = ['x_pos', 'y_pos', 'z_pos', 'intensity', 'lon', 'lat', 'vel']
        self.inputTable = Table([x_pos, y_pos, z_pos, intensity, longitude,
                                 latitude, velocity], names=names)

        if self.saveInputTable:
            filename = '{}_input.dat'.format(self.filename)
            pathToTable = os.path.join(self.tableDirname, filename)
            self.inputTable.write(pathToTable, format='ascii', overwrite=True)
            if self.verbose:
                print("saved input table '{}' in {}".format(
                        filename, self.tableDirname))

    def create_astropy_table(self, results):
        if self.verbose:
            print('creating Astropy table...')
        if self.gpySetting:
            names = ('x_pos', 'y_pos', 'z_pos', 'intensity', 'lon', 'lat',
                     'vel', 'comp', 'dist', 'e_dist', 'prob', 'arm')
            dtype = ('i4', 'i4', 'i4', 'f4', 'f4', 'f4', 'f4',
                     'i4', 'f4', 'f4', 'f4', 'object')
        else:
            addedColnames = ['comp', 'dist', 'e_dist', 'prob', 'arm',
                             'c_u', 'c_v', 'c_w', 'pFar']
            if self.addKinematicDistance:
                addedColnames += ['kDist_1', 'kDist_2']
            names = self.inputTable.colnames + addedColnames

            dtypeInputTable = []
            for name, dtype in self.inputTable.dtype.descr:
                dtypeInputTable.append(dtype)
            added_dtype = ['i4', 'f4', 'f4', 'f4', 'object',
                           'f4', 'f4', 'f4', 'f4']
            if self.addKinematicDistance:
                added_dtype += ['f4', 'f4']
            dtype = dtypeInputTable + added_dtype

        self.tableResults = Table(data=results, names=names, dtype=dtype)

        for key in ['dist', 'e_dist', 'prob', 'c_u', 'c_v', 'c_w']:
            if key in self.tableResults.colnames:
                self.tableResults[key].format = "{0:.4f}"
        for key in ['pFar', 'kDist_1', 'kDist_2']:
            if key in self.tableResults.colnames:
                self.tableResults[key].format = "{0:.2f}"

        if self.verbose:
            print("saved table '{}' in {}\n".format(
                    self.tableFile, self.tableDirname))

        self.tableResults.write(self.pathToTable, format='ascii',
                                overwrite=True)

    def get_table_distance_max_probability(self):
        from tqdm import tqdm
        if self.verbose:
            print('creating Astropy table containing only distance result '
                  'with the highest probability...')

        remove_rows = []

        for idx, component in tqdm(enumerate(self.tableResults['comp'])):
            if idx == 0:
                comps_indices = [idx]
            else:
                if component == 1:
                    first_idx = True
                    for comps_idx in comps_indices:
                        if first_idx:
                            prob = self.tableResults['prob'][comps_idx]
                            prob_idx = comps_idx
                            first_idx = False
                        else:
                            if self.tableResults['prob'][comps_idx] < prob:
                                remove_rows.append(comps_idx)
                            else:
                                remove_rows.append(prob_idx)
                                prob_idx = comps_idx
                                prob = self.tableResults['prob'][comps_idx]
                    comps_indices = [idx]
                if component != 1:
                    comps_indices.append(idx)

        self.tableResults.remove_rows(remove_rows)

        self.tableFile = '{}{}{}'.format(self.tableFilename, '_p_max',
                                         self.tableFileExtension)
        self.pathToTable = os.path.join(self.tableDirname, self.tableFile)

        if self.verbose:
            print("saved table '{}' in {}".format(
                    self.tableFile, self.tableDirname))

        self.tableResults.write(self.pathToTable, format='ascii',
                                overwrite=True)

    def find_index_max_probability(self, indices, arm=False):
        idx = [i for i in indices]
        prob = [self.table['prob'][i] for i in indices]
        max_idx = prob.index(max(prob))

        if arm:
            arms = [self.table['arm'][i] for i in indices]
            return idx[max_idx], arms[max_idx]
        else:
            return idx[max_idx]

    def make_ppp_intensity_cube(self):
        if self.verbose:
            print('create PPP weighted intensity cube...')

        self.check_settings()
        self.initialize_data()

        self.table = Table.read(self.pathToTable, format='ascii.fixed_width')
        maxDist = int(max(self.table['dist'])) + 1
        zrange = int(maxDist/self.distanceSpacing)
        self.shape = (zrange, self.data.shape[1], self.data.shape[2])
        array = np.zeros(self.shape, dtype='float32')
        self.header['NAXIS3'] = zrange
        self.header['CRPIX3'] = 1.
        self.header['CRVAL3'] = self.distanceSpacing
        self.header['CDELT3'] = self.distanceSpacing
        self.header['CTYPE3'] = 'DISTANCE'
        index_list = []

        for idx, (component, probability) in enumerate(
                zip(self.table['comp'], self.table['dist'])):
            if idx == 0:
                comps_indices = [idx]
            else:
                if component == 1:
                    index = self.find_index_max_probability(comps_indices)
                    index_list.append(index)

                    x = self.table['x_pos'][index]
                    y = self.table['y_pos'][index]
                    dist = round(self.table['dist'][index], 1)
                    z = round(dist / self.distanceSpacing)
                    intensity = self.table['intensity'][index]

                    array[z, y, x] += intensity

                    comps_indices = [idx]
                if component != 1:
                    comps_indices.append(idx)

        filename = '{}_distance_ppp.fits'.format(self.filename)
        pathname = os.path.join(self.tableDirname, 'FITS')
        if not os.path.exists(pathname):
            os.makedirs(pathname)
        pathToFile = os.path.join(pathname, filename)
        fits.writeto(pathToFile, array, self.header, overwrite=True)
        if self.verbose:
            print("saved '{}' in {}".format(filename, pathname))

        def make_ppv_distance_cube(self):
            if self.verbose:
                print('create PPV distance cube...')

            self.check_settings()
            self.initialize_data()

            self.table = Table.read(self.pathToTable,
                                    format='ascii.fixed_width')
            array = np.zeros(self.shape, dtype='float32')
            index_list = []

            for idx, (component, probability) in enumerate(
                    zip(self.table['comp'], self.table['dist'])):
                if idx == 0:
                    comps_indices = [idx]
                else:
                    if component == 1:
                        index = self.find_index_max_probability(comps_indices)
                        index_list.append(index)

                        x = self.table['x_pos'][index]
                        y = self.table['y_pos'][index]
                        z = self.table['z_pos'][index]
                        dist = self.table['dist'][index]

                        array[z, y, x] = dist

                        comps_indices = [idx]
                    if component != 1:
                        comps_indices.append(idx)

            filename = '{}_distance.fits'.format(self.filename)
            pathname = os.path.join(self.tableDirname, 'FITS')
            if not os.path.exists(pathname):
                os.makedirs(pathname)
            pathToFile = os.path.join(pathname, filename)
            fits.writeto(pathToFile, array, self.header, overwrite=True)
            if self.verbose:
                print("saved '{}' in {}".format(filename, pathname))

    def timer(self, mode='start', start_time=None):
        """"""
        import time

        if mode == 'start':
            return time.time()
        elif mode == 'stop':
            print('\njob finished on {}'.format(time.ctime()))
            print('required run time: {:.4f} s\n'.format(
                time.time() - start_time))
