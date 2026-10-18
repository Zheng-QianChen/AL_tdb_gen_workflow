"""Published measurements transcribed with source, units and experimental caveats."""

COFE_SOURCE = {
    'doi': '10.1016/S1359-6454(01)00337-8',
    'url': 'https://www.scribd.com/document/646097489/Fe-Co-equi-phase',
    'reference': 'Ohnuma et al. (2002), Table 1, p.384, thin-film columns',
    'extraction': 'Public full-text table; thin-film values only, not bulk/EDX columns.',
    'qualification': 'No numerical composition uncertainty given in this table; low-temperature equilibrium requires long annealing. Not an independent holdout if these data were used in fitting.',
}
COFE_ROWS = [
    # T / degC; bcc/B2 at.% Fe; fcc at.% Fe.
    [800, 27.6, 20.5], [700, 25.5, 14.9], [600, 25.3, 10.9],
    [550, 26.1, 10.9], [500, 26.3, 9.6], [450, 29.1, 9.2], [400, 29.6, 7.3],
]

COW_SOURCE = {
    'doi': '10.2320/matertrans.46.1199',
    'url': 'https://www.jstage.jst.go.jp/article/matertrans/46/6/46_6_1199/_pdf',
    'reference': 'Sato et al. (2005), Table 1, p.1201; section 4.2, pp.1201-1202',
    'extraction': 'PDF Table 1 visually checked, including column alignment and footnote.',
    'qualification': 'W-rich BCC compositions marked * by authors are unreliable due to fine mu precipitates and excluded from error statistics. chi is D019 Co3W (source database TAO); alpha-Co is FCC, not HCP. Ferromagnetic/paramagnetic labels are retained as experimental metadata, not inferred from phase names.',
}
COW_ROWS = [
    # T/K, nominal overall X(W), phases, observed at.% W, indices excluded from statistics.
    [1623, .16, ['FCC','MU'], [15.7,42.9], []],
    [1473, .16, ['FCC','MU'], [14.6,43.1], []],
    [1373, .16, ['FCC','MU'], [13.6,42.5], []],
    [1273, .16, ['FCC','TAO'], [9.1,22.5], []],
    [1183, .10, ['FCC','TAO'], [5.9,22.4], []],
    [1173, .10, ['FCC','TAO'], [2.45,23.6], []],
    [1623, .55, ['MU','BCC'], [48.5,97.6], [1]],
    [1573, .55, ['MU','BCC'], [48.3,97.9], [1]],
    [1473, .55, ['MU','BCC'], [48.5,97.7], [1]],
    [1373, .55, ['MU','BCC'], [47.6,97.7], [1]],
    [1173, .55, ['MU','BCC'], [47.1,97.3], [1]],
    # Diffusion-couple tie line: midpoint is a diagnostic overall composition, not a sample composition.
    [1183, .034, ['FCC','FCC'], [2.6,4.2], []],
]

FENI_SOURCE = {
    'doi': '10.2355/isijinternational.ISIJINT-2022-408',
    'url': 'https://www.jstage.jst.go.jp/article/isijinternational/63/3/63_ISIJINT-2022-408/_html/-char/en',
    'reference': 'Enoki et al. (2023), section 2.1, Figs. 1-2; authors recount experiments of Ohnuma et al. (2019), DOI 10.1016/j.calphad.2019.101677',
    'extraction': 'Explicit sample compositions, temperature, annealing duration and phase observations in open full-text HTML.',
    'qualification': 'Only severely deformed/recrystallized specimens are used. Undeformed specimens were not equilibrated. Qualitative phase-assemblage tests, not boundary-composition measurements.',
}

CUFE_SOURCE = {
    'doi':'10.1063/1.324336',
    'url':'https://pubs.aip.org/aip/jap/article/49/1/229/9431/The-diffusion-and-solubility-of-iron-in-copper',
    'reference':'Salje and Feller-Kniepmeier (1978), publisher abstract: EPMA, 99.999% Cu single crystals',
    'formula':'log10(C_Fe_wt_percent) = 2.951 - 3357/T_K',
    'valid_temperature_K':[923.15,1323.15],
    'qualification':'Comparison to a published regression of experimental solubility, not five independent raw measurements. Original table and uncertainty unavailable; no extrapolation.',
}


def measurements(pair):
    if pair == 'CO-FE':
        return [dict(T_K=t+273.15, X_second=(bcc+fcc)/200,
                     overall_composition_basis='diagnostic midpoint of experimental tie line',
                     expected_ordering=['ORD' if t in (450,400) else None, 'DISORD'],
                     phases=['BCC','FCC'], observed_at_pct=[bcc,fcc], exclude_indices=[], source=COFE_SOURCE)
                for t,bcc,fcc in COFE_ROWS]
    if pair == 'CO-W':
        return [dict(T_K=t,X_second=x,
                     overall_composition_basis='diagnostic tie-line midpoint' if i==11 else 'reported nominal alloy composition',
                     phases=phases,observed_at_pct=observed,exclude_indices=exclude,source=COW_SOURCE)
                for i,(t,x,phases,observed,exclude) in enumerate(COW_ROWS)]
    if pair == 'FE-NI':
        return [dict(T_K=773.15, X_second=x, phases=phases,
                     overall_composition_basis='reported nominal alloy composition',
                     observed_at_pct=None, exclude_indices=[], source=FENI_SOURCE,
                     annealing=duration, experimental_state='severely deformed, recrystallized specimen')
                for x,phases,duration in [(.076,['BCC'],'143 days'),(.115,['BCC','FCC'],'2 months')]]
    if pair == 'CU-FE':
        return [dict(T_K=t+273.15,X_second=.1,source=CUFE_SOURCE,
                     overall_composition_basis='diagnostic overall composition; compare only Cu-rich FCC solubility')
                for t in [650,750,850,950,1050]]
    raise ValueError(pair)
