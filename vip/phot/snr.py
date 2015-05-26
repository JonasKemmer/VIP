#! /usr/bin/env python

"""
Module with SNR calculation functions.
"""

from __future__ import division

__author__ = 'C. Gomez @ ULg, B. Pairet @ UCL'
__all__ = ['snr_student',
           'snr_peakstddev',
           'snrmap']

import numpy as np
import itertools as itt
import photutils
from skimage.draw import circle
from matplotlib import pyplot as plt
from multiprocessing import Pool, cpu_count
from ..conf import eval_func_tuple, timeInit, timing
from ..var import get_annulus, frame_center, dist


def snrmap(array, fwhm, plot=False, mode='sss', source_mask=None, nproc=None):
    """Parallel implementation of the SNR map generation function. Applies the 
    SNR function (small samples penalty) at each pixel.
    
    Parameters
    ----------
    array : array_like
        Input frame.
    fwhm : float
        Size in pixels of the FWHM.
    plot : {False, True}, bool optional
        If True plots the SNR map. 
    mode : {'ss', 'annulus'}, string optional
        'sss' uses the approach with the small sample statistics penalty and
        'annulus' uses the peak(aperture)/std(annulus) version.
    source_mask : array_like, optional
        If exists, it takes into account existing sources. The mask is a ones
        2d array, with the same size as the input frame. The centers of the 
        known sources have a zero value.
    nproc : int
        Number of processes for parallel computing.
    
    Returns
    -------
    snrmap : array_like
        Frame with the same size as the input frame with each pixel.
        
    """
    start_time = timeInit()
    if not array.ndim==2:
        raise TypeError('Input array is not a 2d array or image.')
    if plot:
        plt.close('snr')
        
    sizey, sizex = array.shape
    snrmap = np.zeros_like(array)
    width = min(sizey,sizex)/2 - 1.5*fwhm
    mask = get_annulus(array, fwhm, width)
    mask = np.ma.make_mask(mask)
    yy, xx = np.where(mask)

    if not nproc:  
        nproc = int((cpu_count()/2))  # Hyper-threading duplicates the number of cores
    
    if mode == 'sss':
        func = snr_student
    elif mode == 'annulus':
        func = snr_peakstddev
    else:
        raise TypeError('\nMode not recognized.')
    
    if source_mask is None:
        pool = Pool(processes=nproc)                                        
        res = pool.map(eval_func_tuple, itt.izip(itt.repeat(func),              
                                                 itt.repeat(array),
                                                 yy, xx, itt.repeat(fwhm),
                                                 itt.repeat(False),
                                                 itt.repeat(False),
                                                 itt.repeat(True)))       
        res = np.array(res)
        pool.close()
        yy = res[:,0]
        xx = res[:,1]
        snr = res[:,2]
        snrmap[yy.astype('int'), xx.astype('int')] = snr
    else:
        if not array.shape == source_mask.shape:
            raise ValueError('Source mask has wrong size.')
        if source_mask[source_mask == 0].shape[0] == 0:
            raise TypeError('Input source mask is empty. It must contain at least one source.')
        if source_mask[source_mask == 0].shape[0] > 20:
            raise TypeError('Input source mask is too crowded. Check its validity.')
        
        soury, sourx = np.where(source_mask == 0)
        sources = []
        ciry = []
        cirx = []
        anny = []
        annx = []
        array_sources = array.copy()
        centery, centerx = frame_center(array)
        for (y,x) in zip(soury,sourx):
            radd = dist(centery, centerx, y, x)
            if int(np.floor(radd)) < centery - np.ceil(fwhm):
                sources.append((y,x))
        
        for source in sources:
            y, x = source        
            radd = dist(centery, centerx, y, x)
            tempay, tempax = get_annulus(array, int(np.floor(radd-fwhm)), 
                                    int(np.ceil(2*fwhm)), output_indices=True)
            tempcy, tempcx = circle(y, x, int(np.ceil(1.5*fwhm)))
            tempcy = list(tempcy)
            tempcx = list(tempcx)
            tempay = list(tempay)
            tempax = list(tempax)
            array_sources[tempcy, tempcx] =  np.median(array[tempay, tempax])
            ciry += tempcy
            cirx += tempcx
            anny += tempay
            annx += tempax
        coor_ann = []
        for (y,x) in zip(anny, annx):
            if (y,x) not in zip(ciry, cirx):
                coor_ann.append((y,x))
        yy_ann = list(np.array(coor_ann)[:,0])
        xx_ann = list(np.array(coor_ann)[:,1])
        coor_rest = []
        for (y,x) in zip(yy, xx):
            if (y,x) not in zip(yy_ann, xx_ann):
                coor_rest.append((y,x))
        yy_rest = list(np.array(coor_rest)[:,0])
        xx_rest = list(np.array(coor_rest)[:,1])
        
        pool1 = Pool(processes=nproc)
        res = pool1.map(eval_func_tuple, itt.izip(itt.repeat(func), 
                                                  itt.repeat(array),
                                                  yy_rest, xx_rest, 
                                                  itt.repeat(fwhm),
                                                  itt.repeat(False),
                                                  itt.repeat(False),
                                                  itt.repeat(True)))       
        res = np.array(res)
        pool1.close()
        yy = res[:,0]
        xx = res[:,1]
        snr = res[:,2]
        snrmap[yy.astype('int'), xx.astype('int')] = snr
        
        pool2 = Pool(processes=nproc)
        res = pool2.map(eval_func_tuple, itt.izip(itt.repeat(func), 
                                                  itt.repeat(array_sources),
                                                  yy_ann, xx_ann, 
                                                  itt.repeat(fwhm),
                                                  itt.repeat(False),
                                                  itt.repeat(False),
                                                  itt.repeat(True)))       
        res = np.array(res)
        pool2.close()
        yy = res[:,0]
        xx = res[:,1]
        snr = res[:,2]
        snrmap[yy.astype('int'), xx.astype('int')] = snr
    
    if plot:
        plt.figure('snr')
        plt.imshow(snrmap, origin='lower', interpolation='nearest')
        plt.colorbar()
        plt.show()
        
    print "SNR map created using {:} processes.".format(nproc)
    timing(start_time)
    return snrmap
    
    
def snr_student(array, sourcey, sourcex, fwhm, plot=False, verbose=True, 
                out_coor=False):
    """Calculates the SNR (signal to noise ratio) of a single planet in a 
    post-processed (e.g. by LOCI or PCA) frame. Uses the approach described in 
    Mawet et al. 2014 on small sample statistics, where a student t-test (eq. 9)
    can be used to determine SNR (and contrast) in high contrast imaging. 
    
    Parameters
    ----------
    array : array_like, 2d
        Post-processed frame where we want to measure SNR.
    sourcey : int
        Y coordinate of the planet or test speckle.
    sourcex : int
        X coordinate of the planet or test speckle.
    fwhm : float
        Size in pixels of the FWHM.
    plot : {False, True}, bool optional
        Plots the frame and the apertures considered for clarity. 
    verbose: {True, False}, bool optional
        Chooses whether to print some output or not.
    out_coor: {False, True}, bool optional
        If True returns back the snr value and the y, x input coordinates.
    
    Returns
    -------
    snr : float
        Value of the SNR for the given planet or test speckle.
    
    """
    if not array.ndim==2:
        raise TypeError('Input array is not a frame or 2d array')
    
    centery, centerx = frame_center(array)
    rad = dist(centery,centerx,sourcey,sourcex)
 
    angle = np.arcsin(fwhm/2/rad)*2
    number_circles = int(np.floor(2*np.pi/angle))
    yy = np.zeros((number_circles))
    xx = np.zeros((number_circles))
    cosangle = np.cos(angle)
    sinangle = np.sin(angle)
    xx[0] = sourcex - centerx
    yy[0] = sourcey - centery
    for i in range(number_circles-1):
        xx[i+1] = cosangle*xx[i] + sinangle*yy[i] 
        yy[i+1] = cosangle*yy[i] - sinangle*xx[i] 
     
    xx[:] += centerx
    yy[:] += centery 
        
    rad = fwhm/2.
    aperture = photutils.CircularAperture((xx, yy), r=rad)                      # Coordinates (X,Y)
    fluxes = photutils.aperture_photometry(array, aperture)    
    fluxes = np.array(fluxes['aperture_sum'])
    f_source_ap = photutils.CircularAperture((sourcex, sourcey), rad)
    f_source = photutils.aperture_photometry(array, f_source_ap)
    f_source = f_source['aperture_sum'][0]
    fluxes = fluxes[1:]
    n2 = fluxes.shape[0]
    snr = (f_source - fluxes.mean())/(fluxes.std()*np.sqrt((n2+1)/n2))
        
    if verbose:
        msg1 = 'SNR = {:}' 
        msg2 = 'Flux = {:.3f}, Mean Flux BKG aper = {:.3f}'
        msg3 = 'Stddev BKG aper = {:.3f}'
        print msg1.format(snr)
        print msg2.format(f_source, fluxes.mean())
        print msg3.format(fluxes.std())
    
    if plot:
        fig, ax = plt.subplots(figsize=(6,6))
        im = ax.imshow(array, origin='lower', interpolation='nearest')
        fig.colorbar(im)
        for i in range(xx.shape[0]):
            aper = plt.Circle((xx[i], yy[i]), radius=fwhm/2., color='r', 
                              fill=False)                                       # Coordinates (X,Y)
            ax.add_patch(aper)
            cent = plt.Circle((xx[i], yy[i]), radius=0.5, color='r', fill=True) # Coordinates (X,Y)
            ax.add_patch(cent)
        #plt.show(block=False)
        plt.show()
    
    if out_coor:
        return sourcey, sourcex, snr
    else:
        return snr
    

def snr_peakstddev(array, sourcey, sourcex, fwhm, plot=False, verbose=True, 
                   out_coor=False):
    """Calculates the SNR (signal to noise ratio) of a single planet in a 
    post-processed (e.g. by LOCI or PCA) frame. The signal is taken as the 
    peak value in the planet (test speckle) aperture, and the noise as the 
    standard deviation of the pixels in an annulus at the same radial distance 
    from the center of the frame. The recommended value of the diameter of the
    signal aperture and the annulus width is 1 FWHM ~ 1 lambda/D.
    
    Parameters
    ----------
    array : array_like, 2d
        Post-processed frame where we want to measure SNR.
    sourcey : int
        Y coordinate of the planet or test speckle.
    sourcex : int
        X coordinate of the planet or test speckle.
    fwhm : float
        Size in pixels of the FWHM.
    plot : {False, True}, optional
        Plots the frame and the apertures considered for clarity. 
    verbose: {True, False}
        Chooses whether to print some intermediate results or not.
    out_coor: {False, True}, bool optional
        If True returns back the snr value and the y, x input coordinates.    
        
    Returns
    -------
    snr : float
        Value of the SNR for the given planet or test speckle.
    
    """
    centery, centerx = frame_center(array)
    rad = dist(centery,centerx,sourcey,sourcex)
    
    aperture = photutils.CircularAperture((sourcex, sourcey), fwhm/2.)
    flux = photutils.aperture_photometry(array, aperture)
    flux = np.array(flux['aperture_sum'])
    
    inner_rad = np.round(rad)-(fwhm/2.)
    an_coor = get_annulus(array, inner_rad, fwhm, output_indices=True)

    ap_coor = circle(sourcey, sourcex, int(np.ceil(fwhm/2.)))
    px_in_ap = (fwhm/2.)**2*np.pi
    array2 = array.copy()
    array2[ap_coor] = array[an_coor].mean()   # we 'mask' the flux aperture
    stddev = array2[an_coor].std()
    peak = array[ap_coor].max()
    mean = flux / px_in_ap
    snr = peak / stddev
    if verbose:
        msg = "SNR = {:.3f}, Peak px = {:.3f}, Mean = {:.3f}, Noise = {:.3f}"
        print msg.format(snr, peak, mean[0], stddev)
    
    if plot:
        fig, ax = plt.subplots(figsize=(6,6))
        im = ax.imshow(array, origin='lower', interpolation='nearest')
        fig.colorbar(im)

        circ = plt.Circle((centerx, centery), radius=inner_rad, color='r', 
                          fill=False) 
        ax.add_patch(circ)
        circ2 = plt.Circle((centerx, centery), radius=inner_rad+fwhm, color='r', 
                           fill=False) 
        ax.add_patch(circ2)
        aper = plt.Circle((sourcex, sourcey), radius=fwhm/2., color='r', 
                          fill=False)                                           # Coordinates (X,Y)
        ax.add_patch(aper)
        #plt.show(block=False)
        plt.show()
    
    if out_coor:
        return sourcey, sourcex, snr
    else:
        return snr



