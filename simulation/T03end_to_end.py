from __future__ import absolute_import, division, print_function
import numpy as np
from radiotools import helper as hp
from NuRadioMC.EvtGen import readEventList
from NuRadioMC.SignalGen.RalstonBuniy.create_askaryan import get_time_trace, get_frequency_spectrum
from NuRadioMC.utilities import units
from NuRadioMC.SignalProp import analyticraytraycing as ray
from NuRadioMC.utilities import medium
from NuRadioMC.EvtGen.weight import get_weight
from matplotlib import pyplot as plt
import argparse
import json
import time
import os
import logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("sim")

# define time and frequency resolution of simulation
dt = 1 * units.ns
n_samples = 256
ff = np.fft.rfftfreq(n_samples, dt)

PLOT_FOLDER = 'plots'
if not os.path.isdir(PLOT_FOLDER):
    PLOT_FOLDER = './'

VERSION = 0.1

parser = argparse.ArgumentParser(description='Parse ARA event list.')
parser.add_argument('inputfilename', type=str,
                    help='path to NuRadioMC input event list')
parser.add_argument('observerlist', type=str,
                    help='path to file containing the detector positions')
# parser.add_argument('outputfilename', type=str,
#                     help='name of output file storing the electric field traces at detector positions')
args = parser.parse_args()

# read in detector positions
with open(args.observerlist) as fobs:
    station_list = json.load(fobs)

eventlist = readEventList.read_eventlist(args.inputfilename)
triggered = np.zeros((len(eventlist), len(station_list)), dtype=np.bool)
weights = np.zeros(len(eventlist))
n_events = 1000

t_start = time.time()
for iE, event in enumerate(eventlist[:n_events]):
    event_id, flavor, energy, ccnc, x, y, z, zenith, azimuth, inelasticity = event

    shower_axis = hp.spherical_to_cartesian(zenith, azimuth)
    x1 = np.array([x, y, z])

    # calculate correct chereknov angle for ice density at vertex position
    ice = medium.southpole_simple()
    n = ice.get_index_of_refraction(x1)
    rho = np.arccos(1. / n)

    # first step: peorform raytracing to see if solution exists
    for iStation, station in enumerate(station_list):
        x2 = np.array(station['position'], dtype=np.float)
        r = ray.ray_tracing(x1, x2, ice)
        if(not r.has_solution()):
            logger.debug("event {} and station {} does not have any ray tracing solution".format(event_id, station['name']))
            continue
        dRhos = []
        viewing_angles = []
        for iS in range(r.get_number_of_solutions()):  # loop through all ray tracing solution
            launch_vector = r.get_launch_vector(iS)
            viewing_angle = hp.get_angle(shower_axis, launch_vector)
            viewing_angles.append(viewing_angle)
            dRho = (viewing_angle - rho)
            logger.debug('solution {}: viewing angle {:.1f} = dRho = {:.1f}'.format(iS, viewing_angle / units.deg, (viewing_angle - rho) / units.deg))
            dRhos.append(dRho)
        # discard event if dRho (angle off cherenkov cone) is too large
        if(np.abs(min(dRhos) > 15 * units.deg)):
            logger.debug('dRho too large, event unlikely to be observed, skipping event')
            continue

        n = r.get_number_of_solutions()
        Rs = np.zeros(n)
        Ts = np.zeros(n)
        tts = np.zeros((n, n_samples))
        eRs = np.zeros((n, n_samples))
        eThetas = np.zeros((n, n_samples))
        ePhis = np.zeros((n, n_samples))
        for iS in range(n):  # loop through all ray tracing solution
            R = r.get_path_length(iS)  # calculate path length
            T = r.get_travel_time(iS)  # calculate travel time
            Ts[iS] = T
#             logger.info("R = {:.1f} m, t = {:.1f}ns".format(R / units.m, T / units.ns))
#             eR, eTheta, ePhi = get_frequency_spectrum(energy, viewing_angles[iS], ff, 0, n, R)

            # get neutrino pulse from Askaryan module
            fem = 0  # electrogmatnetic fraction
            fhad = 0  # hadroninc fraction
            if(ccnc == 'nc'):
                fhad = inelasticity
            else:
                if(np.abs(flavor) == 12):
                    fem = (1 - inelasticity)
                    fhad = inelasticity
                elif(np.abs(flavor) == 14):
                    fhad = inelasticity
                elif(np.abs(flavor) == 16):
                    fhad = inelasticity
            tt, traceR, traceTheta, tracePhi = get_time_trace(energy * fhad, viewing_angles[iS], ff, 0, n, R)
            if(fem > 0):
                pass  # TODO: treat EM showers here
                tt2, traceR2, traceTheta2, tracePhi2 = get_time_trace(energy * fem, viewing_angles[iS], ff, 1, n, R)
                traceR += traceR2
                traceTheta += traceTheta2
                tracePhi += tracePhi2

            eRs[iS] = traceR
            eThetas[iS] = traceTheta
            ePhis[iS] = tracePhi

        if(np.max(np.abs(eThetas)) < 45 * units.micro * units.V / units.m):
            logger.debug("event below trigger threshold")
            continue

        triggered[iE, iS] = True
        if 0:
            fig, ax = plt.subplots(1, 1)
            for iS in range(n):
                ls = ['-', '--']
                ax.plot(tt, eRs[iS] / units.micro / units.V * units.m, ls[iS])
                ax.plot(tt, eThetas[iS] / units.micro / units.V * units.m, ls[iS])
    #         ax2.plot(ff / units.MHz, np.abs(eR))
    #         ax2.plot(ff / units.MHz, np.abs(eTheta))
    #         ax2.plot(ff / units.MHz, np.abs(ePhi))
            plt.show()

    # calculate weight
    weights[iE] = get_weight(zenith, energy, mode='simple')

t_total = time.time() - t_start
logger.warning("{:d} events processed in {:.0f} seconds = {:.2f}ms/event".format(n_events, t_total, 1.e3 * t_total / n_events))

# calculate effective
density_ice = 0.9167 * units.g / units.cm ** 3
density_water = 997 * units.kg / units.m ** 3

n_triggered = np.sum(weights[triggered[..., 1]])
print('fraction of triggered events = {:.0f}/{:.0f} = {:.3f}'.format(n_triggered, n_events, n_triggered / n_events))

dX = 10 * units.km
dY = 10 * units.km
dZ = 3 * units.km
V = dX * dY * dZ
Veff = V * density_ice / density_water * 4 * np.pi * np.sum(weights[triggered[..., 1]]) / n_events

print("Veff = {:.2f} km^3 sr".format(Veff / units.km**3))
#     a = 1 / 0
