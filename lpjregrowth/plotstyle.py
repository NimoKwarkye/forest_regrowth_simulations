"""Consistent colormap sampling for experiment and PFT comparison figures."""
import json
from matplotlib import colormaps
from matplotlib.colors import to_hex
from .instructions import ConfigError


def experiment_palette(experiments, cmap_name='jet'):
    try:
        cmap = colormaps[cmap_name]
    except KeyError as exc:
        raise ConfigError(f'Unknown plot_colormap: {cmap_name}') from exc
    ids = [e['id'] for e in experiments]
    # Compare every scientific setting, excluding identifiers.
    keys = set().union(*(set(e) for e in experiments)) - {'id'}
    varying = [k for k in keys if len({json.dumps(e.get(k),sort_keys=True) for e in experiments}) > 1]
    values = None
    parameter = None
    if varying == ['twig_removal']:
        values = [float(e['twig_removal']) for e in experiments]
        parameter = 'twig_removal'
    elif varying == ['densities']:
        densities = [e['densities'] for e in experiments]
        if len({len(d) for d in densities}) == 1:
            indices = [i for i in range(len(densities[0])) if len({d[i] for d in densities}) > 1]
            if len(indices) == 1:
                values = [float(d[indices[0]]) for d in densities]
                parameter = f'densities[{indices[0]}]'
    if values is not None:
        lo, hi = min(values), max(values)
        positions = [(v-lo)/(hi-lo) for v in values]
    else:
        positions = [i/(len(ids)-1) if len(ids)>1 else .5 for i in range(len(ids))]
    colors = {eid:to_hex(cmap(float(t))) for eid,t in zip(ids,positions)}
    details = dict(colormap=cmap_name, mode='numeric' if values is not None else 'categorical',
                   parameter=parameter, colors=colors, positions=dict(zip(ids,positions)),
                   values=dict(zip(ids,values)) if values is not None else None)
    return colors, details


def component_palette(components, cmap_name='jet'):
    names = sorted(set(components))
    cmap = colormaps[cmap_name]
    return {name:to_hex(cmap(float(i/(len(names)-1) if len(names)>1 else .5))) for i,name in enumerate(names)}
