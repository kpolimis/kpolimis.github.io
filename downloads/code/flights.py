import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from mpl_toolkits.basemap import Basemap

fig = plt.figure(figsize=(18,12))

# Plotting across the international dateline is tough. One option is to break up flights
# by hemisphere. Otherwise, you'd need to plot using a different projection like 'robin'
# and potentially center on the Int'l Dateline (lon_0=-180)
# flights = flights[(flights.startlon < 0) & (flights.endlon < 0)]# Western Hemisphere Flights
# flights = flights[(flights.startlon > 0) & (flights.endlon > 0)] # Eastern Hemisphere Flights

xbuf = 0.2
ybuf = 0.35
minlat = np.min([flights.endlat.min(), flights.startlat.min()])
minlon = np.min([flights.endlon.min(), flights.startlon.min()])
maxlat = np.max([flights.endlat.max(), flights.startlat.max()])
maxlon = np.max([flights.endlon.max(), flights.startlon.max()])
width = maxlon - minlon
height = maxlat - minlat

m = Basemap(llcrnrlon=minlon - width* xbuf,
            llcrnrlat=minlat - height*ybuf,
            urcrnrlon=maxlon + width* xbuf,
            urcrnrlat=maxlat + height*ybuf,
            projection='merc',
            resolution='l',
            lat_0=minlat + height/2,
            lon_0=minlon + width/2,)


m.drawmapboundary(fill_color='#EBF4FA')
m.drawcoastlines()
m.drawstates()
m.drawcountries()
m.fillcontinents()

for idx, f in flights.iterrows():
    m.drawgreatcircle(f.startlon, f.startlat, f.endlon, f.endlat, linewidth=3, alpha=0.4, color='b' )
    m.plot(*m(f.startlon, f.startlat), color='g', alpha=0.8, marker='o')
    m.plot(*m(f.endlon, f.endlat), color='r', alpha=0.5, marker='o' )

fig.text(0.125, 0.18, "Data collected from 2012-2014 on Android 4.2-4.4\nPlotted using Python, Basemap",
        ha='left', color='#555555', style='italic')
fig.text(0.125, 0.15, "kivanpolimis.com", color='#555555', fontsize=16, ha='left')
plt.savefig('flights.png', dpi=150, frameon=False, transparent=False, bbox_inches='tight', pad_inches=0.2)
