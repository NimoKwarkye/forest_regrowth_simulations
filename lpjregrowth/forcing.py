"""Three controlled climate/CO2 treatments using the patched CFX reader."""
import re
from .instructions import ConfigError

DEFAULT_TREATMENTS = {
    'baseline': {'fix_climate': False, 'fix_co2': False},
    'co2_constant': {'fix_climate': False, 'fix_co2': True},
    'climate_constant': {'fix_climate': True, 'fix_co2': False},
}


def labels(experiments):
    result = {}
    for exp in experiments:
        controls = settings(exp)
        climate = 'Reference-year climate' if controls['extend_climate'] else 'Historical climate'
        co2 = 'fixed CO2' if controls['fixed_co2'] else 'historical CO2'
        result[exp['id']] = climate + ' + ' + co2
    return result



def expand(config, experiments, first_year, last_year, cut_year):
    spec = config.get('forcing_experiment')
    if spec is None:
        return experiments
    if not isinstance(spec, dict) or set(spec) - {'reference_year', 'start_year', 'management_experiment', 'treatments'}:
        raise ConfigError('forcing_experiment accepts reference_year, start_year, management_experiment, treatments')
    reference = spec.get('reference_year')
    start = spec.get('start_year', cut_year)
    if type(reference) is not int or not 1850 <= reference <= 2500:
        raise ConfigError('forcing_experiment.reference_year must be an integer in 1850..2500')
    if type(start) is not int or not first_year <= start <= last_year:
        raise ConfigError('Forcing start_year must be within the historical simulation period')
    if config.get('input_module', 'cfx') != 'cfx':
        raise ConfigError('Forcing treatments require the patched cfx input module')
    if config.get('baseline', 'baseline') != 'baseline':
        raise ConfigError('Forcing comparisons use baseline as the baseline experiment id')
    base_id = spec.get('management_experiment', 'baseline')
    matches = [e for e in experiments if e['id'] == base_id]
    if len(matches) != 1:
        raise ConfigError('management_experiment must select exactly one experiment row')
    treatments = spec.get('treatments', DEFAULT_TREATMENTS)
    if not isinstance(treatments, dict) or 'baseline' not in treatments or len(treatments) < 2:
        raise ConfigError('treatments must contain baseline and at least one comparison')
    for name, flags in treatments.items():
        if not re.fullmatch(r'[A-Za-z0-9_-]+', name):
            raise ConfigError('Treatment ids must be simple identifiers')
        if not isinstance(flags, dict) or set(flags) != {'fix_climate', 'fix_co2'} or any(type(v) is not bool for v in flags.values()):
            raise ConfigError('Each treatment requires JSON booleans fix_climate and fix_co2')
    if any(treatments['baseline'].values()):
        raise ConfigError('baseline must use fix_climate false and fix_co2 false')
    result = []
    for treatment, flags in treatments.items():
        settings = dict(extend_climate=int(flags['fix_climate']),
                        extend_climate_nyears=1, extend_climate_startyear=reference,
                        climate_recycle_from_year=start, fixed_spinup_climate=0,
                        fixed_co2=int(flags['fix_co2']), fixed_co2_year=reference,
                        fixed_co2_from_year=start, restart=0, save_state=0)
        result.append({**matches[0], 'id': treatment,
                       'forcing': dict(treatment=treatment, reference_year=reference,
                                       start_year=start, settings=settings)})
    return result


def settings(exp):
    return exp.get('forcing', {}).get('settings', {})


def check_snapshot(study, manifest):
    """Reject old executions after changing the requested treatment or management."""
    expected = next(e for e in study.experiments if e['id'] == manifest['experiment']['id'])
    if expected.get('forcing') != manifest['experiment'].get('forcing'):
        raise ConfigError('Execution forcing differs from current study; prepare new executions in a separate workspace')
    if expected.get('forcing'):
        if manifest.get('generated_management') != study.management_values(expected):
            raise ConfigError('Forcing comparison management differs from current study')
        if manifest.get('forcing_settings') != settings(expected):
            raise ConfigError('Execution forcing settings are missing or inconsistent')
