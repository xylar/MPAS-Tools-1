#!/usr/bin/env python
'''
Interpolate fields from an input file to a pre-existing MPAS-LI grid.

The input file can either be CISM format or MPASLI format.

For CISM input files, three interpolation methods are supported:
* a built-in bilinear interpolation method
* a built-in barycentric interpolation method (nearest neighbor is used for extrapolation regions)
* using weights generated by ESMF

For MPAS input files only barycentric interpolation is supported.

Multiple time levels can be interpolated using the --timestart and --timeend options.
Default is to copy the first time level from the source file to the first time level of
the destination file.  If multiple time levels are used, they are translated directly
from the source to the destination.  NOTE: There is no processing of actual time stamps!
NOTE: xtime is NOT copied and must be copied manually, if desired!
'''

from __future__ import absolute_import, division, print_function, \
    unicode_literals

import sys
import numpy as np
import netCDF4
import argparse
import math
from collections import OrderedDict
import scipy.spatial
import time
from datetime import datetime


print("== Gathering information.  (Invoke with --help for more details. All arguments are optional)\n")
parser = argparse.ArgumentParser(formatter_class=argparse.ArgumentDefaultsHelpFormatter)
parser.description = __doc__
parser.add_argument("-s", "--source", dest="inputFile", help="name of source (input) file.  Can be either CISM format or MPASLI format.", default="cism.nc", metavar="FILENAME")
parser.add_argument("-d", "--destination", dest="mpasFile", help="name of destination file on which to interpolate fields.  This needs to be MPASLI format with desired fields already existing.", default="landice_grid.nc", metavar="FILENAME")
parser.add_argument("-m", "--method", dest="interpType", help="interpolation method to use. b=bilinear, d=barycentric, e=ESMF, n=nearest neighbor", default="b", metavar="METHOD")
parser.add_argument("-w", "--weight", dest="weightFile", help="ESMF weight file to input.  Only used by ESMF interpolation method", metavar="FILENAME")
parser.add_argument("-t", "--thickness-only", dest="thicknessOnly", action="store_true", default=False, help="Only interpolate thickness and ignore all other variables (useful for setting up a cullMask)")
parser.add_argument("--timestart", dest="timestart", type=int, default=0, help="time level in input file to start from (0-based)")
parser.add_argument("--timeend", dest="timeend", type=int, default=0, help="time level in input file to end with (0-based, inclusive)")
args = parser.parse_args()


print("  Source file:  {}".format(args.inputFile))
print("  Destination MPASLI file to be modified:  {}".format(args.mpasFile))

print("  Interpolation method to be used:  {}".format(args.interpType))
print("    (b=bilinear, d=barycentric, e=esmf)")

if args.weightFile and args.interpType == 'e':
    print("  Interpolation will be performed using ESMF-weights method, where possible, using weights file:  {}".format(args.weightFile))
    #----------------------------
    # Get weights from file
    wfile = netCDF4.Dataset(args.weightFile, 'r')
    S = wfile.variables['S'][:]
    col = wfile.variables['col'][:]
    row = wfile.variables['row'][:]
    wfile.close()
    #----------------------------

print('') # make a space in stdout before further output



#----------------------------
#----------------------------
# Define needed functions
#----------------------------
#----------------------------

def ESMF_interp(sourceField):
    # Interpolates from the sourceField to the destinationField using ESMF weights
  try:
    # Initialize new field to 0 - required
    destinationField = np.zeros(xCell.shape)  # fields on cells only
    sourceFieldFlat = sourceField.flatten()  # Flatten source field
    for i in range(len(row)):
      destinationField[row[i]-1] = destinationField[row[i]-1] + S[i] * sourceFieldFlat[col[i]]
  except:
     'error in ESMF_interp'
  return destinationField

#----------------------------

def BilinearInterp(Value, gridType):
    # Calculate bilinear interpolation of Value field from x, y to new ValueCell field (return value)  at xCell, yCell
    # This assumes that x, y, Value are regular CISM style grids and xCell, yCell, ValueCell are 1-D unstructured MPAS style grids

    ValueCell = np.zeros(xCell.shape)

    if gridType == 'x0':
        x = x0; y = y0
    elif gridType == 'x1':
        x = x1; y = y1
    else:
        sys.exit('Error: unknown CISM grid type specified.')
    dx = x[1] - x[0]
    dy = y[1] - y[0]
    for i in range(len(xCell)):
       # Calculate the CISM grid cell indices (these are the lower index)
       xgrid = int(math.floor( (xCell[i]-x[0]) / dx ))
       if xgrid >= len(x) - 1:
          xgrid = len(x) - 2
       elif xgrid < 0:
          xgrid = 0
       ygrid = int(math.floor( (yCell[i]-y[0]) / dy ))
       if ygrid >= len(y) - 1:
          ygrid = len(y) - 2
       elif ygrid < 0:
          ygrid = 0
       #print(xgrid, ygrid, i)
       ValueCell[i] = Value[ygrid,xgrid] * (x[xgrid+1] - xCell[i]) * (y[ygrid+1] - yCell[i]) / (dx * dy) + \
                 Value[ygrid+1,xgrid] * (x[xgrid+1] - xCell[i]) * (yCell[i] - y[ygrid]) / (dx * dy) + \
                 Value[ygrid,xgrid+1] * (xCell[i] - x[xgrid]) * (y[ygrid+1] - yCell[i]) / (dx * dy) + \
                 Value[ygrid+1,xgrid+1] * (xCell[i] - x[xgrid]) * (yCell[i] - y[ygrid]) / (dx * dy)
    return ValueCell

#----------------------------

def delaunay_interp_weights(xy, uv, d=2):
    '''
    xy = input x,y coords
    uv = output (MPSALI) x,y coords
    '''

    #print("scipy version=", scipy.version.full_version)
    if xy.shape[0] > 2**24-1:
       print("WARNING: The source file contains more than 2^24-1 (16,777,215) points due to a limitation in older versions of Qhull (see: https://mail.scipy.org/pipermail/scipy-user/2015-June/036598.html).  Delaunay creation may fail if Qhull being linked by scipy.spatial is older than v2015.0.1 2015/8/31.")

    tri = scipy.spatial.Delaunay(xy)
    print("    Delaunay triangulation complete.")
    simplex = tri.find_simplex(uv)
    print("    find_simplex complete.")
    vertices = np.take(tri.simplices, simplex, axis=0)
    print("    identified vertices.")
    temp = np.take(tri.transform, simplex, axis=0)
    print("    np.take complete.")
    delta = uv - temp[:, d]
    bary = np.einsum('njk,nk->nj', temp[:, :d, :], delta)
    print("    calculating bary complete.")
    wts = np.hstack((bary, 1 - bary.sum(axis=1, keepdims=True)))

    # Now figure out if there is any extrapolation.
    # Find indices to points of output file that are outside of convex hull of input points
    outsideInd = np.nonzero(tri.find_simplex(uv)<0)
    outsideCoords = uv[outsideInd]
    #print(outsideInd)
    nExtrap = len(outsideInd[0])
    if nExtrap > 0:
       print("    Found {} points requiring extrapolation.  Using nearest neighbor extrapolation for those.".format(nExtrap))

    # Now find nearest neighbor for each outside point
    # Use KDTree of input points
    tree = scipy.spatial.cKDTree(xy)

    return vertices, wts, outsideInd, tree

#----------------------------

def nn_interp_weights(xy, uv, d=2):
    '''
    xy = input x,y coords
    uv = output (MPSALI) x,y coords
    Note: could separate out building tree and interpolation for efficiency if many fields need to be processed
    '''
    tree = scipy.spatial.cKDTree(xy)
    dist,idx = tree.query(uv, k=1)  # k is the number of nearest neighbors.
#    outfield = values.flatten()[idx]  # 2d cism fields need to be flattened. (Note the indices were flattened during init, so this just matches that operation for the field data itself.)  1d mpas fields do not, but the operation won't do anything because they are already flat.
    return idx
#----------------------------

def delaunay_interpolate(values, gridType):
    if gridType == 'x0':
       vtx = vtx0; wts = wts0
       tree = treex0
       outsideInd = outsideIndx0
    elif gridType == 'x1':
       vtx = vtx1; wts = wts1
       outsideInd = outsideIndx1
       tree = treex1
    elif gridType == 'cell':
       vtx = vtCell; wts = wtsCell
       outsideInd = outsideIndcell
       tree = treecell
    else:
        sys.exit('Error: unknown input file grid type specified.')

    outfield = np.einsum('nj,nj->n', np.take(values, vtx), wts)

    # Now apply nearest neighbor to points outside convex hull
    # We could have this enabled/disabled with a command line option, but for now it will always be done.
    # Note: the barycentric interp applied above could be restricted to the points inside the convex hull
    # instead of being applied to ALL points as is currently implemented.  However it is assumed that
    # "redoing" the outside points has a small performance cost because there generally should be few such points
    # and the implementation is much simpler this way.
    outsideCoord = mpasXY[outsideInd,:]
    if len(outsideInd) > 0:
       dist,idx = tree.query(outsideCoord, k=1)  # k is the number of nearest neighbors.  Could crank this up to 2 (and then average them) with some fiddling, but keeping it simple for now.
       outfield[outsideInd] = values.flatten()[idx]  # 2d cism fields need to be flattened. (Note the indices were flattened during init, so this just matches that operation for the field data itself.)  1d mpas fields do not, but the operation won't do anything because they are already flat.

    return outfield

#----------------------------

def interpolate_field(MPASfieldName):

    if fieldInfo[MPASfieldName]['gridType'] == 'x0' and args.interpType == 'e':
       assert "This CISM field is on the staggered grid, and currently this script does not support a second ESMF weight file for the staggered grid."

    InputFieldName = fieldInfo[MPASfieldName]['InputName']
    if filetype=='cism':
       if 'time' in inputFile.variables[InputFieldName].dimensions:
           InputField = inputFile.variables[InputFieldName][timelev,:,:]
       else:
           InputField = inputFile.variables[InputFieldName][:,:]
    elif filetype=='mpas':
       if 'Time' in inputFile.variables[InputFieldName].dimensions:
           InputField = inputFile.variables[InputFieldName][timelev,:]
       else:
           InputField = inputFile.variables[InputFieldName][:]

    print('  Input field  {} min/max: {} {}'.format(InputFieldName, InputField.min(), InputField.max()))

    # Call the appropriate routine for actually doing the interpolation
    if args.interpType == 'b':
        print("  ...Interpolating to {} using built-in bilinear method...".format(MPASfieldName))
        MPASfield = BilinearInterp(InputField, fieldInfo[MPASfieldName]['gridType'])
    elif args.interpType == 'd':
        print("  ...Interpolating to {} using barycentric method...".format(MPASfieldName))
        MPASfield = delaunay_interpolate(InputField, fieldInfo[MPASfieldName]['gridType'])
    elif args.interpType == 'n':
        print("  ...Interpolating to {} using nearest neighbor method...".format(MPASfieldName))
        if fieldInfo[MPASfieldName]['gridType'] == 'x0':
           MPASfield = InputField.flatten()[nn_idx_x0]  # 2d cism fields need to be flattened. (Note the indices were flattened during init, so this just matches that operation for the field data itself.)  1d mpas fields do not, but the operation won't do anything because they are already flat.
        elif fieldInfo[MPASfieldName]['gridType'] == 'x1':
           MPASfield = InputField.flatten()[nn_idx_x1]  # 2d cism fields need to be flattened. (Note the indices were flattened during init, so this just matches that operation for the field data itself.)  1d mpas fields do not, but the operation won't do anything because they are already flat.
        elif fieldInfo[MPASfieldName]['gridType'] == 'cell':
           MPASfield = InputField.flatten()[nn_idx_cell]  # 2d cism fields need to be flattened. (Note the indices were flattened during init, so this just matches that operation for the field data itself.)  1d mpas fields do not, but the operation won't do anything because they are already flat.
    elif args.interpType == 'e':
        print("  ...Interpolating to {} using ESMF-weights method...".format(MPASfieldName))
        MPASfield = ESMF_interp(InputField)
    else:
        sys.exit('ERROR: Unknown interpolation method specified')

    print('  interpolated MPAS {} min/max: {} {}'.format(MPASfieldName, MPASfield.min(), MPASfield.max()))

    if fieldInfo[MPASfieldName]['scalefactor'] != 1.0:
        MPASfield *= fieldInfo[MPASfieldName]['scalefactor']
        print('  scaled MPAS {} min/max: {} {}'.format(MPASfieldName, MPASfield.min(), MPASfield.max()))
    if fieldInfo[MPASfieldName]['offset'] != 0.0:
        MPASfield += fieldInfo[MPASfieldName]['offset']
        print('  offset MPAS {} min/max: {} {}'.format(MPASfieldName, MPASfield.min(), MPASfield.max()))


    return MPASfield

    del InputField, MPASfield

#----------------------------

def interpolate_field_with_layers(MPASfieldName):

    if fieldInfo[MPASfieldName]['gridType'] == 'x0' and args.interpType == 'e':
       assert "This CISM field is on the staggered grid, and currently this script does not support a second ESMF weight file for the staggered grid."

    InputFieldName = fieldInfo[MPASfieldName]['InputName']
    if filetype=='cism':
       if 'time' in inputFile.variables[InputFieldName].dimensions:
           InputField = inputFile.variables[InputFieldName][timelev,:,:,:]
       else:
           InputField = inputFile.variables[InputFieldName][:,:,:]
       inputVerticalDimSize = InputField.shape[0] # vertical index is the first (since we've eliminated time already)
       layerFieldName = inputFile.variables[InputFieldName].dimensions[1] # second dimension is the vertical one - get the name of it
       input_layers = inputFile.variables[layerFieldName][:]
    elif filetype=='mpas':
       if 'Time' in inputFile.variables[InputFieldName].dimensions:
           InputField = inputFile.variables[InputFieldName][timelev,:,:]
       else:
           InputField = inputFile.variables[InputFieldName][:,:]
       inputVerticalDimSize = InputField.shape[1] # vertical index is the second (since we've eliminated time already)
       layerThicknessFractions = inputFile.variables['layerThicknessFractions'][:]
       # build MPAS sigma levels at center of each layer
       input_layers = np.zeros( (inputVerticalDimSize,) )
       if inputVerticalDimSize == len(layerThicknessFractions):
          print("Using layer centers for the vertical coordinate of this field.")
          input_layers[0] = layerThicknessFractions[0] * 0.5
          for k in range(1,inputVerticalDimSize):
             input_layers[k] = input_layers[k-1] + 0.5 * layerThicknessFractions[k-1] + 0.5 * layerThicknessFractions[k]
          layerFieldName = '(sigma levels calculated from layerThicknessFractions)'
       elif inputVerticalDimSize == len(layerThicknessFractions)+1:
          print("Using layer interfaces for the vertical coordinate of this field.")
          input_layers[0] = 0.0
          for k in range(1,inputVerticalDimSize):
             input_layers[k] = input_layers[k-1] + layerThicknessFractions[k]
       else:
           sys.exit("Unknown vertical dimension for this variable source file.")

    # create array for interpolated source field at all layers
    mpas_grid_input_layers = np.zeros( (inputVerticalDimSize, nCells) ) # make it the size of the CISM vertical layers, but the MPAS horizontal locations

    for z in range(inputVerticalDimSize):
        if filetype=='cism':
           print('  Input layer {}, layer {} min/max: {} {}'.format(z, InputFieldName, InputField[z,:,:].min(), InputField[z,:,:].max()))
        elif filetype=='mpas':
           print('  Input layer {}, layer {} min/max: {} {}'.format(z, InputFieldName, InputField[:,z].min(), InputField[z,:].max()))
        # Call the appropriate routine for actually doing the interpolation
        if args.interpType == 'b':
            print("  ...Layer {}, Interpolating this layer to MPAS grid using built-in bilinear method...".format(z))
            mpas_grid_input_layers[z,:] = BilinearInterp(InputField[z,:,:], fieldInfo[MPASfieldName]['gridType'])
        elif args.interpType == 'd':
            print("  ...Layer {}, Interpolating this layer to MPAS grid using built-in barycentric method...".format(z))
            if filetype=='cism':
               mpas_grid_input_layers[z,:] = delaunay_interpolate(InputField[z,:,:], fieldInfo[MPASfieldName]['gridType'])
            elif filetype=='mpas':
               mpas_grid_input_layers[z,:] = delaunay_interpolate(InputField[:,z], fieldInfo[MPASfieldName]['gridType'])
        elif args.interpType == 'n':
            print("  ...Layer {}, Interpolating this layer to MPAS grid using nearest neighbor method...".format(z))
            if fieldInfo[MPASfieldName]['gridType'] == 'x0':
               mpas_grid_input_layers[z,:] = InputField[z,:,:].flatten()[nn_idx_x0]  # 2d cism fields need to be flattened. (Note the indices were flattened during init, so this just matches that operation for the field data itself.)  1d mpas fields do not, but the operation won't do anything because they are already flat.
            elif fieldInfo[MPASfieldName]['gridType'] == 'x1':
               mpas_grid_input_layers[z,:] = InputField[z,:,:].flatten()[nn_idx_x1]  # 2d cism fields need to be flattened. (Note the indices were flattened during init, so this just matches that operation for the field data itself.)  1d mpas fields do not, but the operation won't do anything because they are already flat.
            elif fieldInfo[MPASfieldName]['gridType'] == 'cell':
                mpas_grid_input_layers[z,:] = InputField[:,z].flatten()[nn_idx_cell]  # 2d cism fields need to be flattened. (Note the indices were flattened during init, so this just matches that operation for the field data itself.)  1d mpas fields do not, but the operation won't do anything because they are already flat.
        elif args.interpType == 'e':
            print("  ...Layer{}, Interpolating this layer to MPAS grid using ESMF-weights method...".format(z))
            mpas_grid_input_layers[z,:] = ESMF_interp(InputField[z,:,:])
        else:
            sys.exit('ERROR: Unknown interpolation method specified')
        print('  interpolated MPAS {}, layer {} min/max {} {}: '.format(MPASfieldName, z, mpas_grid_input_layers[z,:].min(), mpas_grid_input_layers[z,:].max()))

    if fieldInfo[MPASfieldName]['scalefactor'] != 1.0:
        mpas_grid_input_layers *= fieldInfo[MPASfieldName]['scalefactor']
        print('  scaled MPAS {} on CISM vertical layers, min/max: {} {}'.format(MPASfieldName, mpas_grid_input_layers.min(), mpas_grid_input_layers.max()))
    if fieldInfo[MPASfieldName]['offset'] != 0.0:
        mpas_grid_input_layers += fieldInfo[MPASfieldName]['offset']
        print('  offset MPAS {} on CISM vertical layers, min/max: {} {}'.format(MPASfieldName, mpas_grid_input_layers.min(), mpas_grid_input_layers.max()))

    # ------------
    # Now interpolate vertically
    print("  Input layer field {} has layers: {}".format(inputFile.variables[InputFieldName].dimensions[1], input_layers))
    if 'nVertLevels' in MPASfile.variables[MPASfieldName].dimensions():
       print("  MPAS layer centers are: {}".format(mpasLayerCenters))
       destVertCoord = mpasLayerCenters
    elif 'nVertInterfaces' in MPASfile.variables[MPASfieldName].dimensions():
       print("  MPAS layer interfaces are: {}".format(mpasLayerInterfaces))
       destVertCoord = mpasLayerInterfaces
    else:
       sys.exit("Unknown vertical dimension for this variable destination file.")


    if input_layers.min() > destVertCoord.min():
        # This fix ensures that interpolation is done when input_layers.min is very slightly greater than destVertCoord.min
        if input_layers.min() - 1.0e-6 < destVertCoord.min():
            print('input_layers.min = {0:.16f}'.format(input_layers.min()))
            print('destVertCoord.min = {0:.16f}'.format(destVertCoord.min()))
            input_layers[0] = input_layers[0] - 1.0e-6
            print('New input_layers.min = {0:.16f}'.format(input_layers.min()))
        else:
            print("WARNING: input_layers.min() > destVertCoord.min()   Values at the first level of input_layers will be used for all MPAS layers in this region!")
    if input_layers.max() < destVertCoord.max():
        # This fix ensures that interpolation is done when input_layers.max is very slightly smaller than destVertCoord.max
        if input_layers.max() + 1.0e-6 > destVertCoord.min():
            print('input_layers.max = {0:.16f}'.format(input_layers.max()))
            print('destVertCoord.max = {0:.16f}'.format(destVertCoord.max()))
            input_layers[inputVerticalDimSize-1] = input_layers[inputVerticalDimSize-1] + 1.0e-6
            print('New input_layers.max = {0:.16f}'.format(input_layers.max()))
            print('input_layers = {}'.format(input_layers))
        else:
            print("WARNING: input_layers.max() < destVertCoord.max()   Values at the last level of input_layers will be used for all MPAS layers in this region!")
    MPASfield = vertical_interp_MPAS_grid(mpas_grid_input_layers, destVertCoord, input_layers)
    print('  MPAS {} on MPAS vertical layers, min/max of all layers:'.format(MPASfieldName, MPASfield.min(), MPASfield.max()))

    del mpas_grid_input_layers

    return MPASfield


#----------------------------

def vertical_interp_MPAS_grid(mpas_grid_input_layers, destVertCoord, input_layers):
    destinationField = np.zeros((nCells, len(destVertCoord)))
    for i in range(nCells):
        destinationField[i,:] = np.interp(destVertCoord, input_layers, mpas_grid_input_layers[:,i])
    return destinationField


#----------------------------
#----------------------------




print("==================")
print('Gathering coordinate information from input and output files.')


# Open the output file, get needed dimensions & variables
try:
    MPASfile = netCDF4.Dataset(args.mpasFile,'r+')
    MPASfile.set_auto_mask(False)
    try:
      nVertLevels = len(MPASfile.dimensions['nVertLevels'])
    except:
      print('Output file is missing the dimension nVertLevels.  Might not be a problem.')
    try:
      nVertInterfaces = len(MPASfile.dimensions['nVertInterfaces'])
    except:
      print('Output file is missing the dimension nVertInterfaces.  Might not be a problem.')

    try:
      # 1d vertical fields - layer centers
      layerThicknessFractions = MPASfile.variables['layerThicknessFractions'][:]
      # build up sigma levels
      mpasLayerCenters = np.zeros( (nVertLevels,) )
      mpasLayerCenters[0] = 0.5 * layerThicknessFractions[0]
      for k in range(nVertLevels)[1:]:  # skip the first level
          mpasLayerCenters[k] = mpasLayerCenters[k-1] + 0.5 * layerThicknessFractions[k-1] + 0.5 * layerThicknessFractions[k]
      print("  Using MPAS layer centers at sigma levels: {}".format(mpasLayerCenters))
    except:
      print('Trouble calculating mpas layer centers. Might not be a problem.')

    try:
      # 1d vertical field - layer interfaces
      layerThicknessFractions = MPASfile.variables['layerThicknessFractions'][:]
      # build up sigma levels
      mpasLayerInterfaces = np.zeros( (nVertInterfaces,) )
      mpasLayerInterfaces[0] = 0.0
      for k in range(1, nVertInterfaces):  # skip the first level
          mpasLayerCenters[k] = mpasLayerCenters[k-1] + layerThicknessFractions[k]
      print("  Using MPAS layer interfaces at sigma levels: {}".format(mpasLayerInterfaces))
    except:
      print('Trouble calculating mpas layer interfaces. Might not be a problem.')


    # '2d' spatial fields on cell centers
    xCell = MPASfile.variables['xCell'][:]
    #print('xCell min/max:', xCell.min(), xCell.max()
    yCell = MPASfile.variables['yCell'][:]
    #print('yCell min/max:', yCell.min(), yCell.max()
    nCells = len(MPASfile.dimensions['nCells'])

except:
    sys.exit('Error: The output grid file specified is either missing or lacking needed dimensions/variables.')
print("==================\n")



# Open the input file, get needed dimensions
inputFile = netCDF4.Dataset(args.inputFile,'r')
inputFile.set_auto_mask(False)

# Figure out if this is CISM or MPAS
if 'x1' in inputFile.variables:
    filetype='cism'
elif 'xCell' in inputFile.variables:
    filetype='mpas'
else:
        sys.exit("ERROR: Unknown file type.  This does not appear to be a CISM file or an MPAS file.")

if filetype=='cism':
    # Get the CISM vertical dimensions if they exist
    try:
      level = len(inputFile.dimensions['level'])
    except:
      print('  Input file is missing the dimension level.  Might not be a problem.')

    try:
      stagwbndlevel = len(inputFile.dimensions['stagwbndlevel'])
    except:
      print('  Input file is missing the dimension stagwbndlevel.  Might not be a problem.')

    # Get CISM location variables if they exist
    try:
      x1 = inputFile.variables['x1'][:]
      dx1 = x1[1] - x1[0]
      #print('x1 min/max/dx:', x1.min(), x1.max(), dx1
      y1 = inputFile.variables['y1'][:]
      dy1 = y1[1] - y1[0]
      #print('y1 min/max/dx:', y1.min(), y1.max(), dy1

      ##x1 = x1 - (x1.max()-x1.min())/2.0  # This was for some shifted CISM grid but should not be used in general.
      ##y1 = y1 - (y1.max()-y1.min())/2.0
    except:
      print('  Input file is missing x1 and/or y1.  Might not be a problem.')

    try:
      x0 = inputFile.variables['x0'][:]
      #print('x0 min/max:', x0.min(), x0.max()
      y0 = inputFile.variables['y0'][:]
      #print('y0 min/max:', y0.min(), y0.max()

      ##x0 = x0 - (x0.max()-x0.min())/2.0
      ##y0 = y0 - (y0.max()-y0.min())/2.0

    except:
      print('  Input file is missing x0 and/or y0.  Might not be a problem.')

    # Check the overlap of the grids
    print('==================')
    print('CISM Input File extents:')
    print('  x1 min, max:    {} {}'.format(x1.min(), x1.max()))
    print('  y1 min, max:    {} {}'.format(y1.min(), y1.max()))
    print('MPAS File extents:')
    print('  xCell min, max: {} {}'.format(xCell.min(), xCell.max()))
    print('  yCell min, max: {} {}'.format(yCell.min(), yCell.max()))
    print('==================')


elif filetype == 'mpas':

    #try:
    #  nVertInterfaces = len(inputFile.dimensions['nVertInterfaces'])
    #except:
    #  print('  Input file is missing the dimension nVertInterfaces.  Might not be a problem.'

    # Get MPAS location variables if they exist
    try:
      inputxCell = inputFile.variables['xCell'][:]
      inputyCell = inputFile.variables['yCell'][:]
    except:
      sys.exit("ERROR: Input file is missing xCell and/or yCell")


    # Check the overlap of the grids
    print('==================')
    print('Input MPAS File extents:')
    print('  xCell min, max:    {} {}'.format(inputxCell.min(), inputxCell.max()))
    print('  yCell min, max:    {} {}'.format(inputyCell.min(), inputyCell.max()))
    print('Output MPAS File extents:')
    print('  xCell min, max: {} {}'.format(xCell.min(), xCell.max()))
    print('  yCell min, max: {} {}'.format(yCell.min(), yCell.max()))
    print('==================')


if filetype=='mpas' and not args.interpType == 'd':
   sys.exit("ERROR: Input files with MPAS format are only supported with the barycentric interpolation method ('d')")

#----------------------------
# Setup Delaunay/barycentric interpolation weights if needed
if args.interpType == 'd':
   mpasXY = np.vstack((xCell[:], yCell[:])).transpose()

   if filetype=='cism':
      [Yi,Xi] = np.meshgrid(x1[:], y1[:])
      cismXY1 = np.zeros([Xi.shape[0]*Xi.shape[1],2])
      cismXY1[:,0] = Yi.flatten()
      cismXY1[:,1] = Xi.flatten()

      print('\nBuilding interpolation weights: CISM x1/y1 -> MPAS')
      start = time.perf_counter()
      vtx1, wts1, outsideIndx1, treex1 = delaunay_interp_weights(cismXY1, mpasXY)
      if len(outsideIndx1) > 0:
         outsideIndx1 = outsideIndx1[0]  # get the list itself
      end = time.perf_counter(); print('done in {}'.format(end-start))

      if 'x0' in inputFile.variables and not args.thicknessOnly:
         # Need to setup separate weights for this grid
         [Yi,Xi] = np.meshgrid(x0[:], y0[:])
         cismXY0 = np.zeros([Xi.shape[0]*Xi.shape[1],2])
         cismXY0[:,0] = Yi.flatten()
         cismXY0[:,1] = Xi.flatten()

         print('Building interpolation weights: CISM x0/y0 -> MPAS')
         start = time.perf_counter()
         vtx0, wts0, outsideIndx0, treex0 = delaunay_interp_weights(cismXY0, mpasXY)
         if len(outsideIndx0) > 0:
            outsideIndx0 = outsideIndx0[0]  # get the list itself
         end = time.perf_counter(); print('done in {}'.format(end-start))

   elif filetype=='mpas':
      inputmpasXY= np.vstack((inputxCell[:], inputyCell[:])).transpose()
      print('Building interpolation weights: MPAS in -> MPAS out')
      start = time.perf_counter()
      vtCell, wtsCell, outsideIndcell, treecell = delaunay_interp_weights(inputmpasXY, mpasXY)
      end = time.perf_counter(); print('done in {}'.format(end-start))

#----------------------------
# Setup NN interpolation weights if needed
if args.interpType == 'n':
   mpasXY = np.vstack((xCell[:], yCell[:])).transpose()

   if filetype=='cism':
      [Yi,Xi] = np.meshgrid(x1[:], y1[:])
      cismXY1 = np.zeros([Xi.shape[0]*Xi.shape[1],2])
      cismXY1[:,0] = Yi.flatten()
      cismXY1[:,1] = Xi.flatten()

      print('\nBuilding interpolation weights: CISM x1/y1 -> MPAS')
      start = time.perf_counter()
      nn_idx_x1 = nn_interp_weights(cismXY1, mpasXY)
      end = time.perf_counter(); print('done in {}'.format(end-start))

      if 'x0' in inputFile.variables and not args.thicknessOnly:
         # Need to setup separate weights for this grid
         [Yi,Xi] = np.meshgrid(x0[:], y0[:])
         cismXY0 = np.zeros([Xi.shape[0]*Xi.shape[1],2])
         cismXY0[:,0] = Yi.flatten()
         cismXY0[:,1] = Xi.flatten()

         print('Building interpolation weights: CISM x0/y0 -> MPAS')
         start = time.perf_counter()
         nn_idx_x0 = nn_interp_weights(cismXY0, mpasXY)
         end = time.perf_counter(); print('done in {}'.format(end-start))

   elif filetype=='mpas':
      inputmpasXY= np.vstack((inputxCell[:], inputyCell[:])).transpose()
      print('Building interpolation weights: MPAS in -> MPAS out')
      start = time.perf_counter()
      nn_idx_cell = nn_interp_weights(inputmpasXY, mpasXY)
      end = time.perf_counter(); print('done in {}'.format(end-start))


#----------------------------
# Map Input-Output field names - add new fields here as needed

fieldInfo = OrderedDict()
if filetype=='cism':

   fieldInfo['thickness'] =     {'InputName':'thk',  'scalefactor':1.0, 'offset':0.0, 'gridType':'x1', 'vertDim':False}
   if not args.thicknessOnly:
     fieldInfo['bedTopography'] = {'InputName':'topg', 'scalefactor':1.0, 'offset':0.0, 'gridType':'x1', 'vertDim':False}
     fieldInfo['sfcMassBal'] =    {'InputName':'smb', 'scalefactor':910.0/(3600.0*24.0*365.0)/1000.0, 'offset':0.0, 'gridType':'x1', 'vertDim':False}  # Assuming default CISM density and mm/yr w.e. units for smb
     fieldInfo['sfcMassBalUncertainty'] =    {'InputName':'smb_std', 'scalefactor':910.0/(3600.0*24.0*365.0)/1000.0, 'offset':0.0, 'gridType':'x1', 'vertDim':False}  # Assuming default CISM density and mm/yr w.e. units for smb
     fieldInfo['floatingBasalMassBal'] =    {'InputName':'subm', 'scalefactor':910.0/(3600.0*24.0*365.0), 'offset':0.0, 'gridType':'x1', 'vertDim':False}  # Assuming default CISM density
     #fieldInfo['temperature'] =   {'InputName':'temp', 'scalefactor':1.0, 'offset':273.15, 'gridType':'x1', 'vertDim':True}
     fieldInfo['temperature'] =   {'InputName':'tempstag', 'scalefactor':1.0, 'offset':273.15, 'gridType':'x1', 'vertDim':True}  # pick one or the other
     fieldInfo['basalHeatFlux'] = {'InputName':'bheatflx', 'scalefactor':1.0, 'offset':0.0, 'gridType':'x1', 'vertDim':False}
     fieldInfo['surfaceAirTemperature'] = {'InputName':'artm', 'scalefactor':1.0, 'offset':273.15, 'gridType':'x1', 'vertDim':False}
     fieldInfo['beta'] =          {'InputName':'beta', 'scalefactor':1.0, 'offset':0.0, 'gridType':'x0', 'vertDim':False} # needs different mapping file...
     #fieldInfo['observedSpeed'] = {'InputName':'balvel', 'scalefactor':1.0/(365.0*24.0*3600.0), 'offset':0.0, 'gridType':'x0', 'vertDim':False} # needs different mapping file...
     # fields for observed surface speed and associated error, observed thickness change
     fieldInfo['observedSurfaceVelocityX'] = {'InputName':'vx', 'scalefactor':1.0/(365.0*24.0*3600.0), 'offset':0.0, 'gridType':'x1', 'vertDim':False}
     fieldInfo['observedSurfaceVelocityY'] = {'InputName':'vy', 'scalefactor':1.0/(365.0*24.0*3600.0), 'offset':0.0, 'gridType':'x1', 'vertDim':False}
     fieldInfo['observedSurfaceVelocityUncertainty'] = {'InputName':'vErr', 'scalefactor':1.0/(365.0*24.0*3600.0), 'offset':0.0, 'gridType':'x1', 'vertDim':False}
     fieldInfo['observedThicknessTendency'] = {'InputName':'dHdt', 'scalefactor':1.0/(365.0*24.0*3600.0), 'offset':0.0, 'gridType':'x1', 'vertDim':False}
     fieldInfo['observedThicknessTendencyUncertainty'] = {'InputName':'dHdtErr', 'scalefactor':1.0/(365.0*24.0*3600.0), 'offset':0.0, 'gridType':'x1', 'vertDim':False}
     fieldInfo['thicknessUncertainty'] = {'InputName':'topgerr', 'scalefactor':1.0, 'offset':0.0, 'gridType':'x1', 'vertDim':False}

     fieldInfo['ismip6shelfMelt_basin'] = {'InputName':'ismip6shelfMelt_basin', 'scalefactor':1.0, 'offset':0.0, 'gridType':'x1', 'vertDim':False}
     fieldInfo['ismip6shelfMelt_deltaT'] = {'InputName':'ismip6shelfMelt_deltaT', 'scalefactor':1.0, 'offset':0.0, 'gridType':'x1', 'vertDim':False}

elif filetype=='mpas':

   fieldInfo['thickness'] =     {'InputName':'thickness',  'scalefactor':1.0, 'offset':0.0, 'gridType':'cell', 'vertDim':False}
   if not args.thicknessOnly:
     fieldInfo['bedTopography'] = {'InputName':'bedTopography', 'scalefactor':1.0, 'offset':0.0, 'gridType':'cell', 'vertDim':False}
     fieldInfo['sfcMassBal'] =    {'InputName':'sfcMassBal', 'scalefactor':1.0, 'offset':0.0, 'gridType':'cell', 'vertDim':False}
     fieldInfo['floatingBasalMassBal'] =    {'InputName':'floatingBasalMassBal', 'scalefactor':1.0, 'offset':0.0, 'gridType':'cell', 'vertDim':False}
     fieldInfo['temperature'] =   {'InputName':'temperature', 'scalefactor':1.0, 'offset':0.0, 'gridType':'cell', 'vertDim':True}
     fieldInfo['basalHeatFlux'] =    {'InputName':'basalHeatFlux', 'scalefactor':1.0, 'offset':0.0, 'gridType':'cell', 'vertDim':False}
     fieldInfo['surfaceAirTemperature'] =    {'InputName':'surfaceAirTemperature', 'scalefactor':1.0, 'offset':0.0, 'gridType':'cell', 'vertDim':False}
     fieldInfo['beta'] = {'InputName':'beta', 'scalefactor':1.0, 'offset':0.0, 'gridType':'cell', 'vertDim':False}
     # obs fields
     fieldInfo['observedSurfaceVelocityX'] = {'InputName':'observedSurfaceVelocityX', 'scalefactor':1.0, 'offset':0.0, 'gridType':'cell', 'vertDim':False}
     fieldInfo['observedSurfaceVelocityY'] = {'InputName':'observedSurfaceVelocityY', 'scalefactor':1.0, 'offset':0.0, 'gridType':'cell', 'vertDim':False}
     fieldInfo['observedSurfaceVelocityUncertainty'] = {'InputName':'observedSurfaceVelocityUncertainty', 'scalefactor':1.0, 'offset':0.0, 'gridType':'cell', 'vertDim':False}
     fieldInfo['observedThicknessTendency'] = {'InputName':'observedThicknessTendency', 'scalefactor':1.0, 'offset':0.0, 'gridType':'cell', 'vertDim':False}
     fieldInfo['observedThicknessTendencyUncertainty'] = {'InputName':'observedThicknessTendencyUncertainty', 'scalefactor':1.0, 'offset':0.0, 'gridType':'cell', 'vertDim':False}
     fieldInfo['thicknessUncertainty'] = {'InputName':'thicknessUncertainty', 'scalefactor':1.0, 'offset':0.0, 'gridType':'cell', 'vertDim':False}
     fieldInfo['basalFrictionFlux'] =    {'InputName':'basalFrictionFlux', 'scalefactor':1.0, 'offset':0.0, 'gridType':'cell', 'vertDim':False}

# Used by Trevor
#     fieldInfo['sfcMassBalUncertainty'] = {'InputName':'smb_std_vector', 'scalefactor':910.0/(3600.0*24.0*365.0)/1000.0, 'offset':0.0, 'gridType':'cell', 'vertDim':False}
#     fieldInfo['ismip6Runoff'] = {'InputName':'runoff_vector', 'scalefactor':1.0, 'offset':0.0, 'gridType':'cell', 'vertDim':False}
#     fieldInfo['ismip6_2dThermalForcing'] = {'InputName':'thermal_forcing_vector', 'scalefactor':1.0, 'offset':0.0, 'gridType':'cell', 'vertDim':False}
#     fieldInfo['ismip6aST'] = {'InputName':'aST_vector', 'scalefactor':1.0, 'offset':0.0, 'gridType':'cell', 'vertDim':False}
#     fieldInfo['ismip6aSMB'] = {'InputName':'aSMB_vector', 'scalefactor':1.0, 'offset':0.0, 'gridType':'cell', 'vertDim':False}
#     fieldInfo['ismip6refST'] = {'InputName':'ST_vector', 'scalefactor':1.0, 'offset':0.0, 'gridType':'cell', 'vertDim':False}
#     fieldInfo['externalWaterInput'] = {'InputName':'externalWaterInput_vector', 'scalefactor':1.0/(3600.0*24.0*365.0), 'offset':0.0, 'gridType':'cell', 'vertDim':False}


#----------------------------


#----------------------------
# try each field.  If it exists in the input file, it will be copied.  If not, it will be skipped.
for MPASfieldName in fieldInfo:
    print('\n## {} ##'.format(MPASfieldName))

    if not MPASfieldName in MPASfile.variables:
       print("  Warning: Field '{}' is not in the destination file.  Skipping.".format(MPASfieldName))
       continue  # skip the rest of this iteration of the for loop over variables

    if not fieldInfo[MPASfieldName]['InputName'] in inputFile.variables:
       print("  Warning: Field '{}' is not in the source file.  Skipping.".format(fieldInfo[MPASfieldName]['InputName']))
       continue  # skip the rest of this iteration of the for loop over variables

    for timelev in range(args.timestart, args.timeend+1):
       # Note; the interpolate functions called below access timelev as a global variable
       timelevout = timelev # assuming the time level of the output file should match that of the input file
       print("  -- Interpolating time level {}".format(timelev))
       start = time.perf_counter()
       if fieldInfo[MPASfieldName]['vertDim']:
         MPASfield = interpolate_field_with_layers(MPASfieldName)
       else:
         MPASfield = interpolate_field(MPASfieldName)
       end = time.perf_counter(); print('  interpolation done in {}'.format(end-start))

       # Don't allow negative thickness.
       if MPASfieldName == 'thickness' and MPASfield.min() < 0.0:
           MPASfield[MPASfield < 0.0] = 0.0
           print('  removed negative thickness, new min/max: {} {}'.format(MPASfield.min(), MPASfield.max()))

       # Now insert the MPAS field into the file.
       if 'Time' in MPASfile.variables[MPASfieldName].dimensions:
           MPASfile.variables[MPASfieldName][timelevout,:] = MPASfield  # Time will always be leftmost index
       else:
           MPASfile.variables[MPASfieldName][:] = MPASfield

       MPASfile.sync()  # update the file now in case we get an error later

if args.timeend > args.timestart:
   print("\n\nMultiple time levels have been copied, but xtime has not.  Be sure to manually copy or assign xtime values in the destination file if needed.")

# Update history attribute of netCDF file
thiscommand = datetime.now().strftime("%a %b %d %H:%M:%S %Y") + ": " + " ".join(sys.argv[:])
if hasattr(MPASfile, 'history'):
   newhist = '\n'.join([thiscommand, getattr(MPASfile, 'history')])
else:
   newhist = thiscommand
setattr(MPASfile, 'history', newhist )

inputFile.close()
MPASfile.close()

print('\nInterpolation completed.')
