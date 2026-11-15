"""Unfilled D8 terrain screening. No flood depth, rainfall routing or drain model.

Only strictly descending neighbors are routed. Flats and pits are unresolved,
not filled or assumed to drain. Accumulation is contributing raster area within
this finite window, not runoff volume or a verified hydrologic catchment.
"""
import math
import numpy as np


def d8(elevation, resolution=1.0):
    z = np.asarray(elevation, dtype=float)
    if z.ndim != 2 or min(z.shape) < 3 or not math.isfinite(resolution) or resolution <= 0:
        raise ValueError("A two-dimensional terrain grid and positive cell size are required.")
    h, w = z.shape
    valid = np.isfinite(z)
    target = np.full(z.shape, -1, dtype=np.int64)
    slope = np.zeros(z.shape)
    rows, cols = np.indices(z.shape)
    # Deterministic tie order; no artificial gradient imposed on flats.
    for dy, dx in [(-1,0),(0,1),(1,0),(0,-1),(-1,1),(1,1),(1,-1),(-1,-1)]:
        yy, xx = rows + dy, cols + dx
        inside = (yy >= 0) & (yy < h) & (xx >= 0) & (xx < w)
        yy, xx = np.clip(yy,0,h-1), np.clip(xx,0,w-1)
        drop = (z - z[yy,xx]) / (resolution * math.hypot(dy,dx))
        better = inside & valid & np.isfinite(z[yy,xx]) & (drop > slope) & (drop > 1e-6)
        slope[better] = drop[better]
        target[better] = (yy*w + xx)[better]
    area = np.where(valid, resolution**2, 0).ravel()
    flat_target = target.ravel()
    edge = np.zeros(z.shape, dtype=bool)
    edge[0,:] = edge[-1,:] = edge[:,0] = edge[:,-1] = True
    # Also flag contributions next to a NoData boundary as incomplete.
    for dy, dx in [(-1,0),(0,1),(1,0),(0,-1),(-1,1),(1,1),(1,-1),(-1,-1)]:
        edge |= np.roll(~valid, (dy,dx), axis=(0,1))
    edge = edge.ravel()
    for i in np.argsort(np.where(valid,z,-np.inf), axis=None)[::-1]:
        j = flat_target[i]
        if j >= 0:
            area[j] += area[i]
            edge[j] |= edge[i]
    return target, area.reshape(z.shape), edge.reshape(z.shape), slope


def path_from(index, target, max_cells=2000):
    path = [int(index)]
    flat = target.ravel()
    while flat[path[-1]] >= 0 and len(path) < max_cells:
        next_index = int(flat[path[-1]])
        if next_index in path:
            raise ValueError("Terrain routing contains a cycle.")
        path.append(next_index)
    return path
